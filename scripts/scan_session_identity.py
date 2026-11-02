#!/usr/bin/env python3
"""扫 engine_sessions 现库,找每家引擎"跨重新登录稳定"的账号身份字段。

用途:校准 backend/geo/models/engine_sessions.py 里 extract_account_id 的
候选字段表(_IDENTITY_COOKIES 等)。只打印字段名 + 值哈希前 12 位,不打印明文。

判定思路:同 source_label 的多条上传大概率是同一账号的多次登录 ——
  - 字段值在组内所有行都相同  → 跨登录稳定(身份字段候选 ✓)
  - 字段值在不同 label 间不同 → 能区分账号(否则是全员一样的常量,没用)

用法(prod 上):
  cd /home/ubuntu/Dev/geo/backend && .venv/bin/python ../scripts/scan_session_identity.py
本地 sqlite 同理(默认 DATABASE_URL=sqlite:///./data/geo_checker.db)。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import defaultdict

try:
    from sqlalchemy import create_engine, text
except ImportError:
    print("ERROR: 需要 sqlalchemy,请用 backend 的 venv 跑")
    sys.exit(1)


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # 尝试 backend/.env(脚本可能从 backend cwd 跑)
    for env_path in (".env", "backend/.env", "../backend/.env"):
        if os.path.exists(env_path):
            for line in open(env_path):
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "sqlite:///./data/geo_checker.db"


def _h(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()[:12]


def _fields(storage_state: dict) -> dict[str, str]:
    """拍平成 {field_key: value}。cookie.<name> / ls.<key>;ls JSON 再展开一层。"""
    out: dict[str, str] = {}
    for c in storage_state.get("cookies") or []:
        if c.get("name") and c.get("value"):
            out.setdefault(f"cookie.{c['name']}", c["value"])
    for o in storage_state.get("origins") or []:
        for item in o.get("localStorage") or []:
            name, value = item.get("name"), item.get("value")
            if not name or not value:
                continue
            out.setdefault(f"ls.{name}", value)
            if value.lstrip().startswith("{"):
                try:
                    obj = json.loads(value)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, (str, int)) and str(v).strip():
                            out.setdefault(f"ls.{name}.{k}", str(v))
    return out


def main() -> None:
    url = _db_url()
    print(f"DB: {url.split('@')[-1] if '@' in url else url}")
    eng = create_engine(url)
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, engine, source_label, captured_at, storage_state "
            "FROM engine_sessions ORDER BY engine, source_label, captured_at"
        )).fetchall()
    print(f"共 {len(rows)} 条\n")

    by_engine: dict[str, list] = defaultdict(list)
    for r in rows:
        try:
            state = json.loads(r.storage_state)
        except Exception:
            continue
        by_engine[r.engine].append((r.id, r.source_label or f"#${r.id}", _fields(state)))

    for engine in sorted(by_engine):
        items = by_engine[engine]
        groups: dict[str, list] = defaultdict(list)
        for _id, label, fields in items:
            groups[label].append(fields)
        multi = {lb: fs for lb, fs in groups.items() if len(fs) >= 2}
        print(f"━━ {engine}: {len(items)} 行, {len(groups)} 个 label"
              f"(其中 {len(multi)} 个 label 有多次上传可验证稳定性)")

        # 每个字段:组内稳定数 / 可验证组数,跨 label 去重值数
        stats: dict[str, dict] = defaultdict(lambda: {"stable": 0, "checked": 0, "values": set(), "present": 0})
        for label, fs_list in groups.items():
            keys = set().union(*(set(fs) for fs in fs_list))
            for key in keys:
                vals = {fs.get(key) for fs in fs_list if fs.get(key)}
                st = stats[key]
                st["present"] += sum(1 for fs in fs_list if fs.get(key))
                if len(fs_list) >= 2 and all(fs.get(key) for fs in fs_list):
                    st["checked"] += 1
                    if len(vals) == 1:
                        st["stable"] += 1
                if vals:
                    st["values"].update(_h(v) for v in vals)

        n_groups = len(groups)
        candidates = []
        for key, st in stats.items():
            if st["checked"] == 0:
                continue
            if st["stable"] == st["checked"] and len(st["values"]) >= min(2, n_groups):
                candidates.append((key, st))
        candidates.sort(key=lambda kv: (-kv[1]["stable"], kv[0]))

        if not candidates:
            print("   (没有任何 label 有 ≥2 次上传,或没有组内稳定且跨账号区分的字段)")
        for key, st in candidates[:15]:
            print(f"   ✓ {key:50s} 稳定 {st['stable']}/{st['checked']} 组,"
                  f"{len(st['values'])} 个不同值,出现 {st['present']} 行,"
                  f"哈希样例 {sorted(st['values'])[:3]}")
        print()


if __name__ == "__main__":
    main()
