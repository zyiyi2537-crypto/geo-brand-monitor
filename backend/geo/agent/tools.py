"""工具实现(给大模型,Pydantic AI @RunContext[AgentDeps])。

约定:
  - 读类直接调;写类先 usage_guardrail_check;接收资源 id 的先 assert_owns。
  - 入参严格 typed;非法时 raise ModelRetry(具体原因)让 DeepSeek 纠正重试(治 tool 漂)。
  - 工具只「读 / 提议写」;发布等副作用走 Method 层,模型无发布工具。

本文件先落通第一个真实工具 run_geo_checks,remaining tools are implemented incrementally;
未实现的以 ModelRetry/NotImplemented 占位,注册即生效(drop-in)。
"""
from __future__ import annotations

import asyncio
import os
import threading

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from geo.agent.deps import AgentDeps
from geo.agent.methods import usage_guardrail_check

# geo_checker 当前用模块级全局态(state._scores + _geo_checker_lock),并发会串扰。
# ★ W1 硬前置:会话作用域化。在此之前用进程级锁串行化,保证正确(牺牲并行)。
_geo_checks_lock = threading.Lock()

# 热点最近一次成功结果缓存(source -> result):取数冷却/抖动时静默回退,不向用户暴露失败。
# 进程内(每 worker 各一份);热榜数据本就是近期抓取,回退展示无碍。
_hot_cache: dict[str, dict] = {}
# 今日舆情最近一次成功结果缓存(account_id -> result):同理,sentinel 瞬时抖动时静默回退。
_sent_today_cache: dict[int, dict] = {}


# ── 付费能力门禁:种子提示词 / 落库选词需联系销售开通 ──────────────────────
# 用户可建主题、可扩展预览候选词,但「设定种子提示词」「落库选词(确认监控问题)」是付费能力。
# env AGENT_GATE_PROMPT_CONFIG=0 关闭门禁(内部/已开通账号全量放行)。
_SALES_CONTACT = (os.environ.get("AGENT_SALES_CONTACT") or "请联系您的专属销售顾问开通").strip()


def _prompt_config_gated() -> bool:
    return (os.environ.get("AGENT_GATE_PROMPT_CONFIG", "1") or "").strip().lower() not in ("0", "false", "no", "")


def _sales_gate(feature: str) -> dict:
    """门禁命中:不改数据,返回引导联系销售的结构化结果,让模型如实转达(不重试、不报错)。"""
    return {"gated": True, "feature": feature, "modified": False,
            "message": f"「{feature}」是需要开通的付费能力,当前账号暂未开通,我无法直接为你操作。{_SALES_CONTACT}。"}


class TopicInfo(BaseModel):
    topic_id: int
    name: str
    target: str
    industry: str = ""


class GeoCheckResult(BaseModel):
    url: str
    raw: dict  # generate_score 的原始打分(总分 + 分项);TODO: 收敛成稳定 schema


def _account_topic(ctx: RunContext[AgentDeps]):
    """取当前账号的主题(MVP 限 1):优先 deps.topic_id,否则取该账号唯一主题。含归属校验。"""
    from geo.models.ai_telemetry import AiTelemetryTopicORM

    db, acc = ctx.deps.db, ctx.deps.account_id
    if ctx.deps.topic_id:
        t = db.get(AiTelemetryTopicORM, ctx.deps.topic_id)
        if t is None or t.user_id != acc:
            raise ModelRetry("指定主题不存在或不属于当前账号。")
        return t
    # 多主题账号:优先「最近跑批」的主题(用户多半在看那个),其次最新创建;避免选到旧空主题
    return (
        db.query(AiTelemetryTopicORM)
        .filter(AiTelemetryTopicORM.user_id == acc)
        .order_by(AiTelemetryTopicORM.last_run_at.desc().nullslast(), AiTelemetryTopicORM.id.desc())
        .first()
    )


async def create_topic(ctx: RunContext[AgentDeps], name: str, url: str, industry: str = "") -> TopicInfo:
    """【写】新建品牌主题。MVP:**每账号限 1 个主题**,已存在则拒绝。

    name: 品牌/项目名;url: 目标站点;industry: 行业(可空)。
    """
    from geo.models.ai_telemetry import AiTelemetryTopicORM

    usage_guardrail_check(ctx.deps, "create_topic")
    db, acc = ctx.deps.db, ctx.deps.account_id
    existing = (
        db.query(AiTelemetryTopicORM).filter(AiTelemetryTopicORM.user_id == acc).first()
    )
    if existing is not None:
        raise ModelRetry(f"当前账号已有主题「{existing.name}」(MVP 限 1 个),请直接使用它,不要新建。")
    if not (name or "").strip() or not (url or "").strip():
        raise ModelRetry("name 和 url 都不能为空。")

    t = AiTelemetryTopicORM(user_id=acc, name=name.strip(), target=url.strip(), industry=industry or "")
    db.add(t)
    db.commit()
    db.refresh(t)
    ctx.deps.topic_id = t.id  # 同一对话后续工具直接复用
    return TopicInfo(topic_id=t.id, name=t.name, target=t.target, industry=t.industry or "")


async def get_topic(ctx: RunContext[AgentDeps]) -> TopicInfo | None:
    """读当前账号的主题(无则返回 null,引导用户 create_topic)。"""
    t = _account_topic(ctx)
    if t is None:
        return None
    return TopicInfo(topic_id=t.id, name=t.name, target=t.target, industry=t.industry or "")


async def run_geo_checks(ctx: RunContext[AgentDeps], categories: list[str] | None = None) -> GeoCheckResult:
    """【动作】跑 25 项 GEO 检查并打分(发起一次跑批,非纯查询;仅用户明确要「跑/检测」时调)。引擎集/调度由平台固定,不接受用户/模型指定。

    categories: 可选,限定检查项;空=全量。
    """
    from geo_checker.orchestrate import generate_score

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    url = (topic.target or "").strip()
    if not url:
        raise ModelRetry("主题缺少目标站点 URL,无法跑检查。")

    def _run() -> dict:
        with _geo_checks_lock:   # 串行化:规避 geo_checker 模块级全局态串扰(W1 会话化后可去)
            return generate_score(url, allowed_categories=categories)

    raw = await asyncio.to_thread(_run)
    return GeoCheckResult(url=url, raw=raw if isinstance(raw, dict) else {"result": raw})


async def set_seed_prompts(ctx: RunContext[AgentDeps], prompts: list[str]) -> dict:
    """【写·付费】设定/覆盖当前主题的种子提示词。**付费能力**:未开通账号会被门禁拦下、返回引导联系销售,不会真的设置。

    prompts: 种子词列表(品类/品牌相关短语)。
    """
    import json
    if _prompt_config_gated():
        return _sales_gate("设定种子提示词")
    usage_guardrail_check(ctx.deps, "set_seed_prompts")
    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    cleaned = [p.strip() for p in prompts if p and p.strip()]
    if not cleaned:
        raise ModelRetry("prompts 不能为空。")
    topic.seed_prompts_json = json.dumps(cleaned, ensure_ascii=False)
    ctx.deps.db.commit()
    return {"topic_id": topic.id, "seed_prompts": cleaned}


