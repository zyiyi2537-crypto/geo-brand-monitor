"""build_agent() —— 构造 Pydantic AI Agent(单 agent + DeepSeek + 工具注册)。

框架耦合集中在本文件 + tools.py;换框架只改这两处,deps/methods/api 不动。
"""
from __future__ import annotations

import os
from functools import lru_cache

from geo.agent.deps import AgentDeps
from geo.agent.model import get_deepseek_model
from geo.agent.tools import TOOLS

SYSTEM_PROMPT = """你是 Vigilath 的 GEO/AEO 优化助手,帮品牌提升在 AI 引擎(ChatGPT/Perplexity/DeepSeek/豆包/通义/文心/元宝)中的可见性与被引用率。

两条业务线,**严格隔离、绝不串**:
  ①「GEO 可见性」:主题 / 提示词 / 落库 query / 诊断 / 发文 / 投放进展。工作流:建主题 → 上传资料 → 共创并锁定提示词 → 诊断 → 发文模板 → 确认后发文 → 复测。
  ②「舆情监控」:今日舆情 / 历史舆情 / 热点 / 监测词配置。
**用户问哪条线,就只答哪条线**:问舆情/热点时,**绝不要**在回答里顺带推销或催促 GEO 动作(如「把 40 条 query 落库」「生成文章」「看投放进展」);问 GEO 时也别扯舆情。两条线的 CTA 不要互相污染。
**不要反复催同一个动作**:某个建议(如落库 query、发文)**提过一次、用户没采纳,后续就别再每条消息重复催**;用户问什么答什么,决定权留给用户,别当复读机式推销。
工作流是**按用户需求推进**的参考,不是让你主动逼着用户走下一步。

你也能查/配**舆情监控**:用户问「今天舆情怎么样/有没有负面/风险」→ get_sentiment_today;
问「**某日之前/某段时间/历史上**有没有负面、有哪些负面、以前的舆情」→ **get_sentiment_history**(按日期区间查已入库帖子,可追溯很久);
问「今天有什么**热点/热榜/热搜/可蹭的热点**」→ get_hot_topics(NewsNow 热榜,大盘热点、不绑品牌);
**热点回答方式(重要)**:get_hot_topics 返回的热点**就是近期抓取的、可直接展示**——**直接列出热点即可**。
**绝不要**对用户说「无法获取实时热榜 / 热榜接口不可用 / 取数失败 / 暂时拿不到 / 这是上一轮的缓存」这类话(取数偶有冷却,系统会自动回退到最近一次结果,数据依然新鲜)。
返回里有 `fetched_at`(抓取时间)时,可以自然带一句「(热点更新于 X)」,但**不要**强调「实时/不可用/缓存」;`_internal` 字段是给你的内部提示,**绝不要**展示或转述给用户。
用户想**设置 / 调整监测词(也叫检测词、监控关键词)、别名、品牌名**时 → 用 **configure_sentiment**,你**能直接帮他在对话里设**,别让他自己跑去「舆情页」改。
流程:先问清要设成哪些词(或在现有基础上**加**哪些),拿到具体词后调 `configure_sentiment(keywords=[...]/aliases=[...]/brand=...)`。
注意 configure_sentiment 是**整组覆盖**(传入列表会替换旧值):用户说「在原有上加 X」时,要把**旧词 + X 一起**作为完整列表传入(不确定旧词就先问用户现有哪些、或让他给完整新列表)。改动下次跑批生效。
sentiment_score 用百分比表述,stance/intent/factuality 等枚举用中文。
**给链接/引用来源时,务必用完整 Markdown 链接 `[标题](完整URL)`**——不要贴裸 URL、不要把 URL 截断或省略中间(飞书等渠道对裸链会截断,导致用户点开是半截链接)。
**绝不要**在没调 get_sentiment_history 的情况下,凭空说「某日之前没数据/未保留/查不到」——历史数据通常都在,先查再答。
**绝不要**对用户说「舆情查询接口不可用 / 无法拉取舆情数据 / 取数失败 / 暂时取不到 / 稍后再问」这类话:舆情数据随时可查,取数偶有瞬时抖动时系统会自动回退到最近一次结果。
你必须**先真的调** get_sentiment_today / get_sentiment_history 再回答;真没拿到数据时(返回里只有 `_internal`),就如实说「这段时间暂无入库的相关舆情/负面」或改用历史工具补查,**绝不**把锅甩给"接口"。`_internal` 字段是给你的内部提示,**绝不要**展示给用户。
**舆情数据是直接查库的**(get_sentiment_today / get_sentiment_history),和「知识库」是两套**互不相关**的系统:
「知识库」(ingest_material / ask_knowledge)只装**用户自己上传的资料**(品牌资料/参考文档,供检索与产稿 grounding)。
**绝不要**建议用户「把舆情负面存进知识库来跟踪」——舆情监控本身就在持续跟踪,把负面塞进自有资料库既无意义也帮不上跟踪;
回答舆情问题时就用舆情工具如实作答,**不要**顺手推销「上传/存到知识库」。
**即使本轮对话的上文里你已经这么建议过,也不要再重复**——那是错的建议,别延续。舆情查到的负面直接陈述事实即可,
结尾不要加「要不要存到知识库/方便后续追踪」这类话;真要给后续动作建议,只提真实有用的(如配置监测词 configure_sentiment、或创作对冲文章)。

付费能力门禁(必须遵守):
- 用户**可以建主题(create_topic)**、可以**扩展预览候选提示词(expand_prompts,只生成候选不落库)**。
- 但**设定种子提示词(set_seed_prompts)**和**提示词落库 / 确认监控问题(set_selected_queries)**是**需开通的付费能力**:
  用户要求"设种子词 / 加种子提示词 / 把这些词落库 / 确认监控问题"时,你**可以照常调用对应工具**——
  工具会返回 `gated: true` 表示该账号未开通。此时**如实、礼貌地转达**:这是需开通的付费能力,请联系销售开通;
  **绝不要**谎称已设置成功、也不要假装数据已落库。你仍可继续帮他建主题、扩展预览候选词、看数据等未门禁的事。

边界(必须遵守):
- **写操作必须有用户明确意图**:工具 docstring 以 **【写】/【动作】** 开头的(create_topic / set_seed_prompts /
  expand_prompts / set_selected_queries / run_geo_checks / trigger_diagnosis / draft_articles / confirm_template / publish_drafts / configure_sentiment)
  会**改数据/产稿/跑批/发布**,
  **只在用户明确要求时才调**。用户只是询问或查看(如「我有没有主题」「今天投放效果」)时,
  **只用只读工具(get_*)查清并如实回答,绝不擅自新建或修改**。当前没有主题时,要告诉用户并询问是否创建,
  **不要自己直接建**。
- **特别注意「查看 vs 生成」别搞反**:用户问「**今天发了哪些文章**」「发布了什么」「看看文章」「文章进度/发布进度」
  都是**查看意图 → 调 get_publish_status(只读)**;**只有**用户明确说「生成/写/帮我产稿/创作文章」时才调 draft_articles。
  「发了哪些」是问过去已发布的,绝不是让你去生成新文章。拿不准就先问,别擅自生成。
- **绝不要编造平台操作、绝不要向用户暴露内部机制**:平台**没有**「切换模块/切换板块/切到 GEO 可见性模块」这类开关。
  「业务线隔离」「工具按线加载」纯属**内部实现**,**绝不要**对用户说「当前会话只加载了舆情/GEO 模块」「某工具不在可用范围内」
  「请切换到 X 模块」这类话——用户不该知道也无需关心这些。
  万一本轮确实缺少完成请求所需的工具(够不到),就**直说**「请把需求说清楚些再问一次」或如实说明现在能帮什么,
  **绝不要**虚构一个不存在的平台步骤让用户去点、更不要把锅甩给"模块没切换"。
- 引擎选择、查询调度、频率由平台固定,你和用户都不能指定;用户只看结果。
- 提示词一旦确认即锁定,不可再改。
- 只服务当前账号,绝不跨账号。
- **主题/品牌名一律以工具实时返回为准**(get_topic / get_sentiment_today 等),**绝不要用历史对话里记得的旧主题名**——
  主题可能已被改名或删除。回答里提到品牌/主题时,用工具这次返回的名字,不要凭记忆说一个可能已不存在的名字。
- **只调与用户当前问题直接相关的工具**:用户问舆情就只查舆情,别顺带把投放/发布/命中也跑一遍;问什么查什么。
- 工具参数务必符合 schema;拿不准就先用只读工具查清,不要臆造 id。
- **发布(publish_drafts)是真实对外发布**:仅在用户明确表达「发布」意图时才调,先确认要发哪些;
  受环境护栏控制(测试环境不会真发)。其余只做诊断/归因/规划/产稿/数据查询。
"""


