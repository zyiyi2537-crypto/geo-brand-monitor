"""LLM 网关 — 复用 sentinel-service 的 llm_client(单 provider, openai-兼容 SDK).

设计:
- import 路径不强依赖 sentinel package(部署可能分开),用 importlib 软引用
- 缺 key / import 失败 → degrade to stub 模式,返回 stub JSON 不抛错
- 这样代码可上线,正式跑前只需 export LLM_PROVIDER + *_API_KEY

三种调用场景:
- extract_competitors_and_format(): Haiku 级,跑批后异步抽取(便宜)
- generate_cell_insight():         Sonnet 级,按需触发(中等)
- generate_topic_briefing():       Opus 级,周一 09:00 自动(贵)

模型分级靠 LLM_PROVIDER + *_MODEL env 配,不在代码里写死品牌.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)

# 复用 sentinel 的 llm_client(如果可达).否则 stub.
_llm_mod = None
try:
    _llm_mod = importlib.import_module("llm_client")  # sentinel 同进程时
except ImportError:
    try:
        # 退路:把 sentinel-service 加进 sys.path 再 import
        import sys, pathlib
        sentinel_path = pathlib.Path(__file__).resolve().parents[2] / "sentinel-service"
        if sentinel_path.exists() and str(sentinel_path) not in sys.path:
            sys.path.insert(0, str(sentinel_path))
            _llm_mod = importlib.import_module("llm_client")
    except Exception:  # noqa: BLE001
        _llm_mod = None
        log.warning("telemetry-service: llm_client not importable; running in stub mode")


def _has_real_llm() -> bool:
    if _llm_mod is None:
        return False
    try:
        return bool(_llm_mod.has_llm())
    except Exception:  # noqa: BLE001
        return False


def _provider_model() -> str:
    if _llm_mod is None:
        return "stub"
    try:
        return _llm_mod._model()
    except Exception:  # noqa: BLE001
        return "unknown"


def _chat_json(prompt: str, *, temperature: float = 0.3,
               max_completion_tokens: int = 1500) -> tuple[dict | list | None, str]:
    """跑一次 LLM chat,返回 (parsed_json, model_id).
    返回 (None, "stub") 表示降级。
    """
    if not _has_real_llm():
        return None, "stub"
    try:
        # response_format=json_object 不是所有 provider 都支持,先不强约束,
        # 让 prompt 自己保证 JSON-only 输出.
        resp = _llm_mod.chat_create(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        # 容错:LLM 偶尔回 ```json ... ``` 包裹
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
            if text.endswith("```"):
                text = text[:-3]
        parsed = json.loads(text)
        return parsed, _provider_model()
    except Exception as e:  # noqa: BLE001
        log.warning("LLM call failed, returning stub: %s", e)
        return None, "error"


# ─────────────────── prompt 模板(版本化) ──────────────────

EXTRACT_PROMPT_VERSION = "extract_v3"
CELL_PROMPT_VERSION = "cell_v1"
BRIEFING_PROMPT_VERSION = "briefing_v1"


def _extract_prompt(target: str, query: str, engine: str, answer: str,
                    citations: list[dict]) -> str:
    cit_lines = "\n".join(
        f"- {c.get('domain', '')} | {c.get('title', '')}"
        for c in (citations or [])[:20]
    ) or "(无)"
    return f"""你是 GEO 分析师。从下面这条 AI 答复里抽取结构化信息。

【上下文】
检索词(我们关心是否被提及):{target}
引擎:{engine}
Query:{query}

【答复正文】
{answer[:3000]}

【该答复给出的 citations】
{cit_lines}

【任务】
1. competitors:先判定检索词「{target}」的**主体类型**(person / brand / product / organization),
   然后**只抽取同类型的竞品**,最多 5 个。规则:
   - 主体是【人物】(person,如某律师 / 创始人 / 专家)→ 只抽同行**人物**,不要把所在机构 / 公司 / 律所抽成竞品
   - 主体是【品牌或公司】(brand / organization)→ 只抽同业**公司 / 品牌**,不要把员工或代言人抽成竞品
   - 主体是【产品】(product)→ 只抽同类**产品**,不要把生产公司或人员抽成竞品
   每个 item 含 name(原文出现的名字)、count(在答复里出现次数)、snippet(前后约 60 字上下文,带 …)。
   如果答复里没有同类型竞品,competitors 返回空数组。
