"""LLM monitoring-plan generator (OpenAI).

Given a target (company / brand / ticker) plus optional intent, ask the model
to produce a structured search plan: aliases, target platforms, and a small
number of boolean queries the crawler can pass straight to a search engine.

This implements PRD §3.1–§3.2 — natural-language intent → structured monitoring
plan, version-able, human-editable before execution.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import openai

from llm_client import chat_create, has_openai, has_qwen

PLAN_MODEL = os.environ.get("YUQING_PLAN_MODEL", "gpt-4o-mini")
MAX_TOKENS = 2000

# 内置负面 / 风险词库:用于在通用查询里主动召回负面舆情(用户诉求:多扩负面词,
# 数据越多越好)。拆两组避免单条 query 的 OR 项过长稀释命中。抓回的旧负面内容
# 仍全量入库,但展示层按 publish_time 新鲜度窗口收口,只露最新。
RISK_LEXICON_FINANCE = [
    "暴跌", "亏损", "做空", "退市", "违约", "停牌", "债务", "爆仓",
    "财务造假", "业绩暴雷", "下调评级", "监管处罚",
]
RISK_LEXICON_OPS = [
    "欠薪", "裁员", "跑路", "维权", "诉讼", "投诉", "丑闻", "黑幕",
    "停产", "破产", "违规", "罚款", "调查", "数据泄露",
]

# Legacy fallback catalog — used by `ensure_all_platforms()` only when the
# backend pipeline does NOT pass `allowed_domains` explicitly. As of
# migration 010, the GEO backend reads `sentiment_platforms` from its own DB
# and always sends the full domain list to /run-monitor, so this constant is
# only consulted in standalone / manual-test scenarios.
#
# DO NOT edit this list to add a platform — instead INSERT into the
# `sentiment_platforms` table on the GEO backend (or rerun migration 010).
PLATFORM_CATALOG: list[tuple[str, str]] = [
    # ── 财经媒体(主力)──
    ("xueqiu",       "xueqiu.com"),
    ("eastmoney",    "guba.eastmoney.com"),
    ("caixin",       "caixin.com"),
    ("36kr",         "36kr.com"),
    ("sina_finance", "finance.sina.com.cn"),
    ("qq_finance",   "finance.qq.com"),
    ("163_finance",  "money.163.com"),
    ("ths",          "10jqka.com.cn"),
    ("wallstreetcn", "wallstreetcn.com"),
    ("yicai",        "yicai.com"),
    ("cls",          "cls.cn"),
    ("gelonghui",    "gelonghui.com"),
    # ── 财经媒体(扩展)──
    ("jrj",          "jrj.com.cn"),
    ("hexun",        "hexun.com"),
    ("jin10",        "jin10.com"),
    ("nbd",          "nbd.com.cn"),
    ("jingji21",     "21jingji.com"),
    ("stcn",         "stcn.com"),
    ("cs_com",       "cs.com.cn"),
    ("cnstock",      "cnstock.com"),
    ("p5w",          "p5w.net"),
    ("caijing",      "caijing.com.cn"),
    ("iyiou",        "iyiou.com"),
    ("futunn",       "futunn.com"),
    ("itiger",       "itiger.com"),
    ("zhitong",      "zhitongcaijing.com"),
    # ── 社交媒体 ──
    ("weibo",        "weibo.com"),
    ("weixin",       "mp.weixin.qq.com"),
    ("xiaohongshu",  "xiaohongshu.com"),
    ("zhihu",        "zhihu.com"),
    # ── 论坛社区 ──
    ("tieba",        "tieba.baidu.com"),
    ("zhidao",       "zhidao.baidu.com"),
    ("hupu",         "hupu.com"),
    ("douban",       "douban.com"),
    ("v2ex",         "v2ex.com"),
    ("guokr",        "guokr.com"),
    ("csdn",         "csdn.net"),
    ("juejin",       "juejin.cn"),
    # ── 视频平台 ──
    ("bilibili",     "bilibili.com"),
    ("douyin",       "douyin.com"),
    ("kuaishou",     "kuaishou.com"),
    ("toutiao",      "toutiao.com"),
    ("vqq",          "v.qq.com"),
    ("iqiyi",        "iqiyi.com"),
    ("ixigua",       "ixigua.com"),
    # ── 资讯门户 ──
    ("baidu_news",   "news.baidu.com"),
    ("ifeng",        "ifeng.com"),
    ("sina_main",    "sina.com.cn"),
    ("sohu",         "sohu.com"),
    ("chinanews",    "chinanews.com"),
    ("xinhuanet",    "xinhuanet.com"),
    ("people",       "people.com.cn"),
    ("huanqiu",      "huanqiu.com"),
    ("guancha",      "guancha.cn"),
    ("ce_cn",        "ce.cn"),
    ("thepaper",     "thepaper.cn"),
    ("jiemian",      "jiemian.com"),
    ("huxiu",        "huxiu.com"),
    ("tmtpost",      "tmtpost.com"),
    ("pingwest",     "pingwest.com"),
    ("ifanr",        "ifanr.com"),
    ("qbitai",       "qbitai.com"),
    ("jiqizhixin",   "jiqizhixin.com"),
    # ── 海外 ──
    ("reddit",       "reddit.com"),
    ("twitter",      "twitter.com"),
    ("seekingalpha", "seekingalpha.com"),
    ("bloomberg",    "bloomberg.com"),
    ("reuters",      "reuters.com"),
]

PLAN_SYSTEM = """你是一名舆情监测分析师。给定一个公司 / 品牌 / 股票，生成一份"监测计划"——一组可直接发给搜索引擎（DuckDuckGo / Google / Bing）的查询，用于召回该目标在公开平台上的讨论。

