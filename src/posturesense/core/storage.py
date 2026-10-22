"""SQLite 持久化：会话、姿态事件、用户反馈、校准基线。

设计要点:
- 原生 sqlite3（不引入 SQLAlchemy）。
- 时间戳统一 INTEGER epoch 毫秒，便于排序与区间查询。
- busy_timeout 提升并发写安全。
- 事务边界由调用方控制：Connection.commit() 显式提交。
- 迁移器：schema_version 表 + 顺序执行；**整迁移在单事务内**，
  失败整体回滚（避免上游"半应用 schema"问题）。
- 提供 delete_user_data() 满足隐私验收。

默认不保存原始视频帧、不保存人脸图像。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    start_ts     INTEGER NOT NULL,
    end_ts       INTEGER,
    input_mode   TEXT NOT NULL,          -- camera | video | image
    duration_ms  INTEGER DEFAULT 0,      -- 监测总时长
    valid_ms     INTEGER DEFAULT 0,      -- 有效检测时长
    paused_ms    INTEGER DEFAULT 0,      -- 暂停/无效时长
    baseline_id  TEXT,
    algo_version TEXT,
    status       TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS posture_events (
    event_id       TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    start_ts       INTEGER NOT NULL,
    end_ts         INTEGER,
    event_type     TEXT NOT NULL,        -- sustained_deviation | ...
    duration_ms    INTEGER DEFAULT 0,
    max_deviation  REAL,
    was_reminded   INTEGER DEFAULT 0,    -- 0/1
    valid_ratio    REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id   TEXT PRIMARY KEY,
    event_id      TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    note          TEXT DEFAULT '',
    FOREIGN KEY (event_id) REFERENCES posture_events(event_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calibration_profiles (
    profile_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    stats_json  TEXT NOT NULL,           -- FeatureStats 序列化
    version     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_events_session ON posture_events(session_id);
CREATE INDEX IF NOT EXISTS idx_feedback_event ON user_feedback(event_id);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_ts);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class StorageError(RuntimeError):
    """存储层错误。"""


class Database:
    """SQLite 连接与迁移。

    单个实例可被同一线程长期持有；跨线程各自建实例（sqlite3 连接非线程安全）。
    """

    def __init__(self, path: str | os.PathLike[str], timeout: float = 5.0) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self.path), timeout=timeout)
        except sqlite3.Error as exc:
            raise StorageError(f"无法打开数据库 {self.path}: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
        self.migrate()

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            logger.exception("关闭数据库异常")

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """显式事务：异常回滚，正常提交。"""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # 迁移
    # ------------------------------------------------------------------
    def migrate(self) -> None:
        """在单事务内应用迁移并记录版本。"""
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            current = int(row["version"]) if row else 0

            if current < SCHEMA_VERSION:
                conn.executescript(DDL)
                if row is None:
                    conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
                else:
                    conn.execute(
                        "UPDATE schema_version SET version = ?", (SCHEMA_VERSION,)
                    )
                logger.info("数据库迁移到版本 %d", SCHEMA_VERSION)
            elif current > SCHEMA_VERSION:
                raise StorageError(
                    f"数据库版本 {current} 高于程序支持的 {SCHEMA_VERSION}，请升级程序"
                )

    def schema_version(self) -> int:
        row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        return int(row["version"]) if row else 0

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------
    def insert_session(self, rec: dict) -> None:
        """rec: session_id, start_ts, input_mode, [baseline_id, algo_version, status]"""
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (session_id, start_ts, input_mode, baseline_id, algo_version, status)
                   VALUES (:session_id, :start_ts, :input_mode,
                           :baseline_id, :algo_version, :status)""",
                {
                    "baseline_id": None,
                    "algo_version": None,
                    "status": "running",
                    **rec,
                },
            )

    def finish_session(
        self,
        session_id: str,
        end_ts: int,
        duration_ms: int,
        valid_ms: int,
        paused_ms: int,
        status: str = "completed",
    ) -> bool:
        with self.transaction() as conn:
            cur = conn.execute(
                """UPDATE sessions
                   SET end_ts=?, duration_ms=?, valid_ms=?, paused_ms=?, status=?
                   WHERE session_id=?""",
                (end_ts, duration_ms, valid_ms, paused_ms, status, session_id),
            )
            return cur.rowcount > 0

    def get_session(self, session_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY start_ts DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        """删除会话及其事件/反馈（外键 CASCADE）。"""
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # posture_events
    # ------------------------------------------------------------------
    def insert_event(self, rec: dict) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO posture_events
                   (event_id, session_id, start_ts, end_ts, event_type,
                    duration_ms, max_deviation, was_reminded, valid_ratio)
                   VALUES (:event_id, :session_id, :start_ts, :end_ts, :event_type,
                           :duration_ms, :max_deviation, :was_reminded, :valid_ratio)""",
                {
                    "end_ts": None,
                    "duration_ms": 0,
                    "max_deviation": None,
                    "was_reminded": 0,
                    "valid_ratio": None,
                    **rec,
                },
            )

    def list_events(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM posture_events WHERE session_id=? ORDER BY start_ts",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # user_feedback
    # ------------------------------------------------------------------
    def insert_feedback(self, rec: dict) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO user_feedback
                   (feedback_id, event_id, feedback_type, created_at, note)
                   VALUES (:feedback_id, :event_id, :feedback_type, :created_at, :note)""",
                {"note": "", **rec},
            )

    def list_feedback(self, event_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM user_feedback WHERE event_id=? ORDER BY created_at",
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # calibration_profiles
    # ------------------------------------------------------------------
    def insert_profile(self, rec: dict) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO calibration_profiles
                   (profile_id, name, created_at, sample_count, stats_json, version)
                   VALUES (:profile_id, :name, :created_at, :sample_count,
                           :stats_json, :version)""",
                {"version": 1, **rec},
            )

    def get_profile(self, profile_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM calibration_profiles WHERE profile_id=?", (profile_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_profiles(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM calibration_profiles ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_profile(self, profile_id: str) -> bool:
        with self.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM calibration_profiles WHERE profile_id=?", (profile_id,)
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 隐私：清空全部用户数据
    # ------------------------------------------------------------------
    def delete_user_data(self) -> dict[str, int]:
        """清空所有历史数据。返回各表删除行数。"""
        counts: dict[str, int] = {}
        with self.transaction() as conn:
            for table in ("user_feedback", "posture_events", "sessions", "calibration_profiles"):
                cur = conn.execute(f"DELETE FROM {table}")
                counts[table] = cur.rowcount
        logger.info("已清空用户数据: %s", counts)
        return counts

    def count_rows(self) -> dict[str, int]:
        out = {}
        for table in ("sessions", "posture_events", "user_feedback", "calibration_profiles"):
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"])
        return out
