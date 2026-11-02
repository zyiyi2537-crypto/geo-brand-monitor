"""扫码协助授权 —— 有状态二维码流(qwen/文心/元宝 等只能扫码的引擎)。

流程:
  start(engine) → 开一个浏览器到登录页 → 抓二维码图 → 返回 {session_id, qr_image}
  poll(session_id) → 已登录?→ 是:抓 storage_state 入池、关页、done;
                                否:二维码可能刷新 → 重抓返回 pending+qr_image
浏览器页在 start..poll 之间一直开着(模块级 _sessions 持有),过期(QR_TTL)清掉。

无密码(扫码),所以不存 credentials;auth_type='qr'。掉线后靠看板告警 + 人工重扫。
"""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
import time
from typing import Optional

import httpx

_POOL_URL = os.environ.get("ENGINE_SESSION_POOL_URL", "").rstrip("/")
_SERVICE_TOKEN = os.environ.get("ENGINE_SESSION_SERVICE_TOKEN", "")
_QR_TTL = int(os.environ.get("QR_SESSION_TTL_SEC", "300"))

# session_id -> {ctx, page, engine, created}
_sessions: dict = {}

# 每引擎:登录页 + 进入扫码前要点的按钮 + 二维码选择器 + 登录成功判定
_QR_CONFIG = {
    "qwen": {
        # 二维码在 passport.qianwen.com 的 iframe 里,需先点"扫码登录"tab
        "url": "https://www.qianwen.com/",
        "pre_click": ["text=登录", "text=立即登录"],
        "qr_tab": ["text=扫码登录", "text=扫码"],
        "qr_sel": ["[class*='QRCode']", "[class*='QRCodeWrapper']", "iframe[src*='passport']",
                   "canvas", "img[src*='qr']"],
        "success": ["textarea", "text=新建对话"],
        "login_hint": ["扫码", "二维码", "登录"],
    },
    "wenxin": {
        "url": "https://chat.baidu.com/",
        "pre_click": ["text=登录", "text=请登录"],
        "qr_sel": ["img[src*='qr']", "canvas", "[class*='qrcode']", "[class*='qrimg']"],
        "success": ["text=开启新对话", "textarea"],
        "login_hint": ["扫码", "二维码"],
    },
    "yuanbao": {
        "url": "https://yuanbao.tencent.com/",
        "pre_click": ["text=登录", "text=立即登录"],
        "qr_sel": ["iframe[src*='wx']", "img[src*='qr']", "canvas", "[class*='qrcode']"],
        "success": ["text=开启新对话", "textarea"],
        "login_hint": ["微信扫码", "二维码"],
    },
}


def supports_qr(engine: str) -> bool:
    return engine in _QR_CONFIG


async def _grab_qr(page, cfg) -> Optional[str]:
    """截二维码元素 → base64 PNG data URL;失败 None。"""
    for sel in cfg["qr_sel"]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=1500):
                png = await el.screenshot(timeout=3000)
                return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        except Exception:  # noqa: BLE001
            continue
    return None


async def _is_logged_in(page, cfg) -> bool:
    for sel in cfg["success"]:
        try:
            if await page.locator(sel).first.is_visible(timeout=800):
                # 仍显示登录二维码则不算(有些页登录后才隐藏)
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _gc():
    now = time.time()
    for sid in list(_sessions.keys()):
        if now - _sessions[sid]["created"] > _QR_TTL:
            s = _sessions.pop(sid, None)
            if s:
                asyncio.create_task(_close(s))


async def _close(s):
    try:
        await s["ctx"].close()
    except Exception:  # noqa: BLE001
        pass


async def qr_start(engine: str) -> dict:
    """开浏览器到登录页、抓二维码。返回 {session_id, qr_image, error}。"""
    cfg = _QR_CONFIG.get(engine)
    if not cfg:
        return {"error": "unsupported"}
    _gc()
    from cloakbrowser import launch_context_async
    from .browser import get_context_options, _pick_profile
    opts = get_context_options(profile=_pick_profile(platform_filter="Linux x86_64"))
    ctx = await launch_context_async(headless=False, **opts)
    page = await ctx.new_page()
    try:
        await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)
        for sel in cfg["pre_click"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    break
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(2)
        # 切到扫码 tab(部分引擎如 qwen 默认是手机/密码登录,需切)
        for sel in cfg.get("qr_tab", []):
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1500):
                    await el.click()
                    break
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(3)
        qr = await _grab_qr(page, cfg)
        if not qr:
            await ctx.close()
            return {"error": "qr_not_found"}
        sid = secrets.token_urlsafe(12)
        _sessions[sid] = {"ctx": ctx, "page": page, "engine": engine, "created": time.time()}
        return {"session_id": sid, "qr_image": qr, "error": None}
    except Exception as e:  # noqa: BLE001
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass
        return {"error": repr(e)[:200]}


async def qr_poll(session_id: str) -> dict:
    """轮询:done(已登录入池)/ pending(可能带新二维码)/ expired / error。"""
    s = _sessions.get(session_id)
    if not s:
        return {"status": "expired"}
    cfg = _QR_CONFIG[s["engine"]]
    page = s["page"]
    try:
        if await _is_logged_in(page, cfg):
            state = await s["ctx"].storage_state()
            uploaded = False
            err = None
            if _POOL_URL and _SERVICE_TOKEN:
                try:
                    with httpx.Client(timeout=20) as c:
                        r = c.post(
                            f"{_POOL_URL}/api/engine-sessions/upload",
                            headers={"X-Service-Token": _SERVICE_TOKEN, "Content-Type": "application/json"},
                            json={"engine": s["engine"], "storage_state": state,
                                  "source_label": f"qr:{session_id}", "auth_type": "qr",
                                  "ttl_days": 14},
                        )
                    uploaded = (r.status_code == 201)
                    if not uploaded:
                        err = f"upload HTTP {r.status_code}"
                except Exception as e:  # noqa: BLE001
                    err = f"upload failed: {e!r}"[:150]
            _sessions.pop(session_id, None)
            await _close(s)
            return {"status": "done", "uploaded": uploaded, "error": err}
        # 未登录 → 重抓二维码(可能已刷新)
        qr = await _grab_qr(page, cfg)
        return {"status": "pending", "qr_image": qr}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": repr(e)[:200]}
