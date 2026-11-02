"""AI 遥测话题 — ORM + Pydantic schemas.

一个用户可建多个话题(品牌/竞品/行业),每个话题 = 一个检索词 + 一组 query × 一组 AI 引擎.
启用后由 telemetry-service 每天跑一次,结果落到同一 MySQL/SQLite 库的 _runs / _responses 表.

v1(命中追踪) — Topic.target/aliases + Response.hit/hit_excerpt/source_url + QueryHit 矩阵表
v1.1(LLM 诊断) — Response.competitors/citation_domains/answer_format + CellInsight 表
v1.2(周报)    — TopicBriefing 表
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index,
)

from geo.database import Base


# ─────────────────────────── ORM ──────────────────────────────


class AiTelemetryTopicORM(Base):
    """AI 遥测话题配置.

    v1 新增 `target` 字段(被检测的检索词,如 "金诚同达律所")+ `target_aliases_json`(别名列表).
    `queries_json` 升级支持三种形态以做向后兼容:
      - list[str] (旧版,所有 query 视为 topic 创建时即存在)
      - list[{text, created_at}] (v1)
      - list[{text, created_at, cluster_id?}] (v2,picker 端聚类后保留簇归属)
    `clusters_json`:picker 端嵌入 + K-Means 出的簇元数据,跑批结果按 cluster_id 分组用。
    """
    __tablename__ = "ai_telemetry_topics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String, nullable=False)
    # v1 新增 — 检索词与别名;迁移时从 sentiment account 回填
    target = Column(String, nullable=False, default="")
    target_aliases_json = Column(Text, nullable=False, default="[]")    # list[str]
    # v2(Phase C)新增 — 行业 / 业务定位.之前只是 suggest-queries 的临时参数,
    # 现在持久化到 topic 上,编辑时可回显
    industry = Column(Text, nullable=False, default="")

    # v2(Phase C)新增 — 种子提示词列表,审核固化只增不改
    # list[{text, status, submitted_at, approved_at?, rejected_at?, reviewer_id?}]
    seed_prompts_json = Column(Text, nullable=False, default="[]")

    # v2(Phase C)起 query 项 schema 扩展加 status / submitted_at / approved_at:
    # list[str] | list[{text, created_at, cluster_id?}] | list[{text, status, submitted_at, ...}]
    # v3(Phase D)起 query 项再加 `selected`:用户从扩展池里勾选为监测对象的 ≤50 个
    queries_json = Column(Text, nullable=False, default="[]")
    clusters_json = Column(Text, nullable=False, default="[]")  # list[{cluster_id, label, size}]
    engines_json = Column(Text, nullable=False, default="[]")   # list[engine_id]
    enabled = Column(Boolean, nullable=False, default=True)

    # v3(Phase D)审核工作流:整张申请的状态机 + 资料快照
    # profile_json:6 大模块品牌资料表单(基础标识 / 品牌主体 / 服务核心 / 目标用户 / 品牌故事 / 创作边界)
    profile_json = Column(Text, nullable=False, default="{}")
    submission_status = Column(String, nullable=False, default="draft")
    # ↑ draft / pending / approved / rejected — 与 seed_prompts_json[].status 是两层:整张申请 + 单条种子词
    submitted_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    reviewer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # 主题日志:每次资料/种子/queries 变更追加一条 {at, actor_id, actor_role, field, before, after}
    topic_changelog_json = Column(Text, nullable=False, default="[]")
    # 泛化日志:种子词 → LLM 扩展 query 候选的调用记录 [{at, seed, model, expanded_count, raw_excerpt}]
    expansion_log_json = Column(Text, nullable=False, default="[]")

    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String, nullable=True)             # success / failed / running

    # v3.1 — AI 自动生成排程(2026-05-17):每个 topic 一份。
    # cron 每天 02:00 起每小时扫一次,匹配 auto_generate_time 的 topic 各触发一次。
    auto_generate_enabled = Column(Boolean, nullable=False, default=False)
    auto_generate_time = Column(String(length=8), nullable=False, default="09:00")  # "HH:MM",24h, Asia/Shanghai
    auto_generate_count = Column(Integer, nullable=False, default=3)                 # 每次跑几条 query → 几篇稿
    auto_generate_last_run_at = Column(DateTime, nullable=True)                       # 上次自动跑批的 UTC
    # 按 publish_date 自动发布开关(2026-06-09):默认开,admin 可关闭后续发文。
    # content_scheduler.publish_tick 每天 11:00 扫已审批 + auto_publish_enabled 的 topic,
    # 把执行计划里到期(publish_date<=今天)且未发布的稿真发 Mediumsly + 标记其他平台。
    auto_publish_enabled = Column(Boolean, nullable=False, default=True)

    # 修订号 — 每次任何字段改动(包括 admin 编辑 / 审核状态机迁移)都 +1。
    # 跟 topic_changelog_json 配对:changelog 第 N 条对应的就是 version=N+1 的快照。
    # 新建 topic 时 version=1;每次 _append_changelog 都 bump 一次。
    version = Column(Integer, nullable=False, default=1)

    # admin 给单 topic 配的扩展提示词,跑批组装 prompt 时拼到模板末尾。
    # 普通用户不可见;只 /workbench/accounts/:userId/topic 能编辑。
    prompt_extension = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AiTelemetryRunORM(Base):
    """单次跑批的元数据(每天每话题一行)."""
    __tablename__ = "ai_telemetry_runs"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="running")   # running / success / failed
    error = Column(Text, nullable=True)


class AiTelemetryResponseORM(Base):
    """单条 (engine × query) 的回答 + 引用 + 命中判定 + LLM 抽取字段.

    v1 新增:hit / hit_excerpt / source_url(命中判定)
    v1.1 新增:competitors_json / citation_domains_json / answer_format(LLM 跑批后异步抽取)
    """
    __tablename__ = "ai_telemetry_responses"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("ai_telemetry_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    engine = Column(String, nullable=False)
    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False, default="")
    citations_json = Column(Text, nullable=False, default="[]")
    video_url = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # v1 命中判定
    hit = Column(Boolean, nullable=False, default=False, index=True)
    hit_excerpt = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)   # 公开 chat URL,如 yiyan.baidu.com/chat/xxx

    # v1.1 LLM 异步抽取
    competitors_json = Column(Text, nullable=True)         # [{name, count, snippet}]
    citation_domains_json = Column(Text, nullable=True)    # [domain, ...]
    answer_format = Column(String, nullable=True)          # listicle/single_recommendation/report/case_study/qa
    # v1.3 提及位置(检索排名简化版):lead(开头)/ body(中段)/ tail(末尾)/ unknown
    # 未命中 (hit=False) 时为 NULL
    mention_position = Column(String, nullable=True)
    # v1.4(品牌增长页)— 品牌在 AI 答复中第几个被提到,1-based。未命中 / 未抽取时 NULL。
    # 用来聚 Top1/Top3/Top5 占比;mention_position 是段落位置(lead/body/tail),与 brand_rank 不同。
    brand_rank = Column(Integer, nullable=True)


class AiTelemetryQueryHitORM(Base):
    """(query × engine) cell 维度的当前状态 + 首次命中.

    v1 引用追踪矩阵的存储面板. Response 落库时维护:
      - 找到 (topic_id, query, engine) cell,total_runs+=1
      - 若 hit=True:total_hits+=1,first_hit_at 为空则填,first_hit_response_id 同理
      - status 重算
    """
    __tablename__ = "ai_telemetry_query_hits"
    __table_args__ = (
        UniqueConstraint("topic_id", "query", "engine", name="uq_qh_cell"),
        Index("idx_qh_topic", "topic_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False)
    query = Column(Text, nullable=False)
    engine = Column(String, nullable=False)

    status = Column(String, nullable=False, default="pending")    # pending/running/done
    first_hit_at = Column(DateTime, nullable=True)
    first_hit_response_id = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    total_runs = Column(Integer, nullable=False, default=0)
    total_hits = Column(Integer, nullable=False, default=0)


class AiTelemetryCellInsightORM(Base):
    """v1.1 — Cell 级 LLM 诊断 + 优化建议. 按需触发,按 window 缓存.

    主键含 window_end:同 cell 不同窗口可并存(历史回溯).LLM 调用昂贵,
    生命周期由 telemetry-service /cell-insight 端点管理:
      - 若 cache 同 window_end 已存在且 evidence_response_ids 没变 → 直接读
      - 否则调 LLM 生成新一行(prompt_version 加版本号方便 A/B)
    """
    __tablename__ = "ai_telemetry_cell_insights"
    __table_args__ = (
        UniqueConstraint("topic_id", "query", "engine", "window_end", "prompt_version",
                         name="uq_ci_cell_window"),
        Index("idx_ci_topic", "topic_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False)
    query = Column(Text, nullable=False)
    engine = Column(String, nullable=False)

    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)

    verdict = Column(String, nullable=False)              # hit_stable/hit_unstable/near_miss/no_signal/negative_mention
    summary = Column(Text, nullable=False, default="")
    competitors_top3_json = Column(Text, nullable=False, default="[]")     # [{name, count, snippet}]
    recommendations_json = Column(Text, nullable=False, default="[]")      # [{priority, title, action, why}]
    evidence_response_ids_json = Column(Text, nullable=False, default="[]")

    llm_model = Column(String, nullable=False, default="")
    prompt_version = Column(String, nullable=False, default="cell_v1")
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    feedback = Column(String, nullable=True)              # helpful/not_helpful/wrong


class AiTelemetryTopicBriefingORM(Base):
    """v1.2 — Topic 级周报. scheduler 每周一 09:00 北京时间跑."""
    __tablename__ = "ai_telemetry_topic_briefings"
    __table_args__ = (
        UniqueConstraint("topic_id", "period_end", "prompt_version", name="uq_tb_period"),
        Index("idx_tb_topic", "topic_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    body_md = Column(Text, nullable=False, default="")
    kpi_snapshot_json = Column(Text, nullable=False, default="{}")
    top_actions_json = Column(Text, nullable=False, default="[]")

    delivered_email_at = Column(DateTime, nullable=True)
    feedback_score = Column(Integer, nullable=True)       # 1-5 星

    llm_model = Column(String, nullable=False, default="")
    prompt_version = Column(String, nullable=False, default="briefing_v1")
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AiTelemetryTopicExecutionPlanORM(Base):
    """v3(Phase D)— 审核通过时生成的执行计划书快照.

    包含:资料 + 监测问题 + 主题/泛化日志的不变副本(后续即便 topic 被编辑也保留生成时形态)
    + 指向那次"通过即跑"的 run_id,运行进度由 _query_hits 表实时聚合.
    """
    __tablename__ = "ai_telemetry_topic_execution_plans"
    __table_args__ = (Index("idx_tep_topic", "topic_id"),)

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False)
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    generated_by_reviewer_id = Column(Integer, nullable=True)

    # 项目总体状况快照:资料 + 监测问题数 + 引擎清单
    overview_json = Column(Text, nullable=False, default="{}")
    # 主题日志快照(生成那一刻的 topic_changelog_json 副本)
    topic_changelog_snapshot_json = Column(Text, nullable=False, default="[]")
    # 泛化日志快照(生成那一刻的 expansion_log_json 副本)
    expansion_log_snapshot_json = Column(Text, nullable=False, default="[]")
    # 监测问题清单快照(approved 且 selected 的 query 文本列表)
    monitored_queries_snapshot_json = Column(Text, nullable=False, default="[]")

    run_id = Column(Integer, ForeignKey("ai_telemetry_runs.id", ondelete="SET NULL"), nullable=True)
    status = Column(String, nullable=False, default="draft")    # draft / confirmed / failed
    error = Column(Text, nullable=True)
    # 编辑器:发文计划行(列表 of PublishPlanItem 持久化字段子集)
    publishing_plan_json = Column(Text, nullable=False, default="[]")
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_id = Column(Integer, nullable=True)
    last_edited_at = Column(DateTime, nullable=True)


class ContentTemplateORM(Base):
    """内容模板 — 给执行计划里的每一行发文条目挂一个 prompt 模板.

    scope:
      - system:全局预置,运营都能用;只允许超管编辑
      - tenant:租户(用户)级模板,该用户可见可改
      - topic: 主题级模板,挂在某 topic 下,只在该 topic 编辑器里见到

    locked=True 后,prompt_template / kind 字段进入只读态(API 校验 + 前端置灰).
    模板被锁不影响其被发文计划继续引用,LLM 调用每次按"当前 prompt"渲染.
    """
    __tablename__ = "content_templates"
    __table_args__ = (
        Index("idx_content_template_scope", "scope"),
        Index("idx_content_template_tenant", "tenant_id"),
        Index("idx_content_template_topic", "topic_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(length=8), nullable=False, default="tenant")   # system / tenant / topic
    tenant_id = Column(Integer, nullable=True)
    topic_id = Column(Integer, nullable=True)
    name = Column(String(length=64), nullable=False, default="")
    kind = Column(String(length=16), nullable=False, default="长文")      # 长文/短文/FAQ/案例/测评/对比/教程/问答
    prompt_template = Column(Text, nullable=False, default="")
    target_platforms_json = Column(Text, nullable=False, default="[]")
    length_min = Column(Integer, nullable=False, default=800)
    length_max = Column(Integer, nullable=False, default=1500)
    locked = Column(Boolean, nullable=False, default=False)
    locked_at = Column(DateTime, nullable=True)
    locked_by_id = Column(Integer, nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AiTelemetryTopicSolutionORM(Base):
    """v3.3(2026-05-21)— GEO 品牌增长战略方案.

    每个 topic 至多一条(unique topic_id)。admin 在工作台为已审核通过的 topic 触发生成:
      1. 跑 geo_checker.run_geo_check 拿到 25 类诊断 → diagnosis_json
      2. 把 25 类按主题聚成 5 大短板簇 → 喂给 LLM(DeepSeek)
      3. LLM 出方案文案(诊断叙述 / 七步定制 / 6 层关键词 / 愿景) → narrative_json / keywords_json
      4. brand_snapshot_json:生成时 BrandProfile 的不变快照(方便后续重生成对比)

    状态机:idle → generating → ready / failed。
    重新生成会原地覆盖(unique topic_id),前一份的内容被换掉。
    """
    __tablename__ = "ai_telemetry_topic_solutions"
    __table_args__ = (
        UniqueConstraint("topic_id", name="uq_topic_solution"),
        Index("idx_topic_solution_topic", "topic_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(length=16), nullable=False, default="idle")  # idle / generating / ready / failed
    website_url = Column(String(length=512), nullable=False, default="")
    # 25-类扫描结果 + 5 大短板簇 + score / grade
    diagnosis_json = Column(Text, nullable=False, default="{}")
    # LLM 出的文案:诊断叙述 / 七步定制 / 执行流程 / 愿景
    narrative_json = Column(Text, nullable=False, default="{}")
    # LLM 出的 6 层关键词体系
    keywords_json = Column(Text, nullable=False, default="{}")
    # 生成时 BrandProfile 快照
    brand_snapshot_json = Column(Text, nullable=False, default="{}")
    # 生成时监测 Query 快照 — {"queries":[{text,cluster_id,seed}], "clusters":[{cluster_id,label}]}
    # 直接源于 topic.queries_json (selected=True) + topic.clusters_json,不走 LLM
    queries_snapshot_json = Column(Text, nullable=False, default="{}")
    llm_model = Column(String(length=64), nullable=False, default="")
    error = Column(Text, nullable=True)
    generated_by_admin_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TopicGeneratedDocORM(Base):
    """v3(Phase D)— 基于资料 + 通过的监测问题,LLM 生成的内容文案稿.

    生命周期:draft → pending_review → approved/rejected → published(approved 后选发布平台 / 媒体)
    publish_targets_json 不真实调外部平台 OpenAPI,只记录"标注为已发布到哪里".
    """
    __tablename__ = "topic_generated_docs"
    __table_args__ = (
        Index("idx_tgd_topic", "topic_id"),
        Index("idx_tgd_status", "status"),
        Index("idx_tgd_plan_item", "plan_item_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False)
    execution_plan_id = Column(Integer, ForeignKey("ai_telemetry_topic_execution_plans.id", ondelete="SET NULL"), nullable=True)
    # 关联到执行计划编辑器的某一行(publishing_plan_items[].id,uuid 字符串)
    plan_item_id = Column(String(length=36), nullable=True)
    # 生成时使用的模板 + 平台(plan_item 当时的快照值)
    template_id = Column(Integer, ForeignKey("content_templates.id", ondelete="SET NULL"), nullable=True)
    platform = Column(String(length=16), nullable=True)
    # 2026-05-28 — 多变体生成:同一 query 按 (creation_direction, copywriting_type) combo
    # 出多份风格不同的稿;这俩字段做 combo 标识.legacy doc 留空.
    creation_direction = Column(String(length=64), nullable=True)
    copywriting_type = Column(String(length=64), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source_query_text = Column(Text, nullable=False, default="")
    title = Column(String, nullable=False, default="")
    body_markdown = Column(Text, nullable=False, default="")
    summary = Column(Text, nullable=False, default="")          # 200 字内摘要 — 卡片用
    llm_model = Column(String, nullable=False, default="")
    generation_error = Column(Text, nullable=True)

    status = Column(String, nullable=False, default="draft")
    # ↑ draft(LLM 刚出)/ pending_review(admin 勾入审核)/ approved / rejected / published
    selected_for_review = Column(Boolean, nullable=False, default=False)
    review_decision_at = Column(DateTime, nullable=True)
    reviewer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reject_reason = Column(Text, nullable=True)
    # [{platform: "抖音"|"小红书"|"视频号"|"公众号", media: "...", url?, marked_at, marked_by}]
    publish_targets_json = Column(Text, nullable=False, default="[]")
    # v3.1 — 内容来源(2026-05-17):'ai' = AI 自动 / admin 触发生成;'user' = 用户自带稿
    source = Column(String(length=8), nullable=False, default="ai", index=True)

    # URL 级 ROI 命中(2026-05-19):AI 答复 citations_json 里出现 publish_targets[].url 时,
    # 按引擎记 response_id 列表。空 `{}` = 还没被任何引擎引过。
    # 形态:{"deepseek": [response_id, ...], "doubao": [...], ...}
    cited_by_json = Column(Text, nullable=False, default="{}")

    # ─── 平台审核结果回填(2026-06-12)────────────────────────────────
    # 运营把稿子发到平台后,把平台方审核结果填回来;rejected 的 reason 会被
    # platform_rules 的「从拒稿学习」聚合提炼成该平台的审核规则增量。
    platform_review_status = Column(String(length=16), nullable=True)   # passed / rejected
    platform_reject_reason = Column(Text, nullable=True)

    # ─── Mediumsly 推送状态(2026-05-29)─────────────────────────────
    # 由 services/mediumsly_publisher.py 写,publish endpoint 读。与
    # publish_targets_json 解耦:后者是 admin 手动标注,这 4 列追踪自动外发结果。
    #   - 有 mediumsly_post_id → publisher 走 PATCH 原地更新
    #   - 没有 → publisher 走 POST 新建(Mediumsly 那边按 email 自动 upsert user)
    #   - PATCH 收到 404 → publisher 把 mediumsly_post_id 清空 + 写错误,下次重试自动 fallback POST
    # 见 docs/05-geo-integration.md(mediumsly repo)。
    mediumsly_post_id    = Column(String(length=64),  nullable=True)
    mediumsly_url        = Column(String(length=512), nullable=True)
    mediumsly_pushed_at  = Column(DateTime,           nullable=True)
    mediumsly_last_error = Column(Text,               nullable=True)


class PlatformRuleORM(Base):
    """2026-06-12 — 平台审核规则库:按发布平台存一份"审核红线"文本.

    rules_text 在生成文章时按发文行的 platform 注入 prompt(违反任何一条稿件不可用);
    pending_rules_text 是「从拒稿学习」(LLM 聚合该平台 platform_reject_reason 提炼的
    规则增量),admin 采纳后并入 rules_text、清空 pending。
    """
    __tablename__ = "platform_rules"
    __table_args__ = (Index("idx_platform_rules_platform", "platform", unique=True),)

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(length=32), nullable=False)
    rules_text = Column(Text, nullable=False, default="")
    pending_rules_text = Column(Text, nullable=False, default="")
    learned_at = Column(DateTime, nullable=True)        # 最近一次「从拒稿学习」时刻
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_by_id = Column(Integer, nullable=True)


class TopicMediaORM(Base):
    """v3.2(2026-05-18)— 用户为某 topic 上传的图片 / 视频素材.

    资料上传弹窗里两类东西:
      - 文本类(.txt/.md/.docx/PDF):走 /profile/extract*,LLM 抽完直接回填资料表单,
        不持久化原文件;
      - 媒体类(.jpg/.png/.mp4/...):走本表 — 直接落盘 + 数据库登记一条,
        后续做内容生稿 / 发文时作为素材库引用。

    storage_path 是 data/topic_media/{topic_id}/{uuid}.{ext} 的相对路径;
    GET /media/{id}/blob 流式返回时拼回根目录读。
    """
    __tablename__ = "topic_media"
    __table_args__ = (
        Index("idx_topic_media_topic", "topic_id"),
        Index("idx_topic_media_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    filename = Column(String(length=255), nullable=False, default="")  # 用户上传时的原始文件名
    kind = Column(String(length=8), nullable=False, default="image")    # "image" | "video"
    mime = Column(String(length=128), nullable=False, default="")
    size = Column(Integer, nullable=False, default=0)                   # 字节数
    storage_path = Column(String(length=512), nullable=False, default="")
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ─────────────────────────── Schemas ──────────────────────────


VALID_ENGINES = {
    "deepseek", "doubao", "qwen", "wenxin", "yuanbao",
    "chatgpt", "claude", "gemini", "grok", "copilot",
}


class ClusterMeta(BaseModel):
    cluster_id: int
    label: str
    size: int


# Phase C — 审核固化:种子词 + query 的审核状态机
ReviewStatus = str  # "pending" | "approved" | "rejected"

# 2026-05-28 — 4 维场景扩展:同一 seed 并行调 4 套 LLM 模板产出 4 类长尾池
# seed 本身是中性的,scene_type 只贴在产出的 QueryItem 上
SceneType = Literal["search", "qa", "intent", "brand"]
DEFAULT_SCENE: SceneType = "search"
ALL_SCENES: tuple[SceneType, ...] = ("search", "qa", "intent", "brand")


class SeedPromptItem(BaseModel):
    text: str
    status: ReviewStatus = "pending"
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    reviewer_id: Optional[int] = None


class QueryItem(BaseModel):
    text: str
    cluster_id: Optional[int] = None
    # Phase C 审核固化:legacy 数据 migration 时默认 "approved"
    status: ReviewStatus = "approved"
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    reviewer_id: Optional[int] = None
    # Phase D 监测勾选:用户从扩展池里勾的 ≤50 个 → selected=True;legacy 数据默认 True
    selected: bool = True
    # 2026-05-20 — 用户当时从哪个种子提示词扩展出这条 query;空串表示 legacy 或没记录
    seed: str = ""
    # 2026-05-28 — 4 维场景扩展产出的标签:search/qa/intent/brand
    # legacy 数据反序列化时填默认 search
    scene_type: SceneType = DEFAULT_SCENE


# ─────────────── Phase D — 品牌资料(6 大模块) ──────────────


class BrandProfile(BaseModel):
    """用户提交资料时填的 6 大模块表单.

    资料跟 topic 一一对应,序列化进 topic.profile_json.
    必填项见各字段 Field 注解(min_length / 默认值);submit-for-review 端点会再做完整校验.
    """
    # 一、资料基础标识
    profile_name: str = Field("", max_length=128)               # 资料名称
    company_full_name: str = Field("", max_length=256)          # 公司 / 品牌全称
    company_short_name: str = Field("", max_length=64)          # 公司 / 品牌简称
    industry: str = Field("", max_length=128)                   # 所属行业 / 赛道
    # 主体类型 — 驱动扩展词风格(服务工具→功能/价格/集成;制造商→厂家/参数/OEM)。
    # 取值:service_tool / manufacturer / brand_owner / other / ""(资料抽取时 AI 判,可手改)
    entity_type: str = Field("", max_length=32)
    core_business_lines: list[str] = Field(default_factory=list, max_length=20)  # 核心业务线(多选)
    service_geo: str = Field("", max_length=256)                # 服务地域
    website: str = Field("", max_length=512)                    # 品牌官网(选填,填了体检报告直接复用,不填则跳过站内技术诊断)

    # 二、内容创作方向(都是多选)
    creation_directions: list[str] = Field(default_factory=list, max_length=20)  # 创作方向
    copywriting_types: list[str] = Field(default_factory=list, max_length=20)    # 文案类型偏好
    target_platforms: list[str] = Field(default_factory=list, max_length=20)     # 适配平台
    content_tones: list[str] = Field(default_factory=list, max_length=20)        # 内容调性偏好
    content_redlines: list[str] = Field(default_factory=list, max_length=20)     # 内容雷区 / 禁止项(选填)

    # 三、品牌主体信息
    team_size: str = Field("", max_length=64)                                    # 公司 / 团队规模(选填)
    founded_year: str = Field("", max_length=64)                                 # 成立时间 / 从业年限
    core_credentials: list[str] = Field(default_factory=list, max_length=60)     # 核心荣誉 / 背书资质
    brand_diff_tags: list[str] = Field(default_factory=list, max_length=10)      # 品牌差异化标签(3-5 个)

    # 四、产品 / 服务核心信息
    core_service_overview: str = Field("", max_length=2000)                      # 核心服务概述
    service_features: list[str] = Field(default_factory=list, max_length=20)     # 服务核心特点
    service_process: list[str] = Field(default_factory=list, max_length=20)      # 服务关键流程 / 环节
    target_scenarios: list[str] = Field(default_factory=list, max_length=20)     # 服务覆盖场景 / 客户类型
    service_guarantees: list[str] = Field(default_factory=list, max_length=20)   # 服务交付保障(选填)

    # 四、品牌故事与情感素材(原五,2026-05-17 起删了「目标用户与痛点」节)
    brand_story: str = Field("", max_length=2000)                                # 品牌故事 / 成立初衷
    key_person_story: str = Field("", max_length=2000)                           # 核心人物故事(选填)
    case_stories: list[str] = Field(default_factory=list, max_length=60)         # 典型案例(选填)
    brand_values: str = Field("", max_length=1000)                               # 品牌价值观 / 服务理念

    # 五、补充素材与创作边界(原七)
    available_materials: list[str] = Field(default_factory=list, max_length=20)  # 可提供的素材类型(选填)
    brand_slogan: str = Field("", max_length=256)                                # Slogan / 宣传语(选填)
    core_message: str = Field("", max_length=1000)                               # 本次内容核心信息
    extra_notes: str = Field("", max_length=2000)                                # 其他补充说明(选填)


# 资料必填字段清单 — submit-for-review 校验用。
# 「内容创作方向」整节(creation_directions / copywriting_types / target_platforms /
# content_tones / content_redlines)2026-05-17 起从资料表单移除 — 这部分由
# 「内容发布策略」阶段决定,不再在资料里强制。schema 字段保留,老数据兼容。
# 2026-05-17 起 — 只把「一、基础标识」节的 6 个字段卡成必填.
# 2026-05-27:core_business_lines 退出必填 — 实践里很多场景一句话讲清楚业务线
# 写在 industry 里就够,空着也允许跑通.其余 5 个仍必填.
# 其他模块(品牌主体 / 产品服务 / 品牌故事 / 补充素材)都改成选填:
# 用户上传的资料是后续生稿的素材库,鼓励多填但不强迫;LLM 拿到什么用什么.
PROFILE_REQUIRED_FIELDS: tuple[str, ...] = (
    "profile_name", "company_full_name", "company_short_name",
    "industry", "service_geo",
)


class TopicChangelogEntry(BaseModel):
    at: datetime
    actor_id: Optional[int] = None
    actor_role: str = "user"                # user / admin / system
    field: str
    before: Optional[str] = None
    after: Optional[str] = None
    note: Optional[str] = None
    # 这条 changelog 写入后 topic 的 version。老条目(migration 前的)没有,允许缺省
    version: Optional[int] = None


class ExpansionLogEntry(BaseModel):
    at: datetime
    seed: str = ""
    model: str = ""
    expanded_count: int = 0
    raw_excerpt: str = ""                   # 前 300 字截断


class SubmitForReviewPayload(BaseModel):
    """提交审核 — 校验:资料必填齐 + ≥1 个 pending/approved 种子 + ≤50 个 selected query."""
    pass


# 监测问题 selected 上限(2026-05-20 起 50 → 200,扩展候选与最终勾选同上限)
MAX_SELECTED_QUERIES = 200
# 单次 seed 扩展候选上限(用户从这一批里再勾 ≤ MAX_SELECTED_QUERIES 个)
MAX_EXPANSION_CANDIDATES = 200


class MonitoredQueryItem(BaseModel):
    """用户勾选/取消勾选监测问题时的输入项."""
    text: str
    selected: bool
    # 2026-05-20 — 这条 query 当时是从哪个种子词扩展出来的(候选阶段就有),
    # 选中入库时一并持久化,后续报告 / Queries 明细按种子分组渲染。
    seed: str = ""
    # 2026-05-28 — 4 维场景标签(search/qa/intent/brand),前端从 SceneExpander 勾选时传入.
    # legacy / 老 client 不传时由后端兜底成 search.
    scene_type: SceneType = DEFAULT_SCENE


class SelectedQueriesPayload(BaseModel):
    items: list[MonitoredQueryItem] = Field(..., max_length=500)


class ProfileExtractPayload(BaseModel):
    """AI 智能填充 — 用户拖入文件或粘贴的原始文本."""
    text: str = Field(..., min_length=10, max_length=60000)


class ProfileExtractOut(BaseModel):
    profile: BrandProfile
    used_model: str
    # LLM 顺手给的种子提示词候选(3-8 条)。前端步骤 2 用它预填,用户可保留/删改。
    seed_suggestions: list[str] = Field(default_factory=list)


# ─────────────── Phase D — 执行计划书 / 内容文档 ──────────────


class TopicProgressCell(BaseModel):
    query: str
    engine: str
    status: str                          # pending / running / done
    hit: Optional[bool] = None
    last_checked_at: Optional[datetime] = None


class PublishPlanItem(BaseModel):
    """发文计划单行(GET 输出形态).

    持久化字段:id / seq / publish_date / seed / query / template_id / platform / note。
    其余字段是 GET 时实时聚合 / 联表查出来的派生值,不进 publishing_plan_json。

    seed-based 新流程:每个 approved 种子 × 5 种 system 模板 = 5 行;5 行落同一天.
    legacy query-based:每条 monitored query 一行,query 非空、seed 为 None。
    生成内容时优先用 seed(若空则 fallback 到 query),命中率聚合也按 seed 优先.

    优先级:
      - high: 监测命中率 0%(AI 完全没提及品牌,要补内容)
      - med:  0 < 命中率 < 50%(部分命中,补强)
      - low:  >= 50%(已有覆盖,可不发或低频)
    """
    # 持久化字段
    id: str                               # uuid;前端编辑稳定 id,也用来回写 doc.plan_item_id
    seq: int = 0                          # 显示顺序
    publish_date: str                     # YYYY-MM-DD
    seed: Optional[str] = None            # 种子提示词文本(seed-based 行;legacy 行为 None)
    query: str = ""                       # 监测 query(legacy 单选行;新行用 queries 多选)
    # 2026-06-11 — 一篇文章可挂多条监测 query(多选);生成正文时要求自然覆盖这组问题。
    # legacy 行只有 query 单值;两者同时有时 queries 优先。
    queries: list[str] = Field(default_factory=list)
    template_id: Optional[int] = None     # 旧数据 fallback 时为 None
    platform: Optional[str] = None
    note: Optional[str] = None
    # 2026-06-12 — 单行创作偏好(初始计划按模板 kind 自动分配;空则生成时用画像默认)
    creation_directions: list[str] = Field(default_factory=list)
    copywriting_types: list[str] = Field(default_factory=list)
    # 兼容字段(老前端读老数据)
    day: int = 0                          # 第几天(0=今天);新版按 seq 算
    # GET 时算
    coverage_pct: float = 0.0
    priority: str = "low"                 # high / med / low
    doc_id: Optional[int] = None
    doc_status: Optional[str] = None
    # 模板展示用(联表查 ContentTemplateORM)
    template_name: Optional[str] = None
    template_kind: Optional[str] = None
    # 模板默认平台列表(平台下拉用)
    suggested_platforms: list[str] = Field(default_factory=list)


class PlanItemDraft(BaseModel):
    """PUT /execution-plan 时前端送进来的发文行草稿.

    id 可选:为 None 表示新增行,后端补 uuid.seed / query 至少有一个非空.
    seed-based 新行:seed 非空,query 留空;
    legacy 单 query 行:query ∈ monitored,seed 留空.
    """
    id: Optional[str] = None
    seq: int = 0
    publish_date: str                     # YYYY-MM-DD
    seed: Optional[str] = None
    query: str = ""
    # 2026-06-11 — 多选监测 query;每条必 ∈ monitored。与 query 单值并存,queries 优先。
    queries: list[str] = Field(default_factory=list, max_length=50)
    template_id: int
    platform: str
    note: Optional[str] = None
    # 2026-05-28 — 单行 combo override:空数组 / 未传 → 用画像默认
    # (profile.creation_directions × profile.copywriting_types).
    # 行内非空 → 本行只跑这个 combo 子集;
    # 不会突破 GEO_CONTENT_MAX_COMBOS_PER_QUERY 上限(后端会再 cap 一次).
    creation_directions: list[str] = Field(default_factory=list, max_length=10)
    copywriting_types: list[str] = Field(default_factory=list, max_length=10)


class ExecutionPlanUpdatePayload(BaseModel):
    items: list[PlanItemDraft]


class TopicExecutionPlanOut(BaseModel):
    id: int
    topic_id: int
    generated_at: datetime
    generated_by_reviewer_id: Optional[int]
    status: str                          # draft / confirmed / failed
    error: Optional[str] = None
    # 项目总体状况
    overview: dict
    # 主题日志(快照,只增不减)
    topic_changelog: list[TopicChangelogEntry]
    # 泛化日志(快照)
    expansion_log: list[ExpansionLogEntry]
    # 监测问题清单(快照,文本数组)
    monitored_queries: list[str]
    # 运行进度 — 实时聚合,run 完成后停止变化
    run_id: Optional[int] = None
    run_status: Optional[str] = None     # running / success / failed
    progress: list[TopicProgressCell] = Field(default_factory=list)
    progress_done: int = 0
    progress_total: int = 0
    # 发文计划 — 持久化的发文行 + 实时聚合的覆盖率/文章状态
    publishing_plan: list[PublishPlanItem] = Field(default_factory=list)
    # 编辑器元信息
    confirmed_at: Optional[datetime] = None
    confirmed_by_id: Optional[int] = None
    last_edited_at: Optional[datetime] = None


# ────────────── Content Template schemas ──────────────


class ContentTemplateOut(BaseModel):
    id: int
    scope: str                            # system / tenant / topic
    tenant_id: Optional[int]
    topic_id: Optional[int]
    name: str
    kind: str
    prompt_template: str
    target_platforms: list[str] = Field(default_factory=list)
    length_min: int
    length_max: int
    locked: bool
    locked_at: Optional[datetime]
    locked_by_id: Optional[int]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class ContentTemplateCreate(BaseModel):
    scope: Literal["system", "tenant", "topic"] = "tenant"
    topic_id: Optional[int] = None
    name: str
    kind: str = "长文"
    prompt_template: str
    target_platforms: list[str] = Field(default_factory=list)
    length_min: int = 800
    length_max: int = 1500


class ContentTemplateUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    prompt_template: Optional[str] = None
    target_platforms: Optional[list[str]] = None
    length_min: Optional[int] = None
    length_max: Optional[int] = None


class GeneratedDocOut(BaseModel):
    id: int
    topic_id: int
    execution_plan_id: Optional[int]
    created_at: datetime
    source_query_text: str
    title: str
    body_markdown: str
    summary: str
    llm_model: str
    generation_error: Optional[str]
    status: str
    selected_for_review: bool
    review_decision_at: Optional[datetime]
    reviewer_id: Optional[int]
    reject_reason: Optional[str]
    publish_targets: list[dict]
    # v3.1 — 'ai' / 'user'
    source: str = "ai"
    # 2026-05-19 — URL 级 ROI 命中:{engine: [response_id]}
    cited_by: dict[str, list[int]] = Field(default_factory=dict)
    # 2026-05-29 — Mediumsly 推送状态(只读;由 publisher 写,前端只展示)
    mediumsly_post_id: Optional[str] = None
    mediumsly_url: Optional[str] = None
    mediumsly_pushed_at: Optional[datetime] = None
    mediumsly_last_error: Optional[str] = None
    # 2026-05-28 — 多变体生成标识(同一 query 多份稿件按这俩字段区分)
    creation_direction: Optional[str] = None
    copywriting_type: Optional[str] = None
    # 2026-06-12 — 平台审核结果回填(passed / rejected;rejected 带原因供规则学习)
    platform_review_status: Optional[str] = None
    platform_reject_reason: Optional[str] = None

    @classmethod
    def from_orm_row(cls, r: "TopicGeneratedDocORM") -> "GeneratedDocOut":
        try:
            targets = json.loads(r.publish_targets_json or "[]")
        except Exception:  # noqa: BLE001
            targets = []
        if not isinstance(targets, list):
            targets = []
        try:
            cited = json.loads(getattr(r, "cited_by_json", None) or "{}")
        except Exception:  # noqa: BLE001
            cited = {}
        if not isinstance(cited, dict):
            cited = {}
        return cls(
            id=r.id, topic_id=r.topic_id, execution_plan_id=r.execution_plan_id,
            created_at=r.created_at,
            source_query_text=r.source_query_text or "",
            title=r.title or "", body_markdown=r.body_markdown or "",
            summary=r.summary or "", llm_model=r.llm_model or "",
            generation_error=r.generation_error,
            status=r.status, selected_for_review=bool(r.selected_for_review),
            review_decision_at=r.review_decision_at, reviewer_id=r.reviewer_id,
            reject_reason=r.reject_reason, publish_targets=targets,
            source=getattr(r, "source", None) or "ai",
            cited_by=cited,
            mediumsly_post_id=getattr(r, "mediumsly_post_id", None),
            mediumsly_url=getattr(r, "mediumsly_url", None),
            mediumsly_pushed_at=getattr(r, "mediumsly_pushed_at", None),
            mediumsly_last_error=getattr(r, "mediumsly_last_error", None),
            creation_direction=getattr(r, "creation_direction", None),
            platform_review_status=getattr(r, "platform_review_status", None),
            platform_reject_reason=getattr(r, "platform_reject_reason", None),
            copywriting_type=getattr(r, "copywriting_type", None),
        )


class PublishTargetItem(BaseModel):
    platform: str = Field(..., min_length=1, max_length=32)
    media: str = Field("", max_length=128)
    url: str = Field("", max_length=512)


class PublishPayload(BaseModel):
    # 2026-05-31 — min_length 改为 0:Mediumsly 一键发布走"无手填 target,push_to_mediumsly=true"
    # 路径,publish_targets 由 publisher 成功后由后端按需合成。
    publish_targets: list[PublishTargetItem] = Field(default_factory=list, max_length=20)
    push_to_mediumsly: bool = False


# v3.1 — 用户提交 / 编辑自己写的文章
class UserDocSubmitPayload(BaseModel):
    """用户提交自己写的稿件 — POST /api/content/topics/{topic_id}/docs."""
    title: str = Field(..., min_length=1, max_length=200)
    body_markdown: str = Field(..., min_length=1, max_length=100000)
    summary: str = Field("", max_length=500)
    # 关联监测问题(可选,影响后续效果归因);为空 = 自由稿
    source_query_text: str = Field("", max_length=1000)
    # "draft" = 仅保存,留在用户侧;"pending_review" = 直接进 admin 队列
    submit_for_review: bool = False


class UserDocUpdatePayload(BaseModel):
    """用户编辑自己的 draft / rejected 稿子."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    body_markdown: Optional[str] = Field(None, min_length=1, max_length=100000)
    summary: Optional[str] = Field(None, max_length=500)
    source_query_text: Optional[str] = Field(None, max_length=1000)


