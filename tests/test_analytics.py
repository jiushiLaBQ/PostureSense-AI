"""analytics 测试：空库不编数、时长语义分离、聚合正确性。"""

from __future__ import annotations

import pytest

from posturesense.core.analytics import (
    AnalyticsService,
    DURATION_BUCKETS_MS,
)
from posturesense.core.storage import Database


@pytest.fixture
def svc(tmp_path):
    db = Database(tmp_path / "a.db")
    yield AnalyticsService(db)
    db.close()


def _seed(svc: AnalyticsService):
    db = svc.db
    db.insert_session({"session_id": "s1", "start_ts": 1000000, "input_mode": "camera"})
    db.finish_session("s1", end_ts=1060000, duration_ms=60000, valid_ms=50000, paused_ms=10000)
    db.insert_session({"session_id": "s2", "start_ts": 2000000, "input_mode": "video"})
    db.finish_session("s2", end_ts=2120000, duration_ms=120000, valid_ms=120000, paused_ms=0)

    db.insert_event({
        "event_id": "e1", "session_id": "s1", "start_ts": 1010000,
        "end_ts": 1040000, "event_type": "sustained_deviation",
        "duration_ms": 30000, "max_deviation": 3.0, "was_reminded": 1, "valid_ratio": 0.9,
    })
    db.insert_event({
        "event_id": "e2", "session_id": "s1", "start_ts": 1045000,
        "end_ts": 1046000, "event_type": "sustained_deviation",
        "duration_ms": 1000, "max_deviation": 2.5, "was_reminded": 0, "valid_ratio": 0.8,
    })
    db.insert_event({
        "event_id": "e3", "session_id": "s2", "start_ts": 2010000,
        "end_ts": 2070000, "event_type": "shoulder_tilt",
        "duration_ms": 60000, "max_deviation": 4.0, "was_reminded": 1, "valid_ratio": 0.95,
    })


# ---------------------------------------------------------------------------
# 空库红线
# ---------------------------------------------------------------------------
def test_empty_totals_are_zero(svc):
    t = svc.totals()
    assert t.is_empty is True
    assert t.session_count == 0
    assert t.total_monitor_ms == 0
    assert t.total_valid_ms == 0
    assert t.total_event_ms == 0
    assert t.event_count == 0
    assert t.valid_ratio == 0.0


def test_empty_lists_are_empty(svc):
    assert svc.event_type_shares() == []
    assert svc.session_summaries() == []
    assert svc.trend() == []
    assert svc.feedback_summary() == {}
    assert svc.session_timeline("none") == []


def test_empty_duration_distribution_has_zero_buckets(svc):
    """空库仍返回完整桶结构，但计数全 0 — 不编造分布。"""
    buckets = svc.duration_distribution()
    assert len(buckets) == len(DURATION_BUCKETS_MS)
    assert all(b.count == 0 for b in buckets)


# ---------------------------------------------------------------------------
# 时长语义分离
# ---------------------------------------------------------------------------
def test_totals_distinguish_time_concepts(svc):
    _seed(svc)
    t = svc.totals()
    # 三类时长必须分开且可相加核对
    assert t.total_monitor_ms == 60000 + 120000
    assert t.total_valid_ms == 50000 + 120000
    assert t.total_paused_ms == 10000 + 0
    assert t.total_valid_ms + t.total_paused_ms == t.total_monitor_ms
    # 事件时长是子集，不等于监测时长
    assert t.total_event_ms == 30000 + 1000 + 60000
    assert t.total_event_ms != t.total_monitor_ms


def test_valid_ratio(svc):
    _seed(svc)
    t = svc.totals()
    assert t.valid_ratio == pytest.approx(170000 / 180000)


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------
def test_event_type_shares(svc):
    _seed(svc)
    shares = svc.event_type_shares()
    by_type = {s.event_type: s for s in shares}
    assert by_type["sustained_deviation"].count == 2
    assert by_type["shoulder_tilt"].count == 1
    assert by_type["sustained_deviation"].total_ms == 31000


def test_duration_distribution(svc):
    _seed(svc)
    buckets = {b.range_label: b.count for b in svc.duration_distribution()}
    assert buckets["0-30s"] == 1  # 1s 事件
    assert buckets["30s-2m"] == 2  # 30s 与 60s 事件（桶为 [30s, 2m)）
    assert buckets["2m-5m"] == 0
    assert buckets["5m-15m"] == 0
    assert buckets[">15m"] == 0


def test_session_summaries_include_event_rollup(svc):
    _seed(svc)
    sums = {s.session_id: s for s in svc.session_summaries()}
    assert sums["s1"].event_count == 2
    assert sums["s1"].event_ms == 31000
    assert sums["s2"].event_count == 1
    assert sums["s1"].input_mode == "camera"


def test_session_timeline_offsets(svc):
    _seed(svc)
    tl = svc.session_timeline("s1")
    assert len(tl) == 2
    assert tl[0]["start_sec"] == pytest.approx(10.0)  # 1010000-1000000
    assert tl[0]["duration_sec"] == pytest.approx(30.0)
    assert tl[0]["was_reminded"] is True


def test_trend_order_and_ratio(svc):
    _seed(svc)
    pts = svc.trend()
    assert [p.session_id for p in pts] == ["s1", "s2"]  # 时间升序
    assert pts[0].valid_ratio == pytest.approx(50000 / 60000)
    assert pts[1].valid_ratio == pytest.approx(1.0)
    assert pts[0].event_count == 2


def test_feedback_summary(svc):
    _seed(svc)
    svc.db.insert_feedback({
        "feedback_id": "f1", "event_id": "e1",
        "feedback_type": "false_positive", "created_at": 1,
    })
    svc.db.insert_feedback({
        "feedback_id": "f2", "event_id": "e1",
        "feedback_type": "false_positive", "created_at": 2,
    })
    s = svc.feedback_summary()
    assert s == {"false_positive": 2}


def test_valid_ratio_by_input_mode(svc):
    _seed(svc)
    rows = {r["input_mode"]: r for r in svc.valid_ratio_by_input_mode()}
    assert rows["camera"]["session_count"] == 1
    assert rows["camera"]["valid_ratio"] == pytest.approx(50000 / 60000)
    assert rows["video"]["valid_ratio"] == pytest.approx(1.0)