async def get_prompts(ctx: RunContext[AgentDeps]) -> dict:
    """读当前主题的**种子提示词 + 扩展 query**:各自数量 + 列表 + 每个种子扩展了几个。只读。

    回答「种子词有几个 / query 有多少 / 扩展了多少 / 列一下提示词」就用本工具。
    """
    import json

    topic = _account_topic(ctx)
    if topic is None:
        return {"seed_count": 0, "query_count": 0, "seeds": [], "queries": []}
    seeds = _seed_texts(topic.seed_prompts_json)
    raw_q = json.loads(topic.queries_json or "[]")
    query_texts = [q["text"] for q in raw_q if isinstance(q, dict) and q.get("text")]
    # 每个种子扩展出多少 query(query.seed 回溯)
    by_seed: dict[str, int] = {}
    for q in raw_q:
        if isinstance(q, dict) and q.get("text"):
            by_seed[q.get("seed") or "(未归属种子)"] = by_seed.get(q.get("seed") or "(未归属种子)", 0) + 1
    return {
        "topic_id": topic.id,
        "seed_count": len(seeds),
        "query_count": len(query_texts),            # = 投放/监控问题数(对齐 dashboard)
        "expansion_count": len(query_texts),         # 扩展出的 query 总数
        "seeds": seeds,                              # 种子词列表
        "expansion_by_seed": by_seed,               # 每个种子扩展了几个
        "queries": query_texts[:80],                # query 列表(截断前 80)
        "note": (f"{len(seeds)} 个种子词,扩展出 {len(query_texts)} 个 query"
                 + ("(列表已截断,只显示前 80)" if len(query_texts) > 80 else "")),
    }


async def expand_prompts(ctx: RunContext[AgentDeps], seed: str, count_per_scene: int = 10) -> dict:
    """【写*】对一个种子词做 4 维场景扩展(search/qa/intent/brand),返回候选 query 供挑选(只生成候选、不直接落库;落库用 set_selected_queries)。

    seed: 要扩展的种子词;count_per_scene: 每场景产出条数(5–50)。
    引擎/调度由平台固定,与扩展无关。挑好后用 set_selected_queries 落库。
    """
    from geo.services.topic_expand import expand_topic_seed

    usage_guardrail_check(ctx.deps, "expand_prompts")
    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    try:
        res = await expand_topic_seed(topic, seed, count_per_scene=count_per_scene)
    except ValueError as e:
        raise ModelRetry(str(e))

    flat: list[dict] = []
    seen: set[str] = set()
    for scene, info in (res.get("scenes") or {}).items():
        for q in (info.get("queries") or []):
            if q and q not in seen:
                seen.add(q)
                flat.append({"text": q, "scene": scene})
    return {"seed": res["seed"], "total": res["total_count"], "candidates": flat}


async def set_selected_queries(ctx: RunContext[AgentDeps], queries: list[str]) -> dict:
    """【写·付费】把选定的 query 落库到当前主题,供后续诊断/跑批。已存在的不重复加。**付费能力**:未开通账号会被门禁拦下、返回引导联系销售,不会真的落库。"""
    import json
    from datetime import datetime

    if _prompt_config_gated():
        return _sales_gate("提示词落库(确认监控问题)")
    usage_guardrail_check(ctx.deps, "set_selected_queries")
    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    cleaned = [q.strip() for q in queries if q and q.strip()]
    if not cleaned:
        raise ModelRetry("queries 不能为空。")
    existing = json.loads(topic.queries_json or "[]")
    by_text = {q["text"] for q in existing if isinstance(q, dict) and q.get("text")}
    now = datetime.utcnow().isoformat()
    added = 0
    for q in cleaned:
        if q not in by_text:
            existing.append({"text": q, "created_at": now, "status": "approved", "approved_at": now})
            by_text.add(q)
            added += 1
    topic.queries_json = json.dumps(existing, ensure_ascii=False)
    ctx.deps.db.commit()
    return {"topic_id": topic.id, "added": added, "query_count": len(existing)}


async def trigger_diagnosis(ctx: RunContext[AgentDeps]) -> dict:
    """【写】触发当前主题的**诊断方案生成**(异步)。后台跑 geo_checker + LLM,约 30–90s;
    完成后用 get_report 查看根因/叙述。复刻 admin 端点前置(置 generating + 落 website_url)。
    """
    from datetime import datetime

    from geo.models.ai_telemetry import AiTelemetryTopicSolutionORM
    from geo.services.solution_generator import schedule_solution_generation

    usage_guardrail_check(ctx.deps, "trigger_diagnosis")
    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    db = ctx.deps.db
    url = (topic.target or "").strip()
    sol = (
        db.query(AiTelemetryTopicSolutionORM)
        .filter(AiTelemetryTopicSolutionORM.topic_id == topic.id)
        .first()
    )
    if sol is not None and sol.status == "generating":
        return {"status": "generating", "hint": "诊断已在生成中,稍后用 get_report 查看。"}
    if sol is None:
        sol = AiTelemetryTopicSolutionORM(topic_id=topic.id)
        db.add(sol)
    sol.status = "generating"
    sol.website_url = url
    sol.error = None
    sol.generated_by_admin_id = ctx.deps.account_id
    sol.updated_at = datetime.utcnow()
    db.commit()
    schedule_solution_generation(topic_id=topic.id, website_url=url, admin_id=ctx.deps.account_id)
    return {"status": "generating", "hint": "诊断生成中(约 30–90s),稍后用 get_report 查看根因/叙述。"}


async def draft_articles(ctx: RunContext[AgentDeps], max_docs: int = 3, queries: list[str] | None = None) -> dict:
    """⚠️【写操作·生成新内容】基于选定 query **生成全新文章草稿**(异步,会真的产出文章)。

    **仅在用户明确表达"生成/写/产稿/帮我写文章/创作"等意图时才可调用。**
    用户问"今天发了哪些文章""发布了什么""看看文章""文章进度"等**查看类**问题时,
    **绝对不要调用本工具**,改用只读的 get_publish_status。拿不准是不是"要生成"就先别调,先问用户。

    max_docs: 本次生成篇数(1–20);queries: 指定 query 列表(不传则用主题已选 query)。
    """
    import json

    from geo.services.content_generator import schedule_generation

    usage_guardrail_check(ctx.deps, "draft_articles")
    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    qs = [q.strip() for q in (queries or []) if q and q.strip()] or None
    if qs is None and not json.loads(topic.queries_json or "[]"):
        raise ModelRetry("当前主题还没有 query,请先 expand_prompts + set_selected_queries,或显式传 queries。")
    try:
        md = max(1, min(int(max_docs or 3), 20))
    except (TypeError, ValueError):
        md = 3
    schedule_generation(topic_id=topic.id, max_docs=md, queries_override=qs)
    return {"status": "generating", "max_docs": md, "hint": "文章生成中(每篇约 30–90s),稍后用 get_publish_status 看进度。"}


