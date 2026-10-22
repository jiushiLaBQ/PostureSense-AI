"""storage 测试：会话/事件/反馈/基线读写、级联删除、清空数据、迁移。"""

from __future__ import annotations

import sqlite3

import pytest

from posturesense.core.storage import Database, SCHEMA_VERSION, StorageError, now_ms


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


def _session(sid="s1", **kw):
    rec = {"session_id": sid, "start_ts": now_ms(), "input_mode": "camera"}
    rec.update(kw)
    return rec


def _event(eid="e1", sid="s1", **kw):
    rec = {
        "event_id": eid,
        "session_id": sid,
        "start_ts": now_ms(),
        "event_type": "sustained_deviation",
    }
    rec.update(kw)
    return rec


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------
def test_schema_version(db):
    assert db.schema_version() == SCHEMA_VERSION


def test_tables_exist(db):
    counts = db.count_rows()
    assert set(counts) == {
        "sessions", "posture_events", "user_feedback", "calibration_profiles"
    }
    assert all(v == 0 for v in counts.values())


def test_in_memory_db():
    with Database(":memory:") as d:
        assert d.schema_version() == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
def test_session_roundtrip(db):
    db.insert_session(_session())
    got = db.get_session("s1")
    assert got is not None
    assert got["input_mode"] == "camera"
    assert got["status"] == "running"
    assert got["end_ts"] is None


def test_finish_session(db):
    db.insert_session(_session())
    ok = db.finish_session("s1", end_ts=now_ms(), duration_ms=60000, valid_ms=50000, paused_ms=10000)
    assert ok is True
    got = db.get_session("s1")
    assert got["status"] == "completed"
    assert got["duration_ms"] == 60000
    assert got["valid_ms"] == 50000
    assert got["paused_ms"] == 10000


def test_finish_missing_session_returns_false(db):
    assert db.finish_session("nope", 1, 1, 1, 1) is False


def test_list_sessions_order(db):
    db.insert_session(_session("s1", start_ts=1000))
    db.insert_session(_session("s2", start_ts=3000))
    db.insert_session(_session("s3", start_ts=2000))
    ids = [s["session_id"] for s in db.list_sessions()]
    assert ids == ["s2", "s3", "s1"]  # start_ts 降序


def test_list_sessions_pagination(db):
    for i in range(5):
        db.insert_session(_session(f"s{i}", start_ts=1000 + i))
    assert len(db.list_sessions(limit=2)) == 2
    assert len(db.list_sessions(limit=2, offset=2)) == 2


def test_time_concepts_separate(db):
    """监测时长/有效时长/暂停时长必须分开记录（红线）。"""
    db.insert_session(_session())
    db.finish_session("s1", end_ts=10, duration_ms=1000, valid_ms=600, paused_ms=400)
    got = db.get_session("s1")
    assert got["duration_ms"] != got["valid_ms"]
    assert got["valid_ms"] + got["paused_ms"] == got["duration_ms"]


# ---------------------------------------------------------------------------
# events + cascade
# ---------------------------------------------------------------------------
def test_event_roundtrip(db):
    db.insert_session(_session())
    db.insert_event(_event(max_deviation=3.5, was_reminded=1, valid_ratio=0.9))
    evs = db.list_events("s1")
    assert len(evs) == 1
    assert evs[0]["max_deviation"] == 3.5
    assert evs[0]["was_reminded"] == 1


def test_delete_session_cascades(db):
    db.insert_session(_session())
    db.insert_event(_event("e1"))
    db.insert_event(_event("e2"))
    db.insert_feedback({"feedback_id": "f1", "event_id": "e1", "feedback_type": "ignored", "created_at": now_ms()})

    assert db.delete_session("s1") is True
    assert db.get_session("s1") is None
    assert db.list_events("s1") == []
    assert db.count_rows()["posture_events"] == 0
    assert db.count_rows()["user_feedback"] == 0


def test_delete_missing_session(db):
    assert db.delete_session("nope") is False


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------
def test_feedback_roundtrip(db):
    db.insert_session(_session())
    db.insert_event(_event())
    db.insert_feedback({
        "feedback_id": "f1", "event_id": "e1",
        "feedback_type": "false_positive", "created_at": now_ms(),
        "note": "在喝水",
    })
    fbs = db.list_feedback("e1")
    assert len(fbs) == 1
    assert fbs[0]["feedback_type"] == "false_positive"
    assert fbs[0]["note"] == "在喝水"


# ---------------------------------------------------------------------------
# calibration profiles
# ---------------------------------------------------------------------------
def test_profile_roundtrip(db):
    db.insert_profile({
        "profile_id": "bp-1", "name": "我的基线",
        "created_at": now_ms(), "sample_count": 50,
        "stats_json": '{"trunk_tilt_deg": {"count": 50, "mean": 5.0, "std": 1.2}}',
    })
    got = db.get_profile("bp-1")
    assert got is not None
    assert got["name"] == "我的基线"
    assert got["sample_count"] == 50
    assert "trunk_tilt_deg" in got["stats_json"]


def test_profile_rename_delete(db):
    db.insert_profile({"profile_id": "bp-1", "name": "旧名", "created_at": 1, "sample_count": 10, "stats_json": "{}"})
    assert db.delete_profile("bp-1") is True
    assert db.get_profile("bp-1") is None
    assert db.delete_profile("bp-1") is False


def test_list_profiles_order(db):
    db.insert_profile({"profile_id": "a", "name": "a", "created_at": 1, "sample_count": 1, "stats_json": "{}"})
    db.insert_profile({"profile_id": "b", "name": "b", "created_at": 2, "sample_count": 1, "stats_json": "{}"})
    ids = [p["profile_id"] for p in db.list_profiles()]
    assert ids == ["b", "a"]


# ---------------------------------------------------------------------------
# 隐私
# ---------------------------------------------------------------------------
def test_delete_user_data_clears_all(db):
    db.insert_session(_session())
    db.insert_event(_event())
    db.insert_feedback({"feedback_id": "f1", "event_id": "e1", "feedback_type": "ignored", "created_at": 1})
    db.insert_profile({"profile_id": "bp", "name": "x", "created_at": 1, "sample_count": 1, "stats_json": "{}"})

    counts = db.delete_user_data()
    assert counts["sessions"] == 1
    assert counts["posture_events"] == 1
    assert counts["user_feedback"] == 1
    assert counts["calibration_profiles"] == 1
    assert all(v == 0 for v in db.count_rows().values())


def test_persistence_across_reopen(tmp_path):
    """重启程序后历史仍可读取（验收项）。"""
    path = tmp_path / "persist.db"
    with Database(path) as d:
        d.insert_session(_session())
        d.insert_event(_event())

    with Database(path) as d2:
        assert d2.get_session("s1") is not None
        assert len(d2.list_events("s1")) == 1


def test_rollback_on_error(db):
    """事务异常回滚，不写入半条记录。"""
    with pytest.raises(sqlite3.Error):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, start_ts, input_mode) VALUES (?,?,?)",
                ("sx", 1, "camera"),
            )
            conn.execute("INSERT INTO sessions (session_id) VALUES (NULL)")  # 失败
    assert db.get_session("sx") is None
