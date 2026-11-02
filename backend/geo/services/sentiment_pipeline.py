"""舆情 pipeline 编排 — 单账号的 monitor → analyze → brief 全流程.

被 sentiment_scheduler(定时任务)和 /run-now 手动触发共用.
状态机更新 + 失败兜底 + 邮件推送都在这里.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from geo.database import SessionLocal
from geo.models.sentiment import (
    KeywordGroup, SentimentAccountORM, SentimentKnowledgeORM, SentimentRunLogORM,
    flatten_keyword_groups,
)
from geo.services import sentinel_client
from geo.services.sentinel_client import SentinelError

log = logging.getLogger(__name__)


def _load_knowledge(db: Session, account_id: int) -> dict[str, str]:
    rows = db.query(SentimentKnowledgeORM).filter_by(account_id=account_id).all()
    return {r.key: r.body for r in rows if r.body}


def _mark_running(db: Session, acc: SentimentAccountORM, log_row: SentimentRunLogORM):
    acc.last_run_status = "running"
    log_row.status = "running"
    db.commit()


def _mark_success(db: Session, acc: SentimentAccountORM, log_row: SentimentRunLogORM, stats: dict):
    now = datetime.utcnow()
    stats_json = json.dumps(stats, ensure_ascii=False, default=str)
    acc.last_run_at = now
    acc.last_run_status = "success"
    acc.last_run_error = None
    acc.last_run_stats = stats_json
    log_row.ended_at = now
    log_row.status = "success"
    log_row.stats_json = stats_json
    if log_row.started_at:
        log_row.duration_s = int((now - log_row.started_at).total_seconds())
    db.commit()


def _mark_failed(db: Session, acc: SentimentAccountORM, log_row: SentimentRunLogORM, err: str):
    now = datetime.utcnow()
    truncated = err[:500] if err else ""
    acc.last_run_status = "failed"
    acc.last_run_error = truncated
    log_row.ended_at = now
    log_row.status = "failed"
    log_row.error = truncated
    if log_row.started_at:
        log_row.duration_s = int((now - log_row.started_at).total_seconds())
    db.commit()


def run_pipeline_for_account(account_id: int, trigger: str = "manual") -> dict:
    """同步执行 monitor → analyze → brief.

    在 BackgroundTasks 或 APScheduler thread 里调用,内部已经处理状态机.
    返回 {status, stats}.
    """
    db: Session = SessionLocal()
    try:
        acc = db.get(SentimentAccountORM, account_id)
        if not acc:
            log.warning("run_pipeline: account %s not found", account_id)
            return {"status": "failed", "error": "account not found"}

        if not acc.active:
            log.info("run_pipeline: account %s is inactive, skip", account_id)
            return {"status": "skipped", "reason": "inactive"}

        # 防重入 — 另一个 pipeline 正在跑就跳过
        if acc.last_run_status == "running":
            log.info("run_pipeline: account %s already running, skip duplicate", account_id)
            return {"status": "skipped", "reason": "already running"}

        log_row = SentimentRunLogORM(
            account_id=account_id, trigger=trigger,
            started_at=datetime.utcnow(), status="running",
        )
        db.add(log_row)
        _mark_running(db, acc, log_row)

        knowledge = _load_knowledge(db, account_id)
        aliases = json.loads(acc.aliases_json or "[]")
        # 优先用结构化分组展平的关键词;为空才回退扁平字段.
        groups_raw = json.loads(acc.keyword_groups_json or "[]")
        if groups_raw:
            keywords = flatten_keyword_groups(
                [KeywordGroup.model_validate(g) for g in groups_raw]
            )
        else:
            keywords = json.loads(acc.keywords_json or "[]")
        excludes = json.loads(acc.excludes_json or "[]")
        media_allowlist = json.loads(acc.media_allowlist_json or "[]")

        stats: dict = {}
        try:
            log.info("run_pipeline[%s]: monitor begin", account_id)
            r1 = sentinel_client.run_monitor(
                account_id=account_id,
                target=acc.target, ticker=acc.ticker,
                intent=acc.intent, aliases=aliases,
                keywords=keywords, excludes=excludes,
                media_allowlist=media_allowlist,
            )
            stats["monitor"] = r1

            # 直接爬虫 — 全部 *并行* 执行,大幅缩短 pipeline 总时长。
            # 每个爬虫独立 try/except,失败不影响其它。
            log.info("run_pipeline[%s]: crawlers begin (parallel)", account_id)
            ticker = acc.ticker
            target = acc.target

            # 每条 = (name, callable) — callable 不带参,用 lambda 捕获 args
            # 读两个可选数据源配置 — 空 list 时下面对应 crawler 不入 task 列表
            weixin_album_urls = json.loads(acc.weixin_album_urls_json or "[]")
            newsnow_sources = json.loads(acc.newsnow_sources_json or "[]")
            # newsnow 用 aliases + keywords + target 一起作标题过滤
            newsnow_filter_kw = list({target, *aliases, *keywords})

            crawler_tasks: list[tuple[str, callable]] = [
                ("eastmoney",
                 lambda: sentinel_client.crawl_eastmoney(account_id=account_id, symbol=ticker, pages=10)),
                ("eastmoney_news",
                 lambda: sentinel_client.crawl_eastmoney_news(account_id=account_id, keyword=target, pages=5)),
                # 2026-05-08 新增:EastMoney 系 3 个端点(都用 ticker)
                ("eastmoney_ann",
                 lambda: sentinel_client.crawl_eastmoney_ann(account_id=account_id, ticker=ticker, pages=3)),
                ("eastmoney_research",
                 lambda: sentinel_client.crawl_eastmoney_research(account_id=account_id, ticker=ticker, pages=2)),
                ("eastmoney_industry",
                 lambda: sentinel_client.crawl_eastmoney_industry(account_id=account_id, ticker=ticker, pages=2)),
                ("sina_stock",
                 lambda: sentinel_client.crawl_sina_stock(account_id=account_id, ticker=ticker, pages=1)),
                # 历史爬虫 — 多数因 WAF/API 变更失效,继续保留,失败被捕获不影响其它
                ("xueqiu",
                 lambda: sentinel_client.crawl_xueqiu(account_id=account_id, symbol=ticker, pages=5)),
                ("sina",
                 lambda: sentinel_client.crawl_sina(account_id=account_id, keyword=target, pages=3)),
                ("tieba",
                 lambda: sentinel_client.crawl_tieba(account_id=account_id, keyword=target, pages=3)),
                ("cls",
                 lambda: sentinel_client.crawl_cls(account_id=account_id, keyword=target, pages=3)),
                ("gelonghui",
                 lambda: sentinel_client.crawl_gelonghui(account_id=account_id, keyword=target, pages=3)),
                ("wallstreetcn",
                 lambda: sentinel_client.crawl_wallstreetcn(account_id=account_id, keyword=target, pages=3)),
                ("yicai",
                 lambda: sentinel_client.crawl_yicai(account_id=account_id, keyword=target, pages=3)),
                ("36kr",
                 lambda: sentinel_client.crawl_36kr(account_id=account_id, keyword=target, pages=3)),
            ]
            # 仅当账号配置非空才加入,避免每次跑都打 sentinel-service 然后返 skipped
            if weixin_album_urls:
                crawler_tasks.append((
                    "weixin_album",
                    lambda: sentinel_client.crawl_weixin_album(
                        account_id=account_id,
                        album_urls=weixin_album_urls,
                        hydrate_body=True,
                        max_articles_per_album=200,
                    ),
                ))
            if newsnow_sources:
                crawler_tasks.append((
                    "newsnow",
                    lambda: sentinel_client.crawl_newsnow(
                        account_id=account_id,
                        source_ids=newsnow_sources,
                        keywords=newsnow_filter_kw,
                        symbol=ticker,
                    ),
                ))
            crawlers_stats: dict = {}
            from concurrent.futures import ThreadPoolExecutor, as_completed
            # 13 个 crawler,并发 8 是个合理上限(避免同时打太多 sentinel HTTP 请求,
            # 也避免 sentinel-service 内部把上游站点打挂导致整体被风控)
            with ThreadPoolExecutor(max_workers=8) as pool:
                future_to_name = {pool.submit(fn): name for name, fn in crawler_tasks}
                for fut in as_completed(future_to_name):
                    name = future_to_name[fut]
                    try:
                        r = fut.result()
                        crawlers_stats[name] = r
                        log.info("run_pipeline[%s]: %s +%s",
                                 account_id, name, r.get("inserted", 0))
                    except Exception as e:
                        log.warning("run_pipeline[%s]: %s failed: %s", account_id, name, e)
                        crawlers_stats[name] = {"error": str(e)}

            stats["crawlers"] = crawlers_stats

            log.info("run_pipeline[%s]: analyze begin", account_id)
            r2 = sentinel_client.run_analyze(account_id=account_id, ticker=acc.ticker)
            stats["analyze"] = r2

            log.info("run_pipeline[%s]: brief begin", account_id)
            r3 = sentinel_client.run_brief(account_id=account_id, ticker=acc.ticker)
            stats["brief"] = {
                "date": r3.get("date"),
                "path": r3.get("path"),
            }

            # 邮件推送(notify_emails 非空时)
            emails = json.loads(acc.notify_emails_json or "[]")
            if emails:
                _push_brief_email(acc, r3.get("body", ""), emails)

            # 飞书 / 企微推送:账户接入了 IM(有绑定会话)就把当天简报推过去
            # 注意:IM connector 按 user_id 绑定(同 alerts._push_im),不是 SentimentAccount.id
            # 防护:推送结果记进 stats["push"](写入 run 日志),失败可在 sentiment_run_logs 查到
            stats["push"] = _push_brief_im(db, acc.user_id, acc.target, r3.get("body", ""))

            _mark_success(db, acc, log_row, stats)
            log.info("run_pipeline[%s]: done", account_id)
            return {"status": "success", "stats": stats}
        except SentinelError as e:
            log.warning("run_pipeline[%s]: sentinel failed: %s (%s)", account_id, e, e.category)
            _mark_failed(db, acc, log_row, str(e))
            return {"status": "failed", "error": str(e), "category": e.category}
        except Exception as e:
            log.exception("run_pipeline[%s]: crashed: %s", account_id, e)
            _mark_failed(db, acc, log_row, str(e))
            return {"status": "failed", "error": str(e), "category": "system"}
    finally:
        db.close()


def _push_brief_im(db, user_id: int, target: str, body_md: str) -> dict:
    """跑完把当天简报推到该 user 绑定的飞书 / 企微会话(接入的人或群)。

    复用 agent.alerts._push_im。**防护**:返回推送结果 {"ok","sent","errors"} 并写进 run 日志的
    stats["push"],推送失败(含 import/语法错)显式打 ERROR —— 不再静默,"今天没推"一查 run_logs 即知。
    best-effort:推送失败不影响 pipeline 成功状态。
    """
    if not body_md:
        return {"ok": False, "reason": "empty_brief"}
    try:
        import asyncio
        from geo.agent.alerts import _push_im
        date = datetime.utcnow().strftime("%Y-%m-%d")
        text = f"📊 **{target} · 今日舆情简报 {date}**\n\n{body_md}"
        res = asyncio.run(_push_im(db, user_id, text))
        ok = (res.get("sent", 0) > 0)
        if ok:
            log.info("run_pipeline: brief pushed to IM (user=%s, sent=%s, errors=%s)",
                     user_id, res.get("sent"), res.get("errors"))
        else:
            log.error("run_pipeline: brief IM push 发送数为 0!(user=%s) errors=%s",
                      user_id, res.get("errors"))
        return {"ok": ok, **res}
    except Exception as e:  # noqa: BLE001 — import/语法错等也要显式记下来,绝不静默
        log.exception("run_pipeline: IM push 崩溃 (user=%s): %s", user_id, e)
        return {"ok": False, "error": str(e)[:200]}


def _push_brief_email(acc: SentimentAccountORM, body_md: str, recipients: list[str]) -> None:
    """简报邮件推送 — 用 GEO 现有 Resend 通道.
    MVP 简单实现:把 Markdown 直接装进邮件 plaintext;P1 可加 HTML 渲染.
    """
    try:
        from geo.services.email_service import send_email  # type: ignore
    except ImportError:
        log.warning("email_service not available, skipping brief push")
        return

    subject = f"[舆情简报] {acc.target} · {datetime.utcnow().strftime('%Y-%m-%d')}"
    for to in recipients:
        try:
            send_email(to=to, subject=subject, body=body_md)
        except Exception as e:  # noqa: BLE001
            log.warning("brief email to %s failed: %s", to, e)
