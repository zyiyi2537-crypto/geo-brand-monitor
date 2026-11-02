"""Run five browser-service GEO checks and write a readable record.

This client uses only Python's standard library. Browser sessions stay in
Vigilath's browser service; no model API credentials are read here.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "telemetry-service"))

from app.qualified_report import build_report  # noqa: E402
from ai_verifier import check_model, verify_question  # noqa: E402
from session_status import session_ready  # noqa: E402


ENGINES = ("deepseek", "doubao", "yuanbao", "wenxin", "qwen")
ENGINE_DISPLAY_NAMES = {
    "deepseek": "DeepSeek",
    "doubao": "豆包",
    "yuanbao": "元宝",
    "wenxin": "文心一言",
    "qwen": "通义千问",
}
BEIJING = timezone(timedelta(hours=8))
DEFAULT_BASE_URL = "http://127.0.0.1:8091"


def _http_url(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空网址")
    url = value.strip()
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError(f"{label}包含空白或控制字符")
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
        valid = valid and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{label}必须是 http(s) 网址，且不能包含账号密码")
    return url


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and validate the small user-owned monitoring configuration."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取配置文件：{exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    return validate_config(raw)


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a task from either JSON or the desktop form."""
    brand = raw.get("brand")
    if not isinstance(brand, str) or not brand.strip():
        raise ValueError("brand 必须是非空文字")
    questions = raw.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions 必须是非空问题数组")
    clean_questions: list[str] = []
    for index, question in enumerate(questions, 1):
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"第 {index} 个问题必须是非空文字")
        question = question.strip()
        if question not in clean_questions:
            clean_questions.append(question)
    articles = raw.get("articles")
    if not isinstance(articles, list) or not articles:
        raise ValueError("articles 必须是非空文章数组")
    clean_articles: list[dict[str, str]] = []
    for index, article in enumerate(articles, 1):
        if not isinstance(article, dict):
            raise ValueError(f"第 {index} 篇文章必须是 JSON 对象")
        title = article.get("title", "")
        if not isinstance(title, str):
            raise ValueError(f"第 {index} 篇文章的 title 必须是文字")
        url = _http_url(article.get("url"), f"第 {index} 篇文章的 url")
        parsed = urlsplit(url)
        if parsed.hostname == "mp.toutiao.com" and "/preview" in parsed.path:
            raise ValueError(
                f"第 {index} 篇文章是头条后台预览地址，不能作为公开引用来源；"
                "请打开已发布文章，复制 www.toutiao.com/article/... 的公开网址"
            )
        clean_articles.append({
            "title": title.strip() or "已发布文章",
            "url": url,
        })
    return {"brand": brand.strip(), "questions": clean_questions, "articles": clean_articles}


def _request_json(url: str, payload: dict[str, str] | None, timeout: float) -> object:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _check_engines(base_url: str) -> None:
    try:
        status = _request_json(f"{base_url.rstrip('/')}/engines", None, 10)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"无法连接浏览器服务 /engines：{exc}") from exc
    if (not isinstance(status, dict) or not isinstance(status.get("engines"), list)
            or any(not isinstance(engine, str) for engine in status["engines"])):
        raise RuntimeError("浏览器服务 /engines 返回格式不正确")
    available = set(status["engines"])
    missing = [engine for engine in ENGINES if engine not in available]
    if missing:
        raise RuntimeError(f"浏览器服务未启用平台：{', '.join(missing)}。请先配置并启动五个平台")


def _check_sessions(base_url: str) -> list[dict[str, Any]]:
    """Run the browser service's active login probe before spending queries."""
    try:
        status = _request_json(f"{base_url.rstrip('/')}/sessions/verify", None, 45)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"监测前登录态检查失败：{exc}。请重启浏览器服务后重试") from exc
    if not isinstance(status, list):
        raise RuntimeError("监测前登录态检查返回格式不正确")
    return status


