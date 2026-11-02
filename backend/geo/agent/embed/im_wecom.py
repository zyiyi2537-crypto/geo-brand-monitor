"""企业微信(WeCom)IM 接入器(自建应用模式)。

与飞书完全不同:回调走 **XML + 强制 AES 加密**(WXBizMsgCrypt),URL 校验是 GET echostr。
回复走应用消息 message/send(markdown,企微不渲染表格 → 转列表行;企微认 # 标题,故保留)。

连接器(agent_im_connectors,platform='wecom'):
  app_id=CorpID, app_secret=Secret, verify_token=Token, aes_key=EncodingAESKey, config_json={"agentid": N}
回调地址(企微「接收消息」配一次):<host>/api/agent/im/wecom/callback
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from geo.agent.deps import AgentDeps
from geo.agent.embed.dedup import seen_before
from geo.agent.embed.im_feishu import _tables_to_lines, log
from geo.database import SessionLocal
from geo.models.agent import AgentIMConnectorORM

router = APIRouter(prefix="/agent/im")
QYAPI = "https://qyapi.weixin.qq.com/cgi-bin"
_token_cache: dict[str, tuple[str, float]] = {}
_seen: dict[str, float] = {}


def _to_wecom_md(text: str) -> str:
    """企微 markdown:认 # 标题/加粗,但不认表格 → 表格转列表行;截断到 ~2000 字。"""
    return _tables_to_lines(text or "")[:2000]


def _sign(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypt])).encode()).hexdigest()


