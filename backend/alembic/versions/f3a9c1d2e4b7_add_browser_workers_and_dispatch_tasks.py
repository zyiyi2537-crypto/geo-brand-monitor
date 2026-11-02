"""add browser_workers and dispatch_tasks

Revision ID: f3a9c1d2e4b7
Revises: e8f2c5d4a370
Create Date: 2026-06-03 16:00:00.000000

调度中心(dispatch center)pull 模型的两张表:

- browser_workers:多机 browser-service 自注册的 worker 注册表。worker 部署后
  只配一个 DISPATCH_CENTER_URL 就 register + 周期 heartbeat,中心据此知道有哪些
  worker、各自服务哪些引擎、出口 IP、负载、在线与否。

- dispatch_tasks:待跑的 (engine, query) 任务队列。drip 调度器把 browser 引擎的
  pending 入队,worker 用 SELECT ... FOR UPDATE SKIP LOCKED 领取(claim),跑完
  POST 结果回中心落 ai_telemetry_responses。doubao/global 引擎不入队(走 API)。

设计要点:
- dispatch_tasks.query 用 String 而非 Text,以便 (run_id, engine, query) 建唯一索引
  防重复入队(query 实际都 <200 字)。
- (status, engine, priority, id) 复合索引服务 claim 的热路径查询。
- priority:种子 query=0、扩展 query=1,claim 时种子优先。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a9c1d2e4b7'
down_revision: Union[str, None] = 'e8f2c5d4a370'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "browser_workers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_uid", sa.String(), nullable=False),
        sa.Column("hostname", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("exit_ip", sa.String(), nullable=True),
        sa.Column("engines_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(), nullable=False, server_default="offline"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("registered_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("meta_json", sa.Text(), nullable=True),
    )
    op.create_index("uq_browser_workers_uid", "browser_workers", ["worker_uid"], unique=True)

    op.create_table(
        "dispatch_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("query", sa.String(length=1024), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["ai_telemetry_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["ai_telemetry_topics.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_dispatch_tasks_claim", "dispatch_tasks", ["status", "engine", "priority", "id"])
    op.create_index("idx_dispatch_tasks_run", "dispatch_tasks", ["run_id"])
    op.create_index("idx_dispatch_tasks_claimed_by", "dispatch_tasks", ["claimed_by"])
    op.create_index(
        "uq_dispatch_tasks_run_engine_query",
        "dispatch_tasks",
        ["run_id", "engine", "query"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_dispatch_tasks_run_engine_query", table_name="dispatch_tasks")
    op.drop_index("idx_dispatch_tasks_claimed_by", table_name="dispatch_tasks")
    op.drop_index("idx_dispatch_tasks_run", table_name="dispatch_tasks")
    op.drop_index("idx_dispatch_tasks_claim", table_name="dispatch_tasks")
    op.drop_table("dispatch_tasks")
    op.drop_index("uq_browser_workers_uid", table_name="browser_workers")
    op.drop_table("browser_workers")