async def get_report(ctx: RunContext[AgentDeps]) -> dict:
    """读当前主题的诊断报告(solution:根因诊断 + 叙述)。只读。无 / 未就绪时给提示。"""
    import json
    from geo.models.ai_telemetry import AiTelemetryTopicSolutionORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    sol = (
        ctx.deps.db.query(AiTelemetryTopicSolutionORM)
        .filter(AiTelemetryTopicSolutionORM.topic_id == topic.id)
        .order_by(AiTelemetryTopicSolutionORM.id.desc())
        .first()
    )
    if sol is None or sol.status != "ready":
        return {"status": (sol.status if sol else "none"), "report": None, "hint": "诊断报告尚未生成或生成中"}
    return {
        "status": sol.status,
        "diagnosis": json.loads(sol.diagnosis_json or "{}"),
        "narrative": json.loads(sol.narrative_json or "{}"),
    }


async def get_batch_results(ctx: RunContext[AgentDeps]) -> dict:
    """读最近一次跑批的真实引擎可见性(每引擎命中率原始明细)。只读;引擎/调度平台固定,用户只看结果。
    【何时用】要「最近一次跑批的每引擎命中原始明细」→ 用我;要聚合的增长/位次/竞品 → get_growth_summary。"""
    from geo.models.ai_telemetry import AiTelemetryResponseORM, AiTelemetryRunORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    run = (
        ctx.deps.db.query(AiTelemetryRunORM)
        .filter(AiTelemetryRunORM.topic_id == topic.id)
        .order_by(AiTelemetryRunORM.id.desc())
        .first()
    )
    if run is None:
        return {"status": "none", "hint": "还没有跑批结果"}
    resps = ctx.deps.db.query(AiTelemetryResponseORM).filter(AiTelemetryResponseORM.run_id == run.id).all()
    by_engine: dict[str, dict] = {}
    for r in resps:
        e = by_engine.setdefault(r.engine, {"total": 0, "hits": 0})
        e["total"] += 1
        if r.hit:
            e["hits"] += 1
    return {"run_id": run.id, "status": run.status, "response_count": len(resps), "by_engine": by_engine}


async def get_publish_status(ctx: RunContext[AgentDeps]) -> dict:
    """读当前主题文章的发布进度 + 已发布文章列表(含今日发布)。**纯只读**,不生成任何内容。
    【何时用】问「发了哪些·发布进度·已发布列表」→ 用我;要看草稿/正文/按状态列 → list_articles。

    回答「今天发了哪些文章 / 发布了什么 / 看文章」这类**查看类**问题就用本工具,绝不要调 draft_articles。
    """
    from datetime import datetime

    from sqlalchemy import func

    from geo.models.ai_telemetry import TopicGeneratedDocORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    db = ctx.deps.db
    rows = (
        db.query(TopicGeneratedDocORM.status, func.count())
        .filter(TopicGeneratedDocORM.topic_id == topic.id)
        .group_by(TopicGeneratedDocORM.status)
        .all()
    )
    agg = {s: int(c) for s, c in rows}

    # 已发布文章列表(标题 + 发布时间),并统计「今天发了哪些」
    pub = (
        db.query(TopicGeneratedDocORM)
        .filter(TopicGeneratedDocORM.topic_id == topic.id, TopicGeneratedDocORM.status == "published")
        .order_by(TopicGeneratedDocORM.mediumsly_pushed_at.desc().nullslast(), TopicGeneratedDocORM.id.desc())
        .limit(20)
        .all()
    )
    today = datetime.utcnow().date()
    recent, today_list = [], []
    for d in pub:
        ts = d.mediumsly_pushed_at or d.created_at
        item = {
            "id": d.id,
            "title": d.title or (d.source_query_text or "")[:40] or f"doc#{d.id}",
            "url": getattr(d, "mediumsly_url", None),
            "published_at": ts.isoformat() if ts else None,
        }
        recent.append(item)
        if ts and ts.date() == today:
            today_list.append(item)
    return {
        "topic_id": topic.id, "by_status": agg,
        "published": agg.get("published", 0), "total": sum(agg.values()),
        "published_today_count": len(today_list),
        "published_today": today_list,          # 今天发了哪些文章
        "recent_published": recent[:10],         # 最近已发布(最多 10 篇)
    }


async def get_growth_summary(ctx: RunContext[AgentDeps]) -> dict:
    """读品牌增长数据(从最近一次跑批的真实引擎结果聚合):每引擎命中率、品牌位次 Top1/Top3、
    高频竞品、高频被引域名、提及位置分布。只读;引擎/调度平台固定。
    【何时用】问「每引擎命中率·品牌位次·竞品·增长」→ 用我;问命中了几个 query/覆盖率 → get_query_coverage;问今日新增 → get_today_effect。"""
    import json
    from collections import Counter

    from geo.models.ai_telemetry import AiTelemetryResponseORM, AiTelemetryRunORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    run = (
        ctx.deps.db.query(AiTelemetryRunORM)
        .filter(AiTelemetryRunORM.topic_id == topic.id)
        .order_by(AiTelemetryRunORM.id.desc())
        .first()
    )
    if run is None:
        return {"status": "none", "hint": "还没有跑批结果,无法给品牌增长数据"}
    resps = ctx.deps.db.query(AiTelemetryResponseORM).filter(AiTelemetryResponseORM.run_id == run.id).all()

    engines: dict[str, dict] = {}
    top1 = top3 = hit_total = 0
    competitors: Counter = Counter()
    domains: Counter = Counter()
    positions: Counter = Counter()
    for r in resps:
        e = engines.setdefault(r.engine, {"total": 0, "hits": 0})
        e["total"] += 1
        if r.hit:
            e["hits"] += 1
            hit_total += 1
            if isinstance(r.brand_rank, int):
                if r.brand_rank <= 1:
                    top1 += 1
                if r.brand_rank <= 3:
                    top3 += 1
            if r.mention_position:
                positions[r.mention_position] += 1
        for c in (json.loads(r.competitors_json or "[]") if r.competitors_json else []):
            if isinstance(c, dict) and c.get("name"):
                competitors[c["name"]] += int(c.get("count") or 1)
        for d in (json.loads(r.citation_domains_json or "[]") if r.citation_domains_json else []):
            if d:
                domains[d] += 1

    total = len(resps)
    return {
        "run_id": run.id,
        "response_count": total,
        "hit_rate": round(hit_total / total, 3) if total else 0,
        "by_engine": {e: {**v, "hit_rate": round(v["hits"] / v["total"], 3) if v["total"] else 0} for e, v in engines.items()},
        "brand_rank": {"top1": top1, "top3": top3, "hits": hit_total},
        "top_competitors": [{"name": n, "count": c} for n, c in competitors.most_common(8)],
        "top_citation_domains": [{"domain": d, "count": c} for d, c in domains.most_common(8)],
        "mention_positions": dict(positions),
    }