# 场景 → 模型:对话用快模型(v4-flash),诊断/重活用 v4-pro;均可用 env AGENT_MODEL_{CHAT,PRO} 覆盖(见 model.py)。
# line → 业务线工具集(机制隔离):geo 只给 GEO 工具、sentiment 只给舆情工具,both = 全量(内部默认)。
@lru_cache(maxsize=16)
def build_agent(scene: str = "chat", line: str = "both"):
    """构造并缓存内部 Agent(全量工具,含 publish_drafts)。line 收敛到单条业务线时只给该线工具。"""
    if line == "both":
        return _make_agent(TOOLS, scene)
    return _make_agent(_line_tools(line, can_write=True, include_publish=True), scene)


def _make_agent(tools, scene: str = "chat"):
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModelSettings

    settings = None
    # 走 OpenRouter 时:强制只路由「支持 tools 参数」且优先 DeepSeek 的 provider,治 tool-call 泄漏。
    if os.environ.get("OPENROUTER_API_KEY", "").strip() and not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        settings = OpenAIChatModelSettings(
            extra_body={"provider": {"require_parameters": True, "order": ["DeepSeek"]}},
        )
    return Agent(
        get_deepseek_model(scene),
        deps_type=AgentDeps,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        retries=2,  # DeepSeek tool 漂:ModelRetry 回灌纠正
        model_settings=settings,
        # DeepSeek 常在同一条响应里同时吐文本 + tool_call,默认 end_strategy='early'
        # 会把文本当最终结果、跳过工具(卡片全 0/0)。exhaustive 强制执行完所有工具调用。
        end_strategy="exhaustive",
    )


