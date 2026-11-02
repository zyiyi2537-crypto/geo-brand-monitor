"""Phase D.1 — 内容自动生成定时任务.

每小时整点跑一次,扫所有 auto_generate_enabled=True 的 topic,看本小时是否匹配
其 auto_generate_time(只比较 HH 部分,粒度小时;时区 Asia/Shanghai)。匹配且
当天还没生成过就触发 content_generator.schedule_generation()。

幂等保护:用 auto_generate_last_run_at 当 "今天已跑标记"。今天比上一次跑批日期晚就触发;
所以同一天即便 cron 触发 24 次也只跑一次。

由 sentiment_scheduler 共用的 APScheduler 进程托管 — 也就是说只有 GEO_SCHEDULER_LEADER=1
的实例才会跑这条 job.

环境变量:
    GEO_CONTENT_SCHED_TZ       默认 Asia/Shanghai
    GEO_CONTENT_SCHED_MINUTE   每小时第几分钟触发,默认 7(避开 sentinel 的 :05)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from geo.database import SessionLocal
from geo.models.ai_telemetry import AiTelemetryTopicORM
from geo.services.content_generator import schedule_generation

log = logging.getLogger(__name__)

TIMEZONE = os.environ.get("GEO_CONTENT_SCHED_TZ", "Asia/Shanghai")
START_MINUTE = int(os.environ.get("GEO_CONTENT_SCHED_MINUTE", "7"))
# 发文计划「持续滚动」续期 — 每天该小时扫一次,对 runway 不足的计划接排下一个月.
REFILL_HOUR = int(os.environ.get("GEO_PLAN_REFILL_HOUR", "3"))
# 按 publish_date 自动发布 — 每天该小时扫一次,把到期且未发布的稿发出去.默认 11 点.
PUBLISH_HOUR = int(os.environ.get("GEO_AUTO_PUBLISH_HOUR", "11"))
# 总闸:默认开(=1).生产侧设 0 可一键停掉所有按排期自动发布(应急用,不动 DB).
AUTO_PUBLISH_ENABLED = os.environ.get("GEO_AUTO_PUBLISH_ENABLED", "1") == "1"


def _now_local() -> datetime:
    """返回 Asia/Shanghai 当前时间(naive)。

    SQLite 把 datetime 存 naive,这里也用 naive 时间和库里 last_run_at 比较;
    但 last_run_at 存的是 UTC,所以转一次。
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TIMEZONE))
    except Exception:  # noqa: BLE001
        # 兜底:UTC+8
        return datetime.utcnow() + timedelta(hours=8)


def _utc_today_start_in_tz() -> datetime:
    """返回今天本地 0 点对应的 UTC naive datetime,用于判断 last_run_at 是不是"今天跑过"."""
    local = _now_local()
    # 本地 0 点
    if local.tzinfo:
        local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        utc_midnight = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        utc_midnight = (local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8))
    return utc_midnight


def hourly_tick() -> None:
    """APScheduler 每小时触发的入口."""
    db: Session = SessionLocal()
    try:
        now = _now_local()
        today_start_utc = _utc_today_start_in_tz()
        log.info("[content-cron] tick hour=%02d", now.hour)
        rows = (
            db.query(AiTelemetryTopicORM)
              .filter(AiTelemetryTopicORM.auto_generate_enabled.is_(True))
              .filter(AiTelemetryTopicORM.submission_status == "approved")
              .all()
        )
        triggered = 0
        for t in rows:
            try:
                hh, _, _ = (t.auto_generate_time or "09:00").partition(":")
                target_hour = int(hh)
            except ValueError:
                continue
            if target_hour != now.hour:
                continue
            # 今天跑过就跳过
            if t.auto_generate_last_run_at and t.auto_generate_last_run_at >= today_start_utc:
                continue
            count = max(1, min(20, int(t.auto_generate_count or 3)))
            log.info("[content-cron] firing topic=%d count=%d", t.id, count)
            schedule_generation(
                topic_id=t.id, max_docs=count, mark_auto_run=True,
            )
            triggered += 1
        log.info("[content-cron] %d topics triggered", triggered)
    finally:
        db.close()