async def get_query_coverage(ctx: RunContext[AgentDeps]) -> dict:
    """**累计**被 AI 引擎搜到(命中)的情况(all-time,非今天):监测 query 总数、被命中的 query 数、
    被命中的种子词数。口径与品牌增长 dashboard 一致(读 ai_telemetry_query_hits 命中追踪表)。
    【何时用】问「累计/总共 被搜到几个·命中多少·收录情况·覆盖率」→ 用我;问「今天/今日 新增」→ get_today_effect;
    问每引擎命中率/品牌位次/增长 → get_growth_summary。
    """
    import json

    from sqlalchemy import distinct, func

    from geo.models.ai_telemetry import AiTelemetryQueryHitORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    db = ctx.deps.db
    # 被命中 query → 经 queries_json 的 seed 字段回溯到种子词
    text2seed: dict[str, str] = {}
    for q in json.loads(topic.queries_json or "[]"):
        if isinstance(q, dict) and q.get("text"):
            text2seed[q["text"]] = q.get("seed") or ""

    # 命中表里 total_hits>0 的 query 全集
    hit_all = {r[0] for r in db.query(distinct(AiTelemetryQueryHitORM.query)).filter(
        AiTelemetryQueryHitORM.topic_id == topic.id, AiTelemetryQueryHitORM.total_hits > 0).all()}
    # 监控/投放问题总数 = 当前选中 query 数(queries_json),与 dashboard 一致。
    # 命中数**限定在投放集内**,保证 命中 + 未命中 = 投放(否则旧的已移除 query 命中会让总数对不上)。
    if text2seed:
        selected = set(text2seed)
        monitored = len(selected)
        hit = len(selected & hit_all)
    else:
        monitored = len(hit_all) or (db.query(func.count(distinct(AiTelemetryQueryHitORM.query))).filter(
            AiTelemetryQueryHitORM.topic_id == topic.id).scalar() or 0)
        hit = len(hit_all)
    seeds_hit = {text2seed[t] for t in hit_all if text2seed.get(t)}      # 复用 hit_all,命中 query 的种子
    seeds_total = len(_seed_texts(topic.seed_prompts_json))

    return {
        "topic_id": topic.id, "topic_name": topic.name, "scope": "all-time",
        "hit_queries": hit, "monitored_queries": monitored,
        "hit_seeds": len(seeds_hit), "seed_total": seeds_total,
        "note": "累计被 AI 引擎命中的 query / 种子词;今天的增量用 get_today_effect。" if monitored else
                "该主题暂无监测命中记录(可能未跑批或选错主题)。",
    }


def _seed_texts(raw: str | None) -> list[str]:
    """seed_prompts_json 项可能是 dict({'text':...}) 或 str —— 统一取文本。"""
    import json
    out: list[str] = []
    for s in json.loads(raw or "[]"):
        if isinstance(s, dict) and s.get("text"):
            out.append(s["text"])
        elif isinstance(s, str) and s.strip():
            out.append(s)
    return out


async def get_today_effect(ctx: RunContext[AgentDeps]) -> dict:
    """投放效果:**今日新增命中** + **累计被搜到**的问题/种子词(读命中表 query_hits,口径同品牌增长 dashboard)。只读。
    【何时用】问「今天/今日 效果·新增命中·进展」→ 用我;只问累计总数/覆盖率 → get_query_coverage;问每引擎命中率/品牌位次 → get_growth_summary。

    cumulative_* = 至今被 AI 引擎搜到的问题/种子词;today_new_hits = 今天跑批新命中的问题数。
    """
    import json
    from datetime import datetime, timedelta

    from sqlalchemy import distinct, func

    from geo.models.ai_telemetry import AiTelemetryQueryHitORM, AiTelemetryResponseORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    db, tid = ctx.deps.db, topic.id

    text2seed: dict[str, str] = {}
    for q in json.loads(topic.queries_json or "[]"):
        if isinstance(q, dict) and q.get("text"):
            text2seed[q["text"]] = q.get("seed") or ""
    seed_total = len(_seed_texts(topic.seed_prompts_json))

    # 监控/投放问题总数 = 当前选中 query 数(queries_json),与 dashboard 一致;空则回退命中表 distinct。
    selected = set(text2seed)
    monitored = len(selected) or db.query(func.count(distinct(AiTelemetryQueryHitORM.query))).filter(
        AiTelemetryQueryHitORM.topic_id == tid).scalar() or 0
    # 累计被命中 query —— **限定在投放集内**,与 get_query_coverage / list_unhit_queries 一致
    #(命中表里可能含已从投放集移除的老 query,不限定会让 命中+未命中≠投放)。
    hit_rows = [r[0] for r in db.query(AiTelemetryQueryHitORM.query).filter(
        AiTelemetryQueryHitORM.topic_id == tid, AiTelemetryQueryHitORM.total_hits > 0).all()]
    cum_hit_set = (set(hit_rows) & selected) if selected else set(hit_rows)
    cum_hit_seeds = {text2seed[x] for x in cum_hit_set if text2seed.get(x)}

    # 今日(上海时区)起点
    sh_now = datetime.utcnow() + timedelta(hours=8)
    today_start_utc = sh_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    # 今天跑批命中的去重 query(同样限定投放集内)
    today_hit = {
        r[0] for r in db.query(distinct(AiTelemetryResponseORM.query)).filter(
            AiTelemetryResponseORM.topic_id == tid,
            AiTelemetryResponseORM.hit.is_(True),
            AiTelemetryResponseORM.created_at >= today_start_utc,
        ).all()
    }
    prior_hit = {
        r[0] for r in db.query(distinct(AiTelemetryResponseORM.query)).filter(
            AiTelemetryResponseORM.topic_id == tid,
            AiTelemetryResponseORM.hit.is_(True),
            AiTelemetryResponseORM.created_at < today_start_utc,
        ).all()
    }
    if selected:
        today_hit &= selected
        prior_hit &= selected
    new_today = today_hit - prior_hit            # 今天才首次命中的 query(真正“新增”)

    ran_today = bool(today_hit)
    return {
        "topic_name": topic.name, "date": sh_now.strftime("%Y-%m-%d"),
        "today_new_hits": len(new_today),            # 真正今日新增(之前没命中、今天首次命中)
        "today_batch_hits": len(today_hit),          # 今天跑批命中的 query 数(含旧 query 复命中)
        "cumulative_hit_queries": len(cum_hit_set), "monitored_queries": monitored,
        "cumulative_hit_seeds": len(cum_hit_seeds), "seed_total": seed_total,
        "note": ("今天没有跑批,下列为累计数据。" if not ran_today
                 else f"今天跑批命中 {len(today_hit)} 个 query,其中 {len(new_today)} 个为首次命中(真正新增)。"),
    }