2. answer_format:在以下 5 类中选一个:listicle / single_recommendation / report / case_study / qa
3. citation_domains:答复 citations 列出的顶级域名集合(去重)
4. mention_position:检索词「{target}」在答复里的位置 — 四选一:
   - lead:出现在开头(前 30%)或被显式推荐为首选 / 列表第 1-3 项
   - body:出现在中段(30%-70%)或列表 4-7 项
   - tail:出现在末尾(后 30%)或列表 8+ / 一笔带过
   - unknown:检索词没出现,或难以判断位置
5. brand_rank:检索词「{target}」是答复里第几个被「实质性推荐 / 列入榜单 / 着重介绍」的同类实体
   (1-based,数字)。判定原则:
   - 看「实体级别的推荐次序」,不只是字面出现次序。例如答复列出 1.A 2.B 3.{target} 4.C,
     即使 {target} 在文本里第 4 个字符位置才出现,brand_rank 也是 3
   - 如果只是顺带提一句(没列入排序 / 没推荐),不算入次序,brand_rank 设为相对最后位次
   - 如果检索词「{target}」根本没出现,或难以判断,返回 null

【硬约束】
- 严格输出 JSON,不要解释、不要 markdown 包裹
- 不要编造未在原文出现的实体名(competitors 必须能在答复里找到 snippet)
- 中文识别 + 中文 snippet
- brand_rank 是整数或 null,绝不返回字符串

【输出格式】
{{"competitors": [{{"name":"...","count":1,"snippet":"..."}}],
  "answer_format": "...",
  "citation_domains": ["site.com", ...],
  "mention_position": "lead",
  "brand_rank": 3}}
"""


def extract_response_insights(*, target: str, query: str, engine: str,
                              answer: str, citations: list[dict]) -> dict[str, Any]:
    """跑批后异步调:从 answer 抽 competitors / answer_format / citation_domains.
    返回 {} 表示 LLM 不可用或失败 — caller 应自行兜底.
    """
    if not answer:
        return {}
    prompt = _extract_prompt(target, query, engine, answer, citations)
    parsed, model = _chat_json(prompt, temperature=0.2, max_completion_tokens=800)
    if not isinstance(parsed, dict):
        return {}
    pos = (parsed.get("mention_position") or "").strip().lower()
    if pos not in {"lead", "body", "tail", "unknown"}:
        pos = None
    rank_raw = parsed.get("brand_rank")
    brand_rank: Optional[int] = None
    if isinstance(rank_raw, int) and rank_raw >= 1:
        brand_rank = rank_raw
    elif isinstance(rank_raw, str):
        try:
            v = int(rank_raw.strip())
            if v >= 1:
                brand_rank = v
        except (ValueError, AttributeError):
            pass
    return {
        "competitors": parsed.get("competitors") or [],
        "answer_format": parsed.get("answer_format") or None,
        "citation_domains": parsed.get("citation_domains") or [],
        "mention_position": pos,
        "brand_rank": brand_rank,
        "llm_model": model,
    }


def _cell_insight_prompt(*, target: str, query: str, engine: str,
                         window_responses: list[dict]) -> str:
    blocks = []
    for r in window_responses[:20]:
        blocks.append(
            f"--- created_at={r.get('created_at')} hit={r.get('hit')} ---\n"
            f"ANSWER: {(r.get('answer') or '')[:2000]}\n"
            f"COMPETITORS: {r.get('competitors')}\n"
            f"CITATIONS_DOMAINS: {r.get('citation_domains')}\n"
            f"ANSWER_FORMAT: {r.get('answer_format')}\n"
        )
    return f"""你是 GEO(生成式引擎优化)战略分析师。客户希望在 AI 搜索引擎里被推荐。

【上下文】
检索词:{target}
引擎:{engine}
Query:{query}

【近期答复(最多 20 条)】
{chr(10).join(blocks)}

【分析任务】
1. verdict 五选一:hit_stable / hit_unstable / near_miss / no_signal / negative_mention
2. summary:1-2 句话总结
3. competitors_top3:取出现最多的 3 个竞品,每个 name + count + 一条 snippet
4. recommendations:3 条优化建议,每条带 priority(P0/P1/P2) + title(≤30字)
   + action(具体做什么 + 渠道 / 落地页 + 量化目标) + why(基于哪条证据)

【硬约束】
- 输出严格 JSON,不要 markdown 包裹
- 建议必须可执行,不接受 "提升内容质量" 这种空话
- 建议必须含可量化目标(如 "30 天内加 3 篇 TMT 案例")
- 中文输出

【输出格式】
{{"verdict":"...","summary":"...","competitors_top3":[{{"name":"...","count":N,"snippet":"..."}}],
  "recommendations":[{{"priority":"P0","title":"...","action":"...","why":"..."}}, ...]}}
