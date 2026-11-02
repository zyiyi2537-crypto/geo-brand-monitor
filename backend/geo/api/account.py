"""Personal center (/account) endpoints.

Exposes per-user data the `/account` UI needs beyond the existing auth and
membership routes: detection history (list/detail/delete) and password
change. Everything here requires a valid Bearer token — `get_current_user`
returns the `UserORM` row for the caller.
"""
import json
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from geo.api.auth import get_current_user
from geo.database import SessionLocal
from geo.models.detection import (
    DetectionRecordDetail,
    DetectionRecordList,
    DetectionRecordSummary,
)
from geo.models.payment import PaymentSessionORM
from geo.models.membership import MembershipORM
from geo.models.user import UserORM
from geo.services.detection_service import (
    delete_detection,
    get_detection,
    list_detections,
)
from geo.utils.error_handler import AppException


router = APIRouter()


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)


@router.get("/detections", response_model=DetectionRecordList)
async def list_user_detections(
    page: int = 1,
    size: int = 10,
    current_user: UserORM = Depends(get_current_user),
):
    rows, total = list_detections(user_id=current_user.id, page=page, size=size)
    items = [DetectionRecordSummary.model_validate(r) for r in rows]
    return DetectionRecordList(items=items, total=total, page=page, size=size)


@router.get("/detections/{record_id}", response_model=DetectionRecordDetail)
async def get_user_detection(
    record_id: int,
    current_user: UserORM = Depends(get_current_user),
):
    row = get_detection(user_id=current_user.id, record_id=record_id)
    if row is None:
        raise AppException(status_code=404, message="Detection record not found")
    try:
        snapshot = json.loads(row.result_snapshot) if row.result_snapshot else {}
    except json.JSONDecodeError:
        snapshot = {}
    return DetectionRecordDetail(
        id=row.id,
        url=row.url,
        score=row.score,
        grade=row.grade,
        tier=row.tier,
        mode=row.mode,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
        result=snapshot,
    )


@router.delete("/detections/{record_id}")
async def delete_user_detection(
    record_id: int,
    current_user: UserORM = Depends(get_current_user),
):
    ok = delete_detection(user_id=current_user.id, record_id=record_id)
    if not ok:
        raise AppException(status_code=404, message="Detection record not found")
    return {"success": True}


class PaymentRecordItem(BaseModel):
    id: int
    membership_slug: str
    amount_cents: int
    currency: str
    status: str
    provider: str = "stripe"
    checkout_url: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class PaymentRecordList(BaseModel):
    items: list[PaymentRecordItem]
    total: int
    page: int
    size: int