输出严格 JSON，结构如下：

{
  "target": "目标名称",
  "ticker": "股票代码（如适用，无则 null）",
  "aliases": ["别名 / 英文名 / 昵称 / 错别字 / 历史名"],
  "platforms": [
    {"name": "xueqiu",    "domain": "xueqiu.com",          "rationale": "金融专业讨论"},
    {"name": "eastmoney", "domain": "guba.eastmoney.com",  "rationale": "散户股吧"},
    {"name": "weibo",     "domain": "weibo.com",           "rationale": "广义社交"},
    {"name": "zhihu",     "domain": "zhihu.com",           "rationale": "深度问答"},
    {"name": "36kr",      "domain": "36kr.com",            "rationale": "科技 / 创投资讯"},
    {"name": "caixin",    "domain": "caixin.com",          "rationale": "财经深度报道"},
    {"name": "bilibili",  "domain": "bilibili.com",        "rationale": "视频 / 年轻用户讨论"},
    {"name": "toutiao",   "domain": "toutiao.com",         "rationale": "今日头条资讯"},
    {"name": "weixin",    "domain": "mp.weixin.qq.com",    "rationale": "微信公众号文章"},
    {"name": "xiaohongshu","domain": "xiaohongshu.com",    "rationale": "小红书 / 消费者口碑"},
    {"name": "kuaishou",  "domain": "kuaishou.com",        "rationale": "快手短视频"},
    {"name": "tieba",     "domain": "tieba.baidu.com",     "rationale": "百度贴吧 / 主题社区 (经 DDG 间接索引)"},
    {"name": "zhidao",    "domain": "zhidao.baidu.com",    "rationale": "百度知道 / 问答 (经 DDG 间接索引)"},
    {"name": "baidu_news","domain": "news.baidu.com",      "rationale": "百度新闻聚合 (经 DDG 间接索引)"},
    {"name": "reddit",    "domain": "reddit.com",          "rationale": "海外英文讨论"}
  ],
  "queries": [
    {
      "platform": "xueqiu",
      "query":    "site:xueqiu.com (世纪互联 OR VNET)",
      "intent":   "broad-recall: 该平台上所有提及"
    },
    {
      "platform": "xueqiu",
      "query":    "site:xueqiu.com (世纪互联 OR VNET) (失望 OR 垃圾 OR 跌 OR 管理层 OR 业绩)",
      "intent":   "negative-sentiment: 吐槽 / 情绪化 / 风险信号"
    }
  ],
  "notes": "查询设计的简短说明 (≤80 字)"
}

