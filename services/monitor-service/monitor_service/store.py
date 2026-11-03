"""SQLite job store: tenant-scoped monitoring tasks and their live state.

One row per monitoring job. The runner updates progress rows; the API reads
them. Everything is persisted so a service restart never loses queue state,
which fixes the in-memory job limitation of the old unified backend.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    brand TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    total_questions INTEGER NOT NULL,
    completed_questions INTEGER NOT NULL DEFAULT 0,
    report_dir TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON jobs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, created_at);
"""

_ALLOWED_STATUS = {"queued", "running", "done", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, *, tenant_id: str, user_id: str, config: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid4().hex
        record = {
            "id": job_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "brand": config["brand"],
            "config": config,
            "status": "queued",
            "total_questions": len(config["questions"]),
            "completed_questions": 0,
            "report_dir": None,
            "error": None,
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
        }
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO jobs (id, tenant_id, user_id, brand, config_json, status,"
                " total_questions, completed_questions, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'queued', ?, 0, ?)",
                (job_id, tenant_id, user_id, record["brand"],
                 json.dumps(config, ensure_ascii=False), record["total_questions"],
                 record["created_at"]),
            )
        return record

    def claim_next(self) -> dict[str, Any] | None:
        """Atomically take the oldest queued job and mark it running."""
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                (_now(), row["id"]),
            )
        return self.get(row["id"])

    def update_progress(self, job_id: str, completed: int, report_dir: str | Path | None = None) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            if report_dir is not None:
                conn.execute(
                    "UPDATE jobs SET completed_questions = ?, report_dir = ? WHERE id = ?",
                    (completed, str(report_dir), job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET completed_questions = ? WHERE id = ?",
                    (completed, job_id),
                )

    def finish(self, job_id: str, *, status: str, report_dir: str | Path | None = None,
               error: str | None = None) -> None:
        if status not in _ALLOWED_STATUS:
            raise ValueError(f"未知任务状态：{status}")
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE jobs SET status = ?, report_dir = COALESCE(?, report_dir),"
                " error = ?, finished_at = ? WHERE id = ?",
                (status, str(report_dir) if report_dir else None, error, _now(), job_id),
            )

    def get(self, job_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            if tenant_id is None:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE id = ? AND tenant_id = ?", (job_id, tenant_id)
                ).fetchone()
        return self._to_dict(row) if row else None

    def list(self, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._to_dict(row) for row in rows]

    def list_all(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._to_dict(row) for row in rows]

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["config"] = json.loads(record.pop("config_json"))
        return record
