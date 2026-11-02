"""根据 seed 主题生成 query 候选 — 用户在 AI 遥测建话题前不再手填.

设计要点(2026-05-13 v3):
- 候选来源混合两路:
    1. DeepSeek LLM 合成(主力,提供"用户口语化问题"语料)
    2. Baidu sugrec + Bing osjson autocomplete(补真实搜索行为快照,中文场景下
       google / DDG 返回 0 不接)
  两路并行(asyncio.gather),autocomplete 不增加 wall-clock 延迟。
- 4 维 composite 评分(0-100):seed_relevance / retrieval_potential /
  commercial_intent / uniqueness。LLM 输出长度/熵都满分,human_like/entropy
  砍掉避免无信息维度稀释。
- target 非空时:LLM 走 GEO-aware prompt + _drop_target_mentions 兜底过滤,
  并对 autocomplete 结果一并应用过滤(autocomplete 高频出 target 字面)。
- 单 provider 失败不致命:autocomplete 整路失败只让 LLM 候选直出。

ENV:
- DEEPSEEK_API_KEY    必填
- DEEPSEEK_BASE_URL   可选,默认 https://api.deepseek.com
- DEEPSEEK_MODEL      可选,默认 deepseek-chat
"""
from __future__ import annotations

import asyncio
import math
import os
import re
from collections import Counter
from typing import Optional

import httpx


DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

_SUGGEST_TIMEOUT = 6.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_SYSTEM_MSG = (
    "You generate realistic user search prompts for evaluating how AI assistants "
    "respond about a given topic. Output one prompt per line, no numbering, no bullets, no commentary. "
    "Always write every prompt in the SAME LANGUAGE as the seed query."
)

_BULLET_RE = re.compile(r"^[•\-\*\d\.\)\]\s>]+")
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]*|[一-鿿]")
_CJK_RE = re.compile(r"[一-鿿]")


# ─── autocomplete 扇出模板(CJK / EN 分路)──────────────────

_CJK_SUFFIXES = [
    "费用", "价格", "收费", "推荐", "排名", "对比",
    "评价", "案例", "流程", "注意事项", "怎么选", "哪个好",
]
_CJK_QUESTION_PREFIXES = [
    "什么是", "如何", "怎么", "怎样", "为什么",
    "哪里有", "哪个", "哪种", "能否", "是否",
]
_CJK_COMMERCIAL_PREFIXES = [
    "最好的", "最佳", "推荐的", "知名的", "排名靠前的",
]

_EN_QUESTION_PREFIXES = [
    "what is", "how does", "how to", "why is", "when to use",
    "is", "are", "can", "should", "which",
]
_EN_COMMERCIAL_PREFIXES = [
    "best", "top", "cheap", "free", "alternatives to",
    "vs", "comparison", "review of",
]


# ─── 评分用词表 ────────────────────────────────────

_COMMERCIAL_TERMS_EN = {
    "best", "top", "cheap", "cheapest", "free", "alternative", "alternatives",
    "vs", "versus", "compared", "comparison", "review", "reviews", "rating",
    "price", "pricing", "cost", "buy", "purchase", "discount", "recommend",
    "recommendation", "recommended", "leader", "leading",
}
_CJK_COMMERCIAL_MARKERS = (
    "最好", "最佳", "推荐", "排名", "排行",
    "对比", "比较", "评价", "评测", "测评",
    "价格", "费用", "收费", "价位",
    "哪个好", "怎么选", "排行榜", "性价比",
    # GEO / AEO 决策型 query 高频信号
    "哪家", "擅长", "适合", "靠谱", "资深", "头部", "知名", "求推荐",
)

_QUESTION_WORDS_EN = {
    "what", "how", "why", "when", "where", "who", "which",
    "is", "are", "can", "should", "does", "do", "will", "would",
}
_CJK_QUESTION_MARKERS = (
    "什么", "怎么", "怎样", "如何", "为什么",
    "哪里", "哪个", "哪种", "哪些", "能否", "是否",
    "吗", "呢", "?", "?",
)

_VERBS_EN = {
    "do", "does", "is", "are", "use", "uses", "using", "build", "make", "made",
    "compare", "choose", "pick", "find", "get", "learn", "track", "monitor",
    "measure", "deploy", "configure", "set", "integrate", "optimize",
}

_STOP_WORDS_EN = {
    "a", "an", "the", "of", "for", "to", "in", "on", "with",
    "and", "or", "but", "my", "your", "our", "their", "this", "that",
}
_CJK_STOP_CHARS = set("的了是在和或吗呢啊呀这那个就也都还有为以及但")


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


# ─── LLM prompt 构造(GEO-aware / generic 两套)────────────


def _user_msg_zh_geo_dirty(seed: str, count: int, dirty_markers: list[str],
                           avoid_clause: str) -> str:
    """脏 seed 专用 prompt — seed 本身已是 query,不能再叠意图后缀 / 前缀。

    只允许:
      - 内部语序调整(把「不要 X」挪到前面 / 把意图词移到不同位置)
      - 同义虚词替换(推荐↔求推荐;不要↔非/不;有没有↔哪里有)
    禁止:
      - 拼新意图后缀(X 推荐 → X 推荐推荐 / X 推荐哪家好)
      - 改变 seed 实质内容
    """
    markers_str = "、".join(f"「{m}」" for m in dirty_markers[:5])
    return (
        f"任务:把下面这条**已是完整 query 的种子**改写成 {count} 条同义 query。\n"
        f"\n"
        f"━━━ 种子(已是完整 query)━━━\n"
        f"「{seed}」\n"
        f"\n"
        f"━━━ ⚠️ 关键约束(种子里已含意图词 {markers_str})━━━\n"
        f"这条种子**本身已经是一句完整 query**,不是名词短语 — 它已经表达了「求推荐 / 找 / 哪家好」这层意思。\n"
        f"你**不能**再拼新的意图后缀 / 前缀(否则会变成「X推荐推荐」「X哪家好哪家好」这种病句)。\n"
        f"\n"
        f"━━━ 唯一允许的改写方式 ━━━\n"
        f"1. **内部语序调整** — 把 seed 里的「业务 / 地点 / 意图 / 约束」名词块前后挪。\n"
        f"   例:「清洁机器人推荐,不要家用」可改成:\n"
        f"     - 「推荐清洁机器人,不要家用」(意图前置)\n"
        f"     - 「不要家用的清洁机器人推荐」(约束前置)\n"
        f"     - 「非家用的清洁机器人推荐」(同义词替换 + 约束前置)\n"
        f"\n"
        f"2. **同义虚词替换**(不增加新意图,只换说法):\n"
        f"   • 推荐 ↔ 求推荐 ↔ 想找 ↔ 有没有(任选其一替换,不要叠加)\n"
        f"   • 不要 ↔ 非 ↔ 不要 …… 之外的 ↔ 排除\n"
        f"   • 哪家好 ↔ 哪家靠谱 ↔ 哪家专业(如 seed 已有「哪家好」,可换说法,但不能再加一个「哪家好」)\n"
        f"\n"
        f"3. **加产品 / 实体量词**(如果 seed 没有,可加):\n"
        f"   例:「清洁机器人推荐」可加成「清洁机器人**哪款**推荐」/「清洁机器人**哪个**推荐」\n"
        f"   注意:这不是加意图词,是把已有的意图说得更具体。\n"
        f"\n"
        f"━━━ 严格禁止 ━━━\n"
        f"✗ **再加意图后缀**(seed 已有「推荐」就不能再加「推荐 / 哪家好 / 求推荐 / 怎么找 / 有推荐吗」)\n"
        f"✗ **再加意图前缀**(seed 已有意图就不能再加「适合 / 推荐 / 求推荐 / 想找 / 帮忙推荐」)\n"
        f"✗ **替换 seed 里的业务词 / 地点词 / 实体词**(逐字保留)\n"
        f"✗ **砍掉 seed 里的字段**(包括约束句如「不要家用」「,2024年款」)\n"
        f"✗ **加 seed 里没有的实质内容**(新城市 / 新公司 / 新场景)\n"
        f"\n"
        f"━━━ 示例(种子 = 「清洁机器人推荐,不要家用」,合格改写应该长这样)━━━\n"
        f"  • 推荐清洁机器人,不要家用\n"
        f"  • 不要家用的清洁机器人推荐\n"
        f"  • 非家用的清洁机器人推荐\n"
        f"  • 清洁机器人哪款推荐,不要家用\n"
        f"  • 清洁机器人哪个推荐,不要家用\n"
        f"  • 求推荐清洁机器人,不要家用\n"
        f"  • 想找清洁机器人,不要家用\n"
        f"  • 非家用清洁机器人,有推荐吗\n"
        f"  • 清洁机器人,不要家用的有推荐吗\n"
        f"  • 哪款清洁机器人推荐,不家用\n"
        f"\n"
        f"━━━ 数量与格式 ━━━\n"
        f"产出 {count} 条改写,每行一条,纯中文,不要编号,不要项目符号,不要解释。\n"
        f"{count} 条**不是硬指标** — 写不出就停,**绝对不许灌水或叠加意图词**。\n"
        f"{avoid_clause}"
        f"\n"
        f"现在围绕「{seed}」开始改写,记住:**只调顺序 + 同义虚词替换,不许新增意图词**。"
    )


