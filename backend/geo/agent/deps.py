"""AgentDeps —— 注入每次 Agent run 的租户上下文(Pydantic AI deps),与越权防护。

铁律(最佳方案 §12):
  - account_id 由 resolve_account 注入,**绝不作为大模型可填参数**;
  - 模型给的资源 id 一律经 assert_owns 校验归属当前账号。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class AgentDeps:
    """通过 Agent(deps_type=AgentDeps) 声明,Agent.run(msg, deps=...) 注入,工具内 ctx.deps 取。"""

    account_id: int
    user_id: int
    db: Session
    topic_id: int | None = None          # 当前激活主题(MVP 限 1;为多主题留 account×topic)
    budget: dict[str, Any] = field(default_factory=dict)   # 用量护栏:token/步数(非计费)
    caps: list[str] = field(default_factory=lambda: ["read", "write"])   # 能力 scope;内部全权,对外由 embed token 收敛


class OwnershipError(PermissionError):
    """资源不属于当前账号 —— 拒绝(防跨账号读写)。"""


def assert_owns(deps: AgentDeps, owner_account_id: int | None, what: str = "resource") -> None:
    """所有接收模型传入资源 id 的工具,取出该资源后必须先调它校验归属。"""
    if owner_account_id is None or owner_account_id != deps.account_id:
        raise OwnershipError(f"{what} 不属于当前账号(account_id={deps.account_id})")
