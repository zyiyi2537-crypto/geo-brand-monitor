"""Migration 011: split single `category` axis into `media_type` + `industry`.

对标 WisersOne 的 filter 模型:每个媒体源同时有
  - 媒体类型 / media_type(载体):web / weibo / wechat / app / forum /
    short_video / long_video / broadcast / newspaper / magazine / blog /
    ecommerce / review
  - 媒体分类 / industry(主题):finance / general / tech / science /
    party_media / health / overseas_en

之前 `category` 字段把这两个维度压扁成一个(finance/social/forum/video/news/
overseas),无法表达"36氪 = web + tech"或"weibo = weibo + general"这类组合。

本迁移:
  1. ALTER TABLE 加两列(允许为空)
  2. UPDATE 把 68 个种子 code 映射到 (media_type, industry)
  3. 只回填 NULL / 空值 — 已被 admin 手动调整过的行不动

Idempotent:重跑只补 NULL 的列,已填好的不覆盖。

Usage:
    cd backend && python migrations/011_sentiment_platform_axes.py
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# code → (media_type, industry)
# media_type:载体形态(用户在筛选器里看到的"是什么类型的媒体")
# industry:主题/行业(用户在筛选器里看到的"这家媒体覆盖什么领域")
AXES_MAP: dict[str, tuple[str, str]] = {
    # ── 财经媒体(主力)── 多数是 web,xueqiu/ths/cls/futunn/itiger 是金融 app
    "xueqiu":       ("app",        "finance"),
    "eastmoney":    ("forum",      "finance"),  # 股吧
    "caixin":       ("web",        "finance"),
    "36kr":         ("web",        "tech"),
    "sina_finance": ("web",        "finance"),
    "qq_finance":   ("web",        "finance"),
    "163_finance":  ("web",        "finance"),
    "ths":          ("app",        "finance"),
    "wallstreetcn": ("web",        "finance"),
    "yicai":        ("web",        "finance"),
    "cls":          ("app",        "finance"),
    "gelonghui":    ("web",        "finance"),
    # ── 财经媒体(扩展)──
    "jrj":          ("web",        "finance"),
    "hexun":        ("web",        "finance"),
    "jin10":        ("web",        "finance"),
    "nbd":          ("web",        "finance"),
    "jingji21":     ("web",        "finance"),
    "stcn":         ("web",        "finance"),
    "cs_com":       ("web",        "finance"),
    "cnstock":      ("web",        "finance"),
    "p5w":          ("web",        "finance"),
    "caijing":      ("web",        "finance"),
    "iyiou":        ("web",        "tech"),
    "futunn":       ("app",        "finance"),
    "itiger":       ("app",        "finance"),
    "zhitong":      ("web",        "finance"),
    # ── 社交媒体 ── 微博 / 微信公众号有专门的 media_type;小红书/知乎按 app
    "weibo":        ("weibo",      "general"),
    "weixin":       ("wechat",     "general"),
    "xiaohongshu":  ("app",        "general"),
    "zhihu":        ("app",        "general"),
    # ── 论坛社区 ──
    "tieba":        ("forum",      "general"),
    "zhidao":       ("forum",      "general"),
    "hupu":         ("forum",      "general"),
    "douban":       ("forum",      "general"),
    "v2ex":         ("forum",      "tech"),
    "guokr":        ("forum",      "science"),
    "csdn":         ("forum",      "tech"),
    "juejin":       ("forum",      "tech"),
    # ── 视频平台 ──
    "bilibili":     ("long_video", "general"),
    "douyin":       ("short_video","general"),
    "kuaishou":     ("short_video","general"),
    "toutiao":      ("app",        "general"),  # 头条本质是聚合 app
    "vqq":          ("long_video", "general"),
    "iqiyi":        ("long_video", "general"),
    "ixigua":       ("short_video","general"),
    # ── 资讯门户(综合 + 党政央媒 + 科技)──
    "baidu_news":   ("web",        "general"),
    "ifeng":        ("web",        "general"),
    "sina_main":    ("web",        "general"),
    "sohu":         ("web",        "general"),
    "chinanews":    ("web",        "party_media"),
    "xinhuanet":    ("web",        "party_media"),
    "people":       ("web",        "party_media"),
    "huanqiu":      ("web",        "party_media"),
    "guancha":      ("web",        "general"),
    "ce_cn":        ("web",        "party_media"),
    "thepaper":     ("web",        "general"),
    "jiemian":      ("web",        "finance"),
    "huxiu":        ("web",        "tech"),
    "tmtpost":      ("web",        "tech"),
    "pingwest":     ("web",        "tech"),
    "ifanr":        ("web",        "tech"),
    "qbitai":       ("web",        "tech"),
    "jiqizhixin":   ("web",        "tech"),
    # ── 海外 ──
    "reddit":       ("forum",      "overseas_en"),
    "twitter":      ("weibo",      "overseas_en"),  # X/Twitter = 微博形态
    "seekingalpha": ("web",        "finance"),
    "bloomberg":    ("web",        "finance"),
    "reuters":      ("web",        "finance"),
}


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
        print(f"[migrate] {db_path} does not exist — run backend once or 010 first")
        return

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # 1. 表存在?
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sentiment_platforms'"
        )
        if not cur.fetchone():
            print("[migrate] sentiment_platforms table missing — run migration 010 first")
            return

        # 2. 加列(若不存在)
        cur.execute("PRAGMA table_info(sentiment_platforms)")
        cols = {row[1] for row in cur.fetchall()}
        added = []
        if "media_type" not in cols:
            cur.execute(
                "ALTER TABLE sentiment_platforms ADD COLUMN media_type VARCHAR DEFAULT ''"
            )
            added.append("media_type")
        if "industry" not in cols:
            cur.execute(
                "ALTER TABLE sentiment_platforms ADD COLUMN industry VARCHAR DEFAULT ''"
            )
            added.append("industry")
        if added:
            conn.commit()
            print(f"[migrate] added columns: {', '.join(added)}")
        else:
            print("[migrate] media_type and industry columns already exist")

        # 3. 回填 — 只动 NULL / '' 的行(保留 admin 手动改的值)
        cur.execute(
            "SELECT code, media_type, industry FROM sentiment_platforms"
        )
        rows = cur.fetchall()
        updates: list[tuple[str, str, str]] = []  # (media_type, industry, code)
        for code, mt, ind in rows:
            target = AXES_MAP.get(code)
            if not target:
                continue  # 未知 code(用户后加的)— 不动
            new_mt = target[0] if (mt is None or mt == "") else None
            new_ind = target[1] if (ind is None or ind == "") else None
            if new_mt is None and new_ind is None:
                continue  # 两列都已填,跳过
            updates.append((
                new_mt if new_mt is not None else mt,
                new_ind if new_ind is not None else ind,
                code,
            ))

        if not updates:
            print(f"[migrate] all {len(rows)} rows already have media_type and industry — nothing to backfill")
        else:
            cur.executemany(
                "UPDATE sentiment_platforms SET media_type = ?, industry = ? WHERE code = ?",
                updates,
            )
            conn.commit()
            print(f"[migrate] backfilled axes on {len(updates)} rows ({len(rows) - len(updates)} were already filled or unknown)")
    finally:
        conn.close()

    print("[migrate] done")


if __name__ == "__main__":
    main()