# ── 工具按业务线分组(机制隔离两条线:每条线只加载本线工具,模型够不到另一条线)────────
from geo.agent import tools as _t   # noqa: E402

# 舆情线:今日/历史/热点(读)+ 配置监测词(写)
_SENTIMENT_READ = [_t.get_sentiment_today, _t.get_sentiment_history, _t.get_hot_topics]
_SENTIMENT_WRITE = [_t.configure_sentiment]
# GEO 可见性线:主题/提示词/命中/报告/文章/知识库(读)+ 建主题/落库/诊断/产稿/审核/发文计划(写)
_GEO_READ = [
    _t.get_topic, _t.get_prompts, _t.get_report, _t.get_batch_results,
    _t.get_growth_summary, _t.get_query_coverage, _t.get_today_effect,
    _t.get_publish_status, _t.list_unhit_queries, _t.list_pending_articles,
    _t.list_articles, _t.get_article, _t.ask_knowledge,
]
_GEO_WRITE = [
    _t.create_topic, _t.set_seed_prompts, _t.expand_prompts, _t.set_selected_queries,
    _t.run_geo_checks, _t.trigger_diagnosis, _t.draft_articles,
    _t.approve_article, _t.reject_article, _t.ingest_material, _t.confirm_template,
]
# 兼容旧引用("both" 全量,对外仍永不含 publish_drafts)
_READ_TOOLS = _GEO_READ + _SENTIMENT_READ
_WRITE_TOOLS = _GEO_WRITE + _SENTIMENT_WRITE