def _search_one(base_url: str, engine: str, query: str, timeout: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "engine": engine, "query": query, "answer": "", "citations": [], "error": None,
    }
    session_dir = os.environ.get("BROWSER_SESSION_DIR")
    if session_dir:
        session = Path(session_dir) / f"{engine}.json"
        if not session.is_file() or session.stat().st_size == 0:
            row["error"] = "未保存有效登录态，请重新登录并保存"
            return row
    try:
        response = _request_json(
            f"{base_url.rstrip('/')}/search", {"engine": engine, "query": query}, timeout,
        )
        if not isinstance(response, dict):
            raise ValueError("响应不是 JSON 对象")
        returned_engine = response.get("engine")
        if returned_engine not in {engine, ENGINE_DISPLAY_NAMES[engine]}:
            raise ValueError(f"响应平台与请求不一致：{returned_engine!r}")
        if response.get("query") != query:
            raise ValueError("响应的问题与请求不一致")
        answer = response.get("answer")
        citations = response.get("citations")
        error = response.get("error")
        if not isinstance(answer, str) or not isinstance(citations, list):
            raise ValueError("回答或引用字段格式不正确")
        if error is not None and not isinstance(error, str):
            raise ValueError("错误字段格式不正确")
        if any(not isinstance(item, dict) or not isinstance(item.get("url"), str)
               for item in citations):
            raise ValueError("引用字段格式不正确")
        if error or not answer.strip():
            row["error"] = error or "平台返回空回答"
        else:
            row["answer"] = answer
            row["citations"] = citations
            collection = response.get("citation_collection")
            if isinstance(collection, dict) and collection:
                row["citation_collection"] = collection
            for key in ("source_url", "screenshot", "page_evidence", "browser_checked_at"):
                if isinstance(response.get(key), str):
                    row[key] = response[key]
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        row["error"] = f"请求失败：{exc}"
    return row


