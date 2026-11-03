"""Smoke test: sign a user token, create a job, wait for the AI-verdict report.

Requires monitor-service on :8085 and tests/mock_upstream.py on :8093 with:
  MONITOR_JWT_SECRET=smoke-secret-16chars
  MONITOR_BROWSER_URL=http://127.0.0.1:8093
  GEO_AI_BASE_URL=http://127.0.0.1:8093/v1  GEO_AI_MODEL=mock  GEO_AI_API_KEY=sk-mock

Run: venv/Scripts/python tests/smoke_test.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8085"
SECRET = "smoke-secret-16chars"
BRAND = "测试品牌"
ARTICLE_URL = "https://www.example.com/article/1"


def b64(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign_token() -> str:
    header = b64({"alg": "HS256", "typ": "JWT"})
    payload = b64({"sub": "smoke-user", "tenant_id": "smoke-tenant",
                   "name": "Smoke", "exp": int(time.time()) + 3600})
    signing = f"{header}.{payload}".encode()
    sig = hmac.new(SECRET.encode(), signing, hashlib.sha256).digest()
    return f"{header}.{payload}." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


def call(method: str, path: str, token: str, body: dict | None = None, raw: bool = False):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
        return payload if raw else json.loads(payload.decode("utf-8"))


def main() -> int:
    token = sign_token()

    me = call("GET", "/api/me", token)
    assert me["tenant_id"] == "smoke-tenant", me
    print("[pass] /api/me identity bridge")

    status = call("GET", "/api/platform-status", token)
    assert status["ready"] is True and len(status["platforms"]) == 5, status
    print("[pass] /api/platform-status all ready")

    job = call("POST", "/api/jobs", token, {
        "brand": BRAND,
        "articles": [{"title": "测试文章", "url": ARTICLE_URL}],
        "questions": ["高功率激光器哪家国产品牌做得好？"],
    })
    job_id = job["id"]
    print(f"[pass] job created: {job_id}")

    deadline = time.time() + 120
    while time.time() < deadline:
        job = call("GET", f"/api/jobs/{job_id}", token)
        if job["status"] in {"done", "failed"}:
            break
        time.sleep(2)
    assert job["status"] == "done", job
    assert job["completed_questions"] == 1, job
    print("[pass] job finished with AI verdict pipeline")

    report = call("GET", f"/api/jobs/{job_id}/report", token, raw=True).decode("utf-8")
    for needle in (BRAND, "已提及", "已引用"):
        assert needle in report, f"report missing: {needle}"
    print("[pass] record.html rendered with mention/citation verdicts")

    results = json.loads(call("GET", f"/api/jobs/{job_id}/results", token, raw=True))
    row = results["results"][0]
    verdict = row["ai_verdict"]
    assert verdict["brand_mentioned"] is True and verdict["citation_status"] == "cited", verdict
    assert verdict["brand_evidence_quote"] in row["answer"], verdict
    assert verdict["mentioned_brands"][0]["name"] == BRAND, verdict
    print("[pass] ai_verdict: brand_mentioned=True, citation=cited, evidence verbatim")

    print("\nSMOKE OK — the server chain reproduces the desktop AI-verdict pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