# v3.1 — AI 自动生成排程配置
class AutoGenerateConfigPayload(BaseModel):
    enabled: bool
    # "HH:MM",24h,Asia/Shanghai;后端校验格式
    time: str = Field("09:00", min_length=4, max_length=5)
    count: int = Field(3, ge=1, le=20)
    # 自动发布开关;None = 本次不改,True/False = 设置。admin 关掉即停后续按排期发文。
    publish_enabled: Optional[bool] = None


class RejectDocPayload(BaseModel):
    reason: str = Field("", max_length=500)


class SelectDocsPayload(BaseModel):
    doc_ids: list[int] = Field(..., min_length=1, max_length=100)


class TopicMediaOut(BaseModel):
    """topic 的图片 / 视频素材 — 给前端 GET /topics/{id}/media 用."""
    id: int
    topic_id: int
    filename: str
    kind: str           # "image" | "video"
    mime: str
    size: int
    # 前端拉文件的 URL — 跟 /blob 路由对齐,不暴露 storage_path
    url: str
    uploaded_at: datetime


class TopicPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    target: str = Field("", max_length=128)
    target_aliases: list[str] = Field(default_factory=list, max_length=10)
    industry: str = Field("", max_length=128)
    queries: list[str] = Field(..., min_length=1, max_length=200)
    # 与 queries 同长的 cluster_id 数组,可选;长度不齐或缺省时全部按 0 处理
    query_cluster_ids: Optional[list[int]] = None
    clusters: Optional[list[ClusterMeta]] = None
    # 2026-05-20 — 与 queries 同长,每条 query 来自哪个种子提示词(picker 端"按种子分组"用)。
    # 缺省 / 长度不齐 → 后端忽略,沿用 queries_json 里已有的 seed(若有)。
    query_seeds: Optional[list[str]] = None
    # 2026-06-11 — 与 queries 同长,4 维场景标签(search/qa/intent/brand)。
    # 缺省 / 长度不齐 → 后端忽略,沿用 queries_json 里已有的 scene_type(若有)。
    query_scene_types: Optional[list[str]] = None
    engines: list[str] = Field(..., min_length=1, max_length=10)
    enabled: bool = True
    # Phase C — 创建 / 更新时,如果用户在编辑器里填了种子提示词,把它们附带提交;
    # 后端去重 + 追加到 seed_prompts_json(status=pending),保证种子词总会进审核流。
    # 字段名跟 TopicOut.seed_prompts(SeedPromptItem 列表)区分开 — 这里只是
    # 提交的纯文本,后端补 status/timestamp 写库.
    seed_drafts: Optional[list[str]] = Field(default=None, max_length=10)
    # Phase D — 同请求一起提交品牌资料(6 大模块);后端写 profile_json + 追加 changelog.
    # None / 缺失 = 这次保存不动 profile_json(向后兼容老 client).
    profile: Optional[BrandProfile] = None
    # v1.4 — admin 给该 topic 配的扩展提示词;跑批组装 query 时拼到末尾。
    # 普通用户编辑接口忽略此字段(API 层强制清空),只 admin 工作台能写。
    prompt_extension: Optional[str] = Field(default=None, max_length=2000)


