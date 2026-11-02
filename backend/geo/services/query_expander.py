"""4 维场景扩展 — 单 seed 并行喂 4 套 LLM 模板,产出搜索 / 问答 / 意图 / 品牌 4 类长尾.

2026-05-28 起接管 `/expand-queries` 的扩展产出.老路径只调 telemetry-service 拿 1 份,
新路径在我们这边做 LLM 调用,4 维并行,每维独立 prompt 模板.

模板根据讯灵实测反推:
  - search:  品类/产品搜索意图 — XX厂家/XX供应商/推荐XX(纯关键词)
  - qa:      问答 / 推荐 / 对比 — 哪家XX好/XX怎么选(带问句词)
  - intent:  用户意图查询 — 如何选XX/XX攻略(带意图词)
  - brand:   品牌评估 — {target}怎么样/详细介绍/客户评价(主语必须是品牌名)

ENV(复用 content_generator 的 2 路 fallback):
  DEEPSEEK_API_KEY      优先,直连 DeepSeek
  OPENROUTER_API_KEY    fallback,通过 OpenRouter 调 DeepSeek
  GEO_EXPANSION_TIMEOUT 单条 LLM 请求超时(秒),默认 90
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from geo.models.ai_telemetry import ALL_SCENES, SceneType

log = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
OPENROUTER_DEEPSEEK_MODEL = os.environ.get("OPENROUTER_DEEPSEEK_MODEL", "deepseek/deepseek-v4-flash")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT = int(os.environ.get("GEO_EXPANSION_TIMEOUT", "90"))


# ─────────── 主体类型 → 扩展词风格指令(覆盖模板里默认的制造业措辞) ───────────
# 资料里的 entity_type 决定扩展词往哪个方向走。空 / other → 不注入,模板按原样跑。
ENTITY_TYPE_HINTS: dict[str, str] = {
    "service_tool": (
        "主体类型:【服务 / 工具类】(SaaS / 软件 / 平台 / 在线服务)。"
        "把品类用「工具 / 软件 / 平台 / 系统 / 方案 / 服务」这类说法自然表达;"
        "别用「厂家 / 供应商 / 生产商 / 制造 / 批发 / OEM / 工厂」这类制造业词。"
    ),
    "manufacturer": (
        "主体类型:【生产制造商】(工厂 / 代工 / 设备 / 零部件)。"
        "贴合采购方找供应商的问法,可用「厂家 / 供应商 / 生产厂 / 设备 / 选型」这类说法。"
    ),
    "brand_owner": (
        "主体类型:【品牌方 / 零售商】(消费品 / 渠道 / 代理)。"
        "用消费者口吻:「哪个牌子好 / 什么品牌 / 正品 / 哪里买」;少用上游制造词。"
    ),
    "other": "",
}


# ─────────────────── 4 套 prompt 模板 ──────────────────

# 2026-05-28 — 画像注入策略(参考讯灵 AI蒸馏 实测):
#   search:  弱依赖 — 只用 industry / service_geo(纯品类 SEO 词)
#   qa:      弱依赖 — 只用 industry / service_geo
#   intent:  中依赖 — industry / service_geo / case_stories(案例追溯型查询)
#   brand:   强依赖 — target / aliases / industry / service_geo / case_stories
#                    / core_credentials / brand_diff_tags / core_service_overview
SCENE_PROMPTS: dict[SceneType, str] = {
    "search": """你在为「AI 搜索可见性监测」生成监测问题。这些词会拿去问 AI 搜索引擎(ChatGPT / 豆包 /
DeepSeek / 文心 等),用来看 AI 的回答里会不会推荐 / 列举某个品牌或公司 —— 用户随后优化内容,
争取让自己的品牌出现在这些回答里。所以要生成【会让 AI 给出品牌 / 公司 / 产品推荐清单】的词。

品类:「{seed}」(用它代表的【品类】来造词;若原文太长太书面,请换成更自然、口语、简短的品类说法,
不要把这串字整块照搬)
{entity_hint}
行业:{industry};地域:{service_geo}

