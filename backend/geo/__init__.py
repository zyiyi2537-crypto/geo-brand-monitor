"""Package init — only registers ORM models on Base.metadata.

Schema creation/migration has moved to alembic (see backend/alembic/). Do NOT
call Base.metadata.create_all here: it races between uvicorn --workers N
spawn processes and bypasses the migration history alembic relies on.

New tables / columns: add the ORM model below, then run
    alembic revision --autogenerate -m "..."
in backend/, review the generated file, and commit.
"""
from geo.database import Base  # noqa: F401
from geo.models.user import UserORM  # noqa: F401
from geo.models.membership import (  # noqa: F401
    AnonymousCheckUsageORM,
    ContactSubmissionORM,
    MembershipORM,
    UserCheckUsageORM,
    UserMembershipORM,
)
from geo.models.payment import PaymentSessionORM  # noqa: F401
from geo.models.detection import DetectionRecordORM  # noqa: F401
from geo.models.sentiment import (  # noqa: F401
    SentimentAccountORM,
    SentimentKnowledgeORM,
    SentimentRunLogORM,
    SentimentPlatformORM,
)
from geo.models.ai_telemetry import (  # noqa: F401
    AiTelemetryTopicORM,
    AiTelemetryRunORM,
    AiTelemetryResponseORM,
    AiTelemetryQueryHitORM,
    AiTelemetryCellInsightORM,
    AiTelemetryTopicBriefingORM,
)
