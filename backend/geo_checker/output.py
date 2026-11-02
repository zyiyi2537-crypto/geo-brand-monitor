"""Output layer: structured i18n emit + legacy print shim.

Migrated from /geo_checker.py lines 68–143 (LANG / _ZH / _tr / _pad / print
shim / emit_check) and backend/geo_checker/__main__.py lines 70–125
(emit_check / emit_fix).

Design:
- `emit_check(status, key, message, params)` — canonical check output. When
  GEO_EMIT_STRUCTURED=1 (set by backend before import), a machine-readable
  key marker is appended so the backend's parse_geo_output can attach
  message_key / message_params to CheckResult. CLI users don't set the env
  var and see clean English output.
- `emit_fix(key, message, params)` — the analog for fix recommendations.
  Collapses multi-line messages onto a single line (joined by \\x02) so the
  line-based parser handles it as one row; the backend splits them back out.
- `fix(message)` — legacy helper that routes to emit_fix with no i18n key.
  Kept so un-migrated call sites still work.
- `print(...)` — shadows builtin print; when LANG != "en" it runs each arg
  through _tr() before delegating. CLI users pass --lang zh to trigger.
- `_tr(text)` / `_pad` / `_display_width` — i18n helpers for CLI-mode
  Chinese output. _ZH is populated from /docs (or whatever the upstream ZH
  table source is) at module import; see the legacy root file for the table.
"""

import json
import os as _os
import re as _re
import sys as _sys

from .state import SHOW_FIX as _SHOW_FIX_IMPORT
from . import state as _state
from .constants import FIX

# ---------------------------------------------------------------------------
# i18n  — output-level translation (CLI mode)
# ---------------------------------------------------------------------------
LANG = "en"

# Pre-scan sys.argv so everything downstream sees the right language.
# Only meaningful when invoked as CLI (`geo-checker --lang zh ...`); backend
# never passes --lang.
if "--lang" in _sys.argv:
    _idx = _sys.argv.index("--lang")
    if _idx + 1 < len(_sys.argv) and _sys.argv[_idx + 1] in ("en", "zh"):
        LANG = _sys.argv[_idx + 1]

# _ZH maps English substrings → Chinese. Populated at end of translations
# setup (currently done by a separate module or at package load); entries
# are tried longest-first via _ZH_SORTED to avoid partial matches.
_ZH: dict = {}
_ZH_SORTED: list = []  # [(en, zh)] sorted by len(en) descending; built once


def _tr(text):
    """Translate English substrings in *text* to Chinese using _ZH table."""
    global _ZH_SORTED
    if LANG == "en" or not _ZH:
        return text
    if not _ZH_SORTED:
        _ZH_SORTED = sorted(_ZH.items(), key=lambda kv: len(kv[0]), reverse=True)
    for en, zh in _ZH_SORTED:
        if en in text:
            text = text.replace(en, zh)
    return text


def _display_width(s):
    """Return the number of terminal columns *s* occupies. CJK chars are
    double-width; ANSI escapes are zero-width."""
    import unicodedata
    s = _re.sub(r'\033\[[0-9;]*m', '', s)  # strip ANSI
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def _pad(s, width):
    """Left-align *s* in a field of *width* terminal columns. Translates *s*
    first so padding accounts for CJK display width."""
    s = _tr(s)
    return s + ' ' * max(0, width - _display_width(s))


# Keep a reference to the real print so the shim can delegate.
_builtin_print = print


def print(*args, **kwargs):            # noqa: A001 — intentional shadow
    """Module-level print override. Only translates when LANG != 'en'."""
    if LANG != "en" and args:
        args = tuple(_tr(str(a)) if isinstance(a, str) else a for a in args)
    _builtin_print(*args, **kwargs)


# ---------------------------------------------------------------------------
# Structured-emit layer for backend i18n
# ---------------------------------------------------------------------------
# When the backend imports us it sets GEO_EMIT_STRUCTURED=1 in the env
# BEFORE importing. emit_check / emit_fix then embed a machine-parseable
# marker at the end of each printed line carrying the i18n key + params.
# The backend's parse_geo_output extracts the marker and attaches
# message_key / message_params fields to CheckResult, enabling frontend
# t(key, params) rendering. Standalone CLI users don't set the env var and
# see clean English output, exactly as the original upstream behavior.

_EMIT_STRUCTURED = _os.environ.get("GEO_EMIT_STRUCTURED") == "1"
_KEY_MARKER_START = "\x01GK\x01"
_KEY_MARKER_END = "\x01GE\x01"


def emit_check(status_tag, key, message, params=None):
    """Print a check result line and (optionally) embed i18n metadata.

    status_tag: one of PASS / WARN / FAIL / INFO (the ANSI-wrapped constants)
    key:        i18n key path under result.checks.* on the frontend
    message:    human-readable English fallback (also drives CLI output)
    params:     dict of interpolation values (e.g. {"count": 12})
    """
    line = f"  [{status_tag}] {message}"
    if _EMIT_STRUCTURED and key:
        meta = json.dumps({"k": key, "p": params or {}}, ensure_ascii=False)
        line += f"{_KEY_MARKER_START}{meta}{_KEY_MARKER_END}"
    print(line)


def emit_fix(key, message, params=None):
    """Print a fix recommendation (multi-line) with optional i18n metadata.

    Emits the entire message as a single line (joined with sentinel \\x02
    that the backend parser splits back out) so the structured marker only
    appears once and the parser can assign fix_key / fix_params to the
    preceding check. When SHOW_FIX is off the call is a no-op.
    """
    if not _state.SHOW_FIX:
        return
    one_liner = message.strip().replace("\n", "\x02")
    line = f"  [{FIX}] {one_liner}"
    if _EMIT_STRUCTURED and key:
        meta = json.dumps({"k": key, "p": params or {}}, ensure_ascii=False)
        line += f"{_KEY_MARKER_START}{meta}{_KEY_MARKER_END}"
    print(line)


def fix(message):
    """Legacy fix() helper — routes to emit_fix() with no i18n key so
    un-migrated call sites still work. New code should call emit_fix()
    directly with a stable key under result.fixes.*.
    """
    emit_fix(None, message)