async def ingest_material(
    ctx: RunContext[AgentDeps], text: str | None = None, url: str | None = None, title: str = "",
) -> dict:
    """【写】把用户资料存入账号知识库(「知识库 = 用户自有资料」,**与舆情数据无关**)。可传 text,或传 url(自动抓取并提取正文)。
    供 ask_knowledge 检索 + 后续 grounding。
    """
    from geo.models.agent import AgentMaterialORM

    usage_guardrail_check(ctx.deps, "ingest_material")
    topic = _account_topic(ctx)
    body = (text or "").strip()
    source = (url or "").strip()
    if source:
        if not source.startswith(("http://", "https://")):
            raise ModelRetry("url 必须以 http:// 或 https:// 开头。")

        def _fetch() -> str:
            import requests
            from bs4 import BeautifulSoup
            r = requests.get(source, timeout=20, headers={"User-Agent": "Vigilath-Agent/1.0"})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            return soup.get_text(" ", strip=True)

        try:
            body = (await asyncio.to_thread(_fetch))[:50000]
        except Exception as e:  # noqa: BLE001
            raise ModelRetry(f"抓取 url 失败:{str(e)[:200]}")
    if not body:
        raise ModelRetry("请提供 text,或可提取正文的 url。")
    m = AgentMaterialORM(
        account_id=ctx.deps.account_id,
        topic_id=(topic.id if topic else None),
        source=source[:512],
        title=(title or source or "资料")[:512],
        text=body,
    )
    ctx.deps.db.add(m)
    ctx.deps.db.commit()
    ctx.deps.db.refresh(m)
    # 算向量(DashScope),供语义检索;失败/无 key 不阻断(ask_knowledge 回退关键词)
    embedded = False
    try:
        import json as _json

        from geo.services.embedding import embed_texts
        vecs = await embed_texts([body])
        if vecs:
            m.embedding_json = _json.dumps(vecs[0])
            ctx.deps.db.commit()
            embedded = True
    except Exception:  # noqa: BLE001
        pass
    return {"material_id": m.id, "chars": len(body), "title": m.title, "embedded": embedded}


async def ask_knowledge(ctx: RunContext[AgentDeps], query: str) -> dict:
    """检索账号**自有资料**里与 query 相关的片段(只读)。返回命中片段,你据此回答用户。
    MVP 关键词检索(后续可升级语义/向量)。
    """
    import re

    from geo.models.agent import AgentMaterialORM

    q = (query or "").strip()
    if not q:
        raise ModelRetry("query 不能为空。")
    rows = (
        ctx.deps.db.query(AgentMaterialORM)
        .filter(AgentMaterialORM.account_id == ctx.deps.account_id)
        .order_by(AgentMaterialORM.id.desc())
        .limit(200)
        .all()
    )
    if not rows:
        return {"hits": [], "hint": "账号还没有上传资料,可先用 ingest_material 添加。"}

    # 1) 语义检索(DashScope 向量)优先 —— 对有 embedding 的资料按 cosine 排
    try:
        import json as _json

        from geo.services.embedding import cosine, embed_texts
        qv = await embed_texts([q])
        if qv:
            qvec = qv[0]
            sem: list[tuple[float, dict]] = []
            for m in rows:
                if not m.embedding_json:
                    continue
                try:
                    mv = _json.loads(m.embedding_json)
                except Exception:  # noqa: BLE001
                    continue
                s = cosine(qvec, mv)
                if s > 0.2:   # 阈值过滤明显无关
                    sem.append((s, {"title": m.title, "source": m.source, "snippet": (m.text or "")[:400], "score": round(s, 3)}))
            if sem:
                sem.sort(key=lambda x: -x[0])
                return {"hits": [h for _, h in sem[:5]], "count": min(len(sem), 5), "mode": "semantic"}
    except Exception:  # noqa: BLE001 — 语义失败回退关键词
        pass

    # 2) 回退:中文 bigram 关键词检索
    def _tokens(s: str) -> list[str]:
        """中文 bigram + 英文/数字词 —— 中文无空格,whitespace 分词无效,故用 2-gram。"""
        s = s.lower()
        toks = re.findall(r"[a-z0-9]{2,}", s)            # ascii 词
        for run in re.findall(r"[一-鿿]+", s):    # 中文串 → bigram
            toks += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
        return toks

    qtoks = list(dict.fromkeys(_tokens(q)))[:40]
    scored: list[tuple[float, int, dict]] = []
    for m in rows:
        low = (m.text or "").lower()
        if not qtoks:
            continue
        hit_toks = sum(1 for t in qtoks if t in low)
        if hit_toks == 0:
            continue
        occ = sum(low.count(t) for t in qtoks)
        score = hit_toks * 2 + min(occ, 20) + (8 if q.lower() in low else 0)   # 覆盖度为主 + 频次/整句加权
        idx = next((low.find(t) for t in qtoks if low.find(t) >= 0), 0)
        start = max(0, idx - 120)
        scored.append((score, m.id, {"title": m.title, "source": m.source, "snippet": (m.text or "")[start:start + 400]}))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    hits = [h for _, _, h in scored[:5]]
    if not hits:  # 无命中 → 回退最近资料摘要
        hits = [{"title": m.title, "source": m.source, "snippet": (m.text or "")[:300]} for m in rows[:3]]
    return {"hits": hits, "count": len(hits), "mode": "keyword"}


async def confirm_template(ctx: RunContext[AgentDeps]) -> dict:
    """【写】确认发文计划(模板)→ 触发文章生成(草稿,异步)。计划状态 draft→confirmed。
    无计划时引导用 draft_articles 直接产稿。复刻 admin confirm_execution_plan。
    """
    from datetime import datetime

    from geo.models.ai_telemetry import AiTelemetryTopicExecutionPlanORM
    from geo.services.content_generator import schedule_generation

    usage_guardrail_check(ctx.deps, "confirm_template")
    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    plan = (
        ctx.deps.db.query(AiTelemetryTopicExecutionPlanORM)
        .filter(AiTelemetryTopicExecutionPlanORM.topic_id == topic.id)
        .order_by(AiTelemetryTopicExecutionPlanORM.id.desc())
        .first()
    )
    if plan is None:
        raise ModelRetry("当前主题还没有发文计划;可用 draft_articles 直接基于选定 query 产稿。")
    if plan.status != "confirmed":
        plan.status = "confirmed"
        plan.confirmed_at = datetime.utcnow()
        plan.confirmed_by_id = ctx.deps.account_id
        ctx.deps.db.commit()
    schedule_generation(topic_id=topic.id, plan_id=plan.id)
    return {"plan_id": plan.id, "status": "confirmed", "hint": "已确认模板,文章生成中(草稿)。用 get_publish_status 看进度、publish_drafts 发布。"}


