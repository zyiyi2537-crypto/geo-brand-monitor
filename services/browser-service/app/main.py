"""Browser Engine Microservice.

ENV-driven: REGION, ENGINE_LIST, MAX_CONCURRENT_QUERIES control behavior.
Two instances (cn / global) run the same code with different ENV.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .engines.base import EngineAdapter, EngineResult, Citation
from .models import (
    SearchRequest, SearchResponse, CitationOut,
    FetchTitleRequest, FetchTitleResponse,
    SessionInfo, EnginesResponse, HealthResponse,
)
from .session_store import (
    load_storage_state, save_storage_state, clear_session, peek_session_exists,
    _read_session_json, _SESSION_DIR, list_local_accounts,
    create_local_account, delete_local_account, use_local_account,
    set_local_account_result, report_session_outcome, has_local_accounts,
    get_local_account_count,
)

# ── ENV configuration ──────────────────────────────────────────

REGION = os.environ.get("REGION", "cn")
ENGINE_LIST = [e.strip() for e in os.environ.get("ENGINE_LIST", "").split(",") if e.strip()]
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_QUERIES", "3"))
SEMAPHORE_TIMEOUT = int(os.environ.get("SEMAPHORE_TIMEOUT", "300"))

ENGINE_MODULE_MAP = {
    "deepseek": "app.engines.deepseek_browser:DeepSeekBrowserAdapter",
    "doubao":   "app.engines.doubao_browser:DoubaoBrowserAdapter",
    "qwen":     "app.engines.qwen_browser:QwenBrowserAdapter",
    "wenxin":   "app.engines.wenxin_browser:WenxinBrowserAdapter",
    "yuanbao":  "app.engines.yuanbao_browser:YuanbaoBrowserAdapter",
    "chatgpt":  "app.engines.chatgpt_browser:ChatGPTBrowserAdapter",
    "claude":   "app.engines.claude_browser:ClaudeBrowserAdapter",
    "gemini":   "app.engines.gemini_browser:GeminiBrowserAdapter",
    "grok":     "app.engines.grok_browser:GrokBrowserAdapter",
    "copilot":  "app.engines.copilot_browser:CopilotBrowserAdapter",
}

ENGINE_DISPLAY_NAMES = {
    "deepseek": "DeepSeek", "doubao": "豆包", "qwen": "通义千问",
    "wenxin": "文心一言", "yuanbao": "元宝", "chatgpt": "ChatGPT",
    "claude": "Claude", "gemini": "Gemini", "grok": "Grok",
    "copilot": "Copilot",
}

# ── Load adapters ──────────────────────────────────────────────

_adapters: dict[str, EngineAdapter] = {}
_semaphore: Optional[asyncio.Semaphore] = None

# D4 hot browser:engine_name → EngineSession.lazy 创建,首次 /search-hot 触发.
from .engine_session import EngineSession  # noqa: E402
_hot_sessions: dict[str, EngineSession] = {}
_hot_lock = asyncio.Lock()  # 保护 _hot_sessions dict


def _load_adapters() -> None:
    global _semaphore
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    for name in ENGINE_LIST:
        spec = ENGINE_MODULE_MAP.get(name)
        if not spec:
            print(f"[WARN] Unknown engine: {name}, skipping")
            continue
        module_path, class_name = spec.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            _adapters[name] = cls()
            print(f"[OK] Loaded engine: {name} ({class_name})")
        except Exception as e:
            print(f"[ERROR] Failed to load {name}: {e}")


# ── Snapshot paths ─────────────────────────────────────────────

_SNAPSHOT_BASE = Path(os.environ.get(
    "SNAPSHOT_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"),
))


# ── App lifecycle ──────────────────────────────────────────────

_agent_stop: Optional[asyncio.Event] = None
_agent_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent_stop, _agent_task
    _load_adapters()
    print(f"[START] region={REGION} engines={list(_adapters.keys())} max_concurrent={MAX_CONCURRENT}")
    # 配了 DISPATCH_CENTER_URL → 启动 worker agent loop(pull 模型:自注册 + 领任务)
    if os.environ.get("DISPATCH_CENTER_URL", "").strip():
        from .agent import agent_loop
        _agent_stop = asyncio.Event()
        _agent_task = asyncio.create_task(agent_loop(
            run_hot=run_hot_query,
            engines=list(_adapters.keys()),
            max_concurrency=MAX_CONCURRENT,
            breaker_engines=_breaker_engines,
            stop=_agent_stop,
        ))
        print(f"[START] dispatch worker agent → {os.environ['DISPATCH_CENTER_URL']}")
    # 登录态自动续期守护(只在指定的一台 worker 上跑,避免多机重复续同一账号)
    _refresh_stop = None
    _refresh_task = None
    if os.environ.get("ENGINE_REFRESH_ENABLED", "").strip() == "1":
        from .refresh_daemon import refresh_loop
        _refresh_stop = asyncio.Event()
        _refresh_task = asyncio.create_task(refresh_loop(_refresh_stop))
        print("[START] 登录态自动续期守护已启动")
    app.state._refresh_stop = _refresh_stop
    app.state._refresh_task = _refresh_task
    yield
    # 停续期守护
    if getattr(app.state, "_refresh_stop", None):
        app.state._refresh_stop.set()
    # 停 agent loop
    if _agent_stop:
        _agent_stop.set()
    if _agent_task:
        try:
            await asyncio.wait_for(_agent_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _agent_task.cancel()
    # D4:关掉所有 hot sessions
    for engine, sess in list(_hot_sessions.items()):
        try:
            await sess.close()
            print(f"[STOP] hot session {engine} closed")
        except Exception as e:
            print(f"[STOP] hot session {engine} close failed: {e}")
    # Cleanup: close browser if needed
    from .browser import close_browser
    await close_browser()
    print("[STOP] Browser service shut down")


app = FastAPI(title="Browser Service", version="0.1.0", lifespan=lifespan)


# ── API endpoints ──────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    from .browser import get_browser
    connected = False
    try:
        b = await get_browser()
        connected = b.is_connected()
    except Exception:
        pass
    return HealthResponse(
        status="healthy",
        browser_connected=connected,
        region=REGION,
        engine_count=len(_adapters),
        background_mode=os.environ.get("GEO_BROWSER_BACKGROUND", "").strip() == "1",
        desktop_isolated=os.environ.get("GEO_BROWSER_PRIVATE_DESKTOP", "").strip() == "1",
    )


@app.get("/debug/env")
async def debug_env():
    """Diagnostic: return DISPLAY, Xvfb status, and key env vars."""
    import subprocess
    display = os.environ.get("DISPLAY", "")
    xvfb_running = False
    xvfb_details = ""
    if display:
        try:
            r = subprocess.run(["xdpyinfo", "-display", display],
                               capture_output=True, text=True, timeout=5)
            xvfb_running = r.returncode == 0
            xvfb_details = r.stdout[:200] if xvfb_running else r.stderr[:200]
        except Exception as e:
            xvfb_details = str(e)
    return {
        "DISPLAY": display or "(not set)",
        "xvfb_running": xvfb_running,
        "xvfb_details": xvfb_details.strip() or "(no xdpyinfo)",
        "MAX_CONCURRENT_QUERIES": MAX_CONCURRENT,
        "REGION": REGION,
        "ENGINE_LIST": ENGINE_LIST,
    }


@app.get("/engines", response_model=EnginesResponse)
async def engines():
    return EnginesResponse(region=REGION, engines=list(_adapters.keys()))


@app.post("/authorize")
async def authorize(req: dict):
    """账号授权:密码自动登录 → 抓登录态入池。内网调用(管理台经后端代理)。
    body: {engine, identifier, password}。返回 {ok, error, account_handle, uploaded}。"""
    engine = (req or {}).get("engine")
    identifier = (req or {}).get("identifier")
    password = (req or {}).get("password")
    if not (engine and identifier and password):
        raise HTTPException(status_code=400, detail="engine/identifier/password required")
    from .authorizer import authorize_password, supports_password
    if not supports_password(engine):
        raise HTTPException(status_code=400, detail=f"engine {engine} 不支持密码自动登录(走扫码/APIKey)")
    return await authorize_password(engine, identifier, password)


@app.post("/authorize/qr/start")
async def authorize_qr_start(req: dict):
    """扫码协助授权-开始:开浏览器到登录页抓二维码。body {engine} → {session_id, qr_image}。"""
    engine = (req or {}).get("engine")
    from .qr_authorize import qr_start, supports_qr
    if not engine or not supports_qr(engine):
        raise HTTPException(status_code=400, detail=f"engine {engine} 不支持扫码授权")
    return await qr_start(engine)


@app.post("/authorize/qr/poll")
async def authorize_qr_poll(req: dict):
    """扫码协助授权-轮询:done(已登录入池)/ pending(可能带新二维码)/ expired。"""
    sid = (req or {}).get("session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    from .qr_authorize import qr_poll
    return await qr_poll(sid)


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    adapter = _adapters.get(req.engine)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {req.engine}")

    # Acquire semaphore with timeout
    try:
        await asyncio.wait_for(_semaphore.acquire(), timeout=SEMAPHORE_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Too many concurrent queries")

    # 全局 search timeout — 必须 > 各 engine 内部 wait timeout(目前 wenxin 内部
     # 180s typing wait + 30s stable double-check,加上 goto/输入/extract = 总耗
    # 可能到 240s)。默认 300s,通过 ENGINE_SEARCH_TIMEOUT 可调。
    search_timeout = int(os.environ.get("ENGINE_SEARCH_TIMEOUT", "300"))
    start = time.time()
    try:
        result: EngineResult = await asyncio.wait_for(
            adapter.search(req.query),
            timeout=search_timeout,
        )
        elapsed = time.time() - start
        print(
            f"[SEARCH] engine={req.engine} query={req.query[:30]!r} "
            f"ans_len={len(result.answer or '')} cites={len(result.citations or [])} "
            f"err={result.error!r} {elapsed:.1f}s"
        )
        err = (result.error or "").lower()
        if not result.error and (result.answer or "").strip():
            report_session_outcome(req.engine, result="success")
        elif not result.error:
            report_session_outcome(req.engine, result="empty_answer")
        elif any(token in err for token in ("captcha", "验证码", "安全验证", "验证中心")):
            report_session_outcome(req.engine, result="captcha", error_msg=result.error)
        elif any(token in err for token in ("rate limit", "rate_limit", "频率", "请求过于", "限流")):
            report_session_outcome(req.engine, result="rate_limited", error_msg=result.error)
        elif any(token in err for token in ("login", "登录", "未登录", "失效")):
            report_session_outcome(req.engine, result="login_lost", error_msg=result.error)
        elif any(token in err for token in ("timeout", "超时")):
            report_session_outcome(req.engine, result="timeout", error_msg=result.error)
        elif not (result.answer or "").strip():
            report_session_outcome(req.engine, result="empty_answer", error_msg=result.error)
        else:
            report_session_outcome(req.engine, result="crash", error_msg=result.error)
        # Build video URL if recording was captured
        video_url = None
        if hasattr(result, "video_path") and result.video_path:
            from pathlib import PurePosixPath
            vpath = PurePosixPath(result.video_path)
            video_url = f"/snapshot/{req.engine}/{vpath.name}"
        return SearchResponse(
            engine=result.engine,
            query=result.query,
            answer=result.answer or "",
            citations=[
                CitationOut(
                    url=c.url, domain=c.domain, title=c.title,
                    snippet=c.snippet, position=c.position,
                )
                for c in (result.citations or [])
            ],
            error=result.error,
            video_url=video_url,
            citation_collection=result.citation_collection,
            source_url=result.source_url,
        )
    except asyncio.TimeoutError:
        report_session_outcome(req.engine, result="timeout", error_msg=f"timeout ({search_timeout}s)")
        return SearchResponse(engine=req.engine, query=req.query, error=f"timeout ({search_timeout}s)")
    except Exception as e:
        report_session_outcome(req.engine, result="crash", error_msg=str(e))
        return SearchResponse(engine=req.engine, query=req.query, error=str(e))
    finally:
        _semaphore.release()


# fetch-title ─────────────────────────────────────────────────
# 给定任意 URL,用真实浏览器(带反检测)导航过去取页面标题.知乎等站点对裸 HTTP
# 请求返回 403,只有真实浏览器能拿到 <title>,所以引用标题回填统一走这里.
# 不依赖任何引擎登录态 — 用一次性 clean context.best-effort,抓不到返回空.

@app.post("/fetch-title", response_model=FetchTitleResponse)
async def fetch_title(req: FetchTitleRequest):
    try:
        await asyncio.wait_for(_semaphore.acquire(), timeout=SEMAPHORE_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Too many concurrent queries")

    from .browser import create_stealth_page
    page = context = None
    try:
        page, context = await create_stealth_page("_title_probe")
        await page.goto(req.url, wait_until="domcontentloaded", timeout=req.timeout_ms)
        title = ""
        try:
            title = (await page.title()) or ""
        except Exception:  # noqa: BLE001
            title = ""
        if not title.strip():
            # 退到 og:title / 首个 h1
            try:
                title = (await page.evaluate(
                    "() => {"
                    "  const m = document.querySelector('meta[property=\"og:title\"], meta[name=\"og:title\"]');"
                    "  if (m && m.getAttribute('content')) return m.getAttribute('content');"
                    "  const h = document.querySelector('h1');"
                    "  return (h && h.innerText) || '';"
                    "}"
                )) or ""
            except Exception:  # noqa: BLE001
                pass
        return FetchTitleResponse(url=req.url, title=(title or "").strip()[:300])
    except Exception as e:  # noqa: BLE001
        return FetchTitleResponse(url=req.url, title="", error=str(e))
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
        _semaphore.release()


# D4 hot-browser endpoint ─────────────────────────────────────
# 同 /search,但走 EngineSession 复用 browser context.engine 必须实现
# _prepare_page + _query_with_page(目前仅 deepseek).返回相同 SearchResponse.

async def _get_hot_session(engine: str) -> EngineSession:
    """lazy 创建 + init EngineSession(线程/任务 safe).未适配 hot protocol 抛 NotImplementedError."""
    adapter = _adapters.get(engine)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {engine}")
    async with _hot_lock:
        sess = _hot_sessions.get(engine)
        if sess is None:
            sess = EngineSession(engine, adapter)
            _hot_sessions[engine] = sess
    if not sess._initialized:
        await sess.init()
    return sess


_exit_ip_cache: dict = {}          # proxy_key -> (ip, ts);按账号 sticky 代理键缓存出口 IP
_EXIT_IP_TTL_SEC = 3600


def _proxy_dict_to_url(p: dict | None) -> str | None:
    """_engine_proxy() 的 {server,username,password} → httpx 代理 URL。"""
    if not p:
        return None
    server = p.get("server", "")
    scheme, sep, hostport = server.partition("://")
    if not sep:
        scheme, hostport = "http", server
    return f"{scheme}://{p['username']}:{p['password']}@{hostport}"


# 出口 IP 探测端点(多端点兜底):ipify 海外/JP 代理可达;ipip.net 国内可达。
_IP_ECHO_URLS = ["https://api.ipify.org", "https://ipinfo.io/ip", "https://myip.ipip.net"]
_IP_RE = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")


def _resolve_exit_ip(proxy_url: str | None) -> str | None:
    """解析当前 egress 的出口 IP(经代理或本机),按 proxy_url 缓存 1h。best-effort。
    多端点兜底:host(国内)走 ipify 不通时回落到 ipip.net。"""
    key = proxy_url or "__host__"
    now = time.time()
    hit = _exit_ip_cache.get(key)
    if hit and now - hit[1] < _EXIT_IP_TTL_SEC:
        return hit[0]
    import httpx
    ip = None
    for url in _IP_ECHO_URLS:
        try:
            with httpx.Client(timeout=8, proxy=proxy_url) as c:
                m = _IP_RE.search(c.get(url).text)
            if m:
                ip = m.group(1)
                break
        except Exception:  # noqa: BLE001
            continue
    if not ip:
        ip = hit[0] if hit else None
    if ip:
        _exit_ip_cache[key] = (ip, now)
    return ip


def _deepseek_http_sync(query: str, max_attempts: int = 6) -> dict:
    """deepseek 纯 HTTP 路径(无浏览器):check-out 拿 token → HTTP 查询 → check-in。
    check-out / check-in / HTTP 全在同一线程,保证 session_store 的 thread-local 一致。

    故障转移:login_lost / pow_failed 时隔离坏号并换新号重试(最多 max_attempts 次),
    而不是整条失败 —— 单个账号掉登录不影响这条查询(换池里其它号)。
    """
    from .session_store import load_storage_state, report_session_outcome
    from .deepseek_http import run_deepseek_http
    from .browser import _engine_proxy
    empty = {"engine": "deepseek", "query": query, "answer": "", "citations": [],
             "source_url": None, "video_url": None, "error": None}
    err = None
    res: dict = {}
    for attempt in range(max_attempts):
        state = load_storage_state("deepseek")  # 每次重新 check-out → 换到没被隔离的号
        if not state:
            return {**empty, "error": "no session available"}
        # 按账号 sticky 出口代理(honors PROXY_ENGINES);此前 HTTP 路径漏传 proxy,
        # 导致所有号从本机单 IP 直出 → 被 deepseek 风控集中禁言。现按账号粘定出口。
        proxy_url = _proxy_dict_to_url(_engine_proxy("deepseek", state))
        res = run_deepseek_http(state, query, proxy=proxy_url)
        err = res.get("error")
        exit_ip = _resolve_exit_ip(proxy_url)   # 该号实际出口 IP,随 check-in 回报落库
        # 映射成池子的 check-in 结果:login_lost→隔离;pow_failed→crash(不怪账号);empty→empty_answer
        if err == "login_lost":
            report_session_outcome("deepseek", result="login_lost", exit_ip=exit_ip)
        elif err == "rate_limited":
            # 账号被临时禁言(deepseek 风控)→ 冷却该号到 mute_until(不隔离不罚),换下一个号
            report_session_outcome("deepseek", result="rate_limited",
                                   error_msg="muted", rate_limited_until=res.get("mute_until"),
                                   exit_ip=exit_ip)
        elif err == "empty_answer":
            report_session_outcome("deepseek", result="empty_answer", exit_ip=exit_ip)
        elif err:
            report_session_outcome("deepseek", result="crash", error_msg=err, exit_ip=exit_ip)
        else:
            report_session_outcome("deepseek", result="success", exit_ip=exit_ip)
        # 只对"账号/瞬时"类错误换号重试;empty_answer 是真实结果不重试
        if err not in ("login_lost", "pow_failed", "rate_limited"):
            break
    return {"engine": "deepseek", "query": query, "answer": res.get("answer", ""),
            "citations": res.get("citations", []), "source_url": None, "video_url": None,
            "error": err}


_QWEN_QUERY_SCRIPT = os.path.join(os.path.dirname(__file__), "qwen_query.py")
_HEAL_PROBE_SCRIPT = os.path.join(os.path.dirname(__file__), "heal_probe.py")


class HealValidateIn(BaseModel):
    engine: str
    override: dict = {}
    query: str = "2026年最新国产手机推荐"


@app.post("/heal-validate")
async def heal_validate(req: HealValidateIn):
    """用提议的选择器临时覆盖跑一条 canary,验证是否真能出答案+引用(不落库)。
    目前支持 qwen(子进程 + QWEN_SELECTOR_OVERRIDE env)。返回 {ans_len, cites, error}。"""
    if req.engine != "qwen":
        return {"engine": req.engine, "error": "validate: only qwen supported", "ans_len": 0, "cites": 0}
    env = dict(os.environ)
    env["QWEN_SELECTOR_OVERRIDE"] = json.dumps(req.override, ensure_ascii=False)
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, _QWEN_QUERY_SCRIPT, req.query,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=130)
        lines = [ln for ln in out.decode("utf-8", "replace").splitlines() if ln.strip()]
        d = json.loads(lines[-1]) if lines else {}
        return {"engine": "qwen", "ans_len": len(d.get("answer") or ""),
                "cites": len(d.get("citations") or []), "error": d.get("error")}
    except asyncio.TimeoutError:
        if proc:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return {"engine": "qwen", "error": "validate timeout", "ans_len": 0, "cites": 0}
    except Exception as e:  # noqa: BLE001
        return {"engine": "qwen", "error": f"validate: {e}"[:200], "ans_len": 0, "cites": 0}


@app.post("/heal-probe")
async def heal_probe(req: SearchRequest):
    """自愈结构探针(browser-agent Phase 2):spawn heal_probe.py dump 引擎页面结构
    (可交互元素/答案容器/网络API),供后端 LLM 提议选择器。只读探测。"""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, _HEAL_PROBE_SCRIPT, req.engine,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=dict(os.environ),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        lines = [ln for ln in out.decode("utf-8", "replace").splitlines() if ln.strip()]
        if not lines:
            return {"engine": req.engine, "error": "heal-probe: no output"}
        return json.loads(lines[-1])
    except asyncio.TimeoutError:
        if proc:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return {"engine": req.engine, "error": "heal-probe timeout"}
    except Exception as e:  # noqa: BLE001
        return {"engine": req.engine, "error": f"heal-probe: {e}"[:200]}


async def _run_qwen_subprocess(query: str) -> dict:
    """spawn 一个干净 python 进程跑 app/qwen_query.py(进程内 create_stealth_page 与常驻
    hot 浏览器 context 冲突,独立进程才稳)。继承本进程 env,取最后一行 JSON。"""
    empty = {"engine": "qwen", "query": query, "answer": "", "citations": [],
             "source_url": None, "video_url": None, "error": None}
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, _QWEN_QUERY_SCRIPT, query,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=dict(os.environ),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        lines = [ln for ln in out.decode("utf-8", "replace").splitlines() if ln.strip()]
        if not lines:
            return {**empty, "error": "qwen subprocess: no output"}
        d = json.loads(lines[-1])
        return {"engine": "qwen", "query": query, "answer": d.get("answer", ""),
                "citations": d.get("citations", []), "source_url": None,
                "video_url": None, "error": d.get("error")}
    except asyncio.TimeoutError:
        if proc:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return {**empty, "error": "qwen subprocess timeout"}
    except Exception as e:  # noqa: BLE001
        return {**empty, "error": f"qwen subprocess: {e}"[:200]}


async def run_qwen_browser(query: str, max_attempts: int = 3) -> dict:
    """qwen 浏览器查询(子进程跑 + 失败转移)。空答案/掉线 → 换号重试(每次子进程重新
    check-out 账号),避开掉线的 qwen 号(扫码登录态常过期),与 deepseek failover 同理。"""
    d = {"engine": "qwen", "query": query, "answer": "", "citations": [],
         "source_url": None, "video_url": None, "error": "no attempt"}
    for _ in range(max_attempts):
        d = await _run_qwen_subprocess(query)
        if d.get("answer"):
            return d
        # 空/掉线/超时 → 换号再试
    return d


async def run_hot_query(engine: str, query: str) -> dict:
    """跑一条 hot query,返回 dispatch /result 需要的 dict 形状(供 /search-hot 与 worker agent 共用)。"""
    # deepseek 走纯 HTTP(无浏览器):DEEPSEEK_HTTP_MODE=1 时启用,结果与网页一致(含联网引用)
    from .deepseek_http import deepseek_http_enabled
    if engine == "deepseek" and deepseek_http_enabled():
        return await asyncio.to_thread(_deepseek_http_sync, query)
    # qwen 走 probe 实证的干净浏览器流程(绕开失配的 EngineSession 路径)
    if engine == "qwen":
        return await run_qwen_browser(query)

    search_timeout = int(os.environ.get("ENGINE_SEARCH_TIMEOUT", "300"))
    try:
        sess = await _get_hot_session(engine)
    except NotImplementedError as e:
        return {"engine": engine, "query": query, "answer": "", "citations": [],
                "source_url": None, "video_url": None, "error": f"not hot-adapted: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"engine": engine, "query": query, "answer": "", "citations": [],
                "source_url": None, "video_url": None, "error": f"hot-session init failed: {e}"}
    try:
        result: EngineResult = await asyncio.wait_for(sess.query(query), timeout=search_timeout)
    except asyncio.TimeoutError:
        return {"engine": engine, "query": query, "answer": "", "citations": [],
                "source_url": None, "video_url": None, "error": f"timeout ({search_timeout}s)"}
    except Exception as e:  # noqa: BLE001
        return {"engine": engine, "query": query, "answer": "", "citations": [],
                "source_url": None, "video_url": None, "error": str(e)}
    return {
        "engine": result.engine, "query": result.query, "answer": result.answer or "",
        "citations": [
            {"url": c.url, "domain": c.domain, "title": c.title,
             "snippet": c.snippet, "position": c.position}
            for c in (result.citations or [])
        ],
        "source_url": result.source_url, "video_url": None, "error": result.error,
        "citation_collection": result.citation_collection,
    }


def _breaker_engines() -> set[str]:
    """当前处于 IP 熔断中的引擎(claim 时跳过,让中心把任务留给别的 worker)。"""
    now = time.time()
    return {e for e, s in _hot_sessions.items() if getattr(s, "_breaker_until", 0) > now}


@app.post("/search-hot", response_model=SearchResponse)
async def search_hot(req: SearchRequest):
    adapter = _adapters.get(req.engine)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {req.engine}")

    # deepseek 纯 HTTP 分支(与 worker agent 的 run_hot_query 一致)
    from .deepseek_http import deepseek_http_enabled
    if req.engine == "deepseek" and deepseek_http_enabled():
        d = await asyncio.to_thread(_deepseek_http_sync, req.query)
        return SearchResponse(
            engine="deepseek", query=req.query, answer=d.get("answer", ""),
            citations=[CitationOut(**c) for c in d.get("citations", [])],
            error=d.get("error"),
        )
    # qwen 走 probe 实证的干净浏览器流程(绕开失配的 EngineSession 路径)
    if req.engine == "qwen":
        d = await run_qwen_browser(req.query)
        return SearchResponse(
            engine="qwen", query=req.query, answer=d.get("answer", ""),
            citations=[CitationOut(**c) for c in d.get("citations", [])],
            error=d.get("error"),
        )

    # lazy 创建 + init EngineSession(线程/任务 safe)
    async with _hot_lock:
        sess = _hot_sessions.get(req.engine)
        if sess is None:
            sess = EngineSession(req.engine, adapter)
            _hot_sessions[req.engine] = sess

    try:
        if not sess._initialized:
            await sess.init()  # 首次:launch + prepare
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        return SearchResponse(engine=req.engine, query=req.query, error=f"hot-session init failed: {e}")

    search_timeout = int(os.environ.get("ENGINE_SEARCH_TIMEOUT", "300"))
    start = time.time()
    try:
        result: EngineResult = await asyncio.wait_for(
            sess.query(req.query),
            timeout=search_timeout,
        )
        elapsed = time.time() - start
        print(
            f"[SEARCH-HOT] engine={req.engine} query={req.query[:30]!r} "
            f"ans_len={len(result.answer or '')} cites={len(result.citations or [])} "
            f"err={result.error!r} {elapsed:.1f}s q#{sess.query_count}"
        )
        return SearchResponse(
            engine=result.engine,
            query=result.query,
            answer=result.answer or "",
            citations=[
                CitationOut(
                    url=c.url, domain=c.domain, title=c.title,
                    snippet=c.snippet, position=c.position,
                )
                for c in (result.citations or [])
            ],
            error=result.error,
            video_url=None,  # hot 模式下视频暂不支持
            citation_collection=result.citation_collection,
            source_url=result.source_url,
        )
    except asyncio.TimeoutError:
        return SearchResponse(engine=req.engine, query=req.query, error=f"timeout ({search_timeout}s)")
    except Exception as e:
        return SearchResponse(engine=req.engine, query=req.query, error=str(e))


@app.get("/hot-sessions")
async def list_hot_sessions():
    """Debug: list active hot sessions + stats."""
    return [
        {
            "engine": eng,
            "initialized": s._initialized,
            "query_count": s.query_count,
            "last_used_at": s.last_used_at,
        }
        for eng, s in _hot_sessions.items()
    ]


@app.post("/hot-sessions/{engine}/rotate")
async def rotate_hot_session(engine: str, reason: str = "manual"):
    """Force rotate (close + reopen with fresh session)."""
    sess = _hot_sessions.get(engine)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"no hot session for engine={engine}")
    await sess.rotate(reason=reason)
    return {"engine": engine, "rotated": True}


# ── Session management ─────────────────────────────────────────

@app.get("/sessions", response_model=list[SessionInfo])
async def list_sessions():
    results = []
    for name in _adapters:
        results.append(SessionInfo(
            engine=name,
            has_session=peek_session_exists(name),  # 只读,绝不 check-out(状态查询不烧配额/不泄漏租约)
            name=ENGINE_DISPLAY_NAMES.get(name, name),
        ))
    return results


@app.get("/sessions/verify")
async def verify_sessions():
    """Actively verify saved sessions before a monitoring run.

    ``/sessions`` only reports whether a local file exists. This endpoint loads
    each saved browser context. Account-aware adapters require authentication
    evidence as well as a usable input; network failures are inconclusive.
    """
    timeout = float(os.environ.get("SESSION_VERIFY_TIMEOUT", "25"))

    async def verify_account(engine: str, adapter: EngineAdapter, account: dict) -> dict:
        account_id = account["account_id"]
        path = _SESSION_DIR / f"{engine}.json" if account_id == "default" else _SESSION_DIR / f"{engine}__{account_id}.json"
        base = {"engine": engine, "name": ENGINE_DISPLAY_NAMES.get(engine, engine)}
        if not path.is_file() or path.stat().st_size == 0:
            return {**base, "account_id": account_id, "label": account.get("label"),
                    "status": "missing", "logged_in": False, "detail": "未保存登录态"}
        try:
            state = _read_session_json(path)
            if (not isinstance(state, dict) or not isinstance(state.get("cookies"), list)
                    or not isinstance(state.get("origins", []), list)):
                raise ValueError("不是有效的浏览器会话")
            before = (path.stat().st_mtime_ns, path.stat().st_size)
        except (OSError, UnicodeError, ValueError) as exc:
            set_local_account_result(engine, account_id, "invalid_file")
            return {**base, "account_id": account_id, "label": account.get("label"),
                    "status": "invalid_file", "logged_in": False,
                    "detail": f"登录态文件无效：{exc}"}
        try:
            verifier = getattr(adapter, "verify_session", None)
            with use_local_account(engine, account_id):
                if verifier is not None:
                    result = await asyncio.wait_for(verifier(), timeout=timeout)
                else:
                    available = await asyncio.wait_for(adapter.is_available(), timeout=timeout)
                    result = {"status": "ok" if available else "unknown",
                              "logged_in": True if available else None,
                              "ready": bool(available),
                              "verification_method": "page_input",
                              "detail": "对话页面可用" if available else "对话页面不可用，无法确认登录状态"}
            after = (path.stat().st_mtime_ns, path.stat().st_size) if path.is_file() else None
            if before != after:
                result = {"status": "unknown", "logged_in": None, "ready": False,
                          "detail": "检查期间登录态已变更，请重新检查"}
            if result.get("status") == "ok":
                set_local_account_result(engine, account_id, "success")
            elif result.get("status") == "expired":
                set_local_account_result(engine, account_id, "login_lost")
            elif result.get("status") == "challenge":
                set_local_account_result(engine, account_id, "challenge")
            return {**base, "account_id": account_id, "label": account.get("label"),
                    **result, "checked_at": time.time()}
        except asyncio.TimeoutError:
            return {**base, "account_id": account_id, "label": account.get("label"),
                    "status": "timeout", "logged_in": None,
                    "detail": f"登录检查超过 {timeout:g} 秒"}
        except Exception as exc:  # noqa: BLE001
            return {**base, "account_id": account_id, "label": account.get("label"),
                    "status": "error", "logged_in": None, "detail": str(exc)}

    async def verify_one(engine: str, adapter: EngineAdapter) -> dict:
        accounts = [item for item in list_local_accounts(engine) if item.get("exists")]
        if accounts:
            checks = []
            for account in accounts:
                checks.append(await verify_account(engine, adapter, account))
            ready = next((item for item in checks if item.get("status") == "ok"
                          and item.get("logged_in") is True and item.get("ready", True)), None)
            if ready:
                aggregate = dict(ready)
                aggregate["detail"] = f"{ready.get('label') or ready['account_id']} 已登录；{sum(item.get('status') == 'ok' for item in checks)}/{len(checks)} 个账号可用"
            else:
                aggregate = dict(checks[0])
                aggregate["detail"] = "；".join(
                    f"{item.get('label') or item['account_id']}：{item.get('detail') or item.get('status')}"
                    for item in checks
                )
            aggregate["accounts"] = checks
            aggregate["account_count"] = len(checks)
            aggregate["usable_accounts"] = sum(
                item.get("status") == "ok" and item.get("logged_in") is True
                and item.get("ready", True) for item in checks
            )
            return aggregate

        account = {"account_id": "default", "label": "默认账号"}
        return await verify_account(engine, adapter, account)

    return await asyncio.gather(*(verify_one(engine, adapter)
                                  for engine, adapter in _adapters.items()))


@app.get("/sessions/{engine}", response_model=SessionInfo)
async def get_session(engine: str):
    if engine not in _adapters:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine}")
    return SessionInfo(
        engine=engine,
        has_session=peek_session_exists(engine),  # 只读,绝不 check-out
        name=ENGINE_DISPLAY_NAMES.get(engine, engine),
    )


class SessionUpload(BaseModel):
    storage_state: dict
    profile: dict | None = None  # Fingerprint profile for CF-gated engines


class LocalAccountCreate(BaseModel):
    label: str


@app.get("/sessions/{engine}/accounts")
async def get_local_accounts(engine: str):
    if engine not in _adapters:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine}")
    return list_local_accounts(engine)


@app.post("/sessions/{engine}/accounts")
async def add_local_account(engine: str, body: LocalAccountCreate):
    if engine not in _adapters:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine}")
    try:
        return create_local_account(engine, body.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/sessions/{engine}/accounts/{account_id}")
async def remove_local_account(engine: str, account_id: str):
    if engine not in _adapters:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine}")
    try:
        delete_local_account(engine, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "engine": engine, "account_id": account_id}


@app.put("/sessions/{engine}")
async def upload_session(engine: str, body: SessionUpload):
    if engine not in _adapters:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine}")
    save_storage_state(engine, body.storage_state)
    if body.profile:
        from .session_store import save_engine_profile
        save_engine_profile(engine, body.profile)
    return {"status": "ok", "engine": engine, "profile_saved": bool(body.profile)}


@app.delete("/sessions/{engine}")
async def delete_session(engine: str):
    if engine not in _adapters:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine}")
    clear_session(engine)
    return {"status": "ok", "engine": engine}


# ── Snapshot download ──────────────────────────────────────────

@app.get("/snapshot/{engine}/{filename:path}")
async def download_snapshot(engine: str, filename: str):
    if engine not in _adapters:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine}")
    filepath = _SNAPSHOT_BASE / engine / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return FileResponse(
        path=str(filepath),
        media_type="video/webm",
        filename=filename,
    )