def refill_tick() -> None:
    """每日触发:扫已审批 + 自动生成的 topic,对发文计划 runway 不足的接排下一个月.

    幂等由 extend_plan_one_month 内部的 PLAN_REFILL_LEAD_DAYS 阈值保证(runway 够就跳过),
    所以每天扫一次,每个 topic 实际约每月续一次.
    """
    from geo.api.admin_review import extend_plan_one_month
    from geo.models.ai_telemetry import AiTelemetryTopicExecutionPlanORM

    db: Session = SessionLocal()
    try:
        topics = (
            db.query(AiTelemetryTopicORM)
              .filter(AiTelemetryTopicORM.auto_generate_enabled.is_(True))
              .filter(AiTelemetryTopicORM.submission_status == "approved")
              .all()
        )
        refilled = 0
        for t in topics:
            plan = (
                db.query(AiTelemetryTopicExecutionPlanORM)
                  .filter(AiTelemetryTopicExecutionPlanORM.topic_id == t.id)
                  .order_by(AiTelemetryTopicExecutionPlanORM.id.desc())
                  .first()
            )
            if not plan or plan.status not in ("draft", "confirmed"):
                continue
            try:
                n = extend_plan_one_month(db, plan)
            except Exception:  # noqa: BLE001
                log.exception("[plan-refill] topic=%d failed", t.id)
                db.rollback()
                continue
            if n:
                refilled += 1
                log.info("[plan-refill] topic=%d +%d rows", t.id, n)
        log.info("[plan-refill] %d plans extended", refilled)
    finally:
        db.close()


def _mark_platform_target(d) -> None:
    """把 doc.platform 追加一条到 publish_targets_json,标记「系统自动发布到此平台」.

    marked_by=0 表示系统自动(非某个 admin 手点).与 admin 手动 publish 同一份字段,
    前端按已发布平台渲染时无需区分来源.
    """
    try:
        targets = json.loads(d.publish_targets_json or "[]")
    except Exception:  # noqa: BLE001
        targets = []
    if not isinstance(targets, list):
        targets = []
    targets.append({
        "platform": d.platform or "",
        "media": "",
        "url": "",
        "marked_at": datetime.utcnow().isoformat(),
        "marked_by": 0,
    })
    d.publish_targets_json = json.dumps(targets, ensure_ascii=False)


async def _run_publish() -> None:
    """扫到期稿并发布.单 event loop 内串行 await(Mediumsly publisher 自带并发闸)."""
    from geo.models.ai_telemetry import (
        AiTelemetryTopicExecutionPlanORM,
        AiTelemetryTopicORM,
        TopicGeneratedDocORM,
    )
    from geo.models.user import UserORM
    from geo.services import mediumsly_publisher

    today = _now_local().date()
    db: Session = SessionLocal()
    published = 0
    try:
        topics = (
            db.query(AiTelemetryTopicORM)
              .filter(AiTelemetryTopicORM.auto_publish_enabled.is_(True))
              .filter(AiTelemetryTopicORM.submission_status == "approved")
              .all()
        )
        for t in topics:
            plan = (
                db.query(AiTelemetryTopicExecutionPlanORM)
                  .filter(AiTelemetryTopicExecutionPlanORM.topic_id == t.id)
                  .order_by(AiTelemetryTopicExecutionPlanORM.id.desc())
                  .first()
            )
            if not plan or plan.status not in ("draft", "confirmed"):
                continue
            try:
                items = json.loads(plan.publishing_plan_json or "[]")
            except Exception:  # noqa: BLE001
                items = []
            # 到期(publish_date <= 今天)的 plan_item id 集合 — 含历史欠发的补发.
            due_ids: set[str] = set()
            for it in items:
                if not isinstance(it, dict):
                    continue
                pd = str(it.get("publish_date") or "")[:10]
                if not pd:
                    continue
                try:
                    if date.fromisoformat(pd) <= today and it.get("id"):
                        due_ids.add(str(it["id"]))
                except ValueError:
                    continue
            if not due_ids:
                continue
            docs = (
                db.query(TopicGeneratedDocORM)
                  .filter(TopicGeneratedDocORM.topic_id == t.id)
                  .filter(TopicGeneratedDocORM.plan_item_id.in_(list(due_ids)))
                  .filter(TopicGeneratedDocORM.status.notin_(("published", "rejected")))
                  .all()
            )
            if not docs:
                continue
            user = db.get(UserORM, t.user_id)
            for d in docs:
                if not (d.body_markdown or "").strip():
                    continue  # 没正文(生成失败 / 占位)不发
                _mark_platform_target(d)
                # 真发 Mediumsly;token 没配 → 降级为只标记,不阻塞.
                if user and user.email:
                    try:
                        result = await mediumsly_publisher.push(d, user, t)
                        d.mediumsly_post_id = result.post_id
                        d.mediumsly_url = result.url
                        d.mediumsly_pushed_at = datetime.utcnow()
                        d.mediumsly_last_error = None
                    except mediumsly_publisher.MediumslyNotConfigured:
                        pass  # 未配 token,只标记 publish_targets
                    except mediumsly_publisher.MediumslyPostGone:
                        d.mediumsly_post_id = None
                        d.mediumsly_last_error = (
                            "Mediumsly post deleted upstream — id cleared, retry"
                        )
                    except mediumsly_publisher.MediumslyError as e:
                        d.mediumsly_last_error = f"{e.code or 'ERROR'}: {e}"
                        log.warning("[publish-cron] doc=%s push failed: %s",
                                    d.id, d.mediumsly_last_error)
                # 与 admin 手动 publish 同语义:外发失败也置 published,错误留 mediumsly_last_error.
                d.status = "published"
                published += 1
            db.commit()
            if docs:
                log.info("[publish-cron] topic=%d published %d docs", t.id, len(docs))
        log.info("[publish-cron] %d docs published total", published)
    finally:
        db.close()


