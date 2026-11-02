"""Daily AI brief generator (OpenAI), map-reduce style.

Aggregates structured analyses for one symbol on one date into a Markdown
brief suitable for a morning summary email or Lark/Feishu doc.

For large corpora, posts are chunked into batches; each batch is mapped to
a small JSON summary (topics / risks / picks); a single reduce call merges
those plus deterministic global stats and the globally-top-ranked posts
into the final markdown. Small corpora (≤ batch_size relevant posts) skip
the map phase and go straight to reduce.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date as _date
from pathlib import Path

import openai

from storage import connect, init_schema, analyses_for_day, insert_brief
from llm_client import chat_create, has_openai, has_qwen

BRIEF_MODEL = os.environ.get("YUQING_BRIEF_MODEL", "gpt-4o-mini")
MAP_MODEL = os.environ.get("YUQING_BRIEF_MAP_MODEL", BRIEF_MODEL)
REDUCE_MODEL = os.environ.get("YUQING_BRIEF_REDUCE_MODEL", BRIEF_MODEL)
MAP_MAX_TOKENS = 1500
REDUCE_MAX_TOKENS = 4000

DEFAULT_BATCH_SIZE = 20
DEFAULT_TOP_NOTEWORTHY = 5

MAP_SYSTEM = """你正在为日度舆情简报做分批分析。给你一组帖子的结构化数据，输出**严格 JSON**：

{
  "topic_notes": [
    {"topic": "主题名", "what_said": "1-2 句概括散户/专业用户在说什么", "sample_post_ids": ["post_id1"]}
  ],
  "risks": [
    {"level": "low|medium|high", "type": "风险类型", "summary": "简述", "post_id": "post_idX"}
  ],
  "top_picks": ["post_idA", "post_idB"]
}

规则：
- topic_notes：根据帖子的 topics 字段归并同主题；每个主题给 1-2 句话总结，并引用 1-3 条 post_id
- risks：只保留 risk_level ∈ {medium, high} 的帖子
- top_picks：本批最值得关注的 ≤3 条 post_id（综合考虑情感强度、影响力、风险）
- post_id 字符串必须严格使用输入 post_id 字段的值，不要改写
- 严格 JSON，无任何额外文字 / 代码块标记
"""

REDUCE_SYSTEM = """你是一名舆情分析师，正在为公司公关 / 投关 / 二级市场团队撰写"日度舆情简报"。

输入字段：
- stats：全日确定值统计（总量、相关量、情感分布、风险分布、top_topics、noteworthy_top_ids）
- topic_notes：分批归并的主题分析（可能为空，表示语料较小，请直接从 posts 归纳主题）
- risks：去重后的 medium / high 风险信号（可能为空）
- posts：帖子查询表，**引用时只能从这里取 url / title / author**

请生成 Markdown 简报，结构如下：

# {symbol} 舆情简报 · {date}

## 一、概览
- 当日讨论量、情感占比、风险分布（用 stats 给的数）
- 一句话定性
- ⚠️ 不要编造与历史的对比；除非数据中明确给出 prior_day_stats

## 二、关键主题
列出 3-5 个最热主题（参考 topic_notes 与 stats.top_topics），每个：
- 主题名 — 帖子数 — 主导情感
- 1-2 句概括（综合 topic_notes 的 what_said；topic_notes 为空时直接从 posts 归纳）
- 引用 1 条 post（标题、链接，从 posts 取）

## 三、风险信号
若 risks 非空，每个：
- 风险类型 + 简述 + 链接（从 posts 取） + 建议处置
若空：一句话说明"今日未见 medium 及以上风险信号"

## 四、值得关注的帖子（按 stats.noteworthy_top_ids 顺序，最多 5 条）
每条：[标题](url) — 作者 — 情感倾向 / 风险等级（都用中文） — 一句话点评

## 五、建议动作
- 1-3 条具体建议

## 写作要求
- 口语化但专业，不要"客套"
- 所有引用 post_id 必须能在 posts 中找到
- **每一处提到具体帖子 / 事件 / 主题 / 风险信号 / 值得关注项,都必须带可点击的 Markdown 链接 `[标题](完整url)`**
  (url 从 posts 的 url 字段取)——**不要只写标题不给链接,也不要贴裸 url、不要截断 url**。
  关键主题、风险信号、值得关注帖、建议动作里引用到的每条 post 都要可点。posts 里确实没有 url 的才可省略。
