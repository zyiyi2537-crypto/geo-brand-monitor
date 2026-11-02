"""Persistence for per-user GEO check history (the `/account` history tab).

Each successful check run by a logged-in user is snapshotted here so the
personal center can list past checks and replay results without having to
re-run the checker (which would also burn the user's monthly quota).
"""
import json
from datetime import datetime
from typing import Optional, Tuple, List

from sqlalchemy import desc

from geo.database import SessionLocal
from geo.models.detection import DetectionRecordORM
from geo.models.geo import GeoTestResult


def save_detection(
    user_id: int,
    result: GeoTestResult,
    mode: str = "free",
) -> Optional[int]:
    """Persist a completed check. Returns the new record id, or None on failure.

    Never raises — a history write must not break the check endpoint. Callers
    should treat this as best-effort telemetry.
    """
    try:
        snapshot = json.dumps(result.model_dump(), ensure_ascii=False, default=str)
    except Exception as exc:
        print(f"[detection_service] snapshot serialization failed: {exc}")
        return None

    db = SessionLocal()
    try:
        row = DetectionRecordORM(
            user_id=user_id,
            url=result.url,
            score=result.score,
            grade=result.grade,
            tier=result.tier,
            mode=mode,
            result_snapshot=snapshot,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception as exc:
        db.rollback()
        print(f"[detection_service] save failed for user {user_id}: {exc}")
        return None
    finally:
        db.close()


def list_detections(
    user_id: int,
    page: int = 1,
    size: int = 10,
) -> Tuple[List[DetectionRecordORM], int]:
    """Return (rows, total) for the given user, newest first."""
    page = max(page, 1)
    size = max(min(size, 100), 1)
    db = SessionLocal()
    try:
        q = db.query(DetectionRecordORM).filter(DetectionRecordORM.user_id == user_id)
        total = q.count()
        rows = (
            q.order_by(desc(DetectionRecordORM.created_at))
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return rows, total
    finally:
        db.close()


def get_detection(user_id: int, record_id: int) -> Optional[DetectionRecordORM]:
    db = SessionLocal()
    try:
        row = (
            db.query(DetectionRecordORM)
            .filter(
                DetectionRecordORM.id == record_id,
                DetectionRecordORM.user_id == user_id,
            )
            .first()
        )
        if row and row.deleted_at is not None:
            return None
        return row
    finally:
        db.close()


def delete_detection(user_id: int, record_id: int) -> bool:
    db = SessionLocal()
    try:
        row = (
            db.query(DetectionRecordORM)
            .filter(
                DetectionRecordORM.id == record_id,
                DetectionRecordORM.user_id == user_id,
            )
            .first()
        )
        if not row or row.deleted_at is not None:
            return False
        row.deleted_at = datetime.utcnow()
        db.commit()
        return True
    finally:
        db.close()