async def publish_drafts(ctx: RunContext[AgentDeps], draft_ids: list[int] | None = None) -> dict:
    """【写·对外】把已生成文章**真实发布到外部平台**(outward-facing,真实外发)。

    **环境护栏**:仅当 `AGENT_ALLOW_EXTERNAL_PUBLISH=1` 才真发;否则(如测试环境)拦截不发,防误发。
    draft_ids: 指定要发的文章 id(不传 = 该主题所有有正文的稿)。
    """
    import os
    from datetime import datetime

    from geo.models.ai_telemetry import TopicGeneratedDocORM
    from geo.models.user import UserORM
    from geo.services import mediumsly_publisher

    usage_guardrail_check(ctx.deps, "publish_drafts")
    if os.environ.get("AGENT_ALLOW_EXTERNAL_PUBLISH", "0") != "1":
        return {
            "published": 0, "blocked": True,
            "hint": "外发护栏关闭(测试环境默认),未真实发布。生产侧设 AGENT_ALLOW_EXTERNAL_PUBLISH=1 才开启。",
        }
    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    db = ctx.deps.db
    user = db.get(UserORM, ctx.deps.account_id)
    if user is None:
        raise ModelRetry("找不到账号用户。")
    q = db.query(TopicGeneratedDocORM).filter(TopicGeneratedDocORM.topic_id == topic.id)
    if draft_ids:
        q = q.filter(TopicGeneratedDocORM.id.in_(draft_ids))
    docs = [d for d in q.all() if (d.body_markdown or "").strip()]
    if not docs:
        raise ModelRetry("没有可发布的文章,请先 draft_articles / confirm_template 产稿。")

    published = 0
    results: list[dict] = []
    for d in docs:
        try:
            res = await mediumsly_publisher.push(d, user, topic)
            d.mediumsly_post_id = res.post_id
            d.mediumsly_url = res.url
            d.mediumsly_pushed_at = datetime.utcnow()
            d.mediumsly_last_error = None
            d.status = "published"
            published += 1
            results.append({"doc_id": d.id, "url": res.url})
        except mediumsly_publisher.MediumslyError as e:  # 不打断其余 doc
            d.mediumsly_last_error = f"{getattr(e, 'code', None) or 'ERROR'}: {e}"
            results.append({"doc_id": d.id, "error": d.mediumsly_last_error})
    db.commit()
    return {"published": published, "total": len(docs), "results": results}


async def list_pending_articles(ctx: RunContext[AgentDeps]) -> dict:
    """列出当前主题**待审核**的文章(草稿 / 待审,含 id+标题+摘要),供用户自审。**纯只读**。

    回答「有哪些待审文章 / 要审核的文章」就用本工具。审核通过/驳回用 approve_article / reject_article。
    """
    from geo.models.ai_telemetry import TopicGeneratedDocORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    rows = (
        ctx.deps.db.query(TopicGeneratedDocORM)
        .filter(TopicGeneratedDocORM.topic_id == topic.id,
                TopicGeneratedDocORM.status.in_(["draft", "pending_review"]))
        .order_by(TopicGeneratedDocORM.id.desc()).limit(30).all()
    )
    return {
        "count": len(rows),
        "pending": [{"id": d.id, "title": d.title or (d.source_query_text or "")[:40] or f"doc#{d.id}",
                     "status": d.status, "summary": (d.summary or "")[:120]} for d in rows],
    }


async def list_articles(ctx: RunContext[AgentDeps], status: str | None = None, limit: int = 5) -> dict:
    """列出文章并**带标题+摘要+正文摘录**(可按状态:draft/pending_review/approved/published/rejected)。只读。
    【何时用】要「列多篇·按状态浏览·展示几篇」→ 用我;看某篇全文 → get_article;只看待审 → list_pending_articles;只看发布进度 → get_publish_status。

    用户要「展示/看这几篇文章、文章内容、待审文章正文、把文章发这里」时用本工具。
    要某一篇的**完整正文**用 get_article(doc_id)。
    """
    from geo.models.ai_telemetry import TopicGeneratedDocORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    q = ctx.deps.db.query(TopicGeneratedDocORM).filter(TopicGeneratedDocORM.topic_id == topic.id)
    if status in ("draft", "pending_review", "approved", "published", "rejected"):
        q = q.filter(TopicGeneratedDocORM.status == status)
    try:
        lim = max(1, min(int(limit or 5), 10))
    except (TypeError, ValueError):
        lim = 5
    rows = q.order_by(TopicGeneratedDocORM.id.desc()).limit(lim).all()
    return {
        "count": len(rows),
        "articles": [{
            "id": d.id, "title": d.title or (d.source_query_text or "")[:40] or f"doc#{d.id}",
            "status": d.status, "summary": (d.summary or "")[:200],
            "body_excerpt": (d.body_markdown or "")[:800],
            "truncated": len(d.body_markdown or "") > 800,
        } for d in rows],
        "note": "正文已截断到 800 字;要某篇完整正文用 get_article(doc_id)。" if rows else "没有符合条件的文章。",
    }


async def get_article(ctx: RunContext[AgentDeps], doc_id: int) -> dict:
    """查看**某一篇文章的完整内容**(标题/摘要/正文/状态)。只读。用户要「看/展示第 N 篇、某篇全文」时用。"""
    from geo.models.ai_telemetry import TopicGeneratedDocORM

    topic = _account_topic(ctx)
    d = ctx.deps.db.get(TopicGeneratedDocORM, doc_id)
    if d is None or topic is None or d.topic_id != topic.id:
        raise ModelRetry("找不到这篇文章,或不属于当前账号主题;先用 list_articles 看 id。")
    body = d.body_markdown or ""
    return {
        "id": d.id, "title": d.title or "(无标题)", "status": d.status,
        "summary": (d.summary or "")[:400], "body": body[:4000], "truncated": len(body) > 4000,
        "source_query": d.source_query_text or "",
    }


def _review_doc(ctx: RunContext[AgentDeps], doc_id: int, *, approve: bool, reason: str = ""):
    from datetime import datetime

    from geo.models.ai_telemetry import TopicGeneratedDocORM

    usage_guardrail_check(ctx.deps, "review_article")
    topic = _account_topic(ctx)
    d = ctx.deps.db.get(TopicGeneratedDocORM, doc_id)
    if d is None or topic is None or d.topic_id != topic.id:
        raise ModelRetry("找不到这篇文章,或它不属于当前账号主题;先用 list_pending_articles 看 id。")
    if d.status not in ("draft", "pending_review"):
        raise ModelRetry(f"文章当前 status={d.status},不可审核(只能审 草稿/待审)。")
    d.status = "approved" if approve else "rejected"
    d.review_decision_at = datetime.utcnow()
    d.reviewer_id = ctx.deps.account_id
    if approve:
        d.selected_for_review = True
        d.reject_reason = None
    else:
        d.reject_reason = (reason or "").strip()[:500]
    ctx.deps.db.commit()
    return {"id": d.id, "title": d.title, "status": d.status}