def _user_msg_zh_geo(seed: str, count: int, target: str, aliases: list[str], industry: str,
                     service_geo: str = "", profile_cases: list[str] | None = None) -> str:
    """中文 GEO-aware prompt — 2026-05-26 改版:整句 prompt 同义改写,不再做主题词扩展。

    设计意图(用户口述):种子提示词应该是「跨境并购的北京律师」这种**完整 query**,
    扩展出的应是「适合跨境并购的北京律师推荐」这种**同义改写** —— 同一个用户意图换说法,
    而不是分支到不同案件 / 不同城市 / 不同子业务。

    service_geo / profile_cases 仍保留参数(向后兼容 caller),但不再写进 prompt:
    地点信息以 seed 本身为准,案例追溯型已废弃。industry / target / aliases 仍用于
    避免点名 + 上下文锚定。
    """
    _ = service_geo, profile_cases, industry  # 保留 caller 兼容
    alias_part = "、".join(f"「{a}」" for a in aliases) if aliases else ""
    avoid_clause = ""
    if target.strip():
        avoid_clause = (
            f"\n━━━ 禁名规则 ━━━\n"
            f"不要出现「{target}」"
            + (f" 或别名 {alias_part}" if alias_part else "")
            + "(测的是 AI 主动推荐,不是点名查)。\n"
        )
    # 脏 seed 走完全不同的 prompt 路径 — seed 本身已是 query,不能再叠意图词
    is_dirty, dirty_markers = _seed_is_dirty(seed)
    if is_dirty:
        return _user_msg_zh_geo_dirty(seed, count, dirty_markers, avoid_clause)
    # 从种子末尾推断实体词 → 注入针对该实体的禁词清单
    entity_blacklist = _seed_entity_blacklist(seed)
    entity_lock_clause = ""
    if entity_blacklist:
        # 找出实际命中的 entity_word(可能是 2-5 字),用于自然措辞
        cleaned = "".join(c for c in seed if not c.isspace())
        entity_word = ""
        for ent in sorted(_ENTITY_BLACKLIST.keys(), key=len, reverse=True):
            if cleaned.endswith(ent):
                entity_word = ent
                break
        # 实体类型决定 narrative 措辞 + 量词黑名单
        kind = _detect_seed_entity_kind(seed)
        descriptor = {
            "person":      "一个**具体的人**",
            "institution": "一个**机构 / 团队 / 公司**",
            "product":     "一个**具体的产品 / 物品 / 工具**",
        }.get(kind, "**这个实体**")
        good_quantifiers = {
            "person":      "哪位 / 一位 / 哪个 / 几位",
            "institution": "哪家 / 一家 / 几家 / 哪个",
            "product":     "哪款 / 一款 / 几款 / 哪个",
        }.get(kind, "")
        bad_quantifiers = _QUANTIFIER_BLACKLIST.get(kind, ())
        bad_list = "、".join(f"「{w}」" for w in entity_blacklist)
        quantifier_clause = ""
        if bad_quantifiers and good_quantifiers:
            bad_q_str = "、".join(f"「{w}」" for w in bad_quantifiers)
            quantifier_clause = (
                f"   量词必须跟实体匹配 — 「{entity_word}」是「{descriptor.strip('*')}」,"
                f"只能用 {good_quantifiers};**绝对不许**出现 {bad_q_str} 这些跟实体不匹配的量词。\n"
            )
        entity_lock_clause = (
            f"\n━━━ 实体词硬锁(再强调一次)━━━\n"
            f"种子里的身份是「{entity_word}」(指代{descriptor}),\n"
            f"   ① **对立实体词**:你产出的每一条 query 里**绝对不许出现** {bad_list} 这些词,"
            f"哪怕只在 query 中间出现一次(如「在 XX{entity_blacklist[0]}的{entity_word}」)整条作废。\n"
            f"   ② **身份末尾**:query 末尾的身份词只能是「{entity_word}」,逐字一致。\n"
            f"{quantifier_clause}"
        )
    # 脏 seed 已在函数开头早退到 _user_msg_zh_geo_dirty,这里走干净 seed 路径
    return (
        f"任务:把下面这条**种子提示词**改写成 {count} 条**结构上各异、语义相近**的搜索 query。\n"
        f"\n"
        f"━━━ 种子 ━━━\n"
        f"「{seed}」\n"
        f"\n"
        f"━━━ 设计意图(重要!读懂再写)━━━\n"
        f"我要的是 {count} 条**句式骨架不同**的同义改写,**不是 {count} 条换 1 个虚词的近义复制**。\n"
        f"如果你写出:`{seed}推荐` / `适合{seed}` / `求推荐{seed}` / `推荐一位{seed}` ……\n"
        f"这种**只有前后缀差异**的输出,我就只要 3-5 条,**其余作废**。\n"
        f"每条改写都要在**句式结构**上跟其它条**显著不同**(不只是换 1 个意图虚词)。\n"
        f"\n"
        f"━━━ 5 大允许的变化维度(每条改写至少动 2 个)━━━\n"
        f"\n"
        f"**(A) 调内部顺序** — 种子里「业务 / 地点 / 身份」名词块前后挪\n"
        f"  • 「业务 的 地点 身份」→「地点 业务 身份」/「业务 身份 在 地点」/「地点 + 身份 + 做 业务 的」\n"
        f"\n"
        f"**(B) 句式骨架变化** — 同义内容用完全不同句式表达\n"
        f"  • 陈述请求:「{seed}推荐」\n"
        f"  • 直接寻问:「{seed}哪位比较靠谱」\n"
        f"  • 处境式:「想找{seed},有谁推荐」\n"
        f"  • 询问式:「{seed} — 谁比较好」\n"
        f"  • 双句式:「{seed},朋友圈有靠谱推荐吗」(克制,占比 < 20%)\n"
        f"  • 短词式:「{seed}」(原样,占比 < 5%)\n"
        f"  • 强调式:「{seed},找哪位最专业」\n"
        f"  • 反问式:「{seed}哪位是真的靠谱」\n"
        f"\n"
        f"**(C) 加修饰词(在种子末尾的身份前面加 adj)**\n"
        f"  • 资深的 / 专业的 / 头部的 / 顶尖的 / 优秀的 / 经验丰富的 / 比较好的 / 擅长这块的 / 业内有名的 / "
        f"老牌的 / 实力强的 / 圈内公认的\n"
        f"  • 例:「资深{seed}」/「头部{seed}推荐」/「业内有名的{seed}」\n"
        f"\n"
        f"**(D) 意图前/后缀**(白名单,每条最多前后各 1 个,不要堆叠)\n"
        f"  • 前缀:推荐 / 求推荐 / 适合 / 推荐一位 / 推荐一个 / 想找 / 求 / 找 / 帮忙推荐 / 有没有 / 哪里有 / 求帮忙找\n"
        f"  • 后缀:推荐 / 求推荐 / 有推荐吗 / 哪位好 / 哪个靠谱 / 哪位比较专业 / 哪位最好 / 谁靠谱 / 谁比较好 / 怎么找 / 怎么选\n"
        f"\n"
        f"**(E) 询问者口吻 / 语气**(混搭使用,不要一条到底)\n"
        f"  • 正式咨询:「请问 X 哪位比较靠谱」\n"
        f"  • 朋友求助:「有没有靠谱的 X 推荐一下」\n"
        f"  • 简短直接:「X 找哪位好」\n"
        f"  • 内行口吻:「X — 业内头部都有谁」\n"
        f"\n"
        f"━━━ 严格禁止(违反一条整条作废)━━━\n"
        f"✗ **不许替换种子里任何字**。逐字保留:\n"
        f"  • 业务词原样:种子是「跨境并购」就写「跨境并购」,**不许**换「跨境收购 / 海外并购 / 跨境业务 / 并购 / 跨境投融资」等任何变体。\n"
        f"  • 身份词原样:种子是「律师」就写「律师」,**不许**换「律所 / 合伙人 / 法务 / 顾问 / 团队 / 专家」等。\n"
        f"  • 地点原样:种子是「北京」就写「北京」,**不许**换「京 / 帝都 / 在京 / 北京市 / 中关村 / 朝阳 / 海淀」等。\n"
        f"✗ **不许砍掉种子里任何字段**。如种子有「企业跨境/TMT投资、海外并购」,改写里**这一整串**都得在,包括「/」和「、」和每个字符。\n"
        f"✗ **不许加种子里没有的实质内容**(具体公司名 / 具体案件 / 具体子领域 / 其它城市 / 其它国家 / 具体年份)。\n"
        f"✗ **不许改成认知 / 对比 / 元 / SEO 句式**(「什么是 X」「X 流程」「X 费用是多少」「A vs B」「X 有哪些类型」)。\n"
        f"✗ **不许灌水**:连续 3 条只换 1 个虚词(推荐/求推荐 互换,的/吗 互换)= 灌水征兆,立刻停笔。\n"
        f"\n"
        f"━━━ 多样性自检(写完每条问自己)━━━\n"
        f"• 这条和上一条相比,**句式骨架**是否真的不同?(不只是换了个意图前后缀)\n"
        f"• 这条用的「变化维度」(A-E)中,至少动了 2 个?\n"
        f"• 5 条以内出现 2 条结构相同 → 第 2 条作废。\n"
        f"\n"
        f"━━━ 用「{seed}」直接套出来的好例子(结构骨架要这么变)━━━\n"
        f"  • {seed}推荐(直接陈述)\n"
        f"  • 资深{seed}有哪些(加修饰 + 询问)\n"
        f"  • 想找{seed},有谁比较靠谱(处境 + 反问)\n"
        f"  • 头部{seed}都是谁(修饰 + 直接寻问)\n"
        f"  • {seed} — 业内最专业的是哪位(强调式 + 内行口吻)\n"
        f"  • 求推荐一位{seed},朋友圈有合适的吗(双句 + 朋友求助)\n"
        f"  • 请问{seed}哪位比较有经验(正式口吻 + 修饰)\n"
        f"  • {seed},找谁最靠谱(反问 + 强调)\n"
        f"  • 经验丰富的{seed},怎么找(修饰 + 询问方式)\n"
        f"  • {seed}哪位口碑最好(询问 + 强调)\n"
        f"  • {seed}怎么找\n"
        f"  • 帮忙推荐一位{seed}\n"
        f"\n"
        f"━━━ 数量与格式 ━━━\n"
        f"产出 {count} 条改写,每行一条,纯中文,不要编号,不要项目符号,不要解释。\n"
        f"{count} 条**不是硬指标** — 写不出 {count} 条不重复的就停下,**绝对不许灌水**。\n"
        f"{avoid_clause}"
        f"{entity_lock_clause}"
        f"\n"
        f"现在围绕种子「{seed}」开始改写,记住:**只调顺序 + 加白名单意图词,一字不许换**。"
    )


