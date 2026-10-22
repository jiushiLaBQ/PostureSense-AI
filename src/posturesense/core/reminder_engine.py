"""提醒引擎：冷却、静音、延后、用户反馈。

设计要点:
- 提醒温和非强制，允许用户忽略、标记误报、延后。
- 冷却时间决定同一会话内两次提醒的最小间隔。
- 静音 / 延后期间不产生提醒，但**事件照常记录**（监测不中断）。
- 用户反馈只记录，不自动当作模型标签（红线）。

通知投放（桌面通知/声音）是 UI 层职责；本模块只做决策与状态，
保证可单测、不依赖 OS 通知服务。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class FeedbackType(str, Enum):
    """用户对一次提醒的反馈。"""

    IGNORED = "ignored"  # 忽略
    FALSE_POSITIVE = "false_positive"  # 标记误报
    ADJUSTED = "adjusted"  # 已调整坐姿
    DISMISSED = "dismissed"  # 关闭提示
    SNOOZED = "snoozed"  # 延后


@dataclass
class ReminderConfig:
    cooldown_sec: float = 300.0  # 提醒冷却
    snooze_sec: float = 120.0  # 延后时长
    sound_enabled: bool = True
    desktop_notification: bool = True


@dataclass
class ReminderRecord:
    """一次提醒投放记录。"""

    reminder_id: str
    event_id: str
    created_at: float
    delivered: bool
    suppressed_reason: str = ""


@dataclass
class FeedbackRecord:
    """一条用户反馈。与事件 ID 关联。"""

    feedback_id: str
    event_id: str
    feedback_type: FeedbackType
    created_at: float
    note: str = ""


class ReminderEngine:
    """提醒决策。单线程使用（GUI 线程或专用调度线程）。"""

    def __init__(self, config: Optional[ReminderConfig] = None) -> None:
        self.config = config or ReminderConfig()
        self._last_reminder_at: Optional[float] = None
        self._muted_until: Optional[float] = None
        self._snoozed_until: Optional[float] = None
        self._records: list[ReminderRecord] = []
        self._feedback: list[FeedbackRecord] = []
        self._seq = 0

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def is_muted(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return self._muted_until is not None and now < self._muted_until

    def is_snoozed(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return self._snoozed_until is not None and now < self._snoozed_until

    def cooldown_remaining(self, now: Optional[float] = None) -> float:
        now = time.time() if now is None else now
        if self._last_reminder_at is None:
            return 0.0
        return max(0.0, self.config.cooldown_sec - (now - self._last_reminder_at))

    # ------------------------------------------------------------------
    # 用户控制
    # ------------------------------------------------------------------
    def mute(self, duration_sec: float, now: Optional[float] = None) -> float:
        """静音 duration_sec。返回静音截止时间。"""
        now = time.time() if now is None else now
        self._muted_until = now + max(0.0, duration_sec)
        logger.info("提醒静音至 %.1f", self._muted_until)
        return self._muted_until

    def unmute(self) -> None:
        self._muted_until = None

    def snooze(self, now: Optional[float] = None) -> float:
        """延后一次提醒。返回延后截止时间。"""
        now = time.time() if now is None else now
        self._snoozed_until = now + self.config.snooze_sec
        logger.info("提醒延后至 %.1f", self._snoozed_until)
        return self._snoozed_until

    # ------------------------------------------------------------------
    # 提醒决策
    # ------------------------------------------------------------------
    def try_remind(self, event_id: str, now: Optional[float] = None) -> ReminderRecord:
        """尝试投放一次提醒。返回记录（可能 suppressed_reason 非空）。"""
        now = time.time() if now is None else now
        self._seq += 1
        rid = f"rm-{self._seq}"

        if self.is_muted(now):
            return self._record(rid, event_id, now, False, "muted")
        if self.is_snoozed(now):
            return self._record(rid, event_id, now, False, "snoozed")
        if self.cooldown_remaining(now) > 0:
            return self._record(
                rid, event_id, now, False,
                f"cooldown:{self.cooldown_remaining(now):.0f}s",
            )

        self._last_reminder_at = now
        rec = self._record(rid, event_id, now, True, "")
        logger.info("提醒已投放: %s (event=%s)", rid, event_id)
        return rec

    def _record(self, rid, event_id, now, delivered, reason) -> ReminderRecord:
        rec = ReminderRecord(
            reminder_id=rid,
            event_id=event_id,
            created_at=now,
            delivered=delivered,
            suppressed_reason=reason,
        )
        self._records.append(rec)
        return rec

    # ------------------------------------------------------------------
    # 反馈
    # ------------------------------------------------------------------
    def add_feedback(
        self,
        event_id: str,
        feedback_type: FeedbackType,
        note: str = "",
        now: Optional[float] = None,
    ) -> FeedbackRecord:
        """记录用户反馈。不自动回灌为模型标签。"""
        now = time.time() if now is None else now
        self._seq += 1
        rec = FeedbackRecord(
            feedback_id=f"fb-{self._seq}",
            event_id=event_id,
            feedback_type=feedback_type,
            created_at=now,
            note=note,
        )
        self._feedback.append(rec)
        logger.info(
            "用户反馈: event=%s type=%s note=%r", event_id, feedback_type.value, note
        )
        return rec

    # ------------------------------------------------------------------
    # 查询（供分析中心）
    # ------------------------------------------------------------------
    @property
    def records(self) -> list[ReminderRecord]:
        return list(self._records)

    @property
    def feedbacks(self) -> list[FeedbackRecord]:
        return list(self._feedback)

    def delivered_count(self) -> int:
        return sum(1 for r in self._records if r.delivered)

    def feedback_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for f in self._feedback:
            summary[f.feedback_type.value] = summary.get(f.feedback_type.value, 0) + 1
        return summary

    def reset(self) -> None:
        self._last_reminder_at = None
        self._muted_until = None
        self._snoozed_until = None
        self._records.clear()
        self._feedback.clear()
        self._seq = 0
