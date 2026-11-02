#!/usr/bin/env python3
"""引擎健康哨兵:对每个引擎跑一条 canary 查询,断言有答案(联网引擎再看引用),
结果写 ENGINE_HEALTH_FILE(默认 /opt/geo/engine_health.json),供 admin 端点读 + 告警。

cron 用(vm02,每小时):
  */60 * * * * /opt/geo/backend/venv/bin/python /opt/geo/scripts/engine_health_check.py >> /var/log/engine_health.log 2>&1
"""
import json
import os
import sys
import urllib.request
from datetime import datetime

BASE = os.environ.get("BROWSER_SERVICE_URL", "http://127.0.0.1:8092").rstrip("/")
OUT = os.environ.get("ENGINE_HEALTH_FILE", "/opt/geo/engine_health.json")
ENGINES = os.environ.get("HEALTH_ENGINES", "deepseek,qwen,wenxin,yuanbao,doubao").split(",")
CANARY = os.environ.get("HEALTH_CANARY", "2026年最新国产手机推荐")
TIMEOUT = int(os.environ.get("HEALTH_TIMEOUT", "260"))


def probe(engine: str) -> dict:
    body = json.dumps({"engine": engine, "query": CANARY}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/search-hot", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8"))
        al = len(d.get("answer") or "")
        ci = len(d.get("citations") or [])
        return {"engine": engine, "ok": al > 0, "ans_len": al, "cites": ci,
                "error": d.get("error")}
    except Exception as e:  # noqa: BLE001
        return {"engine": engine, "ok": False, "ans_len": 0, "cites": 0,
                "error": str(e)[:150]}


def main() -> None:
    results = [probe(e.strip()) for e in ENGINES if e.strip()]
    health = {"checked_at": datetime.utcnow().isoformat() + "Z", "engines": results}
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(health, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print(f"[health] write {OUT} failed: {e}", file=sys.stderr)
    for r in results:
        line = f"{'OK  ' if r['ok'] else 'FAIL'} {r['engine']} ans={r['ans_len']} cites={r['cites']} err={r['error']}"
        print(f"{datetime.utcnow().isoformat()} {line}")
        if not r["ok"]:
            print(f"[ALERT] engine {r['engine']} unhealthy: {r['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
