from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from geo.database import Base


class DetectionRecordORM(Base):
    __tablename__ = "detection_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    url = Column(String, nullable=False)
    score = Column(Integer, nullable=True)
    grade = Column(String, nullable=True)
    tier = Column(String, nullable=True)
    mode = Column(String, nullable=False, default="free")  # 'free' | 'advanced'
    result_snapshot = Column(Text, nullable=False)  # JSON string of GeoTestResult
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    deleted_at = Column(DateTime, nullable=True, default=None)


class DetectionRecordSummary(BaseModel):
    id: int
    url: str
    score: Optional[int] = None
    grade: Optional[str] = None
    tier: Optional[str] = None
    mode: str
    created_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DetectionRecordDetail(DetectionRecordSummary):
    result: Dict[str, Any]


class DetectionRecordList(BaseModel):
    items: List[DetectionRecordSummary]
    total: int
    page: int
    size: int