def _user_msg_en_geo(seed: str, count: int, target: str, aliases: list[str], industry: str,
                     service_geo: str = "") -> str:
    alias_part = ", ".join(f'"{a}"' for a in aliases) if aliases else ""
    avoid = f'"{target}"' + (f" or its aliases {alias_part}" if alias_part else "")
    ind = f" (industry: {industry})" if industry else ""
    geo_lock_en = ""
    if service_geo.strip():
        sg = service_geo.strip()
        geo_lock_en = (
            f"\n━━━ ⚠️ LOCATION HARD LOCK (overrides any later 'feel free to vary location' guidance) ━━━\n"
            f"User has fixed the service region to **\"{sg}\"**. Every query's location dimension MUST be one of:\n"
            f"  - \"{sg}\" itself (or its well-known sub-districts)\n"
            f"  - generic non-specific phrases like \"nationwide\" / \"cross-region\" / \"remote\"\n"
            f"  - queries with NO location at all (identity / situation driven)\n"
            f"**DO NOT** mention any other specific city / country / overseas hub. "
            f"Discard any query that does. Mix: ~40-55% mention \"{sg}\" by name, ~45-60% no specific location.\n"
        )
    return (
        f"You are helping the brand \"{target}\"{ind} run a GEO / AEO audit. "
        f"What we measure: **when real users ask an AI assistant (ChatGPT / DeepSeek / "
        f"Perplexity / Claude / Gemini) about this kind of topic, will the AI naturally "
        f"recommend us?** Generate {count} candidate queries around the topic: '{seed}'.\n"
        f"{geo_lock_en}"
        f"\n"
        f"━━━ Hard rules ━━━\n"
        f"1. **Never mention {avoid}** — naming us in the prompt is cheating; throw those out.\n"
        f"2. Every line is something a real user would actually say to an AI — conversational, "
        f"casual is fine, **but not SEO keyword stuffing**.\n"
        f"3. 5-20 words each. **Short and human** beats long and listy.\n"
        f"4. English only. No numbering, no bullets, no commentary. One prompt per line.\n"
        f"\n"
        f"━━━ Mix (critical) ━━━\n"
        f"For GEO / AEO, **\"recommend / find / who's the best\" decision-stage queries are the "
        f"strongest signal**. Produce:\n"
        f"  - **Decision / recommendation: 60-70%** (the bulk — vary modifiers, not intent)\n"
        f"  - Comparison: 15-20% (\"A vs B\", \"differences between\", \"which is better\")\n"
        f"  - Awareness: 15-20% (\"what is\", \"how does X work\", \"what to look for\")\n"
        f"**Don't split evenly** — heavily over-index on decision queries.\n"
        f"\n"
        f"━━━ Decision-query templates (produce many variants of each) ━━━\n"
        f"- Recommend: \"recommend a X\", \"any good X for Y\", \"best X for Y\", \"who does X well\"\n"
        f"- Find: \"find a X in [city]\", \"X near [city]\", \"[city] X that handles [scenario]\"\n"
        f"- Fit: \"X for [scenario]\", \"which X works for [user type]\", \"X specialized in [scenario]\"\n"
        f"- Rank: \"top X in [city/scenario]\", \"leading X for [scenario]\", \"X firms ranked\"\n"
        f"\n"
        f"━━━ Modifier dimensions (stack them to get real variation) ━━━\n"
        f"- **Location**: major US/UK/EU/APAC cities, financial hubs (NYC, London, Singapore, "
        f"Hong Kong, Tokyo), or \"cross-border / global / remote\". If the topic is about a "
        f"person / service / firm, **35-50% of queries should carry a location modifier**.\n"
        f"- **Scenario / sub-vertical**: infer 5-10 real sub-scenarios from '{seed}'.\n"
        f"- **User type**: startup / public company / SMB / individual / enterprise — mix in.\n"
        f"- **Quality words (optional)**: experienced, reputable, top-tier, specialized.\n"
        f"\n"
        f"━━━ Examples (assume seed = 'cross-border M&A lawyer' — for format only, do not copy) ━━━\n"
        f"- recommend a cross-border M&A lawyer in New York\n"
        f"- best cross-border M&A attorneys in Hong Kong\n"
        f"- looking for an M&A lawyer for our overseas acquisition\n"
        f"- who handles cross-border M&A in Singapore well\n"
        f"- top firms for SPAC cross-border deals\n"
        f"- M&A lawyer recommendations for a US listed company expanding to Asia\n"
        f"\n"
        f"Now produce {count} queries around '{seed}', one per line."
    )


def _user_msg_zh_generic(seed: str, count: int) -> str:
    """中文 generic prompt(无 target 上下文)— 跟 zh_geo 同样要求「结构多样」。"""
    return (
        f"任务:把下面这条**种子提示词**改写成 {count} 条**结构上各异、语义相近**的搜索 query。\n"
        f"\n"
        f"━━━ 种子 ━━━\n"
        f"「{seed}」\n"
        f"\n"
        f"━━━ 设计意图 ━━━\n"
        f"我要 {count} 条**句式骨架不同**的同义改写,**不要换 1 个虚词的近义克隆**。\n"
        f"\n"
        f"━━━ 5 大变化维度(每条至少动 2 个)━━━\n"
        f"(A) **调内部顺序**:业务 / 地点 / 身份名词块前后挪\n"
        f"(B) **句式骨架变化**:陈述请求 / 直接寻问 / 处境式 / 询问式 / 双句式 / 反问式 / 强调式\n"
        f"(C) **加修饰词**(身份前面加 adj):资深 / 专业 / 头部 / 顶尖 / 优秀 / 经验丰富 / 业内有名 / 老牌 / 实力强\n"
        f"(D) **意图前/后缀**:推荐 / 求推荐 / 想找 / 哪位好 / 哪个靠谱 / 怎么找 / 谁靠谱 等(每条最多前后各 1 个)\n"
        f"(E) **口吻**:正式咨询 / 朋友求助 / 简短直接 / 内行口吻 / 强调式 — 混搭\n"
        f"\n"
        f"━━━ 严格禁止 ━━━\n"
        f"✗ **不许替换种子里任何字** — 业务 / 身份 / 地点词逐字保留(含「/」「、」)\n"
        f"✗ **不许砍掉种子里任何字段**\n"
        f"✗ **不许加种子里没有的实质内容**(公司名 / 案件 / 子领域 / 其它城市 / 国家)\n"
        f"✗ **不许改成认知 / 对比 / 元 / SEO 句式**\n"
        f"✗ **不许灌水** — 连续 3 条只换 1 个虚词立刻停笔\n"
        f"\n"
        f"━━━ 用「{seed}」直接套出来的好例子(结构骨架要这么变)━━━\n"
        f"  • {seed}推荐\n"
        f"  • 资深{seed}有哪些\n"
        f"  • 想找{seed},有谁比较靠谱\n"
        f"  • 头部{seed}都是谁\n"
        f"  • {seed} — 业内最专业的是哪位\n"
        f"  • 求推荐一位{seed}\n"
        f"  • 请问{seed}哪位比较有经验\n"
        f"  • 经验丰富的{seed},怎么找\n"
        f"\n"
        f"━━━ 数量与格式 ━━━\n"
        f"产出 {count} 条,每行一条,纯中文,不要编号 / 项目符号 / 解释。\n"
        f"{count} 条**不是硬指标** — 写不出结构上真有差异的就停下,**绝对不许灌水**。\n"
        f"\n"
        f"现在围绕「{seed}」开始改写:**每条要在句式结构上真有差异,不只是换虚词**。"
    )


