"""Job runner: executes monitoring jobs with the desktop pipeline unchanged.

The pipeline is the same one the desktop GUI drives through tools/geo_record:

    browser-service (five real platform logins)
      -> collect_results (per-question five-platform fetch, incremental save)
        -> verify_question (AI verdict per question: brand mention, citation,
                            sentiment, evidence quote, other brands)
          -> save_run_progress (record.html / record.md / results.json)

This module only adds the server shell around it: a queue, tenant-scoped
report directories, and an optional quota bridge to the subscription site.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from . import config

ROOT = config.ROOT
# tools/ modules import each other as top-level names and reach the report
# renderer through the telemetry-service path, exactly as the desktop does.
sys.path.insert(0, str(ROOT / "tools"))

import geo_record  # noqa: E402
from agent_planner import generate_questions  # noqa: E402
from ai_verifier import check_model  # noqa: E402

BEIJING = timezone(timedelta(hours=8))


class QuotaDenied(RuntimeError):
    """The subscription site refused the job's quota request."""


def request_quota(tenant_id: str, question_count: int) -> None:
    """Ask the subscription site whether this tenant may start a job."""
    if not config.MONITOR_QUOTA_URL:
        return
    body = json.dumps({
        "tenant_id": tenant_id,
        "questions": question_count,
        "cost": {"platform_queries": question_count * 5, "ai_verdicts": question_count},
    }, ensure_ascii=False).encode("utf-8")
    request = Request(
        config.MONITOR_QUOTA_URL, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": f"Bearer {config.MONITOR_QUOTA_TOKEN}"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        allowed = payload.get("allowed") if isinstance(payload, dict) else None
        if allowed is True:
            return
        reason = payload.get("reason") if isinstance(payload, dict) else None
        raise QuotaDenied(str(reason or "订阅额度不足或套餐未开通"))
    except QuotaDenied:
        raise
    except Exception as exc:  # noqa: BLE001 - network to the billing bridge
        if config.MONITOR_QUOTA_FAIL_MODE == "allow":
            return
        raise QuotaDenied(f"配额检查失败，本次未启动监测：{exc}") from exc


def generate_questions_for(brand: str, article_urls: list[str], keywords: list[str]) -> list[str]:
    """Reuse the desktop planner; the judge model drafts the questions."""
    return generate_questions(
        brand=brand, article_urls=article_urls, keywords=keywords,
        **config.ai_settings(),
    )


def preflight_model() -> None:
    """Fail fast before any platform question is sent (desktop behaviour)."""
    check_model(**config.ai_settings())


def run_job(store, job: dict[str, Any]) -> None:
    """Execute one queued job to completion or failure, always saving reports."""
    job_id = job["id"]
    tenant_id = job["tenant_id"]
    config_payload = job["config"]
    generated_at = datetime.now(BEIJING)
    safe_tenant = re.sub(r"[^\w.-]", "_", tenant_id) or "tenant"
    directory = config.REPORTS_DIR / safe_tenant / job_id
    directory.mkdir(parents=True, exist_ok=True)

    progress_rows: list[dict[str, Any]] = []
    completed_questions = 0
    geo_record.save_run_progress(directory, config_payload, progress_rows,
                                 completed_questions, generated_at)
    store.update_progress(job_id, completed_questions, directory)

    def persist_progress(current: list[dict[str, Any]], completed: int) -> None:
        nonlocal progress_rows, completed_questions
        progress_rows = list(current)
        completed_questions = completed
        geo_record.save_run_progress(directory, config_payload, progress_rows,
                                     completed, generated_at)
        store.update_progress(job_id, completed, directory)

    try:
        # Quota is checked once at submission time (create_job); the runner
        # must not re-check or the billing bridge would meter a job twice.
        preflight_model()
        geo_record.collect_results(
            config_payload, config.BROWSER_SERVICE_URL,
            timeout=config.MONITOR_JOB_TIMEOUT,
            on_question=persist_progress,
            check_sessions=True,
            ai_settings=config.ai_settings(),
        )
    except Exception as exc:  # noqa: BLE001 - any failure must keep a readable report
        try:
            geo_record.save_run_progress(directory, config_payload, progress_rows,
                                         completed_questions, generated_at,
                                         run_error=str(exc))
        except Exception:  # noqa: BLE001
            pass
        store.finish(job_id, status="failed", report_dir=directory,
                     error=str(exc)[:500])
        return
    store.finish(job_id, status="done", report_dir=directory)


class Worker:
    """Claim queued jobs and run them with bounded concurrency.

    Platform queries stay serialised inside one job (the pipeline never sends
    overlapping requests to the same platform); the worker count here only
    controls how many jobs run in parallel. Default 1 keeps the shared
    browser-service fair across tenants.
    """

    def __init__(self, store) -> None:
        self._store = store
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        count = max(1, config.MONITOR_WORKERS)
        for index in range(count):
            thread = threading.Thread(target=self._loop, name=f"monitor-worker-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._store.claim_next()
            except Exception:  # noqa: BLE001 - store hiccup, retry later
                job = None
            if job is None:
                self._stop.wait(2.0)
                continue
            run_job(self._store, job)


def fail_interrupted(store) -> int:
    """On startup, close jobs a previous process left mid-run.

    Partial reports stay on disk; the job is marked failed with an actionable
    error instead of being silently re-run (questions would be re-sent).
    """
    count = 0
    for job in store.list_all(limit=200):
        if job["status"] == "running":
            store.finish(job["id"], status="failed",
                         error="服务重启，任务中断。阶段性报告已保留；如需完整结果请新建任务重跑")
            count += 1
    return count
