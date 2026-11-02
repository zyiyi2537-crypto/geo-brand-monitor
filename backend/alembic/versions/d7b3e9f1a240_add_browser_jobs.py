"""add browser_jobs (neutral browser-automation queue)

Revision ID: d7b3e9f1a240
Revises: c6f1a9d3e820
Create Date: 2026-06-09 12:00:00.000000

对外"浏览器自动化即服务"P0 的中性任务队列。

dispatch_tasks 焊死舆情域(run_id/topic_id,结果走 detect_hit/save_response 落
ai_telemetry_responses);browser_jobs 不带任何业务语义,只有 (engine, query) →
(answer, citations, ...),结果就地存本表。worker 用同一 pull 模型领取,claim 时
内部 dispatch_tasks 绝对优先、外部 jobs 填剩余槽,且每引擎受日上限 share 护栏。

tenant_id / idempotency_key / callback_url 为多租户网关(P1)预留,P0 可空。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7b3e9f1a240'
down_revision: Union[str, None] = 'c6f1a9d3e820'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "browser_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("query", sa.String(length=2048), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("callback_url", sa.String(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("citations_json", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("video_url", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    # claim 热路径:status+engine+priority+id;日上限计数:engine+claimed_at
    op.create_index("idx_browser_jobs_claim", "browser_jobs", ["status", "engine", "priority", "id"])
    op.create_index("idx_browser_jobs_engine_claimed", "browser_jobs", ["engine", "claimed_at"])
    op.create_index("idx_browser_jobs_claimed_by", "browser_jobs", ["claimed_by"])
    op.create_index("idx_browser_jobs_tenant", "browser_jobs", ["tenant_id"])
    op.create_index("uq_browser_jobs_idem", "browser_jobs", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_browser_jobs_idem", table_name="browser_jobs")
    op.drop_index("idx_browser_jobs_tenant", table_name="browser_jobs")
    op.drop_index("idx_browser_jobs_claimed_by", table_name="browser_jobs")
    op.drop_index("idx_browser_jobs_engine_claimed", table_name="browser_jobs")
    op.drop_index("idx_browser_jobs_claim", table_name="browser_jobs")
    op.drop_table("browser_jobs")
