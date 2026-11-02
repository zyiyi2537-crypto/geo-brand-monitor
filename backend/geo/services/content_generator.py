"""Phase D — 内容文案生成 service.

入口 `schedule_generation(topic_id, plan_id)` 在 admin 通过资料审核时由
admin_review.approve_topic 通过 FastAPI BackgroundTasks 异步触发。

流程:
  1. 加载 topic 的资料 + 通过的监测问题(approved 且 selected)
  2. 对每条监测问题,组装 prompt(资料中创作方向/文案类型/平台/调性/雷区/Slogan)
  3. 调用 LLM(DeepSeek) 拿输出(JSON {title, body, summary})
  4. 落 TopicGeneratedDocORM(status=draft)

模型用 DeepSeek-Chat.两条路:
  - 直连:配 DEEPSEEK_API_KEY,走 https://api.deepseek.com/chat/completions
  - 走 OpenRouter:配 OPENROUTER_API_KEY,model 用 deepseek/deepseek-chat
两个都没配 → 落库时记错误,不阻塞审核流程.

失败粒度:单条 query 失败不影响其它,失败的稿件会用 generation_error 记录原因.

ENV:
    DEEPSEEK_API_KEY      可选,优先使用 → 直连 DeepSeek
    OPENROUTER_API_KEY    可选,fallback → 通过 OpenRouter 调 DeepSeek 模型
    DEEPSEEK_BASE_URL     可选,默认 https://api.deepseek.com
    DEEPSEEK_MODEL        直连模型 id,可选,默认 deepseek-chat
    OPENROUTER_DEEPSEEK_MODEL 可选,默认 deepseek/deepseek-chat
    GEO_CONTENT_TIMEOUT   可选,单条 LLM 请求超时(秒),默认 180
    GEO_CONTENT_MAX_DOCS  可选,单次审核最多生成多少稿(默认 = 监测问题数,上限 50)
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Optional

import requests

from geo.database import SessionLocal
from geo.models.ai_telemetry import (
    AiTelemetryTopicExecutionPlanORM, AiTelemetryTopicORM, BrandProfile,
    ContentTemplateORM, TopicGeneratedDocORM, TopicMediaORM,
)

log = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
OPENROUTER_DEEPSEEK_MODEL = os.environ.get("OPENROUTER_DEEPSEEK_MODEL", "deepseek/deepseek-chat")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT = int(os.environ.get("GEO_CONTENT_TIMEOUT", "180"))


def schedule_generation(
    *,
    topic_id: int,
    plan_id: int | None = None,
    max_docs: int | None = None,
    queries_override: list[str] | None = None,
    plan_item_ids: list[str] | None = None,
    mark_auto_run: bool = False,
) -> None:
    """fire-and-forget thread.BackgroundTasks 已是 fire-and-forget,
    但为了不阻塞 FastAPI 的事件循环(LLM 单条 30-90s),再起一个 daemon thread.

    参数:
      max_docs            — 限制本次生成的稿件数;不传则按 env / 50 兜底
      queries_override    — 指定本次要写的 query 列表;不传则按 plan_item_ids /
                            plan.publishing_plan_json / topic.queries_json 三段择优
      plan_item_ids       — 指定本次只跑 publishing_plan_items 里的哪几行(单条重生用)
      mark_auto_run       — True 时写 auto_generate_last_run_at(cron / 立即生成入口用)
    """
    thread = threading.Thread(
        target=_run_generation_safe,
        args=(topic_id, plan_id, max_docs, queries_override, plan_item_ids, mark_auto_run),
        daemon=True,
    )
    thread.start()


def _run_generation_safe(
    topic_id: int, plan_id: int | None,
    max_docs: int | None, queries_override: list[str] | None,
    plan_item_ids: list[str] | None,
    mark_auto_run: bool,
) -> None:
    try:
        _run_generation(
            topic_id, plan_id, max_docs, queries_override,
            plan_item_ids, mark_auto_run,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("content generation crashed for topic %d: %s", topic_id, e)


def _resolve_provider() -> tuple[str | None, str, str]:
    """挑 LLM provider + 拿 api key.返回 (provider | None, model_id, api_key)."""
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if ds_key:
        return "deepseek", DEEPSEEK_MODEL, ds_key
    if or_key:
        return "openrouter", OPENROUTER_DEEPSEEK_MODEL, or_key
    return None, DEEPSEEK_MODEL, ""


def _run_generation(
    topic_id: int, plan_id: int | None,
    max_docs_override: int | None, queries_override: list[str] | None,
    plan_item_ids: list[str] | None,
    mark_auto_run: bool,
) -> None:
    db = SessionLocal()
    try:
        t = db.get(AiTelemetryTopicORM, topic_id)
        if not t:
            log.warning("content gen: topic %d not found", topic_id)
            return
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

        # 新路径优先:plan_id + plan.publishing_plan_json 有内容 → 按 plan item 派工.
        # 旧路径(queries_override / topic.queries_json) 仅在没 plan 数据时走.
        plan_items: list[dict] = []
        if plan_id is not None:
            plan = db.get(AiTelemetryTopicExecutionPlanORM, plan_id)
            if plan:
                try:
                    raw = json.loads(plan.publishing_plan_json or "[]")
                except Exception:  # noqa: BLE001
                    raw = []
                plan_items = [it for it in raw if isinstance(it, dict)]
                if plan_item_ids:
                    wanted = set(plan_item_ids)
                    plan_items = [it for it in plan_items if it.get("id") in wanted]

        if plan_items:
            _run_per_item(
                db, t, profile, topic_id, plan_id, plan_items, mark_auto_run,
            )
            return

        # ── 兼容旧路径:按整批 queries 跑 ──────────────────────────────────────────
        if queries_override is not None:
            queries = [q for q in queries_override if isinstance(q, str) and q.strip()]
        else:
            try:
                qarr = json.loads(t.queries_json or "[]")
            except Exception:  # noqa: BLE001
                qarr = []
            queries = [
                q["text"] for q in qarr
                if isinstance(q, dict) and q.get("text")
                and q.get("selected", True) and q.get("status") == "approved"
            ]
        if not queries:
            log.info("content gen: no queries to write for topic %d", topic_id)
            return
        env_cap = int(os.environ.get("GEO_CONTENT_MAX_DOCS", "50"))
        cap = max_docs_override if max_docs_override and max_docs_override > 0 else env_cap
        cap = min(cap, env_cap, len(queries))
        queries = queries[:cap]

        provider, model_id, api_key = _resolve_provider()
        style_refs = _load_style_refs(db, topic_id)

        # 2026-05-28 — 4 维场景扩展第二波:按 (creation_direction, copywriting_type)
        # combo 多变体生成.profile 里两边都填了 → N×M combo;一边空 → 单边 fan-out;
        # 都空 → fallback 单变体(向后兼容).
        combos = _build_combos(profile)
        log.info("content gen: topic %d, %d queries × %d combos = %d docs target",
                 topic_id, len(queries), len(combos), len(queries) * len(combos))

        for q in queries:
            for direction, copywriting_type in combos:
                doc = TopicGeneratedDocORM(
                    topic_id=topic_id, execution_plan_id=plan_id,
                    source_query_text=q, status="pending_review",
                    selected_for_review=True,
                    llm_model=model_id, source="ai",
                    creation_direction=direction,
                    copywriting_type=copywriting_type,
                )
                if not provider:
                    doc.generation_error = "DEEPSEEK_API_KEY / OPENROUTER_API_KEY 都未配置"
                    doc.title = f"[未生成] {q}"
                    db.add(doc)
                    continue
                try:
                    medias = _match_topic_media(db, topic_id, q)
                    title, body, summary = _generate_one(
                        profile, q, provider, api_key,
                        direction=direction, copywriting_type=copywriting_type,
                        medias=medias, topic_id=topic_id, style_refs=style_refs,
                    )
                    doc.title = title
                    # allow_md 类型的 prompt 已让 LLM 自己嵌图;不再 append URL 列表
                    # 老规则类型(no md)仍按老路径在末尾追加图片列表
                    allow_md = bool(TYPE_HINTS.get(copywriting_type or "", {}).get("allow_md", False))
                    if allow_md:
                        doc.body_markdown = body
                    else:
                        doc.body_markdown = _append_media_to_body(db, topic_id, q, body)
                    doc.summary = summary
                except Exception as e:  # noqa: BLE001
                    log.warning("content gen failed for q='%s' combo=(%s,%s) topic=%d: %s",
                                q, direction, copywriting_type, topic_id, e)
                    doc.generation_error = str(e)[:500]
                    doc.title = f"[生成失败] {q}"
                db.add(doc)
        if mark_auto_run:
            t.auto_generate_last_run_at = datetime.utcnow()
        db.commit()
        log.info("content gen done for topic %d: %d queries × %d combos",
                 topic_id, len(queries), len(combos))
    finally:
        db.close()


# 2026-05-28 — combo 构造:从 BrandProfile 拿 creation_directions × copywriting_types.
# 单边空 → 用一个 None 占位(prompt 里降级,不注 hint);双空 → 单 (None, None) → 老路径
_MAX_COMBOS_PER_QUERY = int(os.environ.get("GEO_CONTENT_MAX_COMBOS_PER_QUERY", "9"))


def _build_combos(profile: BrandProfile) -> list[tuple[Optional[str], Optional[str]]]:
    """根据 profile.creation_directions × copywriting_types 出 combo 列表.

    cap 在 GEO_CONTENT_MAX_COMBOS_PER_QUERY(默认 9)— 防止 N×M 爆炸.
    """
    dirs = [d for d in (profile.creation_directions or []) if d and d in DIRECTION_HINTS]
    types = [t for t in (profile.copywriting_types or []) if t and t in TYPE_HINTS]
    if not dirs and not types:
        return [(None, None)]  # 兜底:老路径,1 篇
    if not dirs:
        return [(None, t) for t in types[:_MAX_COMBOS_PER_QUERY]]
    if not types:
        return [(d, None) for d in dirs[:_MAX_COMBOS_PER_QUERY]]
    out: list[tuple[Optional[str], Optional[str]]] = []
    for d in dirs:
        for t in types:
            out.append((d, t))
            if len(out) >= _MAX_COMBOS_PER_QUERY:
                return out
    return out


def _run_per_item(
    db, t: AiTelemetryTopicORM, profile: BrandProfile,
    topic_id: int, plan_id: int | None,
    plan_items: list[dict], mark_auto_run: bool,
) -> None:
    """按 publishing_plan_items 逐条出稿.

    一条 item → 一篇 doc。doc 按 (topic_id, plan_item_id) upsert:
    - 已有 doc → 覆写 title/body/summary,把 status 回 pending_review
    - 没有 doc → 新建
    模板缺失或不存在 → 直接走旧的 _generate_one(画像 prompt 兜底).
    """
    provider, model_id, api_key = _resolve_provider()
    style_refs = _load_style_refs(db, topic_id)

    # 批量取模板,减少 N 次查询
    tmpl_ids = {it.get("template_id") for it in plan_items if it.get("template_id")}
    tmpl_by_id: dict[int, ContentTemplateORM] = {}
    if tmpl_ids:
        for tmpl in (
            db.query(ContentTemplateORM)
              .filter(ContentTemplateORM.id.in_(list(tmpl_ids)))
              .all()
        ):
            tmpl_by_id[tmpl.id] = tmpl

    # 已有 doc 索引 — 2026-05-28 改成 (plan_item_id, creation_direction, copywriting_type)
    # 三元 key,支持同一 plan_item 有多个 combo 变体(N×M).
    # combo 字段为 None 时存空串作 key,便于查找.
    def _doc_key(pid: Optional[str], d: Optional[str], t: Optional[str]) -> str:
        return f"{pid or ''}|{d or ''}|{t or ''}"
    existing_by_combo: dict[str, TopicGeneratedDocORM] = {}
    for d in (
        db.query(TopicGeneratedDocORM)
          .filter(TopicGeneratedDocORM.topic_id == topic_id)
          .filter(TopicGeneratedDocORM.plan_item_id.isnot(None))
          .all()
    ):
        if d.plan_item_id:
            existing_by_combo[_doc_key(d.plan_item_id, d.creation_direction, d.copywriting_type)] = d

    n_ok = 0
    for it in plan_items:
        item_id = str(it.get("id") or "")
        q = str(it.get("query") or "").strip()
        seed = str(it.get("seed") or "").strip()
        # 2026-06-11 — 多选 queries 行:这组监测问题要被正文自然覆盖;legacy 单 query 行兼容.
        cover_queries = [str(x).strip() for x in (it.get("queries") or []) if str(x).strip()]
        if not cover_queries and q:
            cover_queries = [q]
        # seed-based 行用 seed 当主题;legacy 行 fallback 到 query.
        topic_text = seed or q or (cover_queries[0] if cover_queries else "")
        platform = str(it.get("platform") or "") or None
        tmpl_id = it.get("template_id")
        tmpl = tmpl_by_id.get(tmpl_id) if tmpl_id else None
        if not topic_text:
            continue

        # 2026-05-28 — 单行 combo override.行内非空 → 用行的,否则用画像默认.
        # 双方都空 → 单变体 (None, None) 走老路径.
        row_dirs = [d for d in (it.get("creation_directions") or []) if d and d in DIRECTION_HINTS]
        row_types = [t for t in (it.get("copywriting_types") or []) if t and t in TYPE_HINTS]
        if row_dirs or row_types:
            # 行 override:只用本行的(笛卡尔积,各边空补 [None])
            dirs = row_dirs or [None]
            types = row_types or [None]
            combos: list[tuple[Optional[str], Optional[str]]] = []
            for dx in dirs:
                for tx in types:
                    combos.append((dx, tx))
                    if len(combos) >= _MAX_COMBOS_PER_QUERY:
                        break
                if len(combos) >= _MAX_COMBOS_PER_QUERY:
                    break
        else:
            combos = _build_combos(profile)

        for direction, copywriting_type in combos:
            ckey = _doc_key(item_id, direction, copywriting_type)
            doc = existing_by_combo.get(ckey)
            if doc is None:
                doc = TopicGeneratedDocORM(
                    topic_id=topic_id, execution_plan_id=plan_id,
                    plan_item_id=item_id or None,
                    template_id=tmpl.id if tmpl else None,
                    platform=platform,
                    source_query_text=topic_text, status="pending_review",
                    selected_for_review=True,
                    llm_model=model_id, source="ai",
                    creation_direction=direction,
                    copywriting_type=copywriting_type,
                )
                db.add(doc)
            else:
                # 重生:清错 + 把 status 回 pending_review,等 LLM 跑完覆写正文
                doc.template_id = tmpl.id if tmpl else None
                doc.platform = platform
                doc.source_query_text = topic_text
                doc.generation_error = None
                doc.status = "pending_review"
                doc.selected_for_review = True
                doc.llm_model = model_id
                doc.source = "ai"

            if not provider:
                doc.generation_error = "DEEPSEEK_API_KEY / OPENROUTER_API_KEY 都未配置"
                doc.title = f"[未生成] {topic_text}"
                continue
            try:
                rules_block = _platform_rules_block(db, platform)
                if tmpl and direction is None and copywriting_type is None:
                    # 单变体老路径走 template;有 combo 时即使有 template 也走 _generate_one
                    # (template prompt 不接 combo 注入,直接走 profile combo)
                    title, body, summary = _generate_with_template(
                        profile, tmpl, topic_text, platform or "", provider, api_key,
                        seed=seed or None, style_refs=style_refs,
                        cover_queries=cover_queries,
                        platform_rules=rules_block,
                    )
                else:
                    medias = _match_topic_media(db, topic_id, topic_text)
                    title, body, summary = _generate_one(
                        profile, topic_text, provider, api_key,
                        direction=direction, copywriting_type=copywriting_type,
                        medias=medias, topic_id=topic_id, style_refs=style_refs,
                        cover_queries=cover_queries,
                        platform_rules=rules_block,
                    )
                doc.title = title
                allow_md = bool(TYPE_HINTS.get(copywriting_type or "", {}).get("allow_md", False))
                if allow_md:
                    # LLM 已经在正文内嵌图,不再追加末尾列表
                    doc.body_markdown = body
                else:
                    doc.body_markdown = _append_media_to_body(db, topic_id, topic_text, body)
                doc.summary = summary
                n_ok += 1
            except Exception as e:  # noqa: BLE001
                log.warning("content gen failed for item=%s combo=(%s,%s) topic=%d: %s",
                            item_id, direction, copywriting_type, topic_id, e)
                doc.generation_error = str(e)[:500]
                doc.title = f"[生成失败] {topic_text}"

    if mark_auto_run:
        t.auto_generate_last_run_at = datetime.utcnow()
    db.commit()
    log.info(
        "content gen done(per-item) topic %d: ok=%d / total=%d",
        topic_id, n_ok, len(plan_items),
    )


def regenerate_doc(db, doc: TopicGeneratedDocORM) -> TopicGeneratedDocORM:
    """重新生成单篇已存在的 doc — 就地覆写 title/body/summary.

    复用 doc 自带的 source_query_text / creation_direction / copywriting_type /
    template_id / platform,尽量复现这篇稿原本的生成路径:
      - 有 template 且无 combo(direction/type 都空)→ 走模板路径
      - 否则 → 走 _generate_one(画像 + combo 注入 + 配图)
    成功 → status 回 pending_review、清 generation_error;失败直接 raise(调用方记错).
    同步执行(LLM 单条 ~20-60s).
    """
    topic_id = doc.topic_id
    t = db.get(AiTelemetryTopicORM, topic_id)
    if not t:
        raise RuntimeError(f"topic {topic_id} not found")
    try:
        profile_data = json.loads(t.profile_json or "{}")
        if not isinstance(profile_data, dict):
            profile_data = {}
        profile = BrandProfile(**profile_data)
    except Exception:  # noqa: BLE001
        profile = BrandProfile()

    query = (doc.source_query_text or "").strip()
    if not query:
        raise RuntimeError("doc 缺少监测问题文本,无法重新生成")

    provider, model_id, api_key = _resolve_provider()
    if not provider:
        raise RuntimeError("DEEPSEEK_API_KEY / OPENROUTER_API_KEY 都未配置")

    direction = doc.creation_direction
    copywriting_type = doc.copywriting_type
    tmpl = db.get(ContentTemplateORM, doc.template_id) if doc.template_id else None
    style_refs = _load_style_refs(db, topic_id)

    rules_block = _platform_rules_block(db, doc.platform)
    if tmpl and direction is None and copywriting_type is None:
        # 单变体走模板;有 combo 时模板 prompt 不接注入,改走 _generate_one
        title, body, summary = _generate_with_template(
            profile, tmpl, query, doc.platform or "", provider, api_key,
            style_refs=style_refs,
            platform_rules=rules_block,
        )
        doc.body_markdown = body
    else:
        medias = _match_topic_media(db, topic_id, query)
        title, body, summary = _generate_one(
            profile, query, provider, api_key,
            direction=direction, copywriting_type=copywriting_type,
            medias=medias, topic_id=topic_id, style_refs=style_refs,
            platform_rules=rules_block,
        )
        allow_md = bool(TYPE_HINTS.get(copywriting_type or "", {}).get("allow_md", False))
        doc.body_markdown = body if allow_md else _append_media_to_body(db, topic_id, query, body)

    doc.title = title
    doc.summary = summary
    doc.llm_model = model_id
    doc.generation_error = None
    doc.status = "pending_review"
    doc.selected_for_review = True
    db.commit()
    db.refresh(doc)
    log.info("content regen done: doc=%d topic=%d", doc.id, topic_id)
    return doc


_MEDIA_APPEND_MAX = 3
_MEDIA_BLOCK_HEADER = "── 自动配图建议 ──"

def _match_topic_media(db, topic_id: int, query: str) -> list[TopicMediaORM]:
    """按 query 关键词模糊匹配 topic 已上传素材(filename 子串).

    召回策略:
      1. 把 query 拆成关键词(去标点 / 短词),依次在 filename 里找子串
      2. 命中即累计;同一素材只算一次,按 uploaded_at desc 取前 _MEDIA_APPEND_MAX
      3. 若 query 无任何命中,退到「最新 3 张素材」兜底(让 admin 至少有可挑的)
      4. 2026-05-28 起 image + video 都召回(由 prompt 决定怎么用)
    """
    rows = (
        db.query(TopicMediaORM)
          .filter(TopicMediaORM.topic_id == topic_id)
          .order_by(TopicMediaORM.uploaded_at.desc())
          .all()
    )
    if not rows:
        return []
    q = (query or "").lower()
    # 简单切词:把常见标点 / 空白替换成空格,过滤 1 字短词(英文 1 字母 / 中文单字保留意义低)
    tokens = [w for w in re.split(r"[\s,。!?:;、,/\\()\[\]【】「」“”\"'·.…—-]+", q) if len(w) >= 2]
    if not tokens:
        return rows[:_MEDIA_APPEND_MAX]
    hits: list[TopicMediaORM] = []
    seen: set[int] = set()
    for r in rows:
        fn = (r.filename or "").lower()
        if any(t in fn for t in tokens):
            if r.id not in seen:
                hits.append(r); seen.add(r.id)
        if len(hits) >= _MEDIA_APPEND_MAX:
            break
    if hits:
        return hits
    # 兜底:即使 filename 不匹配,也给最新几张让 admin 决定
    return rows[:_MEDIA_APPEND_MAX]


def _format_media_block(topic_id: int, medias: list[TopicMediaORM]) -> str:
    """正文末尾追加的纯文本配图块.不用 Markdown(平台直接粘贴会出乱码).

    2026-05-28 — URL 改用 /public/topic-media/.. 公开端点(UUID 文件名保护),
    `<img>` 标签直接渲染,发布到 公众号 / 知乎 / 小红书 都能用.
    """
    if not medias:
        return ""
    lines = [_MEDIA_BLOCK_HEADER]
    for i, m in enumerate(medias, 1):
        url = _media_public_url(m)
        kind_label = "视频" if m.kind == "video" else "图片"
        lines.append(
            f"{i}. [{kind_label}] {m.filename or f'media-{m.id}'} → {url}"
        )
    return "\n\n" + "\n".join(lines)


def _append_media_to_body(db, topic_id: int, query: str, body: str) -> str:
    """业务封装:body 已经生成完,按 query 召回图片,附在末尾.
    召回失败或 0 张 → 原样返回.异常吞掉(配图属增强,不能拖稿生成失败).
    """
    try:
        medias = _match_topic_media(db, topic_id, query)
        block = _format_media_block(topic_id, medias)
        if block:
            return (body or "") + block
        return body
    except Exception:  # noqa: BLE001
        log.warning("append media failed topic=%d q=%r — skipped", topic_id, query, exc_info=True)
        return body


def _render_template(prompt_template: str, vars: dict[str, object]) -> str:
    """简易 mustache 替换:{{key}} → str(value).未匹配的占位符保留原样."""
    s = prompt_template or ""
    for k, v in vars.items():
        s = s.replace("{{" + k + "}}", str(v if v is not None else ""))
    return s


def _build_brand_block(profile: BrandProfile) -> str:
    """画像摘要 — 给模板里 {{brand_block}} 占位用。比 _build_system_prompt 紧凑些."""
    parts: list[str] = []
    if profile.brand_diff_tags:
        parts.append(f"品牌差异化:{', '.join(profile.brand_diff_tags)}")
    if profile.content_tones:
        parts.append(f"调性:{', '.join(profile.content_tones)}")
    if profile.content_redlines:
        parts.append(f"内容雷区(必须避开):{', '.join(profile.content_redlines)}")
    if profile.brand_slogan:
        parts.append(f"Slogan:{profile.brand_slogan}")
    if profile.core_message:
        parts.append(f"核心信息:{profile.core_message}")
    return "\n".join(parts)


def _platform_rules_block(db, platform: Optional[str]) -> str:
    """2026-06-12 — 按发布平台取审核红线(platform_rules 表),渲染成 prompt 注入段.

    平台为空 / 没配规则 → 空串(生成行为不变)。
    """
    p = (platform or "").strip()
    if not p:
        return ""
    try:
        from geo.models.ai_telemetry import PlatformRuleORM
        row = db.query(PlatformRuleORM).filter(PlatformRuleORM.platform == p).first()
    except Exception:  # noqa: BLE001 — 表还没迁移时不阻塞生成
        return ""
    rules = (row.rules_text or "").strip() if row else ""
    if not rules:
        return ""
    return (
        f"\n\n【{p} 平台审核红线 — 违反任何一条稿件会被平台拒审,必须全部遵守】\n"
        f"{rules[:4000]}"
    )


def _build_cover_queries_block(cover_queries: Optional[list[str]], topic_text: str = "") -> str:
    """多选 queries 行的覆盖要求段 — 追加到 user prompt 末尾.

    单条且与主题相同(legacy 单 query 行)时返回空串,不重复啰嗦。
    """
    qs = [q for q in (cover_queries or []) if q and q != topic_text]
    if not qs:
        return ""
    bullets = "\n".join(f"  - {q}" for q in qs[:20])
    return (
        f"\n\n本文必须自然覆盖以下用户真实搜索问题(围绕它们组织内容,"
        f"在正文中逐一给出解答或信息;融进行文,不要把问题原文罗列成清单):\n{bullets}"
    )


def _generate_with_template(
    profile: BrandProfile, tmpl: ContentTemplateORM,
    query: str, platform: str,
    provider: str, api_key: str,
    seed: Optional[str] = None,
    style_refs: Optional[list] = None,
    cover_queries: Optional[list[str]] = None,
    platform_rules: str = "",
) -> tuple[str, str, str]:
    """模板路径 — system prompt 仍走品牌画像,user prompt 走模板渲染.

    seed 非空时(seed-based plan),模板里 {seed} 拿到种子文本,{query} 拿到 seed 副本以兼容
    旧模板;legacy plan 行 seed 为 None,两个变量都拿 query.
    cover_queries 非空时在渲染结果后追加「需自然覆盖的问题组」段(多选 query 行)。
    """
    system_prompt = _build_system_prompt(profile, style_refs=style_refs)
    brand_block = _build_brand_block(profile)
    user_prompt = _render_template(tmpl.prompt_template, {
        "query": query,
        "seed": seed or query,
        "brand": profile.company_short_name or profile.company_full_name or "",
        "industry": profile.industry or "",
        "platform": platform or (profile.target_platforms[0] if profile.target_platforms else ""),
        "length_min": tmpl.length_min,
        "length_max": tmpl.length_max,
        "brand_block": brand_block,
    })
    user_prompt += _build_cover_queries_block(cover_queries, topic_text=query)
    user_prompt += platform_rules
    return _call_llm(system_prompt, user_prompt, provider, api_key)


def _call_llm(
    system_prompt: str, user_prompt: str,
    provider: str, api_key: str,
) -> tuple[str, str, str]:
    """OpenAI-兼容 /chat/completions 调用 + JSON 解析 + Markdown 兜底清洗."""
    if provider == "deepseek":
        url = f"{DEEPSEEK_BASE_URL}/chat/completions"
        model = DEEPSEEK_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    else:
        url = OPENROUTER_URL
        model = OPENROUTER_DEEPSEEK_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://www.vigilath.com",
            "X-Title": "GEO Content Generator",
        }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
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
    title = _strip_md_inline(str(parsed.get("title") or ""))[:200]
    body = _strip_md_block(str(parsed.get("body") or ""))
    summary = _strip_md_inline(str(parsed.get("summary") or ""))[:500]
    if not title or not body:
        raise RuntimeError("LLM returned empty title/body")
    return title, body, summary


def _generate_one(
    profile: BrandProfile, query: str, provider: str, api_key: str,
    *,
    direction: Optional[str] = None,
    copywriting_type: Optional[str] = None,
    medias: Optional[list] = None,
    topic_id: Optional[int] = None,
    style_refs: Optional[list] = None,
    cover_queries: Optional[list[str]] = None,
    platform_rules: str = "",
) -> tuple[str, str, str]:
    """单条 query → (title, body_markdown, summary).

    provider:
      - "deepseek":  直连 https://api.deepseek.com/chat/completions,model=deepseek-chat
      - "openrouter": 走 https://openrouter.ai,model=deepseek/deepseek-chat

    2026-05-28 — direction / copywriting_type / medias 参数:
      - 非空时:按 combo 注入形式约束段;allow_md=True 的类型放开 markdown(可内嵌图片)
      - 全空时:退回到 2026-05-18 的"纯净排版文本"老路径,行为不变
    """
    system_prompt = _build_system_prompt(
        profile, direction=direction, copywriting_type=copywriting_type,
        medias=medias, topic_id=topic_id, style_refs=style_refs,
    )
    allow_md = bool(TYPE_HINTS.get(copywriting_type or "", {}).get("allow_md", False))
    # 篇幅来自 TYPE_HINTS,combo 没给就走老的 800-1500 字默认
    type_cfg = TYPE_HINTS.get(copywriting_type or "", {})
    body_len_spec = str(type_cfg.get("len") or "800-1500 字")

    if allow_md:
        # markdown 友好:允许 # 标题 / **加粗** / ![](url) 图片嵌入,不再 strip
        body_rules = (
            f"  1. 可以使用 Markdown 标记(# 标题 / ## 二级 / **加粗** / 列表 / ![图片](url) / [链接](url));\n"
            f"  2. 如果上面给了图片素材列表,**必须在正文 2-3 处自然位置嵌入 ![描述](素材url)**;\n"
            f"  3. 段落之间空一行,文章首尾要有钩子段和总结段;\n"
            f"  4. 标点用中文全角,英文术语 / 数字保留原样。"
        )
    else:
        # 老规则:严禁 markdown,平台直发友好
        body_rules = (
            f"  1. 严禁使用 Markdown / HTML 标记 — 不要出现 # ## ### **加粗** *斜体* `代码` > 引用 [链接](url) ![图片] 等任何符号;\n"
            f"  2. 严禁使用 - * 1. 等列表前缀;需要分点时用「一、二、三、」或「①②③」中文序号开头另起一段;\n"
            f"  3. 小标题独占一行、不加任何符号修饰,正文段落与小标题之间空一行;\n"
            f"  4. 段落与段落之间用一个空行分隔,段内不要硬换行;\n"
            f"  5. 所有标点用中文全角(,。!?:;「」),英文术语 / 数字保留原样即可。"
        )

    cover_block = _build_cover_queries_block(cover_queries, topic_text=query)
    user_prompt = (
        f"针对下面这个{'主题' if cover_block else '问题'},写一篇符合资料调性、可以直接复制发布的文章。\n"
        f"{'主题' if cover_block else '问题'}:{query}"
        f"{cover_block}{platform_rules}\n\n"
        f"输出严格 JSON,字段:\n"
        f'  "title": 文案标题(吸睛,≤30 字,纯文本不要带任何符号修饰),\n'
        f'  "summary": 200 字内的摘要(纯文本,用于卡片预览),\n'
        f'  "body": 文章正文({body_len_spec})。\n\n'
        f"正文排版强制要求(违反会导致稿件不可用):\n"
        f"{body_rules}\n\n"
        f"只输出 JSON,不要包前后 ``` 围栏。"
    )
    if provider == "deepseek":
        url = f"{DEEPSEEK_BASE_URL}/chat/completions"
        model = DEEPSEEK_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    else:  # openrouter
        url = OPENROUTER_URL
        model = OPENROUTER_DEEPSEEK_MODEL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://www.vigilath.com",
            "X-Title": "GEO Content Generator",
        }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        # DeepSeek/OpenRouter 都支持 OpenAI 风格 response_format;DeepSeek 要求 user
        # message 里出现 "json" 字样,我们 prompt 末尾明确写了"只输出 JSON",满足要求
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
    title = _strip_md_inline(str(parsed.get("title") or ""))[:200]
    raw_body = str(parsed.get("body") or "")
    # 2026-05-28 — allow_md=True 的类型(long_form / medium_post / faq_list)保留 markdown,
    # 否则按老规则 strip 成纯文本.title / summary 永远 strip 行内符号(卡片用,不允许 MD).
    body = raw_body if allow_md else _strip_md_block(raw_body)
    summary = _strip_md_inline(str(parsed.get("summary") or ""))[:500]
    if not title or not body:
        raise RuntimeError("LLM returned empty title/body")
    return title, body, summary


# ─────────── Markdown 兜底清洗 ───────────
# prompt 已经明令禁止 MD,但 LLM 偶尔会偷偷出 `**xxx**` / `# 标题` / `- 项`,
# 直接落到稿件里就会以原始符号显示在公众号 / 小红书。这里做一次轻量正则清理:
# 只剥**安全的**结构性符号,不动正文文字。粗暴 strip 不是目标——目标是「人眼
# 读起来跟纯文本一样」。

import re as _re

# 行首 # / ## / ### / ####...  → 留文字、独占一行(LLM 一般用作小标题)
_RE_HEADING = _re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
# 行首  -  /  *  /  •  /  · / 数字. / 数字) — 列表前缀,直接删掉,正文用「一、」中文序号
_RE_LIST_PREFIX = _re.compile(r"(?m)^\s{0,3}([\-\*•·]|\d+[.)、])\s+")
# 行首 > 引用
_RE_BLOCKQUOTE = _re.compile(r"(?m)^\s{0,3}>\s?")
# **加粗** / __加粗__ → 文字
_RE_BOLD = _re.compile(r"\*\*([^*\n]+?)\*\*|__([^_\n]+?)__")
# *斜体* / _斜体_ → 文字(注意要避免把孤立的 * 当列表前缀;前面已处理)
_RE_ITALIC = _re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)|(?<!_)_([^_\n]+?)_(?!_)")
# `代码` → 文字
_RE_INLINE_CODE = _re.compile(r"`([^`\n]+?)`")
# ```围栏``` 整段保留内容,只剥围栏
_RE_FENCE = _re.compile(r"```[a-zA-Z0-9]*\n?([\s\S]*?)```")
# [文字](链接) → 文字;![alt](链接) → alt
_RE_LINK = _re.compile(r"!?\[([^\]\n]*?)\]\([^)\n]*?\)")
# 表格分隔行 |---|---|
_RE_TABLE_SEP = _re.compile(r"(?m)^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")


def _strip_md_inline(s: str) -> str:
    """单行用 — 标题 / 摘要,清行内符号 + 折叠多空格."""
    s = _RE_BOLD.sub(lambda m: m.group(1) or m.group(2) or "", s)
    s = _RE_ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", s)
    s = _RE_INLINE_CODE.sub(r"\1", s)
    s = _RE_LINK.sub(r"\1", s)
    return s.strip()


def _strip_md_block(s: str) -> str:
    """正文用 — 先剥块级符号(标题/列表/引用/围栏/表格分隔),再走行内清理.
    最后压缩 3+ 连续空行到 2 行,避免段落空白爆炸.
    """
    s = _RE_FENCE.sub(r"\1", s)
    s = _RE_HEADING.sub("", s)
    s = _RE_BLOCKQUOTE.sub("", s)
    s = _RE_LIST_PREFIX.sub("", s)
    s = _RE_TABLE_SEP.sub("", s)
    s = _RE_BOLD.sub(lambda m: m.group(1) or m.group(2) or "", s)
    s = _RE_ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", s)
    s = _RE_INLINE_CODE.sub(r"\1", s)
    s = _RE_LINK.sub(r"\1", s)
    s = _re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ─────────── 2026-05-28 — 创作方向 × 文案类型 多变体生成 ───────────

# 7 个创作方向 — 每个值对应一段写作指南.profile.creation_directions 多选自此枚举.
DIRECTION_HINTS: dict[str, str] = {
    "industry_insight":  "以行业趋势 / 市场数据 / 头部玩家动向切入,产出有信息密度的分析。"
                         "避免泛泛而谈,每个论点配 1 个数据 / 案例 / 引述支撑。",
    "case_story":        "围绕一个真实案例展开:背景 → 挑战 → 我方解法 → 量化结果 → 启发。"
                         "案例主角用资料里的 case_stories 或 customer 真实名字,不要虚构。",
    "how_to_guide":      "用步骤化叙述:Step 1 / Step 2 / Step 3 ...,每步要有可执行动作 + 判断节点。"
                         "适合「怎么做 / 怎么选」类意图查询,先给框架再展开。",
    "trend_forecast":    "用前瞻视角:近 12-36 个月可能发生的变化 + 应对建议。"
                         "至少引用 1 个权威信号(政策 / 头部公司动作 / 监管文件)。",
    "product_review":    "对比 2-3 个同类产品 / 方案,列优劣矩阵,给出推荐场景。"
                         "评测维度 ≥ 4 个(价格 / 性能 / 适配 / 服务),保持客观语气。",
    "customer_story":    "第一人称引述客户原话(标注客户姓名 + 行业),用 2-3 段还原使用场景 + 量化成果。"
                         "篇幅 60% 给客户故事,40% 给我方点评 / 关联业务。",
    "faq":               "8-12 条常见问题 + 每题 100-200 字回答,问题先于回答。"
                         "问题口语化(模拟真实用户提问),回答专业精炼。",
}

# 6 种文案类型 — 决定篇幅 / 形式约束 + 是否允许 markdown(图片嵌入).
# 'allow_md' = True 时 prompt 不强制纯文本,可以嵌入 Markdown 图片 / 加粗;
# False 时仍走老的"纯净排版文本"规则.
TYPE_HINTS: dict[str, dict[str, object]] = {
    "long_form":          {"len": "1500-2500 字", "allow_md": True,
                           "hint": "正文 3-5 个二级小节,每节 300-500 字,带过渡句。"
                                   "首段 100-150 字钩子,尾段总结 + 行动召唤。"},
    "medium_post":        {"len": "500-1500 字", "allow_md": True,
                           "hint": "正文 2-3 个二级小节,适合公众号 / 知乎中等阅读量帖子。"
                                   "首段开门见山,正文每节 1 个核心观点。"},
    "short_social":       {"len": "≤500 字", "allow_md": False,
                           "hint": "短社媒文案:无小节,1-3 个 emoji,1 个 CTA。"
                                   "首句 3 秒抓眼球,适合小红书 / 微博。"},
    "video_script_long":  {"len": "5-8 分钟口播稿(2000-3000 字)", "allow_md": False,
                           "hint": "段落用 [镜头] / [口播] / [屏幕字] 标注。"
                                   "前 10 秒钩子吸引完播,中段问题铺陈,尾段解决方案 + CTA。"},
    "video_script_short": {"len": "30-60 秒口播稿(150-300 字)", "allow_md": False,
                           "hint": "前 3 秒钩子(疑问 / 痛点) → 5 秒共鸣 → 15 秒解法 → 5 秒 CTA。"
                                   "用短句,口语化,禁书面词。"},
    "faq_list":           {"len": "8-12 条 Q&A(总长 1000-2000 字)", "allow_md": True,
                           "hint": "纯 Q&A 列表,每条问题独占一行(用「Q:」前缀),"
                                   "回答 100-200 字(用「A:」前缀)。问题口语化,回答专业。"},
}


def _build_combo_block(direction: Optional[str], copywriting_type: Optional[str]) -> str:
    """渲染 combo hint 段,塞进 system prompt.两个都为空 → 返回 '' (走老路径)."""
    if not direction and not copywriting_type:
        return ""
    lines: list[str] = ["", "## 本次稿件的形式要求"]
    if direction:
        h = DIRECTION_HINTS.get(direction, "")
        if h:
            lines.append(f"- 创作方向「{direction}」: {h}")
        else:
            lines.append(f"- 创作方向: {direction}")
    if copywriting_type:
        cfg = TYPE_HINTS.get(copywriting_type, {})
        len_ = cfg.get("len", "")
        hint = cfg.get("hint", "")
        if len_ or hint:
            lines.append(f"- 文案类型「{copywriting_type}」: 篇幅 {len_};{hint}")
        else:
            lines.append(f"- 文案类型: {copywriting_type}")
    return "\n".join(lines)


def _media_public_url(media: "TopicMediaORM", base: str = "") -> str:
    """把 storage_path → 公开 URL.

    storage_path 格式:.../data/topic_media/{topic_id}/{32hex}.{ext}
    返回:{base}/api/ai-telemetry/public/topic-media/{topic_id}/{32hex}.{ext}

    base 为空(默认)→ 相对路径,前端在同源下 / nginx 反代时直接用.
    设 GEO_PUBLIC_MEDIA_BASE 环境变量 → 绝对 URL(发布到公众号 / 知乎需要绝对 https).
    """
    base = base or os.environ.get("GEO_PUBLIC_MEDIA_BASE", "").rstrip("/")
    sp = (media.storage_path or "").replace("\\", "/")
    fname = sp.rsplit("/", 1)[-1] if "/" in sp else sp
    return f"{base}/api/ai-telemetry/public/topic-media/{media.topic_id}/{fname}"


def _build_media_block_for_prompt(medias: list["TopicMediaORM"], topic_id: int,
                                    allow_md: bool) -> str:
    """渲染素材清单段塞进 system prompt.

    2026-05-28 — 把用户上传到 TopicMedia 的图 / 视频列给 LLM,带**公开 URL**
    (走 /public/topic-media/{tid}/{32hex}.{ext} 端点,无需 Bearer auth,
    UUID 文件名 128 bit 熵不可猜测).LLM 在 allow_md 类型里直接嵌 ![](url) markdown.

    支持:
      - kind=image → markdown ![](url) 图片
      - kind=video → markdown [视频:filename](url) 链接(平台不支持 video 自动播放,留链接给 admin)
    """
    if not medias:
        return ""
    img_list = [m for m in medias if (m.kind or "image") == "image"]
    vid_list = [m for m in medias if m.kind == "video"]
    lines: list[str] = ["", "## 可用素材(用户已上传到该主题,均为公开 URL,可直接嵌入正文)"]
    if img_list:
        lines.append("图片素材:")
        for m in img_list:
            fn = m.filename or f"media-{m.id}"
            url = _media_public_url(m)
            lines.append(f"  - 文件名「{fn}」 URL: {url}")
    if vid_list:
        lines.append("视频素材:")
        for m in vid_list:
            fn = m.filename or f"video-{m.id}"
            url = _media_public_url(m)
            lines.append(f"  - 文件名「{fn}」 URL: {url}")
    lines.append("")
    if allow_md:
        lines.append("**在正文 2-3 处自然位置嵌入图片素材**:")
        lines.append("  - 图片用 markdown 标准语法: `![描述](url)`,url 从上面图片素材列表挑")
        lines.append("  - 视频用链接: `[观看视频:filename](url)`,放在引出处")
        lines.append("  - 首张图放开头钩子段之后,引出客户故事 / 案例时优先用对应素材")
        lines.append("  - 不要瞎编 URL — 必须用上面列出的真实 URL")
    else:
        lines.append("(本次文案偏短 / 视频脚本,无需主动嵌入素材;列表仅供你了解品牌已有视觉资产.)")
    return "\n".join(lines)


# ─────────── 自有文章文风学习(few-shot)───────────
# 2026-06-09 — 老的生成只喂品牌画像,完全没参考用户导入的自有文章,导致出稿
# 文风/结构/节奏跟自有稿对不上(例:程晓峰主题,用户上传了几篇自有文章,但 AI
# 出稿读起来完全是另一个人写的)。这里把同主题下 source="user" 的自有文章当文风
# 范例注入 system prompt,让 LLM 模仿其文风/结构/段落节奏/开头钩子/结尾,而不是
# 照抄内容。只取自有(user)稿,绝不拿 AI 自己生成的稿当范例(否则会自我强化跑偏)。
_STYLE_REF_MAX = int(os.environ.get("GEO_CONTENT_STYLE_REF_MAX", "2"))
_STYLE_REF_BODY_CHARS = int(os.environ.get("GEO_CONTENT_STYLE_REF_CHARS", "1800"))


def _load_style_refs(db, topic_id: int, limit: int = _STYLE_REF_MAX) -> list[dict]:
    """加载同主题下用户导入的自有文章,当文风范例.

    只取 source="user" 且正文非空的稿,按 created_at desc 取最近 limit 篇.
    优先已 approved/published 的(更代表用户认可的成稿),不足再补其它状态.
    返回 [{title, body}],body 截到 _STYLE_REF_BODY_CHARS 控 token.
    """
    if limit <= 0:
        return []
    try:
        rows = (
            db.query(TopicGeneratedDocORM)
              .filter(TopicGeneratedDocORM.topic_id == topic_id)
              .filter(TopicGeneratedDocORM.source == "user")
              .filter(TopicGeneratedDocORM.body_markdown != "")
              .order_by(TopicGeneratedDocORM.created_at.desc())
              .all()
        )
    except Exception:  # noqa: BLE001
        log.warning("load style refs failed topic=%d — skipped", topic_id, exc_info=True)
        return []
    if not rows:
        return []
    _PREFERRED = ("published", "approved")
    rows.sort(key=lambda d: 0 if (d.status or "") in _PREFERRED else 1)
    refs: list[dict] = []
    for d in rows[:limit]:
        body = (d.body_markdown or "").strip()
        if not body:
            continue
        if len(body) > _STYLE_REF_BODY_CHARS:
            body = body[:_STYLE_REF_BODY_CHARS].rstrip() + "……(略)"
        refs.append({"title": (d.title or "").strip(), "body": body})
    return refs


def _build_style_ref_block(style_refs: Optional[list]) -> str:
    """把自有文章范例拼成 system prompt 的「文风模仿」段."""
    if not style_refs:
        return ""
    lines = [
        "",
        "─── 自有文章文风范例(必须严格模仿)───",
        "下面是该品牌已导入的自有文章。请你深度学习并模仿它们的**文风、结构、",
        "段落节奏、开头钩子、结尾收束、句式长短、用词习惯、口吻语气**,让本次出稿",
        "读起来像同一个作者、同一个品牌写出来的。注意:",
        "  - 只学「怎么写」,不要照抄范例里的具体内容/事实/数据/案例;",
        "  - 本次主题以上面的「问题 / 核心信息」为准,不要被范例的主题带跑;",
        "  - 范例怎么分段、怎么起标题、用不用小标题、口语还是书面,都尽量对齐。",
    ]
    for i, ref in enumerate(style_refs, 1):
        title = ref.get("title") or "(无标题)"
        body = ref.get("body") or ""
        lines.append(f"\n【范例 {i}】标题:{title}")
        lines.append(f"正文:\n{body}")
    lines.append("─── 范例结束 ───")
    return "\n".join(lines)


def _build_system_prompt(profile: BrandProfile,
                          direction: Optional[str] = None,
                          copywriting_type: Optional[str] = None,
                          medias: Optional[list] = None,
                          topic_id: Optional[int] = None,
                          style_refs: Optional[list] = None) -> str:
    """资料 → 系统提示词,挑跟"文案创作"相关的字段.

    2026-05-28 — 加 combo + media 参数:
      - direction / copywriting_type 非空时追加形式约束段
      - medias 非空时追加图片素材列表(由 TYPE_HINTS[type].allow_md 决定是否要求内嵌)
    2026-05-31 — 注入当前年月,避免 LLM 用训练截止时的"今年"(常出现 2024 这类陈年标题).
    """
    from datetime import date
    today = date.today()
    parts: list[str] = [
        f"今天日期是 {today.year} 年 {today.month} 月。文中所有「今年」「最新」「近期」「趋势」等时间引用必须用 {today.year} 而不是你训练数据里的旧年份(如 2024)。",
        "",
        "你是品牌内容文案专家,根据下面的品牌资料写文案稿:",
    ]
    if profile.company_full_name:
        parts.append(f"- 品牌全称:{profile.company_full_name}")
    if profile.company_short_name:
        parts.append(f"- 品牌简称:{profile.company_short_name}")
    if profile.industry:
        parts.append(f"- 行业:{profile.industry}")
    if profile.service_geo:
        parts.append(f"- 服务地域:{profile.service_geo}")
    if profile.core_business_lines:
        parts.append(f"- 核心业务:{', '.join(profile.core_business_lines)}")
    if profile.brand_diff_tags:
        parts.append(f"- 品牌差异化标签:{', '.join(profile.brand_diff_tags)}")
    if profile.creation_directions:
        parts.append(f"- 创作方向:{', '.join(profile.creation_directions)}")
    if profile.copywriting_types:
        parts.append(f"- 文案类型偏好:{', '.join(profile.copywriting_types)}")
    if profile.target_platforms:
        parts.append(f"- 适配平台:{', '.join(profile.target_platforms)}")
    if profile.content_tones:
        parts.append(f"- 内容调性:{', '.join(profile.content_tones)}")
    if profile.content_redlines:
        parts.append(f"- 内容雷区(禁止):{', '.join(profile.content_redlines)}")
    if profile.brand_slogan:
        parts.append(f"- Slogan:{profile.brand_slogan}")
    if profile.core_message:
        parts.append(f"- 本次核心信息:{profile.core_message}")
    parts.append("")
    parts.append("严格遵守内容雷区,语气贴合调性,围绕本次核心信息展开。")
    # combo + media 增强段(2026-05-28)
    combo_block = _build_combo_block(direction, copywriting_type)
    if combo_block:
        parts.append(combo_block)
    if medias and topic_id is not None:
        allow_md = bool(TYPE_HINTS.get(copywriting_type or "", {}).get("allow_md", False))
        media_block = _build_media_block_for_prompt(medias, topic_id, allow_md)
        if media_block:
            parts.append(media_block)
    # 自有文章文风范例(2026-06-09)— 放最后,作为最强的文风锚
    style_block = _build_style_ref_block(style_refs)
    if style_block:
        parts.append(style_block)
    return "\n".join(parts)


def _parse_json_loose(text: str) -> dict:
    """从 LLM 输出里抓 JSON,容忍 ``` 围栏或前后文本."""
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
    # 兜底:正则抓第一对 { } 块
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
