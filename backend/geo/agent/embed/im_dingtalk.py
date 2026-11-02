"""钉钉(DingTalk)IM 接入器(企业内部机器人,HTTP 回调模式)。

比企微简单:回调是 JSON,签名用 HMAC-SHA256;回复直接 POST 回调里带的 sessionWebhook(无需 access_token)。
钉钉 markdown 认 # 标题/加粗,但不认表格 → 表格转列表行。

连接器(agent_im_connectors,platform='dingtalk'):
  app_id=机器人 AppKey/robotCode, app_secret=AppSecret(用于验签)
回调地址(钉钉机器人「消息接收地址」配一次):<host>/api/agent/im/dingtalk/callback
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy.orm import Session

from geo.agent.deps import AgentDeps
from geo.agent.embed.dedup import seen_before
from geo.agent.embed.im_feishu import _tables_to_lines, log
from geo.database import SessionLocal
from geo.models.agent import AgentIMConnectorORM

router = APIRouter(prefix="/agent/im")
_seen: dict[str, float] = {}


def _to_dingtalk_md(text: str) -> str:
    return _tables_to_lines(text or "")[:3000]


def _verify(app_secret: str, timestamp: str, sign: str) -> bool:
    """钉钉出站签名:base64(HMAC-SHA256(appSecret, f"{timestamp}\\n{appSecret}"))。"""
    if not (app_secret and timestamp and sign):
        return False
    base = f"{timestamp}\n{app_secret}".encode("utf-8")
    calc = base64.b64encode(hmac.new(app_secret.encode("utf-8"), base, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(calc, sign)


async def _reply(session_webhook: str, text: str) -> None:
    if not session_webhook:
        log.warning("[dingtalk] 无 sessionWebhook,无法回贴")
        return
    payload = {"msgtype": "markdown", "markdown": {"title": "GEO 助手", "text": _to_dingtalk_md(text)}}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(session_webhook, json=payload)
        d = r.json()
        if d.get("errcode") not in (0, None):
            log.warning("[dingtalk] 回贴失败 errcode=%s errmsg=%s", d.get("errcode"), d.get("errmsg"))
        else:
            log.info("[dingtalk] 已回贴")
    except Exception as e:  # noqa: BLE001
        log.warning("[dingtalk] 回贴异常:%s", e)


async def _handle(account_id: int, session_webhook: str, text: str) -> None:
    from geo.agent.agent import build_embed_agent, route_line
    from geo.agent.methods import load_message_history, save_message_history

    await _reply(session_webhook, "⏳ 正在查询,请稍候…")    # 即时回执(sessionWebhook 一次发送)
    db = SessionLocal()
    try:
        deps = AgentDeps(account_id=account_id, user_id=account_id, db=db, caps=["read", "write"])
        result = await build_embed_agent(True, line=route_line(text)).run(text, deps=deps, message_history=load_message_history(deps))
        try:
            save_message_history(deps, result.all_messages_json())
        except Exception:  # noqa: BLE001
            pass
        await _reply(session_webhook, (result.output or "（无输出）").strip())
    except Exception as e:  # noqa: BLE001
        await _reply(session_webhook, f"抱歉,处理出错了:{e}")
    finally:
        db.close()


@router.post("/dingtalk/callback")
async def dingtalk_callback(request: Request, bg: BackgroundTasks):
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {"errcode": 0}

    robot_code = body.get("robotCode") or body.get("chatbotUserId") or ""
    db = SessionLocal()
    try:
        # 优先按 robotCode 找连接器;找不到再遍历用 appSecret 验签匹配
        conn = None
        if robot_code:
            conn = (db.query(AgentIMConnectorORM)
                    .filter(AgentIMConnectorORM.platform == "dingtalk", AgentIMConnectorORM.app_id == robot_code,
                            AgentIMConnectorORM.enabled == 1).first())
        candidates = [conn] if conn else db.query(AgentIMConnectorORM).filter(
            AgentIMConnectorORM.platform == "dingtalk", AgentIMConnectorORM.enabled == 1).all()
        conn = next((c for c in candidates if c and _verify(c.app_secret, timestamp, sign)), None)
        if conn is None:
            log.warning("[dingtalk] 验签未匹配(robotCode=%s)", robot_code)
            return {"errcode": 0}

        if (body.get("msgtype") or "") != "text":
            return {"errcode": 0}
        content = ((body.get("text") or {}).get("content") or "").strip()
        session_webhook = body.get("sessionWebhook") or ""
        msg_id = body.get("msgId") or ""
        if msg_id and await seen_before(msg_id):
            return {"errcode": 0}
        if content and session_webhook:
            log.info("[dingtalk] 消息 account=%s text=%r", conn.account_id, content[:40])
            bg.add_task(_handle, conn.account_id, session_webhook, content)
        return {"errcode": 0}
    finally:
        db.close()