def _user_msg_en_generic(seed: str, count: int) -> str:
    return (
        f"Generate {count} semantically related but distinct prompts a real user "
        f"might send to an AI assistant when they care about: '{seed}'. "
        f"Mix question forms (what/how/why/best/vs/alternatives), intent types "
        f"(informational, comparison, transactional), and phrasing styles. "
        f"Keep each prompt 4-15 words. Write every prompt in English. "
        f"Do not number. One prompt per line."
    )


def _user_msg(seed: str, count: int, target: str, aliases: list[str], industry: str,
              service_geo: str = "", profile_cases: list[str] | None = None) -> str:
    cjk = _has_cjk(seed) or _has_cjk(target)
    if target.strip():
        return _user_msg_zh_geo(seed, count, target, aliases, industry, service_geo, profile_cases) if cjk \
            else _user_msg_en_geo(seed, count, target, aliases, industry, service_geo)
    return _user_msg_zh_generic(seed, count) if cjk else _user_msg_en_generic(seed, count)


def _parse_lines(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = _BULLET_RE.sub("", line).strip().strip('"\'')
        if 4 <= len(line) <= 200 and line not in seen:
            seen.add(line)
            out.append(line)
    return out


# ─── DeepSeek 调用 ─────────────────────────────────


class DeepSeekError(Exception):
    """DeepSeek 调用失败 — caller 翻译成 4xx/5xx."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


async def _fetch_llm(seed: str, raw_count: int, target: str, aliases: list[str],
                    industry: str, service_geo: str = "",
                    profile_cases: list[str] | None = None,
                    max_attempts: int = 3) -> list[str]:
    """调 DeepSeek 拿候选;失败抛 DeepSeekError。

    2026-05-26 — 加 retry:
      - HTTP 429 / 5xx / 网络瞬态错误 → 退避重试(指数 0.5s, 1.5s, 3.5s)
      - HTTP 4xx 非 429(配置 / auth 错)→ 立刻抛,不重试
    max_tokens 上限砍到 4000(原 16000 过大,导致 LLM 生成慢,反而容易超时)。
    每条 query 大概 30-50 token,4000 tokens 够 80-130 条候选,远超实际 raw_count。
    """
    import asyncio
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise DeepSeekError("no_key", "DEEPSEEK_API_KEY 未配置")

    # max_tokens:每条 query 30-50 token,留 buffer 拿 60 token/条
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_MSG},
            {"role": "user", "content": _user_msg(seed, raw_count, target, aliases, industry, service_geo, profile_cases)},
        ],
        "temperature": 0.7,
        "max_tokens": min(4000, max(800, raw_count * 60)),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"

    last_err: DeepSeekError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                r = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            last_err = DeepSeekError("network", f"attempt {attempt}: {e}")
        else:
            if r.status_code == 200:
                try:
                    data = r.json()
                    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                except (ValueError, IndexError, KeyError) as e:
                    raise DeepSeekError("parse", str(e)) from e
                return _parse_lines(text)
            # 4xx(429 除外)= 配置 / payload 错,不要重试
            if 400 <= r.status_code < 500 and r.status_code != 429:
                raise DeepSeekError(f"http_{r.status_code}", r.text[:200])
            last_err = DeepSeekError(f"http_{r.status_code}", f"attempt {attempt}: {r.text[:200]}")
        # 退避后重试
        if attempt < max_attempts:
            await asyncio.sleep(0.5 * (2 ** (attempt - 1)))  # 0.5s, 1.0s, 2.0s, ...

    assert last_err is not None  # noqa: S101
    raise last_err


# ─── 簇主题摘要(LLM 二次打标)─────────────────────


_CLUSTER_LABEL_RE = re.compile(r"^[簇\s]*(\d+)[\s]*[:：]\s*(.+?)\s*$")


async def _label_clusters_llm(by_cluster: dict[int, list[dict]],
                              seed: str = "") -> dict[int, str]:
    """让 DeepSeek 给每个簇生成 2-8 字主题摘要。一次 call 处理所有簇。

    输入:{cluster_id: [{text, score, ...}, ...]} (每簇候选列表,score 顺序无关)
    输出:{cluster_id: 主题词} (失败返回空 dict,caller 应回退到 max-score label)
    """
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key or not by_cluster:
        return {}

    blocks: list[str] = []
    for cid in sorted(by_cluster.keys()):
        members = by_cluster[cid]
        top = sorted(members, key=lambda c: c.get("score", 0), reverse=True)[:6]
        sample = "\n".join(f"  - {m['text']}" for m in top)
        blocks.append(f"簇 {cid}(共 {len(members)} 条,以下为代表样本):\n{sample}")

    seed_hint = f"\n这些 query 都围绕主题「{seed}」展开。" if seed else ""
    user_msg = (
        f"下面是按语义聚成的 {len(by_cluster)} 个簇。请给每个簇生成一个"
        f"**2-8 个汉字的主题摘要**,概括该簇 query 的共性。"
        f"摘要可以是「业务方向」「用户身份」「地点偏好」「问询类型」等。"
        f"{seed_hint}\n\n"
        f"{chr(10).join(blocks)}\n\n"
        f"输出格式严格遵守(不要解释、不要标点、不要项目符号):\n"
        f"簇 0: 主题词\n"
        f"簇 1: 主题词\n"
        f"……\n\n"
        f"主题词要让人一眼看到簇内容,避免「类」「型」「相关」「问题」这类冗余后缀。"
    )

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system",
             "content": "You generate concise 2-8 character Chinese topic labels for clustered queries. Output only labels in '簇 N: 主题词' format, one per line."},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            return {}
        data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except (httpx.HTTPError, ValueError, IndexError, KeyError):
        return {}

    out: dict[int, str] = {}
    for line in text.splitlines():
        m = _CLUSTER_LABEL_RE.match(line.strip())
        if not m:
            continue
        cid = int(m.group(1))
        label = m.group(2).strip().strip("「」\"'")
        if 2 <= len(label) <= 30:
            out[cid] = label
    return out


# ─── Autocomplete(Baidu / Bing)────────────────────


async def _suggest_baidu(client: httpx.AsyncClient, query: str) -> list[str]:
    try:
        r = await client.get(
            "https://www.baidu.com/sugrec",
            params={"prod": "pc", "wd": query},
            timeout=_SUGGEST_TIMEOUT,
            headers={"User-Agent": _UA},
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, dict) and isinstance(data.get("g"), list):
            return [item.get("q", "") for item in data["g"]
                    if isinstance(item, dict) and item.get("q")]
    except (httpx.HTTPError, ValueError):
        pass
    return []


async def _suggest_bing(client: httpx.AsyncClient, query: str) -> list[str]:
    params = {"query": query}
    if _has_cjk(query):
        params["mkt"] = "zh-CN"
    try:
        r = await client.get(
            "https://api.bing.com/osjson.aspx",
            params=params,
            timeout=_SUGGEST_TIMEOUT,
            headers={"User-Agent": _UA},
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [s for s in data[1] if isinstance(s, str)]
    except (httpx.HTTPError, ValueError):
        pass
    return []


def _fan_out_queries(seed: str) -> list[str]:
    """seed → 一批扩展 query 喂 autocomplete。CJK / EN 分两条模板路径。"""
    queries = [seed]
    if _has_cjk(seed):
        for suffix in _CJK_SUFFIXES:
            queries.append(f"{seed}{suffix}")
        for prefix in _CJK_QUESTION_PREFIXES:
            queries.append(f"{prefix}{seed}")
        for prefix in _CJK_COMMERCIAL_PREFIXES:
            queries.append(f"{prefix}{seed}")
    else:
        for prefix in _EN_QUESTION_PREFIXES:
            queries.append(f"{prefix} {seed}")
        for prefix in _EN_COMMERCIAL_PREFIXES:
            queries.append(f"{prefix} {seed}")
    return queries


_SUGGEST_CONCURRENCY = 8  # 同时打 Baidu/Bing 的并发上限,避免触发反爬


async def _fetch_suggest(seed: str) -> list[tuple[str, str]]:
    """并行打 Baidu + Bing autocomplete。返回 [(text, "suggest:baidu"), ...]。

    用 Semaphore 限流 8 并发,避免高频请求被 rate limit。
    任何 provider/请求失败都吞掉(autocomplete 是补充源,不致命)。
    """
    fan = _fan_out_queries(seed)
    sem = asyncio.Semaphore(_SUGGEST_CONCURRENCY)

    async def _gated(source: str, coro_fn, client, q):
        async with sem:
            return source, await coro_fn(client, q)

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    async with httpx.AsyncClient() as client:
        tasks = []
        for q in fan:
            tasks.append(_gated("suggest:baidu", _suggest_baidu, client, q))
            tasks.append(_gated("suggest:bing", _suggest_bing, client, q))
        results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            continue
        source, lines = res
        if not isinstance(lines, list):
            continue
        for s in lines:
            norm = s.strip()
            if 4 <= len(norm) <= 200:
                key = norm.lower()
                if key not in seen:
                    seen.add(key)
                    out.append((norm, source))
    return out


# ─── Target 兜底过滤(autocomplete + LLM 统一过)─────


def _drop_target_mentions(items: list[tuple[str, str]],
                          target: str, aliases: list[str]) -> list[tuple[str, str]]:
    """子串大小写不敏感过滤 — 候选含 target / aliases 字面的整条丢掉。

    target 空时直通(向后兼容)。
    """
    if not target.strip():
        return items
    terms = [target.strip().lower()]
    terms.extend(a.strip().lower() for a in aliases if a.strip())
    terms = [t for t in terms if t]
    out: list[tuple[str, str]] = []
    for text, source in items:
        low = text.lower()
        if any(t in low for t in terms):
            continue
        out.append((text, source))
    return out


def _seed_anchor(seed: str) -> str:
    """提取 seed 的主体锚词 — CJK 取末尾 2 字,EN 取最后一个 content token。

    用于 _drop_anchor_drift 兜底:候选不含 seed 主体词的直接丢,挡住
    LLM 的近义词漂移(律师→律所、医生→医院等)。
    """
    seed = (seed or "").strip()
    if not seed:
        return ""
    if _has_cjk(seed):
        cjk_only = "".join(c for c in seed if not c.isspace())
        if len(cjk_only) >= 2:
            return cjk_only[-2:]
        return cjk_only
    tokens = _tokenize(seed)
    content = [t for t in tokens if t not in _STOP_WORDS_EN]
    if content:
        return content[-1]
    return tokens[-1] if tokens else ""


def _drop_anchor_drift(items: list[tuple[str, str]], anchor: str) -> list[tuple[str, str]]:
    """seed 主体词不在候选里 → 丢。anchor 空 / 长度 <2 时直通。

    保护:过滤掉 > 50% 候选时,通常说明 seed 末尾不是真身份词(抽象业务词如
    「私募股权」末尾「股权」/「资本市场」末尾「市场」),回滚不过滤,避免把
    候选全干掉触发 empty → 502。
    """
    if not anchor or len(anchor) < 2:
        return items
    if not items:
        return items
    a_low = anchor.lower()
    kept: list[tuple[str, str]] = []
    for text, source in items:
        if a_low in text.lower():
            kept.append((text, source))
    if len(kept) / len(items) < 0.5:
        return items
    return kept


# 字符级 paraphrase 严格过滤:候选必须把 seed 的所有实质字符都包含进去。
# 忽略「可选虚词」(的 / 了 / 等)和「业务列表分隔符」(/ 、 , ,),其它
# 任何字符缺失整条作废 —— 这是 paraphrase 模式下「不许换字 / 不许漏字段」的
# 硬性保证,把 LLM 的偷懒(简化业务、主体词漂移、加新场景)挡在 score 之前。
_PARAPHRASE_OPTIONAL_CHARS = set("的了等啊呀呢吗")
_PARAPHRASE_SEPARATOR_CHARS = set("/、,, ./.\t ")


# 实体对立词表:seed 末尾若是 key,候选里出现 value 列表里任一词都作废。
# 挡 LLM「在候选里同时塞进种子实体词 + 对立实体词」的偷懒,例如:
#   seed = ...律师 → 候选「在北京律所做跨境并购的律师推荐」(同时有律师 + 律所)
# 字符过滤要求「律 + 师」都在,这种候选两个都满足,会漏过去。
# 加这层 substring 黑名单兜底。
_ENTITY_BLACKLIST: dict[str, tuple[str, ...]] = {
    # 人
    "律师":   ("律所", "事务所", "法务", "合伙人"),
    "医生":   ("医院", "诊所", "科室"),
    "顾问":   ("咨询师", "专家"),
    "教练":   ("老师", "师傅"),
    "老师":   ("教练",),
    # 机构
    "律所":   ("律师",),
    "事务所": ("律师",),
    "医院":   ("医生", "诊所"),
    "诊所":   ("医生", "医院"),
    # 产品 — 不许出现「人」「机构」类词(产品就是物品本身,不是公司不是人)
    "机器人": ("律师", "顾问", "公司", "团队", "工程师"),
    "软件":   ("律师", "顾问", "公司", "团队", "工程师"),
    "设备":   ("律师", "顾问", "公司", "团队", "工程师"),
    "系统":   ("律师", "顾问", "公司", "团队", "工程师"),
    "工具":   ("律师", "顾问", "公司", "团队"),
    "服务":   ("律师", "顾问"),  # 服务模糊,放宽
    "应用":   ("律师", "顾问", "公司"),
    "App":    ("律师", "顾问", "公司"),
    "app":    ("律师", "顾问", "公司"),
}


# 2026-05-26 — 量词跟实体类型不匹配的禁用词。
# 例:seed=「律师」(人)→ 候选不许出现「哪家」「几家」(机构量词)。
# 这是 "量词错配" 而非 "实体词漂移"(后者由 _ENTITY_BLACKLIST 挡),独立一层。
_QUANTIFIER_BLACKLIST: dict[str, tuple[str, ...]] = {
    # 人 — 禁机构量词 + 产品量词
    "person":      ("哪家", "几家", "哪款", "几款", "一款"),
    # 机构 — 禁人量词 + 产品量词
    "institution": ("哪位", "一位", "几位", "推荐一位", "推荐几位",
                    "哪款", "几款", "一款"),
    # 产品 — 禁人量词 + 机构量词
    "product":     ("哪位", "一位", "几位", "推荐一位", "推荐几位",
                    "哪家", "几家", "推荐几家"),
    # generic 不限
    "generic":     (),
}


def _seed_entity_blacklist(seed: str) -> tuple[str, ...]:
    """seed 末尾命中 _ENTITY_BLACKLIST 中任一 key,返回对立实体词列表。

    长串优先匹配避免误判:
      - 「机器人」(3字)能正确匹中,不会被「器人」(2字)截断
      - 「扫地机器人」会命中「机器人」而不是「扫地机」

    例:
      - seed='...北京律师' → ('律所','事务所','法务','合伙人')
      - seed='清洁机器人' → ('律师','顾问','公司','团队','工程师')
      - seed='北京律师事务所' → ('律师',)
    """
    if not seed:
        return ()
    cleaned = "".join(c for c in seed if not c.isspace())
    if not cleaned:
        return ()
    for ent in sorted(_ENTITY_BLACKLIST.keys(), key=len, reverse=True):
        if cleaned.endswith(ent):
            return _ENTITY_BLACKLIST[ent]
    return ()


def _drop_seed_underspec(items: list[tuple[str, str]],
                         seed: str) -> list[tuple[str, str]]:
    """Paraphrase 模式硬过滤 — 三条规则:
       (a) 候选必须包含 seed 的所有实质字符(忽略虚词 + 业务分隔符)
       (b) 候选不能出现 seed 实体词的对立词(律师↛律所,医生↛医院,等)
       (c) 候选量词必须跟实体类型匹配(律师↛哪家;律所↛哪位;机器人↛哪位/哪家)

    挡 LLM:
    - 砍业务字段:「跨境并购」→「并购」(漏「跨」「境」字符 — 规则 a)
    - 换更窄子集:「跨境并购」→「美股 SPAC」(漏所有原字符 — 规则 a)
    - 主体词漂移:「律师」→「律所」(漏「师」字符 — 规则 a)
    - 双塞实体词:「北京律所的律师推荐」(规则 a 漏过,规则 b 拦截 — '律所' 命中黑名单)
    - 加种子里没有的城市:种子「北京」却写「香港」(规则 a 拦)
    - 量词错配:种子「律师」却写「律师哪家好」(规则 c 拦 — '哪家' 是机构量词)

    保护:过滤掉 > 70% 候选时(< 30% 留存)且样本 ≥ 5,回滚不过滤,避免 seed 含
    罕见字符 / 标点导致全军覆没 → empty → 502。
    """
    if not items or not seed.strip():
        return items
    required = set(seed) - _PARAPHRASE_OPTIONAL_CHARS - _PARAPHRASE_SEPARATOR_CHARS
    required_lower = {c.lower() for c in required}
    if not required_lower:
        return items
    blacklist = _seed_entity_blacklist(seed)
    # 规则 (c) 量词黑名单 — 按实体类型决定
    entity_kind = _detect_seed_entity_kind(seed)
    quantifier_blacklist = _QUANTIFIER_BLACKLIST.get(entity_kind, ())
    kept: list[tuple[str, str]] = []
    for text, source in items:
        c_lower = {c.lower() for c in text}
        if not required_lower.issubset(c_lower):
            continue
        # 实体对立词:命中即作废
        if blacklist and any(bad in text for bad in blacklist):
            continue
        # 量词错配:命中即作废
        if quantifier_blacklist and any(q in text for q in quantifier_blacklist):
            continue
        kept.append((text, source))
    # 保护性回滚:LLM 几乎全错时,可能 seed 含罕见字 / 标点导致误杀,回滚
    if len(items) >= 5 and len(kept) / len(items) < 0.30:
        return items
    return kept


def _edit_distance(a: str, b: str) -> int:
    """字符级 Levenshtein 距离(标准 DP 实现,O(m*n) 时间 / O(min(m,n)) 空间)。"""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _drop_near_clones(items: list[tuple[str, str]],
                      seed: str,
                      tail_jaccard_threshold: float = 0.60,
                      max_per_family: int = 10) -> list[tuple[str, str]]:
    """挡「只差一个意图虚词」的近义克隆。

    度量:**非种子字符** jaccard。对每条候选,提取「字符集 - 种子字符集」= tail_chars,
    跟已 kept 的 tail_chars 比 jaccard。如果 ≥ threshold,就是同一个「意图家族」的克隆。

    场景:seed = 「私募股权的北京律师」
      • 「私募股权的北京律师推荐」     → tail = {推, 荐}
      • 「私募股权的北京律师求推荐」   → tail = {求, 推, 荐}    jaccard with 推荐 = 0.67 → 砍
      • 「私募股权的北京律师哪位好」   → tail = {哪, 位, 好}    jaccard with 推荐 = 0   → 留(真的不同)
      • 「私募股权的北京律师哪位靠谱」 → tail = {哪, 位, 靠, 谱} jaccard with 哪位好 = 0.4  → 砍

    `max_per_family=1` 即每个意图家族(=有共同非种子字符的)只留 1 条最高分。
    template:intent 源直通(模板按设计是近义,这层放过它们)。
    保护性回滚:留存率 < 30% 且样本 ≥ 5 时回滚。
    """
    if not items:
        return items
    seed_chars = {c.lower() for c in seed}
    kept: list[tuple[str, str]] = []
    kept_tails: list[set[str]] = []
    for text, source in items:
        if source == "template:intent":
            kept.append((text, source))
            continue
        t_low = text.lower().strip()
        if not t_low:
            continue
        tail = {c for c in t_low if c not in seed_chars}
        # tail 太短(< 2)或者完全等同于种子时,直接保留(已 kept 集合里也按内容去重)
        if len(tail) < 2:
            if t_low not in {t.lower() for t, _ in kept}:
                kept.append((text, source))
                kept_tails.append(tail)
            continue
        clone_count = 0
        for prev_tail in kept_tails:
            if not prev_tail:
                continue
            union = tail | prev_tail
            if not union:
                continue
            j = len(tail & prev_tail) / len(union)
            if j >= tail_jaccard_threshold:
                clone_count += 1
                if clone_count >= max_per_family:
                    break
        if clone_count >= max_per_family:
            continue
        kept.append((text, source))
        kept_tails.append(tail)
    # 保护性回滚
    if len(items) >= 5 and len(kept) / len(items) < 0.30:
        return items
    return kept


def _dedup_template_glut(scored: list[dict], prefix_len: int = 6,
                         suffix_len: int = 6,
                         max_per_template: int = 4,
                         jaccard_threshold: float = 0.78,
                         max_per_jaccard_group: int = 3) -> list[dict]:
    """三层模板去重 — 前缀 / 后缀 / token-bag jaccard。score 高的优先保留。

    2026-05-26 第二轮调整:用户反馈 LLM 输出仍是「换一个虚词」的近义复制,
    阈值再收紧:
      - max_per_template 80→4:同前缀 / 同后缀的最多保留 4 条
      - jaccard_threshold 0.92→0.78:更激进地识别近义重复
      - max_per_jaccard_group 80→3:同模板簇最多 3 条
    配合 prompt 里「结构多样性」约束,LLM 输出的近义克隆会被挡掉,
    最终落到候选池里的都是**句式结构上真有差异**的同义改写。

    `sources == ["template:intent"]` 的纯模板候选直通且不进 accepted 累计 —
    模板按设计就是同前缀枚举,这层去重的初衷是挡 LLM 灌水,把模板顺手砍了
    会让保底候选全军覆没。
    """
    def _norm(s: str) -> str:
        return "".join(ch for ch in s if ch not in " ,.!?!?\t\n").lower()

    items = sorted(scored, key=lambda c: c["score"], reverse=True)
    prefix_counts: dict[str, int] = {}
    suffix_counts: dict[str, int] = {}
    accepted_tokens: list[set[str]] = []
    out: list[dict] = []
    for c in items:
        if c.get("sources") == ["template:intent"]:
            out.append(c)
            continue
        norm = _norm(c["text"])
        tokens = set(_tokenize(c["text"]))
        # jaccard 去重:与已 accepted 比,>= threshold 算"同模板"计票
        if tokens and accepted_tokens:
            jaccard_hits = 0
            for prev in accepted_tokens:
                union = tokens | prev
                if not union:
                    continue
                j = len(tokens & prev) / len(union)
                if j >= jaccard_threshold:
                    jaccard_hits += 1
                    if jaccard_hits >= max_per_jaccard_group:
                        break
            if jaccard_hits >= max_per_jaccard_group:
                continue
        # prefix / suffix 桶限制
        if len(norm) >= max(prefix_len, suffix_len):
            pk = norm[:prefix_len]
            sk = norm[-suffix_len:]
            if prefix_counts.get(pk, 0) >= max_per_template:
                continue
            if suffix_counts.get(sk, 0) >= max_per_template:
                continue
            prefix_counts[pk] = prefix_counts.get(pk, 0) + 1
            suffix_counts[sk] = suffix_counts.get(sk, 0) + 1
        out.append(c)
        accepted_tokens.append(tokens)
    return out


# ─── 4 维 composite 评分 ───────────────────────────


def _seed_core_terms(seed: str) -> list[str]:
    """CJK seed 拆 2 字 chunk(融资律师→[融资,律师]);EN 拆 content tokens。"""
    seed = (seed or "").strip()
    if not seed:
        return []
    if _has_cjk(seed):
        cjk_only = "".join(c for c in seed if not c.isspace())
        chunks: list[str] = []
        i = 0
        while i + 1 < len(cjk_only):
            chunks.append(cjk_only[i:i + 2])
            i += 2
        if i < len(cjk_only):
            if chunks:
                chunks[-1] = chunks[-1] + cjk_only[i]
            else:
                chunks.append(cjk_only[i])
        return [c for c in chunks if c]
    tokens = _tokenize(seed)
    content = [t for t in tokens if t not in _STOP_WORDS_EN]
    return content or tokens


def _score_seed_relevance(text: str, seed_terms: list[str]) -> float:
    if not text or not seed_terms:
        return 0.0
    text_l = text.lower()
    hits = sum(1 for t in seed_terms if t.lower() in text_l)
    return hits / len(seed_terms)


def _score_retrieval_potential(text: str) -> float:
    """含问句词 / 动词 / ≥2 实词。LLM 候选大多满分,autocomplete 偏低。"""
    tokens = _tokenize(text)
    if not tokens:
        return 0.0
    score = 0.0
    if (any(t in _QUESTION_WORDS_EN for t in tokens)
            or any(m in text for m in _CJK_QUESTION_MARKERS)):
        score += 0.5
    if any(t in _VERBS_EN for t in tokens):
        score += 0.2
    content = [t for t in tokens
               if t not in _STOP_WORDS_EN and t not in _CJK_STOP_CHARS]
    if len(content) >= 2:
        score += 0.3
    return min(1.0, score)


def _score_commercial_intent(text: str) -> float:
    tokens = _tokenize(text)
    hits = sum(1 for t in tokens if t in _COMMERCIAL_TERMS_EN)
    hits += sum(1 for m in _CJK_COMMERCIAL_MARKERS if m in text)
    if hits == 0:
        return 0.0
    return 0.6 if hits == 1 else 1.0


def _score_uniqueness(text: str, accepted_token_sets: list[set[str]]) -> float:
    tokens = set(_tokenize(text))
    if not tokens or not accepted_token_sets:
        return 1.0
    max_j = 0.0
    for prev in accepted_token_sets:
        union = tokens | prev
        if not union:
            continue
        j = len(tokens & prev) / len(union)
        if j > max_j:
            max_j = j
    return max(0.0, 1.0 - max_j)


def _score_candidate(text: str, seed_terms: list[str],
                     accepted_token_sets: list[set[str]]) -> int:
    """4 维加权,seed_relevance 阻尼,出 0-100 int。

    权重设计:LLM 输出长度/熵都满分,human_like/entropy 无信息量已砍。
    """
    seed_rel = _score_seed_relevance(text, seed_terms) if seed_terms else 1.0
    retrieval = _score_retrieval_potential(text)
    commercial = _score_commercial_intent(text)
    uniqueness = _score_uniqueness(text, accepted_token_sets)
    base = (
        seed_rel * 0.35
        + retrieval * 0.25
        + commercial * 0.20
        + uniqueness * 0.20
    ) * 100
    # seed_relevance 阻尼,但 seed_relevance 已经在 base 里了,这里不再重复乘
    return int(round(base))


# ─── 纯模板扩展(seed + 同义意图前/后缀)───────────────
#
# 0 漂移、0 幻觉的保底底盘。seed 原样保留,只拼前缀 / 后缀。
# 2026-05-26 升级:按 seed 末尾实体词自动选「人」/「机构」两套量词:
#   - seed 是律师 / 医生 / 顾问 这类「人」 → 用「哪位 / 哪个 / 推荐一位」
#   - seed 是律所 / 事务所 / 公司 这类「机构」 → 用「哪家 / 推荐几家」
#   - 检测不到 → fallback 机构套(向后兼容)
# 词表跟 prompt 白名单基本一致,确保 LLM 和模板产出风格一致。

# seed 末尾命中下面任一,判定为「人」
_PERSON_ENTITIES: tuple[str, ...] = (
    "律师", "医生", "顾问", "教练", "老师", "师傅",
    "设计师", "工程师", "咨询师", "培训师", "经纪人",
    "专家", "合伙人", "投顾", "主播", "摄影师", "写手", "翻译",
)
# seed 末尾命中下面任一,判定为「机构」(优先长串匹配:律师事务所 > 事务所)
_INSTITUTION_ENTITIES: tuple[str, ...] = (
    "律师事务所", "事务所", "律所", "医院", "诊所", "公司",
    "工作室", "机构", "学校", "培训机构", "团队",
)
# seed 末尾命中下面任一,判定为「产品」(物品 / 工具 / 软件 / 服务)
_PRODUCT_ENTITIES: tuple[str, ...] = (
    "机器人", "扫地机", "扫地机器人", "吸尘器", "洗碗机", "净水器", "空气净化器",
    "软件", "工具", "设备", "系统", "平台", "应用", "服务", "套件", "方案",
    "产品", "App", "app", "SaaS", "saas", "插件", "模板",
)

# 通用前缀(人/机构/产品都能用)
_INTENT_PREFIXES: tuple[str, ...] = (
    "推荐", "求推荐", "适合", "推荐一个",
    "想找", "求", "找", "帮忙推荐",
    "有没有", "有没有靠谱的", "哪里有", "哪里能找到",
)

# 「人」专用后缀(用哪位 / 哪个 / 推荐一位)
_PERSON_INTENT_SUFFIXES: tuple[str, ...] = (
    "哪位好", "哪位靠谱", "哪位专业", "哪位口碑好", "哪位资深",
    "哪个好", "哪个靠谱", "哪个专业",
    "推荐", "推荐一位", "推荐一个", "推荐几位",
    "求推荐", "求推荐一位",
    "找哪位", "找哪个", "怎么找",
    "有推荐吗", "有靠谱的吗", "找谁靠谱", "找谁好",
)
_PERSON_EXTRA_PREFIXES: tuple[str, ...] = (
    "推荐一位", "推荐几位", "帮忙推荐一位", "帮忙推荐一个",
)

# 「机构」专用后缀(用哪家)
_INSTITUTION_INTENT_SUFFIXES: tuple[str, ...] = (
    "哪家好", "哪家强", "哪家专业", "哪家靠谱", "哪家口碑好",
    "哪个好", "哪个靠谱",
    "推荐", "推荐哪家", "推荐几家", "求推荐",
    "找哪家", "怎么找", "选哪家", "选哪家好",
    "排名", "有哪些",
    "在哪里找", "去哪里找",
)
_INSTITUTION_EXTRA_PREFIXES: tuple[str, ...] = (
    "推荐几家", "帮忙推荐几家",
)

# 「产品」专用后缀(用哪款 / 哪个 / 推荐一款)
_PRODUCT_INTENT_SUFFIXES: tuple[str, ...] = (
    "哪款好", "哪款靠谱", "哪款值得买", "哪款性价比高",
    "哪个好", "哪个值得买", "哪个推荐", "哪个靠谱", "哪个性价比高",
    "推荐", "推荐一款", "推荐一个", "推荐几款",
    "求推荐", "求推荐一款", "求选购建议",
    "选哪个", "选哪款", "怎么选",
    "有推荐吗", "有什么好的",
)
_PRODUCT_EXTRA_PREFIXES: tuple[str, ...] = (
    "推荐一款", "推荐几款", "选购", "想买",
)


def _detect_seed_entity_kind(seed: str) -> str:
    """返回 'person' / 'institution' / 'product' / 'generic'。

    匹配优先级:机构 > 产品 > 人 — 长串先匹避免误判:
      - 「律师事务所」不被「律师」误判成 person
      - 「扫地机器人」不被「扫地机」误判过早,而是先匹「机器人」结尾后判 product
    """
    seed = (seed or "").strip()
    if not seed:
        return "generic"
    # 移除空白但保留中文 / 英文 / 标点(实体词可能含 App / SaaS 这种英文)
    cleaned = "".join(c for c in seed if not c.isspace())
    if not cleaned:
        return "generic"
    for ent in sorted(_INSTITUTION_ENTITIES, key=len, reverse=True):
        if cleaned.endswith(ent):
            return "institution"
    for ent in sorted(_PRODUCT_ENTITIES, key=len, reverse=True):
        if cleaned.endswith(ent):
            return "product"
    for ent in sorted(_PERSON_ENTITIES, key=len, reverse=True):
        if cleaned.endswith(ent):
            return "person"
    return "generic"


# 「脏 seed」标志词 — seed 里出现这些就说明 seed 已经是 query 不是名词短语,
# 拼意图后缀会产出「X推荐推荐」「X，不要 Y 哪家好」这种重复 / 病句。
# 检测到就跳过 template:intent 这一路,让 LLM 直接 paraphrase。
_DIRTY_SEED_INTENT_MARKERS: tuple[str, ...] = (
    "推荐", "求推荐", "哪家好", "哪个好", "哪位好", "哪款好",
    "哪家靠谱", "哪个靠谱", "哪位靠谱", "哪款靠谱",
    "哪家专业", "哪家强", "怎么找", "怎么选",
    "有推荐吗", "有靠谱的吗", "有没有靠谱的",
    "哪里有", "哪里能找到", "选哪家", "选哪个", "选哪款",
    "找哪家", "找哪个", "找哪位", "找谁靠谱", "找谁好",
    "排名", "有哪些",
)


def _seed_is_dirty(seed: str) -> tuple[bool, list[str]]:
    """检测 seed 是否已含意图词。返回 (is_dirty, markers_found)。"""
    if not seed:
        return False, []
    hits = [m for m in _DIRTY_SEED_INTENT_MARKERS if m in seed]
    return bool(hits), hits


def _template_expand_zh(seed: str) -> list[str]:
    """中文 seed 的纯模板扩展 — 按实体类型(人 / 机构)选意图词。

    产出:
      1. seed 原样
      2. [seed] + [实体匹配的意图后缀]
      3. [通用前缀 + 实体专用前缀] + [seed]
    内部按 lowercase 去重保序。

    数量级:人 ≈ 38 条,机构 ≈ 30 条,generic ≈ 30 条。
    """
    seed = (seed or "").strip()
    if not seed:
        return []
    # 脏 seed(已含意图词)— 跳过 template:intent,只返回 seed 本身。
    # 不再拼后缀避免「X推荐推荐」「X，不要 Y 哪家好」之类的重复 / 病句。
    is_dirty, _ = _seed_is_dirty(seed)
    if is_dirty:
        return [seed]

    kind = _detect_seed_entity_kind(seed)
    if kind == "person":
        suffixes = _PERSON_INTENT_SUFFIXES
        prefixes = _INTENT_PREFIXES + _PERSON_EXTRA_PREFIXES
    elif kind == "institution":
        suffixes = _INSTITUTION_INTENT_SUFFIXES
        prefixes = _INTENT_PREFIXES + _INSTITUTION_EXTRA_PREFIXES
    elif kind == "product":
        suffixes = _PRODUCT_INTENT_SUFFIXES
        prefixes = _INTENT_PREFIXES + _PRODUCT_EXTRA_PREFIXES
    else:
        # generic / 旧行为兜底
        suffixes = _INSTITUTION_INTENT_SUFFIXES
        prefixes = _INTENT_PREFIXES

    out: list[str] = [seed]
    for suf in suffixes:
        out.append(seed + suf)
    for pre in prefixes:
        out.append(pre + seed)

    seen: set[str] = set()
    dedup: list[str] = []
    for t in out:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(t)
    return dedup


# 纯模板固定分。70 让模板在最终 list 里占住中位:
# - LLM 高质量场景 (>= 80) 仍排前
# - 模板「seed + 商业意图后缀」(=70) 居中,做保底底盘
# - LLM 弱质量 / 模板尾巴 / autocomplete (< 70) 排后
_TEMPLATE_FIXED_SCORE = 70


# ─── Public entry ─────────────────────────────────


async def suggest_queries(
    seed: str, count: int = 200, *,
    target: str = "", aliases: Optional[list[str]] = None, industry: str = "",
    service_geo: str = "",
    profile_cases: Optional[list[str]] = None,
    include_autocomplete: bool = False,
    include_clusters: bool = True,
) -> tuple[list[dict], list[dict]]:
    """seed → (candidates, clusters_meta)。

    candidates = [{text, score, sources, cluster_id}, ...],按 score 降序。
    clusters_meta = [{cluster_id, label, size, medoid_index}, ...] 按 size 降序;
                    include_clusters=False 或候选 <4 时返回空列表。

    并行调:
      - DeepSeek(主力,GEO-aware prompt + 自身去重)
      - Baidu sugrec + Bing osjson(补真实搜索词;include_autocomplete=False 可关)
    打分后跑 sentence-transformers 嵌入 + K-Means(silhouette auto-K 3-8)。

    target 非空时:LLM 多要 ~1.3x 量,合并后统一过 _drop_target_mentions 兜底。
    失败时抛 DeepSeekError(no_key / invalid_seed / http_4xx / network / empty)。
    """
    seed = (seed or "").strip()
    if not seed:
        raise DeepSeekError("invalid_seed", "seed 不能为空")
    count = max(5, min(count, 300))
    target = (target or "").strip()
    aliases = [a.strip() for a in (aliases or []) if a and a.strip()]
    industry = (industry or "").strip()
    service_geo = (service_geo or "").strip()
    profile_cases = [c.strip() for c in (profile_cases or []) if c and c.strip()][:40]

    # raw_count 上限 80 — 2026-05-26 砍下来(原 200 太大,LLM 生成慢易超时,
    # 且 paraphrase 模式下 80 条已远超合理多样性上限)。
    raw_count = min(80, max(20, int(count * 1.3))) if target else min(80, max(20, count))

    # 两路并行:autocomplete 失败吞掉。LLM 失败 2026-05-26 起也吞掉,
    # 退到 template:intent 那一路兜底(CJK seed 永远有 ~30 条模板候选)。
    llm_task = _fetch_llm(seed, raw_count, target, aliases, industry, service_geo, profile_cases)
    if include_autocomplete:
        results = await asyncio.gather(
            llm_task, _fetch_suggest(seed), return_exceptions=True,
        )
        llm_res, sug_res = results[0], results[1]
    else:
        try:
            llm_res = await llm_task
        except DeepSeekError as e:
            # no_key / invalid_seed 是配置错,得让 caller 知道
            if e.code in ("no_key", "invalid_seed"):
                raise
            # 其它(network / http_429 / http_5xx / parse)→ 软失败,走模板兜底
            import logging
            logging.getLogger(__name__).warning(
                "LLM failed (%s: %s), falling back to template-only", e.code, e.message,
            )
            llm_res = e
        sug_res = []

    # LLM 出错 → 取空列表,后面 template:intent 路径兜底
    llm_lines: list[str]
    if isinstance(llm_res, Exception):
        llm_lines = []
    else:
        llm_lines = llm_res
    sug_pairs: list[tuple[str, str]] = sug_res if isinstance(sug_res, list) else []

    # 合并 + 去重(归一化小写),记录每条 text 来自哪几个 source
    merged: dict[str, dict] = {}
    for text in llm_lines:
        key = text.strip().lower()
        if not key:
            continue
        merged.setdefault(key, {"text": text.strip(), "sources": []})
        merged[key]["sources"].append("llm:deepseek")
    for text, source in sug_pairs:
        key = text.strip().lower()
        if not key:
            continue
        merged.setdefault(key, {"text": text.strip(), "sources": []})
        if source not in merged[key]["sources"]:
            merged[key]["sources"].append(source)

    # 模板扩展:仅 CJK seed。seed 100% 原样保留 + 商业意图后缀枚举,
    # 不走 LLM —— 0 漂移、0 幻觉,做高商业意图的保底底盘。
    # 若 LLM 也撞出同一条 text,在这里多打一个 source,排序 / 评分
    # 走 LLM 那一档(因为 sources != ["template:intent"])。
    if _has_cjk(seed):
        for text in _template_expand_zh(seed):
            key = text.strip().lower()
            if not key:
                continue
            merged.setdefault(key, {"text": text.strip(), "sources": []})
            if "template:intent" not in merged[key]["sources"]:
                merged[key]["sources"].append("template:intent")

    # target 过滤(LLM + suggest 统一过)
    if target:
        pairs = [(m["text"], "_") for m in merged.values()]
        kept_texts = {t.lower() for t, _ in _drop_target_mentions(pairs, target, aliases)}
        merged = {k: v for k, v in merged.items() if v["text"].lower() in kept_texts}

    # seed 主体词锚定过滤 — 不含 seed 末尾主体词的候选全丢,挡住
    # LLM 的近义词漂移(律师→律所、医生→医院、教练→老师 等)
    anchor = _seed_anchor(seed)
    if anchor and len(anchor) >= 2:
        pairs = [(m["text"], "_") for m in merged.values()]
        kept_texts = {t.lower() for t, _ in _drop_anchor_drift(pairs, anchor)}
        merged = {k: v for k, v in merged.items() if v["text"].lower() in kept_texts}

    # Paraphrase 字符级硬过滤 — 候选必须包含 seed 的所有实质字符(忽略虚词 + 业务分隔符)。
    # 比 anchor_drift 严得多:anchor 只检查主体词末 2 字,这层覆盖整个 seed,
    # 把「砍业务字段 / 换更窄子集 / 漏字段」全堵掉。模板源(template:intent)直通,
    # 因为模板按设计是 seed 原样拼后缀,字符完整保留。
    pairs = [(m["text"], "_") for m in merged.values()
             if "template:intent" not in m["sources"]]
    if pairs:
        kept_texts = {t for t, _ in _drop_seed_underspec(pairs, seed)}
        merged = {
            k: v for k, v in merged.items()
            if v["text"] in kept_texts or "template:intent" in v["sources"]
        }

    # 2026-05-26 — 近义克隆过滤(`{seed}推荐` / `{seed}求推荐` / `{seed}哪位好` …
    # 这种「只差 1 个意图虚词」的候选)。按 score 从高到低顺序遍历,跟已 kept 比
    # 字符编辑距离 / 长度。token jaccard 在 CJK 短句上分不开近义克隆 vs 真结构差异,
    # 编辑距离能。
    pairs2 = [(m["text"], "llm" if "llm:deepseek" in m["sources"] else "_")
              for m in merged.values() if "template:intent" not in m["sources"]]
    if pairs2:
        kept_texts2 = {t for t, _ in _drop_near_clones(pairs2, seed)}
        merged = {
            k: v for k, v in merged.items()
            if v["text"] in kept_texts2 or "template:intent" in v["sources"]
        }

    if not merged:
        raise DeepSeekError("empty", "候选全被过滤或 LLM 返回为空,换个 seed 重试")

    # 评分(uniqueness 依赖输入顺序,按 sources 优先级排:先 LLM,然后混合,
    # 最后纯模板)。纯模板候选不走 _score_candidate,固定 70 分,也不进
    # accepted —— 因为模板按设计高度相似,放进 accepted 会污染 LLM uniqueness。
    seed_terms = _seed_core_terms(seed)
    items = list(merged.values())
    items.sort(key=lambda m: (
        0 if "llm:deepseek" in m["sources"] else (
            2 if m["sources"] == ["template:intent"] else 1
        ),
        m["text"],
    ))
    accepted: list[set[str]] = []
    scored: list[dict] = []
    for m in items:
        if m["sources"] == ["template:intent"]:
            scored.append({"text": m["text"], "score": _TEMPLATE_FIXED_SCORE,
                           "sources": m["sources"]})
            continue
        score = _score_candidate(m["text"], seed_terms, accepted)
        scored.append({"text": m["text"], "score": score, "sources": m["sources"]})
        accepted.append(set(_tokenize(m["text"])))

    scored.sort(key=lambda c: c["score"], reverse=True)
    # 模板灌水兜底:同前缀 6 字的 query 每模板最多 5 条 — 挡 LLM 在 count 大时
    # 进入「同句式 + 国家/行业字典遍历」凑数模式
    scored = _dedup_template_glut(scored)
    scored = scored[:count]

    # 聚类:嵌入 + K-Means。失败吞掉(聚类是锦上添花,不致 endpoint 5xx)
    clusters_meta: list[dict] = []
    if include_clusters and len(scored) >= 4:
        try:
            from .clustering import cluster_candidates
            texts = [c["text"] for c in scored]
            labels, clusters_meta = await cluster_candidates(texts)
            for c, lab in zip(scored, labels):
                c["cluster_id"] = int(lab)
            # label 重命名:先用簇内最高 score 当 fallback label,再尝试 LLM 二次打标
            # 生成 2-8 字主题摘要(更直观)。LLM 失败回退到 max-score label。
            by_cluster: dict[int, list[dict]] = {}
            for c in scored:
                by_cluster.setdefault(c["cluster_id"], []).append(c)
            for meta in clusters_meta:
                members = by_cluster.get(meta["cluster_id"]) or []
                if members:
                    top = max(members, key=lambda c: c["score"])
                    meta["label"] = top["text"]
            # LLM 二次打标 — 一次 call 给所有簇生成主题摘要
            try:
                llm_labels = await _label_clusters_llm(by_cluster, seed=seed)
                for meta in clusters_meta:
                    if meta["cluster_id"] in llm_labels:
                        meta["label"] = llm_labels[meta["cluster_id"]]
            except Exception:  # noqa: BLE001 — LLM 打标失败保留 max-score label
                pass
        except Exception:  # noqa: BLE001 — 模型加载/推理失败都不让 endpoint 5xx
            clusters_meta = []
            for c in scored:
                c["cluster_id"] = 0
    else:
        for c in scored:
            c["cluster_id"] = 0

    return scored, clusters_meta
