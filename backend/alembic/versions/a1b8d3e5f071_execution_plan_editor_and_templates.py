"""Execution plan editor: editable publishing plan + content templates

Revision ID: a1b8d3e5f071
Revises: e7a14b3f9c2d
Create Date: 2026-05-27 16:00:00.000000

新增:
- ai_telemetry_topic_execution_plans:加 publishing_plan_json / confirmed_at /
  confirmed_by_id / last_edited_at;status 取值集从 generating/ready/failed
  迁到 draft/confirmed/failed(旧 ready → confirmed,旧 generating → draft)
- 新表 content_templates(系统/租户/主题三级 scope,带 locked 锁版本开关)
- topic_generated_docs 加 plan_item_id / template_id / platform
- seed 5 个系统内置模板:长文 / 短文 / FAQ / 案例 / 对比
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b8d3e5f071'
down_revision: Union[str, None] = 'e7a14b3f9c2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SYSTEM_TEMPLATES = [
    {
        "name": "长文 · 深度评测",
        "kind": "长文",
        "prompt_template": (
            "针对下面这个用户搜索词,写一篇符合品牌资料调性、可以直接复制到「{{platform}}」"
            "发布的深度评测文章。\n"
            "搜索词:{{query}}\n"
            "品牌:{{brand}}  ·  行业:{{industry}}\n\n"
            "字数 {{length_min}}-{{length_max}};围绕「该问题用户最关心什么」组织 3-5 个小节,"
            "结合品牌差异点给出具体可落地的建议。\n"
            "{{brand_block}}\n\n"
            "输出严格 JSON,字段:title (≤30 字纯文本) / summary (200 字内) / body (正文)。\n"
            "正文严禁 Markdown / 列表前缀,小标题独占一行不加任何修饰符号,"
            "段间空一行;标点用中文全角。只输出 JSON,不要前后围栏。"
        ),
        "target_platforms_json": '["公众号", "知乎"]',
        "length_min": 1200, "length_max": 2000,
    },
    {
        "name": "短文 · 推荐导读",
        "kind": "短文",
        "prompt_template": (
            "针对下面这个用户搜索词,写一篇可发布在「{{platform}}」的轻量推荐短文。\n"
            "搜索词:{{query}}\n"
            "品牌:{{brand}}  ·  行业:{{industry}}\n\n"
            "字数 {{length_min}}-{{length_max}};开头 1-2 句切入问题,中间给 2-3 个核心要点,"
            "末尾自然落到品牌相关价值。轻盈、易读、贴近平台调性。\n"
            "{{brand_block}}\n\n"
            "输出严格 JSON,字段:title (≤30 字纯文本) / summary (200 字内) / body (正文)。\n"
            "正文严禁 Markdown 符号,标点中文全角。只输出 JSON,不要前后围栏。"
        ),
        "target_platforms_json": '["小红书", "抖音", "视频号"]',
        "length_min": 500, "length_max": 900,
    },
    {
        "name": "FAQ · 问答梳理",
        "kind": "FAQ",
        "prompt_template": (
            "围绕用户搜索词「{{query}}」,写一篇 FAQ 形式的内容,目标发布平台「{{platform}}」。\n"
            "品牌:{{brand}}  ·  行业:{{industry}}\n\n"
            "字数 {{length_min}}-{{length_max}};用「问题 — 回答」的对话结构整理 4-6 组用户最关心的"
            "问题与解答,回答里自然结合品牌方案,但不要硬广。每组问题用中文序号「一、二、…」开头另起一段。\n"
            "{{brand_block}}\n\n"
            "输出严格 JSON,字段:title (≤30 字纯文本) / summary (200 字内) / body (正文)。\n"
            "正文严禁 Markdown 符号 / 列表前缀,标点中文全角。只输出 JSON,不要前后围栏。"
        ),
        "target_platforms_json": '["公众号", "小红书"]',
        "length_min": 800, "length_max": 1300,
    },
    {
        "name": "案例 · 客户故事",
        "kind": "案例",
        "prompt_template": (
            "围绕用户搜索词「{{query}}」,以「典型客户故事」的视角写一篇案例文章,目标平台「{{platform}}」。\n"
            "品牌:{{brand}}  ·  行业:{{industry}}\n\n"
            "字数 {{length_min}}-{{length_max}};按「场景 — 难题 — 解法 — 结果」推进,可适度虚构"
            "细节但要符合行业常识;最后给出 1-2 句对其他读者的启示。\n"
            "{{brand_block}}\n\n"
            "输出严格 JSON,字段:title (≤30 字纯文本) / summary (200 字内) / body (正文)。\n"
            "正文严禁 Markdown 符号,标点中文全角。只输出 JSON,不要前后围栏。"
        ),
        "target_platforms_json": '["公众号", "知乎"]',
        "length_min": 900, "length_max": 1500,
    },
    {
        "name": "对比 · 选型横评",
        "kind": "对比",
        "prompt_template": (
            "围绕用户搜索词「{{query}}」,写一篇选型对比文章,目标平台「{{platform}}」。\n"
            "品牌:{{brand}}  ·  行业:{{industry}}\n\n"
            "字数 {{length_min}}-{{length_max}};列出 2-3 个常见选型维度("
            "如能力 / 价格 / 适配场景 / 服务),对比 2-3 类常见方案的差异,"
            "最后引出品牌差异点。不要贬低任何具体竞品,以「方案类型」描述。\n"
            "{{brand_block}}\n\n"
            "输出严格 JSON,字段:title (≤30 字纯文本) / summary (200 字内) / body (正文)。\n"
            "正文严禁 Markdown / 列表前缀,小节用中文序号开头,标点中文全角。"
            "只输出 JSON,不要前后围栏。"
        ),
        "target_platforms_json": '["公众号", "知乎"]',
        "length_min": 1000, "length_max": 1800,
    },
]


def upgrade() -> None:
    # 1) execution_plans 加列
    with op.batch_alter_table("ai_telemetry_topic_execution_plans", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "publishing_plan_json", sa.Text(),
            nullable=False, server_default="[]",
        ))
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("confirmed_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_edited_at", sa.DateTime(), nullable=True))

    # 2) 旧 status 迁移:ready / generating → confirmed / draft
    op.execute(
        "UPDATE ai_telemetry_topic_execution_plans "
        "SET status = 'confirmed' WHERE status = 'ready'"
    )
    op.execute(
        "UPDATE ai_telemetry_topic_execution_plans "
        "SET status = 'draft' WHERE status = 'generating'"
    )

    # 3) content_templates 表
    op.create_table(
        "content_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=8), nullable=False, server_default="tenant"),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="长文"),
        sa.Column("prompt_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_platforms_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("length_min", sa.Integer(), nullable=False, server_default="800"),
        sa.Column("length_max", sa.Integer(), nullable=False, server_default="1500"),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    with op.batch_alter_table("content_templates", schema=None) as batch_op:
        batch_op.create_index("idx_content_template_scope", ["scope"], unique=False)
        batch_op.create_index("idx_content_template_tenant", ["tenant_id"], unique=False)
        batch_op.create_index("idx_content_template_topic", ["topic_id"], unique=False)

    # 4) 种子 5 个 system 模板
    bind = op.get_bind()
    tmpl_table = sa.table(
        "content_templates",
        sa.column("scope", sa.String),
        sa.column("name", sa.String),
        sa.column("kind", sa.String),
        sa.column("prompt_template", sa.Text),
        sa.column("target_platforms_json", sa.Text),
        sa.column("length_min", sa.Integer),
        sa.column("length_max", sa.Integer),
        sa.column("locked", sa.Boolean),
    )
    bind.execute(tmpl_table.insert(), [
        {"scope": "system", "locked": False, **t} for t in SYSTEM_TEMPLATES
    ])

    # 5) topic_generated_docs 加列
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("plan_item_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("template_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("platform", sa.String(length=16), nullable=True))
        batch_op.create_index("idx_tgd_plan_item", ["plan_item_id"], unique=False)
        # FK 单独建,SQLite batch_alter_table 会自动重建表
        batch_op.create_foreign_key(
            "fk_tgd_template", "content_templates",
            ["template_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_tgd_template", type_="foreignkey")
        batch_op.drop_index("idx_tgd_plan_item")
        batch_op.drop_column("platform")
        batch_op.drop_column("template_id")
        batch_op.drop_column("plan_item_id")

    op.drop_index("idx_content_template_topic", table_name="content_templates")
    op.drop_index("idx_content_template_tenant", table_name="content_templates")
    op.drop_index("idx_content_template_scope", table_name="content_templates")
    op.drop_table("content_templates")

    op.execute(
        "UPDATE ai_telemetry_topic_execution_plans "
        "SET status = 'ready' WHERE status = 'confirmed'"
    )
    op.execute(
        "UPDATE ai_telemetry_topic_execution_plans "
        "SET status = 'generating' WHERE status = 'draft'"
    )

    with op.batch_alter_table("ai_telemetry_topic_execution_plans", schema=None) as batch_op:
        batch_op.drop_column("last_edited_at")
        batch_op.drop_column("confirmed_by_id")
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("publishing_plan_json")