扩展 {count} 条,**全部按「修饰词 + 品类」的推荐型短语**(下面是句式骨架,{{品类}} 用本主题的品类替换):
- 求推荐型:推荐{{品类}} / 求推荐{{品类}} / 推荐一下{{品类}} / {{品类}}推荐 / {{品类}}排名 / {{品类}}排行
- 夸赞型(每条换一个形容词,别只用「好」):靠谱的{{品类}} / 专业的{{品类}} / 有实力的{{品类}} /
  知名的{{品类}} / 口碑好的{{品类}} / 高性价比的{{品类}} / 服务好的{{品类}} / 资质齐全的{{品类}} /
  正规的{{品类}} / 比较好的{{品类}} / 诚信的{{品类}}
- 同义品类变体:把「{{品类}}」替换成贴切的同义说法(公司 / 企业 / 机构 / 平台 / 品牌 / 工具 / 软件 —— 按主体类型挑)

要求:
1. 每条 6~18 字,纯短语、不带问号;主体是品类,不是某个具体品牌名。
2. 【严禁】功能 / 价格 / 套餐 / 登录 / 注册 / 下载 / 官网 / 月费 / 年费 / API / 集成 / 试用 / 教程 / 操作指南
   这类功能点 / 导航 / 交易后缀 —— 问 AI 这些根本不会推荐品牌,属于无效词。
3. 【严禁】把品类原文当名词整块照搬再机械加后缀(反例:「推荐{seed}功能」「{seed}下载」)。
4. 不重复;若 service_geo 非空,可少量加地域(如 {service_geo}靠谱的{{品类}})。

只输出 JSON 对象,字段名 "queries",值是字符串数组,如:
{{"queries": ["推荐XX", "靠谱的XX", "口碑好的XX", "..."]}}
不要前后包 ```json``` 围栏,不要任何额外说明文字。""",

    "qa": """你在为「AI 搜索可见性监测」生成监测问题(用途同 search 场景:让 AI 回答里给出品牌 / 产品推荐,
供用户优化后争取被推荐)。本场景专出【对比 / 选型 / 求推荐】类口语问句。

品类:「{seed}」(用自然、简短的品类说法,别整块照搬原文)
{entity_hint}
行业:{industry};地域:{service_geo}

扩展 {count} 条问句(下面是句式骨架,{{品类}} 用本主题的品类替换):
- 哪家{{品类}}好 / 哪个{{品类}}靠谱 / {{品类}}怎么选 / {{品类}}哪家专业 / 选哪个{{品类}}好
- {{品类}}哪家性价比高 / 求推荐靠谱的{{品类}} / {{品类}}哪家口碑好 / {{品类}}哪家有实力

要求:
1. 每条 8~22 字,真实口语问句,带「哪个 / 哪家 / 怎么选 / 推荐 / 靠谱 / 好不好」等词。
2. 每条都要能引出品牌 / 公司推荐;不要纯关键词(归 search 场景)。
3. 【严禁】功能 / 价格 / 登录 / 下载 / 官网 / 月费 / 试用 / 教程 这类后缀;严禁品类原文整块照搬加后缀。
4. 不重复。

只输出 JSON 对象:{{"queries": ["..."]}};不要 ```json``` 围栏。""",

    "intent": """你在为「AI 搜索可见性监测」生成监测问题(目的:让 AI 的回答里推荐到品牌 / 服务商 / 解决方案,
供用户优化后争取被推荐)。本场景出【带真实使用场景的第一人称口语问句】,像用户在跟 AI 聊天
描述自己的需求并求推荐 / 求方案。

品类:「{seed}」(用自然说法,别整块照搬原文)
{entity_hint}
行业:{industry};地域:{service_geo}
真实案例 / 业务经历(当作场景背景融进问句,**至少 30% 的 query 围绕这些展开**):
{profile_cases_block}

用户定位:处于【泛需求阶段】— 刚意识到要找这类东西,随手跟 AI 说一句话求推荐;
不是已经列好条件清单的采购专家。

扩展 {count} 条。多样性来自【不同的单一切入点】,每条只取下面一个维度:
- 要解决的事(为什么需要这个品类)
- 使用场景 / 地点 / 人群
- 一个在意点(怕不靠谱 / 想要省钱的 / 要有真实案例的…)
- 上面列的真实案例场景

