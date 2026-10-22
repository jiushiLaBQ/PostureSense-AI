"""8 个页面。每个页面连真实业务或明确空状态。

红线: 不使用装饰性假数字；空数据库显示空状态。
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.analytics import AnalyticsService
from ..core.baseline_manager import CalibrationCollector
from ..core.csv_export import export_all
from ..core.reminder_engine import ReminderConfig, ReminderEngine
from ..core.storage import Database
from ..core.strategies import STRATEGY_REGISTRY
from ..core.temporal_analyzer import AnalyzerConfig
from .widgets import (
    EmptyState,
    StatCard,
    fill_table,
    format_ms,
    format_ratio,
    make_table,
)

logger = logging.getLogger(__name__)


def _scrollable(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(content)
    return area


def _title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("pageTitle")
    return lab


def _subtitle(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("pageSubtitle")
    lab.setWordWrap(True)
    return lab


# ===========================================================================
# 1. 产品首页
# ===========================================================================
class HomePage(QWidget):
    """首页：今日概览（真读库）+ 快速入口。"""

    def __init__(self, db: Database, nav_callback, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.nav_callback = nav_callback
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(16)

        lay.addWidget(_title("智姿 AI"))
        lay.addWidget(_subtitle("人体工学智能感知与自适应辅助系统 · 本地离线 · 非医学诊断"))

        # 统计卡
        cards = QHBoxLayout()
        self.card_sessions = StatCard("累计监测次数")
        self.card_time = StatCard("累计监测时长")
        self.card_valid = StatCard("有效检测占比")
        self.card_events = StatCard("姿态事件数")
        for c in (self.card_sessions, self.card_time, self.card_valid, self.card_events):
            cards.addWidget(c)
        cards.addStretch(1)
        lay.addLayout(cards)

        # 快速入口
        actions = QHBoxLayout()
        for label, target in (
            ("▶ 开始实时监测", "monitor"),
            ("◈ 进行姿态校准", "calibration"),
            ("▦ 查看历史记录", "history"),
            ("◔ 数据分析中心", "analytics"),
        ):
            btn = QPushButton(label)
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda _=False, t=target: self.nav_callback(t))
            actions.addWidget(btn)
        actions.addStretch(1)
        lay.addLayout(actions)

        # 免责声明
        disc = QFrame()
        disc.setObjectName("card")
        dl = QVBoxLayout(disc)
        warn = QLabel(
            "使用边界：本软件仅用于日常姿态观察与使用习惯辅助，"
            "不提供医学诊断，不声称预防或治疗颈椎疾病。"
            "摄像头角度、遮挡与光照会影响结果。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #94A3B8; font-size: 13px;")
        dl.addWidget(warn)
        lay.addWidget(disc)

        lay.addStretch(1)
        outer.addWidget(_scrollable(content))

    def refresh(self) -> None:
        svc = AnalyticsService(self.db)
        t = svc.totals()
        if t.is_empty:
            self.card_sessions.set_value("0")
            self.card_time.set_value("—")
            self.card_valid.set_value("—")
            self.card_events.set_value("0")
        else:
            self.card_sessions.set_value(str(t.session_count))
            self.card_time.set_value(format_ms(t.total_monitor_ms))
            self.card_valid.set_value(format_ratio(t.valid_ratio))
            self.card_events.set_value(str(t.event_count))


# ===========================================================================
# 2. 实时姿态监测
# ===========================================================================
class MonitorPage(QWidget):
    """实时监测：视频 + 指标 + 开始/停止。

    真实相机与推理由外部 InferenceWorker 驱动，本页只负责展示与控制。
    """

    def __init__(self, start_cb, stop_cb, parent=None) -> None:
        super().__init__(parent)
        self.start_cb = start_cb
        self.stop_cb = stop_cb
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.addWidget(_title("实时姿态监测"))
        outer.addWidget(_subtitle(
            "关键点缺失或质量不足时显示「无法判断」，不判为姿态异常。"
            "所有指标为真实测量值。"
        ))

        self.video_label = QLabel("点击「开始监测」以启动摄像头")
        self.video_label.setObjectName("video")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 320)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self.video_label, stretch=1)

        # 指标
        metrics = QHBoxLayout()
        self.lbl_fps = QLabel("FPS: —")
        self.lbl_fps.setObjectName("metrics")
        self.lbl_lat = QLabel("单帧延迟: —")
        self.lbl_lat.setObjectName("metrics")
        self.lbl_valid = QLabel("关键点有效率: —")
        self.lbl_valid.setObjectName("metrics")
        self.lbl_state = QLabel("姿态状态: 未启动")
        self.lbl_state.setObjectName("metrics")
        for w in (self.lbl_fps, self.lbl_lat, self.lbl_valid, self.lbl_state):
            metrics.addWidget(w)
        metrics.addStretch(1)
        outer.addLayout(metrics)

        feats = QHBoxLayout()
        self.lbl_trunk = QLabel("躯干倾角: —")
        self.lbl_trunk.setObjectName("metrics")
        self.lbl_shoulder = QLabel("肩部倾角: —")
        self.lbl_shoulder.setObjectName("metrics")
        self.lbl_head = QLabel("头部前倾: —")
        self.lbl_head.setObjectName("metrics")
        self.lbl_baseline = QLabel("基线模式: 默认规则（未校准）")
        self.lbl_baseline.setObjectName("metrics")
        for w in (self.lbl_trunk, self.lbl_shoulder, self.lbl_head, self.lbl_baseline):
            feats.addWidget(w)
        feats.addStretch(1)
        outer.addLayout(feats)

        btns = QHBoxLayout()
        self.btn_start = QPushButton("开始监测")
        self.btn_stop = QPushButton("停止监测")
        self.btn_stop.setObjectName("stopBtn")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        btns.addStretch(1)
        outer.addLayout(btns)

    def _on_start(self) -> None:
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.start_cb()

    def _on_stop(self) -> None:
        self.btn_stop.setEnabled(False)
        self.stop_cb()

    def set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        if not running:
            self._reset_metrics()

    def _reset_metrics(self) -> None:
        self.lbl_fps.setText("FPS: —")
        self.lbl_lat.setText("单帧延迟: —")
        self.lbl_valid.setText("关键点有效率: —")
        self.lbl_state.setText("姿态状态: 已停止")
        self.lbl_trunk.setText("躯干倾角: —")
        self.lbl_shoulder.setText("肩部倾角: —")
        self.lbl_head.setText("头部前倾: —")

    def set_baseline_mode(self, name: Optional[str]) -> None:
        if name:
            self.lbl_baseline.setText(f"基线模式: 个性化「{name}」")
        else:
            self.lbl_baseline.setText("基线模式: 默认规则（未校准）")

    def on_frame(self, payload: dict) -> None:
        from PySide6.QtGui import QPixmap
        img = payload.get("image")
        if img is not None:
            pix = QPixmap.fromImage(img)
            self.video_label.setPixmap(
                pix.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.lbl_fps.setText(f"FPS: {payload.get('fps', 0.0):.1f}")
        self.lbl_lat.setText(f"单帧延迟: {payload.get('latency_ms', 0.0):.1f} ms")
        self.lbl_valid.setText(f"关键点有效率: {payload.get('valid_ratio', 0.0) * 100:.0f}%")
        state = payload.get("pose_state", "error")
        self.lbl_state.setText(f"姿态状态: {self._state_text(state)}")
        self.lbl_trunk.setText(f"躯干倾角: {self._deg(payload.get('trunk_tilt'))}")
        self.lbl_shoulder.setText(f"肩部倾角: {self._deg(payload.get('shoulder_tilt'))}")
        self.lbl_head.setText(f"头部前倾: {self._rat(payload.get('head_forward'))}")

    @staticmethod
    def _deg(v) -> str:
        return "—" if v is None else f"{v:.1f}°"

    @staticmethod
    def _rat(v) -> str:
        return "—" if v is None else f"{v:.3f}"

    @staticmethod
    def _state_text(state: str) -> str:
        return {
            "ok": "已检测到人体",
            "no_person": "未检测到人体",
            "low_visibility": "关键点质量不足（无法判断）",
            "error": "检测异常",
        }.get(state, state)


# ===========================================================================
# 3. 个性化姿态校准
# ===========================================================================
class CalibrationPage(QWidget):
    """校准页：采集 → 统计 → 保存。真实特征驱动。"""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.collector = CalibrationCollector(min_samples=30)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)

        lay.addWidget(_title("个性化姿态校准"))
        lay.addWidget(_subtitle(
            "请调整摄像头位置，使头部、肩部和躯干尽可能清晰可见。"
            "然后保持自然、舒适的坐姿。"
        ))

        guide = QFrame()
        guide.setObjectName("card")
        gl = QVBoxLayout(guide)
        gl.addWidget(QLabel(
            "1. 坐正，目视屏幕\n"
            "2. 双肩放松、自然平放\n"
            "3. 保持 30 秒以上\n"
            "4. 系统自动过滤质量差的样本"
        ))
        lay.addWidget(guide)

        # 进度
        self.lbl_progress = QLabel("有效样本: 0 / 30")
        self.lbl_progress.setObjectName("metrics")
        lay.addWidget(self.lbl_progress)

        self.lbl_stats = QLabel("尚未采集到数据")
        self.lbl_stats.setObjectName("metrics")
        self.lbl_stats.setWordWrap(True)
        lay.addWidget(self.lbl_stats)

        row = QHBoxLayout()
        self.btn_start = QPushButton("开始采集")
        self.btn_finish = QPushButton("计算并保存基线")
        self.btn_finish.setEnabled(False)
        self.btn_reset = QPushButton("重新开始")
        self.btn_reset.setObjectName("ghost")
        self.btn_start.clicked.connect(self._on_start)
        self.btn_finish.clicked.connect(self._on_finish)
        self.btn_reset.clicked.connect(self._on_reset)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_finish)
        row.addWidget(self.btn_reset)
        row.addStretch(1)
        lay.addLayout(row)

        # 已保存基线列表
        lay.addWidget(QLabel("已保存的基线"))
        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(160)
        lay.addWidget(self.profile_list)

        self._collecting = False
        lay.addStretch(1)
        outer.addWidget(_scrollable(content))
        self.refresh()

    def _on_start(self) -> None:
        self._collecting = True
        self.collector = CalibrationCollector(min_samples=30)
        self.btn_start.setEnabled(False)
        self.btn_finish.setEnabled(True)
        self.lbl_progress.setText("有效样本: 0 / 30（采集中…）")

    def _on_reset(self) -> None:
        self._collecting = False
        self.collector = CalibrationCollector(min_samples=30)
        self.btn_start.setEnabled(True)
        self.btn_finish.setEnabled(False)
        self.lbl_progress.setText("有效样本: 0 / 30")
        self.lbl_stats.setText("尚未采集到数据")

    def on_features(self, features) -> None:
        """由主窗口在每帧推理后调用。"""
        if not self._collecting:
            return
        self.collector.add(features)
        n = self.collector.valid_frames
        self.lbl_progress.setText(f"有效样本: {n} / 30（采集中…）")

    def _on_finish(self) -> None:
        self._collecting = False
        try:
            profile = self.collector.compute(name=f"基线-{len(self.db.list_profiles()) + 1}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "校准失败", str(exc))
            self.btn_finish.setEnabled(False)
            return

        import json
        stats_json = json.dumps(
            {
                k: {
                    "count": v.count, "mean": v.mean, "median": v.median,
                    "std": v.std, "min": v.min_value, "max": v.max_value,
                }
                for k, v in profile.stats.items()
            },
            ensure_ascii=False,
        )
        self.db.insert_profile({
            "profile_id": profile.profile_id,
            "name": profile.name,
            "created_at": int(profile.created_at * 1000),
            "sample_count": profile.sample_count,
            "stats_json": stats_json,
        })

        lines = [f"已保存「{profile.name}」  样本数 {profile.sample_count}",
                 "下次开始监测时将自动启用该基线。"]
        for k, v in profile.stats.items():
            if v.is_available:
                lines.append(f"  {k}: mean={v.mean:.3f} std={v.std:.3f} median={v.median:.3f}")
        self.lbl_stats.setText("\n".join(lines))
        self.btn_finish.setEnabled(False)
        self.refresh()

    def refresh(self) -> None:
        self.profile_list.clear()
        for p in self.db.list_profiles():
            item = QListWidgetItem(
                f"{p['name']}  ·  样本 {p['sample_count']}  ·  ID {p['profile_id']}"
            )
            self.profile_list.addItem(item)


# ===========================================================================
# 4. 智能提醒设置
# ===========================================================================
class RemindersPage(QWidget):
    """提醒参数配置。真实绑定 ReminderConfig / AnalyzerConfig。"""

    def __init__(self, reminder: ReminderEngine, analyzer_cfg: AnalyzerConfig, parent=None) -> None:
        super().__init__(parent)
        self.reminder = reminder
        self.analyzer_cfg = analyzer_cfg
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)

        lay.addWidget(_title("智能提醒设置"))
        lay.addWidget(_subtitle(
            "提醒温和非强制，可忽略、延后或标记误报。"
            "参数默认值为初值，建议通过算法实验室实测后调整。"
        ))

        # 姿态判定
        g1 = QGroupBox("姿态判定参数")
        f1 = QFormLayout(g1)
        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.1, 20.0)
        self.spin_threshold.setSingleStep(0.1)
        self.spin_threshold.setValue(self.analyzer_cfg.deviation_threshold)
        self.spin_sustain = QDoubleSpinBox()
        self.spin_sustain.setRange(1.0, 300.0)
        self.spin_sustain.setValue(self.analyzer_cfg.sustain_sec)
        self.spin_recover = QDoubleSpinBox()
        self.spin_recover.setRange(1.0, 300.0)
        self.spin_recover.setValue(self.analyzer_cfg.recover_sec)
        self.spin_valid = QDoubleSpinBox()
        self.spin_valid.setRange(0.0, 1.0)
        self.spin_valid.setSingleStep(0.05)
        self.spin_valid.setValue(self.analyzer_cfg.min_valid_ratio)
        self.spin_window = QSpinBox()
        self.spin_window.setRange(1, 300)
        self.spin_window.setValue(self.analyzer_cfg.window_size)

        f1.addRow("偏离阈值", self.spin_threshold)
        f1.addRow("连续异常判定时间 (秒)", self.spin_sustain)
        f1.addRow("连续正常恢复时间 (秒)", self.spin_recover)
        f1.addRow("关键点最低有效率", self.spin_valid)
        f1.addRow("滑动窗口 (帧)", self.spin_window)
        lay.addWidget(g1)

        # 提醒行为
        g2 = QGroupBox("提醒行为")
        f2 = QFormLayout(g2)
        self.spin_cooldown = QDoubleSpinBox()
        self.spin_cooldown.setRange(10.0, 3600.0)
        self.spin_cooldown.setValue(self.reminder.config.cooldown_sec)
        self.spin_snooze = QDoubleSpinBox()
        self.spin_snooze.setRange(10.0, 1800.0)
        self.spin_snooze.setValue(self.reminder.config.snooze_sec)
        self.cmb_sound = QComboBox()
        self.cmb_sound.addItems(["开启", "关闭"])
        self.cmb_notify = QComboBox()
        self.cmb_notify.addItems(["开启", "关闭"])
        f2.addRow("提醒冷却 (秒)", self.spin_cooldown)
        f2.addRow("延后时长 (秒)", self.spin_snooze)
        f2.addRow("声音提醒", self.cmb_sound)
        f2.addRow("桌面通知", self.cmb_notify)
        lay.addWidget(g2)

        row = QHBoxLayout()
        btn_apply = QPushButton("应用设置")
        btn_apply.clicked.connect(self._apply)
        btn_mute = QPushButton("静音 10 分钟")
        btn_mute.setObjectName("ghost")
        btn_mute.clicked.connect(self._mute)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("metrics")
        row.addWidget(btn_apply)
        row.addWidget(btn_mute)
        row.addWidget(self.lbl_status)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addStretch(1)
        outer.addWidget(_scrollable(content))

    def _apply(self) -> None:
        self.analyzer_cfg.deviation_threshold = self.spin_threshold.value()
        self.analyzer_cfg.sustain_sec = self.spin_sustain.value()
        self.analyzer_cfg.recover_sec = self.spin_recover.value()
        self.analyzer_cfg.min_valid_ratio = self.spin_valid.value()
        self.analyzer_cfg.window_size = self.spin_window.value()

        self.reminder.config.cooldown_sec = self.spin_cooldown.value()
        self.reminder.config.snooze_sec = self.spin_snooze.value()
        self.reminder.config.sound_enabled = self.cmb_sound.currentText() == "开启"
        self.reminder.config.desktop_notification = self.cmb_notify.currentText() == "开启"

        self.lbl_status.setText("✓ 设置已应用")

    def _mute(self) -> None:
        self.reminder.mute(600.0)
        self.lbl_status.setText("✓ 已静音 10 分钟")


# ===========================================================================
# 5. 会话记录与历史回顾
# ===========================================================================
class HistoryPage(QWidget):
    """历史：真实读 SQLite。空库显示空状态。"""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(12)

        lay.addWidget(_title("会话记录与历史回顾"))
        lay.addWidget(_subtitle(
            "监测时长 / 有效检测时长 / 暂停时长 分开记录，不混算。"
        ))

        row = QHBoxLayout()
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("ghost")
        btn_refresh.clicked.connect(self.refresh)
        btn_delete = QPushButton("删除选中会话")
        btn_delete.setObjectName("stopBtn")
        btn_delete.clicked.connect(self._delete_selected)
        btn_clear = QPushButton("清空全部历史")
        btn_clear.setObjectName("stopBtn")
        btn_clear.clicked.connect(self._clear_all)
        row.addWidget(btn_refresh)
        row.addWidget(btn_delete)
        row.addWidget(btn_clear)
        row.addStretch(1)
        lay.addLayout(row)

        self.table = make_table([
            "会话 ID", "开始时间", "输入", "监测时长", "有效时长", "暂停时长", "事件数", "状态",
        ])
        lay.addWidget(self.table)

        self.empty = EmptyState(
            "暂无会话记录",
            "点击左侧「实时姿态监测」开始第一次监测后，这里会显示真实的历史数据。",
        )
        lay.addWidget(self.empty)

        lay.addWidget(QLabel("会话内姿态事件时间线"))
        self.event_table = make_table([
            "事件 ID", "开始 (s)", "时长 (s)", "类型", "最大偏离", "已提醒",
        ])
        lay.addWidget(self.event_table)

        self.table.itemSelectionChanged.connect(self._on_select)
        lay.addStretch(1)
        outer.addWidget(_scrollable(content))

    def refresh(self) -> None:
        rows = []
        for s in self.db.list_sessions(limit=200):
            evs = self.db.list_events(s["session_id"])
            rows.append([
                s["session_id"],
                str(s["start_ts"]),
                s["input_mode"],
                format_ms(s["duration_ms"]),
                format_ms(s["valid_ms"]),
                format_ms(s["paused_ms"]),
                str(len(evs)),
                s["status"],
            ])
        from .widgets import fill_table as _ft
        _ft(self.table, rows)
        self.empty.setVisible(len(rows) == 0)
        self.table.setVisible(len(rows) > 0)

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        sid = items[0].text()
        evs = self.db.list_events(sid)
        start = self.db.get_session(sid)
        base = int(start["start_ts"]) if start else 0
        rows = []
        for e in evs:
            rows.append([
                e["event_id"],
                f"{(int(e['start_ts']) - base) / 1000:.1f}",
                f"{int(e.get('duration_ms') or 0) / 1000:.1f}",
                e["event_type"],
                f"{e['max_deviation']:.2f}" if e.get("max_deviation") is not None else "—",
                "是" if e.get("was_reminded") else "否",
            ])
        from .widgets import fill_table as _ft
        _ft(self.event_table, rows)

    def _delete_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            QMessageBox.information(self, "提示", "请先选择要删除的会话")
            return
        sid = items[0].text()
        if QMessageBox.question(self, "确认", f"删除会话 {sid} 及其全部事件？") != QMessageBox.Yes:
            return
        self.db.delete_session(sid)
        self.refresh()

    def _clear_all(self) -> None:
        if QMessageBox.question(self, "确认", "清空全部历史数据？此操作不可恢复。") != QMessageBox.Yes:
            return
        self.db.delete_user_data()
        self.refresh()


# ===========================================================================
# 6. 数据分析中心
# ===========================================================================
class AnalyticsPage(QWidget):
    """数据分析：真读库 + 空态。"""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)

        lay.addWidget(_title("数据分析中心"))
        lay.addWidget(_subtitle(
            "所有数字来自本地 SQLite 真实数据。空数据库显示空状态，不填充虚构统计。"
        ))

        cards = QHBoxLayout()
        self.c_monitor = StatCard("累计监测时长")
        self.c_valid = StatCard("有效检测时长")
        self.c_paused = StatCard("暂停/无效时长")
        self.c_event = StatCard("事件总时长")
        self.c_cnt = StatCard("事件数")
        for c in (self.c_monitor, self.c_valid, self.c_paused, self.c_event, self.c_cnt):
            cards.addWidget(c)
        cards.addStretch(1)
        lay.addLayout(cards)

        self.empty = EmptyState(
            "数据库为空，暂无可分析数据",
            "完成至少一次监测后，这里会显示真实的时间分布、类型占比与趋势。",
        )
        lay.addWidget(self.empty)

        self.data_area = QWidget()
        data_lay = QVBoxLayout(self.data_area)

        lay.addWidget(QLabel("事件时长分布"))
        self.dist_table = make_table(["区间", "事件数"])
        data_lay.addWidget(self.dist_table)

        lay.addWidget(QLabel("事件类型占比"))
        self.type_table = make_table(["类型", "事件数", "总时长"])
        data_lay.addWidget(self.type_table)

        lay.addWidget(QLabel("跨会话趋势"))
        self.trend_table = make_table(["会话", "有效率", "事件数"])
        data_lay.addWidget(self.trend_table)

        lay.addWidget(QLabel("用户反馈统计"))
        self.fb_table = make_table(["反馈类型", "次数"])
        data_lay.addWidget(self.fb_table)

        lay.addWidget(QLabel("输入模式与关键点有效率"))
        self.mode_table = make_table(["输入模式", "会话数", "有效率"])
        data_lay.addWidget(self.mode_table)

        lay.addWidget(self.data_area)

        row = QHBoxLayout()
        btn_export = QPushButton("导出 CSV")
        btn_export.clicked.connect(self._export)
        self.lbl_export = QLabel("")
        self.lbl_export.setObjectName("metrics")
        row.addWidget(btn_export)
        row.addWidget(self.lbl_export)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addStretch(1)
        outer.addWidget(_scrollable(content))

    def refresh(self) -> None:
        from .widgets import fill_table as _ft
        svc = AnalyticsService(self.db)
        t = svc.totals()

        if t.is_empty:
            self.empty.setVisible(True)
            self.data_area.setVisible(False)
            for c in (self.c_monitor, self.c_valid, self.c_paused, self.c_event, self.c_cnt):
                c.set_value("—")
            return

        self.empty.setVisible(False)
        self.data_area.setVisible(True)
        self.c_monitor.set_value(format_ms(t.total_monitor_ms))
        self.c_valid.set_value(format_ms(t.total_valid_ms))
        self.c_paused.set_value(format_ms(t.total_paused_ms))
        self.c_event.set_value(format_ms(t.total_event_ms))
        self.c_cnt.set_value(str(t.event_count))

        _ft(self.dist_table, [[b.range_label, str(b.count)] for b in svc.duration_distribution()])
        _ft(self.type_table, [
            [s.event_type, str(s.count), format_ms(s.total_ms)]
            for s in svc.event_type_shares()
        ])
        _ft(self.trend_table, [
            [p.session_id, format_ratio(p.valid_ratio), str(p.event_count)]
            for p in svc.trend()
        ])
        fb = svc.feedback_summary()
        _ft(self.fb_table, [[k, str(v)] for k, v in fb.items()] or [["—", "0"]])
        _ft(self.mode_table, [
            [m["input_mode"], str(m["session_count"]), format_ratio(m["valid_ratio"])]
            for m in svc.valid_ratio_by_input_mode()
        ])

    def _export(self) -> None:
        from pathlib import Path
        out = Path.home() / "PostureSenseAI" / "export"
        counts = export_all(self.db, out)
        self.lbl_export.setText(
            f"✓ 已导出 sessions={counts['sessions']} events={counts['events']} "
            f"feedback={counts['feedback']} → {out}"
        )


# ===========================================================================
# 7. 算法测试实验室
# ===========================================================================
class LabPage(QWidget):
    """算法实验室：方案定义 + 指标空态。有标注数据才出数字。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)

        lay.addWidget(_title("算法测试实验室"))
        lay.addWidget(_subtitle(
            "三方案共用同一特征提取器，仅判定策略不同。"
            "无标注数据时显示空状态，不伪造评估结果。"
        ))

        lay.addWidget(QLabel("对比方案定义"))
        table = make_table(["方案", "名称", "定义"])
        from .widgets import fill_table as _ft
        rows = [
            ["A", "A_fixed_single", "固定阈值、单帧判断"],
            ["B", "B_fixed_sustained", "固定阈值、连续时间判断"],
            ["C", "C_baseline_sustained", "个性化基线、连续时间判断"],
        ]
        _ft(table, rows)
        lay.addWidget(table)

        lay.addWidget(QLabel("当前可用策略"))
        strat_table = make_table(["键", "类名", "默认参数"])
        strat_rows = []
        for k, cls in STRATEGY_REGISTRY.items():
            strat_rows.append([k, cls.__name__, str(cls().params())])
        _ft(strat_table, strat_rows)
        lay.addWidget(strat_table)

        self.empty = EmptyState(
            "尚无实验结果",
            "需要先录制测试视频并完成人工标注（JSONL）。"
            "评估指标（Precision / Recall / F1 / FPR / 每小时误报 / 检测延迟）"
            "在实测后才会显示，本页不填充虚构数字。\n\n"
            "标注格式与流程见项目 README.md §4.6（算法实验室）",
        )
        lay.addWidget(self.empty)

        lay.addWidget(QLabel("评估指标（待实测）"))
        metric_table = make_table(["指标", "方案 A", "方案 B", "方案 C"])
        _ft(metric_table, [[m, "—", "—", "—"] for m in (
            "Precision", "Recall", "F1", "False Positive Rate",
            "每小时误报次数", "平均检测延迟 (s)",
        )])
        lay.addWidget(metric_table)

        lay.addStretch(1)
        outer.addWidget(_scrollable(content))

    def refresh(self) -> None:
        # 有实验记录后再接真实数据
        return


