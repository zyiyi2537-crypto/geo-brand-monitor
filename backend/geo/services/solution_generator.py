"""GEO 品牌增长战略方案生成 service.

入口 `schedule_solution_generation(topic_id, website_url, admin_id)` 在 admin 点
"生成战略方案"时由 admin_review POST endpoint 通过 FastAPI BackgroundTasks 异步触发。

混合架构(硬数据 + LLM 文案):
  1. 硬数据:跑 geo_checker.run_geo_check 拿 25 类诊断 + score + grade
  2. 聚类:把 25 类按 5 大主题分簇(站内技术 5 大短板),每簇计算 severity
  3. LLM:把 BrandProfile + diagnosis_summary + 模板骨架喂 DeepSeek
     拿 JSON {diagnosis_summaries, seven_steps, keyword_tiers, vision}
  4. 拼接:LLM 文案 + 硬数据 → SolutionORM 落库

失败:任何步骤失败 → status=failed + error_text;前端轮询拿到错误 + 重试按钮。

ENV:
    DEEPSEEK_API_KEY      可选,优先 → 直连
    OPENROUTER_API_KEY    可选,fallback → 通过 OpenRouter 调 DeepSeek
    GEO_SOLUTION_TIMEOUT  可选,LLM 单次请求超时(秒),默认 180
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any

import requests

from geo.database import SessionLocal
from geo.models.ai_telemetry import (
    AiTelemetryTopicORM, AiTelemetryTopicSolutionORM, BrandProfile,
)

log = logging.getLogger(__name__)

# 超过这个时间未更新的 generating 行视为僵尸 — 后台 thread 是 daemon,backend
# restart 时会被 SIGTERM 杀死,DB 里 status 会卡在 generating,前端轮询永远等不到结果。
STALE_GENERATING_THRESHOLD = timedelta(minutes=10)

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
OPENROUTER_DEEPSEEK_MODEL = os.environ.get("OPENROUTER_DEEPSEEK_MODEL", "deepseek/deepseek-chat")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT = int(os.environ.get("GEO_SOLUTION_TIMEOUT", "180"))


# ─────────────── 25 类 → 5 大短板簇映射 ───────────────
# 参照 SPARKOZ / BrainWM 两份 PDF 里站内技术诊断的分类骨架:
#   1) AI 协议与抓取规则   2) 爬虫访问 & 性能   3) 结构化数据 & 语义化
#   4) URL & 元标签        5) 内容 & 安全 & 媒体
#
# 25-类英文 label 直接来自 geo_checker.orchestrate.CHECK_REGISTRY,不要改。
CLUSTER_DEFS: list[dict[str, Any]] = [
    {
        "key": "ai_protocol",
        "title_zh": "AI 专属协议与抓取规则",
        "categories": [
            "llms.txt",
            ".well-known Discovery",
            "AI Crawl Readiness",
            "AI-Specific Optimization",
            "Search Engine & AI Platform Registration",
        ],
    },
    {
        "key": "crawl_performance",
        "title_zh": "爬虫访问与页面性能",
        "categories": [
            "Technical Crawlability",
            "Mobile-Friendliness & Page Weight",
            "robots.txt",
            "sitemap.xml",
            "HTTPS",
        ],
    },
    {
        "key": "structured_data",
        "title_zh": "结构化数据与语义化",
        "categories": [
            "Structured Data",
            "Content Accessibility",
            "AI Answer Format Optimization",
            "Schema Breadcrumbs & Knowledge Panel",
            "Brand Entity in Knowledge Graphs",
        ],
    },
    {
        "key": "url_meta",
        "title_zh": "URL 与元标签规范",
        "categories": [
            "URL Normalization",
            "Meta Tags",
            "Multilingual Content Depth",
            "Multi-Page Sampling",
        ],
    },
    {
        "key": "content_safety",
        "title_zh": "内容、安全与媒体",
        "categories": [
            "Content Quality for AI",
            "Trust & Safety Signals",
            "Authority & Trust Signals",
            "Outbound Links & Media",
            "Social Signals",
            "Cross-Platform Content Distribution",
        ],
    },
]

SEVEN_STEPS_TEMPLATE = [
    {"step": 1, "name": "种子提示词搭建", "core_goal": "确立品牌 AI 引擎元定义"},
    {"step": 2, "name": "意图深度扩展",   "core_goal": "挖掘 AI 搜索真实用户需求"},
    {"step": 3, "name": "提示词聚类拓扑", "core_goal": "搭建品牌行业知识矩阵"},
    {"step": 4, "name": "结构化内容生成", "core_goal": "打造 AI 高抓取偏好内容"},
    {"step": 5, "name": "全链路多维分发", "core_goal": "搭建行业权威证人矩阵"},
    {"step": 6, "name": "数据遥测引用分析", "core_goal": "监控 AI 品牌曝光数据"},
    {"step": 7, "name": "强化反馈闭环",   "core_goal": "形成自迭代增长运营环"},
]

KEYWORD_TIERS_TEMPLATE = [
    {"tier": "brand_core",      "title_zh": "品牌核心词",  "description_hint": "品牌名 / 公司名 / 主力产品系列名"},
    {"tier": "product_model",   "title_zh": "产品 / 型号词", "description_hint": "具体产品型号、SKU、产品线名"},
    {"tier": "tech",            "title_zh": "技术词",      "description_hint": "AI 回答「这款产品 / 服务有什么技术优势」时检索的词"},
    {"tier": "scenario",        "title_zh": "场景词",      "description_hint": "用户在 AI 引擎中问「XXX 场所 / 行业用什么」时触发的词"},
    {"tier": "procurement",     "title_zh": "采购决策词",   "description_hint": "B2B 采购决策者真实提问的词,转化价值最高"},
    {"tier": "pain_point",      "title_zh": "痛点词",      "description_hint": "用户描述问题时使用的词,AI 引擎把问题与解决方案品牌匹配"},
]


# ─────────────── 入口 ───────────────


def schedule_solution_generation(
    *,
    topic_id: int,
    website_url: str,
    admin_id: int,
) -> None:
    """fire-and-forget thread.LLM 单次 30-90s,要避开 FastAPI 事件循环."""
    thread = threading.Thread(
        target=_run_safe,
        args=(topic_id, website_url, admin_id),
        daemon=True,
    )
    thread.start()


def reset_stale_generating() -> int:
    """启动时调用 — 把超过 STALE_GENERATING_THRESHOLD 没更新的 generating 行
    标成 failed。daemon thread 在 backend restart 时会被杀,这里兜底防止 UI 一直转圈。
    返回被重置的行数。"""
    cutoff = datetime.utcnow() - STALE_GENERATING_THRESHOLD
    db = SessionLocal()
    try:
        stale = (
            db.query(AiTelemetryTopicSolutionORM)
              .filter(AiTelemetryTopicSolutionORM.status == "generating",
                      AiTelemetryTopicSolutionORM.updated_at < cutoff)
              .all()
        )
        for row in stale:
            row.status = "failed"
            row.error = "后端在生成途中重启,后台任务被中断。请点重试重新生成。"
            row.updated_at = datetime.utcnow()
        if stale:
            db.commit()
            log.warning("reset %d stale generating solution rows: %s",
                        len(stale), [r.id for r in stale])
        return len(stale)
    finally:
        db.close()


def _run_safe(topic_id: int, website_url: str, admin_id: int) -> None:
    try:
        _run(topic_id, website_url, admin_id)
    except Exception as e:  # noqa: BLE001
        log.exception("solution generation crashed for topic %d: %s", topic_id, e)
        _mark_failed(topic_id, str(e)[:1000])


def _run(topic_id: int, website_url: str, admin_id: int) -> None:
    db = SessionLocal()
    try:
        t = db.get(AiTelemetryTopicORM, topic_id)
        if not t:
            log.warning("solution gen: topic %d not found", topic_id)
            return

        # 1) 加载 brand profile
        try:
            profile_data = json.loads(t.profile_json or "{}")
        except Exception:  # noqa: BLE001
            profile_data = {}
        if not isinstance(profile_data, dict):
            profile_data = {}
        try:
            profile = BrandProfile(**profile_data)
        except Exception:  # noqa: BLE001
            profile = BrandProfile()

        # 2) 跑 geo_checker — 硬数据(website 选填:空时跳过技术诊断,只生成基于品牌资料的 4 块)
        url = (website_url or "").strip()
        diagnosis = _run_diagnosis(url) if url else _empty_diagnosis()

        # 3) 调 LLM — 拼方案文案
        narrative, keywords, llm_model = _call_llm(profile, diagnosis, website_url)

        # 3.5) 快照监测 Query — 直接取 topic.queries_json 里 selected=True 的项
        #      + topic.clusters_json 的簇标签,不走 LLM.报告里"监测 Query 清单"节用.
        queries_snapshot = _snapshot_selected_queries(t)

        # 4) 落库 — upsert
        sol = (
            db.query(AiTelemetryTopicSolutionORM)
              .filter(AiTelemetryTopicSolutionORM.topic_id == topic_id)
              .first()
        )
        if sol is None:
            sol = AiTelemetryTopicSolutionORM(topic_id=topic_id)
            db.add(sol)
        sol.status = "ready"
        sol.website_url = website_url
        sol.diagnosis_json = json.dumps(diagnosis, ensure_ascii=False)
        sol.narrative_json = json.dumps(narrative, ensure_ascii=False)
        sol.keywords_json = json.dumps(keywords, ensure_ascii=False)
        sol.brand_snapshot_json = json.dumps(profile.model_dump(), ensure_ascii=False)
        sol.queries_snapshot_json = json.dumps(queries_snapshot, ensure_ascii=False)
        sol.llm_model = llm_model
        sol.error = None
        sol.generated_by_admin_id = admin_id
        sol.updated_at = datetime.utcnow()
        db.commit()
        log.info("solution gen done for topic %d (score=%s)", topic_id, diagnosis.get("score"))
    finally:
        db.close()


def _mark_failed(topic_id: int, error: str) -> None:
    db = SessionLocal()
    try:
        sol = (
            db.query(AiTelemetryTopicSolutionORM)
              .filter(AiTelemetryTopicSolutionORM.topic_id == topic_id)
              .first()
        )
        if sol is None:
            return
        sol.status = "failed"
        sol.error = error
        sol.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


# ─────────────── 硬数据:topic 已选 Query 快照 ───────────────


def _snapshot_selected_queries(topic: AiTelemetryTopicORM) -> dict[str, Any]:
    """从 topic.queries_json 提取 selected=True 的项 + clusters_json 簇标签,落成快照.

    queries_json 兼容多形态(参 ai_telemetry.AiTelemetryTopicORM 注释):
      - list[str](legacy):全部视为 selected=True,cluster_id=-1,seed=""
      - list[dict]:取 selected(默认 True)/ text / cluster_id / seed
    clusters_json 形态:list[{cluster_id, label, size}].

    返回 dict 与 SolutionQueriesSnapshot 同构,落 queries_snapshot_json 用.
    """
    queries_out: list[dict[str, Any]] = []
    try:
        raw = json.loads(topic.queries_json or "[]")
    except Exception:  # noqa: BLE001
        raw = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    queries_out.append({"text": text, "cluster_id": -1, "seed": ""})
                continue
            if not isinstance(item, dict):
                continue
            # legacy 无 selected 字段时默认 True(老话题的 query 默认都参与监测)
            if not bool(item.get("selected", True)):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            cid = item.get("cluster_id")
            cluster_id = int(cid) if isinstance(cid, int) else -1
            seed = str(item.get("seed") or "")
            queries_out.append({"text": text, "cluster_id": cluster_id, "seed": seed})

    clusters_out: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    try:
        cluster_raw = json.loads(topic.clusters_json or "[]")
    except Exception:  # noqa: BLE001
        cluster_raw = []
    if isinstance(cluster_raw, list):
        for c in cluster_raw:
            if not isinstance(c, dict):
                continue
            try:
                cid = int(c.get("cluster_id"))
            except (TypeError, ValueError):
                continue
            label = str(c.get("label") or "").strip()
            if not label:
                continue
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            clusters_out.append({"cluster_id": cid, "label": label})

    return {"clusters": clusters_out, "queries": queries_out}


# ─────────────── 硬数据:geo_checker 扫描 ───────────────


def _empty_diagnosis() -> dict[str, Any]:
    """website_url 为空时的占位 — 让 _call_llm 跳过技术诊断相关 prompt 段,
    报告页前端也按 score=0 + 空 clusters 判断不渲染诊断 / 执行流程两节."""
    return {
        "url": "",
        "score": 0,
        "grade": "",
        "pass_count": 0,
        "warn_count": 0,
        "fail_count": 0,
        "info_count": 0,
        "clusters": [],
        "execution_layers": [],
        "all_checks": [],
    }


def _run_diagnosis(url: str) -> dict[str, Any]:
    """跑 run_geo_check 拿 25 类结果 → 转 SolutionDiagnosis dict."""
    from geo.services.geo_checker import run_geo_check

    result = run_geo_check(url, include_fix=True, tier="growth")
    checks_all: list[dict[str, Any]] = []
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for c in (result.checks or []):
        item = {
            "category": c.category or "",
            "status": c.status or "",
            "message": c.message or "",
            "fix": c.fix or None,
        }
        checks_all.append(item)
        by_cat.setdefault(item["category"], []).append(item)

    clusters: list[dict[str, Any]] = []
    severity_rank = {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}
    for cdef in CLUSTER_DEFS:
        cluster_checks: list[dict[str, Any]] = []
        worst = 0
        for cat in cdef["categories"]:
            for it in by_cat.get(cat, []):
                cluster_checks.append(it)
                worst = max(worst, severity_rank.get(it["status"], 0))
        severity = "high" if worst >= 2 else ("med" if worst == 1 else "low")
        # bullets:截 FAIL/WARN 的 message 前 60 字,最多 6 条
        bullets: list[str] = []
        for it in cluster_checks:
            if it["status"] in ("FAIL", "WARN"):
                msg = (it["message"] or "").strip()
                if msg:
                    bullets.append(msg[:120])
            if len(bullets) >= 6:
                break
        clusters.append({
            "key": cdef["key"],
            "title_zh": cdef["title_zh"],
            "severity": severity,
            "summary": "",   # 留给 LLM 填
            "bullets": bullets,
            "checks": cluster_checks,
        })

    # 三层执行流程:基于 cluster severity 自动派生
    layer_map = {
        "ai_protocol": "technical_base",
        "crawl_performance": "technical_base",
        "url_meta": "technical_base",
        "structured_data": "content_core",
        "content_safety": "weight_push",
    }
    layer_titles = {
        "technical_base": "技术地基",
        "content_core":   "内容核心",
        "weight_push":    "权重推力",
    }
    layer_hints = {
        "technical_base": "补齐 AI 公认的「实体信任」",
        "content_core":   "把品牌优势转化为 AI 易抓取的「事实库」",
        "weight_push":    "在站外高权重平台建立全网语义背书",
    }
    layer_agg: dict[str, dict[str, Any]] = {
        k: {"key": k, "title_zh": v, "hint": layer_hints[k], "clusters": []}
        for k, v in layer_titles.items()
    }
    for c in clusters:
        layer_key = layer_map.get(c["key"], "technical_base")
        layer_agg[layer_key]["clusters"].append(c["title_zh"])
    execution_layers = list(layer_agg.values())

    summary = result.summary or {}

    return {
        "url": result.url or url,
        "score": int(getattr(result, "score", 0) or 0),
        "grade": getattr(result, "grade", "") or "",
        "pass_count": int(summary.get("pass_count", 0) or 0),
        "warn_count": int(summary.get("warn_count", 0) or 0),
        "fail_count": int(summary.get("fail_count", 0) or 0),
        "info_count": int(summary.get("info_count", 0) or 0),
        "clusters": clusters,
        "execution_layers": execution_layers,
        "all_checks": checks_all,
    }


# ─────────────── LLM:文案 ───────────────


def _call_llm(
    profile: BrandProfile, diagnosis: dict[str, Any], website_url: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """LLM 一次出方案文案:聚类摘要 + 七步定制 + 关键词 + 愿景.

    返回 (narrative, keywords, model_id);
      narrative = {cluster_summaries: {key: text}, seven_steps: [...], vision: [...]}
      keywords  = {tiers: [SolutionKeywordTier]}
    """
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if ds_key:
        provider, model_id, api_key = "deepseek", DEEPSEEK_MODEL, ds_key
    elif or_key:
        provider, model_id, api_key = "openrouter", OPENROUTER_DEEPSEEK_MODEL, or_key
    else:
        raise RuntimeError("DEEPSEEK_API_KEY / OPENROUTER_API_KEY 都未配置,无法生成战略方案")

    system_prompt = _build_system_prompt(profile, diagnosis, website_url)
    user_prompt = _build_user_prompt(profile, diagnosis)

    if provider == "deepseek":
        url = f"{DEEPSEEK_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    else:
        url = OPENROUTER_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://www.vigilath.com",
            "X-Title": "GEO Solution Generator",
        }
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"{provider} {r.status_code}: {r.text[:200]}")
    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"unexpected {provider} response shape: {e}")

    parsed = _parse_json_loose(content)
    narrative, keywords = _normalize_llm_output(parsed, profile, diagnosis)
    return narrative, keywords, model_id


def _build_system_prompt(profile: BrandProfile, diagnosis: dict, website_url: str) -> str:
    has_diag = bool((diagnosis or {}).get("clusters")) or bool((website_url or "").strip())
    if has_diag:
        intro = "你的任务:基于「品牌资料 + 站内技术诊断」,产出一份可交付的「GEO 品牌增长战略方案」JSON。"
    else:
        intro = ("你的任务:基于「品牌资料」(此次未提供官网,跳过站内技术诊断),"
                 "产出一份可交付的「GEO 品牌增长战略方案」JSON;只输出品牌定位 / 七步 / 关键词 / 愿景,"
                 "不要编造诊断分数。")
    parts = [
        "你是 GEO(Generative Engine Optimization)品牌增长战略顾问。",
        intro,
        "",
        "## 品牌资料",
    ]
    if website_url:
        parts.append(f"- 官网:{website_url}")
    if profile.company_full_name:
        parts.append(f"- 品牌全称:{profile.company_full_name}")
    if profile.company_short_name:
        parts.append(f"- 品牌简称:{profile.company_short_name}")
    if profile.industry:
        parts.append(f"- 行业:{profile.industry}")
    if profile.core_business_lines:
        parts.append(f"- 核心业务:{', '.join(profile.core_business_lines)}")
    if profile.target_scenarios:
        parts.append(f"- 目标场景:{', '.join(profile.target_scenarios)}")
    if profile.service_geo:
        parts.append(f"- 服务地域:{profile.service_geo}")
    if profile.brand_diff_tags:
        parts.append(f"- 品牌差异化标签:{', '.join(profile.brand_diff_tags)}")
    if profile.core_service_overview:
        parts.append(f"- 核心服务概述:{profile.core_service_overview}")
    if profile.brand_slogan:
        parts.append(f"- Slogan:{profile.brand_slogan}")
    if profile.core_message:
        parts.append(f"- 核心信息:{profile.core_message}")

    if diagnosis.get("clusters"):
        parts.append("")
        parts.append("## 站内技术诊断概览")
        parts.append(f"- AI 可见度评分:{diagnosis.get('score', 0)}/100 ({diagnosis.get('grade', '')})")
        parts.append(f"- 通过:{diagnosis.get('pass_count', 0)} · 警告:{diagnosis.get('warn_count', 0)} · 失败:{diagnosis.get('fail_count', 0)}")
        parts.append("")
        parts.append("## 5 大短板簇(已聚类)")
        for c in diagnosis.get("clusters", []):
            bullets = "; ".join(c.get("bullets", []) or [])
            parts.append(f"- 【{c['title_zh']}】(严重度 {c['severity']}):{bullets or '无明显短板'}")

    parts.append("")
    parts.append("## 写作要求(严格遵守)")
    parts.append("1. 全部用中文,符合「GEO 品牌增长战略」语境,语气专业但不堆术语。")
    parts.append("2. 不要使用 Markdown 符号(# ** * - ` 等);所有「中文标点」用全角(,。!?:;「」)。")
    parts.append("3. 关键词体系里产品 / 技术 / 场景 / 痛点词,英文场景的品牌(海外业务)用英文,中文场景用中文,贴近品牌实际市场。")
    parts.append("4. 严格按 user 给的 JSON schema 输出,不要多字段不要漏字段,不要 ``` 围栏。")
    return "\n".join(parts)


def _build_user_prompt(profile: BrandProfile, diagnosis: dict) -> str:
    cluster_keys = [c["key"] for c in diagnosis.get("clusters", [])]
    seven_steps_names = [s["name"] for s in SEVEN_STEPS_TEMPLATE]
    keyword_tiers = KEYWORD_TIERS_TEMPLATE
    schema_hint = {
        "cluster_summaries": {k: "string,40-120字,描述本簇短板对品牌AI可见性的具体影响" for k in cluster_keys},
        "seven_steps": [
            {
                "step": "int 1-7",
                "name": "string,跟模板一致",
                "core_goal": "string,跟模板一致",
                "core_action": "string,80-200字,针对本品牌的具体执行内容,要点名品牌名/产品/场景",
                "output_value": "string,40-100字,核心产出 & 价值",
            } for _ in range(7)
        ],
        "keyword_tiers": [
            {
                "tier": "tier slug(brand_core/product_model/tech/scenario/procurement/pain_point)",
                "title_zh": "中文层名",
                "description": "string,30-80字,这一层关键词的定位",
                "keywords": ["list[str],8-20 个具体关键词"],
            } for _ in keyword_tiers
        ],
        "vision": [
            {"title": "成为行业权威", "body": "string,80-180字,围绕「AI 引擎回答 XXX 时品牌成为首选引用源」展开"},
            {"title": "降低获客成本", "body": "string,80-180字,围绕「自然流量减少付费依赖」+ 量化预期"},
            {"title": "建立全球信任", "body": "string,80-180字,围绕「在主流 AI 模型中构建品牌形象」"},
        ],
    }
    return (
        "请基于上面的品牌资料 + 诊断,产出严格符合下面 schema 的 JSON。\n\n"
        f"七步增长模型固定模板(请按这 7 步顺序填充,name/core_goal 与模板一致):\n"
        f"{json.dumps([{'step': s['step'], 'name': s['name'], 'core_goal': s['core_goal']} for s in SEVEN_STEPS_TEMPLATE], ensure_ascii=False)}\n\n"
        f"6 层关键词体系(请按这 6 层顺序填充,tier/title_zh 与模板一致):\n"
        f"{json.dumps([{'tier': t['tier'], 'title_zh': t['title_zh']} for t in keyword_tiers], ensure_ascii=False)}\n\n"
        f"输出 JSON Schema:\n{json.dumps(schema_hint, ensure_ascii=False, indent=2)}\n\n"
        "只输出 JSON,不要前后文,不要 ``` 围栏。"
    )


def _normalize_llm_output(
    raw: dict, profile: BrandProfile, diagnosis: dict,
) -> tuple[dict, dict]:
    """把 LLM 出的 JSON 校验 + 兜底 + 拆成 narrative / keywords 两块.

    narrative = {cluster_summaries, seven_steps, vision}
    keywords  = {tiers: [...]}
    """
    # cluster_summaries
    cluster_summaries_raw = raw.get("cluster_summaries") or {}
    if not isinstance(cluster_summaries_raw, dict):
        cluster_summaries_raw = {}
    cluster_summaries: dict[str, str] = {}
    for c in diagnosis.get("clusters", []):
        v = cluster_summaries_raw.get(c["key"])
        cluster_summaries[c["key"]] = str(v).strip() if v else ""

    # seven_steps — 必须 7 项,按模板对齐
    seven_steps_raw = raw.get("seven_steps") or []
    if not isinstance(seven_steps_raw, list):
        seven_steps_raw = []
    seven_steps: list[dict] = []
    for i, tpl in enumerate(SEVEN_STEPS_TEMPLATE):
        item = seven_steps_raw[i] if i < len(seven_steps_raw) and isinstance(seven_steps_raw[i], dict) else {}
        seven_steps.append({
            "step": tpl["step"],
            "name": tpl["name"],
            "core_goal": tpl["core_goal"],
            "core_action": str(item.get("core_action") or "").strip(),
            "output_value": str(item.get("output_value") or "").strip(),
        })

    # vision — 3 段
    vision_raw = raw.get("vision") or []
    if not isinstance(vision_raw, list):
        vision_raw = []
    vision_defaults = [
        {"title": "成为行业权威", "body": ""},
        {"title": "降低获客成本", "body": ""},
        {"title": "建立全球信任", "body": ""},
    ]
    vision: list[dict] = []
    for i, d in enumerate(vision_defaults):
        v = vision_raw[i] if i < len(vision_raw) and isinstance(vision_raw[i], dict) else {}
        vision.append({
            "title": str(v.get("title") or d["title"]).strip(),
            "body": str(v.get("body") or "").strip(),
        })

    # keyword_tiers — 6 层
    tiers_raw = raw.get("keyword_tiers") or []
    if not isinstance(tiers_raw, list):
        tiers_raw = []
    tiers: list[dict] = []
    for i, tpl in enumerate(KEYWORD_TIERS_TEMPLATE):
        t = tiers_raw[i] if i < len(tiers_raw) and isinstance(tiers_raw[i], dict) else {}
        kw_list = t.get("keywords") or []
        if not isinstance(kw_list, list):
            kw_list = []
        kws = [str(k).strip() for k in kw_list if str(k).strip()][:30]
        tiers.append({
            "tier": tpl["tier"],
            "title_zh": tpl["title_zh"],
            "description": str(t.get("description") or "").strip(),
            "keywords": kws,
        })

    narrative = {
        "cluster_summaries": cluster_summaries,
        "seven_steps": seven_steps,
        "vision": vision,
    }
    keywords = {"tiers": tiers}
    return narrative, keywords


def _parse_json_loose(text: str) -> dict:
    """容忍 ``` 围栏的 JSON 解析."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.lstrip("`").lstrip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
        if s.endswith("```"):
            s = s[:-3].rstrip()
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            return v
    except Exception:  # noqa: BLE001
        pass
    import re
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, dict):
                return v
        except Exception:  # noqa: BLE001
            pass
    raise RuntimeError(f"failed to parse JSON from LLM output: {s[:200]}")
