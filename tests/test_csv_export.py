"""CSV 导出测试：BOM、中文、行数、空表、时间格式。"""

from __future__ import annotations

import csv

from posturesense.core.csv_export import (
    export_all,
    export_events,
    export_feedback,
    export_sessions,
)
from posturesense.core.storage import Database, now_ms


def _seed(db: Database):
    db.insert_session({"session_id": "s1", "start_ts": 1700000000000, "input_mode": "camera"})
    db.finish_session("s1", end_ts=1700000060000, duration_ms=60000, valid_ms=50000, paused_ms=10000)
    db.insert_event({
        "event_id": "e1", "session_id": "s1", "start_ts": 1700000010000,
        "end_ts": 1700000020000, "event_type": "sustained_deviation",
        "duration_ms": 10000, "max_deviation": 3.2, "was_reminded": 1, "valid_ratio": 0.91,
    })
    db.insert_feedback({
        "feedback_id": "f1", "event_id": "e1", "feedback_type": "false_positive",
        "created_at": 1700000030000, "note": "我在喝水",
    })


def test_sessions_csv(tmp_path):
    db = Database(":memory:")
    _seed(db)
    out = tmp_path / "sessions.csv"
    n = export_sessions(db, out)
    assert n == 1

    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "必须写 BOM 以便 Excel 读中文"

    with out.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["session_id"] == "s1"
    assert rows[0]["start_iso"] == "2023-11-14T22:13:20+00:00"
    assert rows[0]["duration_ms"] == "60000"


def test_events_csv(tmp_path):
    db = Database(":memory:")
    _seed(db)
    out = tmp_path / "events.csv"
    n = export_events(db, out)
    assert n == 1
    with out.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["max_deviation"] == "3.2"
    assert rows[0]["was_reminded"] == "1"


def test_events_csv_filter_by_session(tmp_path):
    db = Database(":memory:")
    _seed(db)
    out = tmp_path / "e.csv"
    assert export_events(db, out, session_id="s1") == 1
    assert export_events(db, out, session_id="none") == 0


def test_feedback_csv_chinese(tmp_path):
    db = Database(":memory:")
    _seed(db)
    out = tmp_path / "fb.csv"
    assert export_feedback(db, out) == 1
    text = out.read_text(encoding="utf-8-sig")
    assert "我在喝水" in text


def test_empty_db_exports_headers_only(tmp_path):
    """空库导出只有表头，0 行 — 不编造数据。"""
    db = Database(":memory:")
    out = tmp_path / "s.csv"
    n = export_sessions(db, out)
    assert n == 0
    lines = out.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(lines) == 1  # 仅表头


def test_export_all(tmp_path):
    db = Database(":memory:")
    _seed(db)
    counts = export_all(db, tmp_path / "out")
    assert counts == {"sessions": 1, "events": 1, "feedback": 1}
    assert (tmp_path / "out" / "sessions.csv").exists()
    assert (tmp_path / "out" / "posture_events.csv").exists()
    assert (tmp_path / "out" / "user_feedback.csv").exists()


def test_no_image_columns(tmp_path):
    """导出不含任何图像列（隐私红线）。"""
    db = Database(":memory:")
    _seed(db)
    out = tmp_path / "s.csv"
    export_sessions(db, out)
    header = out.read_text(encoding="utf-8-sig").splitlines()[0].lower()
    for banned in ("image", "frame", "photo", "face", "landmark"):
        assert banned not in header
