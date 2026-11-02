"""领号 CLI —— 给账号签发 1 年期 embed token(明文只打印一次)。

用法(在 backend 目录,agent-venv):
    python -m geo.agent.embed.mint <account_id> [--caps read,write] [--label "给谁"] [--days 365]
    python -m geo.agent.embed.mint --list <account_id>        # 列出该账号的 token
    python -m geo.agent.embed.mint --revoke <tid>             # 吊销某 token
"""
from __future__ import annotations

import argparse
import sys

from geo.agent.embed.tokens import issue_token
from geo.database import SessionLocal
from geo.models.agent import AgentTokenORM
from geo.models.user import UserORM


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="geo.agent.embed.mint")
    p.add_argument("account_id", nargs="?", type=int)
    p.add_argument("--caps", default="read,write", help="逗号分隔:read[,write]")
    p.add_argument("--label", default="")
    p.add_argument("--origins", default="", help="逗号分隔 CORS 白名单(浏览器直连才需)")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--list", dest="list_acct", type=int, help="列出该账号的 token")
    p.add_argument("--revoke", help="吊销指定 tid")
    args = p.parse_args(argv)

    db = SessionLocal()
    try:
        if args.revoke:
            row = db.query(AgentTokenORM).filter(AgentTokenORM.tid == args.revoke).first()
            if not row:
                sys.exit(f"未找到 tid={args.revoke}")
            row.enabled = 0
            db.commit()
            print(f"已吊销 {args.revoke}(account_id={row.account_id})")
            return

        if args.list_acct is not None:
            rows = db.query(AgentTokenORM).filter(AgentTokenORM.account_id == args.list_acct).all()
            if not rows:
                print(f"account_id={args.list_acct} 无 token")
            for r in rows:
                state = "启用" if r.enabled == 1 else "已吊销"
                print(f"{r.tid}  caps={r.caps}  {state}  到期={r.expires_at:%Y-%m-%d}  label={r.label}")
            return

        if args.account_id is None:
            p.error("需要 account_id(或用 --list / --revoke)")

        user = db.get(UserORM, args.account_id)
        if user is None:
            sys.exit(f"account_id={args.account_id} 不存在")

        caps = [c.strip() for c in args.caps.split(",") if c.strip()]
        origins = [o.strip() for o in args.origins.split(",") if o.strip()]
        token, tid = issue_token(db, args.account_id, caps=caps, label=args.label, origins=origins, ttl_days=args.days)

        print("=" * 60)
        print(f"账号 account_id : {args.account_id}（{getattr(user, 'username', '')}）")
        print(f"tid            : {tid}")
        print(f"caps           : {caps}   (can_publish 永远 False)")
        print(f"有效期         : {args.days} 天")
        print("token（机密,只显示这一次,妥善保管 / 别提交进库):")
        print(token)
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
