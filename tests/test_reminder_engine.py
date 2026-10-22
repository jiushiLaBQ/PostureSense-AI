"""reminder_engine 测试：冷却、静音、延后、反馈。"""

from __future__ import annotations

from posturesense.core.reminder_engine import (
    FeedbackType,
    ReminderConfig,
    ReminderEngine,
)


def _engine(**kw) -> ReminderEngine:
    cfg = ReminderConfig(cooldown_sec=300.0, snooze_sec=120.0, **kw)
    return ReminderEngine(cfg)


# ---------------------------------------------------------------------------
# 冷却
# ---------------------------------------------------------------------------
def test_first_reminder_delivers():
    e = _engine()
    rec = e.try_remind("pe-1", now=100.0)
    assert rec.delivered is True
    assert rec.event_id == "pe-1"
    assert rec.suppressed_reason == ""


def test_cooldown_suppresses_second():
    e = _engine()
    e.try_remind("pe-1", now=100.0)
    rec = e.try_remind("pe-2", now=150.0)  # 50s 后，冷却 300s
    assert rec.delivered is False
    assert rec.suppressed_reason.startswith("cooldown")


def test_cooldown_expires():
    e = _engine()
    e.try_remind("pe-1", now=100.0)
    rec = e.try_remind("pe-2", now=401.0)  # 301s 后
    assert rec.delivered is True


def test_cooldown_remaining():
    e = _engine()
    assert e.cooldown_remaining(now=0.0) == 0.0
    e.try_remind("pe-1", now=100.0)
    assert e.cooldown_remaining(now=100.0) == 300.0
    assert e.cooldown_remaining(now=250.0) == 150.0
    assert e.cooldown_remaining(now=400.0) == 0.0


# ---------------------------------------------------------------------------
# 静音 / 延后
# ---------------------------------------------------------------------------
def test_mute_suppresses():
    e = _engine()
    e.mute(60.0, now=100.0)
    rec = e.try_remind("pe-1", now=120.0)
    assert rec.delivered is False
    assert rec.suppressed_reason == "muted"


def test_mute_expires():
    e = _engine()
    e.mute(60.0, now=100.0)
    rec = e.try_remind("pe-1", now=161.0)
    assert rec.delivered is True


def test_unmute():
    e = _engine()
    e.mute(1000.0, now=100.0)
    e.unmute()
    rec = e.try_remind("pe-1", now=101.0)
    assert rec.delivered is True


def test_snooze_suppresses():
    e = _engine()
    e.snooze(now=100.0)
    rec = e.try_remind("pe-1", now=150.0)
    assert rec.delivered is False
    assert rec.suppressed_reason == "snoozed"


def test_snooze_expires():
    e = _engine()
    e.snooze(now=100.0)  # 120s
    rec = e.try_remind("pe-1", now=221.0)
    assert rec.delivered is True


def test_mute_takes_priority_over_snooze():
    e = _engine()
    e.mute(100.0, now=100.0)
    e.snooze(now=100.0)
    rec = e.try_remind("pe-1", now=110.0)
    assert rec.suppressed_reason == "muted"


# ---------------------------------------------------------------------------
# 反馈
# ---------------------------------------------------------------------------
def test_feedback_records_event_id():
    e = _engine()
    fb = e.add_feedback("pe-1", FeedbackType.FALSE_POSITIVE, note="站着的", now=100.0)
    assert fb.event_id == "pe-1"
    assert fb.feedback_type is FeedbackType.FALSE_POSITIVE
    assert fb.note == "站着的"
    assert e.feedbacks == [fb]


def test_feedback_summary():
    e = _engine()
    e.add_feedback("pe-1", FeedbackType.IGNORED, now=1.0)
    e.add_feedback("pe-2", FeedbackType.IGNORED, now=2.0)
    e.add_feedback("pe-3", FeedbackType.ADJUSTED, now=3.0)
    s = e.feedback_summary()
    assert s["ignored"] == 2
    assert s["adjusted"] == 1


def test_feedback_does_not_affect_cooldown():
    """反馈不改变冷却状态（不回灌为标签/不重置冷却）。"""
    e = _engine()
    e.try_remind("pe-1", now=100.0)
    e.add_feedback("pe-1", FeedbackType.FALSE_POSITIVE, now=101.0)
    rec = e.try_remind("pe-2", now=150.0)
    assert rec.delivered is False


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def test_delivered_count():
    e = _engine()
    e.try_remind("pe-1", now=100.0)
    e.try_remind("pe-2", now=110.0)  # 冷却抑制
    e.try_remind("pe-3", now=500.0)  # 投放
    assert e.delivered_count() == 2
    assert len(e.records) == 3


def test_reset_clears_state():
    e = _engine()
    e.try_remind("pe-1", now=100.0)
    e.add_feedback("pe-1", FeedbackType.DISMISSED, now=101.0)
    e.reset()
    assert e.records == []
    assert e.feedbacks == []
    assert e.cooldown_remaining(now=102.0) == 0.0
