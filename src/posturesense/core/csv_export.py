"""CSV 导出：会话、姿态事件、反馈。

- UTF-8 with BOM，Excel 直接双击可读中文。
- 时间戳同时导出 epoch 毫秒与 ISO 8601，便于人读与程序处理。
- 只导出结构化数据，不导出任何图像。
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .storage import Database

logger = logging.getLogger(__name__)

SESSION_FIELDS = [
    "session_id", "start_ts", "start_iso", "end_ts", "end_iso",
    "input_mode", "duration_ms", "valid_ms", "paused_ms",
    "baseline_id", "algo_version", "status",
]

EVENT_FIELDS = [
    "event_id", "session_id", "start_ts", "start_iso", "end_ts", "end_iso",
    "event_type", "duration_ms", "max_deviation", "was_reminded", "valid_ratio",
]

FEEDBACK_FIELDS = [
    "feedback_id", "event_id", "feedback_type", "created_at", "created_iso", "note",
]


def _iso(ts) -> str:
    """epoch 毫秒 → ISO 8601 (UTC)。None/非法返回空串。"""
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(int(ts) / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _write_csv(path: Path, fields: list[str], rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # utf-8-sig 写 BOM，Excel 打开中文不乱码
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    logger.info("CSV 已导出: %s (%d 行)", path, count)
    return count


def export_sessions(db: Database, path: str | Path) -> int:
    rows = []
    for s in db.list_sessions(limit=100000):
        rows.append({
            **s,
            "start_iso": _iso(s.get("start_ts")),
            "end_iso": _iso(s.get("end_ts")),
        })
    return _write_csv(Path(path), SESSION_FIELDS, rows)


def export_events(db: Database, path: str | Path, session_id: str | None = None) -> int:
    if session_id is not None:
        events = db.list_events(session_id)
    else:
        # 全量：遍历会话
        events = []
        for s in db.list_sessions(limit=100000):
            events.extend(db.list_events(s["session_id"]))
    rows = []
    for e in events:
        rows.append({
            **e,
            "start_iso": _iso(e.get("start_ts")),
            "end_iso": _iso(e.get("end_ts")),
        })
    return _write_csv(Path(path), EVENT_FIELDS, rows)


def export_feedback(db: Database, path: str | Path) -> int:
    rows = []
    for s in db.list_sessions(limit=100000):
        for e in db.list_events(s["session_id"]):
            for f in db.list_feedback(e["event_id"]):
                rows.append({**f, "created_iso": _iso(f.get("created_at"))})
    return _write_csv(Path(path), FEEDBACK_FIELDS, rows)


def export_all(db: Database, directory: str | Path) -> dict[str, int]:
    """导出三张表到目录。返回各文件行数。"""
    directory = Path(directory)
    return {
        "sessions": export_sessions(db, directory / "sessions.csv"),
        "events": export_events(db, directory / "posture_events.csv"),
        "feedback": export_feedback(db, directory / "user_feedback.csv"),
    }