## 规则
- 同时覆盖中文和英文（中国公司在 reddit / X 也常被提及；海外公司在国内股吧也有讨论）
- 每个平台生成 1-3 条 query：至少 1 条 broad-recall，1 条 sentiment / risk modifier
- query 字符串必须可直接用于搜索引擎：用 `site:` + 关键词 + `OR` / 空格 (AND)
- **重要**：用 `(A OR B)` 而不是 `(A B)` —— 后者会被引擎当作 `A AND B`，过度收窄
- 平台数量 5-7 个、查询总数 6-14 条为宜（控制 DDG 压力）
- 如果用户传入 `force_all: true`：忽略上一条上限，**必须**覆盖示例 platforms 列表里的**每一个**平台，每个平台至少 1 条 broad-recall 查询（有情绪修饰词时再加 1 条 sentiment 查询）
- 如果用户在 intent 中指定了关注点（例如"做空报告 / 业绩传闻"），优先生成相关查询
- 如果用户提供了 `media` 字段（域名白名单），**只能**为这些域名生成 `site:` 查询；忽略其他平台
- 如果用户提供了 `keywords` 字段（修饰词列表），把它们作为 AND 修饰组拼到 query 末尾：`site:X (target OR alias) (kw1 OR kw2 OR …)`，至少覆盖一条该平台的查询
- 如果用户传入 `targets` 数组（同一集团下的多个实体），**每条 query 的目标分组必须把所有 targets 都 OR 进去**，再叠加别名，例如 `site:X (世纪互联 OR VNET世纪互联 OR 蓝云 OR <aliases…>)`。输出 JSON 中 `target` 字段使用首个主体（用作显示 / 主键），并新增 `targets` 字段镜像输入数组
- 严格 JSON，不要附加任何额外文字 / 代码块标记
"""


def generate_monitoring_plan(
    target: str | list[str],
    ticker: str | None = None,
    intent: str | None = None,
    media: list[str] | None = None,
    keywords: list[str] | None = None,
    force_all: bool = False,
) -> dict:
    if not (has_openai() or has_qwen()):
        sys.exit(
            "no LLM key available. Set OPENAI_API_KEY (sk-...) or QWEN_API_KEY, "
            "or use --plan-in to load a hand-written one."
        )
    if isinstance(target, str):
        targets = [t.strip() for t in target.split(",") if t.strip()] or [target]
    else:
        targets = [t.strip() for t in target if t and t.strip()]
    if not targets:
        sys.exit("generate_monitoring_plan: target list is empty")
    primary = targets[0]
    payload: dict = {
        "target": primary,
        "ticker": ticker,
        "intent": intent or "全方位舆情监测：情感、风险、传播信号",
    }
    if len(targets) > 1:
        payload["targets"] = targets
    if media:
        payload["media"] = media
    if keywords:
        payload["keywords"] = keywords
    if force_all:
        payload["force_all"] = True
    user_msg = (
        "为以下目标生成监测查询计划：\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    resp = chat_create(
        PLAN_MODEL,
        max_completion_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )
    text = resp.choices[0].message.content or "{}"
    plan = json.loads(text)
    plan.setdefault("target", primary)
    plan.setdefault("ticker", ticker)
    if len(targets) > 1:
        plan["targets"] = targets
    if media:
        plan = filter_queries_by_media(plan, media)
    if force_all:
        plan = ensure_all_platforms(plan, targets, ticker, allowed_domains=media)
    if keywords:
        plan = augment_queries_with_keywords(plan, keywords)
    plan = add_general_queries(plan, targets, keywords)
    return plan


def add_general_queries(plan: dict, targets: list[str],
                        keywords: list[str] | None = None) -> dict:
    """追加不限 site 的通用查询。

    监测计划默认都是 `site:平台 (...)` 限定查询;但有些引擎(如经 Web Unlocker
    的百度)对 site: 限定不返回结果,只对通用查询返回。这里补两条通用查询,
    让百度等也能贡献(覆盖新闻、自媒体等非平台来源)。
    """
    primary = ((targets[0] if targets else plan.get("target")) or "").strip()
    if not primary:
        return plan
    queries = plan.get("queries") or []
    existing = {q.get("query") for q in queries}

    # 用引号锁定完整目标名:避免搜索引擎按中文分词把「世纪互联」拆成「世纪」,
    # 召回词典释义 / 同名实体等噪声。配合 pipeline 的相关性闸门双保险。
    extra = [{"platform": "general", "query": f'"{primary}"',
              "intent": "通用召回:全网提及(覆盖百度/新闻/自媒体)"}]
    # 新闻向召回:偏向有时效的报道 / 财报 / 公告,压低词典 / 百科类常青页占比。
    extra.append({"platform": "general",
                  "query": f'"{primary}" (新闻 OR 财报 OR 业绩 OR 公告 OR 股价)',
                  "intent": "通用召回:新闻/财经动态"})
    # 负面 / 风险信号召回:内置词库分两组拼成 OR 查询,主动扩大负面舆情覆盖。
    extra.append({"platform": "general",
                  "query": f'"{primary}" (' + " OR ".join(RISK_LEXICON_FINANCE) + ")",
                  "intent": "通用召回:财务/市场风险信号"})
    extra.append({"platform": "general",
                  "query": f'"{primary}" (' + " OR ".join(RISK_LEXICON_OPS) + ")",
                  "intent": "通用召回:经营/声誉风险信号"})
    # 海外标的(美股 ADR / 港股等)中文源覆盖薄,有 ticker 时补一条英文新闻向查询。
    ticker = (plan.get("ticker") or "").strip()
    if ticker:
        extra.append({"platform": "general",
                      "query": f"{ticker} (news OR earnings OR stock OR revenue)",
                      "intent": "通用召回:英文新闻(海外标的)"})
    # 关键词召回:OR 分批(每批 ~12 个)。避免"每词一条查询"在词表扩到 ~70 时
    # 让 monitor 跑 70 条 × 各引擎(百度 Web Unlocker ~30s/条)而超时;OR 分批把
    # 70 词压成 ~6 条查询,配合相关性闸门过滤跑题。
    kws = [k.strip() for k in (keywords or []) if k and k.strip()]
    _BATCH = 12
    for i in range(0, len(kws), _BATCH):
        grp = kws[i:i + _BATCH]
        extra.append({"platform": "general",
                      "query": f'"{primary}" (' + " OR ".join(grp) + ")",
                      "intent": f"通用召回:话题词批{i // _BATCH + 1}"})

    for q in extra:
        if q["query"] not in existing:
            queries.append(q)
    plan["queries"] = queries
    return plan


_SITE_RE = re.compile(r"site:([^\s)]+)", re.IGNORECASE)
_MODIFIER_TAIL_RE = re.compile(r"\([^()]*\)\s*$")


def read_csv_list(path: Path | str) -> list[str]:
    """Read a txt file and parse comma- and/or newline-separated tokens."""
    raw = Path(path).read_text(encoding="utf-8")
    return [s.strip() for s in raw.replace("\n", ",").split(",") if s.strip()]


def _normalize_domain(d: str) -> str:
    return d.strip().lower().lstrip(".").removeprefix("https://").removeprefix("http://").rstrip("/")


def filter_queries_by_media(plan: dict, media: list[str]) -> dict:
    """Drop queries whose `site:` directive doesn't match any allowed domain."""
    allow = [_normalize_domain(m) for m in media if m.strip()]
    if not allow:
        return plan
    kept = []
    for q in plan.get("queries") or []:
        sites = [_normalize_domain(s) for s in _SITE_RE.findall(q.get("query", ""))]
        if not sites:
            continue
        if any(s == a or s.endswith("." + a) for s in sites for a in allow):
            kept.append(q)
    plan["queries"] = kept
    return plan


