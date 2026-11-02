"""飞书 IM 接入器(自建应用模式)。

客户在自己飞书建自建应用 → 把 App ID/Secret/Verify Token 粘进控制台连接器 →
事件订阅回调填 `<host>/api/agent/im/feishu/callback`。

流程:飞书事件 → 按 app_id 反查 connector → account_id → 跑 agent → 调飞书 API 回贴。
回调必须 3s 内 200,故 agent(慢)放后台任务,回答用消息 API 异步发回。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time

import httpx


def _tables_to_lines(text: str) -> str:
    """飞书卡片 markdown 不渲染表格(`| a | b |` 会裸露),把 Markdown 表格转成可读列表行。

    2 列 → `• 左:右`;多列 → `• 表头1 值1 · 表头2 值2 …`。非表格内容原样保留。
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    sep = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")   # 分隔行 |---|---|
    while i < len(lines):
        cur = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if "|" in cur and "|" in nxt and "-" in nxt and sep.match(nxt):
            header = [c.strip() for c in cur.strip().strip("|").split("|")]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) == 2:
                    out.append(f"• {cells[0]}:{cells[1]}")
                else:
                    parts = [f"{header[j] + ' ' if j < len(header) and header[j] else ''}{c}".strip()
                             for j, c in enumerate(cells)]
                    out.append("• " + " · ".join(p for p in parts if p))
                i += 1
            continue
        out.append(cur)
        i += 1
    return "\n".join(out)


def _clean_md(text: str) -> str:
    """清洗飞书不可靠渲染的 markdown 记号 → 纯文本(飞书表格单元格/部分卡片不渲染 **,会裸露)。

    # 标题→去井号;---/***/___ 分隔线→删;**粗**/*斜*→去星号(网页端 react-markdown 不走此函数,照常加粗)。
    """
    t = text or ""
    t = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.*?)[ \t]*#*$", r"\1", t)        # 标题:去 # 留文字
    t = re.sub(r"(?m)^[ \t]{0,3}([*\-_])(?:[ \t]*\1){2,}[ \t]*$", "", t)      # 分隔线整行→删
    t = re.sub(r"\*\*\*([^*\n]+)\*\*\*", r"\1", t)                            # ***x***→x
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", t)                                # **x**→x
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", t)                       # *x*→x
    t = re.sub(r"\*{2,}", "", t)                                              # 残留连续星号→删
    return t


# 裸 URL 自动转显式 markdown 链接。
# Why:飞书 lark_md 对**裸** URL 会自动转链,但 href 在遇到 `,` `?` `&` `#` 等字符处被
# 截断 —— 东财股吧 `…/news,VNET,123.html`(逗号)、带 `?query` 的 SERP 链接点开就是半截。
# 包成 `[url](url)` 后,markdown 链接按 `)` 收尾,逗号/查询参数全保住,href 完整。
# 负向 lookbehind 跳过已在 `[..](..)` 里的 URL(前面是 `(` 或 `[`),避免重复包。
_BARE_URL_RE = re.compile(r"(?<![(\[])\bhttps?://[^\s<>()\[\]]+")


def _autolink_urls(text: str) -> str:
    return _BARE_URL_RE.sub(lambda m: f"[{m.group(0)}]({m.group(0)})", text or "")


def _to_feishu_md(text: str) -> str:
    """转成飞书卡片能渲染的 Markdown:标题→加粗、分隔线清理、表格→列表行、裸链→显式链接;加粗/列表/代码飞书本就认。"""
    return _autolink_urls(_tables_to_lines(_clean_md(text)))


_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


