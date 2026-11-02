"""Method 层 —— 确定性副作用,**不暴露给大模型**(由工具内部或编排层调用)。

无计量计费:usage_guardrail 是我们自己的成本/资源护栏,与客户收费无关(收费走线下合同)。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from geo.agent.deps import AgentDeps
from geo.models.user import UserORM


def resolve_account(current_user: UserORM, db: Session, topic_id: int | None = None) -> AgentDeps:
    """鉴权后构造租户上下文。沿用现有 user 体系:account_id = current_user.id。"""
    return AgentDeps(account_id=current_user.id, user_id=current_user.id, db=db, topic_id=topic_id)


def load_message_history(deps: AgentDeps):
    """读账号多轮对话历史 → Pydantic AI message_history(无则 None)。"""
    from geo.models.agent import AgentConversationORM

    row = deps.db.query(AgentConversationORM).filter(AgentConversationORM.account_id == deps.account_id).first()
    if not row or not row.messages_json or row.messages_json in ("[]", ""):
        return None
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter
        return ModelMessagesTypeAdapter.validate_json(row.messages_json)
    except Exception:  # noqa: BLE001 — 历史损坏不阻断对话
        return None


def save_message_history(deps: AgentDeps, messages_json: bytes | str) -> None:
    """保存账号多轮历史(全量,供下轮续接)。capped:超长只留最近 ~50 条。"""
    from datetime import datetime

    from geo.models.agent import AgentConversationORM

    s = messages_json.decode() if isinstance(messages_json, (bytes, bytearray)) else str(messages_json)
    row = deps.db.query(AgentConversationORM).filter(AgentConversationORM.account_id == deps.account_id).first()
    if row is None:
        row = AgentConversationORM(account_id=deps.account_id)
        deps.db.add(row)
    row.messages_json = s
    row.updated_at = datetime.utcnow()
    deps.db.commit()


def reset_conversation(deps: AgentDeps) -> None:
    """清空账号对话记忆(用户「重新开始」用)。"""
    from geo.models.agent import AgentConversationORM

    deps.db.query(AgentConversationORM).filter(AgentConversationORM.account_id == deps.account_id).delete()
    deps.db.commit()


def usage_guardrail_check(deps: AgentDeps, action: str) -> None:
    """用量护栏(非计费):token 预算 / 步数 / 引擎资源上限。超额抛错即停。

    TODO(W1):接 quota_service 做账号级上限 + ai_telemetry 计量;当前为放行占位。
    """
    return None


def publish_execute(deps: AgentDeps, draft_ids: list[int]) -> None:
    """模板已确认 → 调 publisher 发布 + 回填 publish_record。仅由「产稿完成事件」触发,模型不可调。

    TODO:接 mediumsly_publisher 等;校验对应 ExecutionPlan.status == confirmed。
    """
    raise NotImplementedError("publish_execute: W4 实现(模板确认后自动发文)")


def deliver_notification(deps: AgentDeps, message: str) -> None:
    """主动触达投递(Web + IM),去重 / 限频 / 免打扰。由中心 cron / 批次完成事件触发。

    TODO:W7 实现;按 account_channel_binding 投递。
    """
    raise NotImplementedError("deliver_notification: W7 实现(主动触达)")