async def approve_article(ctx: RunContext[AgentDeps], doc_id: int) -> dict:
    """【写】审核**通过**一篇文章(draft/pending_review → approved)。仅在用户明确要「通过/批准」某篇时调。"""
    return _review_doc(ctx, doc_id, approve=True)


async def reject_article(ctx: RunContext[AgentDeps], doc_id: int, reason: str = "") -> dict:
    """【写】审核**驳回**一篇文章(→ rejected,带原因)。仅在用户明确要「驳回/拒绝」某篇时调。"""
    return _review_doc(ctx, doc_id, approve=False, reason=reason)


async def list_unhit_queries(ctx: RunContext[AgentDeps]) -> dict:
    """列出当前主题**投放了但还没被 AI 引擎命中(搜到)**的 query。只读。

    回答「哪几个没命中 / 没被搜到 / 未覆盖的是哪些 / 那 5 个是什么」就用本工具。
    口径:投放集(queries_json)里 命中表 total_hits=0 的 query。
    """
    import json

    from sqlalchemy import distinct

    from geo.models.ai_telemetry import AiTelemetryQueryHitORM

    topic = _account_topic(ctx)
    if topic is None:
        raise ModelRetry("当前账号还没有主题,请先 create_topic。")
    db, tid = ctx.deps.db, topic.id
    selected = [q["text"] for q in json.loads(topic.queries_json or "[]")
                if isinstance(q, dict) and q.get("text")]
    hit_set = {r[0] for r in db.query(distinct(AiTelemetryQueryHitORM.query)).filter(
        AiTelemetryQueryHitORM.topic_id == tid, AiTelemetryQueryHitORM.total_hits > 0).all()}
    unhit = [q for q in selected if q not in hit_set]
    return {
        "monitored": len(selected), "hit": len(selected) - len(unhit), "unhit_count": len(unhit),
        "unhit_queries": unhit[:60],
        "note": ("全部已命中。" if not unhit else
                 f"投放 {len(selected)} 个,{len(unhit)} 个未命中" + ("(列表已截断,只显示前 60)" if len(unhit) > 60 else "")),
    }


def _sentiment_account(ctx: RunContext[AgentDeps], active_only: bool = False):
    from geo.models.sentiment import SentimentAccountORM

    q = ctx.deps.db.query(SentimentAccountORM).filter(SentimentAccountORM.user_id == ctx.deps.account_id)
    if active_only:
        q = q.filter(SentimentAccountORM.active.is_(True))
    return q.order_by(SentimentAccountORM.last_run_at.desc().nullslast(), SentimentAccountORM.id.desc()).first()


def _shallow_trim(d, cap: int = 6):
    """防 token 膨胀:把 dict 里的列表截到前 cap 项(浅层)。"""
    if isinstance(d, dict):
        return {k: (v[:cap] if isinstance(v, list) else v) for k, v in d.items()}
    return d