class TopicDraftPayload(BaseModel):
    """Step1 落库 — POST /topics/draft。只存品牌资料(6 大模块)+ 基础字段,
    queries/engines 允许为空,submission_status=draft;后续 step3 再用
    PUT /topics/{id} 补 queries/engines + 走提交审核。"""
    name: str = Field("", max_length=128)
    target: str = Field("", max_length=128)
    target_aliases: list[str] = Field(default_factory=list, max_length=10)
    industry: str = Field("", max_length=128)
    engines: list[str] = Field(default_factory=list, max_length=10)
    enabled: bool = True
    profile: Optional[BrandProfile] = None


class SeedPromptSubmitPayload(BaseModel):
    """甲方追加新种子词 — POST /topics/{id}/seed-prompts."""
    text: str = Field(..., min_length=1, max_length=256)


class TopicOut(BaseModel):
    id: int
    name: str
    target: str
    target_aliases: list[str]
    industry: str
    queries: list[str]
    query_cluster_ids: list[int]
    # Phase C — 跟 queries 同长的 status 数组,便于前端徽章渲染
    query_statuses: list[ReviewStatus]
    # Phase D — 跟 queries 同长的 selected 数组(用户勾选为监测问题的标志)
    query_selected: list[bool]
    # 2026-05-20 — 跟 queries 同长的种子词数组;legacy / 未记录的位为 ""
    query_seeds: list[str] = Field(default_factory=list)
    # 2026-05-26 — 跟 queries 同长的「种子原文 query」标记。is_seed=True 的 query 是
    # 由某个已批准的 seed_prompt 直接派生的副本(query.text == seed.text),默认 selected=True
    # 且 locked=True(UI 不可取消)。前端用来加 badge + filter「仅显示种子原文」。
    query_is_seed: list[bool] = Field(default_factory=list)
    # 2026-05-26 — 跟 queries 同长的 locked 标记。locked=True 时前端 picker 不可取消勾选。
    # 当前唯一锁源:is_seed=True 的 query(种子原文 query 强制入监测)。
    query_locked: list[bool] = Field(default_factory=list)
    # 2026-05-28 — 跟 queries 同长的场景标签;legacy / 未记录的位为 "search"
    query_scene_types: list[SceneType] = Field(default_factory=list)
    clusters: list[ClusterMeta]
    seed_prompts: list[SeedPromptItem]
    engines: list[str]
    enabled: bool
    last_run_at: Optional[datetime]
    last_run_status: Optional[str]
    # Phase D — 资料申请状态机
    profile: BrandProfile
    submission_status: str                  # draft / pending / approved / rejected
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    reviewer_id: Optional[int] = None
    selected_query_count: int = 0           # 当前 selected=True 的 query 数,前端徽章用
    version: int = 1                        # 修订号:每次 _append_changelog 自增,前端徽章 "v3"
    # v3.1 — AI 自动生成排程
    auto_generate_enabled: bool = False
    auto_generate_time: str = "09:00"
    auto_generate_count: int = 3
    auto_generate_last_run_at: Optional[datetime] = None
    auto_publish_enabled: bool = True       # 按 publish_date 自动发布;admin 可关
    # v1.4 — admin 配的扩展提示词;TopicOut 暴露给 admin 前端,普通用户前端不渲染。
    prompt_extension: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, r: AiTelemetryTopicORM) -> "TopicOut":
        # queries_json 兼容 4 种形态:
        #   v0: list[str]
        #   v1: list[{text, created_at}]
        #   v2 (intent cluster): list[{text, created_at, cluster_id}]
        #   v3 (Phase C 审核): list[{text, cluster_id?, status, submitted_at?, ...}]
        #   v4 (Phase D 监测勾选): list[{text, ..., selected: bool}]
        raw = json.loads(r.queries_json or "[]")
        queries: list[str] = []
        cluster_ids: list[int] = []
        statuses: list[str] = []
        selected: list[bool] = []
        query_seeds: list[str] = []
        query_is_seed: list[bool] = []
        query_locked: list[bool] = []
        query_scene_types: list[str] = []
        for q in raw:
            if isinstance(q, dict):
                t = q.get("text") or ""
                if t:
                    queries.append(t)
                    cid = q.get("cluster_id")
                    cluster_ids.append(int(cid) if isinstance(cid, int) else -1)
                    statuses.append(q.get("status") or "approved")
                    # legacy 无 selected 字段:默认 True(老话题的 query 默认都参与监测)
                    selected.append(bool(q.get("selected", True)))
                    query_seeds.append(str(q.get("seed") or ""))
                    query_is_seed.append(bool(q.get("is_seed", False)))
                    # locked 默认跟 is_seed 走 — 种子原文 query 强制锁定;
                    # 显式给了 locked 字段就尊重之
                    query_locked.append(bool(q.get("locked", q.get("is_seed", False))))
                    raw_scene = q.get("scene_type") or "search"
                    query_scene_types.append(raw_scene if raw_scene in ALL_SCENES else "search")
            elif isinstance(q, str):
                queries.append(q)
                cluster_ids.append(-1)
                statuses.append("approved")
                selected.append(True)
                query_seeds.append("")
                query_is_seed.append(False)
                query_locked.append(False)
                query_scene_types.append("search")
        clusters_raw = json.loads(r.clusters_json or "[]")
        clusters = [ClusterMeta(**c) for c in clusters_raw if isinstance(c, dict)]
        seeds_raw = json.loads(getattr(r, "seed_prompts_json", None) or "[]")
        seeds = [SeedPromptItem(**s) for s in seeds_raw if isinstance(s, dict)]
        try:
            profile_data = json.loads(getattr(r, "profile_json", None) or "{}")
        except Exception:  # noqa: BLE001
            profile_data = {}
        if not isinstance(profile_data, dict):
            profile_data = {}
        try:
            profile = BrandProfile(**profile_data)
        except Exception:  # noqa: BLE001
            profile = BrandProfile()
        return cls(
            id=r.id,
            name=r.name,
            target=r.target or "",
            target_aliases=json.loads(r.target_aliases_json or "[]"),
            industry=getattr(r, "industry", None) or "",
            queries=queries,
            query_cluster_ids=cluster_ids,
            query_statuses=statuses,
            query_selected=selected,
            query_seeds=query_seeds,
            query_is_seed=query_is_seed,
            query_locked=query_locked,
            query_scene_types=query_scene_types,
            clusters=clusters,
            seed_prompts=seeds,
            engines=json.loads(r.engines_json or "[]"),
            enabled=r.enabled,
            last_run_at=r.last_run_at,
            last_run_status=r.last_run_status,
            profile=profile,
            submission_status=getattr(r, "submission_status", None) or "draft",
            submitted_at=getattr(r, "submitted_at", None),
            approved_at=getattr(r, "approved_at", None),
            rejected_at=getattr(r, "rejected_at", None),
            reviewer_id=getattr(r, "reviewer_id", None),
            selected_query_count=sum(1 for s in selected if s),
            version=int(getattr(r, "version", 1) or 1),
            auto_generate_enabled=bool(getattr(r, "auto_generate_enabled", False) or False),
            auto_generate_time=str(getattr(r, "auto_generate_time", None) or "09:00"),
            auto_generate_count=int(getattr(r, "auto_generate_count", 3) or 3),
            auto_generate_last_run_at=getattr(r, "auto_generate_last_run_at", None),
            auto_publish_enabled=bool(getattr(r, "auto_publish_enabled", True)),
            prompt_extension=getattr(r, "prompt_extension", None),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )


