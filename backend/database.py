"""SQLite job records. Results themselves live as JSON next to their media in the work dir."""

import sqlite3
import threading
import time

import config

_lock = threading.Lock()
_conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL,          -- queued | running | done | failed
        stage TEXT,
        error TEXT,
        result_path TEXT,
        video_sha TEXT,
        sop_sha TEXT,
        created_at REAL,
        updated_at REAL
    )
""")
_conn.execute("""
    CREATE TABLE IF NOT EXISTS usage (
        day TEXT NOT NULL,             -- UTC date
        kind TEXT NOT NULL,            -- video | rules | compile
        n INTEGER NOT NULL,
        PRIMARY KEY (day, kind)
    )
""")
_conn.commit()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def take_quota(kind: str, limit: int) -> bool:
    """Count one use against a daily budget. False once the budget is spent; 0 = unlimited."""
    if limit <= 0:
        return True
    with _lock:
        row = _conn.execute("SELECT n FROM usage WHERE day = ? AND kind = ?", (_today(), kind)).fetchone()
        if row and row["n"] >= limit:
            return False
        _conn.execute(
            "INSERT INTO usage (day, kind, n) VALUES (?, ?, 1) ON CONFLICT(day, kind) DO UPDATE SET n = n + 1",
            (_today(), kind),
        )
        _conn.commit()
    return True


def quota_left(kind: str, limit: int) -> int | None:
    if limit <= 0:
        return None
    with _lock:
        row = _conn.execute("SELECT n FROM usage WHERE day = ? AND kind = ?", (_today(), kind)).fetchone()
    return max(0, limit - (row["n"] if row else 0))


def create_job(job_id: str, video_sha: str, sop_sha: str) -> None:
    now = time.time()
    with _lock:
        _conn.execute(
            "INSERT INTO jobs (id, status, stage, video_sha, sop_sha, created_at, updated_at) VALUES (?, 'queued', 'Queued', ?, ?, ?, ?)",
            (job_id, video_sha, sop_sha, now, now),
        )
        _conn.commit()


def update_job(job_id: str, **fields) -> None:
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        _conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
        _conn.commit()


def get_job(job_id: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None