def _segment(text: str) -> list:
    """把文本切成块:('md', 文本) 或 ('table', 表头, 行列表)。"""
    lines = (text or "").split("\n")
    blocks: list = []
    buf: list[str] = []
    i = 0

    def flush():
        if buf:
            blocks.append(("md", "\n".join(buf)))
            buf.clear()

    while i < len(lines):
        cur = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if "|" in cur and "|" in nxt and "-" in nxt and _SEP.match(nxt):
            flush()
            header = [c.strip() for c in cur.strip().strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(("table", header, rows))
            continue
        buf.append(cur)
        i += 1
    flush()
    return blocks


def _build_card_v2(text: str) -> dict:
    """构造飞书 2.0 卡片:Markdown 段落 + **真表格组件**(table)。供有表格时渲染成真正的表格。"""
    elements: list = []
    for blk in _segment(text):
        if blk[0] == "md":
            content = _autolink_urls(_clean_md(blk[1])).strip()
            if content:
                elements.append({"tag": "markdown", "content": content})
        else:
            _, header, rows = blk
            ncols = max([len(header)] + [len(r) for r in rows]) if rows else len(header)
            cols = [{"name": f"c{j}",
                     "display_name": (_clean_md(header[j]) if j < len(header) and header[j] else f"列{j + 1}"),
                     "data_type": "text"} for j in range(ncols)]
            # 单元格也去 markdown 记号(表格组件按纯文本显示,** 会裸露)
            trows = [{f"c{j}": (_clean_md(r[j]) if j < len(r) else "") for j in range(ncols)} for r in rows]
            elements.append({"tag": "table", "page_size": min(max(len(trows), 1), 10),
                             "row_height": "low", "columns": cols, "rows": trows})
    if not elements:
        elements = [{"tag": "markdown", "content": text or "（无输出）"}]
    # 2.0 卡片外层只要 schema + body(wide_screen_mode 是 1.0 字段,2.0 放进来会被拒)
    return {"schema": "2.0", "body": {"elements": elements}}


def _has_table(text: str) -> bool:
    return any(b[0] == "table" for b in _segment(text))


class _Log:
    """直接 print 到 stdout(journald 必收);自定义 logger 不一定挂到 uvicorn handler。"""

    def info(self, msg, *a):
        print(msg % a if a else msg, flush=True)

    warning = info


log = _Log()
from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy.orm import Session

from geo.agent.deps import AgentDeps
from geo.agent.embed.dedup import seen_before
from geo.database import SessionLocal
from geo.models.agent import AgentIMConnectorORM

router = APIRouter(prefix="/agent/im")

FEISHU_BASE = "https://open.feishu.cn/open-apis"
_token_cache: dict[str, tuple[str, float]] = {}     # app_id -> (tenant_access_token, expire_ts)


def _connector_by_app(db: Session, app_id: str) -> AgentIMConnectorORM | None:
    return (
        db.query(AgentIMConnectorORM)
        .filter(AgentIMConnectorORM.platform == "feishu", AgentIMConnectorORM.app_id == app_id, AgentIMConnectorORM.enabled == 1)
        .first()
    )


def _connector_by_token(db: Session, token: str) -> AgentIMConnectorORM | None:
    """卡片按钮回调不带 app_id,用 verify_token 反查连接器。"""
    if not token:
        return None
    return (db.query(AgentIMConnectorORM)
            .filter(AgentIMConnectorORM.platform == "feishu", AgentIMConnectorORM.verify_token == token,
                    AgentIMConnectorORM.enabled == 1).first())


def _help_card() -> dict:
    """全部功能清单卡片(1.0 lark_md,渲染加粗)。"""
    return _text_card(_HELP_TEXT)


# 快捷按钮默认值 / 解析见 geo.im_quick_config(可按连接器在控制台配置;此处仅默认兜底)。
from geo.im_quick_config import DEFAULT_QUICK_ACTIONS as _DEF_QA  # noqa: E402
QUICK_ACTIONS = [(l, q) for l, q in _DEF_QA]


def _footer_buttons_1x(actions) -> dict:
    """1.0 卡片底部按钮行(action + button,value.q 回调)。"""
    return {"tag": "action", "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": label},
         "type": "default", "value": {"q": q}} for label, q in actions]}


