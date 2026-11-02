"""/api/agent/* 路由。模块级不导入 pydantic-ai(在端点内惰性导入),保证未安装时也能加载、不影响主应用。

注册(在 geo/main.py):
    from geo.agent import api as agent_api
    app.include_router(agent_api.router, prefix="/api", tags=["agent"])
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from geo.agent.auth import get_current_user          # 独立校验,不 import geo.api
from geo.agent.methods import (
    load_message_history,
    reset_conversation,
    resolve_account,
    save_message_history,
)
from geo.database import SessionLocal
from geo.models.user import UserORM

# 这些「数据工具」的返回会作为结构化卡片推给前端渲染
CARD_TOOLS = {"get_report", "get_growth_summary", "get_today_effect", "get_query_coverage", "get_publish_status", "get_batch_results"}

router = APIRouter(prefix="/agent")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChatIn(BaseModel):
    message: str
    topic_id: int | None = None


def _load_agent(scene: str = "chat", line: str = "both"):
    try:
        from geo.agent.agent import build_agent
        return build_agent(scene, line)
    except Exception as e:  # pydantic-ai 未装 / 缺 DEEPSEEK_API_KEY
        raise HTTPException(status_code=503, detail=f"Agent 暂不可用:{e}")


@router.post("/chat")
async def chat(
    body: ChatIn,
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """对话(SSE 流式)。会话单位 = 账号;多轮记忆落库 + 数据工具结果作结构化卡片推前端。"""
    from geo.agent.agent import route_line
    agent = _load_agent("chat", route_line(body.message))   # 按消息路由到 GEO / 舆情 工具集
    deps = resolve_account(current_user, db, topic_id=body.topic_id)
    history = load_message_history(deps)   # 多轮:载入账号历史

    async def event_stream():
        try:
            # 用 agent.iter() 走完整图(模型→工具→模型,工具正常执行),并**边生成边流式**推 token。
            # 不能用 run_stream()+stream_text():DeepSeek 同响应吐文本+tool_call 时它会把文本当最终结果、
            # 跳过工具(卡片全 0/0)。iter() 逐节点执行,工具照跑,且每个模型节点可流式出 token。
            from pydantic_ai import Agent
            from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, TextPart, TextPartDelta

            async with agent.iter(body.message, deps=deps, message_history=history) as run:
                async for node in run:
                    if not Agent.is_model_request_node(node):
                        continue
                    async with node.stream(run.ctx) as req_stream:
                        async for ev in req_stream:
                            delta = None
                            if isinstance(ev, PartStartEvent) and isinstance(ev.part, TextPart):
                                delta = ev.part.content
                            elif isinstance(ev, PartDeltaEvent) and isinstance(ev.delta, TextPartDelta):
                                delta = ev.delta.content_delta
                            if delta:
                                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
                result = run.result

            # 抽真实执行的数据工具返回 → 结构化卡片(去重:同工具留最后一次)
            cards_by_tool: dict[str, dict] = {}
            for m in result.all_messages():
                for p in getattr(m, "parts", []):
                    if getattr(p, "part_kind", "") == "tool-return" and getattr(p, "tool_name", "") in CARD_TOOLS:
                        cards_by_tool[p.tool_name] = {"tool": p.tool_name, "data": p.content}
            cards = list(cards_by_tool.values())
            if cards:
                yield f"data: {json.dumps({'cards': cards}, ensure_ascii=False, default=str)}\n\n"

            # 落库多轮记忆
            try:
                save_message_history(deps, result.all_messages_json())
            except Exception:  # noqa: BLE001 — 存历史失败不影响本轮回答
                pass
            yield "data: {\"done\": true}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/reset")
async def reset(
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清空当前账号的对话记忆(用户「重新开始」)。"""
    deps = resolve_account(current_user, db)
    reset_conversation(deps)
    return {"ok": True}


@router.post("/diagnose")
async def diagnose(
    topic_id: int | None = None,
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """对当前主题跑诊断并给带证据根因(非流式)。重活 → 用 pro 模型。"""
    agent = _load_agent("pro")
    deps = resolve_account(current_user, db, topic_id=topic_id)
    result = await agent.run("请对当前主题跑 GEO 诊断,并给出带证据的根因结论。", deps=deps)
    return {"output": result.output}


@router.get("/notifications")
async def list_notifications(
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """拉当前账号的未读主动通知(舆情高风险等),聊天窗打开时展示。"""
    from geo.models.agent import AgentNotificationORM

    rows = (
        db.query(AgentNotificationORM)
        .filter(AgentNotificationORM.account_id == current_user.id, AgentNotificationORM.read_at.is_(None))
        .order_by(AgentNotificationORM.id.desc())
        .limit(20)
        .all()
    )
    return {"notifications": [{"id": r.id, "title": r.title, "body": r.body,
                               "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}


@router.post("/notifications/read")
async def mark_notifications_read(
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把当前账号所有未读通知标记为已读(聊天窗展示后调)。"""
    from datetime import datetime

    from geo.models.agent import AgentNotificationORM

    (db.query(AgentNotificationORM)
     .filter(AgentNotificationORM.account_id == current_user.id, AgentNotificationORM.read_at.is_(None))
     .update({AgentNotificationORM.read_at: datetime.utcnow()}, synchronize_session=False))
    db.commit()
    return {"ok": True}