class RunNowCitation(BaseModel):
    url: str
    domain: str
    title: str = ""


class RunNowResult(BaseModel):
    engine: str
    query: str
    answer: str = ""
    citations: list[RunNowCitation] = Field(default_factory=list)
    error: Optional[str] = None


class RunOut(BaseModel):
    id: int
    topic_id: int
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    error: Optional[str]
    response_count: int = 0


class AdminRunOut(BaseModel):
    """admin 跨用户跑批总览,一行 = 一次 run。"""
    run_id: int
    topic_id: int
    topic_name: str
    topic_target: str
    user_id: int
    user_email: str
    started_at: datetime
    finished_at: Optional[datetime]
    status: str                      # running / success / failed
    error: Optional[str]
    response_count: int = 0          # 该 run 的总 response 条数
    hit_count: int = 0               # response 里 hit=True 的条数
    error_count: int = 0             # response 里 error 非空的条数

    @classmethod
    def from_orm_row(cls, r, response_count: int = 0) -> "RunOut":
        return cls(
            id=r.id, topic_id=r.topic_id, status=r.status,
            started_at=r.started_at, finished_at=r.finished_at,
            error=r.error, response_count=response_count,
        )


class ResponseOut(BaseModel):
    id: int
    engine: str
    query: str
    answer: str
    citations: list[RunNowCitation]
    video_url: Optional[str]
    source_url: Optional[str] = None
    error: Optional[str]
    created_at: datetime
    hit: bool = False
    hit_excerpt: Optional[str] = None
    mention_position: Optional[str] = None
    brand_rank: Optional[int] = None