def _decrypt(encrypt_b64: str, encoding_aes_key: str) -> tuple[str, str]:
    """返回 (明文消息, receiveid)。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = base64.b64decode(encoding_aes_key + "=")
    data = base64.b64decode(encrypt_b64)
    dec = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
    plain = dec.update(data) + dec.finalize()
    plain = plain[: -plain[-1]]                              # PKCS7
    msg_len = struct.unpack(">I", plain[16:20])[0]
    return plain[20:20 + msg_len].decode("utf-8"), plain[20 + msg_len:].decode("utf-8")


def _connector_by_corp(db: Session, corpid: str) -> AgentIMConnectorORM | None:
    return (db.query(AgentIMConnectorORM)
            .filter(AgentIMConnectorORM.platform == "wecom", AgentIMConnectorORM.app_id == corpid,
                    AgentIMConnectorORM.enabled == 1).first())


async def _access_token(corpid: str, secret: str) -> str | None:
    ck = f"{corpid}:{secret[:6]}"
    c = _token_cache.get(ck)
    if c and c[1] - 60 > time.monotonic():
        return c[0]
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.get(f"{QYAPI}/gettoken", params={"corpid": corpid, "corpsecret": secret})
        d = r.json()
        tok = d.get("access_token")
        if tok:
            _token_cache[ck] = (tok, time.monotonic() + int(d.get("expires_in", 7000)))
        else:
            log.warning("[wecom] gettoken 失败:%s", d)
        return tok
    except Exception as e:  # noqa: BLE001
        log.warning("[wecom] gettoken 异常:%s", e)
        return None


async def _send_markdown(corpid: str, secret: str, agentid, touser: str, text: str) -> None:
    tok = await _access_token(corpid, secret)
    if not tok:
        log.warning("[wecom] 无 access_token,无法回贴")
        return
    payload = {"touser": touser, "msgtype": "markdown", "agentid": agentid,
               "markdown": {"content": _to_wecom_md(text)}}
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{QYAPI}/message/send", params={"access_token": tok}, json=payload)
        d = r.json()
        if d.get("errcode") not in (0, None):
            log.warning("[wecom] 发消息失败 errcode=%s errmsg=%s", d.get("errcode"), d.get("errmsg"))
        else:
            log.info("[wecom] 已回贴 touser=%s", touser)
    except Exception as e:  # noqa: BLE001
        log.warning("[wecom] 发消息异常:%s", e)


async def _handle(corpid: str, secret: str, agentid, account_id: int, touser: str, text: str) -> None:
    from geo.agent.agent import build_embed_agent, route_line
    from geo.agent.methods import load_message_history, save_message_history

    await _send_markdown(corpid, secret, agentid, touser, "⏳ 正在查询,请稍候…")    # 即时回执
    db = SessionLocal()
    try:
        deps = AgentDeps(account_id=account_id, user_id=account_id, db=db, caps=["read", "write"])
        result = await build_embed_agent(True, line=route_line(text)).run(text, deps=deps, message_history=load_message_history(deps))
        try:
            save_message_history(deps, result.all_messages_json())
        except Exception:  # noqa: BLE001
            pass
        await _send_markdown(corpid, secret, agentid, touser, (result.output or "（无输出）").strip())
    except Exception as e:  # noqa: BLE001
        await _send_markdown(corpid, secret, agentid, touser, f"抱歉,处理出错了:{e}")
    finally:
        db.close()


@router.get("/wecom/callback")
async def wecom_verify(request: Request):
    """URL 校验(GET echostr):验签 → 解密 echostr → 原样返回明文。"""
    q = request.query_params
    msg_sig, ts, nonce, echostr = q.get("msg_signature", ""), q.get("timestamp", ""), q.get("nonce", ""), q.get("echostr", "")
    db = SessionLocal()
    try:
        # 校验阶段还不知道是哪个 corp(echostr 里才有);遍历 wecom 连接器试解(通常很少)
        for conn in db.query(AgentIMConnectorORM).filter(AgentIMConnectorORM.platform == "wecom").all():
            if _sign(conn.verify_token, ts, nonce, echostr) == msg_sig:
                try:
                    plain, _ = _decrypt(echostr, conn.aes_key)
                    return PlainTextResponse(plain)
                except Exception:  # noqa: BLE001
                    continue
        log.warning("[wecom] URL 校验未匹配任何连接器")
        return PlainTextResponse("", status_code=400)
    finally:
        db.close()


@router.post("/wecom/callback")
async def wecom_callback(request: Request, bg: BackgroundTasks):
    q = request.query_params
    msg_sig, ts, nonce = q.get("msg_signature", ""), q.get("timestamp", ""), q.get("nonce", "")
    raw = (await request.body()).decode("utf-8", "ignore")
    try:
        encrypt = ET.fromstring(raw).findtext("Encrypt") or ""
    except ET.ParseError:
        return PlainTextResponse("")
    db = SessionLocal()
    try:
        # 按 verify_token 验签找到连接器
        conn = None
        for c in db.query(AgentIMConnectorORM).filter(AgentIMConnectorORM.platform == "wecom", AgentIMConnectorORM.enabled == 1).all():
            if _sign(c.verify_token, ts, nonce, encrypt) == msg_sig:
                conn = c
                break
        if conn is None:
            log.warning("[wecom] 消息验签未匹配")
            return PlainTextResponse("")
        msg_xml, _ = _decrypt(encrypt, conn.aes_key)
        node = ET.fromstring(msg_xml)
        if (node.findtext("MsgType") or "") != "text":
            return PlainTextResponse("")
        from_user = node.findtext("FromUserName") or ""
        content = (node.findtext("Content") or "").strip()
        msg_id = node.findtext("MsgId") or ""
        if msg_id and await seen_before(msg_id):
            return PlainTextResponse("")
        if from_user and content:
            if conn.last_chat_id != from_user:           # 记最近用户,供主动推送回推
                conn.last_chat_id = from_user
                db.commit()
            try:
                agentid = json.loads(conn.config_json or "{}").get("agentid")
            except json.JSONDecodeError:
                agentid = None
            log.info("[wecom] 消息 corp=%s user=%s text=%r", conn.app_id, from_user, content[:40])
            bg.add_task(_handle, conn.app_id, conn.app_secret, agentid, conn.account_id, from_user, content)
        return PlainTextResponse("")        # 空串=不被动回复,答案走 message/send 异步推
    finally:
        db.close()