def _domain_to_known_name(domain: str) -> str:
    """Look up a known platform name by domain; fall back to the domain itself."""
    nd = _normalize_domain(domain)
    for name, dom in PLATFORM_CATALOG:
        ndom = _normalize_domain(dom)
        if nd == ndom or nd.endswith("." + ndom) or ndom.endswith("." + nd):
            return name
    return nd


def ensure_all_platforms(plan: dict, target: str | list[str],
                         ticker: str | None = None,
                         allowed_domains: list[str] | None = None) -> dict:
    """Force-cover every catalog domain (or each entry in `allowed_domains`).

    For any domain not already referenced by an existing `site:` query, append a
    synthesized broad-recall query `site:<domain> (target OR alias OR …)`. Used
    by `--force-all` to guarantee deterministic platform coverage even when the
    LLM judges some platforms irrelevant.
    """
    if allowed_domains:
        catalog = [(_domain_to_known_name(d), _normalize_domain(d))
                   for d in allowed_domains if d.strip()]
    else:
        catalog = [(name, _normalize_domain(dom)) for name, dom in PLATFORM_CATALOG]

    queries = plan.get("queries") or []
    covered: set[str] = set()
    for q in queries:
        for s in _SITE_RE.findall(q.get("query", "") or ""):
            covered.add(_normalize_domain(s))

    targets = target if isinstance(target, list) else [target]
    aliases = plan.get("aliases") or []
    terms: list[str] = []
    for t in [*targets, ticker, *aliases]:
        if t and t not in terms:
            terms.append(t)
    target_group = "(" + " OR ".join(terms) + ")" if terms else ""

    plat_list = plan.setdefault("platforms", [])
    for name, domain in catalog:
        if any(c == domain or c.endswith("." + domain) or domain.endswith("." + c)
               for c in covered):
            continue
        queries.append({
            "platform": name,
            "query": f"site:{domain} {target_group}".strip(),
            "intent": "broad-recall (force_all 补全)",
        })
        if not any(p.get("name") == name for p in plat_list):
            plat_list.append({"name": name, "domain": domain,
                              "rationale": "force_all 强制覆盖"})

    plan["queries"] = queries
    return plan