- 不编造帖子或链接；若数据为空，明确说"无数据"
- 整篇控制在 600-1000 字
- **情感倾向 / 风险等级一律用中文，绝不出现英文词或中英混写**（不要写 bearish/neutral/medium 这类，也不要"中性(neutral)"这种括号注释）。
  情感映射:bullish→看多、bearish→看空、neutral→中性、mixed→复杂;风险映射:low→低风险、medium→中风险、high→高风险。
  例:"情感分布:2 条看空、2 条中性"(不是"2 条偏空(bearish)、2 条中性(neutral)")。
"""


def _summarize_analyses(rows) -> dict:
    n = len(rows)
    counts = Counter(r["sentiment_label"] or "unknown" for r in rows if r["is_relevant"])
    risk_counts = Counter(r["risk_level"] or "none" for r in rows if r["is_relevant"])
    topic_counts: Counter[str] = Counter()
    for r in rows:
        if not r["is_relevant"]:
            continue
        for t in json.loads(r["topics_json"] or "[]"):
            topic_counts[t] += 1
    return {
        "total_posts": n,
        "relevant_posts": sum(1 for r in rows if r["is_relevant"]),
        "sentiment_counts": dict(counts),
        "risk_counts": dict(risk_counts),
        "top_topics": topic_counts.most_common(10),
    }


def _post_id(r) -> str:
    return f"{r['source']}:{r['post_id']}"


def _row_to_full(r) -> dict:
    """Full payload — used for reduce-phase posts lookup."""
    return {
        "post_id": _post_id(r),
        "source": r["source"],
        "author": r["author"],
        "title": r["title"],
        "publish_time": r["publish_time"],
        "url": r["url"],
        "view_count": r["view_count"],
        "reply_count": r["reply_count"],
        "summary": r["summary"],
        "sentiment_label": r["sentiment_label"],
        "sentiment_score": r["sentiment_score"],
        "topics": json.loads(r["topics_json"] or "[]"),
        "stance": r["stance"],
        "intent": r["intent"],
        "risk_level": r["risk_level"],
        "risk_signals": json.loads(r["risk_signals_json"] or "[]"),
        "influence_potential": r["influence_potential"],
        "hidden_meaning": r["hidden_meaning"],
        "citations": json.loads(r["citations_json"] or "[]"),
    }


def _row_to_map_payload(r) -> dict:
    """Slim payload for map phase — drops hidden_meaning / citations / view counts."""
    return {
        "post_id": _post_id(r),
        "title": r["title"],
        "summary": r["summary"],
        "topics": json.loads(r["topics_json"] or "[]"),
        "sentiment_label": r["sentiment_label"],
        "sentiment_score": r["sentiment_score"],
        "stance": r["stance"],
        "intent": r["intent"],
        "risk_level": r["risk_level"],
        "risk_signals": json.loads(r["risk_signals_json"] or "[]"),
        "influence_potential": r["influence_potential"],
    }


def _noteworthy_score(r) -> float:
    inf = r["influence_potential"] or 0.0
    s = r["sentiment_score"] or 0.0
    return float(inf) * abs(float(s))


def _chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _call_map(batch, model):
    payload = {"posts": [_row_to_map_payload(r) for r in batch]}
    user = (
        "对以下一批帖子做主题/风险/亮点归并：\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    resp = chat_create(
        model,
        max_completion_tokens=MAP_MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": MAP_SYSTEM},
            {"role": "user", "content": user},
        ],
    )
    text = resp.choices[0].message.content or "{}"
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        out = {}
    return out, resp.usage


def _merge_map_outputs(outputs):
    topic_groups: dict = defaultdict(lambda: {"what_said": [], "sample_post_ids": []})
    risks = []
    top_picks: list[str] = []
    seen_risk: set = set()
    for out in outputs:
        for tn in (out.get("topic_notes") or []):
            t = (tn.get("topic") or "").strip()
            if not t:
                continue
            ws = (tn.get("what_said") or "").strip()
            if ws:
                topic_groups[t]["what_said"].append(ws)
            for pid in (tn.get("sample_post_ids") or []):
                if pid and pid not in topic_groups[t]["sample_post_ids"]:
                    topic_groups[t]["sample_post_ids"].append(pid)
        for r in (out.get("risks") or []):
            key = (r.get("level"), r.get("post_id"))
            if not r.get("post_id") or key in seen_risk:
                continue
            seen_risk.add(key)
            risks.append(r)
        for pid in (out.get("top_picks") or []):
            if pid and pid not in top_picks:
                top_picks.append(pid)
    return {
        "topic_notes": [
            {"topic": t, "what_said": " ".join(g["what_said"]),
             "sample_post_ids": g["sample_post_ids"]}
            for t, g in topic_groups.items()
        ],
        "risks": risks,
        "top_picks": top_picks,
    }


def _call_reduce(symbol, date, stats, merged, posts_lookup, model):
    payload = {
        "symbol": symbol,
        "date": date,
        "stats": stats,
        "topic_notes": merged["topic_notes"],
        "risks": merged["risks"],
        "posts": posts_lookup,
    }
    user = (
        f"为 {symbol} 在 {date} 撰写日度舆情简报。聚合数据如下：\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    resp = chat_create(
        model,
        max_completion_tokens=REDUCE_MAX_TOKENS,
        messages=[
            {"role": "system", "content": REDUCE_SYSTEM},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip(), resp.usage


def generate_brief(symbol: str, date: str | None = None,
                   db_path=None, out_dir: Path | None = None,
                   batch_size: int = DEFAULT_BATCH_SIZE,
                   top_noteworthy: int = DEFAULT_TOP_NOTEWORTHY) -> Path:
    if not (has_openai() or has_qwen()):
        sys.exit("no LLM key available. Set OPENAI_API_KEY (sk-...) or QWEN_API_KEY.")

    date = date or _date.today().isoformat()
    conn = connect(db_path) if db_path else connect()
    init_schema(conn)

    rows = analyses_for_day(conn, symbol, date)
    if not rows:
        sys.exit(f"no analyses found for {symbol} on {date}. "
                 f"Run `python cli.py analyze --symbol {symbol}` first.")

    # 新鲜度闸门:简报只讲最近 N 天的"内容"(按 publish_time),把"今天爬到但
    # 发布于 2024 年"的旧帖排除掉。publish_time 已知且早于窗口的丢弃;无日期的
    # (多为搜索结果未解析到发布时间)保留——它们都是今天入库,默认当作新内容。
    # 极端情况(当天全是旧内容)回退原始 rows,避免简报直接报"无数据"。
    from datetime import timedelta
    max_age = int(os.environ.get("SENTINEL_DISPLAY_MAX_AGE_DAYS", "3"))
    _cutoff = (_date.today() - timedelta(days=max_age - 1)).isoformat()
    _recent = [r for r in rows
               if not (r.get("publish_time") and r["publish_time"][:10] < _cutoff)]
    rows = _recent or rows

    stats = _summarize_analyses(rows)
    relevant = [r for r in rows if r["is_relevant"]]

    map_calls = 0
    map_in = map_out = 0
    if len(relevant) > batch_size:
        outputs = []
        for batch in _chunk(relevant, batch_size):
            out, usage = _call_map(batch, MAP_MODEL)
            outputs.append(out)
            map_calls += 1
            map_in += usage.prompt_tokens
            map_out += usage.completion_tokens
        merged = _merge_map_outputs(outputs)
    else:
        merged = {"topic_notes": [], "risks": [], "top_picks": []}

    # Deterministic global noteworthy ranking — feeds §四 in reduce
    ranked = sorted(relevant, key=_noteworthy_score, reverse=True)
    noteworthy_ids = [_post_id(r) for r in ranked[:top_noteworthy]]
    stats["noteworthy_top_ids"] = noteworthy_ids

    # Build posts lookup: top-N noteworthy + every post the map referenced.
    # Small-corpus path: include all relevant posts so reduce can derive
    # topic narratives directly.
    referenced_ids: set[str] = set(noteworthy_ids)
    for tn in merged["topic_notes"]:
        referenced_ids.update(tn.get("sample_post_ids") or [])
    for r in merged["risks"]:
        if r.get("post_id"):
            referenced_ids.add(r["post_id"])
    referenced_ids.update(merged["top_picks"])
    if len(relevant) <= batch_size:
        for r in relevant:
            referenced_ids.add(_post_id(r))

    by_pid = {_post_id(r): r for r in rows}
    posts_lookup = [_row_to_full(by_pid[pid]) for pid in referenced_ids if pid in by_pid]

    body, reduce_usage = _call_reduce(
        symbol, date, stats, merged, posts_lookup, REDUCE_MODEL
    )

    insert_brief(conn, symbol, date, body, REDUCE_MODEL)
    conn.commit()

    out_dir = out_dir or Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"brief_{symbol}_{date}.md"
    out_path.write_text(body, encoding="utf-8")

    print(f"[brief] {symbol} {date} → {out_path}")
    if map_calls:
        print(f"  map: {map_calls} calls · in={map_in} out={map_out} (model={MAP_MODEL})")
    print(f"  reduce: in={reduce_usage.prompt_tokens} out={reduce_usage.completion_tokens} "
          f"(model={REDUCE_MODEL})")
    return out_path
