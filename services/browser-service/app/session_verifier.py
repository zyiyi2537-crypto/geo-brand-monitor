"""Read-only account checks. A chat input alone is not proof of authentication."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit


ACCOUNT_ENDPOINTS = {
    "doubao": ("accounts.doubao.com", "/passport/account/info/v2"),
    "qwen": ("api.qianwen.com", "/growth/user/benefit/user/member/info"),
}


def session_result(status: str, detail: str, logged_in: bool | None = None) -> dict:
    return {"status": status, "logged_in": logged_in, "detail": detail,
            "ready": status == "ok"}


def is_account_endpoint(engine: str, url: str) -> bool:
    target = urlsplit(url)
    endpoint = ACCOUNT_ENDPOINTS.get(engine)
    if endpoint is None:
        return False
    host, path = endpoint
    return target.hostname == host and target.path.rstrip("/") == path


def account_login_state(engine: str, status: int, payload: object) -> bool | None:
    """Return only an explicit account verdict; outages remain inconclusive."""
    if status == 401:
        return False
    if status != 200 or not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    def has_id(value: object) -> bool:
        return (isinstance(value, (str, int)) and not isinstance(value, bool)
                and str(value).strip() not in ("", "0"))

    if engine == "doubao":
        visitor = data.get("is_visitor_account")
        if visitor is True:
            return False
        if visitor is False and has_id(data.get("user_id") or data.get("user_id_str")):
            return True
    elif engine == "qwen":
        if data.get("isVisitor") is True or data.get("is_visitor_account") is True:
            return False
        if payload.get("success") is True and has_id(data.get("userId")):
            return True
    return None


_PAGE_SIGNALS = r"""() => {
    const visible = el => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none'
            && style.visibility !== 'hidden' && style.opacity !== '0';
    };
    const composers = [...document.querySelectorAll('textarea, [contenteditable="true"]')].filter(visible);
    const inputs = composers.filter(el => !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true');
    const labels = ['登录', '立即登录', '登录/注册', '登录 / 注册', '去登录', '请先登录', 'Login', 'Sign in'];
    const login = composers.some(el => /请.*登[录陆]|登[录陆]后|先登[录陆]/.test(
        [el.getAttribute('placeholder'), el.getAttribute('data-placeholder'), el.getAttribute('aria-label')].join(' ')))
        || [...document.querySelectorAll('button, [role="button"], a, span')]
            .some(el => visible(el) && labels.includes((el.innerText || '').trim()));
    const challenge = [...document.querySelectorAll(
        '[class*="captcha"], [id*="captcha"], iframe[src*="captcha"], [role="dialog"]'
    )].some(el => visible(el) && (el.tagName === 'IFRAME' ||
        /拖动滑块|安全验证|请完成验证|请完成下方验证/.test(el.innerText || '')));
    return {input: inputs.length > 0, login, challenge};
}"""


async def inspect_account_page(page, engine: str, url: str, *,
                               settle_timeout: float = 8, guest_grace: float = 4,
                               dismiss_popups=None) -> dict:
    """Observe the platform's own account response without sending any question."""
    account: bool | None = None
    account_failed = False
    pending: set[asyncio.Task] = set()

    async def read_response(response):
        nonlocal account, account_failed
        try:
            payload = await response.json() if response.status == 200 else None
            verdict = account_login_state(engine, response.status, payload)
            if verdict is not None:
                account = verdict
                account_failed = False
            else:
                account_failed = True
        except Exception:
            account_failed = True

    def on_response(response):
        if is_account_endpoint(engine, response.url):
            task = asyncio.create_task(read_response(response))
            pending.add(task)
            task.add_done_callback(pending.discard)

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=12000)
        if dismiss_popups is not None:
            try:
                await dismiss_popups(page)
            except Exception:
                pass
        started = time.monotonic()
        deadline = started + settle_timeout
        guest_since = None
        signals = {}
        while True:
            signals = await page.evaluate(_PAGE_SIGNALS)
            now = time.monotonic()
            if signals.get("challenge"):
                return session_result("challenge", "平台要求安全验证，请打开该平台完成验证", account)
            if account is False:
                return session_result("expired", "平台账号接口确认未登录或登录已失效", False)
            if account is True and signals.get("input") and not signals.get("login"):
                return session_result("ok", "账号接口确认已登录，对话输入可用", True)
            # Yuanbao currently exposes no stable account API for a read-only
            # check. A visible, enabled composer with no login prompt is the
            # strongest available signal there; do not turn that into an
            # indefinite 'unknown' result.
            if (engine not in ACCOUNT_ENDPOINTS and signals.get("input")
                    and not signals.get("login") and not account_failed):
                return session_result("ok", "对话输入可用，页面未显示登录入口", True)
            if signals.get("login") and account is None and not pending and not account_failed:
                guest_since = now if guest_since is None else guest_since
                if now - started >= guest_grace and now - guest_since >= min(1, guest_grace):
                    return session_result("expired", "页面显示登录入口，当前保存的会话未登录", False)
            else:
                guest_since = None
            if now >= deadline:
                break
            await asyncio.sleep(min(0.25, max(0, deadline - now)))
        if account is True:
            return session_result("unavailable", "账号已登录，但对话页面尚未就绪，请重试检查", True)
        detail = ("账号检查请求失败，无法确认登录状态，请重试检查" if account_failed
                  else "没有取得明确的账号登录信号，请重试检查")
        return session_result("unknown", detail)
    finally:
        page.remove_listener("response", on_response)
        for task in tuple(pending):
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def verify_account_session(adapter, engine: str, *, probe_new_chat: bool = False) -> dict:
    """Use exactly the same browser factory as a monitoring query; always close it."""
    page = ctx = None
    try:
        page, ctx = await adapter._create_hot_page()
        # Adapters expose popup dismissal as a page-bound helper. Keeping it
        # optional lets the generic account probe remain usable in tests and
        # for platforms that do not need it.
        result = await inspect_account_page(
            page, engine, adapter.CHAT_URL,
            dismiss_popups=getattr(adapter, "_dismiss_popups", None),
        )
        if probe_new_chat and result.get("status") == "ok":
            start_new_chat = getattr(adapter, "_start_new_chat", None)
            if start_new_chat is None:
                return session_result("unavailable", "平台不支持新对话预检，请重试检查", result.get("logged_in"))
            try:
                await start_new_chat(page)
            except Exception as exc:
                return session_result(
                    "unavailable",
                    f"登录已确认，但新对话预检失败：{str(exc)[:220]}",
                    result.get("logged_in"),
                )
            result["verification_method"] = "page_input_and_new_chat"
            result["detail"] = "账号已登录，对话输入和新对话均可用"
        return result
    except Exception:
        # A browser/navigation failure says nothing about whether the user logged in.
        return session_result("error", "登录检查页面加载失败，请检查网络后重试")
    finally:
        if ctx is not None:
            await adapter._close_hot_page(page, ctx)