class KpiBlock(BaseModel):
    value: float
    delta_pct: Optional[float] = None    # 与上一周期相比,百分比;None 表示不可比
    sparkline: list[float] = Field(default_factory=list)  # 周期内每日序列


class TrendPoint(BaseModel):
    date: str   # YYYY-MM-DD
    values: dict[str, int]   # engine -> citation count for that day


class DomainCount(BaseModel):
    domain: str
    count: int
    pct: float                    # 0-100,本 domain 占总 citations 的百分比


class OwnedSplit(BaseModel):
    owned: int                    # 命中自家关键词的 citation 数
    other: int                    # 未命中的 citation 数
    owned_pct: float              # 0-100
    delta_pct: Optional[float] = None   # 与上一周期 owned_pct 相比


class ClusterBreakdownItem(BaseModel):
    cluster_id: int
    label: str
    query_count: int          # 这一簇里的 query 数(topic 维度,不分时段)
    response_count: int       # 本期成功 response 数(query × engine,error 不算)
    mention_count: int        # response 里有品牌词的数
    mention_rate: float       # mention_count / response_count(0 → 0.0)
    citation_count: int       # response.citations 累计


class IntentBreakdownOut(BaseModel):
    topic_id: int
    period_days: int
    brand_keywords: list[str]
    clusters: list[ClusterBreakdownItem]   # 按 size 降序
    uncategorized: ClusterBreakdownItem    # cluster_id 无匹配 / 老话题无聚类信息时的兜底桶


