"""Migration 010: media platform catalog table + seed.

把媒体平台目录从代码硬编码迁到 DB,新建表 + 插入 27 条种子数据。

之前的硬编码三处:
  - frontend/src/constants/sentimentPlatforms.ts
  - services/sentinel-service/search/plan.py PLATFORM_CATALOG
  - backend/geo/services/sentinel_client.py _PLATFORM_CODE_TO_DOMAIN

新增/调整平台只需要 INSERT/UPDATE 这张表 — 不再改代码、不重启 systemd。
后续若需要 admin UI 加平台,直接对此表 CRUD。

Idempotent:
  - 表已存在 → 跳过 CREATE
  - 表中已有该 code → 跳过 INSERT
  - 重跑只补缺失行,不覆盖已有

Usage:
    cd backend && python migrations/010_sentiment_platforms.py
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# (code, domain, category, region, name_zh, name_en, sort_order)
#
# 2026-05-08 v1: 27 条种子(基础财经/社交/论坛/视频/海外)
# 2026-05-08 v2: 扩到 68 条 — 主流财经媒体 + 综合门户 + 科技媒体 + 海外英文财经
#   动机:对标 WisersOne(57 万源)我们无法企及,但扩容目录后 LLM 生成 site: 查询
#   有更多落点,且结果 URL 过滤器(filter_queries_by_media)放行更多域名 — 之前
#   bing/baidu 返回的 sina/sohu/chinanews/people/csdn/虎嗅/钛媒等结果会被白名单
#   过滤掉,扩容后可入库。
SEED: list[tuple[str, str, str, str, str, str, int]] = [
    # ── 财经媒体(主力)──
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
    # ── 财经媒体(扩展)──
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
    # ── 资讯门户(综合)──
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


def main():
    from geo.database import settings

    db_url = settings.DATABASE_URL
    if not db_url.startswith("sqlite:///"):
        print(f"[migrate] non-sqlite URL detected ({db_url}) — aborting")
        return

    db_path_str = db_url.replace("sqlite:///", "", 1)
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = BACKEND_DIR / db_path
    if not db_path.exists():
        print(f"[migrate] {db_path} does not exist yet — Base.metadata.create_all will build the table on next backend start; rerun this script after that to seed.")
        return

    import sqlite3
    from datetime import datetime, timezone

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # 1. 建表(若 ORM 已经 create_all 过会跳过)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sentiment_platforms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code VARCHAR NOT NULL UNIQUE,
                domain VARCHAR NOT NULL,
                category VARCHAR NOT NULL,
                region VARCHAR NOT NULL,
                name_zh VARCHAR NOT NULL DEFAULT '',
                name_en VARCHAR NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS ix_sentiment_platforms_code ON sentiment_platforms(code)")

        # 2. 拿到现有 code,只插缺失的(idempotent)
        cur.execute("SELECT code FROM sentiment_platforms")
        existing = {row[0] for row in cur.fetchall()}

        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        new_rows = [r for r in SEED if r[0] not in existing]
        if not new_rows:
            print(f"[migrate] sentiment_platforms already has all {len(SEED)} seed codes — nothing to insert")
        else:
            # 011 加了 media_type / industry 两列且 NOT NULL — 若表结构已是 011 版,
            # 010 的 INSERT 必须显式提供这两列(空串占位,让 011 之后回填),否则
            # 原始 010 schema 的表(只有 11 列)用窄 INSERT。
            cur.execute("PRAGMA table_info(sentiment_platforms)")
            cols = {row[1] for row in cur.fetchall()}
            has_axes = "media_type" in cols and "industry" in cols
            if has_axes:
                cur.executemany(
                    """
                    INSERT INTO sentiment_platforms
                      (code, domain, category, region, name_zh, name_en, sort_order,
                       media_type, industry, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, '', '', 1, ?, ?)
                    """,
                    [(*row, now, now) for row in new_rows],
                )
            else:
                cur.executemany(
                    """
                    INSERT INTO sentiment_platforms
                      (code, domain, category, region, name_zh, name_en, sort_order, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    [(*row, now, now) for row in new_rows],
                )
            conn.commit()
            print(f"[migrate] inserted {len(new_rows)} new platform rows ({len(existing)} pre-existing left untouched)")
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