# ===========================================================================
# 8. 隐私与系统设置
# ===========================================================================
class PrivacyPage(QWidget):
    """隐私与设置：数据管理 + 边界声明。"""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)

        lay.addWidget(_title("隐私与系统设置"))
        lay.addWidget(_subtitle("所有数据保存在本机，不上传云端。"))

        g1 = QGroupBox("数据概况")
        f1 = QFormLayout(g1)
        self.lbl_counts = QLabel("—")
        self.lbl_counts.setWordWrap(True)
        f1.addRow("本地数据行数", self.lbl_counts)
        lay.addWidget(g1)

        row = QHBoxLayout()
        btn_refresh = QPushButton("刷新统计")
        btn_refresh.setObjectName("ghost")
        btn_refresh.clicked.connect(self.refresh)
        btn_delete = QPushButton("删除全部本地数据")
        btn_delete.setObjectName("stopBtn")
        btn_delete.clicked.connect(self._delete_all)
        row.addWidget(btn_refresh)
        row.addWidget(btn_delete)
        row.addStretch(1)
        lay.addLayout(row)

        g2 = QGroupBox("隐私承诺")
        f2 = QVBoxLayout(g2)
        for text in (
            "✓ 摄像头由您主动开启；停止监测后立即释放设备",
            "✓ 默认不保存原始视频帧",
            "✓ 不进行人脸身份识别",
            "✓ 不推断心理状态、疾病或工作能力",
            "✓ 关键点与特征数据仅存于本机 SQLite",
            "✓ 可随时删除全部本地历史数据",
        ):
            lab = QLabel(text)
            lab.setStyleSheet("color: #94A3B8; font-size: 13px;")
            lab.setWordWrap(True)
            f2.addWidget(lab)
        lay.addWidget(g2)

        g3 = QGroupBox("使用边界")
        f3 = QVBoxLayout(g3)
        warn = QLabel(
            "本软件用于日常姿态观察与使用习惯辅助，"
            "**不提供医学诊断**，不声称预防或治疗颈椎疾病。\n\n"
            "摄像头角度、拍摄方向、遮挡、光照与距离都会影响检测结果。"
            "当关键点质量不足时，系统显示「无法判断」而不是强行输出异常标签。\n\n"
            "如需医学建议，请咨询专业医疗人员。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #94A3B8; font-size: 13px;")
        f3.addWidget(warn)
        lay.addWidget(g3)

        lay.addStretch(1)
        outer.addWidget(_scrollable(content))

    def refresh(self) -> None:
        counts = self.db.count_rows()
        self.lbl_counts.setText(
            f"会话 {counts['sessions']} 条 · 事件 {counts['posture_events']} 条 · "
            f"反馈 {counts['user_feedback']} 条 · 基线 {counts['calibration_profiles']} 条"
        )

    def _delete_all(self) -> None:
        if QMessageBox.question(
            self, "确认删除", "确定删除全部本地数据？此操作不可恢复。"
        ) != QMessageBox.Yes:
            return
        self.db.delete_user_data()
        self.refresh()
        QMessageBox.information(self, "完成", "已删除全部本地数据。")