class OverviewOut(BaseModel):
    topic_id: int
    period_days: int
    brand_keywords: list[str]
    visibility: KpiBlock         # 0-100,品牌提及率 × 100
    citations: KpiBlock          # 引用总数
    growth: KpiBlock             # 引用增长率(= citations.delta_pct,单独成卡显示主数)
    engines_covered: KpiBlock    # 有 ≥1 成功 response 的引擎数
    engines_total: int
    trend: list[TrendPoint]      # 按天 bucket 的引用数,每天 dict[engine]=count
    engines: list[str]           # 趋势图要绘制的引擎(本期出现过的)
    top_domains: list[DomainCount]                  # 按引用次数降序前 10
    owned_split: OwnedSplit                         # 自家 vs 其他
    engine_domain_matrix: dict[str, dict[str, int]] # engine -> {domain: count},只含 top_domains
    engine_factor_matrix: dict[str, dict[str, int]] = {}  # engine -> {GEO 因子: count},本期全部 citation


# ─────────────────── v1 引用追踪 schemas ────────────────────


class QueryHitCell(BaseModel):
    """矩阵中一个 cell."""
    query: str
    engine: str
    status: str                          # pending/running/done
    first_hit_at: Optional[datetime]
    first_hit_response_id: Optional[int]
    last_checked_at: Optional[datetime]
    total_runs: int
    total_hits: int
    # 2026-05-26 — 该 (query, engine) cell 命中过的 target / alias 字面词列表
    # (扫 hit_excerpt 看含哪几个,前端用来支持「按命中词筛选」)
    aliases_hit: list[str] = Field(default_factory=list)