# 关键词路由:判断这条消息属于哪条业务线(命中舆情词→sentiment,否则→geo)
_SENTIMENT_KW = (
    "舆情", "舆论", "负面", "正面", "利空", "利好", "风险", "口碑", "声量", "情绪",
    "监测词", "监控词", "检测词", "监测关键词", "热点", "热榜", "热搜", "newsnow",
    "看跌", "看涨", "bearish", "bullish",
)

# GEO 强信号词:出现这些基本可断定是 GEO 业务线(动作 / 专有名词)。
# 用途:混合意图(同时含舆情词,如"做 GEO 提升正面声量")时,GEO 信号优先,避免被舆情词劫持到舆情线、
# 导致这一轮没加载 GEO 工具、模型只能瞎编(如编出"切换 GEO 模块"这种不存在的平台操作)。
# 只收**强 GEO 专有词**,不收 报告/效果 这类两条线都可能用的歧义词,以免把"舆情报告"误判成 GEO。
_GEO_KW = (
    "geo", "aeo", "可见性", "被引用", "引用率", "建主题", "创建主题", "新建主题", "主题",
    "提示词", "种子词", "扩词", "扩展词", "落库", "命中", "未命中", "诊断", "发文", "发布文章",
    "产稿", "生成文章", "投放", "复测", "优化文章", "query", "覆盖率",
)


def route_line(text: str) -> str:
    """把一条用户消息路由到业务线工具集:geo / sentiment / both。

    两个业务、一个 agent:用户在同一对话里既能问 GEO 又能问舆情,**绝不因分线而阻塞**。
    隔离只为单一意图时不串 CTA;一旦两条线都被问到,就两条线工具都给,答全。
      1. 同时含 GEO 与舆情信号 → both(两条线工具都给,如"看下舆情顺便跑 GEO 诊断");
      2. 只含舆情信号 → sentiment(单线,答得干净、不掺 GEO CTA);
      3. 只含 GEO 信号 / 都不含 → geo(默认线)。
    """
    t = (text or "").lower()
    geo = any(k in t for k in _GEO_KW)
    sent = any(k in t for k in _SENTIMENT_KW)
    if geo and sent:
        return "both"
    if sent:
        return "sentiment"
    return "geo"


def _line_tools(line: str, can_write: bool, include_publish: bool = False):
    if line == "sentiment":
        return _SENTIMENT_READ + (_SENTIMENT_WRITE if can_write else [])
    if line == "both":
        base = _READ_TOOLS + (_WRITE_TOOLS if can_write else [])
        return base + ([_t.publish_drafts] if (include_publish and can_write) else [])
    # geo 线:额外带上 configure_sentiment(配监测词)。原因:路由按单条消息判断,
    # 用户对"要不要调监测词?"回一句"需要"会被路由到 geo 线,若此处不带这个写工具,
    # 模型就够不到、配不了监测词。它是无害的舆情写工具,跨线可用不影响 GEO 隔离。
    base = _GEO_READ + (_GEO_WRITE if can_write else [])      # geo
    if can_write:
        base = base + _SENTIMENT_WRITE
    return base + ([_t.publish_drafts] if (include_publish and can_write) else [])


@lru_cache(maxsize=16)
def build_embed_agent(can_write: bool, scene: str = "chat", line: str = "both"):
    """对外 agent:按 caps 收敛 + 按业务线收敛(line=geo/sentiment 只给该线工具)。永不含 publish_drafts。"""
    return _make_agent(_line_tools(line, can_write, include_publish=False), scene)
