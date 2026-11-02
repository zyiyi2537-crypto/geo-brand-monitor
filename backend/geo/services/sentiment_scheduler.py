"""舆情定时任务 — APScheduler 集成.

每小时执行一次(可通过 SENTINEL_CRON_INTERVAL_HOURS 调整),
遍历所有有舆情服务权限的账号,触发 pipeline.

部署要点:
- 多 worker 时只让 leader 起 scheduler(读 GEO_SCHEDULER_LEADER 环境变量)
- jobs 持久化用 SQLAlchemyJobStore,容器重启不丢
- 每 10 分钟扫一次"僵尸任务"(running 但 last_run_at 超 60 分钟未更新)
- 任务间隔 1 小时,所以僵尸阈值放宽到 60 分钟,给 LLM 调用充分时间

启动:
    在 backend/geo/main.py 的 startup hook 里,如果 GEO_SCHEDULER_LEADER=1 则调
    sentiment_scheduler.start()
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from geo.database import SessionLocal, engine
from geo.models.sentiment import SentimentAccountORM
from geo.services.sentiment_pipeline import run_pipeline_for_account

log = logging.getLogger(__name__)

# 调度间隔(小时):默认 1 小时跑一次
INTERVAL_HOURS = int(os.environ.get("SENTINEL_CRON_INTERVAL_HOURS", "1"))
# 起始偏移(分钟):避开整点峰值 — 默认 5 分(每小时 :05 跑)
START_MINUTE = int(os.environ.get("SENTINEL_CRON_START_MINUTE", "5"))
# 固定每天某点跑一次(0-23);设置后优先于 INTERVAL_HOURS。
# 例:SENTINEL_CRON_HOUR=10 + START_MINUTE=0 → 每天 10:00 跑一次。
_cron_hour_raw = os.environ.get("SENTINEL_CRON_HOUR", "").strip()
CRON_HOUR = int(_cron_hour_raw) if _cron_hour_raw else None
TIMEZONE = os.environ.get("SENTINEL_CRON_TZ", "Asia/Shanghai")
# 僵尸超时:任务间隔 1h,所以 60 分钟没动静才算挂了
ZOMBIE_TIMEOUT_MIN = int(os.environ.get("SENTINEL_ZOMBIE_TIMEOUT_MIN", "60"))

_scheduler = None


def _list_eligible_accounts(db: Session) -> list[int]:
    """返回所有 active 且会员有舆情权限的账号 id.

    MVP 简化:只看 active 字段;后续接入 membership 表的 sentiment_enabled.
    TODO: JOIN users → user_memberships → memberships WHERE sentiment_enabled=1
    """
    rows = (
        db.query(SentimentAccountORM.id)
          .filter(SentimentAccountORM.active.is_(True))
          .all()
    )
    return [r[0] for r in rows]


def run_hourly_job():
    """cron 触发入口 — 每小时跑一次所有合格账号.

    串行执行(避免 LLM 限流);P1 可加并发 + 限流.

    逻辑兜底:如果上一轮还没跑完(running),APScheduler 的 max_instances=1
    会自动跳过这次触发,避免重叠.
    """
    log.info("[sentinel-cron] hourly run start")
    db = SessionLocal()
    try:
        ids = _list_eligible_accounts(db)
    finally:
        db.close()

    log.info("[sentinel-cron] %d eligible accounts", len(ids))
    success = failed = skipped = 0
    for aid in ids:
        try:
            r = run_pipeline_for_account(aid, trigger="cron")
            if r.get("status") == "success":
                success += 1
            elif r.get("status") == "skipped":
                skipped += 1
            else:
                failed += 1
        except Exception as e:  # noqa: BLE001
            log.exception("account %s pipeline crashed: %s", aid, e)
            failed += 1
    log.info("[sentinel-cron] done success=%d failed=%d skipped=%d", success, failed, skipped)


def cleanup_zombies():
    """每 10 分钟跑一次,把超时未完成的 'running' 任务标记为 failed.

    场景:服务进程被 kill / OOM / docker stop,任务状态机没机会写 'failed',
    永远卡在 'running'.前端会一直显示"任务运行中".
    """
    db: Session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=ZOMBIE_TIMEOUT_MIN)
        # 用 last_run_at 做判断:如果它在 30 分钟前还是 running,说明僵尸
        zombies = (
            db.query(SentimentAccountORM)
              .filter(SentimentAccountORM.last_run_status == "running")
              .filter(SentimentAccountORM.last_run_at < cutoff)
              .all()
        )
        for acc in zombies:
            log.warning("[sentinel-cleanup] zombie account %s, marking failed", acc.id)
            acc.last_run_status = "failed"
            acc.last_run_error = "task interrupted (zombie cleanup)"
        if zombies:
            db.commit()
    finally:
        db.close()


def start() -> None:
    """启动 APScheduler.只有 leader 进程应该调这个.

    APScheduler 在 BackgroundScheduler 模式下用线程跑 jobs,与 FastAPI 主进程并行.
    """
    global _scheduler
    if _scheduler is not None:
        log.warning("[sentinel-scheduler] already started")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    except ImportError:
        log.error("[sentinel-scheduler] APScheduler not installed; run: pip install 'apscheduler[sqlalchemy]'")
        return

    _scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(engine=engine)},
        timezone=TIMEZONE,
    )

    # 每 INTERVAL_HOURS 小时跑一次,在每小时 START_MINUTE 分触发
    # (默认每小时 :05 — 避开整点高峰,且数据更新到点后稍迟)
    if CRON_HOUR is not None:
        # 每天固定 CRON_HOUR:START_MINUTE 跑一次
        trigger_kwargs = dict(trigger="cron", hour=CRON_HOUR, minute=START_MINUTE)
    elif INTERVAL_HOURS == 1:
        # 每小时 :MM 触发
        trigger_kwargs = dict(trigger="cron", minute=START_MINUTE)
    else:
        # 每 N 小时一次,从 :MM 起算
        trigger_kwargs = dict(
            trigger="cron",
            hour=f"*/{INTERVAL_HOURS}",
            minute=START_MINUTE,
        )

    _scheduler.add_job(
        run_hourly_job,
        **trigger_kwargs,
        id="sentinel_hourly",
        replace_existing=True,
        coalesce=True,                  # 错过的多次合并成 1 次
        misfire_grace_time=1800,        # 错过 30 分钟内还能补跑
        max_instances=1,                # 关键:避免上一轮没跑完就开下一轮
    )
    _scheduler.add_job(
        cleanup_zombies,
        trigger="interval", minutes=10,
        id="sentinel_cleanup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    _scheduler.start()
    _sched_desc = (f"daily at {CRON_HOUR:02d}:{START_MINUTE:02d}" if CRON_HOUR is not None
                   else f"every {INTERVAL_HOURS}h at :{START_MINUTE:02d}")
    log.info(
        "[sentinel-scheduler] started: %s %s, zombie_timeout=%dmin, cleanup=10min",
        _sched_desc, TIMEZONE, ZOMBIE_TIMEOUT_MIN,
    )


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("[sentinel-scheduler] stopped")


def maybe_start_from_env() -> None:
    """在 main.py 启动钩子里调.根据 env 决定是否启动."""
    if os.environ.get("GEO_SCHEDULER_LEADER", "0") == "1":
        log.info("[sentinel-scheduler] leader mode, starting…")
        start()
    else:
        log.info("[sentinel-scheduler] not leader (GEO_SCHEDULER_LEADER!=1), skip")