def publish_tick() -> None:
    """每天 PUBLISH_HOUR 触发:把发文计划里到期且未发布的稿按排期发出去.

    选稿:auto_publish_enabled 的已审批 topic → 最新执行计划 →
          publish_date<=今天 的 plan_item → 关联且 status∉(published,rejected) 且有正文的 doc.
    发布:真发 Mediumsly(token 缺失降级为只标记)+ 写 publish_targets 标记平台,置 published.
    幂等:published 的 doc 下次不再入选(status 过滤),天然防重发.
    """
    if not AUTO_PUBLISH_ENABLED:
        log.info("[publish-cron] GEO_AUTO_PUBLISH_ENABLED!=1, skip")
        return
    try:
        asyncio.run(_run_publish())
    except Exception:  # noqa: BLE001
        log.exception("[publish-cron] crashed")


_scheduler = None


def attach(scheduler) -> None:
    """挂载到外部 APScheduler 实例(供其它进程内 scheduler 共用)."""
    scheduler.add_job(
        hourly_tick,
        trigger="cron", minute=START_MINUTE,
        id="content_auto_generate_hourly",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=1800,
        max_instances=1,
    )
    scheduler.add_job(
        refill_tick,
        trigger="cron", hour=REFILL_HOUR, minute=0,
        id="plan_monthly_refill",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    scheduler.add_job(
        publish_tick,
        trigger="cron", hour=PUBLISH_HOUR, minute=0,
        id="content_auto_publish",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    log.info("[content-cron] attached: content @:%02d, plan-refill @%02d:00, "
             "auto-publish @%02d:00",
             START_MINUTE, REFILL_HOUR, PUBLISH_HOUR)


def start() -> None:
    """独立启动一个 APScheduler 实例,只挂 content cron.

    跟 sentiment_scheduler 解耦 — 测试 / 生产环境里舆情已经有独立的
    geo-sentinel.service 跑,backend 进程不能再叠加 sentiment hourly job,
    否则任务会重复执行。所以内容生成走自己的 leader env。
    """
    global _scheduler
    if _scheduler is not None:
        log.warning("[content-scheduler] already started")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        log.error("[content-scheduler] APScheduler not installed; "
                  "run: pip install 'apscheduler[sqlalchemy]'")
        return
    _scheduler = BackgroundScheduler(timezone=TIMEZONE)
    attach(_scheduler)
    _scheduler.start()
    log.info("[content-scheduler] started independently (tz=%s)", TIMEZONE)


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("[content-scheduler] stopped")


def maybe_start_from_env() -> None:
    """在 main.py 的 startup hook 里调.GEO_CONTENT_SCHEDULER_LEADER=1 才起."""
    if os.environ.get("GEO_CONTENT_SCHEDULER_LEADER", "0") == "1":
        log.info("[content-scheduler] leader mode, starting…")
        start()
    else:
        log.info("[content-scheduler] not leader, skip")
