"""脚本:Query 提取 + 语义扩展 — 两阶段,每阶段都用 LLM。

2026-05-26 改:提取阶段产出的不是「短关键词」而是**完整的 user query**,
扩展阶段每条 query 走 test_expand_seed.py 同一路径(paraphrase)。

流程:
  1. 输入:一段文本(品牌描述 / 业务说明)
  2. Stage 1 — LLM 提取 N 条**完整 user query**(每条 8-25 字,是真实用户会问 AI 的句子)
                同时判定实体类型(person / institution / product)
  3. Stage 2 — 对每条提取的 query,调用 suggest_queries 跑 paraphrase 扩展(K 条/query)
                同义改写 + 实体硬锁 + 字符完整性 + 实体黑名单 + 脏 seed 走 dirty prompt
  4. 输出按 query 分组 + JSON 落地到 tmp/

用法:
    DEEPSEEK_API_KEY=sk-xxx /home/DEV/GEO/backend/venv/bin/python \\
        /home/DEV/GEO/services/telemetry-service/scripts/test_extract_and_expand.py \\
        "企业跨境 / TMT 投资、海外并购的北京律师事务所,擅长 SPAC 并购、红筹架构" \\
        --queries 6 --per-query 15 \\
        --target "金诚同达" --industry "商事律所" --service-geo "北京"

跟 test_expand_seed.py 的差别:
  - test_expand_seed.py — 单条 seed → 50 条 paraphrase
  - 本脚本           — 一段文本 → 提 6 条 query → 每条 paraphrase 15 → 共 90 条
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
TS_ROOT = REPO_ROOT / "services" / "telemetry-service"
sys.path.insert(0, str(TS_ROOT))

# 复用 query_suggest 里已有的工具(实体类型识别 + LLM 调用基础设施)
from app.query_suggest import (  # noqa: E402
    DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    DeepSeekError, _detect_seed_entity_kind, suggest_queries,
)


DEFAULT_TEXT = (
    "企业跨境 / TMT 投资、海外并购的北京律师事务所,擅长上市公司收购、SPAC 并购、"
    "红筹架构搭建、VIE 拆除、跨境换股、港股 / 美股 IPO 法律顾问。"
)


_BULLET_RE = re.compile(r"^[•\-\*\d\.\)\]\s>「」『』\"\']+|[「」『』\"\']+$")


# ─── Stage 1:LLM 提取 user query(整句 prompt 形式)─────────


def _extract_prompt(text: str, count: int) -> str:
    return (
        f"任务:看下面这段文本,先判断**品牌主体身份**是【人 / 机构 / 产品】,然后"
        f"提取 {count} 条**完整的 user query**(每条 8-25 字,真实用户会问 AI 的句子),"
        f"用于后续 GEO / AEO 监测 — 每条 query 会再被 paraphrase 扩展。\n"
        f"\n"
        f"━━━ 输入文本 ━━━\n"
        f"{text}\n"
        f"\n"
        f"━━━ 主体身份判断(只能选一个)━━━\n"
        f"• **person**:文本主体是**一个具体的人**(律师 / 医生 / 顾问 / 教练 / 设计师 / 摄影师 …)\n"
        f"• **institution**:文本主体是**机构 / 团队 / 公司**(律所 / 律师事务所 / 医院 / 公司 / 工作室 …)\n"
        f"• **product**:文本主体是**产品 / 物品 / 工具 / 软件 / 服务**(机器人 / 软件 / 设备 / App …)\n"
        f"两者并存时(如某律师在某律所工作),按文本**主要落点**判断 — 文本核心在介绍**人**的业务"
        f"专长就 person,核心在介绍**机构**的服务规模就 institution。\n"
        f"\n"
        f"━━━ Query 要求(关键!不是短关键词)━━━\n"
        f"1. 每条是一句**完整的 user query** — 真实用户准备拿去问 AI 助手时的整句。\n"
        f"   句子结构通常是「[业务] 的 [地点] [身份]」/「[身份] for [业务]」,**包含 entity 词**。\n"
        f"   ✓「跨境并购的北京律师」「SPAC 并购方向的北京律师」「红筹架构搭建的律师事务所」\n"
        f"   ✓「适合跨境并购的北京律师」「擅长 SPAC 并购的律所」\n"
        f"   ✗「跨境并购」「SPAC 并购」「红筹架构」(太短,只是关键词,缺主体身份词)\n"
        f"   ✗「业务范围」「服务领域」(meta 维度名,信号为零)\n"
        f"   ✗「{text[:20]}…」(原文太长,要提炼成 1 个聚焦的子方向)\n"
        f"2. 每条 8-25 字。短关键词请加上 entity 词补成完整 query(如「跨境并购」→「跨境并购的北京律师」)。\n"
        f"3. 每条覆盖**一个独立的业务子方向 / 服务场景**,query 之间业务焦点应**互不重叠**。\n"
        f"4. **逐字使用文本里出现的业务 / 地点 / 实体词**,不要近义替换、不要泛化、不要造词。\n"
        f"5. **不要拼意图后缀**(推荐 / 哪家好 / 求推荐)— 这些留给后面 paraphrase 阶段去加。\n"
        f"   提取的 query 应是**干净的名词短语**(描述目标 entity),而不是已带意图的完整问句。\n"
        f"\n"
        f"━━━ 输出格式(严格遵守)━━━\n"
        f"第 1 行:`entity: person` 或 `entity: institution` 或 `entity: product`\n"
        f"第 2 行起:每行一条完整 query,不要编号 / 项目符号 / 引号 / 解释。\n"
        f"\n"
        f"示例输出格式(只是格式参考,不是内容):\n"
        f"entity: institution\n"
        f"跨境并购的北京律师事务所\n"
        f"SPAC 并购方向的北京律所\n"
        f"红筹架构搭建的北京律所\n"
        f"……"
    )


async def _llm_call(messages: list[dict], temperature: float = 0.5,
                    max_tokens: int = 4000) -> str:
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise DeepSeekError("no_key", "DEEPSEEK_API_KEY 未配置")
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(url, json=payload, headers=headers)
    if r.status_code != 200:
        raise DeepSeekError(f"http_{r.status_code}", r.text[:300])
    data = r.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


def _clean_line(s: str) -> str:
    return _BULLET_RE.sub("", s).strip().strip("「」『』\"'")


_ENTITY_LINE_RE = re.compile(
    r"^\s*entity\s*[::]\s*(person|institution|product)\b",
    re.IGNORECASE,
)


async def extract_queries(text: str, count: int) -> tuple[str, list[str]]:
    """返回 (entity_kind, queries)。entity_kind ∈ {'person','institution','product','generic'}。

    LLM 第一行返回 `entity: person|institution|product`,后续每行一条**完整 query**(8-25 字)。
    第一行解析失败 → entity_kind = 'generic'(交给 caller 用启发式兜底)。
    """
    msg = await _llm_call(
        messages=[
            {"role": "system",
             "content": "You analyze brand description text. First decide if the brand's subject is a person, institution, or product. Then extract complete 8-25 char Chinese user queries (NOT short keywords) for GEO/AEO monitoring. Strict output format: first line `entity: person|institution|product`, then one full query per line. No numbering, no quotes, no commentary."},
            {"role": "user", "content": _extract_prompt(text, count)},
        ],
        temperature=0.3,
        max_tokens=1200,
    )
    lines = msg.splitlines()
    entity_kind = "generic"
    q_lines = lines
    if lines:
        m = _ENTITY_LINE_RE.match(lines[0].strip())
        if m:
            entity_kind = m.group(1).lower()
            q_lines = lines[1:]
    out: list[str] = []
    seen: set[str] = set()
    for line in q_lines:
        q = _clean_line(line)
        # 整句 query 长度 6-50 字,挡过短(关键词)和过长(原文复制)
        if 6 <= len(q) <= 50 and q not in seen:
            seen.add(q)
            out.append(q)
    return entity_kind, out[:count]


# 旧函数名保持兼容(实际行为已切换到提整句 query)
extract_keywords = extract_queries


# ─── Stage 2:每个关键词扩展 K 条 user query ─────────
#
# 2026-05-26 改:直接复用 query_suggest.suggest_queries(test_expand_seed.py 同一路径),
# 走「语义同义改写」mode。Stage 2 输出风格跟 paraphrase 模式一致,
# 全套保护(实体硬锁 / 字符完整性 / 实体黑名单 / 脏 seed 走 dirty prompt)都生效。


async def expand_query(query: str, count: int, entity_kind: str,
                       industry: str, service_geo: str, target: str,
                       aliases: list[str]) -> list[str]:
    """走 query_suggest.suggest_queries 的 paraphrase pipeline(同 test_expand_seed.py)。

    entity_kind 不直接传入 — suggest_queries 内部用 _detect_seed_entity_kind 探,
    在 prompt 里自动注入实体硬锁。caller 传的 entity_kind 仅用于上层 UI 展示。
    """
    _ = entity_kind  # 当前实现不直接用,留给未来扩展(如 force_kind 参数)
    candidates, _clusters = await suggest_queries(
        query, count,
        target=target, aliases=aliases, industry=industry,
        service_geo=service_geo, profile_cases=[],
        include_autocomplete=False,
        include_clusters=False,
    )
    # candidates 是 [{text, score, sources}, ...],按 score 降序
    return [c["text"] for c in candidates]


# 旧函数名保持兼容(实际是对 query 跑 paraphrase)
expand_keyword = expand_query


# ─────────────────────────────────────────────────────────────────
# ─── 旧方式:自写「场景化扩展」prompt(已注释保留)──────────────
# ─────────────────────────────────────────────────────────────────
# 旧版自写 _expand_prompt + expand_keyword,prompt 鼓励「场景化 / 处境驱动 /
# 软对比」多样化句式;后过滤只挡对立实体词,不挡字段缺失。用户反馈太散,
# 2026-05-26 改用 paraphrase 路径(test_expand_seed.py)。下面是旧代码,
# 想回退把上面那段 expand_keyword 删掉,反注释这段就行。
#
# def _expand_prompt(keyword: str, count: int, entity_kind: str,
#                    industry: str, service_geo: str, target: str,
#                    aliases: list[str]) -> str:
#     if entity_kind == "person":
#         ent_clause = "实体类型:**「人」**(律师 / 医生 / 顾问 / 教练 等)— query 末尾问的是一个具体的人,用「哪位 / 哪个 / 推荐一位」"
#     elif entity_kind == "institution":
#         ent_clause = "实体类型:**「机构」**(律所 / 律师事务所 / 医院 / 公司 等)— query 末尾问的是一个机构,用「哪家 / 推荐几家」"
#     else:
#         ent_clause = "实体类型:推断不出(自行选合适量词)"
#     ind = f"行业:{industry}\n" if industry else ""
#     geo = f"服务地域:{service_geo}(query 里的地点只允许出现这个,或不带地点)\n" if service_geo else ""
#     avoid = ""
#     if target.strip():
#         alias_part = "、".join(f"「{a}」" for a in aliases) if aliases else ""
#         avoid = f"**禁名**:不要出现「{target}」" + (f" 或别名 {alias_part}" if alias_part else "") + "。\n"
#     return (
#         f"任务:围绕关键词「{keyword}」生成 {count} 条真实用户向 AI 助手提问的中文 query。\n"
#         f"\n"
#         f"━━━ 上下文 ━━━\n"
#         f"{ind}{geo}{ent_clause}\n"
#         f"{avoid}"
#         f"\n"
#         f"━━━ 要求 ━━━\n"
#         f"1. 每条都是真实用户准备「找 / 选 / 咨询 / 求帮忙」时脱口而出的话,带具体场景 / 身份 / 处境。\n"
#         f"2. **关键词「{keyword}」必须在每条 query 里逐字出现**(允许内部位置变化,但不能漏字 / 换字)。\n"
#         f"3. 句式混搭(粗略配比):\n"
#         f"   • 推荐 / 找人型(50%-60%):「推荐一位做 X 的 Y」「X 找哪位 Y 靠谱」「[城市] 哪位 Y 擅长 X」\n"
#         f"   • 处境驱动型(25%-35%):「[身份] 想 [动作],该找哪位 Y」「第一次 [动作] 找谁靠谱」\n"
#         f"   • 软对比型(10%-15%):「做 X 的 Y,A 和 B 哪个更合适」(克制,别凑数)\n"
#         f"4. **不许**:\n"
#         f"   ✗ 认知 / 元 / SEO 句式(「什么是 X」「X 流程」「X 注意事项」「X 有哪些类型」)\n"
#         f"   ✗ 纯定价(「X 费用多少」「X 收费高吗」)— 占比 < 5% 且必须带处境\n"
#         f"   ✗ hashtag 前缀(「{keyword},推荐」「{keyword},做 X 的」)\n"
#         f"   ✗ 占位维度名(「X 适合什么类型 / 规模 / 阶段 / 客户」)\n"
#         f"5. 每条 8-35 个汉字。\n"
#         f"\n"
#         f"━━━ 数量与格式 ━━━\n"
#         f"产出 {count} 条,每行一条,纯中文,不要编号,不要项目符号,不要解释。\n"
#         f"{count} 条不是硬指标 — 写不出就停,**绝对不许灌水**(连续 3+ 条只换一个词就是灌水)。\n"
#         f"\n"
#         f"现在围绕「{keyword}」开始。"
#     )
#
#
# def _entity_forbidden_words(entity_kind: str) -> tuple[str, ...]:
#     """根据实体类型,返回扩展候选里**禁止出现**的对立实体词。
#
#     person → 不许出现 律所 / 事务所 / 法务 / 合伙人 / 医院 / 公司 / 工作室 等机构词
#     institution → 不许出现 律师 / 医生 / 顾问 / 设计师 等人词
#     generic → 不过滤
#     """
#     # 旧实现需要重新 import _PERSON_ENTITIES / _INSTITUTION_ENTITIES
#     # from app.query_suggest import _PERSON_ENTITIES, _INSTITUTION_ENTITIES
#     # if entity_kind == "person":
#     #     return _INSTITUTION_ENTITIES
#     # if entity_kind == "institution":
#     #     return _PERSON_ENTITIES
#     return ()
#
#
# async def expand_keyword_old(keyword: str, count: int, entity_kind: str,
#                              industry: str, service_geo: str, target: str,
#                              aliases: list[str]) -> list[str]:
#     msg = await _llm_call(
#         messages=[
#             {"role": "system",
#              "content": "You generate realistic Chinese user search prompts a real person would say to an AI assistant. One prompt per line, no numbering, no commentary."},
#             {"role": "user", "content": _expand_prompt(
#                 keyword, count, entity_kind, industry, service_geo, target, aliases)},
#         ],
#         temperature=0.7,
#         max_tokens=min(16000, count * 50),
#     )
#     forbidden = _entity_forbidden_words(entity_kind)
#     out: list[str] = []
#     seen: set[str] = set()
#     for line in msg.splitlines():
#         q = _clean_line(line)
#         if not (6 <= len(q) <= 100) or q in seen:
#             continue
#         # 关键词必须在 query 里(防 LLM 漂走)
#         if not (keyword in q or keyword.replace(" ", "") in q.replace(" ", "")):
#             continue
#         # 对立实体词命中即丢
#         if forbidden and any(bad in q for bad in forbidden):
#             continue
#         seen.add(q)
#         out.append(q)
#     return out


