"""账号授权器 —— 服务端自动登录,抓登录态入池(全自动授权的核心)。

支持「密码自动登录」(deepseek 已验证):管理台填 账号+密码 → 这里 server 端
跑一次登录 → 抓 storage_state → POST 到账号池 upload 端点。掉登录后由守护进程
用存的密码再调本函数自动重登。

扫码协助、API Key 走别的路径(不在本模块)。qwen/文心 因反爬保留浏览器、且 qwen
无密码登录,故本模块当前主要服务 deepseek(及任何有密码登录的引擎)。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import httpx

_POOL_URL = os.environ.get("ENGINE_SESSION_POOL_URL", "").rstrip("/")
# upload 用 service token(browser-service 本就有,用于 check-out/in);后端 upload 已接受它
_SERVICE_TOKEN = os.environ.get("ENGINE_SESSION_SERVICE_TOKEN", "")

# 每引擎登录流程配置。只配「有密码登录」的引擎;扫码/无密码的不在这。
_LOGIN_CONFIG = {
    "deepseek": {
        "url": "https://chat.deepseek.com/sign_in",
        "pw_login_btn": ["text=Login with password", "text=密码登录"],
        "identifier_sel": "input:not([type=password])",
        "password_sel": "input[type=password]",
        "submit": ["button:has-text('登录')", "button:has-text('Log in')"],
        "success": [":text-is('New chat')", "text=开启新对话"],
        "bad_cred_text": "密码错误或账户不存在",
        "profile_platform": "Linux x86_64",
    },
    # wenxin 有账号密码登录入口,日后可加(但运行走浏览器路径)
}


def supports_password(engine: str) -> bool:
    return engine in _LOGIN_CONFIG


def _mask(identifier: str) -> str:
    """掩码展示用:foo@bar.com → fo***@bar.com。"""
    if "@" in identifier:
        u, d = identifier.split("@", 1)
        return (u[:2] + "***") + "@" + d
    return identifier[:3] + "***" + identifier[-2:] if len(identifier) > 5 else identifier


async def authorize_password(
    engine: str,
    identifier: str,
    password: str,
    *,
    proxy: Optional[dict] = None,
    upload: bool = True,
    ttl_days: int = 14,
) -> dict:
    """服务端用 账号+密码 自动登录,抓登录态(可选入池)。

    返回 {ok, error, account_handle, uploaded}。
    error:'unsupported'|'bad_credentials'|'login_failed'|'<异常>'。
    """
    cfg = _LOGIN_CONFIG.get(engine)
    if not cfg:
        return {"ok": False, "error": "unsupported"}

    from cloakbrowser import launch_context_async
    from .browser import get_context_options, _pick_profile

    # deepseek 等国内引擎从国内 IP 登录页有摩擦,默认走配置的出口代理(与运行时一致)。
    # caller 没传 proxy 且该引擎在 PROXY_ENGINES 里 → 自动从 env 构造。
    if proxy is None:
        proxy_engines = [e.strip() for e in os.environ.get("PROXY_ENGINES", "").split(",") if e.strip()]
        server = os.environ.get("ENGINE_PROXY_SERVER", "").strip()
        user = os.environ.get("ENGINE_PROXY_USER", "").strip()
        pw = os.environ.get("ENGINE_PROXY_PASS", "").strip()
        if engine in proxy_engines and server and user and pw:
            proxy = {"server": server, "username": f"{user}-session-authz", "password": pw}

    opts = get_context_options(profile=_pick_profile(platform_filter=cfg["profile_platform"]))
    if proxy:
        opts["proxy"] = proxy
    ctx = await launch_context_async(headless=False, **opts)
    pg = await ctx.new_page()
    try:
        await pg.goto(cfg["url"], wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        # 切到密码登录
        for s in cfg["pw_login_btn"]:
            try:
                el = pg.locator(s).first
                if await el.is_visible(timeout=3000):
                    await el.click()
                    break
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(2)
        await pg.locator(cfg["identifier_sel"]).first.fill(identifier)
        await pg.locator(cfg["password_sel"]).first.fill(password)
        await pg.locator(cfg["password_sel"]).first.press("Enter")
        await asyncio.sleep(1)
        for s in cfg["submit"]:
            try:
                b = pg.locator(s).first
                if await b.is_visible(timeout=1500):
                    await b.click()
                    break
            except Exception:  # noqa: BLE001
                pass
        # 轮询登录成功(最多 ~18s)
        ok = False
        for _ in range(9):
            await asyncio.sleep(2)
            cnt = 0
            for s in cfg["success"]:
                try:
                    cnt += await pg.locator(s).count()
                except Exception:  # noqa: BLE001
                    pass
            if cnt > 0:
                ok = True
                break
        if not ok:
            try:
                body = (await pg.inner_text("body"))[:200]
            except Exception:  # noqa: BLE001
                body = ""
            if cfg["bad_cred_text"] in body:
                return {"ok": False, "error": "bad_credentials"}
            return {"ok": False, "error": "login_failed"}

        state = await ctx.storage_state()
        handle = _mask(identifier)
        result = {"ok": True, "error": None, "account_handle": handle, "uploaded": False}
        # 加密存凭证(identifier+password),供掉线自动续期重登
        from . import crypto
        enc_cred = crypto.encrypt(json.dumps({"identifier": identifier, "password": password}))
        if upload and _POOL_URL and _SERVICE_TOKEN:
            try:
                with httpx.Client(timeout=20) as c:
                    r = c.post(
                        f"{_POOL_URL}/api/engine-sessions/upload",
                        headers={"X-Service-Token": _SERVICE_TOKEN, "Content-Type": "application/json"},
                        json={"engine": engine, "storage_state": state,
                              # 每账号唯一 source_label(=标识),避免 upsert 把多账号合并成一行
                              "source_label": f"authz:{identifier}", "account_handle": handle,
                              "ttl_days": ttl_days,
                              "auth_type": "password", "credentials": enc_cred},
                    )
                result["uploaded"] = (r.status_code == 201)
                if r.status_code != 201:
                    result["error"] = f"upload HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                result["error"] = f"upload failed: {e!r}"[:200]
        return result
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": repr(e)[:200]}
    finally:
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass
