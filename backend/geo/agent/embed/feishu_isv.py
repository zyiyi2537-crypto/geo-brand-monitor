"""飞书 ISV 接入器(应用市场应用,多租户)。

与自建模式(im_feishu.py)并存。差异:
- 一个 app(我们的)服务无数企业;鉴权走 ISV 三段式:
  app_ticket(飞书定时推)→ app_access_token → tenant_access_token(按 tenant_key)。
- 每个使用者各自绑定:(tenant_key, open_id) → Vigilath account_id;未绑定提示发"绑定码"。

我方 ISV 应用凭证走环境变量(我们自己一套,非每客户):
  FEISHU_ISV_APP_ID / FEISHU_ISV_APP_SECRET / FEISHU_ISV_VERIFY_TOKEN / FEISHU_ISV_ENCRYPT_KEY
回调地址(飞书 ISV 应用里配一次):<host>/api/agent/im/feishu-isv/callback
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy.orm import Session

from geo.agent.deps import AgentDeps
from geo.agent.embed.im_feishu import _build_card_v2, _has_table, _maybe_decrypt, _to_feishu_md, log
from geo.database import SessionLocal
from geo.models.agent import AgentIMBindCodeORM, AgentIMUserBindingORM, AgentISVStateORM

router = APIRouter(prefix="/agent/im")
FEISHU_BASE = "https://open.feishu.cn/open-apis"

_app_token_cache: tuple[str, float] | None = None
_tenant_token_cache: dict[str, tuple[str, float]] = {}
_seen_events: dict[str, float] = {}


def _isv() -> tuple[str, str, str, str]:
    return (
        (os.environ.get("FEISHU_ISV_APP_ID") or "").strip(),
        (os.environ.get("FEISHU_ISV_APP_SECRET") or "").strip(),
        (os.environ.get("FEISHU_ISV_VERIFY_TOKEN") or "").strip(),
        (os.environ.get("FEISHU_ISV_ENCRYPT_KEY") or "").strip(),
    )


def _save_app_ticket(db: Session, app_id: str, ticket: str) -> None:
    row = db.query(AgentISVStateORM).filter(AgentISVStateORM.app_id == app_id).first()
    if row is None:
        row = AgentISVStateORM(app_id=app_id)
        db.add(row)
    row.app_ticket = ticket
    row.updated_at = datetime.utcnow()
    db.commit()
    log.info("app_ticket 已更新(app_id=%s)", app_id)


def _get_app_ticket(db: Session, app_id: str) -> str:
    row = db.query(AgentISVStateORM).filter(AgentISVStateORM.app_id == app_id).first()
    return row.app_ticket if row else ""


async def _resend_app_ticket(app_id: str, app_secret: str) -> None:
    """没有 app_ticket 时,主动让飞书重推一次(它会 POST 到我们回调)。"""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{FEISHU_BASE}/auth/v3/app_ticket/resend",
                         json={"app_id": app_id, "app_secret": app_secret})
    except Exception:  # noqa: BLE001
        pass


async def _app_access_token(db: Session) -> str | None:
    global _app_token_cache
    if _app_token_cache and _app_token_cache[1] - 60 > time.monotonic():
        return _app_token_cache[0]
    app_id, app_secret, _, _ = _isv()
    ticket = _get_app_ticket(db, app_id)
    if not ticket:
        await _resend_app_ticket(app_id, app_secret)
        log.warning("无 app_ticket,已请求飞书重推;稍后重试")
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{FEISHU_BASE}/auth/v3/app_access_token",
                             json={"app_id": app_id, "app_secret": app_secret, "app_ticket": ticket})
        d = r.json()
        tok = d.get("app_access_token")
        if tok:
            _app_token_cache = (tok, time.monotonic() + int(d.get("expire", 7000)))
        else:
            log.warning("换 app_access_token 失败:%s", d)
        return tok
    except Exception as e:  # noqa: BLE001
        log.warning("app_access_token 异常:%s", e)
        return None


async def _tenant_token(db: Session, tenant_key: str) -> str | None:
    cached = _tenant_token_cache.get(tenant_key)
    if cached and cached[1] - 60 > time.monotonic():
        return cached[0]
    app_tok = await _app_access_token(db)
    if not app_tok:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{FEISHU_BASE}/auth/v3/tenant_access_token",
                             json={"app_access_token": app_tok, "tenant_key": tenant_key})
        d = r.json()
        tok = d.get("tenant_access_token")
        if tok:
            _tenant_token_cache[tenant_key] = (tok, time.monotonic() + int(d.get("expire", 7000)))
        return tok
    except Exception as e:  # noqa: BLE001
        log.warning("tenant_access_token 异常:%s", e)
        return None


async def _send_card(db: Session, tenant_key: str, chat_id: str, text: str) -> None:
    tok = await _tenant_token(db, tenant_key)
    if not tok:
        log.warning("ISV 拿不到 tenant_access_token(tenant=%s),无法回贴", tenant_key)
        return

    async def _post(card: dict) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"{FEISHU_BASE}/im/v1/messages", params={"receive_id_type": "chat_id"},
                                 headers={"Authorization": f"Bearer {tok}"},
                                 json={"receive_id": chat_id, "msg_type": "interactive",
                                       "content": json.dumps(card, ensure_ascii=False)})
            return r.json().get("code")
        except Exception as e:  # noqa: BLE001
            log.warning("ISV 发消息异常:%s", e)
            return None

    # 有表格 → 真表格卡片;失败/无表格 → markdown(表格转列表行)
    if _has_table(text):
        if await _post(_build_card_v2(text)) == 0:
            log.info("ISV 已回贴(表格卡片)tenant=%s", tenant_key)
            return
        log.warning("ISV 表格卡片被拒,回退列表行")
    code = await _post({"config": {"wide_screen_mode": True}, "elements": [{"tag": "markdown", "content": _to_feishu_md(text)}]})
    if code not in (0, None):
        log.warning("ISV 发消息失败 code=%s", code)
    elif code == 0:
        log.info("ISV 已回贴 tenant=%s chat=%s", tenant_key, chat_id)


def _resolve_account(db: Session, tenant_key: str, open_id: str) -> int | None:
    row = (db.query(AgentIMUserBindingORM)
           .filter(AgentIMUserBindingORM.platform == "feishu", AgentIMUserBindingORM.tenant_key == tenant_key,
                   AgentIMUserBindingORM.open_id == open_id).first())
    return row.account_id if row else None


def _try_bind(db: Session, tenant_key: str, open_id: str, text: str) -> int | None:
    """文本若是有效绑定码 → 建立绑定,返回 account_id;否则 None。"""
    code = (text or "").strip().upper()
    if not (4 <= len(code) <= 16):
        return None
    row = (db.query(AgentIMBindCodeORM)
           .filter(AgentIMBindCodeORM.code == code, AgentIMBindCodeORM.used == 0,
                   AgentIMBindCodeORM.expires_at > datetime.utcnow()).first())
    if not row:
        return None
    db.add(AgentIMUserBindingORM(platform="feishu", tenant_key=tenant_key, open_id=open_id, account_id=row.account_id))
    row.used = 1
    db.commit()
    log.info("ISV 绑定成功 tenant=%s open_id=%s -> account=%s", tenant_key, open_id, row.account_id)
    return row.account_id


async def _handle_message(tenant_key: str, chat_id: str, open_id: str, text: str) -> None:
    from geo.agent.agent import build_embed_agent, route_line
    from geo.agent.methods import load_message_history, save_message_history

    db = SessionLocal()
    try:
        account_id = _resolve_account(db, tenant_key, open_id)
        if account_id is None:
            # 尝试把这条当绑定码
            account_id = _try_bind(db, tenant_key, open_id, text)
            if account_id is not None:
                await _send_card(db, tenant_key, chat_id, "✅ 绑定成功!现在可以直接问我「我被搜到几个问题」「帮我诊断」了。")
                return
            await _send_card(db, tenant_key, chat_id,
                             "请先绑定您的 Vigilath 账号:登录 Vigilath 控制台 → 对接集成 → 获取**飞书绑定码**,把绑定码发给我即可。")
            return
        await _send_card(db, tenant_key, chat_id, "⏳ 正在查询,请稍候…")    # 即时回执
        deps = AgentDeps(account_id=account_id, user_id=account_id, db=db, caps=["read", "write"])
        agent = build_embed_agent(True, line=route_line(text))
        history = load_message_history(deps)
        result = await agent.run(text, deps=deps, message_history=history)
        try:
            save_message_history(deps, result.all_messages_json())
        except Exception:  # noqa: BLE001
            pass
        await _send_card(db, tenant_key, chat_id, (result.output or "（无输出）").strip())
    except Exception as e:  # noqa: BLE001
        await _send_card(db, tenant_key, chat_id, f"抱歉,处理出错了:{e}")
    finally:
        db.close()


@router.post("/feishu-isv/callback")
async def feishu_isv_callback(request: Request, bg: BackgroundTasks):
    body = await request.json()
    _, _, verify_token, encrypt_key = _isv()
    if encrypt_key and "encrypt" in body:
        body = _maybe_decrypt(body, encrypt_key)

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    db = SessionLocal()
    try:
        header = body.get("header") or {}
        event = body.get("event") or {}

        # app_ticket 推送(ISV 必处理):可能在 event.app_ticket 或顶层
        ticket = event.get("app_ticket") or body.get("app_ticket")
        if ticket:
            app_id = event.get("app_id") or header.get("app_id") or _isv()[0]
            _save_app_ticket(db, app_id, ticket)
            return {"code": 0}

        # 去重
        eid = header.get("event_id") or body.get("uuid") or ""
        now = time.time()
        if eid:
            for k in [k for k, t in _seen_events.items() if now - t > 600]:
                _seen_events.pop(k, None)
            if eid in _seen_events:
                return {"code": 0}
            _seen_events[eid] = now

        if header.get("event_type") == "im.message.receive_v1":
            msg = event.get("message") or {}
            if msg.get("message_type") == "text":
                import re as _re
                tenant_key = header.get("tenant_key") or ""
                open_id = (((event.get("sender") or {}).get("sender_id") or {}).get("open_id")) or ""
                chat_id = msg.get("chat_id") or ""
                try:
                    text = json.loads(msg.get("content") or "{}").get("text", "").strip()
                except json.JSONDecodeError:
                    text = ""
                text = _re.sub(r"@_user_\d+", "", text).strip()
                # 群聊只在有 @(机器人)时才回;单聊照常(ISV 暂用「有@即回」的轻量判断)
                if (msg.get("chat_type") or "") == "group" and not (msg.get("mentions") or []):
                    return {"code": 0}
                if chat_id and open_id and text:
                    log.info("ISV 消息 tenant=%s open_id=%s text=%r", tenant_key, open_id, text[:40])
                    bg.add_task(_handle_message, tenant_key, chat_id, open_id, text)
        return {"code": 0}
    finally:
        db.close()