"""


def generate_cell_insight(*, target: str, query: str, engine: str,
                          window_responses: list[dict]) -> dict[str, Any]:
    """对一个 cell 的近期 Response 做 LLM 诊断 + 给优化建议."""
    if not window_responses:
        return _stub_cell_insight(target, query, engine, reason="no_data")
    prompt = _cell_insight_prompt(
        target=target, query=query, engine=engine,
        window_responses=window_responses,
    )
    parsed, model = _chat_json(prompt, temperature=0.3, max_completion_tokens=1500)
    if not isinstance(parsed, dict):
        return _stub_cell_insight(target, query, engine, reason=f"llm_failed:{model}")
    parsed["llm_model"] = model
    return parsed


def _stub_cell_insight(target: str, query: str, engine: str, *, reason: str) -> dict[str, Any]:
    """降级返回 — LLM 不可用时给静态文案,UI 仍能展示."""
    return {
        "verdict": "no_signal",
        "summary": f"暂无诊断 ({reason})。配置 LLM_PROVIDER 后将自动生成。",
        "competitors_top3": [],
        "recommendations": [
            {
                "priority": "P1",
                "title": "增加投放主题密度",
                "action": f"围绕「{query}」选 3 个细分主题,每周 1 篇,30 天达到 12 篇",
                "why": "提升 {engine} 引擎对检索词的语义关联强度",
            },
        ],
        "llm_model": "stub",
    }


def _briefing_prompt(*, target: str, period_label: str, kpi_snapshot: dict,
                     new_hits: list[dict], lost_hits: list[dict],
                     cell_insights: list[dict]) -> str:
    return f"""你是 GEO 战略顾问。为客户撰写本周({period_label})的 AI 引擎曝光周报。

【上下文】
检索词:{target}
本周 KPI:{json.dumps(kpi_snapshot, ensure_ascii=False)}
本周新命中 cells:{json.dumps(new_hits, ensure_ascii=False)}
本周流失 cells:{json.dumps(lost_hits, ensure_ascii=False)}
各 cell 最新诊断(精简):{json.dumps(cell_insights, ensure_ascii=False)[:6000]}

【输出格式】
严格 JSON,字段:
- body_md:Markdown 正文(含 ## 本周亮点 / ## 本周 KPI / ## 下周优先行动 / ## 引擎画像差异 4 节)
- top_actions:list[{{priority,title,why,how}}],最多 5 条,P0/P1/P2 分级

【硬约束】
- body_md 总长 < 600 字(客户邮件场景)
- 优先行动必须含可量化目标
- 不重复 cell drawer 已有的细节,聚焦"跨 cell 看到的模式"
- 中文输出

【输出】
{{"body_md":"...","top_actions":[{{"priority":"P0","title":"...","why":"...","how":"..."}}]}}
"""


def generate_topic_briefing(*, target: str, period_label: str, kpi_snapshot: dict,
                            new_hits: list[dict], lost_hits: list[dict],
                            cell_insights: list[dict]) -> dict[str, Any]:
    """生成 topic 级周报."""
    prompt = _briefing_prompt(
        target=target, period_label=period_label, kpi_snapshot=kpi_snapshot,
        new_hits=new_hits, lost_hits=lost_hits, cell_insights=cell_insights,
    )
    parsed, model = _chat_json(prompt, temperature=0.5, max_completion_tokens=2500)
    if not isinstance(parsed, dict):
        return _stub_briefing(target, period_label, kpi_snapshot, reason=f"llm_failed:{model}")
    parsed["llm_model"] = model
    return parsed


def _stub_briefing(target: str, period_label: str, kpi: dict, *, reason: str) -> dict[str, Any]:
    body = (
        f"## 本周亮点\n- 暂无周报 LLM 输出 ({reason})\n\n"
        f"## 本周 KPI\n- 命中率:{kpi.get('hit_rate', '-')}\n"
        f"- TTFM:{kpi.get('ttfm_days', '-')}\n"
        f"- 新命中:{kpi.get('new_hits_count', 0)}\n"
        f"- 流失:{kpi.get('lost_hits_count', 0)}\n\n"
        f"## 下周优先行动\n- 配置 LLM_PROVIDER + 对应 API key 后将自动生成战略建议\n\n"
        f"## 引擎画像差异\n- 待 LLM 启用后填充\n"
    )
    return {
        "body_md": body,
        "top_actions": [],
        "llm_model": "stub",
    }
