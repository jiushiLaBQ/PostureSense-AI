"""连续姿态分析：滑窗平滑 + 状态机 + 误报抑制。

设计要点（见仓库根 README.md §4.5 时序状态机与报警阈值）:

状态机
    INIT → NORMAL → SUSPECT → SUSTAINED → REMINDED → RECOVERING → NORMAL
    旁路: PAUSED（用户暂停）/ UNKNOWN（关键点质量不足，无法判断）

硬性规则
    1. 单帧偏离**不**触发事件 —— 必须滑窗平滑 + 持续时间 ≥ sustain_sec
    2. 关键点有效率低于门槛 → UNKNOWN（**不是** SUSPECT，不记异常事件）
    3. 进入阈值 ≠ 退出阈值（滞回），并有最短驻留时间
    4. 提醒受冷却时间约束（由 reminder_engine 状态机记录，这里只暴露 REMINDED）
    5. 事件记录 start/end/duration/max_deviation/reminded

参数全部可配，默认值为初值，待实测标定。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class PostureState(str, Enum):
    INIT = "init"
    NORMAL = "normal"
    SUSPECT = "suspect"  # 疑似偏离
    SUSTAINED = "sustained"  # 持续偏离（可提醒）
    REMINDED = "reminded"  # 已提醒
    RECOVERING = "recovering"  # 恢复观察
    UNKNOWN = "unknown"  # 无法判断（关键点不足）
    PAUSED = "paused"  # 用户暂停


@dataclass
class AnalyzerConfig:
    """时序分析参数。默认值为初值，须实测标定。"""

    deviation_threshold: float = 2.0  # 综合偏离阈值
    hysteresis_margin: float = 0.3  # 退出阈值 = threshold - margin
    sustain_sec: float = 30.0  # 连续异常判定时间
    recover_sec: float = 10.0  # 连续正常恢复时间
    min_valid_ratio: float = 0.5  # 关键点最低有效率
    window_size: int = 30  # 滑动窗口（帧）
    min_dwell_sec: float = 2.0  # 状态最短驻留时间，防抖
    unknown_breaks_streak: bool = True  # UNKNOWN 是否打断异常持续计时

    @property
    def recover_threshold(self) -> float:
        return max(0.0, self.deviation_threshold - self.hysteresis_margin)


@dataclass
class PostureEvent:
    """一次姿态偏离事件。"""

    event_id: str
    state: PostureState
    start_ts: float
    end_ts: float = 0.0
    max_deviation: float = 0.0
    reminded: bool = False

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_ts - self.start_ts)


@dataclass
class FrameSample:
    """单帧输入。deviation=None 表示无法判断。"""

    timestamp: float
    deviation: Optional[float]  # 综合偏离指标（baseline composite 或固定阈值输入）
    valid_ratio: float
    is_paused: bool = False


@dataclass
class AnalyzerSnapshot:
    """一次状态机推进后的输出。"""

    state: PostureState
    smoothed_deviation: Optional[float]
    # 本次调用中新结束的事件（非 None 表示有事件落盘）
    closed_event: Optional[PostureEvent] = None
    should_remind: bool = False
    reason: str = ""


class TemporalAnalyzer:
    """滑窗平滑 + 状态机。单线程使用。"""

    def __init__(self, config: Optional[AnalyzerConfig] = None) -> None:
        self.config = config or AnalyzerConfig()
        self._window: deque[float] = deque(maxlen=self.config.window_size)
        self._state = PostureState.INIT
        self._state_since: float = 0.0
        self._streak_start: Optional[float] = None
        self._recover_start: Optional[float] = None
        self._open_event: Optional[PostureEvent] = None
        self._event_seq = 0

    # ------------------------------------------------------------------
    @property
    def state(self) -> PostureState:
        return self._state

    @property
    def smoothed(self) -> Optional[float]:
        if not self._window:
            return None
        return sum(self._window) / len(self._window)

    def reset(self) -> None:
        self.__init__(self.config)  # noqa: WPS612 - 简洁重置

    # ------------------------------------------------------------------
    def update(self, sample: FrameSample) -> AnalyzerSnapshot:
        """喂入一帧，返回状态快照。"""
        cfg = self.config

        # --- 暂停优先 ---------------------------------------------
        if sample.is_paused:
            return self._enter(PostureState.PAUSED, sample.timestamp, "用户暂停")

        # --- 无法判断 ---------------------------------------------
        if sample.valid_ratio < cfg.min_valid_ratio or sample.deviation is None:
            if cfg.unknown_breaks_streak:
                self._streak_start = None
                self._recover_start = None
            return self._enter(PostureState.UNKNOWN, sample.timestamp, "关键点质量不足")

        # --- 更新滑窗 ---------------------------------------------
        self._window.append(float(sample.deviation))
        smoothed = self.smoothed

        now = sample.timestamp
        over = smoothed >= cfg.deviation_threshold
        under = smoothed <= cfg.recover_threshold
        # 带内（滞回区间）→ 维持当前趋势

        # --- 状态转移 ---------------------------------------------
        if self._state in (PostureState.INIT, PostureState.PAUSED, PostureState.UNKNOWN):
            return self._enter(
                PostureState.NORMAL, now, "开始正常监测", smoothed=smoothed
            )

        if self._state is PostureState.NORMAL:
            if over:
                if self._streak_start is None:
                    self._streak_start = now
                if now - self._streak_start >= cfg.sustain_sec:
                    self._open_event = self._new_event(now, smoothed)
                    return self._enter(
                        PostureState.SUSTAINED, now,
                        f"持续偏离 ≥{cfg.sustain_sec}s", smoothed=smoothed,
                    )
                return self._enter(
                    PostureState.SUSPECT, now, "疑似偏离", smoothed=smoothed
                )
            self._streak_start = None
            return self._stay(now, smoothed)

        if self._state is PostureState.SUSPECT:
            if over:
                if self._streak_start is None:
                    self._streak_start = now
                if now - self._streak_start >= cfg.sustain_sec:
                    self._open_event = self._new_event(now, smoothed)
                    return self._enter(
                        PostureState.SUSTAINED, now,
                        f"持续偏离 ≥{cfg.sustain_sec}s", smoothed=smoothed,
                    )
                return self._stay(now, smoothed)
            # 跌回阈值下 → 取消疑似（短暂动作不触发事件）
            self._streak_start = None
            return self._enter(PostureState.NORMAL, now, "偏离取消", smoothed=smoothed)

        if self._state is PostureState.SUSTAINED:
            if self._open_event and smoothed is not None:
                self._open_event.max_deviation = max(
                    self._open_event.max_deviation, smoothed
                )
            # 触发一次提醒后进入 REMINDED
            should = self._open_event is not None and not self._open_event.reminded
            if should:
                self._open_event.reminded = True
                snap = self._enter(
                    PostureState.REMINDED, now, "已提醒", smoothed=smoothed
                )
                snap.should_remind = True
                return snap
            return self._stay(now, smoothed)

        if self._state is PostureState.REMINDED:
            if self._open_event and smoothed is not None:
                self._open_event.max_deviation = max(
                    self._open_event.max_deviation, smoothed
                )
            if under:
                self._recover_start = now
                return self._enter(
                    PostureState.RECOVERING, now, "恢复观察", smoothed=smoothed
                )
            return self._stay(now, smoothed)

        if self._state is PostureState.RECOVERING:
            if under:
                if self._recover_start is None:
                    self._recover_start = now
                if now - self._recover_start >= cfg.recover_sec:
                    closed = self._close_event(now)
                    self._streak_start = None
                    self._recover_start = None
                    snap = self._enter(
                        PostureState.NORMAL, now, "已恢复", smoothed=smoothed
                    )
                    snap.closed_event = closed
                    return snap
                return self._stay(now, smoothed)
            # 又超阈值 → 回到已提醒
            self._recover_start = None
            return self._enter(
                PostureState.REMINDED, now, "再次偏离", smoothed=smoothed
            )

        return self._stay(now, smoothed)

    # ------------------------------------------------------------------
    def flush(self, timestamp: float) -> Optional[PostureEvent]:
        """强制关闭未完成事件（停止监测时调用）。"""
        return self._close_event(timestamp)

    # ------------------------------------------------------------------
    def _new_event(self, ts: float, deviation: Optional[float]) -> PostureEvent:
        self._event_seq += 1
        return PostureEvent(
            event_id=f"pe-{self._event_seq}",
            state=PostureState.SUSTAINED,
            start_ts=ts,
            max_deviation=deviation or 0.0,
        )

    def _close_event(self, ts: float) -> Optional[PostureEvent]:
        ev = self._open_event
        if ev is None:
            return None
        ev.end_ts = ts
        self._open_event = None
        logger.info(
            "姿态事件结束: %s duration=%.1fs max_dev=%.2f reminded=%s",
            ev.event_id, ev.duration_sec, ev.max_deviation, ev.reminded,
        )
        return ev

    def _enter(
        self,
        new_state: PostureState,
        ts: float,
        reason: str,
        smoothed: Optional[float] = None,
    ) -> AnalyzerSnapshot:
        old = self._state
        # 最短驻留：INIT 无约束，其余状态切换需距上次 ≥ min_dwell_sec
        if (
            old not in (PostureState.INIT,)
            and new_state != old
            and ts - self._state_since < self.config.min_dwell_sec
            and old in (PostureState.SUSPECT, PostureState.NORMAL)
        ):
            return self._stay(ts, smoothed, reason=f"驻留未满，维持 {old.value}")
        self._state = new_state
        self._state_since = ts
        if new_state != old:
            logger.debug("状态切换 %s → %s (%s)", old.value, new_state.value, reason)
        return AnalyzerSnapshot(
            state=new_state,
            smoothed_deviation=smoothed if smoothed is not None else self.smoothed,
            reason=reason,
        )

    def _stay(
        self, ts: float, smoothed: Optional[float] = None, reason: str = ""
    ) -> AnalyzerSnapshot:
        return AnalyzerSnapshot(
            state=self._state,
            smoothed_deviation=smoothed if smoothed is not None else self.smoothed,
            reason=reason,
        )