def _with_footer(card: dict, actions=None) -> dict:
    """给回复卡片底部追加快捷按钮(actions=[(label,q)…];None 用默认)。1.0/2.0 都支持,失败不影响正文。"""
    actions = actions or QUICK_ACTIONS
    try:
        if card.get("schema") == "2.0":
            cols = [{"tag": "column", "width": "auto", "vertical_align": "center", "elements": [
                {"tag": "button", "text": {"tag": "plain_text", "content": label}, "type": "default",
                 "behaviors": [{"type": "callback", "value": {"q": q}}]}]} for label, q in actions]
            card["body"]["elements"].append(
                {"tag": "column_set", "flex_mode": "flow", "horizontal_spacing": "8px", "columns": cols})
        else:
            card.setdefault("elements", []).append({"tag": "hr"})
            card["elements"].append(_footer_buttons_1x(actions))
    except Exception:  # noqa: BLE001 — 加按钮失败就发不带按钮的原卡,别因此丢正文
        pass
    return card


def _menu_card() -> dict:
    """快捷操作按钮卡片(1.0 action;群聊可点)。"""
    btns = [{"tag": "button", "text": {"tag": "plain_text", "content": label},
             "type": "primary" if i == 0 else "default", "value": {"q": q}}
            for i, (label, q) in enumerate(QUICK_ACTIONS)]
    return {"config": {"wide_screen_mode": True}, "elements": [
        {"tag": "div", "text": {"tag": "lark_md", "content": "**Vigilath GEO 助手** —— 点按钮查询,或直接打字问我:"}},
        {"tag": "action", "actions": btns},
    ]}


_HELP_TEXT = """**Vigilath GEO 助手 · 全部功能**(直接打字问我即可)

**📊 数据查询**
- 今日投放效果 / 累计被搜到几个 / 哪些 query 没命中
- 种子词几个、query 多少、每个种子扩展了几个
- 品牌增长、各引擎命中率、竞品对比
- 文章发布进度 / 今天发了哪些文章
- 今天舆情怎么样、有没有负面/风险
- 查我上传的资料(知识库)

**📝 诊断与内容**
- 跑 GEO 诊断、看诊断报告(带根因)
- 生成文章、审核文章(通过/驳回)

**⚙️ 配置**
- 设/扩展提示词、配置舆情监测关键词

**🔗 页面跳转**(网页端)
- 「去信源分析 / 竞品 / 引擎」带你跳到对应页

> 真实对外发布不在对话内开放(平台护栏)。也可用输入框底部的菜单按钮。"""


def _maybe_decrypt(body: dict, aes_key: str) -> dict:
    """飞书设了 Encrypt Key 时事件体是 {'encrypt': '...'};未设则明文直接返回。"""
    if "encrypt" not in body:
        return body
    import base64
    import hashlib

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # 延迟导入

    raw = base64.b64decode(body["encrypt"])
    key = hashlib.sha256(aes_key.encode()).digest()
    iv, ct = raw[:16], raw[16:]
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = dec.update(ct) + dec.finalize()
    plain = plain[: -plain[-1]]                      # 去 PKCS7 padding
    return json.loads(plain.decode("utf-8"))


async def _tenant_token(app_id: str, app_secret: str) -> str | None:
    cached = _token_cache.get(app_id)
    if cached and cached[1] - 60 > time.monotonic():
        return cached[0]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            d = r.json()
        tok = d.get("tenant_access_token")
        if tok:
            _token_cache[app_id] = (tok, time.monotonic() + int(d.get("expire", 7000)))
        return tok
    except Exception:  # noqa: BLE001
        return None


_bot_id_cache: dict[str, str] = {}


async def _bot_open_id(app_id: str, app_secret: str) -> str:
    """取机器人自己的 open_id(判断群里是否被 @ 用),缓存。"""
    if app_id in _bot_id_cache:
        return _bot_id_cache[app_id]
    tok = await _tenant_token(app_id, app_secret)
    if not tok:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{FEISHU_BASE}/bot/v3/info", headers={"Authorization": f"Bearer {tok}"})
        oid = (r.json().get("bot") or {}).get("open_id", "")
        if oid:
            _bot_id_cache[app_id] = oid
        return oid
    except Exception:  # noqa: BLE001
        return ""


