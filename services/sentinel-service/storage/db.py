"""PostgreSQL storage for posts, LLM analyses, AI briefs and response drafts.

多租户落地:每个 account_id 一个独立 PG schema `tenant_{N}`,
通过 `SET search_path` 让原有未限定的 `SELECT * FROM posts` 自动路由到当前
租户的表上(对调用方零侵入).

历史背景:这个模块原来是裸 sqlite3,每账户一个 .db 文件.切 PG 时:
- driver psycopg3,row_factory=dict_row 让 `row["col"]` 语法不变
- `?` → `%s`
- `INSERT OR REPLACE` → `INSERT … ON CONFLICT (...) DO UPDATE SET …`
- `lastrowid` → `RETURNING id` + `fetchone()["id"]`
- `json_extract(col, '$[0]')` → `(col::jsonb)->>0`(空串/NULL 用 CASE 兜底)
- `AUTOINCREMENT` → `BIGSERIAL`
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

import psycopg
from psycopg.rows import dict_row


# DATABASE_URL 来自 systemd EnvironmentFile / .env;import 阶段不连库,
# 真正缺值在 connect() 抛,避免 pytest collect 阶段炸.
DATABASE_URL = os.environ.get("DATABASE_URL", "")


# 历史 alias:storage/__init__.py 旧版 re-export 此名;新版不再用,保留空值避免
# 上游 from storage import DEFAULT_DB_PATH 立即炸.可在 cleanup 后删.
DEFAULT_DB_PATH: Path | None = None


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS posts (
        source        TEXT NOT NULL,
        post_id       TEXT NOT NULL,
        symbol        TEXT,
        author        TEXT,
        title         TEXT,
        content       TEXT,
        publish_time  TEXT,
        view_count    INTEGER,
        reply_count   INTEGER,
        like_count    INTEGER,
        share_count   INTEGER,
        url           TEXT,
        ingested_at   TEXT NOT NULL,
        PRIMARY KEY (source, post_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_posts_symbol ON posts(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_posts_pubtime ON posts(publish_time)",
    """
    CREATE TABLE IF NOT EXISTS analyses (
        source              TEXT NOT NULL,
        post_id             TEXT NOT NULL,
        symbol              TEXT,
        is_relevant         INTEGER NOT NULL,
        filter_reason       TEXT,
        summary             TEXT,
        sentiment_label     TEXT,
        sentiment_score     DOUBLE PRECISION,
        emotions_json       TEXT,
        topics_json         TEXT,
        entities_json       TEXT,
        stance              TEXT,
        intent              TEXT,
        factuality          TEXT,
        risk_level          TEXT,
        risk_signals_json   TEXT,
        influence_potential DOUBLE PRECISION,
        hidden_meaning      TEXT,
        citations_json      TEXT,
        reasoning           TEXT,
        model               TEXT NOT NULL,
        analyzed_at         TEXT NOT NULL,
        PRIMARY KEY (source, post_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_analyses_symbol ON analyses(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_analyses_risk ON analyses(risk_level)",
    "CREATE INDEX IF NOT EXISTS idx_analyses_sentiment ON analyses(sentiment_label)",
    """
    CREATE TABLE IF NOT EXISTS briefs (
        id            BIGSERIAL PRIMARY KEY,
        symbol        TEXT NOT NULL,
        date          TEXT NOT NULL,
        body          TEXT NOT NULL,
        model         TEXT NOT NULL,
        generated_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_briefs_symbol_date ON briefs(symbol, date)",
    """
    CREATE TABLE IF NOT EXISTS drafts (
        id                BIGSERIAL PRIMARY KEY,
        symbol            TEXT NOT NULL,
        source            TEXT,
        post_id           TEXT,
        topic             TEXT,
        variant           TEXT NOT NULL,
        body              TEXT NOT NULL,
        rationale         TEXT,
        predicted_effect  TEXT,
        cautions          TEXT,
        model             TEXT NOT NULL,
        generated_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_drafts_symbol ON drafts(symbol)",
    """
    CREATE TABLE IF NOT EXISTS query_runs (
        symbol        TEXT NOT NULL,
        query         TEXT NOT NULL,
        last_run_at   TEXT NOT NULL,
        PRIMARY KEY (symbol, query)
    )
    """,
)


def _schema_name(account_id: int) -> str:
    # int cast 是安全卫词:account_id 来自上游 user 配置,不应直接拼 SQL 标识符.
    return f"tenant_{int(account_id)}"


def connect(account_id: int | None = None) -> psycopg.Connection:
    """获取 PG 连接,可选地绑定到某个 tenant schema.

    - account_id 非 None:确保 schema 存在,然后 SET search_path TO tenant_{N}, public.
      原有未限定 SQL(`SELECT * FROM posts`)自动解析到该 schema.
    - account_id None:连默认 search_path(运维 / 健康检查 / 不读写租户数据用).

    DATABASE_URL 必须在 env 中设置,否则抛.
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL 未设置.systemd unit / .env 里加 "
            "DATABASE_URL=postgresql://appuser:***@host:port/appdb"
        )
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    if account_id is not None:
        schema = _schema_name(account_id)
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cur.execute(f'SET search_path TO "{schema}", public')
        conn.commit()
    return conn


def init_schema(conn: psycopg.Connection) -> None:
    """在 conn 当前 search_path(由 connect 绑定的 tenant)下建齐 5 张表.

    幂等(CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS),每个请求入口
    都调一次也无所谓 — 已存在的 schema/表会直接跳过.
    """
    with conn.cursor() as cur:
        # 串行化并发 schema 初始化:多个爬虫端点并行调用时,CREATE INDEX / ALTER 的
        # AccessExclusiveLock 会两两死锁。事务级咨询锁让它们排队(持有到 commit),
        # 而不是死锁。key 任意常量,全局唯一即可。
        cur.execute("SELECT pg_advisory_xact_lock(727274)")
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)
        # 历史 ADD COLUMN 兼容:posts 后期加 like_count / share_count
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS like_count INTEGER")
        cur.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS share_count INTEGER")
    conn.commit()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def upsert_post(conn: psycopg.Connection, rec: dict) -> bool:
    """Insert post if new; return True if inserted, False if it already existed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posts (source, post_id, symbol, author, title, content,
                               publish_time, view_count, reply_count,
                               like_count, share_count,
                               url, ingested_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source, post_id) DO NOTHING
            """,
            (
                rec.get("source"),
                str(rec.get("post_id")),
                rec.get("symbol"),
                rec.get("author"),
                rec.get("title"),
                rec.get("content"),
                rec.get("publish_time"),
                rec.get("view_count"),
                rec.get("reply_count"),
                rec.get("like_count"),
                rec.get("share_count"),
                rec.get("url"),
                _now(),
            ),
        )
        return cur.rowcount == 1


def upsert_analysis(conn: psycopg.Connection, source: str, post_id: str,
                    symbol: str | None, analysis: dict, model: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analyses (
                source, post_id, symbol,
                is_relevant, filter_reason,
                summary, sentiment_label, sentiment_score,
                emotions_json, topics_json, entities_json,
                stance, intent, factuality,
                risk_level, risk_signals_json, influence_potential,
                hidden_meaning, citations_json, reasoning,
                model, analyzed_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source, post_id) DO UPDATE SET
                symbol              = EXCLUDED.symbol,
                is_relevant         = EXCLUDED.is_relevant,
                filter_reason       = EXCLUDED.filter_reason,
                summary             = EXCLUDED.summary,
                sentiment_label     = EXCLUDED.sentiment_label,
                sentiment_score     = EXCLUDED.sentiment_score,
                emotions_json       = EXCLUDED.emotions_json,
                topics_json         = EXCLUDED.topics_json,
                entities_json       = EXCLUDED.entities_json,
                stance              = EXCLUDED.stance,
                intent              = EXCLUDED.intent,
                factuality          = EXCLUDED.factuality,
                risk_level          = EXCLUDED.risk_level,
                risk_signals_json   = EXCLUDED.risk_signals_json,
                influence_potential = EXCLUDED.influence_potential,
                hidden_meaning      = EXCLUDED.hidden_meaning,
                citations_json      = EXCLUDED.citations_json,
                reasoning           = EXCLUDED.reasoning,
                model               = EXCLUDED.model,
                analyzed_at         = EXCLUDED.analyzed_at
            """,
            (
                source, str(post_id), symbol,
                1 if analysis.get("is_relevant") else 0,
                analysis.get("filter_reason"),
                analysis.get("summary"),
                analysis.get("sentiment_label"),
                analysis.get("sentiment_score"),
                json.dumps(analysis.get("emotions") or [], ensure_ascii=False),
                json.dumps(analysis.get("topics") or [], ensure_ascii=False),
                json.dumps(analysis.get("entities") or [], ensure_ascii=False),
                analysis.get("stance"),
                analysis.get("intent"),
                analysis.get("factuality"),
                analysis.get("risk_level"),
                json.dumps(analysis.get("risk_signals") or [], ensure_ascii=False),
                analysis.get("influence_potential"),
                analysis.get("hidden_meaning"),
                json.dumps(analysis.get("citations") or [], ensure_ascii=False),
                analysis.get("reasoning"),
                model, _now(),
            ),
        )


def insert_brief(conn: psycopg.Connection, symbol: str, date: str,
                 body: str, model: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO briefs (symbol, date, body, model, generated_at) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (symbol, date, body, model, _now()),
        )
        row = cur.fetchone()
        return int(row["id"])


def insert_draft(conn: psycopg.Connection, symbol: str,
                 source: str | None, post_id: str | None, topic: str | None,
                 variant: str, body: str, rationale: str | None,
                 predicted_effect: str | None, cautions: str | None,
                 model: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO drafts (symbol, source, post_id, topic, variant, body,
                                rationale, predicted_effect, cautions,
                                model, generated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (symbol, source, post_id, topic, variant, body,
             rationale, predicted_effect, cautions, model, _now()),
        )
        row = cur.fetchone()
        return int(row["id"])


def posts_for_symbol(conn: psycopg.Connection, symbol: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM posts WHERE symbol = %s ORDER BY publish_time DESC",
            (symbol,),
        )
        return list(cur.fetchall())


def posts_missing_analysis(conn: psycopg.Connection, symbol: str,
                           limit: int | None = None) -> list[dict]:
    sql = """
        SELECT p.* FROM posts p
        LEFT JOIN analyses a ON a.source = p.source AND a.post_id = p.post_id
        WHERE p.symbol = %s AND a.post_id IS NULL
        ORDER BY p.publish_time DESC
    """
    params: tuple = (symbol,)
    if limit:
        sql += " LIMIT %s"
        params = (symbol, limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


# sort_by 白名单 → SQL ORDER BY 子句.
# 全部在 SQL 层排,前端不再客户端排,避免跨 page 顺序错乱.
# 时间排序只认 publish_time;undated(NULL)放最后,不再用 ingested_at 兜底.
# cluster 用 topics_json 第一个 topic;PG 下要 cast 成 jsonb,空串/NULL 兜底.
_SORT_SQL: dict[str, str] = {
    "newest":         "p.publish_time DESC NULLS LAST",
    "oldest":         "p.publish_time ASC NULLS LAST",
    "engagement":     ("(COALESCE(p.view_count,0) + COALESCE(p.reply_count,0) "
                       "+ COALESCE(p.like_count,0) + COALESCE(p.share_count,0)) DESC"),
    "shares":         "COALESCE(p.share_count, -1) DESC",
    "replies":        "COALESCE(p.reply_count, -1) DESC",
    "likes":          "COALESCE(p.like_count, -1) DESC",
    "views":          "COALESCE(p.view_count, -1) DESC",
    "cluster":        (
        "COALESCE("
        "  CASE WHEN a.topics_json IS NULL OR a.topics_json = '' OR a.topics_json = '[]' "
        "       THEN NULL "
        "       ELSE (a.topics_json::jsonb)->>0 END, '~') ASC, "
        "(COALESCE(a.influence_potential,0) * ABS(COALESCE(a.sentiment_score,0))) DESC"
    ),
    "mediaAZ":        "p.source ASC",
    "mediaZA":        "p.source DESC",
    "scoreSentiment": "ABS(COALESCE(a.sentiment_score, 0)) DESC",
    "scoreInfluence": ("(COALESCE(a.influence_potential,0) * "
                       "ABS(COALESCE(a.sentiment_score,0))) DESC"),
}


def analyses_for_symbol(conn: psycopg.Connection, symbol: str,
                        days: int | None = 1,
                        start: str | None = None,
                        end: str | None = None,
                        limit: int | None = None,
                        offset: int = 0,
                        sort_by: str = "newest",
                        ) -> list[dict]:
    """文章列表(舆情 Tab 用).参见 sqlite 版本的 docstring,语义一致.

    只返回 is_relevant=1 的帖子 — 与 today_aggregation 的 KPI / 趋势 / 风险饼 /
    Top5 及简报口径一致(它们早已过滤),避免文章列表把分析判定无关的搜索噪声
    (同名实体、词典释义)露给用户.
    """
    where = ["a.symbol = %s", "a.is_relevant = 1"]
    params: list = [symbol]

    if start or end:
        if start:
            where.append("p.publish_time >= %s")
            params.append(start)
        if end:
            where.append("p.publish_time <= %s")
            params.append(end)
    elif days and days > 0:
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        where.append("p.publish_time >= %s")
        params.append(cutoff)

    order = _SORT_SQL.get(sort_by) or _SORT_SQL["newest"]
    tie = "p.ingested_at DESC, p.post_id ASC"
    sql = f"""
        SELECT a.*, p.title, p.author, p.publish_time, p.view_count,
               p.reply_count, p.like_count, p.share_count,
               p.url, p.content, p.ingested_at
        FROM analyses a
        JOIN posts p ON p.source = a.source AND p.post_id = a.post_id
        WHERE {' AND '.join(where)}
        ORDER BY {order}, {tie}
    """
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params.extend([int(limit), int(offset)])
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return list(cur.fetchall())


def analyses_count_for_symbol(conn: psycopg.Connection, symbol: str,
                              days: int | None = 1,
                              start: str | None = None,
                              end: str | None = None,
                              ) -> int:
    # 与 analyses_for_symbol 口径一致:只数 is_relevant=1,分页总数才对得上。
    where = ["a.symbol = %s", "a.is_relevant = 1"]
    params: list = [symbol]

    if start or end:
        if start:
            where.append("p.publish_time >= %s")
            params.append(start)
        if end:
            where.append("p.publish_time <= %s")
            params.append(end)
    elif days and days > 0:
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        where.append("p.publish_time >= %s")
        params.append(cutoff)

    sql = f"""
        SELECT count(*) AS c
        FROM analyses a
        JOIN posts p ON p.source = a.source AND p.post_id = a.post_id
        WHERE {' AND '.join(where)}
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        return int(row["c"] if row else 0)


def analyses_for_day(conn: psycopg.Connection, symbol: str,
                     date: str, hours: int | None = None) -> list[dict]:
    """日报取帖 —— 只认**发布时间** publish_time,**滚动近 N 小时**窗口(默认 24h)。

    窗口 = publish_time 在 [now - hours, now]:
      · 带时分的(如 2026-06-18T09:07)→ 精确比 now-hours;
      · 纯日期的(如 2026-06-18,只到天)→ 按"发布日 >= 截止当天"宽松纳入(不知具体时分)。
    undated(publish_time 为 NULL)一律**排除**,绝不退回 ingested_at。
    hours 可用环境变量 SENTINEL_BRIEF_HOURS 调:24=近24小时 / 72=近3天 / 168=近一周。
    """
    import os
    from datetime import datetime, timedelta
    if hours is None:
        try:
            hours = int(os.environ.get("SENTINEL_BRIEF_HOURS", "24"))
        except ValueError:
            hours = 24
    cutoff = datetime.now() - timedelta(hours=max(hours, 1))
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M")
    cutoff_date = cutoff.strftime("%Y-%m-%d")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.*, p.title, p.author, p.publish_time, p.view_count,
                   p.reply_count, p.url, p.content
            FROM analyses a
            JOIN posts p ON p.source = a.source AND p.post_id = a.post_id
            WHERE a.symbol = %s
              AND p.publish_time IS NOT NULL
              AND (
                (length(p.publish_time) > 10 AND p.publish_time >= %s)
                OR (length(p.publish_time) <= 10 AND substr(p.publish_time, 1, 10) >= %s)
              )
            ORDER BY p.publish_time DESC
            """,
            (symbol, cutoff_iso, cutoff_date),
        )
        return list(cur.fetchall())


def brand_post_lookup(conn: psycopg.Connection, source: str,
                      post_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.*, a.summary, a.sentiment_label, a.risk_level,
                   a.topics_json, a.intent, a.stance
            FROM posts p
            LEFT JOIN analyses a ON a.source = p.source AND a.post_id = p.post_id
            WHERE p.source = %s AND p.post_id = %s
            """,
            (source, str(post_id)),
        )
        return cur.fetchone()


def get_query_last_run(conn: psycopg.Connection, symbol: str,
                       query: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_run_at FROM query_runs WHERE symbol = %s AND query = %s",
            (symbol, query),
        )
        row = cur.fetchone()
        return row["last_run_at"] if row else None


def upsert_query_last_run(conn: psycopg.Connection, symbol: str,
                          query: str, ts: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO query_runs (symbol, query, last_run_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (symbol, query) DO UPDATE SET last_run_at = EXCLUDED.last_run_at
            """,
            (symbol, query, ts or _now()),
        )


def ingest_jsonl_dir(conn: psycopg.Connection, data_dir: Path) -> tuple[int, int]:
    """Ingest every *.jsonl file in data_dir. Returns (inserted, skipped)."""
    inserted = skipped = 0
    for path in sorted(data_dir.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if upsert_post(conn, rec):
                    inserted += 1
                else:
                    skipped += 1
    conn.commit()
    return inserted, skipped


def ingest_records(conn: psycopg.Connection, records: Iterable[dict]) -> int:
    n = 0
    for r in records:
        if upsert_post(conn, r):
            n += 1
    conn.commit()
    return n
