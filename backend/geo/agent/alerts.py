"""主动触达:舆情高风险扫描 + 通知投递(Web 通知表 + IM 最佳努力回推)。

触发信号:sentinel get_today 的 kpi.high_risk > 阈值(默认 1)。
去重:同账号同一天只推一次(dedup_key=sent:{account_id}:{date})。
投递:① 写 agent_notifications(Web 聊天窗打开时拉未读);② 若账号有 IM 连接器 + 最近会话,回推飞书/企微。

跑法(cron,prod 无 scheduler leader → 走 crontab):
    /opt/geo/agent-venv/bin/python -m geo.agent.alerts
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime

from geo.database import SessionLocal
from geo.models.agent import AgentIMConnectorORM, AgentNotificationORM
from geo.models.sentiment import SentimentAccountORM

HIGH_RISK_THRESHOLD = int(os.environ.get("SENTIMENT_ALERT_THRESHOLD", "1"))
# 控制台地址(告警里给「查看舆情详情」链接用);各环境可用 env 覆盖,默认指向正式控制台。
APP_BASE_URL = (os.environ.get("AGENT_APP_BASE_URL") or "https://www.vigilath.com").rstrip("/")


def _insert_notification(db, account_id: int, title: str, body: str, dedup_key: str) -> bool:
    """插入通知;dedup_key 已存在则跳过。返回是否新插入。"""
    exists = db.query(AgentNotificationORM).filter(AgentNotificationORM.dedup_key == dedup_key).first()
    if exists:
        return False
    db.add(AgentNotificationORM(account_id=account_id, title=title, body=body, dedup_key=dedup_key))
    try:
        db.commit()
        return True
    except Exception:  # noqa: BLE001 — 唯一键并发冲突等
        db.rollback()
        return False


async def _push_im(db, account_id: int, text: str) -> dict:
    """把通知回推到账号绑定的 IM(飞书/企微)。返回 {"sent":n,"failed":n,"errors":[...]}。

    防护:每个目标的发送结果都计数 + 失败显式记日志,绝不静默吞掉(否则"今天没推"无从排查)。
    """
    conns = (db.query(AgentIMConnectorORM)
             .filter(AgentIMConnectorORM.account_id == account_id, AgentIMConnectorORM.enabled == 1).all())
    sent = 0
    errors: list[str] = []
    for c in conns:
        try:
            if c.platform == "feishu":
                from geo.agent.embed.im_feishu import (
                    _tenant_token, list_bot_chats, send_reply, send_webhook)
                # 统一推送配置:连接器 config_json.push_targets = [{type,name,enabled,...}]
                cfg = json.loads(c.config_json or "{}") or {}
                push_targets = [t for t in (cfg.get("push_targets") or [])
                                if t.get("enabled", True)]
                if push_targets:
                    tok = None
                    for t in push_targets:
                        typ, name = t.get("type"), t.get("name") or t.get("chat_id") or t.get("url")
                        try:
                            if typ == "webhook" and t.get("url"):
                                ok = await send_webhook(t["url"], text, t.get("secret", ""))
                                if ok:
                                    sent += 1
                                else:
                                    errors.append(f"webhook失败:{name}")
                            elif typ == "bot" and t.get("chat_id"):
                                if tok is None:
                                    tok = await _tenant_token(c.app_id, c.app_secret)
                                if not tok:
                                    errors.append(f"取token失败:{name}"); continue
                                await send_reply(tok, t["chat_id"], text)
                                sent += 1
                        except Exception as te:  # noqa: BLE001
                            errors.append(f"{typ}:{name}:{str(te)[:40]}")
                    continue
                # 兜底(未配 push_targets):推到机器人所在全部群 + last_chat_id
                tok = await _tenant_token(c.app_id, c.app_secret)
                if not tok:
                    errors.append(f"取token失败(connector {c.id})"); continue
                targets = set(await list_bot_chats(tok))
                if c.last_chat_id:
                    targets.add(c.last_chat_id)
                for cid in targets:
                    await send_reply(tok, cid, text)
                    sent += 1
            elif c.platform == "wecom":
                if not c.last_chat_id:
                    continue
                from geo.agent.embed.im_wecom import _send_markdown
                agentid = (json.loads(c.config_json or "{}") or {}).get("agentid")
                await _send_markdown(c.app_id, c.app_secret, agentid, c.last_chat_id, text)
                sent += 1
            # 钉钉:回复靠短时 sessionWebhook(会过期),不支持事后主动推,跳过
        except Exception as e:  # noqa: BLE001 — 连接器级异常也记下来,不静默
            errors.append(f"connector{c.id}:{str(e)[:60]}")
            log.warning("[_push_im] connector %s 推送异常: %s", c.id, e)
    return {"sent": sent, "failed": len(errors), "errors": errors}


# 情感 / 风险英文标签 → 中文(告警清单展示用,不混英文)
_LABEL_ZH = {"bearish": "偏空", "看跌": "偏空", "利空": "偏空", "negative": "偏空",
             "bullish": "偏多", "看涨": "偏多", "neutral": "中性", "mixed": "复杂"}
_RISK_ZH = {"high": "高风险", "medium": "中风险", "low": "低风险"}


def _today_published_risk(db, acc):
    """**只看当日发布**(publish_time = 今天)的相关帖,返回(中/高风险清单[最多10条], 当日发布相关总数)。

    关键:按 publish_time 当天过滤,而非入库时间——旧文(2016/2021)今天被重爬不会算进来。
    """
    from datetime import date

    from sqlalchemy import text

    schema = f"tenant_{int(acc.id)}"
    today = date.today().isoformat()
    base = (f"FROM {schema}.posts p JOIN {schema}.analyses a "
            f"  ON p.source = a.source AND p.post_id = a.post_id "
            f"WHERE p.symbol = :sym AND a.is_relevant = 1 "
            f"  AND substr(CAST(p.publish_time AS text), 1, 10) = :today")
    try:
        total = db.execute(text(f"SELECT count(*) {base}"), {"sym": acc.ticker, "today": today}).scalar() or 0
        rows = db.execute(text(
            f"SELECT p.title, p.url, a.sentiment_label, a.risk_level, p.publish_time {base} "
            f"  AND a.risk_level IN ('medium', 'high') ORDER BY p.publish_time DESC NULLS LAST LIMIT 10"),
            {"sym": acc.ticker, "today": today}).fetchall()
    except Exception:  # noqa: BLE001 — schema 不存在/取数失败:不触发
        return [], 0
    posts = [{"title": (t or "(无标题)")[:60], "url": u or "",
              "label": _LABEL_ZH.get((lab or "").lower(), lab or ""),
              "risk": _RISK_ZH.get((rk or "").lower(), rk or ""),
              "time": str(pt)[:10] if pt else ""} for t, u, lab, rk, pt in rows]
    return posts, int(total)


async def scan_and_deliver() -> dict:
    db = SessionLocal()
    delivered = 0
    scanned = 0
    try:
        accounts = db.query(SentimentAccountORM).filter(SentimentAccountORM.active.is_(True)).all()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        for acc in accounts:
            scanned += 1
            # 只看**当日发布**的中/高风险帖(旧文今天重爬不触发);风险数 ≥ 阈值才推
            posts, total = _today_published_risk(db, acc)
            if len(posts) < HIGH_RISK_THRESHOLD:
                continue
            title = "舆情风险提醒"
            # 列表(非表格)展示:飞书 lark_md 列表里的链接可点,表格单元格不可点
            lines = [f"⚠️ {acc.target} 今日新增 {len(posts)} 条中高风险负面(当日共 {total} 条相关):"]
            for i, p in enumerate(posts, 1):
                meta = " / ".join(x for x in (p["label"], p["risk"], p["time"]) if x)
                head = f"[{p['title']}]({p['url']})" if p["url"] else p["title"]
                lines.append(f"{i}. {head} — {meta}")
            body = "\n".join(lines)
            if _insert_notification(db, acc.user_id, title, body, f"sent:{acc.user_id}:{today}"):
                delivered += 1
                await _push_im(db, acc.user_id, f"**{title}**\n{body}")
        return {"scanned": scanned, "delivered": delivered}
    finally:
        db.close()


def deliver_manual(account_id: int, title: str, body: str, dedup_key: str | None = None) -> bool:
    """供其它事件(非舆情)主动投递通知。dedup_key 不传则用时间戳(每次都推)。"""
    db = SessionLocal()
    try:
        key = dedup_key or f"manual:{account_id}:{datetime.utcnow().timestamp()}"
        ok = _insert_notification(db, account_id, title, body, key)
        if ok:
            asyncio.run(_push_im(db, account_id, f"**{title}**\n{body}"))
        return ok
    finally:
        db.close()


if __name__ == "__main__":
    print(asyncio.run(scan_and_deliver()))