async def list_bot_chats(tok: str) -> list[str]:
    """列出机器人所在的**所有群** chat_id(分页)。供主动推送(简报/告警)群发,不再只发 last_chat_id。失败返回空。"""
    out: list[str] = []
    page_token = ""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            for _ in range(10):                      # 最多 10 页 ×100 = 1000 群,足够
                params = {"page_size": 100}
                if page_token:
                    params["page_token"] = page_token
                r = await c.get(f"{FEISHU_BASE}/im/v1/chats", params=params,
                                headers={"Authorization": f"Bearer {tok}"})
                data = (r.json() or {}).get("data") or {}
                out.extend(it["chat_id"] for it in (data.get("items") or []) if it.get("chat_id"))
                page_token = data.get("page_token") or ""
                if not data.get("has_more") or not page_token:
                    break
    except Exception as e:  # noqa: BLE001
        log.warning("[im-feishu] 列群失败:%s", e)
    return out


async def _post_card(tok: str, receive_id: str, card: dict, rid_type: str = "chat_id") -> int | None:
    """发一张交互卡片,返回飞书 code(0=成功,None=异常)。rid_type: chat_id / open_id。"""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{FEISHU_BASE}/im/v1/messages",
                params={"receive_id_type": rid_type},
                headers={"Authorization": f"Bearer {tok}"},
                json={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
            )
        return r.json().get("code")
    except Exception as e:  # noqa: BLE001
        log.warning("[im-feishu] 发消息异常:%s", e)
        return None


async def _send_card_id(tok: str, receive_id: str, card: dict, rid_type: str = "chat_id") -> str:
    """发卡片并返回 message_id(用于稍后原地更新同一张卡)。"""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{FEISHU_BASE}/im/v1/messages", params={"receive_id_type": rid_type},
                headers={"Authorization": f"Bearer {tok}"},
                json={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
            )
        return ((r.json().get("data") or {}).get("message_id")) or ""
    except Exception as e:  # noqa: BLE001
        log.warning("[im-feishu] 发卡片异常:%s", e)
        return ""


async def _patch_card(tok: str, message_id: str, card: dict) -> bool:
    """原地更新已发的卡片(把「正在查询」那张改成结果)。成功返回 True。"""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(
                f"{FEISHU_BASE}/im/v1/messages/{message_id}",
                headers={"Authorization": f"Bearer {tok}"},
                json={"content": json.dumps(card, ensure_ascii=False)},
            )
        return r.json().get("code") == 0
    except Exception as e:  # noqa: BLE001
        log.warning("[im-feishu] 更新卡片异常:%s", e)
        return False