@router.get("/payments", response_model=PaymentRecordList)
async def list_user_payments(
    page: int = 1,
    size: int = 10,
    current_user: UserORM = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        q = (
            db.query(PaymentSessionORM, MembershipORM.slug)
            .outerjoin(MembershipORM, PaymentSessionORM.membership_id == MembershipORM.id)
            .filter(PaymentSessionORM.user_id == current_user.id)
            .order_by(PaymentSessionORM.created_at.desc())
        )
        total = q.count()
        rows = q.offset((page - 1) * size).limit(size).all()
        items = [
            PaymentRecordItem(
                id=ps.id,
                membership_slug=slug or "",
                amount_cents=ps.amount_cents,
                currency=ps.currency,
                status=ps.status,
                provider=ps.provider or "stripe",
                checkout_url=ps.checkout_url if ps.status == "pending" and (ps.provider or "stripe") == "stripe" else None,
                created_at=str(ps.created_at),
                completed_at=str(ps.completed_at) if ps.completed_at else None,
            )
            for ps, slug in rows
        ]
        return PaymentRecordList(items=items, total=total, page=page, size=size)
    finally:
        db.close()


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: UserORM = Depends(get_current_user),
):
    # Truncate to bcrypt's 72-byte limit, matching user_service.create_user.
    old_pw = payload.old_password[:72]
    new_pw = payload.new_password[:72]

    if not bcrypt.checkpw(old_pw.encode("utf-8"), current_user.password_hash.encode("utf-8")):
        raise AppException(status_code=400, message="Current password is incorrect")

    new_hash = bcrypt.hashpw(new_pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    db = SessionLocal()
    try:
        row = db.query(UserORM).filter(UserORM.id == current_user.id).first()
        if row is None:
            raise AppException(status_code=404, message="User not found")
        row.password_hash = new_hash
        db.commit()
    finally:
        db.close()

    return {"success": True}


# ── 对外开放:账号自助 embed token(给外部 agent / 小龙虾链接本账号)──────────
# 签发模块 geo.agent.embed.tokens 不依赖 pydantic-ai,可在主后端安全调用;
# 签名密钥与 agent service 共用(同 .env),故主后端签的 token 在 :8010 校验通过。

class IssueTokenRequest(BaseModel):
    label: str = ""
    days: int = 365


@router.get("/agent-tokens")
async def list_agent_tokens(current_user: UserORM = Depends(get_current_user)):
    """列出本账号的 embed token(不返回明文,只元数据)。"""
    from geo.models.agent import AgentTokenORM

    db = SessionLocal()
    try:
        rows = (
            db.query(AgentTokenORM)
            .filter(AgentTokenORM.account_id == current_user.id)
            .order_by(AgentTokenORM.id.desc())
            .all()
        )
        return {
            "tokens": [
                {
                    "tid": r.tid,
                    "caps": r.caps,
                    "label": r.label,
                    "enabled": r.enabled == 1,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }
    finally:
        db.close()


@router.post("/agent-token")
async def issue_agent_token(
    payload: IssueTokenRequest,
    current_user: UserORM = Depends(get_current_user),
):
    """自助领号:为当前账号签发 1 年期 embed token(明文只此一次返回)。

    能力一律全开(读 + 诊断/产稿);真实对外发布不在 token 能力内,由平台护栏控制(can_publish 恒 False)。
    """
    from geo.agent.embed.tokens import issue_token

    caps = ["read", "write"]
    days = max(1, min(int(payload.days or 365), 366))
    db = SessionLocal()
    try:
        token, tid = issue_token(
            db, current_user.id, caps=caps, label=(payload.label or "")[:255], ttl_days=days,
        )
        return {"token": token, "tid": tid, "caps": caps, "days": days, "can_publish": False}
    finally:
        db.close()


@router.post("/agent-token/{tid}/revoke")
async def revoke_agent_token(tid: str, current_user: UserORM = Depends(get_current_user)):
    """吊销本账号的某个 token(只能吊销自己的)。"""
    from geo.models.agent import AgentTokenORM

    db = SessionLocal()
    try:
        row = (
            db.query(AgentTokenORM)
            .filter(AgentTokenORM.tid == tid, AgentTokenORM.account_id == current_user.id)
            .first()
        )
        if row is None:
            raise AppException(status_code=404, message="token not found")
        row.enabled = 0
        db.commit()
        return {"success": True, "tid": tid}
    finally:
        db.close()


# ── 对外开放:IM 接入器(自建应用模式,飞书/企微)────────────────────────────
def _mask(s: str) -> str:
    return (s[:4] + "••••" + s[-2:]) if s and len(s) > 8 else ("••••" if s else "")


class IMConnectorRequest(BaseModel):
    platform: str = "feishu"          # feishu / wecom / dingtalk
    app_id: str                       # 飞书 App ID / 企微 CorpID / 钉钉 AppKey(robotCode)
    app_secret: str = ""
    verify_token: str = ""            # 企微 Token(飞书可空)
    aes_key: str = ""                 # 企微 EncodingAESKey / 飞书 Encrypt Key
    agentid: str = ""                 # 企微自建应用 AgentId


@router.get("/im-connectors")
async def list_im_connectors(current_user: UserORM = Depends(get_current_user)):
    """列出本账号的 IM 接入器(密钥脱敏)。"""
    from geo.models.agent import AgentIMConnectorORM

    db = SessionLocal()
    try:
        rows = db.query(AgentIMConnectorORM).filter(AgentIMConnectorORM.account_id == current_user.id).all()
        return {
            "connectors": [
                {
                    "id": r.id, "platform": r.platform, "app_id": r.app_id,
                    "app_secret_masked": _mask(r.app_secret),
                    "has_verify_token": bool(r.verify_token), "has_aes_key": bool(r.aes_key),
                    "enabled": r.enabled == 1,
                    "callback_path": f"/api/agent/im/{r.platform}/callback",
                }
                for r in rows
            ]
        }
    finally:
        db.close()


@router.post("/im-connector")
async def upsert_im_connector(
    payload: IMConnectorRequest,
    current_user: UserORM = Depends(get_current_user),
):
    """保存/更新本账号某平台的 IM 接入器(一账号一平台一条)。返回回调路径供填回飞书。"""
    from geo.models.agent import AgentIMConnectorORM

    if payload.platform not in ("feishu", "wecom", "dingtalk"):
        raise AppException(status_code=400, message="platform must be feishu / wecom / dingtalk")
    import json as _json

    db = SessionLocal()
    try:
        row = (
            db.query(AgentIMConnectorORM)
            .filter(AgentIMConnectorORM.account_id == current_user.id, AgentIMConnectorORM.platform == payload.platform)
            .first()
        )
        if row is None:
            row = AgentIMConnectorORM(account_id=current_user.id, platform=payload.platform)
            db.add(row)
        row.app_id = payload.app_id.strip()
        row.app_secret = payload.app_secret.strip()
        row.verify_token = payload.verify_token.strip()
        row.aes_key = payload.aes_key.strip()
        # 保留已有的快捷按钮/菜单配置(quick_actions / menu_map),只更新 agentid
        try:
            cfg = _json.loads(row.config_json) if row.config_json else {}
            if not isinstance(cfg, dict):
                cfg = {}
        except (ValueError, TypeError):
            cfg = {}
        if payload.agentid.strip():
            cfg["agentid"] = payload.agentid.strip()
        else:
            cfg.pop("agentid", None)
        row.config_json = _json.dumps(cfg, ensure_ascii=False)
        row.enabled = 1
        db.commit()
        return {"success": True, "id": row.id, "callback_path": f"/api/agent/im/{payload.platform}/callback"}
    finally:
        db.close()


@router.post("/im-bind-code")
async def gen_im_bind_code(current_user: UserORM = Depends(get_current_user)):
    """生成一次性飞书绑定码(ISV 模式):用户在飞书把它发给机器人即可绑定本账号。10 分钟有效。"""
    import random
    import string
    from datetime import datetime, timedelta

    from geo.models.agent import AgentIMBindCodeORM

    db = SessionLocal()
    try:
        # 6 位、去掉易混字符(0/O/1/I)
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _ in range(8):
            code = "".join(random.choice(alphabet) for _ in range(6))
            if not db.query(AgentIMBindCodeORM).filter(AgentIMBindCodeORM.code == code).first():
                break
        row = AgentIMBindCodeORM(
            code=code, account_id=current_user.id,
            expires_at=datetime.utcnow() + timedelta(minutes=10), used=0,
        )
        db.add(row)
        db.commit()
        return {"code": code, "expires_in": 600}
    finally:
        db.close()


@router.post("/im-connector/{cid}/delete")
async def delete_im_connector(cid: int, current_user: UserORM = Depends(get_current_user)):
    from geo.models.agent import AgentIMConnectorORM

    db = SessionLocal()
    try:
        row = (
            db.query(AgentIMConnectorORM)
            .filter(AgentIMConnectorORM.id == cid, AgentIMConnectorORM.account_id == current_user.id)
            .first()
        )
        if row is None:
            raise AppException(status_code=404, message="connector not found")
        db.delete(row)
        db.commit()
        return {"success": True}
    finally:
        db.close()


class QuickConfigRequest(BaseModel):
    # 回复底部快捷按钮:[["📈 投放进展","今日投放进展和效果如何?"], ...]
    quick_actions: list[list[str]] = []
    # 飞书机器人底部菜单 event_key → 问句:{"today":"今日投放效果如何?", ...}
    menu_map: dict[str, str] = {}


class PushTargetItem(BaseModel):
    type: str = "webhook"          # webhook | bot
    name: str = ""
    url: str = ""                  # webhook 用:飞书自定义机器人 hook URL
    secret: str = ""               # webhook 加签密钥(可选)
    chat_id: str = ""              # bot 用:群 chat_id
    enabled: bool = True


class PushTargetsRequest(BaseModel):
    # 简报/告警群发的推送目标:webhook(可多个)+ bot 群,可单独开关
    push_targets: list[PushTargetItem] = []


@router.get("/im-connector/{cid}/quick-config")
async def get_im_quick_config(cid: int, current_user: UserORM = Depends(get_current_user)):
    """读某连接器的快捷按钮 + 菜单映射(未配返回默认,供控制台编辑)。"""
    from geo.im_quick_config import DEFAULT_MENU_MAP, DEFAULT_QUICK_ACTIONS, menu_map, quick_actions
    from geo.models.agent import AgentIMConnectorORM

    db = SessionLocal()
    try:
        row = (db.query(AgentIMConnectorORM)
               .filter(AgentIMConnectorORM.id == cid, AgentIMConnectorORM.account_id == current_user.id).first())
        if row is None:
            raise AppException(status_code=404, message="connector not found")
        return {
            "platform": row.platform,
            "quick_actions": [[l, q] for l, q in quick_actions(row.config_json)],
            "menu_map": menu_map(row.config_json),
            "defaults": {"quick_actions": DEFAULT_QUICK_ACTIONS, "menu_map": DEFAULT_MENU_MAP},
        }
    finally:
        db.close()


@router.post("/im-connector/{cid}/quick-config")
async def set_im_quick_config(
    cid: int, payload: QuickConfigRequest, current_user: UserORM = Depends(get_current_user),
):
    """保存某连接器的快捷按钮 + 菜单映射(合并进 config_json,不动凭证)。"""
    import json as _json

    from geo.models.agent import AgentIMConnectorORM

    db = SessionLocal()
    try:
        row = (db.query(AgentIMConnectorORM)
               .filter(AgentIMConnectorORM.id == cid, AgentIMConnectorORM.account_id == current_user.id).first())
        if row is None:
            raise AppException(status_code=404, message="connector not found")
        try:
            cfg = _json.loads(row.config_json) if row.config_json else {}
            if not isinstance(cfg, dict):
                cfg = {}
        except (ValueError, TypeError):
            cfg = {}
        # 清洗:label/问句非空,按钮最多 6 个
        qa = [[str(it[0]).strip(), str(it[1]).strip()] for it in payload.quick_actions
              if isinstance(it, (list, tuple)) and len(it) >= 2 and str(it[0]).strip() and str(it[1]).strip()][:6]
        mm = {str(k).strip(): str(v).strip() for k, v in payload.menu_map.items()
              if str(k).strip() and str(v).strip()}
        cfg["quick_actions"] = qa
        cfg["menu_map"] = mm
        row.config_json = _json.dumps(cfg, ensure_ascii=False)
        db.commit()
        return {"success": True, "quick_actions": qa, "menu_map": mm}
    finally:
        db.close()


@router.get("/im-connector/{cid}/push-targets")
async def get_im_push_targets(cid: int, current_user: UserORM = Depends(get_current_user)):
    """读连接器的推送目标(webhook + bot 群,简报/告警群发用)。"""
    from geo.models.agent import AgentIMConnectorORM

    db = SessionLocal()
    try:
        row = (db.query(AgentIMConnectorORM)
               .filter(AgentIMConnectorORM.id == cid, AgentIMConnectorORM.account_id == current_user.id).first())
        if row is None:
            raise AppException(status_code=404, message="connector not found")
        try:
            cfg = json.loads(row.config_json) if row.config_json else {}
        except (ValueError, TypeError):
            cfg = {}
        targets = cfg.get("push_targets") if isinstance(cfg, dict) else None
        return {"push_targets": targets or [], "last_chat_id": row.last_chat_id}
    finally:
        db.close()


@router.post("/im-connector/{cid}/push-targets")
async def set_im_push_targets(
    cid: int, payload: PushTargetsRequest, current_user: UserORM = Depends(get_current_user),
):
    """保存推送目标(合并进 config_json.push_targets,不动凭证/快捷按钮)。"""
    from geo.models.agent import AgentIMConnectorORM

    db = SessionLocal()
    try:
        row = (db.query(AgentIMConnectorORM)
               .filter(AgentIMConnectorORM.id == cid, AgentIMConnectorORM.account_id == current_user.id).first())
        if row is None:
            raise AppException(status_code=404, message="connector not found")
        try:
            cfg = json.loads(row.config_json) if row.config_json else {}
            if not isinstance(cfg, dict):
                cfg = {}
        except (ValueError, TypeError):
            cfg = {}
        clean: list[dict] = []
        for t in payload.push_targets:
            typ = (t.type or "").strip()
            if typ == "webhook":
                url = t.url.strip()
                # 空 URL 的 webhook 作为占位**保留并展示**,但强制不启用(不会误发)
                clean.append({"type": "webhook", "name": t.name.strip(),
                              "url": url, "secret": t.secret.strip(),
                              "enabled": bool(t.enabled) and bool(url)})
            elif typ == "bot" and t.chat_id.strip():
                clean.append({"type": "bot", "name": t.name.strip(),
                              "chat_id": t.chat_id.strip(), "enabled": bool(t.enabled)})
        cfg["push_targets"] = clean
        row.config_json = json.dumps(cfg, ensure_ascii=False)
        db.commit()
        return {"success": True, "push_targets": clean}
    finally:
        db.close()