要求:
1. 每条 10~25 字,第一人称口语,像真实用户随手打出来的一句话。
2. 【严禁】一句话堆叠多重条件(身份+场景+问题+限制+目标);每条最多嵌 1 个具体场景或 1 个约束,其余留白。
3. 开头句式至少 5 种(想… / 要… / 有没有… / 求推荐… / 找一个… / 谁知道…),严禁超过 20% 的 query 用同一句式开头。
4. 【严禁】机械枚举行业(在X行业 / 在Y领域 + 同一句式);只有当某行业确实是「{seed}」的典型客户时才可出现,且行业开头的 query 不超过 15%。
5. 场景必须是「{seed}」的真实使用方式;想象不出真实的人会这么问的,不要输出。
6. 句中或结尾要有"求推荐 / 帮我推荐 / 用什么好"的意味,这样 AI 才会给出品牌 / 服务商。
7. 案例型问句必须用上面列的真实案例,不要凭空编造;案例为空就不出案例型。
8. 【严禁】功能 / 价格 / 登录 / 下载 / 月费 这类后缀;不重复。

只输出 JSON 对象:{{"queries": ["..."]}};不要 ```json``` 围栏。""",

    "brand": """你是品牌评估词扩展专家。
针对品牌名「{target}」(seed 是「{seed}」,作为业务/品类上下文)扩展 {count} 个**品牌评估**长尾问句。
{entity_hint}
品牌全称:{target}
品牌别名(可用):{aliases}
行业:{industry};地域:{service_geo}
品牌业务概述:{core_service_overview}
品牌差异化标签(直接引用 1-2 条做 query):{brand_diff_tags_block}
品牌核心资质 / 背书(可作为评估问句的依据):{core_credentials_block}
品牌真实案例(可作为业务线 / 历史成绩带入):{profile_cases_block}

扩展模式参考:
- {target}怎么样 / {target}详细介绍 / {target}基本信息
- {target}公司概况 / {target}客户评价如何 / {target}性价比怎么样
- {target}实力如何 / {target}靠不靠谱 / {target}口碑
- {service_geo}{target}(若 service_geo 非空,加地域前缀)
- **业务线 / 案例型**:{target}做过{{案例名}}吗 / {target}在{{业务领域}}方面有什么经验
- **资质型**:{target}有{{资质}}吗 / {target}的{{差异化标签}}怎么样

要求:
1. 每条 30~50 字,主语必须是品牌名({target} 或别名),不是品类词
2. 涵盖正反两面(评价 / 口碑 / 性价比 / 客户 / 实力 / 资质)
3. **至少 1/3 的 query 必须用上面列的真实案例名 / 资质名 / 差异化标签**,不要凭空编造
4. 不要重复