# ─── 主流程 ─────────────────────────────────────────


async def _run(text: str, n_queries: int, per_query: int,
               target: str, aliases: list[str], industry: str,
               service_geo: str, entity_override: str) -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY 没设。export 一下再跑。", file=sys.stderr)
        sys.exit(2)

    print("=" * 78)
    print(f"input text   : {text}")
    print(f"n_queries    : {n_queries}")
    print(f"per_query    : {per_query}")
    print(f"target       : {target or '(none)'}")
    print(f"aliases      : {aliases or '(none)'}")
    print(f"industry     : {industry or '(none)'}")
    print(f"service_geo  : {service_geo or '(none)'}")
    print(f"entity       : {entity_override or '(auto detect)'}")
    print("=" * 78)

    # ── Stage 1:提取整句 query + 判定实体 ───────────────
    print("\n[Stage 1] LLM 提取整句 query + 判定实体…")
    try:
        llm_entity, queries = await extract_queries(text, n_queries)
    except DeepSeekError as e:
        print(f"\nDeepSeek 失败:[{e.code}] {e.message}", file=sys.stderr)
        sys.exit(1)
    if not queries:
        print("没提取到 query,LLM 输出为空。", file=sys.stderr)
        sys.exit(1)
    # 实体决策优先级:CLI --entity > LLM 判定 > 启发式兜底
    if entity_override:
        ek_final = entity_override
        ek_source = "CLI --entity"
    elif llm_entity in ("person", "institution", "product"):
        ek_final = llm_entity
        ek_source = "LLM 判定"
    else:
        ek_final = _entity_from_text(text)
        ek_source = "启发式兜底"
    print(f"  → 实体类型:{ek_final} (来源:{ek_source})")
    print(f"  → 拿到 {len(queries)} 条 query:")
    for i, q in enumerate(queries, 1):
        print(f"     {i:2d}. {q}")

    # ── Stage 2:对每条 query 跑 paraphrase 扩展 ─────────
    print(f"\n[Stage 2] 并发 paraphrase(每 query {per_query} 条,实体锁 = {ek_final},并发上限 3)…")

    # Semaphore 限流 — 避免 6+ 个 LLM call 同时打 DeepSeek 触发 429
    sem = asyncio.Semaphore(3)

    async def _one(q: str) -> tuple[str, str, list[str]]:
        async with sem:
            try:
                paras = await expand_query(q, per_query, ek_final,
                                           industry, service_geo, target, aliases)
            except DeepSeekError as e:
                print(f"  ✗ {q} 失败:[{e.code}] {e.message}", file=sys.stderr)
                return q, ek_final, []
            return q, ek_final, paras

    results = await asyncio.gather(*[_one(q) for q in queries])

    # ── 输出 ───────────────────────────────
    print("\n──── 候选清单(按 source query 分组) ────")
    total = 0
    grouped: list[dict] = []
    for src_q, ek, paras in results:
        total += len(paras)
        print(f"\n[{src_q}] (实体: {ek}, {len(paras)} 条)")
        for i, p in enumerate(paras, 1):
            print(f"  {i:2d}. {p}")
        grouped.append({"source_query": src_q, "entity_kind": ek, "paraphrases": paras})

    print(f"\n──── 总计:{len(queries)} 条提取 query × ~{per_query} → {total} 条 paraphrase ────")

    # ── JSON 落地 ─────────────────────────
    out_dir = REPO_ROOT / "tmp"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"extract_expand_{abs(hash(text)) % 10_000_000}.json"
    out_path.write_text(
        json.dumps(
            {"input_text": text, "extracted_queries": queries,
             "entity_kind": ek_final, "groups": grouped},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJSON 落地:{out_path}")


def _entity_from_text(text: str) -> str:
    """从输入文本推断实体类型(人/机构)— 比对关键词单独探更稳。

    顺序很重要:
      1. 先看 text 末尾命中 — 末尾通常是品牌身份,信号最强
      2. 否则按 substring 检查,**机构词优先 + 长串优先**(律师事务所 > 律所 > 律师),
         避免「律师事务所」被「律师」单独 substring 误判成 person
    """
    kind = _detect_seed_entity_kind(text)
    if kind != "generic":
        return kind
    # substring 兜底 — 长机构词优先(律师事务所/律所/事务所/医院 > 律师/医生)
    INSTITUTION_ANCHORS = (
        "律师事务所", "律所", "事务所", "医院", "诊所", "公司",
        "工作室", "机构", "学校", "培训机构", "团队",
    )
    PERSON_ANCHORS = (
        "律师", "医生", "顾问", "教练", "设计师", "工程师",
        "咨询师", "培训师", "经纪人", "合伙人",
    )
    for anchor in INSTITUTION_ANCHORS:
        if anchor in text:
            return "institution"
    for anchor in PERSON_ANCHORS:
        if anchor in text:
            return "person"
    return "generic"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("text", nargs="?", default=DEFAULT_TEXT, help="输入文本")
    p.add_argument("--queries", "--keywords", dest="queries",
                   type=int, default=6,
                   help="提取多少条整句 query(旧名 --keywords 仍可用)")
    p.add_argument("--per-query", "--per-keyword", dest="per_query",
                   type=int, default=15,
                   help="每条 query paraphrase 多少条(旧名 --per-keyword 仍可用)")
    p.add_argument("--target", default="", help="被检测品牌(LLM 会绕开点名)")
    p.add_argument("--aliases", default="", help="逗号分隔的品牌别名")
    p.add_argument("--industry", default="", help="行业")
    p.add_argument("--service-geo", default="", help="服务地域")
    p.add_argument("--entity", default="",
                   choices=["", "person", "institution", "product"],
                   help="强制锁实体类型(默认从文本自动探测)")
    args = p.parse_args()

    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    asyncio.run(_run(args.text, args.queries, args.per_query,
                     args.target, aliases, args.industry, args.service_geo,
                     args.entity))


if __name__ == "__main__":
    main()
