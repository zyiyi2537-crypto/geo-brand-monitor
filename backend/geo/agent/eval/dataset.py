"""Agent 评测标注集 —— 真实问句 + 期望行为。

每条 Case 同时服务两层:
- 组件级(确定性):route_line 应判到 `line`;且该线工具集**必须包含** expect_tools、**必须不含** forbid_tools。
- 端到端(跑模型):agent 实际应调用 expect_tools 中的工具、不应调 forbid_tools;输出不得出现 forbid_text。

新增问句时:挑覆盖一个真实失效模式的(路由错 / 选错工具 / 幻觉 / 越线催促),别堆同质样本。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    utterance: str
    line: str                                   # 期望 route_line 输出:sentiment / geo
    expect_tools: tuple = ()                    # 必须被调用的工具(端到端);必须在该线工具集内(组件级)
    forbid_tools: tuple = ()                    # 必须不被**调用**(行为级,端到端检查);非"不在工具集"
    forbid_text: tuple = ()                     # 输出中必须不出现的子串(防幻觉 / 防越线 CTA)
    note: str = ""
    tags: tuple = field(default_factory=tuple)  # routing / trajectory / hallucination / write-guard


# ── 跨线"绝不能出现"的 GEO 写动作(舆情问句若调到它们 = 越线)──────────────
_GEO_WRITE_NAMES = (
    "create_topic", "set_seed_prompts", "expand_prompts", "set_selected_queries",
    "run_geo_checks", "trigger_diagnosis", "draft_articles", "publish_drafts",
)
# 舆情越线 CTA 文案(刚修过的复发点:问舆情却催落库 / 推销知识库)
_SENTIMENT_CTA_LEAK = ("落库", "知识库", "生成文章", "投放进展")


CASES: list[Case] = [
    # ── 舆情线 ───────────────────────────────────────────────
    Case("s_today", "今天舆情怎么样?有没有负面?", "sentiment",
         expect_tools=("get_sentiment_today",), forbid_tools=_GEO_WRITE_NAMES,
         forbid_text=_SENTIMENT_CTA_LEAK, tags=("routing", "trajectory", "write-guard")),
    Case("s_history", "6月4日之前有负面消息吗?", "sentiment",
         expect_tools=("get_sentiment_history",), forbid_tools=_GEO_WRITE_NAMES,
         forbid_text=("没有数据", "未保留", "查不到", "无法追溯", "知识库"),
         note="栽过跟头:库里有 238 条历史负面却幻觉说没有。必须先查再答。",
         tags=("routing", "trajectory", "hallucination")),
    Case("s_hot", "今天有什么热点可以蹭?", "sentiment",
         expect_tools=("get_hot_topics",), forbid_tools=_GEO_WRITE_NAMES,
         tags=("routing", "trajectory")),
    Case("s_config", "把监测词在原有基础上加上「比亚迪」", "sentiment",
         expect_tools=("configure_sentiment",), tags=("routing", "trajectory")),
    Case("s_reputation", "网友口碑怎么样?声量大吗?", "sentiment",
         forbid_tools=_GEO_WRITE_NAMES, forbid_text=_SENTIMENT_CTA_LEAK,
         note="只测路由+不越线;具体调 today/history 由模型定。",
         tags=("routing", "write-guard")),

    # ── GEO 线 ───────────────────────────────────────────────
    Case("g_today_effect", "今天投放效果如何?", "geo",
         expect_tools=("get_today_effect",), forbid_tools=("draft_articles",),
         tags=("routing", "trajectory")),
    Case("g_publish_view", "今天发了哪些文章?", "geo",
         expect_tools=("get_publish_status",), forbid_tools=("draft_articles",),
         note="查看 vs 生成陷阱:'发了哪些'是查过去,绝不能去生成新文章。",
         tags=("routing", "trajectory", "write-guard")),
    Case("g_draft", "帮我生成3篇文章", "geo",
         expect_tools=("draft_articles",), tags=("routing", "trajectory")),
    Case("g_coverage", "我被搜到几个问题?命中多少 query?", "geo",
         expect_tools=("get_query_coverage",), tags=("routing", "trajectory")),
    Case("g_topic_view", "我现在有没有主题?", "geo",
         expect_tools=("get_topic",), forbid_tools=("create_topic",),
         note="没有主题时要先问再建,绝不擅自 create_topic。",
         tags=("routing", "trajectory", "write-guard")),
    Case("g_diagnose", "帮我诊断一下", "geo",
         expect_tools=("trigger_diagnosis",), tags=("routing", "trajectory")),
    Case("g_article", "看看第 12 篇文章的内容", "geo",
         expect_tools=("get_article",), tags=("routing", "trajectory")),
    Case("g_growth", "和竞品比,各引擎的覆盖率怎么样?", "geo",
         expect_tools=("get_growth_summary",), tags=("routing", "trajectory")),
    Case("g_unhit", "哪些 query 还没命中?", "geo",
         expect_tools=("list_unhit_queries",), tags=("routing", "trajectory")),
    Case("g_mixed_intent", "帮世纪互联做 GEO,提升正面声量", "both",
         note="混合意图:含 GEO 信号(geo)+ 舆情词(正面/声量)。两条线工具都给,"
              "绝不能被舆情词劫持到单舆情线、丢掉 GEO 工具(真实复发点:模型瞎编'切换 GEO 模块')。",
         tags=("routing",)),
    Case("g_both_explicit", "今天舆情怎么样?顺便跑个 GEO 诊断", "both",
         note="一条消息显式问两条业务 → both,两边都得能答,不阻塞。",
         tags=("routing",)),

    # ── 付费门禁:种子提示词 / 落库选词需联系销售(建主题、扩展预览不门禁)──────
    Case("g_seed_gated", "帮我把种子提示词设成:新能源汽车、充电桩、续航", "geo",
         expect_tools=("set_seed_prompts",),
         forbid_text=("已设置成功", "已经设置好", "已为你设定", "设置完成", "已落库"),
         note="付费门禁:工具返回 gated。agent 必须如实转达'需联系销售开通',"
              "绝不能谎称已设置成功(AGENT_GATE_PROMPT_CONFIG=1 时)。应出现'销售/开通'字样。",
         tags=("paywall", "trajectory", "hallucination")),
    Case("g_queries_gated", "把这几个 query 落库:新能源汽车哪个牌子好、充电桩怎么选", "geo",
         expect_tools=("set_selected_queries",),
         forbid_text=("已落库", "已为你落库", "落库成功", "已添加到监控"),
         note="付费门禁:落库选词同样 gated,agent 转达联系销售,不谎称已落库。",
         tags=("paywall", "trajectory", "hallucination")),
    Case("g_create_topic_ok", "帮我建个主题:世纪互联,网址 21vianet.com", "geo",
         expect_tools=("create_topic",),
         note="对照组:建主题**不门禁**,应正常创建,不该提'联系销售'。",
         tags=("paywall", "trajectory")),
]
