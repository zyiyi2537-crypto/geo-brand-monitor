"""Seed sentiment_platforms with the 67-platform catalog.

Idempotent. Inserts rows whose `code` is not yet in the table; pre-existing
rows are left untouched (admins may have edited them via the UI).

Usage (new deployment, after `alembic upgrade head`):
    cd backend && .venv/bin/python -m seeds.sentiment_platforms

Note: rows are seeded with empty media_type / industry (the `category` axis
that 011 split). Admins can refine them via the platform editor UI.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


SEED: list[tuple[str, str, str, str, str, str, int]] = [
    # (code, domain, category, region, name_zh, name_en, sort_order)
    # ── 财经媒体 (主力) ──
    ("xueqiu",       "xueqiu.com",          "finance",  "mainland", "雪球",         "Xueqiu",          10),
    ("eastmoney",    "guba.eastmoney.com",  "finance",  "mainland", "东方财富",     "Eastmoney",       20),
    ("caixin",       "caixin.com",          "finance",  "mainland", "财新",         "Caixin",          30),
    ("36kr",         "36kr.com",            "finance",  "mainland", "36氪",         "36Kr",            40),
    ("sina_finance", "finance.sina.com.cn", "finance",  "mainland", "新浪财经",     "Sina Finance",    50),
    ("qq_finance",   "finance.qq.com",      "finance",  "mainland", "腾讯财经",     "Tencent Finance", 60),
    ("163_finance",  "money.163.com",       "finance",  "mainland", "网易财经",     "NetEase Finance", 70),
    ("ths",          "10jqka.com.cn",       "finance",  "mainland", "同花顺",       "10jqka",          80),
    ("wallstreetcn", "wallstreetcn.com",    "finance",  "mainland", "华尔街见闻",   "Wallstreet CN",   90),
    ("yicai",        "yicai.com",           "finance",  "mainland", "第一财经",    "Yicai",           100),
    ("cls",          "cls.cn",              "finance",  "mainland", "财联社",      "CLS",             110),
    ("gelonghui",    "gelonghui.com",       "finance",  "hk",       "格隆汇",      "Gelonghui",       120),
    # ── 财经媒体 (扩展) ──
    ("jrj",          "jrj.com.cn",          "finance",  "mainland", "金融界",      "JRJ",             130),
    ("hexun",        "hexun.com",           "finance",  "mainland", "和讯",        "Hexun",           140),
    ("jin10",        "jin10.com",           "finance",  "mainland", "金十数据",    "Jin10",           150),
    ("nbd",          "nbd.com.cn",          "finance",  "mainland", "每日经济新闻", "NBD",            160),
    ("jingji21",     "21jingji.com",        "finance",  "mainland", "21世纪经济报道","21Jingji",      170),
    ("stcn",         "stcn.com",            "finance",  "mainland", "证券时报",    "STCN",            180),
    ("cs_com",       "cs.com.cn",           "finance",  "mainland", "中国证券报",  "CSRC News",       190),
    ("cnstock",      "cnstock.com",         "finance",  "mainland", "上海证券报",  "CN Stock",        200),
    ("p5w",          "p5w.net",             "finance",  "mainland", "全景网",      "P5W",             210),
    ("caijing",      "caijing.com.cn",      "finance",  "mainland", "财经杂志",    "Caijing",         220),
    ("iyiou",        "iyiou.com",           "finance",  "mainland", "亿欧",        "iyiou",           230),
    ("futunn",       "futunn.com",          "finance",  "mainland", "富途牛牛",    "Futu",            240),
    ("itiger",       "itiger.com",          "finance",  "mainland", "老虎证券",    "Tiger Brokers",   250),
    ("zhitong",      "zhitongcaijing.com",  "finance",  "hk",       "智通财经",    "Zhitong",         260),
    # ── 社交媒体 ──
    ("weibo",        "weibo.com",           "social",   "mainland", "微博",        "Weibo",            10),
    ("weixin",       "mp.weixin.qq.com",    "social",   "mainland", "微信公众号",  "WeChat MP",        20),
    ("xiaohongshu",  "xiaohongshu.com",     "social",   "mainland", "小红书",      "Xiaohongshu",      30),
    ("zhihu",        "zhihu.com",           "social",   "mainland", "知乎",        "Zhihu",            40),
    # ── 论坛社区 ──
    ("tieba",        "tieba.baidu.com",     "forum",    "mainland", "百度贴吧",    "Baidu Tieba",      10),
    ("zhidao",       "zhidao.baidu.com",    "forum",    "mainland", "百度知道",    "Baidu Zhidao",     20),
    ("hupu",         "hupu.com",            "forum",    "mainland", "虎扑",        "Hupu",             30),
    ("douban",       "douban.com",          "forum",    "mainland", "豆瓣",        "Douban",           40),
    ("v2ex",         "v2ex.com",            "forum",    "mainland", "V2EX",        "V2EX",             50),
    ("guokr",        "guokr.com",           "forum",    "mainland", "果壳",        "Guokr",            60),
    ("csdn",         "csdn.net",            "forum",    "mainland", "CSDN",        "CSDN",             70),
    ("juejin",       "juejin.cn",           "forum",    "mainland", "掘金",        "Juejin",           80),
    # ── 视频平台 ──
    ("bilibili",     "bilibili.com",        "video",    "mainland", "哔哩哔哩",    "Bilibili",         10),
    ("douyin",       "douyin.com",          "video",    "mainland", "抖音",        "Douyin",           20),
    ("kuaishou",     "kuaishou.com",        "video",    "mainland", "快手",        "Kuaishou",         30),
    ("toutiao",      "toutiao.com",         "video",    "mainland", "今日头条",    "Toutiao",          40),
    ("vqq",          "v.qq.com",            "video",    "mainland", "腾讯视频",    "Tencent Video",    50),
    ("iqiyi",        "iqiyi.com",           "video",    "mainland", "爱奇艺",      "iQIYI",            60),
    ("ixigua",       "ixigua.com",          "video",    "mainland", "西瓜视频",    "Ixigua",           70),
    # ── 资讯门户 (综合) ──
    ("baidu_news",   "news.baidu.com",      "news",     "mainland", "百度新闻",    "Baidu News",       10),
    ("ifeng",        "ifeng.com",           "news",     "mainland", "凤凰网",      "Ifeng",            20),
    ("sina_main",    "sina.com.cn",         "news",     "mainland", "新浪",        "Sina",             30),
    ("sohu",         "sohu.com",            "news",     "mainland", "搜狐",        "Sohu",             40),
    ("chinanews",    "chinanews.com",       "news",     "mainland", "中新网",      "China News",       50),
    ("xinhuanet",    "xinhuanet.com",       "news",     "mainland", "新华网",      "Xinhua Net",       60),
    ("people",       "people.com.cn",       "news",     "mainland", "人民网",      "People Daily",     70),
    ("huanqiu",      "huanqiu.com",         "news",     "mainland", "环球网",      "Huanqiu",          80),
    ("guancha",      "guancha.cn",          "news",     "mainland", "观察者网",    "Guancha",          90),
    ("ce_cn",        "ce.cn",               "news",     "mainland", "中国经济网",  "CE.cn",           100),
    ("thepaper",     "thepaper.cn",         "news",     "mainland", "澎湃新闻",    "The Paper",       110),
    ("jiemian",      "jiemian.com",         "news",     "mainland", "界面新闻",    "Jiemian",         120),
    ("huxiu",        "huxiu.com",           "news",     "mainland", "虎嗅",        "Huxiu",           130),
    ("tmtpost",      "tmtpost.com",         "news",     "mainland", "钛媒体",      "TMT Post",        140),
    ("pingwest",     "pingwest.com",        "news",     "mainland", "品玩",        "PingWest",        150),
    ("ifanr",        "ifanr.com",           "news",     "mainland", "爱范儿",      "iFanr",           160),
    ("qbitai",       "qbitai.com",          "news",     "mainland", "量子位",      "QbitAI",          170),
    ("jiqizhixin",   "jiqizhixin.com",      "news",     "mainland", "机器之心",    "Synced",          180),
    # ── 海外 ──
    ("reddit",       "reddit.com",          "overseas", "overseas", "Reddit",      "Reddit",           10),
    ("twitter",      "twitter.com",         "overseas", "overseas", "Twitter / X", "Twitter",          20),
    ("seekingalpha", "seekingalpha.com",    "overseas", "overseas", "Seeking Alpha","Seeking Alpha",   30),
    ("bloomberg",    "bloomberg.com",       "overseas", "overseas", "Bloomberg",   "Bloomberg",        40),
    ("reuters",      "reuters.com",         "overseas", "overseas", "Reuters",     "Reuters",          50),
]


def main() -> None:
    from geo.database import SessionLocal
    from geo.models.sentiment import SentimentPlatformORM
    from sqlalchemy import select

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = SessionLocal()
    try:
        existing_codes = set(db.execute(select(SentimentPlatformORM.code)).scalars().all())
        to_insert = [row for row in SEED if row[0] not in existing_codes]
        if not to_insert:
            print(f"[seed:sentiment_platforms] all {len(SEED)} codes already present — nothing to do")
            return

        for code, domain, category, region, name_zh, name_en, sort_order in to_insert:
            db.add(SentimentPlatformORM(
                code=code,
                domain=domain,
                category=category,
                region=region,
                name_zh=name_zh,
                name_en=name_en,
                sort_order=sort_order,
                media_type="",
                industry="",
                enabled=True,
                created_at=now,
                updated_at=now,
            ))
        db.commit()
        print(f"[seed:sentiment_platforms] inserted {len(to_insert)} rows ({len(existing_codes)} pre-existing left untouched)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