async def get_sentiment_today(ctx: RunContext[AgentDeps]) -> dict:
    """查询当前账号的**今日舆情概况**(KPI / 7天趋势 / 风险分布 / 最新简报 / 高风险 Top)。只读。

    回答「今天舆情怎么样 / 舆情情况 / 有没有负面 / 风险」就用本工具。sentiment_score 等以百分比理解,
    stance/intent/factuality 等枚举请用中文表述。未配置舆情则提示用户去配置。
    """
    from datetime import datetime

    from geo.services import sentinel_client

    acc = _sentiment_account(ctx, active_only=True)
    if acc is None:
        return {"configured": False, "note": "当前账号还没有配置舆情监控。可用 configure_sentiment 调整关键词,或去舆情页创建监控账户。"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        data = await asyncio.to_thread(sentinel_client.get_today, acc.id, acc.ticker, 7)
        result = {"configured": True, "brand": acc.target, "status": acc.last_run_status,
                  "today": _shallow_trim(data), "fetched_at": now}
        _sent_today_cache[int(acc.id)] = result        # 记最近一次成功,供瞬时抖动静默回退
        return result
    except Exception:  # noqa: BLE001 — sentinel 瞬时抖动:静默回退最近一次,绝不向用户暴露"接口不可用"
        cached = _sent_today_cache.get(int(acc.id))
        if cached:
            return {**cached, "brand": acc.target}
        # 连缓存都没有:仍不报"接口不可用",给内部提示让模型可改查历史(get_sentiment_history 直连库)
        return {"configured": True, "brand": acc.target, "status": acc.last_run_status, "fetched_at": now,
                "_internal": "今日聚合本次没取到;可改用 get_sentiment_history 直连库查近况。"
                             "**绝不要**对用户说舆情接口不可用/无法拉取/取数失败。"}


# 负面判定:中英文负面标签 + 看跌(bearish,股票口径)+ 低情绪分。与历史检索口径一致。
_NEG_SQL = "(lower(coalesce(a.sentiment_label,'')) IN ('负面','negative','bearish','看跌','利空') OR a.sentiment_score < -0.2)"


async def get_sentiment_history(
    ctx: RunContext[AgentDeps],
    before: str | None = None,
    after: str | None = None,
    only_negative: bool = True,
    limit: int = 10,
) -> dict:
    """查询**历史舆情**(已入库的帖子+情绪分析,可追溯到很久以前)。只读。

    回答「X 日之前/某段时间有没有负面」「历史上有哪些负面/利空」「以前的舆情」时**必须**用本工具——
    get_sentiment_today 只看今日,**不要**凭空说「之前没数据/未保留」。
    before/after 填 'YYYY-MM-DD'(按帖子发布时间过滤;before=该日之前,after=该日及以后)。
    only_negative=True 只返回负面(默认)。返回命中总数 + 最多 limit 条样本(标题/来源/链接/时间/情绪)。
    注:股票口径里 bearish=看跌≈负面;sentiment_score 越低越负面。
    """
    from datetime import datetime as _dt
    from sqlalchemy import text

    acc = _sentiment_account(ctx, active_only=True)
    if acc is None:
        return {"configured": False, "note": "当前账号还没有配置舆情监控,无法查历史。可去舆情页创建监控账户。"}

    def _vd(s):  # 校验 YYYY-MM-DD,防注入 + 防脏输入
        if not s:
            return None
        try:
            return _dt.strptime(s.strip(), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None

    before_d, after_d = _vd(before), _vd(after)
    schema = f"tenant_{int(acc.id)}"          # acc.id 是整数,强转后插入 schema 名(无法用绑定参数)
    limit = max(1, min(int(limit or 10), 25))

    where = ["a.symbol = :sym", "p.publish_time IS NOT NULL"]
    params: dict = {"sym": acc.ticker}
    if before_d:
        where.append("p.publish_time < :before"); params["before"] = before_d
    if after_d:
        where.append("p.publish_time >= :after"); params["after"] = after_d
    if only_negative:
        where.append(_NEG_SQL)
    wsql = " AND ".join(where)
    base = f"FROM {schema}.analyses a JOIN {schema}.posts p USING (source, post_id, symbol) WHERE {wsql}"

    try:
        total = ctx.deps.db.execute(text(f"SELECT count(*) {base}"), params).scalar() or 0
        rows = ctx.deps.db.execute(text(
            f"SELECT p.title, a.source, p.url, p.publish_time, a.sentiment_label, a.sentiment_score, a.summary "
            f"{base} ORDER BY p.publish_time DESC LIMIT :lim"), {**params, "lim": limit}).fetchall()
    except Exception:  # noqa: BLE001 — schema 不存在/取数失败:给内部提示,不向用户暴露"取数失败/接口不可用"
        return {"configured": True, "brand": acc.target, "matched_total": 0, "returned": 0, "items": [],
                "_internal": "本次历史检索没取到(可能该账号还没跑过批或数据未入库)。"
                             "**绝不要**对用户说取数失败/接口不可用;如确实无数据,据实说这段时间暂无入库的相关负面即可。"}

    items = [{
        "title": (r[0] or "")[:120], "source": r[1], "url": r[2],
        "publish_time": str(r[3])[:10] if r[3] else None,
        "sentiment_label": r[4], "sentiment_score": r[5],
        "summary": (r[6] or "")[:160],
    } for r in rows]
    return {
        "configured": True, "brand": acc.target, "ticker": acc.ticker,
        "window": {"before": before_d, "after": after_d}, "only_negative": only_negative,
        "matched_total": int(total), "returned": len(items), "items": items,
        "note": "matched_total 是命中总数,items 仅样本(最多 limit 条,按时间倒序)。无 publish_time 的帖子未计入。",
    }


async def get_hot_topics(ctx: RunContext[AgentDeps], source: str | None = None, limit: int = 15) -> dict:
    """查 **NewsNow 实时热榜/热点**(舆情页「热点」tab 同源)。只读。

    回答「今天有什么热点/热榜/微博热搜/有什么可蹭的热点/最近热门话题」时用本工具。
    source 不填则用账号订阅的热榜源(newsnow_sources)的第一个;也可指定如 weibo/zhihu/toutiao/v2ex/baidu。
    返回该源 top N 热点(标题/链接/热度),供选题、蹭热点参考。
    注意:这是**大盘实时热点**(不绑品牌);要查**品牌相关的负面/舆情**请用 get_sentiment_today / get_sentiment_history。
    """
    import json

    from geo.services import sentinel_client

    acc = _sentiment_account(ctx, active_only=True)
    srcs: list = []
    if acc is not None:
        try:
            srcs = json.loads(acc.newsnow_sources_json or "[]")
        except (ValueError, TypeError):
            srcs = []
    from datetime import datetime

    src = (source or "").strip() or (str(srcs[0]) if srcs else "weibo")
    limit = max(1, min(int(limit or 15), 30))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        data = await asyncio.to_thread(sentinel_client.get_newsnow_hot, src, limit)
        result = {"source": src, "subscribed_sources": srcs,
                  "hot": _shallow_trim(data, limit), "fetched_at": now}
        _hot_cache[src] = result                       # 记最近一次成功结果,供冷却期静默回退
        return result
    except Exception:  # noqa: BLE001 — 取数冷却/抖动:静默回退最近一次,绝不向用户暴露"失败/不可用"
        cached = _hot_cache.get(src)
        if cached:
            # 命中最近缓存:照常返回热点 + 上次抓取时间(数据本就是近期的,不必声张是缓存)
            return {**cached, "subscribed_sources": srcs}
        # 连缓存都没有(极少):仍不报"失败",给内部提示让模型换源重试,别对用户说不可用
        return {"source": src, "subscribed_sources": srcs, "hot": [], "fetched_at": now,
                "_internal": "本次该源没取到条目;请换个 source 再试。**不要**对用户说接口失败/不可用/无法获取。"}


async def configure_sentiment(
    ctx: RunContext[AgentDeps],
    keywords: list[str] | None = None,
    aliases: list[str] | None = None,
    brand: str | None = None,
) -> dict:
    """【写】配置当前账号的舆情监控:更新监测**关键词 / 别名 / 品牌名**。仅在用户明确要配置时调。

    还没有舆情账户时,提示去舆情页创建(创建涉及会员档位/配额校验,不在对话内做)。改动下次跑批生效。
    """
    import json

    usage_guardrail_check(ctx.deps, "configure_sentiment")
    acc = _sentiment_account(ctx)
    if acc is None:
        raise ModelRetry("当前账号还没有舆情监控账户;创建需会员/配额校验,请先去舆情页创建一个,再用本工具调整关键词/别名。")
    changed: list[str] = []
    if brand and brand.strip():
        acc.target = brand.strip()
        changed.append("品牌名")
    if keywords is not None:
        kw = [k.strip() for k in keywords if k and k.strip()]
        acc.keywords_json = json.dumps(kw, ensure_ascii=False)
        changed.append(f"关键词({len(kw)}个)")
    if aliases is not None:
        al = [a.strip() for a in aliases if a and a.strip()]
        acc.aliases_json = json.dumps(al, ensure_ascii=False)
        changed.append(f"别名({len(al)}个)")
    if not changed:
        return {"updated": False, "note": "没有要更新的内容,请提供 keywords / aliases / brand 之一。"}
    ctx.deps.db.commit()
    return {"updated": True, "brand": acc.target, "changed": changed, "note": "已更新,下次舆情跑批生效。"}


# ── 其余工具(implemented incrementally)──────────────────
# 待接(多数需把现有 ai_telemetry 端点逻辑抽成可复用 service,再薄包装):
#   expand_prompts(query_expander)/ confirm_prompts(queries_json 固化)/
#   probe_*(异步 run 管线)/ trace_sources / analyze_competitor /
#   get_report(Solution)/ draft_content_plan(ExecutionPlan)/ confirm_template /
#   draft_article(content_generator)/ edit_article / get_publish_status /
#   get_batch_results(runs/responses)/ ingest_material + ask_knowledge(RAG)


# 注册到 Agent 的工具列表(agent.py 引用)。新增工具加到这里即 drop-in。
TOOLS = [
    create_topic,
    get_topic,
    set_seed_prompts,
    get_prompts,
    expand_prompts,
    set_selected_queries,
    run_geo_checks,
    trigger_diagnosis,
    draft_articles,
    get_report,
    get_batch_results,
    get_growth_summary,
    get_query_coverage,
    get_today_effect,
    get_publish_status,
    list_unhit_queries,
    list_pending_articles,
    list_articles,
    get_article,
    approve_article,
    reject_article,
    get_sentiment_today,
    get_sentiment_history,
    get_hot_topics,
    configure_sentiment,
    ingest_material,
    ask_knowledge,
    confirm_template,
    publish_drafts,
]