class EngineFirstHit(BaseModel):
    """时间线 — 一个引擎首次命中的日期(任一 query 命中即算)."""
    engine: str
    first_hit_at: Optional[datetime]
    first_hit_query: Optional[str]
    days_after_start: Optional[int]     # = (first_hit_at - topic.created_at).days,空 = 还没命中


class TrackingMatrixOut(BaseModel):
    topic_id: int
    target: str
    target_aliases: list[str]
    queries: list[str]
    engines: list[str]
    started_at: datetime                # topic.created_at
    cells: list[QueryHitCell]
    timeline: list[EngineFirstHit]
    total_runs: int                     # 该 topic 历史 run 总数
    total_cells: int                    # = len(queries) × len(engines)
    hit_cells: int                      # status=done 且 total_hits>=1
    hit_cells_pct: float                # = hit_cells / total_cells × 100


# ─────────────────── 增长报告(首次跑批 vs 当前) ──────────────────


class GrowthQueryRow(BaseModel):
    """报告里的一条监测问题 — 首次跑批结果 vs 当前累计结果。"""
    query: str
    seed: Optional[str] = None
    baseline_hit: bool
    baseline_rank: Optional[int]        # 首次跑批中最好的品牌排名(命中且抽出 rank 时),否则 None
    baseline_engines: list[str] = Field(default_factory=list)
    current_hit: bool
    current_rank: Optional[int]
    current_engines: list[str] = Field(default_factory=list)
    # new_hit(新命中)/ improved(排名提升)/ steady(持平)/ regressed(下滑)/ still_miss(仍未命中)
    status: str


class GrowthSnapshot(BaseModel):
    """一份快照的汇总指标(首次 / 当前各一份)。"""
    run_at: Optional[datetime]          # 首次=首跑 started_at;当前=生成时刻
    queries_total: int
    queries_hit: int
    hit_rate_pct: float                 # = queries_hit / queries_total × 100
    avg_rank: Optional[float]           # 命中且有 rank 的问题的平均排名
    engines_covered: int                # 有任一命中的引擎数


class GrowthReportOut(BaseModel):
    topic_id: int
    target: str
    generated_at: datetime
    has_baseline: bool                  # 是否找到首次跑批(无 run 时 False)
    baseline: GrowthSnapshot
    current: GrowthSnapshot
    rows: list[GrowthQueryRow]


# ─────────────────── v1 / v1.1 drawer 详情 ──────────────────


class CellEvidence(BaseModel):
    """drawer 里展示的"历次答复"项."""
    response_id: int
    run_id: int
    created_at: datetime
    engine: str
    query: str
    hit: bool
    hit_excerpt: Optional[str]
    source_url: Optional[str]
    answer: str
    citations: list[RunNowCitation]
    mention_position: Optional[str] = None


class CellInsightRec(BaseModel):
    priority: str                       # P0/P1/P2
    title: str
    action: str
    why: str


class CompetitorMention(BaseModel):
    name: str
    count: int
    snippet: str


class CellInsightOut(BaseModel):
    id: int
    topic_id: int
    query: str
    engine: str
    window_start: datetime
    window_end: datetime
    verdict: str
    summary: str
    competitors_top3: list[CompetitorMention]
    recommendations: list[CellInsightRec]
    answer_format: Optional[str] = None
    citation_domains: list[str] = Field(default_factory=list)
    evidence_response_ids: list[int]
    llm_model: str
    prompt_version: str
    generated_at: datetime
    feedback: Optional[str]


class CellDrawerOut(BaseModel):
    """drawer 完整内容 — cell 状态 + 历次答复 + LLM 诊断(如果有)."""
    cell: QueryHitCell
    evidence: list[CellEvidence]
    insight: Optional[CellInsightOut]    # None = 还没生成(用户点"分析"才出)


# ─────────────────── v1.2 周报 ──────────────────


class BriefingAction(BaseModel):
    priority: str                       # P0/P1/P2
    title: str
    why: str
    how: str


class BriefingOut(BaseModel):
    id: int
    topic_id: int
    period_start: datetime
    period_end: datetime
    body_md: str
    kpi_snapshot: dict
    top_actions: list[BriefingAction]
    delivered_email_at: Optional[datetime]
    feedback_score: Optional[int]
    llm_model: str
    prompt_version: str
    generated_at: datetime


class FeedbackPayload(BaseModel):
    feedback: str = Field(..., pattern="^(helpful|not_helpful|wrong)$")


class BriefingFeedbackPayload(BaseModel):
    score: int = Field(..., ge=1, le=5)


# ─────────────────── v1.3 SAIV / 竞品份额 ──────────────────────


class CompetitorShareEntry(BaseModel):
    name: str
    count: int
    pct: float                          # 该竞品 / 全行业(品牌 + 全部竞品) 提及次数 × 100


class PositionDist(BaseModel):
    """命中位置分布 — 检索排名简化版."""
    lead: int = 0
    body: int = 0
    tail: int = 0
    unknown: int = 0