只输出 JSON 对象:{{"queries": ["..."]}};不要 ```json``` 围栏。""",
}


def _format_list_block(items: list[str] | None, *, max_items: int = 10,
                        per_item_max: int = 200) -> str:
    """把列表渲染成 prompt 里的多行 bullet,空列表 → '(无)'."""
    items = [str(x or "").strip() for x in (items or []) if str(x or "").strip()]
    items = items[:max_items]
    if not items:
        return "(无 — 用户未在画像里填写,本次不要凭空编造)"
    return "\n".join(f"  - {s[:per_item_max]}" for s in items)


def render_prompt(
    scene: SceneType,
    *,
    seed: str,
    count: int,
    target: str = "",
    aliases: list[str] | None = None,
    industry: str = "",
    service_geo: str = "",
    entity_type: str = "",
    profile_cases: list[str] | None = None,
    core_credentials: list[str] | None = None,
    brand_diff_tags: list[str] | None = None,
    core_service_overview: str = "",
) -> str:
    """渲染 scene 对应的 prompt(直接当 user 输入).

    2026-05-28 — 按画像依赖度差异化注入:
      - search / qa: 只用 seed + industry + service_geo
      - intent:      额外注入 profile_cases(案例追溯)
      - brand:       注入全部画像字段(target/aliases/cases/credentials/tags/overview)
    """
    tpl = SCENE_PROMPTS.get(scene) or SCENE_PROMPTS["search"]
    # 通用字段
    kw: dict[str, str] = {
        "seed": seed,
        "count": str(int(count)),
        "target": (target or seed),
        "aliases": "、".join((aliases or [])[:5]) or "(无)",
        "industry": industry or "(未指定)",
        "service_geo": service_geo or "",
        # 主体类型指令 — 空 / other / 未知都退化成空串(模板按原样跑)
        "entity_hint": ENTITY_TYPE_HINTS.get((entity_type or "").strip(), ""),
    }
    # 按场景注入额外字段
    if scene == "intent":
        kw["profile_cases_block"] = _format_list_block(profile_cases)
    elif scene == "brand":
        kw["profile_cases_block"] = _format_list_block(profile_cases)
        kw["core_credentials_block"] = _format_list_block(core_credentials)
        kw["brand_diff_tags_block"] = (
            "、".join([t for t in (brand_diff_tags or []) if (t or "").strip()][:10])
            or "(无)"
        )
        kw["core_service_overview"] = (core_service_overview or "").strip()[:500] or "(无)"
    return tpl.format(**kw)


# ─────────────────── LLM provider 选择(复用 content_generator 同款) ──────────────────


def _resolve_provider() -> tuple[str | None, str, str]:
    """挑 LLM provider + 拿 api key.返回 (provider | None, model_id, api_key)."""
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if ds_key:
        return "deepseek", DEEPSEEK_MODEL, ds_key
    if or_key:
        return "openrouter", OPENROUTER_DEEPSEEK_MODEL, or_key
    return None, DEEPSEEK_MODEL, ""


# ─────────────────── 单 scene 调用 ──────────────────


def _parse_json_loose(text: str) -> dict[str, Any]:
    """把 LLM 输出宽松解析为 dict.允许前后包 ```json``` 围栏 / 前后多余文字."""
    s = (text or "").strip()
    # strip code fences
    if s.startswith("```"):
        s = s.lstrip("`")
        # 去掉首行 'json'
        if "\n" in s:
            first, rest = s.split("\n", 1)
            if first.strip().lower() in ("", "json"):
                s = rest
        if "```" in s:
            s = s.split("```", 1)[0]
    s = s.strip()
    # 尝试 1:整体解析
    try:
        out = json.loads(s)
        if isinstance(out, dict):
            return out
    except Exception:  # noqa: BLE001
        pass
    # 尝试 2:抠出 {...}
    lo = s.find("{")
    hi = s.rfind("}")
    if 0 <= lo < hi:
        try:
            out = json.loads(s[lo:hi + 1])
            if isinstance(out, dict):
                return out
        except Exception:  # noqa: BLE001
            pass
    return {}


async def expand_one_scene(
    *,
    scene: SceneType,
    seed: str,
    count: int,
    target: str = "",
    aliases: list[str] | None = None,
    industry: str = "",
    service_geo: str = "",
    entity_type: str = "",
    # 2026-05-28 — 画像注入(intent / brand 场景用,其他 scene 忽略)
    profile_cases: list[str] | None = None,
    core_credentials: list[str] | None = None,
    brand_diff_tags: list[str] | None = None,
    core_service_overview: str = "",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """对单个 scene 调一次 LLM,返回 {"queries": [...], "model": "...", "error": "..."}.

    失败不抛 — 把 error 写进返回字典,留给上层 fan-out 决定怎么展示.
    """
    provider, model_id, api_key = _resolve_provider()
    if not provider:
        return {"queries": [], "error": "DEEPSEEK_API_KEY / OPENROUTER_API_KEY 都未配置"}

    prompt = render_prompt(
        scene,
        seed=seed, count=count, target=target,
        aliases=aliases, industry=industry, service_geo=service_geo,
        entity_type=entity_type,
        profile_cases=profile_cases,
        core_credentials=core_credentials,
        brand_diff_tags=brand_diff_tags,
        core_service_overview=core_service_overview,
    )

    if provider == "deepseek":
        url = f"{DEEPSEEK_BASE_URL}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        model = model_id
    else:  # openrouter
        url = OPENROUTER_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://www.vigilath.com",
            "X-Title": "GEO Query Expander",
        }
        model = model_id

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.6,
    }

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        r = await client.post(url, headers=headers, json=body)
        if r.status_code != 200:
            return {"queries": [], "model": model_id,
                    "error": f"LLM HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json()
        content = (
            data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
        )
        parsed = _parse_json_loose(content)
        raw_q = parsed.get("queries")
        if not isinstance(raw_q, list):
            return {"queries": [], "model": model_id,
                    "error": "LLM did not return queries array"}
        # 清洗:去空 / 去重 / 截长
        seen: set[str] = set()
        queries: list[str] = []
        for x in raw_q:
            s = str(x or "").strip()
            if not s or s in seen:
                continue
            s = s[:60]  # safety cap
            seen.add(s)
            queries.append(s)
        return {"queries": queries, "model": model_id}
    except httpx.HTTPError as e:
        return {"queries": [], "model": model_id, "error": f"HTTP error: {e}"}
    except Exception as e:  # noqa: BLE001
        log.warning("expand_one_scene crash scene=%s seed=%s: %s", scene, seed, e)
        return {"queries": [], "model": model_id, "error": str(e)[:300]}
    finally:
        if owns_client:
            await client.aclose()


# ─────────────────── 启发式分类(给历史 query 打 scene 标签) ──────────────────

# 顺序敏感:**意图必须先于问答命中**,避免「怎么用」被归 qa(怎么 = 问答?其实是意图).
# 关键词覆盖尽量穷举常见中文搜索行为:产品 SEO query / Q&A / how-to 教程 / 品牌评估.
_INTENT_MARKERS: tuple[str, ...] = (
    # how-to 显式词
    "如何", "怎么用", "怎么做", "怎么选", "怎么挑", "怎么入门", "怎么找",
    "怎么获取", "怎么操作", "怎么学", "怎么实现",
    # 攻略类
    "攻略", "教程", "指南", "操作步骤", "使用方法", "什么时候用",
    "用法", "玩法", "做法",
    # 选择 / 上手 / 流程类
    "挑选", "选购", "选型", "入门", "入手", "上手", "实操",
    "学会", "自学", "新手", "小白", "速成",
    # 步骤 / 流程
    "步骤", "流程", "操作",
)
_QA_MARKERS: tuple[str, ...] = (
    # 推荐 / 对比 / 选择类
    "哪家", "哪个", "哪种", "哪款", "哪些", "选哪",
    "推荐", "排行", "排名", "TOP", "top",
    "对比", "比较", "vs", "VS", "vS", "Vs",
    "区别", "差异", "异同", "不同点",
    # 评价 / 口碑 / 优劣
    "怎么样", "怎样",
    "好不好", "好用吗", "靠谱吗", "靠不靠谱", "值不值", "值得吗",
    "可以信任", "可信", "可靠吗", "评价", "评测", "评估", "测评",
    "优缺点", "优劣", "利弊", "好处", "缺点", "优势", "劣势",
    # 定义类 / 谁字类问题
    "是什么", "是啥", "啥是", "啥意思", "什么意思",
    "是谁", "找谁", "属于谁", "谁是", "谁来", "谁会", "谁能",
    # 性价比 / 价格问句
    "性价比怎么", "性价比好", "性价比高", "划算吗",
    # 句尾问句词(放最后,优先级最低)
    # 注意:同时覆盖 ASCII 半角和 Unicode 全角问号,避免中文 query 句尾 "？" 被漏
    "?", "？", "吗", "呢",
)


def classify_query(
    text: str,
    *,
    target: str = "",
    aliases: list[str] | None = None,
) -> SceneType:
    """启发式把一条 query 归到 4 维场景之一(给历史 query 打标用).

    优先级(从高到低):
      1. 文本含 target / alias 字面 → brand
      2. 含意图词(如何 / 攻略 / 教程 / 怎么选 / 怎么用 ...) → intent
      3. 含问答词(哪家 / 怎么样 / 对比 / 是什么 / 评价 / 吗 ...) → qa
      4. 其余(纯品类 / 关键词)→ search

    这个分类只看字面,不调 LLM —— 跑得快、确定性强,适合一次性 backfill 大批量 query.
    对个别歧义 case(怎么用既像 intent 也像 qa)按优先级一刀切,接受少量误分;
    用户可以重跑(改 target / aliases 后)或手动改单条.
    """
    s = (text or "").strip()
    if not s:
        return DEFAULT_SCENE

    # 1. brand:文本含目标品牌名 / 别名(只在 target/alias 长度 ≥ 2 才匹配,
    #    避免「a」「b」这种短 alias 命中所有 query)
    brand_terms: list[str] = []
    if target and len(target.strip()) >= 2:
        brand_terms.append(target.strip())
    for a in aliases or []:
        a = (a or "").strip()
        if a and len(a) >= 2:
            brand_terms.append(a)
    for term in brand_terms:
        if term and term in s:
            return "brand"

    # 2. intent
    for marker in _INTENT_MARKERS:
        if marker in s:
            return "intent"

    # 3. qa
    for marker in _QA_MARKERS:
        if marker in s:
            return "qa"

    # 4. 默认 search
    return "search"


__all__ = [
    "ALL_SCENES", "SceneType", "SCENE_PROMPTS",
    "render_prompt", "expand_one_scene", "DEFAULT_TIMEOUT",
    "classify_query",
]