def collect_results(
    config: dict[str, Any],
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 330,
    on_question: Callable[[list[dict[str, Any]], int], None] | None = None,
    check_sessions: bool = True,
    ai_settings: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Check each question on five platforms, with at most three concurrent calls.

    Each question finishes before the next starts, so the same platform never
    receives overlapping requests. Failed calls become explicit error rows.
    The callback receives completed rows after every question.
    """
    base_url = _http_url(base_url, "浏览器服务地址")
    if timeout <= 0:
        raise ValueError("timeout 必须大于零")
    _check_engines(base_url)
    if check_sessions:
        print("正在检查五个平台登录态，请稍候……", flush=True)
        sessions = _check_sessions(base_url)
        session_by_engine = {
            item.get("engine"): item for item in sessions if isinstance(item, dict)
        }
        failed_sessions = [engine for engine in ENGINES
                           if not session_ready(session_by_engine.get(engine, {}))]
        if failed_sessions:
            failed_names = []
            preflight_rows = []
            for query in config["questions"]:
                for engine in ENGINES:
                    state = session_by_engine.get(engine)
                    if engine in failed_sessions:
                        detail = (state or {}).get("detail") or (state or {}).get("status") or "未返回登录状态"
                        failed_names.append(f"{ENGINE_DISPLAY_NAMES[engine]}：{detail}")
                        error = f"登录预检未通过：{detail}"
                    else:
                        error = "未执行：其他平台未通过登录预检"
                    preflight_rows.append({
                        "engine": engine, "query": query, "answer": "", "citations": [],
                        "error": error,
                    })
            if on_question is not None:
                on_question(preflight_rows, 0)
            unique_failures = list(dict.fromkeys(failed_names))
            raise RuntimeError("监测前登录态检查未通过：" + "；".join(unique_failures)
                               + "。问题尚未发送。未登录时请登录并保存；检测失败或超时请重试检查")
        print("五个平台登录态检查通过。", flush=True)
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index, query in enumerate(config["questions"], 1):
            print(f"正在检查第 {index}/{len(config['questions'])} 个问题：{query}", flush=True)
            futures = [pool.submit(_search_one, base_url, engine, query, timeout)
                       for engine in ENGINES]
            question_rows = [future.result() for future in futures]
            rows.extend(question_rows)
            if ai_settings is not None:
                try:
                    verdicts = verify_question(
                        config=config, question=query, rows=question_rows, **ai_settings,
                    )
                    for row in question_rows:
                        if row["engine"] in verdicts:
                            row["ai_verdict"] = verdicts[row["engine"]]
                except (ValueError, RuntimeError, OSError) as exc:
                    print(f"第 {index} 个问题合并核对失败，正在分平台核对已保存的回答……", flush=True)
                    retries = [(row, pool.submit(
                        verify_question, config=config, question=query, rows=[row], **ai_settings,
                    )) for row in question_rows if not row.get("error") and row.get("answer")]
                    for row, future in retries:
                        try:
                            verdict = future.result()
                            row["ai_verdict"] = verdict[row["engine"]]
                        except (ValueError, RuntimeError, OSError, KeyError) as platform_exc:
                            row["ai_error"] = str(platform_exc)
                    # Only the platforms whose individual model requests also
                    # failed remain unfinished. Never resend platform questions.
            if on_question is not None:
                on_question(rows, index)
    return rows


def _run_directory(output_dir: str | Path, generated_at: datetime) -> Path:
    stamp = generated_at.astimezone(BEIJING).strftime("%Y%m%d-%H%M%S")
    directory = Path(output_dir) / f"geo-record-{stamp}-{uuid4().hex[:8]}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def _atomic_text(path: Path, content: str) -> None:
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(content, encoding="utf-8")
    os.replace(pending, path)


def save_run_progress(
    directory: Path,
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    completed_questions: int,
    generated_at: datetime,
    run_error: str | None = None,
) -> None:
    """Keep a readable report and raw answers available throughout a run."""
    total = len(config["questions"])
    preflight_blocked = completed_questions == 0 and bool(rows)
    notes = []
    if completed_questions == 0 and not rows:
        report = build_report(config, rows, generated_at, completed_questions=0)
        notes.append("监测已启动，正在等待第一个问题的五个平台结果。")
    else:
        report = build_report(config, rows, generated_at, completed_questions=completed_questions)
    if preflight_blocked:
        notes.append("运行状态：未开始：登录预检未通过，问题尚未发送。请在监测中心检查登录态。")
    elif run_error:
        status = "已中断"
        notes.append(f"运行状态：{status}，已完成 {completed_questions}/{total} 个问题。")
    elif completed_questions < total:
        notes.append(f"运行状态：进行中，已完成 {completed_questions}/{total} 个问题。")

    if notes:
        before, heading, audit = report.partition("\n## 浏览器证据与全部引用来源\n")
        report = before + "\n\n" + "\n\n".join(notes) + "\n" + heading + audit

    from app.qualified_report import render_html

    _atomic_text(directory / "results.json", json.dumps({
        "generated_at": generated_at.isoformat(),
        "brand": config["brand"],
        "config": {key: config[key] for key in ("brand", "articles", "questions")},
        "completed_questions": completed_questions,
        "total_questions": total,
        "run_error": run_error,
        "results": rows,
    }, ensure_ascii=False, indent=2))
    _atomic_text(directory / "record.md", report)
    _atomic_text(directory / "record.html", render_html(
        report, config=config, results=rows, report_directory=directory,
    ))
    print(f"进度 {completed_questions}/{total}，报告已保存：{directory / 'record.html'}", flush=True)


def _parse_time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("generated_at 必须是 ISO 8601 时间文字")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at 不是有效的 ISO 8601 时间") from exc


def _fallback_html(markdown: str) -> str:
    """Keep the HTML deliverable readable if the report module lacks a renderer."""
    parts: list[str] = []
    for line in markdown.splitlines():
        if not line.strip():
            continue
        level = len(line) - len(line.lstrip("#"))
        if 1 <= level <= 3 and line[level:level + 1] == " ":
            parts.append(f"<h{level}>{html.escape(line[level + 1:])}</h{level}>")
        else:
            escaped = html.escape(line)
            escaped = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', escaped)
            parts.append(f"<p>{escaped}</p>")
    body = "\n".join(parts)
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>GEO 引用监测记录</title><style>body{max-width:820px;margin:48px auto;"
            "padding:0 20px;font:16px/1.8 system-ui,sans-serif;color:#202631}"
            "h1,h2{line-height:1.35}p{margin:14px 0}a{overflow-wrap:anywhere}"
            "</style></head><body>" + body + "</body></html>\n")


def write_record(
    config: dict[str, Any],
    results: list[dict[str, Any]],
    output_dir: str | Path,
    generated_at: datetime | None = None,
) -> dict[str, Path]:
    """Write one immutable Markdown and HTML report in a unique run folder."""
    from app import qualified_report

    report = build_report(config, results, generated_at)
    renderer = getattr(qualified_report, "render_html", None)
    moment = generated_at or datetime.now(BEIJING)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BEIJING)
    stamp = moment.astimezone(BEIJING).strftime("%Y%m%d-%H%M%S")
    destination = Path(output_dir) / f"geo-record-{stamp}-{uuid4().hex[:8]}"
    destination.mkdir(parents=True, exist_ok=False)
    rendered = (renderer(report, config=config, results=results, report_directory=destination)
                if callable(renderer) else _fallback_html(report))
    markdown_path = destination / "record.md"
    html_path = destination / "record.html"
    markdown_path.write_text(report, encoding="utf-8")
    html_path.write_text(rendered, encoding="utf-8")
    return {"directory": destination, "markdown": markdown_path, "html": html_path}


def _read_results(path: str | Path) -> tuple[list[dict[str, Any]], datetime | None]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取结果文件：{exc}") from exc
    generated_at = None
    if isinstance(data, dict):
        generated_at = _parse_time(data.get("generated_at"))
        data = data.get("results")
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("结果文件必须是结果数组，或包含 results 数组的 JSON 对象")
    return data, generated_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="五平台 GEO 品牌与文章引用监测记录")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="实际询问五个平台并生成记录")
    run.add_argument("--config", required=True, help="品牌、问题和已发布文章的 JSON 文件")
    run.add_argument("--output-dir", required=True, help="报告输出根目录")
    run.add_argument("--browser-url", default=DEFAULT_BASE_URL, help="浏览器服务地址")
    run.add_argument("--sessions-verified", action="store_true",
                     help="登录态已由桌面界面刚刚通过主动检查")
    render = commands.add_parser("render", help="从已有结果 JSON 生成记录")
    render.add_argument("--config", required=True)
    render.add_argument("--results", required=True)
    render.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "run":
            generated_at = datetime.now(BEIJING)
            destination = _run_directory(args.output_dir, generated_at)
            progress_rows: list[dict[str, Any]] = []
            completed_questions = 0
            save_run_progress(destination, config, progress_rows, completed_questions, generated_at)

            def persist_progress(current: list[dict[str, Any]], completed: int) -> None:
                nonlocal progress_rows, completed_questions
                progress_rows = list(current)
                completed_questions = completed
                save_run_progress(destination, config, progress_rows, completed, generated_at)

            try:
                ai_settings = {
                    "base_url": os.environ.get("GEO_AI_BASE_URL", ""),
                    "model": os.environ.get("GEO_AI_MODEL", ""),
                    "api_key": os.environ.get("GEO_AI_API_KEY", ""),
                    "wire_api": os.environ.get("GEO_AI_WIRE_API", "chat"),
                }
                print("正在验证 AI 引用判定模型……", flush=True)
                if os.environ.get("GEO_AI_PREFLIGHT_OK") != "1":
                    check_model(**ai_settings)
                print(f"AI 引用判定模型已连接：{ai_settings['model']}", flush=True)
                results = collect_results(
                    config, args.browser_url, on_question=persist_progress,
                    check_sessions=not args.sessions_verified,
                    ai_settings=ai_settings,
                )
            except Exception as exc:
                # Preserve an actionable report even if the browser service dies
                # between questions or a platform adapter raises unexpectedly.
                save_run_progress(
                    destination, config, progress_rows, completed_questions, generated_at,
                    run_error=str(exc),
                )
                raise
        else:
            results, generated_at = _read_results(args.results)
        successes = sum(not row.get("error") and isinstance(row.get("answer"), str)
                        and bool(row["answer"].strip()) for row in results)
        if not successes and args.command != "run":
            raise RuntimeError("所有平台检查均失败或没有有效回答；未生成无命中记录。请检查登录态和浏览器服务")
        if args.command == "run":
            files = {
                "directory": destination,
                "markdown": destination / "record.md",
                "html": destination / "record.html",
            }
        else:
            files = write_record(config, results, args.output_dir, generated_at)
        print(f"已取得 {successes}/{len(results)} 条有效回答。")
        print(f"可阅读记录：{files['html']}")
        print(f"Markdown 记录：{files['markdown']}")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
