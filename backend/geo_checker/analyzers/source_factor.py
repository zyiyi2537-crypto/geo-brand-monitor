"""GEO 推荐因子分类(FirstPageSage 口径).

把一条被引用的信源(url + 标题)归到它代表的 GEO 排名因子:
list_mention / reviews / directory / awards / customer / social / authority / other.

跟 source_classify(内容类型:新闻/社交/视频…)不同 —— 因子要看引用的标题/URL,
同一媒体站一篇"2026 最佳CRM"榜单算「权威榜单提及」,普通报道就不是。

参考:FirstPageSage GEO recommendation algorithm 拆解。
"""

from __future__ import annotations

from urllib.parse import urlparse

# ── 域名集合(按域名直接判定的因子)──
_REVIEW_DOMAINS: set[str] = {
    "g2.com", "trustpilot.com", "capterra.com", "trustradius.com",
    "getapp.com", "softwareadvice.com", "yelp.com", "glassdoor.com",
    "sitejabber.com", "productreview.com.au", "dianping.com",  # 大众点评
}
_DIRECTORY_DOMAINS: set[str] = {
    "crunchbase.com", "clutch.co", "goodfirms.co", "bbb.org", "dnb.com",
    "manta.com", "yellowpages.com", "yelp.com",  # yelp 同时是评价,评价优先(下面顺序保证)
    "tianyancha.com", "qcc.com", "aiqicha.baidu.com",  # 天眼查/企查查/爱企查
    "wellfound.com", "angel.co", "builtwith.com",
}
_SOCIAL_DOMAINS: set[str] = {
    "reddit.com", "x.com", "twitter.com", "linkedin.com", "facebook.com",
    "instagram.com", "weibo.com", "zhihu.com", "quora.com", "tiktok.com",
    "douyin.com", "xiaohongshu.com", "v2ex.com", "youtube.com", "bilibili.com",
    "medium.com", "substack.com",
}

# ── 关键词集合(在 标题 + URL path 里找)──
_LIST_KW: tuple[str, ...] = (
    "best ", "top ", "top10", "top 10", "leading", " vs ", "versus",
    "alternatives", "comparison", "compare", "roundup",
    "最佳", "十大", "排行", "排名", "榜", "盘点", "推荐", "选购", "对比",
)
_AWARD_KW: tuple[str, ...] = (
    "award", "winner", "accredit", "certified", "certification", "iso ",
    "recognized", "获奖", "奖项", "认证", "资质", "荣誉", "会员单位",
)
_CUSTOMER_KW: tuple[str, ...] = (
    "case study", "case-study", "case-studies", "success story", "usage data",
    "customers", "案例", "客户故事", "成功案例", "白皮书", "whitepaper",
)
_REVIEW_KW: tuple[str, ...] = (
    "review", "rating", "评价", "测评", "评测", "口碑", "评分",
)
_DIRECTORY_KW: tuple[str, ...] = (
    "directory", "listing", "目录", "名录", "黄页",
)


def _domain_hit(domain: str, domset: set[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in domset)


def classify_factor(url: str, title: str = "", domain: str = "", owned: bool = False) -> str:
    """把一条 citation 归到 GEO 因子.

    Args:
        url: citation URL.
        title: citation 标题(因子判定主要靠它).
        domain: 已抽好的域名(可选,缺省时从 url 解析).
        owned: 该域名是否命中品牌自有(命中且无其它信号 → authority).

    Returns:
        list_mention / reviews / directory / awards / customer / social /
        authority / other.
    """
    try:
        parsed = urlparse(url)
        dom = (domain or parsed.netloc).replace("www.", "").lower().strip()
        path = parsed.path.lower()
    except Exception:
        dom, path = (domain or "").lower(), ""

    text = f"{title or ''} {path}".lower()

    # 1) 域名直判(社交 / 评价 / 目录)—— 评价优先于目录(yelp 类双属性归评价)
    if _domain_hit(dom, _SOCIAL_DOMAINS):
        return "social"
    if _domain_hit(dom, _REVIEW_DOMAINS):
        return "reviews"
    if _domain_hit(dom, _DIRECTORY_DOMAINS):
        return "directory"

    # 2) 标题/URL 信号词(信号优先于 owned,保证榜单/案例/奖项页正确归因)
    if any(k in text for k in _AWARD_KW):
        return "awards"
    if any(k in text for k in _CUSTOMER_KW):
        return "customer"
    if any(k in text for k in _LIST_KW):
        return "list_mention"
    if any(k in text for k in _DIRECTORY_KW):
        return "directory"
    if any(k in text for k in _REVIEW_KW):
        return "reviews"

    # 3) 自有域名 → 网站权威
    if owned:
        return "authority"

    return "other"