class PositionBreakdown(BaseModel):
    """雷达 5 维 + 右核心指标 4 卡的口径。cell × lifetime 维度,全生命周期聚合,
    数值单调不减(历史命中也算命中)。
    visible / source / seed_coverage 分母 N×M;top3/5 分母 = 命中 cell 数(避免被未命中稀释)。"""
    top3_pct: float = 0.0           # cell 内最佳 brand_rank ≤ 3 的 cell 数 / 命中 cell 数 × 100
    top5_pct: float = 0.0           # cell 内最佳 brand_rank ≤ 5 的 cell 数 / 命中 cell 数 × 100
    visible_pct: float = 0.0        # cell 内任一 hit=True 的 cell 数 / (N×M) × 100
    source_pct: float = 0.0         # 至少一个 cell hit=True 的 query 数 / N × 100
    seed_coverage_pct: float = 0.0  # 至少 1 条扩展 query 命中过的种子数 / approved 种子总数 × 100


class EngineSlice(BaseModel):
    """某 engine 在某 group 下的单引擎切片(分母 = group 内 query 数 × 1)。"""
    engine: str
    breakdown: PositionBreakdown
    total_queries: int


class GroupBreakdown(BaseModel):
    """一组 query 的指标汇总 + 各 engine 切片(留给未来扩展;当前只有 query 组)。"""
    scope: Literal["query"]
    total_queries: int                       # N
    total_engines: int                       # M
    total_cells: int                         # = N × M
    breakdown: PositionBreakdown             # 全 engine 汇总
    by_engine: list[EngineSlice] = Field(default_factory=list)


class PositionBreakdownOut(BaseModel):
    topic_id: int
    period_days: int
    industry: str
    # 兼容字段 — 与 query_group 同值,RadarBlock 等老消费者继续读这里
    total_cells: int
    total_queries: int
    breakdown: PositionBreakdown
    industry_baseline: Optional[PositionBreakdown] = None   # 样本不足时 NULL,前端不渲染
    # 新增:全 query 组 + 各 engine 切片(用于模型多选对比)
    query_group: Optional[GroupBreakdown] = None
    engines: list[str] = Field(default_factory=list)        # topic.engines_json 顺序


class IndustryBenchmarkOut(BaseModel):
    industry: str
    sample_size: int                # 参与聚合的 topic 数
    breakdown: Optional[PositionBreakdown] = None    # 样本 <3 时 NULL


class CompetitorSubstitutionItem(BaseModel):
    """C3 竞品分析"被替代证据" — 提了竞品但没提我的 query."""
    query: str
    competitor_name: str
    competitor_count: int        # 该竞品在该 query 历次答复里被提到的总次数
    sample_response_id: int      # 用于跳转到具体证据
    sample_snippet: str          # 短摘抄


class CompetitorSubstitutionOut(BaseModel):
    topic_id: int
    period_days: int
    competitor_filter: Optional[str]   # 单竞品筛选;None=全部
    items: list[CompetitorSubstitutionItem]   # 按 competitor_count 降序
    total: int


class ShareOfVoiceOut(BaseModel):
    """声量份额 — 品牌 vs 竞品 在最近 window 内被 AI 提及次数的对比.

    SAIV(Share of AI Voice) = brand_count / (brand_count + sum(competitors.count)) × 100.
    一个 ResponseORM:hit=True 贡献 brand_count + 1;
                     competitors_json 里每条 {name, count} 贡献到对应 name 的累计.
    """
    topic_id: int
    target: str
    period_days: int                    # 统计窗口
    brand_count: int                    # 品牌在所有 Response 答复里被提到的次数
    competitors_count_total: int        # 所有竞品提及的总次数
    saiv_pct: float                     # 0-100,品牌占比
    competitors: list[CompetitorShareEntry]   # 按 count 降序 top 10
    position_dist: PositionDist         # 命中位置分布(lead/body/tail/unknown)
    optimal_rate_pct: float             # AI 答案优选率 = sum(total_hits) / sum(total_runs) × 100
    total_runs: int                     # 该 topic 累计 run 数
    sample_size: int                    # 用于聚合的 Response 行数(含 hit=False)


# ─────────────── v3.3 — GEO 品牌增长战略方案 ──────────────


class SolutionDiagnosisCheck(BaseModel):
    """诊断里单条 25-类 check 的精简快照(战略方案用,不暴露 i18n key 这种细节)."""
    category: str           # check 类别(英文 label,e.g. "Structured Data")
    status: str             # PASS / WARN / FAIL / INFO
    message: str            # 人类可读消息
    fix: Optional[str] = None


class SolutionDiagnosisCluster(BaseModel):
    """5 大短板簇 — 把 25 类聚成主题(AI 协议 / 爬虫性能 / 结构化数据 / URL & 元标签 / 安全与内容).

    `severity` 给前端排序 + 标红用:high=至少一个 FAIL,med=有 WARN 没 FAIL,low=全 PASS/INFO。
    """
    key: str                # cluster slug,e.g. "ai_protocol"
    title_zh: str           # 簇中文标题
    severity: str           # high / med / low
    summary: str            # LLM 出的本簇短板叙述(40-120 字)
    bullets: list[str] = Field(default_factory=list)   # 具体短板条目(每条 ≤ 60 字)
    checks: list[SolutionDiagnosisCheck] = Field(default_factory=list)  # 该簇里的具体 check


class SolutionDiagnosis(BaseModel):
    """完整诊断块 — geo_checker 跑的结果 + LLM 聚类后的 5 簇 + 总分."""
    url: str
    score: int              # 0-100
    grade: str              # A+/A/B/C/D/F
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    info_count: int = 0
    clusters: list[SolutionDiagnosisCluster] = Field(default_factory=list)
    # 三层执行流程(技术地基 / 内容核心 / 权重推力)— 基于 cluster 严重度自动派生
    execution_layers: list[dict] = Field(default_factory=list)
    # 原始 25 类(不聚类),前端可展开看明细
    all_checks: list[SolutionDiagnosisCheck] = Field(default_factory=list)


class SolutionSevenStepItem(BaseModel):
    """七步增长模型单步 — LLM 根据品牌定制 `core_action` / `output_value`."""
    step: int               # 1-7
    name: str               # 中文步骤名(e.g. "种子提示词搭建")
    core_goal: str          # 核心目标(短句)
    core_action: str        # 针对本品牌的执行内容(LLM 出)
    output_value: str       # 核心产出 & 价值


class SolutionKeywordTier(BaseModel):
    """关键词分层 — 一层 = 一类(品牌核心 / 产品 / 技术 / 场景 / 采购决策 / 痛点)."""
    tier: str               # tier slug,e.g. "brand_core"
    title_zh: str           # 中文层名
    description: str        # 这一层的定位(LLM 出 1 句)
    keywords: list[str] = Field(default_factory=list)   # 具体词条


class SolutionVisionItem(BaseModel):
    """预期愿景 — 行业权威 / 降低获客成本 / 全球信任 三段,LLM 据品牌定制."""
    title: str              # 子标题
    body: str               # 一段话(60-180 字)


class SolutionQueryItem(BaseModel):
    """监测 Query 快照单条 — 直接从 topic.queries_json 提取 selected=True 的项."""
    text: str
    cluster_id: int = -1    # -1 表示未分组
    seed: str = ""          # 这条 Query 当时是从哪个种子提示词扩展出来的(空串=legacy)


class SolutionQueryCluster(BaseModel):
    """监测 Query 簇标签 — 直接来自 topic.clusters_json,前端按 cluster_id 分组用."""
    cluster_id: int
    label: str


class SolutionQueriesSnapshot(BaseModel):
    """监测 Query 清单快照 — 报告生成时把用户已勾选(selected=True)的 Query 锁定下来.

    不走 LLM:数据来源是用户在「监测问题」环节自己勾选 + K-Means 聚类的结果.
    """
    clusters: list[SolutionQueryCluster] = Field(default_factory=list)
    queries: list[SolutionQueryItem] = Field(default_factory=list)


class TopicSolutionOut(BaseModel):
    """完整战略方案 — GET /topic/{id}/solution 的响应。"""
    id: int
    topic_id: int
    status: str                                      # idle / generating / ready / failed
    website_url: str
    error: Optional[str] = None
    generated_by_admin_id: Optional[int] = None
    llm_model: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 内容块 — status != ready 时各字段可能为空
    brand_snapshot: Optional[BrandProfile] = None
    diagnosis: Optional[SolutionDiagnosis] = None
    seven_steps: list[SolutionSevenStepItem] = Field(default_factory=list)
    keyword_tiers: list[SolutionKeywordTier] = Field(default_factory=list)
    vision: list[SolutionVisionItem] = Field(default_factory=list)
    queries_snapshot: Optional[SolutionQueriesSnapshot] = None


class GenerateSolutionPayload(BaseModel):
    """POST /topic/{id}/solution/generate — admin 触发生成.

    website_url 选填:不填则跳过 25 类站内技术诊断,只生成 4 块
    (品牌定位 / 七步模型 / 关键词 / 愿景).
    """
    website_url: str = Field("", max_length=512)