def augment_queries_with_keywords(plan: dict, keywords: list[str]) -> dict:
    """Append `(kw1 OR kw2 OR …)` to each query, replacing any existing trailing modifier group."""
    kws = [k.strip() for k in keywords if k.strip()]
    if not kws:
        return plan
    mod = "(" + " OR ".join(kws) + ")"
    for q in plan.get("queries") or []:
        query = (q.get("query") or "").strip()
        if not query:
            continue
        # If LLM already appended a modifier group at the end, replace it; else append.
        head = _MODIFIER_TAIL_RE.sub("", query).rstrip()
        # Only treat the trailing `(…)` as a modifier when there's already at least
        # one `(…)` group earlier (the target/alias group). Otherwise keep as-is.
        if head.count("(") >= 1 and head != query:
            q["query"] = f"{head} {mod}"
        else:
            q["query"] = f"{query} {mod}"
    return plan


def save_plan(plan: dict, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def load_plan(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def print_plan(plan: dict) -> None:
    targets = plan.get("targets") or []
    if targets and len(targets) > 1:
        head = f"{plan.get('target')} (+{len(targets)-1}: {', '.join(targets[1:])})"
    else:
        head = str(plan.get("target"))
    print(f"\n监测目标: {head}  |  ticker: {plan.get('ticker')}")
    aliases = plan.get("aliases") or []
    if aliases:
        print(f"别名:    {', '.join(aliases)}")
    platforms = plan.get("platforms") or []
    if platforms:
        names = ", ".join(p.get("name", "?") for p in platforms)
        print(f"平台:    {names}")
    queries = plan.get("queries") or []
    print(f"\n共 {len(queries)} 条查询：")
    for i, q in enumerate(queries, 1):
        print(f"  {i:>2}. [{q.get('platform','?'):>10}] {q.get('query','')}")
        intent = q.get("intent")
        if intent:
            print(f"        ↳ {intent}")
    notes = plan.get("notes")
    if notes:
        print(f"\n说明: {notes}")
    print()
