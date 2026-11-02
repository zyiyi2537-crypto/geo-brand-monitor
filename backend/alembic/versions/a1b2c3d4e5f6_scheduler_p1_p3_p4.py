"""scheduler P1+P3+P4: fail-type, lease, region affinity, workers table

Revision ID: a1b2c3d4e5f6
Revises: d9e4b71a0c20
Create Date: 2026-05-18 16:00:00.000000

号池 production 化第一波:

P1 失败信号保真:
- engine_sessions.last_fail_type  最近一次失败的 enum 值
- engine_sessions.last_fail_at    最近失败时间
- engine_sessions.fail_counts_json {failure_type: count} 累计

P3 Lease + region affinity:
- engine_sessions.leased_by_worker_id  当前持有租约的 worker id
- engine_sessions.leased_until         租约过期时间(到点自动释放)
- engine_sessions.captured_from_region 上传者 region(cn-north / cn-east / ...)
- engine_sessions.captured_from_ip     上传者公网 IP(展示用,不参与逻辑)
- engine_sessions.preferred_worker_id  上次成功用过这个 session 的 worker(affinity 优先)

P4 Worker 注册:
- 新表 engine_workers
- worker 启动注册 + 30s 心跳;scheduler 用 last_heartbeat 判活

Indexes 设计:
- idx_sessions_lease:scheduler check-out 时按 (engine, status, leased_until)
  快速找"未被租出 + active"的候选
- idx_sessions_region:region affinity 查找
- idx_workers_alive:scheduler 列在线 worker
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd9e4b71a0c20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── engine_workers(新表)──────────────────────────────────
    op.create_table(
        "engine_workers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("region", sa.String(), nullable=False),
        sa.Column("egress_ip", sa.String(), nullable=True),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("registered_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_workers_alive",
        "engine_workers",
        ["status", "region", "last_heartbeat"],
    )

    # ── engine_sessions 字段扩展 ──────────────────────────────
    with op.batch_alter_table("engine_sessions") as b:
        # P1 失败信号
        b.add_column(sa.Column("last_fail_type", sa.String(), nullable=True))
        b.add_column(sa.Column("last_fail_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column(
            "fail_counts_json", sa.Text(), nullable=False, server_default="{}",
        ))
        # P3 lease + region affinity
        b.add_column(sa.Column("leased_by_worker_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("leased_until", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("captured_from_region", sa.String(), nullable=True))
        b.add_column(sa.Column("captured_from_ip", sa.String(), nullable=True))
        b.add_column(sa.Column("preferred_worker_id", sa.Integer(), nullable=True))

    op.create_index(
        "idx_sessions_lease",
        "engine_sessions",
        ["engine", "status", "leased_until"],
    )
    op.create_index(
        "idx_sessions_region",
        "engine_sessions",
        ["engine", "status", "captured_from_region"],
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_region", table_name="engine_sessions")
    op.drop_index("idx_sessions_lease", table_name="engine_sessions")
    with op.batch_alter_table("engine_sessions") as b:
        b.drop_column("preferred_worker_id")
        b.drop_column("captured_from_ip")
        b.drop_column("captured_from_region")
        b.drop_column("leased_until")
        b.drop_column("leased_by_worker_id")
        b.drop_column("fail_counts_json")
        b.drop_column("last_fail_at")
        b.drop_column("last_fail_type")
    op.drop_index("idx_workers_alive", table_name="engine_workers")
    op.drop_table("engine_workers")
