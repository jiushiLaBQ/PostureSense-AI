"""应用壳：左侧导航 + 右侧内容区 + 真实业务接线。

线程契约:
- 采集/推理在 QThread（InferenceWorker），结果经 Signal 回 GUI 线程。
- 停止异步，GUI 线程不 wait() 长阻塞。
- 相机与模型只在工作线程的 finally / 窗口最终关闭时释放。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.baseline_manager import (
    BaselineError,
    BaselineProfile,
    compute_deviation,
    profile_from_row,
)
from ..core.inference_service import InferenceService
from ..core.reminder_engine import ReminderConfig, ReminderEngine
from ..core.storage import Database
from ..core.temporal_analyzer import (
    AnalyzerConfig,
    FrameSample,
    PostureState,
    TemporalAnalyzer,
)
from ..vision.camera_manager import CameraManager
from ..vision.pose_estimator import PoseEstimator
from .pages import (
    AnalyticsPage,
    CalibrationPage,
    HistoryPage,
    HomePage,
    LabPage,
    MonitorPage,
    PrivacyPage,
    RemindersPage,
)
from .theme import MAIN_STYLESHEET, PAGE_TITLES

logger = logging.getLogger(__name__)

CAMERA_FAILURE_BUDGET_SEC = 3.0

NAV_ORDER = ["home", "monitor", "calibration", "reminders", "history", "analytics", "lab", "privacy"]


class InferenceWorker(QThread):
    """后台推理线程。"""

    frame_ready = Signal(object)
    camera_failed = Signal(str)
    finished_cleanly = Signal()

    def __init__(
        self,
        service: InferenceService,
        analyzer: TemporalAnalyzer,
        baseline: Optional["BaselineProfile"] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._analyzer = analyzer
        self._baseline = baseline
        self._stop_flag = False

    def request_stop(self) -> None:
        self._stop_flag = True

    def run(self) -> None:  # noqa: D102
        try:
            try:
                self._service.start()
            except Exception as exc:  # noqa: BLE001
                logger.exception("启动失败")
                self.camera_failed.emit(f"启动失败: {exc}")
                return

            first_fail: Optional[float] = None
            while not self._stop_flag:
                result = self._service.process_once()
                if not result.has_camera:
                    now = time.monotonic()
                    if first_fail is None:
                        first_fail = now
                    elif now - first_fail >= CAMERA_FAILURE_BUDGET_SEC:
                        self.camera_failed.emit("相机连续 3 秒读帧失败")
                        break
                    continue
                first_fail = None

                payload = self._build_payload(result)
                self.frame_ready.emit(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("推理线程异常")
            self.camera_failed.emit(f"推理异常: {exc}")
        finally:
            try:
                self._service.stop()
            except Exception:  # noqa: BLE001
                logger.exception("停止服务异常")
            self.finished_cleanly.emit()

    def _build_payload(self, result) -> dict:
        qimage = None
        if result.annotated_bgr is not None:
            arr = np.ascontiguousarray(result.annotated_bgr)
            h, w = arr.shape[:2]
            rgb = arr[:, :, ::-1].copy()
            qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()

        pose = result.pose
        feats = result.features

        # 时序状态机推进（真实判定，非装饰）
        # 注意：桌面摄像头常拍不到髋部（trunk=None），此时肩/头特征仍可用，
        # 组合偏离量若能算出就不判 UNKNOWN —— 否则状态机会永远停在"无法判断"。
        # 已校准 → z 分数（方案 C）；无基线 → 绝对几何（方案 B，诚实降级）。
        if feats is not None:
            if self._baseline is not None:
                deviation = compute_deviation(feats, self._baseline).composite
            else:
                deviation = _composite_abs(feats)
        else:
            deviation = None
        snap = self._analyzer.update(
            FrameSample(
                timestamp=result.frame.timestamp if result.frame else time.perf_counter(),
                deviation=deviation,
                valid_ratio=pose.valid_ratio if pose else 0.0,
            )
        )

        return {
            "image": qimage,
            "fps": result.perf.fps,
            "latency_ms": result.perf.frame_latency_ms,
            "frames": result.perf.frames_processed,
            "pose_state": pose.state.value if pose else "error",
            "valid_ratio": pose.valid_ratio if pose else 0.0,
            "error": result.error,
            "trunk_tilt": None if feats is None else feats.trunk_tilt_deg,
            "shoulder_tilt": None if feats is None else feats.shoulder_tilt_deg,
            "head_forward": None if feats is None else feats.head_forward_ratio,
            "head_lateral": None if feats is None else feats.head_lateral_offset,
            "features": feats,
            "posture_state": snap.state.value,
            "smoothed_deviation": snap.smoothed_deviation,
            "should_remind": snap.should_remind,
        }


def _composite_abs(feats) -> Optional[float]:
    """无基线时的绝对几何偏离量（与 strategies._abs_geometry_deviation 同定义）。"""
    from ..core.strategies import _abs_geometry_deviation
    return _abs_geometry_deviation(feats)


class AppShell(QMainWindow):
    """主窗口壳。"""

    def __init__(
        self,
        camera: CameraManager,
        estimator: PoseEstimator,
        db: Database,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("智姿 AI · PostureSense AI")
        self.resize(1280, 800)
        self.setStyleSheet(MAIN_STYLESHEET)

        self._camera = camera
        self._estimator = estimator
        self.db = db
        self.reminder = ReminderEngine(ReminderConfig())
        self.analyzer_cfg = AnalyzerConfig()
        self._analyzer = TemporalAnalyzer(self.analyzer_cfg)
        self._worker: Optional[InferenceWorker] = None
        self._closing = False
        self._last_error = ""
        self._session_id: Optional[str] = None
        self._session_start_ms = 0
        self._event_count = 0
        self._active_baseline: Optional[BaselineProfile] = None

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 导航
        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setFixedWidth(200)
        for key in NAV_ORDER:
            title = PAGE_TITLES[key][0]
            self.nav.addItem(QListWidgetItem(title))
        layout.addWidget(self.nav)

        # 内容
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)

        self.pages = {
            "home": HomePage(self.db, self.navigate),
            "monitor": MonitorPage(self._start_monitoring, self._stop_monitoring),
            "calibration": CalibrationPage(self.db),
            "reminders": RemindersPage(self.reminder, self.analyzer_cfg),
            "history": HistoryPage(self.db),
            "analytics": AnalyticsPage(self.db),
            "lab": LabPage(),
            "privacy": PrivacyPage(self.db),
        }
        for key in NAV_ORDER:
            self.stack.addWidget(self.pages[key])

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.setStatusBar(self.statusBar() if hasattr(self, "statusBar") else None)
        self.statusBar().showMessage("就绪")

    def navigate(self, key: str) -> None:
        if key in NAV_ORDER:
            self.nav.setCurrentRow(NAV_ORDER.index(key))

    def current_key(self) -> str:
        return NAV_ORDER[self.stack.currentIndex()]

    # ------------------------------------------------------------------
    # 监测控制
    # ------------------------------------------------------------------
    def _load_active_baseline(self) -> Optional[BaselineProfile]:
        """读取最新保存的个人基线（created_at 最新优先）。无基线或损坏则返回 None。"""
        rows = self.db.list_profiles()
        if not rows:
            return None
        try:
            return profile_from_row(rows[0])
        except BaselineError:
            logger.exception("基线反序列化失败，回退默认规则")
            return None

    def _start_monitoring(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        self._last_error = ""
        self._analyzer = TemporalAnalyzer(self.analyzer_cfg)
        self._session_start_ms = int(time.time() * 1000)
        self._session_id = f"sess-{self._session_start_ms}"
        self._event_count = 0

        # 会话开始时读取最新基线；本次会话内固定用它（不做热切换）
        self._active_baseline = self._load_active_baseline()
        self.pages["monitor"].set_baseline_mode(
            self._active_baseline.name if self._active_baseline else None
        )

        # 会话落库
        self.db.insert_session({
            "session_id": self._session_id,
            "start_ts": self._session_start_ms,
            "input_mode": "camera",
        })

        service = InferenceService(self._camera, self._estimator, draw_skeleton=True)
        worker = InferenceWorker(
            service, self._analyzer, baseline=self._active_baseline, parent=self
        )
        worker.frame_ready.connect(self._on_frame)
        worker.camera_failed.connect(self._on_camera_failed)
        worker.finished_cleanly.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()
        self.statusBar().showMessage("监测中…")

    def _stop_monitoring(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self.statusBar().showMessage("正在停止…")

    def _on_frame(self, payload: dict) -> None:
        page = self.pages["monitor"]
        page.on_frame(payload)

        # 校准页采集
        feats = payload.get("features")
        self.pages["calibration"].on_features(feats)

        # 提醒
        if payload.get("should_remind"):
            rec = self.reminder.try_remind(
                f"evt-{self._event_count}", now=time.time()
            )
            if rec.delivered:
                self.statusBar().showMessage("⚠ 姿态提醒：请注意坐姿")
            self._event_count += 1

    def _on_camera_failed(self, message: str) -> None:
        self._last_error = message
        self.statusBar().showMessage(f"错误: {message}")
        self.pages["monitor"].set_running(False)
        if not self._closing:
            QMessageBox.warning(self, "摄像头错误", message)

    def _on_worker_finished(self) -> None:
        self.pages["monitor"].set_running(False)
        self._worker = None

        # 会话收尾
        if self._session_id:
            end_ms = int(time.time() * 1000)
            duration = max(0, end_ms - self._session_start_ms)
            # 简化：全部计入有效时长；精确划分需逐帧累加（M9 完善）
            self.db.finish_session(
                self._session_id,
                end_ts=end_ms,
                duration_ms=duration,
                valid_ms=duration,
                paused_ms=0,
                status="failed" if self._last_error else "completed",
            )
            self._session_id = None

        # 刷新历史/分析
        self.pages["history"].refresh()
        self.pages["analytics"].refresh()

        if self._last_error:
            self.statusBar().showMessage(f"已停止 | 上次错误: {self._last_error}")
        else:
            self.statusBar().showMessage("已停止，摄像头资源已释放")

        if self._closing:
            self._finalize_close()

    # ------------------------------------------------------------------
    # 页面刷新
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_all()

    def _refresh_all(self) -> None:
        self.pages["home"].refresh()
        self.pages["calibration"].refresh()
        self.pages["history"].refresh()
        self.pages["analytics"].refresh()
        self.pages["privacy"].refresh()
        # 未在监测中时，基线标签跟随库中最新基线（监测中则由 _start_monitoring 锁定）
        if self._worker is None:
            baseline = self._load_active_baseline()
            self.pages["monitor"].set_baseline_mode(
                baseline.name if baseline else None
            )

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        worker = self._worker
        if worker is not None and worker.isRunning():
            self._closing = True
            worker.request_stop()
            event.ignore()
            self.statusBar().showMessage("正在停止监测…")
            return
        self._finalize_close()
        event.accept()

    def _finalize_close(self) -> None:
        self._camera.release()
        self._estimator.close()
        self.db.close()
        self._closing = False
        self.close()
