"""数据分析中心：真实读取 SQLite，区分四类时长。

红线: 空数据库返回零/空列表，**不生成虚构统计**。
四类时间概念严格分开：
    监测时长 duration_ms   — 会话开始到结束
    有效检测时长 valid_ms  — 有可靠关键点的时间
    暂停/无效 paused_ms    — 暂停或无法判断
    事件时长 event duration — 姿态偏离事件的持续时间
前三者满足 duration = valid + paused；事件时长是**子集**（可能落在 valid 内），
不得与前三者混算。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .storage import Database

logger = logging.getLogger(__name__)


@dataclass
class Totals:
    """总量统计。全部来自 SQL SUM/COUNT，空库时为 0。"""

    session_count: int = 0
    total_monitor_ms: int = 0
    total_valid_ms: int = 0
    total_paused_ms: int = 0
    total_event_ms: int = 0
    event_count: int = 0
    reminded_count: int = 0
    feedback_count: int = 0

    @property
    def is_empty(self) -> bool:
        return self.session_count == 0

    @property
    def valid_ratio(self) -> float:
        if self.total_monitor_ms <= 0:
            return 0.0
        return self.total_valid_ms / self.total_monitor_ms


@dataclass
class EventTypeShare:
    event_type: str
    count: int
    total_ms: int


@dataclass
class SessionSummary:
    session_id: str
    start_ts: int
    input_mode: str
    duration_ms: int
    valid_ms: int
    paused_ms: int
    event_count: int
    event_ms: int
    status: str


@dataclass
class DurationBucket:
    """事件时长分布桶。"""

    range_label: str
    count: int


@dataclass
class TrendPoint:
    session_id: str
    start_ts: int
    valid_ratio: float
    event_count: int


# 事件时长分布桶（毫秒）
DURATION_BUCKETS_MS = (
    ("0-30s", 0, 30_000),
    ("30s-2m", 30_000, 120_000),
    ("2m-5m", 120_000, 300_000),
    ("5m-15m", 300_000, 900_000),
    (">15m", 900_000, 10**15),
)


class AnalyticsService:
    """分析查询。只读，不写库。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    def totals(self) -> Totals:
        row = self.db._conn.execute(
            """SELECT
                 COUNT(*) AS session_count,
                 COALESCE(SUM(duration_ms), 0) AS total_monitor_ms,
                 COALESCE(SUM(valid_ms), 0) AS total_valid_ms,
                 COALESCE(SUM(paused_ms), 0) AS total_paused_ms
               FROM sessions"""
        ).fetchone()

        ev = self.db._conn.execute(
            """SELECT
                 COUNT(*) AS event_count,
                 COALESCE(SUM(duration_ms), 0) AS total_event_ms,
                 COALESCE(SUM(was_reminded), 0) AS reminded_count
               FROM posture_events"""
        ).fetchone()

        fb = self.db._conn.execute(
            "SELECT COUNT(*) AS n FROM user_feedback"
        ).fetchone()

        return Totals(
            session_count=int(row["session_count"]),
            total_monitor_ms=int(row["total_monitor_ms"]),
            total_valid_ms=int(row["total_valid_ms"]),
            total_paused_ms=int(row["total_paused_ms"]),
            total_event_ms=int(ev["total_event_ms"]),
            event_count=int(ev["event_count"]),
            reminded_count=int(ev["reminded_count"]),
            feedback_count=int(fb["n"]),
        )

    # ------------------------------------------------------------------
    def event_type_shares(self) -> list[EventTypeShare]:
        rows = self.db._conn.execute(
            """SELECT event_type, COUNT(*) AS cnt, COALESCE(SUM(duration_ms),0) AS ms
               FROM posture_events
               GROUP BY event_type
               ORDER BY cnt DESC"""
        ).fetchall()
        return [
            EventTypeShare(r["event_type"], int(r["cnt"]), int(r["ms"])) for r in rows
        ]

    def duration_distribution(self) -> list[DurationBucket]:
        """事件时长分布。空库返回全 0 桶。"""
        rows = self.db._conn.execute(
            "SELECT duration_ms FROM posture_events"
        ).fetchall()
        counts = {label: 0 for label, _, _ in DURATION_BUCKETS_MS}
        for r in rows:
            d = int(r["duration_ms"])
            for label, lo, hi in DURATION_BUCKETS_MS:
                if lo <= d < hi:
                    counts[label] += 1
                    break
        return [DurationBucket(label, counts[label]) for label, _, _ in DURATION_BUCKETS_MS]

    def session_summaries(self, limit: int = 50) -> list[SessionSummary]:
        rows = self.db._conn.execute(
            """SELECT s.session_id, s.start_ts, s.input_mode, s.duration_ms,
                      s.valid_ms, s.paused_ms, s.status,
                      COALESCE(e.ec, 0) AS event_count,
                      COALESCE(e.em, 0) AS event_ms
               FROM sessions s
               LEFT JOIN (
                   SELECT session_id, COUNT(*) AS ec, SUM(duration_ms) AS em
                   FROM posture_events GROUP BY session_id
               ) e ON e.session_id = s.session_id
               ORDER BY s.start_ts DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            SessionSummary(
                session_id=r["session_id"],
                start_ts=int(r["start_ts"]),
                input_mode=r["input_mode"],
                duration_ms=int(r["duration_ms"]),
                valid_ms=int(r["valid_ms"]),
                paused_ms=int(r["paused_ms"]),
                event_count=int(r["event_count"]),
                event_ms=int(r["event_ms"]),
                status=r["status"],
            )
            for r in rows
        ]

    def session_timeline(self, session_id: str) -> list[dict]:
        """单会话内的事件时间线（相对会话开始的秒偏移）。"""
        sess = self.db.get_session(session_id)
        if sess is None:
            return []
        start = int(sess["start_ts"])
        events = self.db.list_events(session_id)
        out = []
        for e in events:
            out.append({
                "event_id": e["event_id"],
                "start_sec": (int(e["start_ts"]) - start) / 1000.0,
                "duration_sec": int(e.get("duration_ms") or 0) / 1000.0,
                "event_type": e["event_type"],
                "max_deviation": e.get("max_deviation"),
                "was_reminded": bool(e.get("was_reminded")),
            })
        return out

    def trend(self, limit: int = 30) -> list[TrendPoint]:
        """跨会话趋势：有效率 + 事件数。按时间升序。"""
        rows = self.db._conn.execute(
            """SELECT s.session_id, s.start_ts, s.duration_ms, s.valid_ms,
                      (SELECT COUNT(*) FROM posture_events e
                       WHERE e.session_id = s.session_id) AS event_count
               FROM sessions s
               ORDER BY s.start_ts ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            dur = int(r["duration_ms"])
            valid = int(r["valid_ms"])
            out.append(
                TrendPoint(
                    session_id=r["session_id"],
                    start_ts=int(r["start_ts"]),
                    valid_ratio=(valid / dur) if dur > 0 else 0.0,
                    event_count=int(r["event_count"]),
                )
            )
        return out

    def feedback_summary(self) -> dict[str, int]:
        rows = self.db._conn.execute(
            """SELECT feedback_type, COUNT(*) AS n
               FROM user_feedback GROUP BY feedback_type"""
        ).fetchall()
        return {r["feedback_type"]: int(r["n"]) for r in rows}

    def valid_ratio_by_input_mode(self) -> list[dict]:
        """不同输入模式下的关键点有效率（相机条件代理）。"""
        rows = self.db._conn.execute(
            """SELECT input_mode,
                      COUNT(*) AS n,
                      COALESCE(SUM(duration_ms),0) AS dur,
                      COALESCE(SUM(valid_ms),0) AS val
               FROM sessions GROUP BY input_mode"""
        ).fetchall()
        out = []
        for r in rows:
            dur = int(r["dur"])
            out.append({
                "input_mode": r["input_mode"],
                "session_count": int(r["n"]),
                "valid_ratio": (int(r["val"]) / dur) if dur > 0 else 0.0,
            })
        return out
