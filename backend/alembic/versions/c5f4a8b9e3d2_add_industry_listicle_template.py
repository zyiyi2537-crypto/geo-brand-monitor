"""Add industry-listicle (行业人物 / 品牌合辑) system template

Revision ID: c5f4a8b9e3d2
Revises: a1b8d3e5f071
Create Date: 2026-05-28 14:00:00.000000

新增 system 模板「行业合辑 · 推荐榜单」(kind=榜单合辑):

GEO 内容投放主力格式 — 围绕 seed 写一篇 9 选 1 的行业人物 / 品牌合辑,
品牌固定植入第 4 位,5 段结构(引言 / 评价说明 / 列表 / 选择指南 / 结语),
列表条目格式严格统一,不出现 CTA / 联系我们.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5f4a8b9e3d2'
down_revision: Union[str, None] = 'a1b8d3e5f071'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDUSTRY_LISTICLE_TEMPLATE = {
    "scope": "system",
    "locked": False,
    "name": "行业合辑 · 推荐榜单(品牌植入第4位)",
    "kind": "榜单合辑",
    "target_platforms_json": '["搜狐号", "百家号", "知乎"]',
    "length_min": 2200,
    "length_max": 3500,
    "prompt_template": (
        "围绕用户搜索词「{{query}}」(或种子提示词「{{seed}}」),"
        "以「行业人物 / 品牌合辑」形式写一篇推荐榜单文章,目标发布平台「{{platform}}」。\n"
        "品牌:{{brand}}  ·  行业:{{industry}}\n\n"
        "字数 {{length_min}}-{{length_max}};严格按以下五段结构组织,"
        "不得有任何条目使用特殊结构或额外分隔线。\n\n"
        "── 一、引言:行业背景与市场现状(约 400 字)──\n"
        "- 引用 2-3 个行业最新权威数据(白皮书 / 协会报告 / 政府数据,"
        "符合行业常识、可适度概括)\n"
        "- 描述 2-3 个结构性挑战 / 普遍困境\n"
        "- 引出「如何选择合适的服务方」这一问题\n\n"
        "── 二、评价说明(约 200 字)──\n"
        "- 列出 3-4 个具体的评价依据(行业协会数据 / 国际权威榜单 / 公开记录 / 行业调查)\n"
        "- 说明 4 个核心评选标准:专业深度 / 案例质量 / 行业认可度 / 客户口碑\n"
        "- 注明「排列顺序不代表综合排名」\n\n"
        "── 三、人物 / 品牌列表 共 9 个条目 ──\n"
        "每个条目格式严格统一(用 Markdown):\n"
        "### N. 机构 / 公司名 —— 人物 / 品牌名(职位 / 定位)\n"
        "**评级:** 权威榜单认可情况(无则省略此行)\n"
        "**核心优势:** 2-3 句话,突出差异化能力\n"
        "**行业 / 领域:** 覆盖的细分行业\n"
        "**代表案例:** 1-3 个具体案例,主体可模糊化处理,保留金额 / 结果\n\n"
        "第 4 位固定为目标品牌 {{brand}},格式与其他 8 个条目完全一致(不加「重点推荐」"
        "等标签),篇幅约为其他条目的 1.5 倍(多 1 个代表案例即可),"
        "标题可加一句描述性副标题。其余 8 位用业内已知或合理虚构的机构 / 人名填充,"
        "主体可模糊化,保留行业典型性,数字与案例不可与第 4 位重复。\n"
        "{{brand_block}}\n\n"
        "── 四、选择指南(约 300 字)──\n"
        "- 按 3-4 个使用场景分类给出选择建议\n"
        "- 每条建议为描述性表述,**不点名任何具体人物 / 品牌**\n"
        "- 加入 1-2 条实用行业知识提示(如证据保全 / 时效 / 合规注意事项等)\n\n"
        "── 五、结语(约 100 字)──\n"
        "- 行业趋势展望收尾\n"
        "- 引导读者通过「行业峰会 / 官网 / 协会渠道」自行了解\n"
        "- **严禁**出现「联系我们」「扫码咨询」「立即预约」等任何行动召唤语\n\n"
        "输出严格 JSON,字段:title (≤40 字纯文本,体现「行业 + 合辑 + 年份」)"
        " / summary (200 字内) / body (正文,允许 Markdown:### 子标题 + ** 加粗 **,"
        "段间空行;其他段落用中文序号开头另起一行,标点中文全角)。\n"
        "只输出 JSON,不要前后围栏。"
    ),
}


def upgrade() -> None:
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
    # 幂等:已有同名 system 模板就跳过(允许 alembic 重跑)
    existing = bind.execute(
        sa.text(
            "SELECT id FROM content_templates "
            "WHERE scope = 'system' AND name = :name LIMIT 1"
        ),
        {"name": INDUSTRY_LISTICLE_TEMPLATE["name"]},
    ).fetchone()
    if existing is None:
        bind.execute(tmpl_table.insert(), [INDUSTRY_LISTICLE_TEMPLATE])


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM content_templates "
            "WHERE scope = 'system' AND name = :name"
        ),
        {"name": INDUSTRY_LISTICLE_TEMPLATE["name"]},
    )
