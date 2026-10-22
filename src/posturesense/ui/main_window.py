"""主窗口（M1）：视频区 + 开始/停止 + 真实 FPS/延迟显示。

线程契约（对照仓库根 README.md §4.1，推理在 QThread 执行）:
- 采集与推理在 QThread 中执行，结果经 Signal 传回 GUI 线程。
- GUI 线程**永不**调用 QThread.wait() 长阻塞 —— 停止是异步的，
  由 finished 信号驱动状态切换。
- 相机与模型只在工作线程的 finally 中释放，GUI 线程不与之竞争。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..core.inference_service import InferenceService
from ..vision.camera_manager import CameraError, CameraManager
from ..vision.pose_estimator import PoseEstimator

logger = logging.getLogger(__name__)

# 连续读帧失败预算：超过该秒数仍无有效帧才判定相机故障。
# 短暂丢帧（USB 抖动、驱动卡顿）不应终止整个监测会话。
CAMERA_FAILURE_BUDGET_SEC = 3.0

# 深色科技风配色
STYLE = """
QMainWindow, QWidget { background-color: #0B1220; color: #E2E8F0; }
QLabel#video { background-color: #111A2E; border: 1px solid #1E3A5F; border-radius: 6px; }
QLabel#metrics { font-size: 14px; color: #7DD3FC; padding: 4px 8px; }
QLabel#title { font-size: 18px; font-weight: bold; color: #F8FAFC; }
QPushButton { background-color: #0EA5E9; color: #04121F; border: none;
              padding: 8px 18px; border-radius: 6px; font-weight: 600; }
QPushButton:hover { background-color: #38BDF8; }
QPushButton:disabled { background-color: #334155; color: #94A3B8; }
QPushButton#stop { background-color: #B91C1C; color: #FEE2E2; }
QPushButton#stop:hover { background-color: #DC2626; }
QStatusBar { background-color: #0B1220; color: #94A3B8; }
"""


class InferenceWorker(QThread):
    """后台推理线程。通过 Signal 把结果送回 GUI 线程。"""

    frame_ready = Signal(object)  # dict 快照，含 QImage 与指标
    camera_failed = Signal(str)
    finished_cleanly = Signal()

    def __init__(self, service: InferenceService, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service = service
        self._stop_flag = False

    def request_stop(self) -> None:
        self._stop_flag = True

    def run(self) -> None:  # noqa: D102 - QThread 入口
        started = False
        try:
            try:
                self._service.start()
                started = True
            except Exception as exc:  # noqa: BLE001 - 任何启动失败都要上报，不能逃逸
                logger.exception("推理服务启动失败")
                self.camera_failed.emit(f"启动失败: {exc}")
                return

            first_failure_at: Optional[float] = None

            while not self._stop_flag:
                result = self._service.process_once()

                if not result.has_camera:
                    # 短暂丢帧不终止会话；超过预算才判故障
                    now = time.monotonic()
                    if first_failure_at is None:
                        first_failure_at = now
                    elif now - first_failure_at >= CAMERA_FAILURE_BUDGET_SEC:
                        self.camera_failed.emit(
                            f"相机连续 {CAMERA_FAILURE_BUDGET_SEC:.0f} 秒读帧失败"
                        )
                        break
                    continue

                first_failure_at = None
                self.frame_ready.emit(self._build_payload(result))
        except Exception as exc:  # noqa: BLE001 - 线程内不能让异常逃逸
            logger.exception("推理线程异常")
            self.camera_failed.emit(f"推理异常: {exc}")
        finally:
            # 资源只在这里释放，GUI 线程不参与
            try:
                self._service.stop()
            except Exception:  # noqa: BLE001
                logger.exception("停止推理服务时异常")
            self.finished_cleanly.emit()
            if not started:
                logger.info("工作线程退出（未成功启动）")

    @staticmethod
    def _build_payload(result) -> dict:
        """把 ProcessResult 转成可跨线程传递的 dict。"""
        qimage = None
        if result.annotated_bgr is not None:
            arr = np.ascontiguousarray(result.annotated_bgr)
            h, w = arr.shape[:2]
            rgb = arr[:, :, ::-1].copy()
            qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()

        pose = result.pose
        state = pose.state.value if pose else "error"
        valid_ratio = pose.valid_ratio if pose else 0.0

        feats = result.features
        feat_payload = {
            "head_forward": None if feats is None else feats.head_forward_ratio,
            "trunk_tilt": None if feats is None else feats.trunk_tilt_deg,
            "shoulder_tilt": None if feats is None else feats.shoulder_tilt_deg,
            "head_lateral": None if feats is None else feats.head_lateral_offset,
            "features_reliable": bool(feats is not None and feats.is_reliable),
        }

        return {
            "image": qimage,
            "fps": result.perf.fps,
            "latency_ms": result.perf.frame_latency_ms,
            "avg_latency_ms": result.perf.avg_latency_ms,
            "p95_latency_ms": result.perf.p95_latency_ms,
            "frames": result.perf.frames_processed,
            "pose_state": state,
            "valid_ratio": valid_ratio,
            "error": result.error,
            **feat_payload,
        }


class MainWindow(QMainWindow):
    """M1 主窗口。"""

    def __init__(
        self,
        camera: CameraManager,
        estimator: PoseEstimator,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("智姿 AI · 实时姿态监测 (PostureSense AI)")
        self.resize(1100, 720)
        self.setStyleSheet(STYLE)

        self._camera = camera
        self._estimator = estimator
        self._worker: Optional[InferenceWorker] = None
        self._closing = False
        self._last_error = ""

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        title = QLabel("实时姿态监测")
        title.setObjectName("title")
        layout.addWidget(title)

        self.video_label = QLabel("点击「开始监测」以启动摄像头")
        self.video_label.setObjectName("video")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 360)
        layout.addWidget(self.video_label, stretch=1)

        metrics_row = QHBoxLayout()
        self.lbl_fps = QLabel("FPS: —")
        self.lbl_fps.setObjectName("metrics")
        self.lbl_latency = QLabel("单帧延迟: —")
        self.lbl_latency.setObjectName("metrics")
        self.lbl_valid = QLabel("关键点有效率: —")
        self.lbl_valid.setObjectName("metrics")
        self.lbl_state = QLabel("姿态状态: 未启动")
        self.lbl_state.setObjectName("metrics")
        for w in (self.lbl_fps, self.lbl_latency, self.lbl_valid, self.lbl_state):
            metrics_row.addWidget(w)
        metrics_row.addStretch(1)
        layout.addLayout(metrics_row)

        # 姿态特征行（全部来自几何计算，无法判断时显示 —）
        feat_row = QHBoxLayout()
        self.lbl_trunk = QLabel("躯干倾角: —")
        self.lbl_trunk.setObjectName("metrics")
        self.lbl_shoulder = QLabel("肩部倾角: —")
        self.lbl_shoulder.setObjectName("metrics")
        self.lbl_head_fwd = QLabel("头部前倾: —")
        self.lbl_head_fwd.setObjectName("metrics")
        self.lbl_head_lat = QLabel("头部偏移: —")
        self.lbl_head_lat.setObjectName("metrics")
        for w in (self.lbl_trunk, self.lbl_shoulder, self.lbl_head_fwd, self.lbl_head_lat):
            feat_row.addWidget(w)
        feat_row.addStretch(1)
        layout.addLayout(feat_row)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("开始监测")
        self.btn_stop = QPushButton("停止监测")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._last_error = ""
        self._reset_metrics()
        self.statusBar().showMessage("正在启动摄像头…")

        service = InferenceService(self._camera, self._estimator, draw_skeleton=True)
        worker = InferenceWorker(service, parent=self)
        worker.frame_ready.connect(self._on_frame)
        worker.camera_failed.connect(self._on_camera_failed)
        worker.finished_cleanly.connect(self._on_worker_finished)
        # 线程结束后销毁 worker，避免多次启停堆积 QThread
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_stop(self) -> None:
        """异步停止：不阻塞 GUI 线程。"""
        self.btn_stop.setEnabled(False)
        self.statusBar().showMessage("正在停止…")
        if self._worker is not None:
            self._worker.request_stop()

    def _on_frame(self, payload: dict) -> None:
        img: Optional[QImage] = payload.get("image")
        if img is not None:
            pix = QPixmap.fromImage(img)
            self.video_label.setPixmap(
                pix.scaled(
                    self.video_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )

        self.lbl_fps.setText(f"FPS: {payload.get('fps', 0.0):.1f}")
        self.lbl_latency.setText(f"单帧延迟: {payload.get('latency_ms', 0.0):.1f} ms")
        self.lbl_valid.setText(f"关键点有效率: {payload.get('valid_ratio', 0.0) * 100:.0f}%")
        self.lbl_state.setText(f"姿态状态: {self._state_text(payload.get('pose_state', 'error'))}")

        # 姿态特征：None → "—"（无法判断），不显示 0 等伪造值
        self.lbl_trunk.setText(f"躯干倾角: {self._fmt_deg(payload.get('trunk_tilt'))}")
        self.lbl_shoulder.setText(f"肩部倾角: {self._fmt_deg(payload.get('shoulder_tilt'))}")
        self.lbl_head_fwd.setText(f"头部前倾: {self._fmt_ratio(payload.get('head_forward'))}")
        self.lbl_head_lat.setText(f"头部偏移: {self._fmt_ratio(payload.get('head_lateral'))}")

        err = payload.get("error") or ""
        if err:
            self.statusBar().showMessage(f"检测异常: {err}")

    def _on_camera_failed(self, message: str) -> None:
        self._last_error = message
        self.statusBar().showMessage(f"错误: {message}")
        self._reset_metrics(state_text="姿态状态: 已故障（无数据）")
        if not self._closing:
            QMessageBox.warning(self, "摄像头错误", message)

    def _on_worker_finished(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._worker = None
        if self._last_error:
            # 不用"已停止"覆盖错误信息
            self.statusBar().showMessage(f"已停止 | 上次错误: {self._last_error}")
            self._reset_metrics(state_text="姿态状态: 已故障（无数据）")
        else:
            self.statusBar().showMessage("已停止，摄像头资源已释放")
            self._reset_metrics(state_text="姿态状态: 已停止")

        if self._closing:
            self._finalize_close()

    def _reset_metrics(self, state_text: str = "姿态状态: 未启动") -> None:
        """停止/故障后清空指标，避免残留假读数。"""
        self.lbl_fps.setText("FPS: —")
        self.lbl_latency.setText("单帧延迟: —")
        self.lbl_valid.setText("关键点有效率: —")
        self.lbl_state.setText(state_text)
        self.lbl_trunk.setText("躯干倾角: —")
        self.lbl_shoulder.setText("肩部倾角: —")
        self.lbl_head_fwd.setText("头部前倾: —")
        self.lbl_head_lat.setText("头部偏移: —")

    @staticmethod
    def _fmt_deg(value) -> str:
        return "—" if value is None else f"{value:.1f}°"

    @staticmethod
    def _fmt_ratio(value) -> str:
        return "—" if value is None else f"{value:.3f}"

    @staticmethod
    def _state_text(state: str) -> str:
        # 红线：关键点缺失/质量不足 = 无法判断，不是姿态异常
        return {
            "ok": "已检测到人体",
            "no_person": "未检测到人体",
            "low_visibility": "关键点质量不足（无法判断）",
            "error": "检测异常",
        }.get(state, state)

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        worker = self._worker
        if worker is not None and worker.isRunning():
            # 不在 GUI 线程等待：先请求停止，等 finished_cleanly 再真正关窗
            self._closing = True
            worker.request_stop()
            event.ignore()
            self.statusBar().showMessage("正在停止监测…")
            return

        self._finalize_close()
        event.accept()

    def _finalize_close(self) -> None:
        """真正释放资源并关窗。只在工作线程已退出后调用。"""
        self._camera.release()
        self._estimator.close()
        self._closing = False
        self.close()
