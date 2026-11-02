"""/api/agent/v1/* —— 对外稳定面(给外部 agent / 小龙虾链接)。

鉴权:Authorization: Bearer <1 年期 embed token>(非登录 JWT)。
account_id 一律从 token 解出、后端注入;caps 收敛;publish 永不可达。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from geo.agent.deps import AgentDeps
from geo.agent.embed.tokens import EmbedAuthError, EmbedClaims, verify_token
from geo.agent.methods import (
    load_message_history,
    reset_conversation,
    save_message_history,
)
from geo.database import SessionLocal

router = APIRouter(prefix="/agent/v1")

CARD_TOOLS = {"get_report", "get_growth_summary", "get_today_effect", "get_query_coverage", "get_publish_status", "get_batch_results"}

# /data/{name} → 只读工具(绕过 LLM,直接取数)
DATA_TOOLS = {
    "today": "get_today_effect",
    "coverage": "get_query_coverage",
    "report": "get_report",
    "growth": "get_growth_summary",
    "batch": "get_batch_results",
    "publish": "get_publish_status",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def embed_claims(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> EmbedClaims:
    """解析 Bearer embed token → EmbedClaims。失败映射 HTTP。"""
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    try:
        return verify_token(db, token)
    except EmbedAuthError as e:
        raise HTTPException(status_code=e.code, detail=e.detail)


def _deps(claims: EmbedClaims, db: Session) -> AgentDeps:
    return AgentDeps(account_id=claims.account_id, user_id=claims.account_id, db=db, caps=claims.caps)


class ChatIn(BaseModel):
    message: str


class _FakeCtx:
    """只读工具只用 ctx.deps;造一个最小 ctx 直接调工具,绕过 LLM。"""

    def __init__(self, deps: AgentDeps):
        self.deps = deps


@router.post("/chat")
async def chat(body: ChatIn, claims: EmbedClaims = Depends(embed_claims), db: Session = Depends(get_db)):
    """对话(SSE)。复用内部 agent.run() 全工具循环,工具集按 caps 收敛、永不含 publish。"""
    from geo.agent.agent import build_embed_agent, route_line

    agent = build_embed_agent("write" in claims.caps, line=route_line(body.message))
    deps = _deps(claims, db)
    history = load_message_history(deps)

    async def event_stream():
        try:
            result = await agent.run(body.message, deps=deps, message_history=history)
            text = result.output or ""
            for i in range(0, len(text), 24):
                yield f"data: {json.dumps({'delta': text[i:i + 24]}, ensure_ascii=False)}\n\n"
            cards_by_tool: dict[str, dict] = {}
            for m in result.all_messages():
                for p in getattr(m, "parts", []):
                    if getattr(p, "part_kind", "") == "tool-return" and getattr(p, "tool_name", "") in CARD_TOOLS:
                        cards_by_tool[p.tool_name] = {"tool": p.tool_name, "data": p.content}
            if cards_by_tool:
                yield f"data: {json.dumps({'cards': list(cards_by_tool.values())}, ensure_ascii=False, default=str)}\n\n"
            try:
                save_message_history(deps, result.all_messages_json())
            except Exception:  # noqa: BLE001
                pass
            yield "data: {\"done\": true}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/reset")
async def reset(claims: EmbedClaims = Depends(embed_claims), db: Session = Depends(get_db)):
    reset_conversation(_deps(claims, db))
    return {"ok": True}


@router.get("/data/{name}")
async def data(name: str, claims: EmbedClaims = Depends(embed_claims), db: Session = Depends(get_db)):
    """只读取数,绕过 LLM,直接调对应只读工具。"""
    tool_name = DATA_TOOLS.get(name)
    if not tool_name:
        raise HTTPException(status_code=404, detail=f"unknown data: {name}; 可选 {sorted(DATA_TOOLS)}")
    from geo.agent import tools as t

    fn = getattr(t, tool_name)
    return await fn(_FakeCtx(_deps(claims, db)))


@router.get("/meta/capabilities")
async def capabilities(claims: EmbedClaims = Depends(embed_claims)):
    return {
        "account_id": claims.account_id,
        "caps": claims.caps,
        "can_write": "write" in claims.caps,
        "can_publish": False,            # 真实外发对外永不开放(平台内部护栏控制)
        "data": sorted(DATA_TOOLS),
    }