def _text_card(text: str) -> dict:
    """纯文本/加粗卡片:用 1.0 div+lark_md(飞书最稳的加粗/链接渲染,`markdown` 标签可能裸露 `**`)。"""
    return {"config": {"wide_screen_mode": True},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": _to_feishu_md(text)}}]}


def _result_card(text: str, actions=None) -> dict:
    """结果卡片:有表格走 2.0 table;否则 1.0 div+lark_md(可靠渲染 **加粗**)。底部附快捷按钮(按连接器配置)。"""
    card = _build_card_v2(text) if _has_table(text) else _text_card(text)
    return _with_footer(card, actions)


async def send_reply(tok: str, receive_id: str, text: str, rid_type: str = "chat_id", actions=None) -> None:
    """回贴飞书:有表格→2.0 table 卡片,否则→1.0 lark_md 卡片;失败退纯文本。rid_type: chat_id / open_id。"""
    code = await _post_card(tok, receive_id, _result_card(text, actions), rid_type)
    if code == 0:
        log.info("[im-feishu] 已回贴 to=%s", receive_id)
        return
    log.warning("[im-feishu] 卡片发送失败 code=%s,退纯文本", code)
    try:                                  # 兜底:纯文本(去 markdown 记号,至少不裸露符号)
        plain = re.sub(r"[*#`]", "", _to_feishu_md(text))
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(f"{FEISHU_BASE}/im/v1/messages", params={"receive_id_type": rid_type},
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": plain})})
    except Exception as e:  # noqa: BLE001
        log.warning("[im-feishu] 纯文本兜底也失败:%s", e)


async def send_webhook(url: str, text: str, secret: str = "") -> bool:
    """推到飞书**自定义机器人 webhook**(群里加的"自定义机器人",只需粘 URL,可选签名)。

    与 send_reply 用同一张卡片;secret 非空时按飞书算法做 HMAC-SHA256 签名
    (string_to_sign = f"{timestamp}\\n{secret}",空 body)。best-effort,返回是否成功。
    """
    payload: dict = {"msg_type": "interactive", "card": _result_card(text)}
    if secret:
        ts = str(int(time.time()))
        digest = hmac.new(f"{ts}\n{secret}".encode("utf-8"), b"", hashlib.sha256).digest()
        payload["timestamp"] = ts
        payload["sign"] = base64.b64encode(digest).decode("utf-8")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json=payload)
        d = r.json() or {}
        ok = d.get("code", d.get("StatusCode", 0)) == 0
        if not ok:
            log.warning("[im-feishu] webhook 返回非0:%s", str(d)[:120])
        return ok
    except Exception as e:  # noqa: BLE001
        log.warning("[im-feishu] webhook 推送异常:%s", e)
        return False


async def _send_text(app_id: str, app_secret: str, receive_id: str, text: str, rid_type: str = "chat_id",
                     actions=None) -> None:
    tok = await _tenant_token(app_id, app_secret)
    if not tok:
        log.warning("[im-feishu] 拿不到 tenant_access_token(app_id/secret 错?或缺权限),无法回贴")
        return
    await send_reply(tok, receive_id, text, rid_type, actions)


def _conn_actions(app_id: str):
    """按 app_id 取该连接器配置的快捷按钮(未配则默认)。独立 session,只读。"""
    from geo.im_quick_config import quick_actions
    db = SessionLocal()
    try:
        conn = _connector_by_app(db, app_id)
        return quick_actions(conn.config_json if conn else None)
    finally:
        db.close()


async def _handle_message(app_id: str, app_secret: str, account_id: int, receive_id: str, user_text: str,
                          rid_type: str = "chat_id") -> None:
    """后台:跑 agent → 回贴飞书。复用账号级 agent + 多轮记忆(发布工具不暴露)。rid_type: chat_id / open_id。"""
    from geo.agent.agent import build_embed_agent, route_line
    from geo.agent.methods import load_message_history, save_message_history

    actions = _conn_actions(app_id)        # 该连接器配置的底部快捷按钮(可在控制台改)
    # 即时回执 + 原地更新:先发一张「正在查询」卡片拿 message_id,算完把同一张卡 PATCH 成结果
    #(飞书不支持网页式逐字 SSE,但可更新已发卡片,体验上等于"占位→替换"而非两条消息)。
    tok = await _tenant_token(app_id, app_secret)
    msg_id = ""
    if tok:
        msg_id = await _send_card_id(tok, receive_id, _text_card("⏳ 正在查询,请稍候…"), rid_type)
    db = SessionLocal()
    try:
        deps = AgentDeps(account_id=account_id, user_id=account_id, db=db, caps=["read", "write"])
        agent = build_embed_agent(True, line=route_line(user_text))   # 按消息路由到 GEO / 舆情 工具集
        history = load_message_history(deps)
        result = await agent.run(user_text, deps=deps, message_history=history)
        try:
            save_message_history(deps, result.all_messages_json())
        except Exception:  # noqa: BLE001
            pass
        text = (result.output or "（无输出）").strip()
    except Exception as e:  # noqa: BLE001
        text = f"抱歉,处理出错了:{e}"
    finally:
        db.close()
    # 更新占位卡为结果;更新失败(如超时窗口)则退回发新消息
    if not (tok and msg_id and await _patch_card(tok, msg_id, _result_card(text, actions))):
        await _send_text(app_id, app_secret, receive_id, text, rid_type, actions)


@router.post("/feishu/callback")
async def feishu_callback(request: Request, bg: BackgroundTasks):
    body = await request.json()
    log.info("[im-feishu] 收到回调:type=%s event_type=%s keys=%s",
             body.get("type"), (body.get("header") or {}).get("event_type"), list(body.keys()))

    # 先按 app_id 找 connector(拿 aes_key 解密 / 拿 secret 回贴)。明文事件 app_id 在 header。
    app_id = (body.get("header") or {}).get("app_id") or body.get("app_id") or ""
    db = SessionLocal()
    try:
        conn = _connector_by_app(db, app_id) if app_id else None
        if conn and conn.aes_key:
            body = _maybe_decrypt(body, conn.aes_key)
            app_id = (body.get("header") or {}).get("app_id") or app_id
            if not conn:
                conn = _connector_by_app(db, app_id)

        # URL 校验(配置事件订阅时飞书发一次)
        if body.get("type") == "url_verification":
            return {"challenge": body.get("challenge", "")}

        # 卡片按钮点击回调(群聊快捷按钮):legacy 顶层 action / v2 event.action
        action = body.get("action") or (body.get("event") or {}).get("action")
        if action and isinstance(action, dict) and action.get("value"):
            ev = body.get("event") or {}
            log.info("[im-feishu] 卡片按钮回调 keys=%s value=%s", list(body.keys()), action.get("value"))
            q = (action.get("value") or {}).get("q")
            tok_field = body.get("token") or (body.get("header") or {}).get("token") or ""
            c = _connector_by_token(db, tok_field) or (_connector_by_app(db, app_id) if app_id else None)
            chat = (body.get("open_chat_id") or ev.get("open_chat_id")
                    or ((ev.get("context") or {}).get("open_chat_id")) or "")
            oid = (body.get("open_id") or ((ev.get("operator") or {}).get("operator_id") or {}).get("open_id") or "")
            # 去重:同一次点击飞书会按 legacy + 2.0 两种格式各投一条(两者字段位置不同、无共享 event_id),
            # 用「连接器账号 + 问句」当键(两条都带 value.q、都解析到同一连接器)+ 10s TTL,
            # 折叠瞬时双投;10 秒后再点同一按钮仍会响应。
            acct = c.account_id if c else (app_id or "")
            ckey = f"cardcb:{acct}:{q}"
            if q and await seen_before(ckey, ttl=10):
                log.info("[im-feishu] 卡片回调重复投递,忽略 key=%s", ckey)
                return {}
            if c and q and chat:
                bg.add_task(_handle_message, c.app_id, c.app_secret, c.account_id, chat, q, "chat_id")
            elif c and q and oid:
                bg.add_task(_handle_message, c.app_id, c.app_secret, c.account_id, oid, q, "open_id")
            return {}        # 卡片回调:200 空体即可

        header = body.get("header") or {}
        # 校验 verify token(连接器里存的)
        if conn and header.get("token") and conn.verify_token and header["token"] != conn.verify_token:
            return {"code": 0}        # token 不符,静默丢弃
        if conn is None:
            return {"code": 0}        # 未知 app,忽略

        # 去重(跨 worker,Redis 共享)+ 只处理用户文本消息
        eid = header.get("event_id") or ""
        if eid and await seen_before(eid):
            return {"code": 0}

        if header.get("event_type") == "im.message.receive_v1":
            event = body.get("event") or {}
            msg = event.get("message") or {}
            if msg.get("message_type") == "text":
                chat_id = msg.get("chat_id") or ""
                chat_type = msg.get("chat_type") or ""
                mentions = msg.get("mentions") or []
                try:
                    text = json.loads(msg.get("content") or "{}").get("text", "").strip()
                except json.JSONDecodeError:
                    text = ""
                text = re.sub(r"@_user_\d+", "", text).strip()    # 去掉所有 @占位符
                # 群聊只在 @机器人 时才回;单聊照常回(避免群里逢消息必回)
                if chat_type == "group":
                    bot_oid = await _bot_open_id(app_id, conn.app_secret)
                    mentioned = (any((m.get("id") or {}).get("open_id") == bot_oid for m in mentions)
                                 if bot_oid else bool(mentions))
                    if not mentioned:
                        log.info("[im-feishu] 群消息未@机器人,忽略 chat=%s", chat_id)
                        return {"code": 0}
                if chat_id and text:
                    if conn.last_chat_id != chat_id:        # 记最近会话,供主动推送回推
                        conn.last_chat_id = chat_id
                        db.commit()
                    # 「重新开始/清空记忆」→ 清掉本账号对话记忆(消除改名/删主题后残留的旧上下文)
                    if text in ("重新开始", "清空记忆", "清空对话", "重置", "清除记忆") or text.lower() == "reset":
                        from geo.agent.methods import reset_conversation
                        try:
                            reset_conversation(AgentDeps(account_id=conn.account_id, user_id=conn.account_id, db=db))
                        except Exception:  # noqa: BLE001
                            pass
                        tok = await _tenant_token(app_id, conn.app_secret)
                        if tok:
                            await _post_card(tok, chat_id, _text_card("✅ 已清空对话记忆,后续以最新数据为准。"))
                        return {"code": 0}
                    # 「功能/菜单/帮助/能做什么」→ 一律纯文字能力清单(不发按钮卡片)。不跑 agent
                    low = text.lower()
                    if (text in ("功能", "全部功能", "所有功能", "能做什么", "你能做什么", "帮助", "菜单", "开始")
                            or low in ("help", "/help", "menu", "/menu")):
                        tok = await _tenant_token(app_id, conn.app_secret)
                        if tok:
                            await _post_card(tok, chat_id, _help_card())
                        return {"code": 0}
                    log.info("[im-feishu] 消息→后台跑 agent:account=%s chat=%s text=%r", conn.account_id, chat_id, text[:50])
                    bg.add_task(_handle_message, app_id, conn.app_secret, conn.account_id, chat_id, text)
                else:
                    log.info("[im-feishu] 文本消息但 chat_id/text 为空,跳过")
            else:
                log.info("[im-feishu] 非文本消息(type=%s),跳过", msg.get("message_type"))
        elif header.get("event_type") == "im.chat.access_event.bot_p2p_chat_entered_v1":
            log.info("[im-feishu] 用户进入会话(不自动弹卡片)")
        elif header.get("event_type") == "application.bot.menu_v6":
            # 飞书控制台配的「机器人菜单」被点击:event_key 映射到查询(菜单项在控制台配)
            ev = body.get("event") or {}
            key = ev.get("event_key") or ""
            oid = ((ev.get("operator") or {}).get("operator_id") or {}).get("open_id") or ""
            log.info("[im-feishu] 机器人菜单点击 event_key=%r op=%s", key, oid)
            from geo.im_quick_config import menu_map
            q = menu_map(conn.config_json if conn else None).get(key)   # 该连接器配置的菜单映射(可在控制台改)
            if q is None and key and len(key) <= 40:   # 未配在表里的 key:当问句直接问
                q = key
            if conn and oid:
                tok = await _tenant_token(app_id, conn.app_secret)
                if not tok:
                    return {"code": 0}
                if q in (None, "__help__"):
                    await _post_card(tok, oid, _help_card(), "open_id")
                else:
                    bg.add_task(_handle_message, app_id, conn.app_secret, conn.account_id, oid, q, "open_id")
        else:
            log.info("[im-feishu] 非消息事件(event_type=%s),跳过", header.get("event_type"))
        return {"code": 0}
    finally:
        db.close()