_ZH.update({
    # ── Category names (score table display) ──
    "AI Answer Formats": "AI 回答格式",
    "AI Crawl Readiness": "AI 抓取就绪度",
    "AI Optimization": "AI 优化",
    "Answer Engine Schema": "问答引擎 Schema",
    "Authority & Trust": "权威性与信任度",
    "Brand Entity KG": "品牌实体知识图谱",
    "Content Accessibility": "内容可访问性",
    "Content Quality": "内容质量",
    "Content Structure": "内容结构",
    "Cross-Platform": "跨平台分发",
    "Direct Answer Snippets": "直接回答片段",
    "FAQ Readiness": "FAQ 就绪度",
    "Heading Hierarchy": "标题层级结构",
    "Meta Tags": "Meta 标签",
    "Mobile & Weight": "移动端与页面体积",
    "Multi-Page": "多页面一致性",
    "Multilingual": "多语言支持",
    "Outbound & Media": "外链与媒体",
    "Per-Page Content": "单页内容评分",
    "Platform Registration": "平台注册",
    "Question Headings": "问句式标题",
    "Readability & Trust": "可读性与来源信任",
    "Schema & Knowledge": "Schema 与知识面板",
    "Sitemap": "站点地图",
    "Social Signals": "社交信号",
    "Structured Data": "结构化数据",
    "Technical Crawlability": "技术可抓取性",
    "Trust & Safety": "信任与安全",
    "URL Normalization": "URL 规范化",

    # ── Section headers ──
    ".well-known Discovery": ".well-known 发现",
    "Search Engine & AI Platform Registration": "搜索引擎与 AI 平台注册",
    "Content Quality for AI": "面向 AI 的内容质量",
    "Authority & Trust Signals": "权威性与信任信号",
    "Brand Entity in Knowledge Graphs": "品牌实体在知识图谱中的表现",
    "Trust & Safety Signals": "信任与安全信号",
    "AI-Specific Optimization": "AI 专项优化",
    "AI Answer Format Optimization": "AI 回答格式优化",
    "Schema Breadcrumbs & Knowledge Panel": "Schema 面包屑与知识面板",
    "Mobile-Friendliness & Page Weight": "移动端适配与页面体积",
    "Outbound Links & Media": "外链与媒体资源",
    "Multilingual Content Depth": "多语言内容深度",
    "Cross-Platform Content Distribution": "跨平台内容分发",
    "Multi-Page Sampling": "多页面抽样检测",
    "Per-Page AEO Content Score": "单页 AEO 内容评分",
    "AEO (Answer Engine Optimization) Audit": "AEO（问答引擎优化）审计",
    "1. FAQ Readiness": "1. FAQ 就绪度",
    "2. Question-Pattern Headings": "2. 问句式标题",
    "3. Direct Answer Snippets": "3. 直接回答片段",
    "4. Answer Engine Schema": "4. 问答引擎 Schema",
    "5. Content Structure for AI Extraction": "5. 面向 AI 提取的内容结构",
    "6. Readability & Source Trust": "6. 可读性与来源信任",
    "7. Heading Hierarchy": "7. 标题层级结构",
    "8. Per-Page AEO Content Score": "8. 单页 AEO 内容评分",

    # ── UI chrome / structural ──
    "GEO Readiness Report for:": "GEO 就绪度报告：",
    "Mode:": "模式：",
    "Diagnose + Fix Recommendations": "诊断 + 修复建议",
    "Diagnose Only": "仅诊断",
    "AI VISIBILITY SCORE": "AI 可见度评分",
    "Category Breakdown:": "分类明细：",
    "TOTAL": "总计",
    "Category": "类别",
    "Legend: PASS = good | WARN = could improve | FAIL = missing/bad": "图例：PASS = 良好 | WARN = 待改进 | FAIL = 缺失/异常",
    "FIX = recommended action to resolve the issue": "FIX = 建议采取的修复操作",
    "Tip: Run with --fix to see recommended solutions": "提示：使用 --fix 参数运行可查看修复建议",
    "CONTENT GAP SUGGESTIONS": "内容缺口建议",
    "Based on your weakest categories, here are content strategies": "根据您得分最低的类别，以下是提升",
    "to improve your AI visibility:": "AI 可见度的内容策略：",
    "Priority improvements:": "优先改进项：",
    "AEO SCORE": "AEO 评分",
    "Target:": "目标：",
    "GEO COMPETITIVE COMPARISON": "GEO 竞争对比",
    "AI CITATION SHARE": "AI 引用份额",
    "Winner:": "获胜者：",
    "Lead:": "领先：",
    "Category Advantages:": "类别优势：",
    "Weakest Signal": "最弱信号",
    "Average": "平均",
    "AI VISIBILITY AUDIT": "AI 可见度审计",
    "GEO HEALTH SCORECARD": "GEO 健康度记分卡",
    "Engines:": "引擎：",
    "Per-Engine Visibility:": "各引擎可见度：",
    "Citation leader:": "引用领先者：",
    "CITATION SHARE RESULTS": "引用份额结果",
    "FIX recommendations are shown inline above.": "FIX 修复建议已在上方对应位置显示。",

    # ── Status messages ──
    "Site uses HTTPS": "站点已启用 HTTPS",
    "Site does not use HTTPS — AI engines prefer secure sites": "站点未使用 HTTPS —— AI 引擎更青睐安全站点",
    "robots.txt found": "robots.txt 已找到",
    "robots.txt not found": "robots.txt 未找到",
    "robots.txt references a sitemap": "robots.txt 中引用了站点地图",
    "AI bots not mentioned (inherit wildcard rules):": "以下 AI 爬虫未单独提及（继承通配符规则）：",
    "AI bots explicitly BLOCKED:": "以下 AI 爬虫被明确阻止：",
    "/ai.txt found — strategic AI crawler policy declared": "/ai.txt 已找到 —— 已声明 AI 抓取策略",
    "llms.txt found": "llms.txt 已找到",
    "llms-full.txt found": "llms-full.txt 已找到",
    ".well-known/llms.txt found": ".well-known/llms.txt 已找到",
    "Contains descriptive text": "包含描述性文本",
    "No sections (## headings) — consider organizing content into sections": "无章节（## 标题）—— 建议将内容组织为分节结构",
    "link(s) to resources found": "个资源链接已找到",
    "section(s) found (## headings)": "个章节已找到（## 标题）",
    "No llms.txt found": "未找到 llms.txt",
    "Sitemap found": "站点地图已找到",
    "Sitemap includes <lastmod> timestamps": "站点地图包含 <lastmod> 时间戳",
    "No sitemap found": "未找到站点地图",
    "Google Search Console verification tag found": "Google Search Console 验证标签已找到",
    "Bing Webmaster Tools verification tag found": "Bing Webmaster Tools 验证标签已找到",
    "No Yandex Webmaster verification tag — relevant if targeting international AI platforms": "未找到 Yandex Webmaster 验证标签 —— 若面向国际 AI 平台则需关注",
    "IndexNow endpoint found": "IndexNow 端点已找到",
    "Found JSON-LD block(s)": "找到 JSON-LD 代码块",
    "No structured data (JSON-LD/Microdata) found": "未找到结构化数据（JSON-LD / Microdata）",
    "Granular schema types present:": "已使用细粒度 Schema 类型：",
    "<title> found:": "<title> 已找到：",
    "Meta description found": "Meta 描述已找到",
    "Canonical URL set:": "Canonical URL 已设置：",
    "Open Graph tags present:": "Open Graph 标签已设置：",
    "Twitter Card tags present:": "Twitter Card 标签已设置：",
    "Language declared:": "语言声明：",
    "No hreflang tags — add these if your site supports multiple languages": "无 hreflang 标签 —— 若站点支持多语言请添加",
    "Homepage has": "首页包含",
    "words in initial HTML": "个单词（初始 HTML）",
    "Content-to-HTML ratio:": "内容与 HTML 的比例：",
    "Heading structure found": "标题结构已找到",
    "Content is rendered server-side": "内容为服务端渲染",
    "No restrictive meta robots tag found": "未发现限制性 meta robots 标签",
    "No restrictive X-Robots-Tag header": "未发现限制性 X-Robots-Tag 头",
    "No paywall/login-wall indicators detected": "未检测到付费墙/登录墙",
    "Good semantic HTML structure": "良好的语义化 HTML 结构",
    "images have alt text": "张图片已添加 alt 文本",
    "internal links — good for AI crawl discovery": "个内部链接 —— 有利于 AI 抓取发现",
    "Response time:": "响应时间：",
    "Readability: Flesch-Kincaid grade": "可读性：Flesch-Kincaid 等级",
    "FAQ content detected — strong signal for AI-generated answers": "检测到 FAQ 内容 —— 对 AI 生成回答有强信号作用",
    "quotable statistics found — good for AI citations": "个可引用的统计数据 —— 有利于 AI 引用",
    "No explicit source attributions — citing sources increases AI trust in your content": "未发现明确的来源引用 —— 引用来源可提升 AI 对您内容的信任度",
    "Structured lists found": "找到结构化列表",
    "Canonical URL is self-referencing (correct)": "Canonical URL 自引用（正确）",
    "No redirects — direct access": "无重定向 —— 直接访问",
    "HTTP/2 supported — faster crawling": "支持 HTTP/2 —— 抓取更快",
    "No RSS/Atom feed found — feeds help AI engines monitor content freshness": "未找到 RSS/Atom 订阅源 —— 订阅源帮助 AI 引擎追踪内容更新",
    "Machine-readable / integration endpoints:": "机器可读 / 集成端点：",
    "Strong security headers": "安全响应头设置良好",
    "humans.txt found — authorship transparency": "humans.txt 已找到 —— 作者信息透明",
    "Author markup found in structured data (JSON-LD)": "结构化数据（JSON-LD）中找到作者标记",
    "Bio/about page found at": "个人/关于页面已找到，地址为",
    "Credential signals in bio:": "简介中的资质信号：",
    "No external bylines detected on bio page": "个人简介页未检测到外部署名",
    "Checking entity:": "正在检查实体：",
    "No Wikipedia page found for": "未找到相关 Wikipedia 页面：",
    "No Wikidata entity found for": "未找到相关 Wikidata 实体：",
    "Privacy policy found:": "隐私政策已找到：",
    "Terms of service found:": "服务条款已找到：",
    "Contact page found:": "联系页面已找到：",
    "Legal/DMCA/imprint page found:": "法律声明/DMCA/印记页面已找到：",
    "Partial business identity:": "部分企业身份信息：",
    "Content freshness signals found:": "内容时效性信号已找到：",
    "Healthy sitewide update cadence": "全站更新频率良好",
    "Inconsistent site name across tags:": "各标签中站点名称不一致：",
    "Machine-readable endpoint found:": "机器可读端点已找到：",
    "Twitter/X card tags found:": "Twitter/X Card 标签已找到：",
    "sameAs social links in JSON-LD": "JSON-LD 中的 sameAs 社交链接",
    "definition-style sentence(s) found — highly citable by AI": "个定义式语句 —— AI 引用度极高",
    "No comparison tables — consider adding tables for feature comparisons, pricing, etc.": "未找到对比表格 —— 建议添加功能对比、价格对比等表格",
    "Step-by-step instructional content detected — great for 'how to' AI answers": "检测到分步教程内容 —— 非常适合 AI 的「怎么做」类回答",
    "Pros/cons or advantages/disadvantages content detected": "检测到优缺点/利弊分析内容",
    "Summary/key takeaways section found — AI engines prefer concise summaries": "找到摘要/关键要点部分 —— AI 引擎偏好简洁的总结",
    "question-pattern heading(s) — add more for chat-style queries": "个问句式标题 —— 建议增加更多以适配对话式查询",
    "AI answer format score:": "AI 回答格式评分：",
    "No breadcrumb navigation or schema found": "未找到面包屑导航或 Schema",
    "Organization/Business schema found:": "Organization/Business Schema 已找到：",
    "Organization name: present": "组织名称：已填写",
    "Website URL: present": "网站 URL：已填写",
    "Logo image: present": "Logo 图片：已填写",
    "Description: present": "描述：已填写",
    "Optional fields present:": "可选字段已填写：",
    "Optional fields missing:": "可选字段缺失：",
    "Viewport meta tag found:": "Viewport meta 标签已找到：",
    "Uses width=device-width (responsive)": "使用 width=device-width（响应式）",
    "HTML page weight:": "HTML 页面体积：",
    "Inline resources within acceptable range": "内联资源在可接受范围内",
    "Cache headers found:": "缓存头已找到：",
    "Both trailing slash and non-trailing slash return 200 — ensure canonical is set": "带尾斜杠和不带尾斜杠均返回 200 —— 请确保设置 canonical",
    "serve content — duplicate content risk": "均提供内容 —— 存在重复内容风险",
    "URL case handling is consistent": "URL 大小写处理一致",
    "outbound link(s) to": "个外链指向",
    "unique domain(s)": "个独立域名",
    "Links to authoritative sources:": "指向权威来源的链接：",
    "No video content detected": "未检测到视频内容",
    "Multi-format coverage:": "多格式覆盖：",
    "non-text format(s) detected — more formats = more AI surface area": "种非文本格式 —— 格式越多，AI 可见面越广",
    "No tables found on homepage": "首页未找到表格",
    "First paragraph": "首段",
    "lacks extractable facts — add a definition or key statistic up front": "缺少可提取的事实 —— 建议在开头添加定义或关键数据",
    "No hreflang tags — skipping multilingual check": "无 hreflang 标签 —— 跳过多语言检查",
    "linked on site:": "在站内被链接：",
    "not detected": "未检测到",
    "Limited cross-platform presence:": "跨平台覆盖有限：",
    "Platforms where your brand is visible to AI training:": "您的品牌在以下平台对 AI 训练可见：",
    "trains:": "训练数据来源：",
    "Sampling": "正在抽样",
    "internal page(s)...": "个内部页面……",
    "Low word count (<100 words) on": "低字数（<100 词）的页面共",
    "Duplicate meta descriptions found across pages:": "多个页面存在重复的 meta 描述：",
    "Duplicate <title> tags found across pages:": "多个页面存在重复的 <title> 标签：",
    "All sampled pages maintain consistent GEO standards": "所有抽样页面均保持一致的 GEO 标准",
    "No internal pages to sample": "无内部页面可供抽样",

    # ── Content gap suggestions ──
    "Create a FAQ page with FAQPage schema answering top questions about your product/service": "创建 FAQ 页面并使用 FAQPage Schema，解答关于您产品/服务的常见问题",
    "Add HowTo schema to tutorial or setup guide pages": "在教程或安装指南页面添加 HowTo Schema",
    "Use Product schema with reviews, pricing, and availability on product pages": "在产品页面使用 Product Schema，包含评价、价格和库存信息",
    "Write long-form pillar content (2000+ words) covering your core topic comprehensively": "撰写 2000 字以上的长篇支柱内容，全面覆盖核心主题",
    "Add an 'Industry Statistics' page with original data — AI engines heavily cite pages with numbers": "添加「行业数据」页面并提供原创数据 —— AI 引擎大量引用含数据的页面",
    "Create comparison articles ('X vs Y') — these match competitive queries AI users ask": "创建对比文章（X vs Y）—— 匹配 AI 用户常见的竞品对比查询",
    "Add a 'What is [your product]?' section with a clear 1-2 sentence definition": "添加「什么是[您的产品]？」部分，提供简明的一两句话定义",
    "Structure blog posts as Q&A: use question headings followed by direct answers": "将博客文章结构化为问答形式：使用问句标题，紧跟直接回答",
    "Add 'Key Takeaways' or 'TL;DR' sections — AI engines extract these as summaries": "添加「关键要点」或「TL;DR」部分 —— AI 引擎会将其提取为摘要",
    "Write meta descriptions as self-contained answers (80-160 chars) — AI uses these as fallback snippets": "将 meta 描述写成独立完整的回答（80-160 字符）—— AI 会将其作为备选摘要",
    "Add Open Graph tags so AI engines can extract your preferred title and description": "添加 Open Graph 标签，以便 AI 引擎提取您偏好的标题和描述",
    "Reduce JavaScript dependency — AI crawlers can't execute JS; ensure content is in raw HTML": "减少 JavaScript 依赖 —— AI 爬虫无法执行 JS，请确保内容在原始 HTML 中可见",
    "Add alt text to all images describing what they show — AI uses this for context": "为所有图片添加描述性 alt 文本 —— AI 利用 alt 文本理解图片内容",
    "Create or improve your Wikipedia page — AI engines use Wikipedia as a primary knowledge source": "创建或完善您的 Wikipedia 页面 —— AI 引擎将 Wikipedia 作为主要知识来源",
    "Claim and complete your Google Business Profile, Crunchbase, and LinkedIn company pages": "认领并完善您的 Google 商家资料、Crunchbase 和 LinkedIn 公司页面",
    "Get featured on industry-specific directories and 'best of' lists": "争取出现在行业垂直目录和「精选推荐」榜单中",
    "Add author bios with credentials and links to external profiles (LinkedIn, Twitter)": "添加作者简介，包含资质信息及外部个人主页链接（LinkedIn、Twitter）",
    "Publish guest posts on authoritative sites in your industry with backlinks": "在行业权威网站发布嘉宾文章并附带反向链接",
    "Add an 'About Us' page with team expertise, founding story, and mission statement": "添加「关于我们」页面，包含团队专长、创业故事和使命宣言",
    "Add clearly linked Privacy Policy, Terms of Service, and Contact pages": "添加清晰链接的隐私政策、服务条款和联系方式页面",
    "Display business identity: address, phone, registration number where applicable": "展示企业身份信息：地址、电话、工商注册号等（如适用）",
    "Link to active social media profiles from your site (header or footer)": "在网站页头或页脚链接到活跃的社交媒体主页",
    "Publish regularly on LinkedIn, Twitter/X — AI engines cross-reference social presence": "定期在 LinkedIn、Twitter/X 上发布内容 —— AI 引擎会交叉核实社交媒体存在",
    "Create /llms.txt describing your site's purpose and content for AI crawlers": "创建 /llms.txt，向 AI 爬虫描述您网站的用途和内容",
    "Add /llms-full.txt with comprehensive site documentation for deeper AI indexing": "添加 /llms-full.txt，提供完整的站点文档以促进 AI 深度索引",
    "Create a robots.txt that explicitly allows AI crawler access": "创建 robots.txt 并明确允许 AI 爬虫访问",
    "Add an ai.txt or .well-known/ai.txt to declare your AI data usage preferences": "添加 ai.txt 或 .well-known/ai.txt 以声明您的 AI 数据使用偏好",
    "Ensure each page has a unique title and meta description — duplicate content confuses AI": "确保每个页面都有唯一的标题和 meta 描述 —— 重复内容会干扰 AI 判断",
    "Diversify content across pages; avoid repeating the same paragraphs on multiple URLs": "在各页面差异化内容，避免多个 URL 出现相同段落",
    "Link to authoritative external sources — AI engines trust pages that cite credible references": "链接到权威的外部来源 —— AI 引擎信任引用可靠参考资料的页面",
    "Embed diverse media (images, videos, infographics) — richer content gets cited more": "嵌入多样化媒体（图片、视频、信息图）—— 内容越丰富，被引用越多",

    # ── Fix recommendations ──
    "Install an SSL/TLS certificate (free via Let's Encrypt) and redirect all HTTP traffic to HTTPS.": "安装 SSL/TLS 证书（可通过 Let's Encrypt 免费获取），并将所有 HTTP 流量重定向到 HTTPS。",
    "Create a robots.txt file at your site root.": "在网站根目录创建 robots.txt 文件。",
    "Ensure at least one common AI bot is not blocked by robots.txt.": "确保 robots.txt 未屏蔽至少一个常见的 AI 爬虫。",
    "Add your sitemap URL to robots.txt:": "将站点地图 URL 添加到 robots.txt：",
    "Add a Sitemap reference in robots.txt so AI crawlers find it immediately:": "在 robots.txt 中添加 Sitemap 引用，以便 AI 爬虫能立即找到它：",
    "Create and submit a sitemap.xml": "创建并提交 sitemap.xml",
    "Register with Google Search Console": "注册 Google Search Console",
    "Register with Bing Webmaster Tools": "注册 Bing Webmaster Tools",
    "Add structured data to help AI engines understand your content.": "添加结构化数据，帮助 AI 引擎理解您的内容。",
    "Add a meta description tag.": "添加 meta description 标签。",
    "Set a canonical URL.": "设置 canonical URL。",
    "Add Open Graph meta tags.": "添加 Open Graph meta 标签。",
    "Add alt text to images.": "为图片添加 alt 文本。",
    "Move inline CSS to external stylesheets": "将内联 CSS 移至外部样式表",
    "Move inline JS to external scripts with defer/async": "将内联 JS 移至外部脚本并使用 defer/async 加载",
    "Remove unused HTML/comments": "移除无用的 HTML 代码和注释",
    "Enable server-side compression (gzip/brotli)": "启用服务器端压缩（gzip/brotli）",
    "Reduce page weight:": "减小页面体积：",
    "Simplify content: shorter sentences, plain language, bullet points, active voice.": "简化内容：使用更短的句子、通俗的语言、项目符号列表和主动语态。",
    "Add source attributions to increase credibility:": "添加来源引用以提高可信度：",
    "Add comparison tables where applicable (pricing, features, vs. competitors):": "在适当位置添加对比表格（定价、功能、竞品比较）：",
    "AI engines frequently cite tabular data in comparison answers.": "AI 引擎在生成对比类回答时经常引用表格数据。",
    "Add more question-pattern headings that match how people prompt AI engines:": "添加更多与用户向 AI 引擎提问方式匹配的疑问句式标题：",
    "Follow each with a short, direct answer so AI engines can extract it.": "在每个问题标题后紧跟一个简短、直接的回答，以便 AI 引擎提取。",
    "Add breadcrumb navigation to help AI engines understand your site structure:": "添加面包屑导航，帮助 AI 引擎理解您的网站结构：",
    "Add more fields to strengthen knowledge panel eligibility:": "补充更多字段以增强知识面板的收录资格：",
    "Organize your llms.txt with sections like:": "按以下分区组织您的 llms.txt：",
    "Front-load facts into your first paragraph so AI engines can extract it directly:": "将关键事实前置到第一段，以便 AI 引擎直接提取：",
    "Aim for one definition-style sentence and one concrete stat in the first 25-120 words.": "力求在前 25–120 个词中包含一个定义式语句和一个具体数据。",
    "Write unique meta descriptions for each page. Duplicate descriptions": "为每个页面撰写独特的 meta description。重复的描述",
    "confuse AI engines about which page to cite for a given topic.": "会让 AI 引擎无法判断针对某一主题应引用哪个页面。",
    "Write unique <title> tags for each page. Identical titles cause keyword": "为每个页面撰写独特的 <title> 标签。相同的标题会导致关键词",
    "cannibalization — AI engines can't tell which page to cite for a given query.": "自相蚕食——AI 引擎无法判断针对某一查询应引用哪个页面。",
    "Pages with <100 words have too little content for AI engines. Add substantive, unique text.": "少于 100 词的页面内容过少，不利于 AI 引擎引用。请添加有实质内容的独特文本。",
    "Content overlap / possible cannibalization between pages:": "页面之间存在内容重叠/可能的关键词自相蚕食：",
    "Consolidate into one canonical page and 301-redirect the others.": "合并为一个权威页面，并将其他页面进行 301 重定向。",
    "Differentiate each page with distinct angles, examples, and keywords.": "通过不同的角度、案例和关键词来区分各个页面。",
    "Use rel=canonical to point near-duplicates to the primary page.": "使用 rel=canonical 将近似重复页面指向主页面。",
    "Cannibalization dilutes your AI visibility — pick the strongest page to surface.": "关键词自相蚕食会稀释您的 AI 可见度——选择最有优势的页面来展示。",
    "A Wikipedia page is one of the strongest entity signals for AI engines.": "维基百科页面是 AI 引擎识别实体的最强信号之一。",
    "Wikidata is free to edit and AI engines (especially Google Knowledge Graph) ingest it": "Wikidata 可免费编辑，且 AI 引擎（尤其是 Google Knowledge Graph）会主动采集其数据",
    "Mark up key terms and abbreviations:": "标注关键术语和缩写：",
    "This helps AI engines understand and define terms in your content.": "这有助于 AI 引擎理解和定义您内容中的术语。",
    "Diversify your content formats so AI engines encounter you in more contexts:": "丰富您的内容形式，让 AI 引擎在更多场景中接触到您：",
    "Set up a 301 redirect so one version redirects to the other:": "设置 301 重定向，将其中一个版本跳转到另一个版本：",
    "Then set the canonical URL to match the preferred version.": "然后将 canonical URL 设置为首选版本。",
    "Expand your brand presence on platforms that AI models train on:": "在 AI 模型训练所用的平台上扩展您的品牌影响力：",
    "Being present increases the probability of your brand being cited in AI answers,": "在这些平台上建立存在感，可以提高您的品牌在 AI 回答中被引用的概率，",
    "regardless of which source the AI pulls from.": "无论 AI 最终从哪个来源提取信息。",
    "Add missing trust signals so AI engines can verify who is behind the site:": "补充缺失的信任信号，以便 AI 引擎验证网站的运营主体：",
    "Use the same brand name everywhere.": "在所有平台上使用统一的品牌名称。",
    "No AI API keys found. Set at least one:": "未找到 AI API 密钥。请至少设置一个：",
    "This is a paid feature requiring AI API access.": "此为付费功能，需要 AI API 访问权限。",
    "Tip: Set an AI API key to see Citation Share analysis": "提示：设置 AI API 密钥即可查看引用份额分析",
    "see recommendations above": "请参阅上方建议",

    # ══════════════════════════════════════════════════════════
    # --ai-visibility mode
    # ══════════════════════════════════════════════════════════
    "AI VISIBILITY AUDIT v2": "AI 可见度审计 v2",
    "AI VISIBILITY AUDIT — RESULTS": "AI 可见度审计 — 结果",
    "Entity Definition": "实体定义",
    "Gap Detection": "缺口检测",
    "Total queries:": "查询总数：",
    "engine(s) x 3 runs =": "个引擎 x 3 次运行 =",
    "API calls": "次 API 调用",
    "Estimated time:": "预计耗时：",
    "Engine:": "引擎：",
    "All runs failed": "所有运行均失败",
    "STABLE — cited in": "稳定 — 被引用于",
    "UNSTABLE — cited in": "不稳定 — 被引用于",
    "runs": "次运行",
    "NOT CITED in any run": "在所有运行中均未被引用",
    "Framing:": "定位：",
    "Invalid": "无效",
    "API key. Skipping this engine.": "API 密钥。跳过此引擎。",
    "--- 1. Prompt Visibility ---": "--- 1. 提示词可见性 ---",
    "queries cited": "个查询被引用",
    "--- 2. Entity Clarity ---": "--- 2. 实体清晰度 ---",
    "Found": "找到",
    "definition(s) across engines:": "个跨引擎定义：",
    "No clear definitions found in AI answers": "AI 回答中未找到明确定义",
    "Possible brand confusion: AI describes": "可能存在品牌混淆：AI 将",
    "as a '": "描述为 '",
    "No brand confusion detected": "未检测到品牌混淆",
    "Entity Clarity:": "实体清晰度：",
    "--- 3. Competitor Position ---": "--- 3. 竞争定位 ---",
    "Top competitors mentioned alongside queries:": "查询中同时提及的主要竞争对手：",
    "mention(s)": "次提及",
    "Brand framing across all answers:": "所有回答中的品牌定位分析：",
    "Recommended (strongest)": "推荐（最强）",
    "Leader/major player": "领导者/主要参与者",
    "One of several options": "多个选项之一",
    "Passively mentioned": "被动提及",
    "Niche/experimental": "小众/实验性",
    "Not mentioned": "未被提及",
    "Competitor Position:": "竞争定位：",
    "--- 4. Answer Stability ---": "--- 4. 回答稳定性 ---",
    "Stable (all runs cited):": "稳定（所有运行均引用）：",
    "Unstable (some runs):": "不稳定（部分运行引用）：",
    "Absent (never cited):": "缺失（从未引用）：",
    "Answer Stability:": "回答稳定性：",
    "--- 5. Content Gaps ---": "--- 5. 内容缺口 ---",
    "content gap(s) detected:": "个内容缺口已检测到：",
    "Recommended actions to fill gaps:": "填补缺口的建议操作：",
    "Create dedicated pages for topics where": "为以下主题创建专门页面，其中",
    "is not cited": "未被引用",
    "Add FAQ sections answering these exact queries on your site": "在您的网站上添加 FAQ 栏目，回答这些具体问题",
    "Write comparison pages": "撰写对比页面",
    "for competitive queries": "用于竞争性查询",
    "Publish content on third-party platforms (blog posts, Reddit, GitHub)": "在第三方平台发布内容（博客文章、Reddit、GitHub）",
    "No major content gaps detected!": "未检测到重大内容缺口！",
    "Content Gap:": "内容缺口：",
    "Prompt Visibility": "提示词可见性",
    "Competitor Position": "竞争定位",
    "Answer Stability": "回答稳定性",
    "A — AI engines actively recommend this brand": "A — AI 引擎主动推荐该品牌",
    "B — Good visibility, some gaps to fill": "B — 可见性良好，存在部分缺口待填补",
    "C — Moderate visibility, significant gaps": "C — 可见性一般，存在较大缺口",
    "D — Low visibility, major work needed": "D — 可见性低，需要大量优化工作",
    "F — Not visible to AI engines": "F — 对 AI 引擎不可见",
    "Run periodically to track improvements over time.": "建议定期运行以跟踪改进情况。",
    "Tip: Use --queries to test your specific category prompts.": "提示：使用 --queries 测试您自定义的品类提示词。",

    # ══════════════════════════════════════════════════════════
    # --entity mode
    # ══════════════════════════════════════════════════════════
    "OPENAI_API_KEY environment variable not set.": "未设置 OPENAI_API_KEY 环境变量。",
    "This feature requires an OpenAI API key.": "此功能需要 OpenAI API key。",
    "ENTITY GEO AUDIT": "实体 GEO 审计",
    "Engine: OpenAI GPT-4o-mini (web search)": "引擎：OpenAI GPT-4o-mini（网络搜索）",
    "Phase 1: Knowledge Graph & Platform checks...": "阶段 1：知识图谱与平台检查……",
    "Phase 2: AI engine queries...": "阶段 2：AI 引擎查询……",
    "Analysis complete. Scoring...": "分析完成。正在评分……",
    "Knowledge Graph: Found on": "知识图谱：已在以下平台找到",
    "Knowledge Graph: Not found on Wikipedia or Wikidata": "知识图谱：未在 Wikipedia 或 Wikidata 上找到",
    "ENTITY GEO SCORECARD": "实体 GEO 评分卡",
    "Entity Recognition": "实体识别",
    "Category Association": "类别关联度",
    "Competitive Position": "竞争地位",
    "Sentiment & Framing": "情感与定位",
    "Knowledge Graph": "知识图谱",
    "Platform Footprint": "平台覆盖",
    "ENTITY GEO SCORE": "实体 GEO 总分",
    "Content Gap": "内容缺口",
    "Entity Clarity": "实体清晰度",
    "KEY FINDINGS": "主要发现",
    "Strong Knowledge Graph presence": "知识图谱覆盖良好",
    "Partial Knowledge Graph presence": "知识图谱覆盖部分",
    "Not found in Knowledge Graph (Wikipedia, Wikidata)": "未在知识图谱中找到（Wikipedia、Wikidata）",
    "Strong platform footprint": "平台覆盖良好",
    "Moderate platform footprint": "平台覆盖一般",
    "Weak platform footprint": "平台覆盖薄弱",
    "AI consistently recognizes": "AI 始终能识别",
    "AI partially recognizes": "AI 部分识别",
    "— inconsistent across queries": "—— 不同查询间结果不一致",
    "AI does not reliably recognize": "AI 无法可靠识别",
    "Entity definition is clear and consistent across runs": "实体定义清晰，各次查询结果一致",
    "Entity definition varies between queries — may indicate ambiguity": "实体定义在不同查询间有差异 —— 可能存在歧义",
    "Entity definition is unclear or confused with other entities": "实体定义不清晰或与其他实体混淆",
    "Strong category/domain association detected": "检测到强类别/领域关联",
    "Weak category association — AI may not map entity to its core domain": "类别关联较弱 —— AI 可能无法将实体映射到核心领域",
    "AI does not clearly associate entity with a specific category": "AI 未将实体与特定类别清晰关联",
    "Mentioned among top experts/leaders in field": "在领域顶级专家/领袖中被提及",
    "Mentioned but not prominently positioned among peers": "被提及但在同行中位置不突出",
    "Not mentioned among leaders in field": "未在领域领袖中被提及",
    "Competitive framing:": "竞争定位：",
    "Overall AI sentiment:": "AI 整体情感倾向：",
    "AI uses recommendation language": "AI 使用推荐性语言",
    "strongly positive": "强烈正面",
    "positive": "正面",
    "neutral": "中性",
    "negative": "负面",
    "mixed": "褒贬不一",
    "CONTENT GAPS (entity not mentioned for these queries)": "内容缺口（以下查询中未提及该实体）",
    "No content gaps detected — entity appears across all tested queries": "未检测到内容缺口 —— 实体出现在所有测试查询中",
    "Create content targeting these gap queries:": "创建针对这些缺口查询的内容：",

    # ══════════════════════════════════════════════════════════
    # --authority-audit mode
    # ══════════════════════════════════════════════════════════
    "Authority & Reputation Audit": "权威性与声誉审计",
    "1. Online Reviews": "1. 在线评价",
    "— profile found": "—— 已找到资料页",
    "— possible profile found": "—— 可能找到资料页",
    "— no profile detected": "—— 未检测到资料页",
    "— could not check (timeout/blocked)": "—— 无法检查（超时/被阻止）",
    "Review/Rating structured data found on site": "站点上发现评价/评分结构化数据",
    "review page from site": "评价页面（来自站点）",
    "Review presence: STRONG": "评价覆盖：强",
    "Review presence: MODERATE": "评价覆盖：中等",
    "No review presence detected on major platforms": "在主要平台上未检测到评价信息",
    "2. Awards, Accreditations & Affiliations": "2. 奖项、资质认证与合作关系",
    "Award/accreditation signals found in content:": "在内容中发现奖项/资质认证信号：",
    "No award/accreditation keywords detected in homepage content": "首页内容中未检测到奖项/资质认证关键词",
    "Award/certification structured data found": "发现奖项/认证结构化数据",
    "No award-specific schema markup": "无奖项专用 Schema 标记",
    "Trust/certification badge images found": "发现信任/认证徽章图片",
    "No trust badge images detected": "未检测到信任徽章图片",
    "Awards/accreditations: STRONG": "奖项/资质认证：强",
    "Awards/accreditations: MODERATE": "奖项/资质认证：中等",
    "Awards/accreditations: WEAK": "奖项/资质认证：弱",
    "3. Google Website Authority": "3. Google 网站权威性",
    "Checking Google index presence...": "正在检查 Google 索引情况……",
    "Google indexed pages:": "Google 已索引页面数：",
    "Domain not indexed by Google": "该域名未被 Google 索引",
    "Checking Knowledge Panel readiness...": "正在检查知识面板就绪度……",
    "Organization schema:": "Organization Schema：",
    "No Wikipedia/Wikidata links — consider creating entries for brand recognition": "无 Wikipedia/Wikidata 链接——建议创建条目以提升品牌辨识度",
    "Google authority signals: STRONG": "Google 权威性信号：强",
    "Google authority signals: MODERATE": "Google 权威性信号：中等",
    "Google authority signals: WEAK": "Google 权威性信号：弱",
    "4. Authoritative List Mentions": "4. 权威榜单提及",
    "— no mentions": "—— 无提及",
    "— package found:": "—— 已找到软件包：",
    "— not found": "—— 未找到",
    "— could not check": "—— 无法检查",
    "— company page found": "—— 已找到公司页面",
    "— not detected (may require login)": "—— 未检测到（可能需要登录）",
    "repo(s) found, top:": "个仓库，排名第一：",
    "— found": "—— 已找到",
    "— no profile found": "—— 未找到资料页",
    "authoritative domain(s) (.gov/.edu/.org)": "个权威域名（.gov/.edu/.org）",
    "Authoritative mentions: STRONG": "权威提及：强",
    "Authoritative mentions: MODERATE": "权威提及：中等",
    "Authoritative mentions: WEAK": "权威提及：弱",
    "Authority Score:": "权威性评分：",
    "A — Excellent": "A — 优秀",
    "B — Good": "B — 良好",
    "C — Needs improvement": "C — 有待改进",
    "D — Weak": "D — 薄弱",
    "F — Critical gaps": "F — 存在严重缺陷",
    "Breakdown:": "明细：",
    "Online Reviews:": "在线评价：",
    "Awards/Accreditations:": "奖项/资质认证：",
    "Google Authority:": "Google 权威性：",
    "Authoritative Mentions:": "权威提及：",

    # ══════════════════════════════════════════════════════════
    # --crawl-check / --crawl-test mode
    # ══════════════════════════════════════════════════════════
    "AI/LLM Crawl Activity Report": "AI/LLM 抓取活动报告",
    "No log files matched:": "未匹配到日志文件：",
    "Files matched:": "匹配文件：",
    "MB total": "MB（合计）",
    "Log period:": "日志时段：",
    "Total lines:": "总行数：",
    "Parsed:": "已解析：",
    "AI/LLM bot requests:": "AI/LLM 爬虫请求数：",
    "No AI/LLM crawler activity detected in this log file.": "在此日志文件中未检测到 AI/LLM 爬虫活动。",
    "This could mean:": "这可能意味着：",
    "AI bots haven't discovered your site yet": "AI 爬虫尚未发现您的站点",
    "The log file doesn't cover enough time": "日志文件覆盖的时间段不够长",
    "Bots are blocked by robots.txt or firewall": "爬虫被 robots.txt 或防火墙阻止",
    "Your CDN/proxy strips bot user agents": "您的 CDN/代理剥离了爬虫 User-Agent",
    "Bot Activity Breakdown": "爬虫活动明细",
    "Critical Bots NOT Detected": "关键爬虫未检测到",
    "Optional Bots NOT Detected": "可选爬虫未检测到",
    "bot(s)": "个爬虫",
    "Not seen:": "未检测到：",
    "AI Crawl Accessibility Test": "AI 抓取可访问性测试",
    "robots.txt Rules for AI Bots": "AI 爬虫的 robots.txt 规则",
    "robots.txt not found — all bots allowed by default": "robots.txt 未找到——默认允许所有爬虫",
    "— BLOCKED by robots.txt": "—— 被 robots.txt 阻止",
    "— allowed": "—— 已允许",
    "Simulated Bot Access Test": "模拟爬虫访问测试",
    "Sending requests to": "正在发送请求到",
    "with AI bot user agents...": "使用 AI 爬虫 User-Agent……",
    "(Checks if your server/CDN/WAF blocks bot traffic)": "（检查您的服务器/CDN/WAF 是否阻止爬虫流量）",
    "Baseline (browser):": "基准（浏览器）：",
    "— BLOCKED by server/WAF": "—— 被服务器/WAF 阻止",
    "suspiciously small vs baseline": "与基准相比可疑地小",
    "request failed:": "请求失败：",
    "All tested bots can access your site successfully.": "所有测试的爬虫均可成功访问您的站点。",
    "Common Crawl Index Check": "Common Crawl 索引检查",
    "page(s) in Common Crawl index": "个页面在 Common Crawl 索引中",
    "Domain not found in Common Crawl index": "在 Common Crawl 索引中未找到该域名",
    "Could not reach Common Crawl index — their servers may be slow, try again later": "无法连接 Common Crawl 索引——其服务器可能较慢，请稍后重试",
    "Your site appears accessible to all major AI crawlers.": "您的站点对所有主要 AI 爬虫均可访问。",
    "Issues found:": "发现的问题：",
    "bot(s) blocked by robots.txt,": "个爬虫被 robots.txt 阻止，",
    "bot(s) blocked by server/WAF": "个爬虫被服务器/WAF 阻止",

    # AI_CRAWLERS powers values
    "ChatGPT training data": "ChatGPT 训练数据",
    "ChatGPT live browsing": "ChatGPT 实时浏览",
    "Claude training data": "Claude 训练数据",
    "Anthropic crawling": "Anthropic 爬取",
    "Perplexity AI answers": "Perplexity AI 回答",
    "Google AI training": "Google AI 训练",
    "Bing link preview (Teams/Outlook)": "Bing 链接预览（Teams/Outlook）",
    "Common Crawl (used by many LLMs)": "Common Crawl（被众多 LLM 使用）",
    "Knowledge graph extraction": "知识图谱提取",
    "Apple Intelligence / Siri": "Apple Intelligence / Siri",
    "Apple search / Siri": "Apple 搜索 / Siri",
    "Cohere models": "Cohere 模型",
    "You.com AI search": "You.com AI 搜索",
    "SEO analytics (AI-adjacent)": "SEO 分析（AI 相关）",

    # ══════════════════════════════════════════════════════════
    # --citation-check mode
    # ══════════════════════════════════════════════════════════
    "PERPLEXITY_API_KEY environment variable not set.": "PERPLEXITY_API_KEY 环境变量未设置。",
    "This is a paid feature. Set your API key to use it:": "这是一项付费功能。请设置 API 密钥后使用：",
    "AI Citation Check (Powered by Perplexity)": "AI 引用检查（由 Perplexity 驱动）",
    "Sending brand-relevant queries to Perplexity AI...": "正在向 Perplexity AI 发送品牌相关查询……",
    "appears in AI-generated citations...": "是否出现在 AI 生成的引用中……",
    "Invalid API key. Check your PERPLEXITY_API_KEY.": "API 密钥无效。请检查 PERPLEXITY_API_KEY。",
    "Rate limited. Waiting before next query...": "已被限流。正在等待后重试……",
    "CITED!": "被引用！",
    "citation(s) from": "条引用来自",
    "MENTIONED in answer (no direct citation link)": "在回答中被提及（无直接引用链接）",
    "Not cited.": "未被引用。",
    "other source(s) cited instead.": "个其他来源被引用。",
    "AI CITATION REPORT": "AI 引用报告",
    "No queries completed successfully.": "无查询成功完成。",
    "Citation Rate:": "引用率：",
    "Direct Links:": "直接链接：",
    "citation(s) pointing to": "条引用指向",
    "A — Excellent AI visibility": "A — AI 可见度优秀",
    "B — Good AI visibility": "B — AI 可见度良好",
    "C — Moderate AI visibility": "C — AI 可见度中等",
    "D — Low AI visibility": "D — AI 可见度偏低",
    "F — Not visible to AI engines": "F — 对 AI 引擎不可见",
    "AI Visibility:": "AI 可见度：",
    "Query Results:": "查询结果：",
    "CITED": "已引用",
    "NOT CITED": "未引用",
    "Recommendations to improve AI citation rate:": "提高 AI 引用率的建议：",
    "Ensure your site has comprehensive, authoritative content about your brand": "确保您的站点拥有关于品牌的全面、权威内容",
    "Add structured data (JSON-LD) with Organization schema": "添加包含 Organization Schema 的结构化数据（JSON-LD）",
    "Create an llms.txt file to help AI engines understand your site": "创建 llms.txt 文件以帮助 AI 引擎了解您的站点",
    "Build presence on platforms AI models reference (Wikipedia, Reddit, GitHub)": "在 AI 模型引用的平台上建立影响力（Wikipedia、Reddit、GitHub）",
    "Publish original research, data, and expert content that AI engines want to cite": "发布 AI 引擎乐于引用的原创研究、数据和专家内容",
    "Ensure AI crawlers (GPTBot, ClaudeBot, PerplexityBot) are not blocked in robots.txt": "确保 robots.txt 未屏蔽 AI 爬虫（GPTBot、ClaudeBot、PerplexityBot）",
    "Results reflect Perplexity AI's current knowledge. Other AI engines": "结果反映 Perplexity AI 当前的知识。其他 AI 引擎",
    "(ChatGPT, Gemini, Claude) may differ. Run periodically to track changes.": "（ChatGPT、Gemini、Claude）的结果可能不同。建议定期运行以跟踪变化。",
})
