"""GEO 优化 Agent —— 独立 service(方案 B)。

为什么独立:pydantic-ai 需 pydantic>=2.11,而主后端钉死 fastapi==0.104.1 + pydantic==2.5.0
(不兼容)。本 service 跑在**独立 venv**(fastapi>=0.115 + pydantic>=2.11 + pydantic-ai,
见 requirements-agent.txt),与主后端隔离;共用同一 DB / SECRET_KEY / OPENROUTER_API_KEY。

运行:
    uvicorn geo.agent.service:app --host 127.0.0.1 --port 8010
nginx 把 /api/agent/* 反代到本 service(而非主后端)。
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from geo.agent.api import router as agent_router
from geo.agent.embed.api import router as embed_router
from geo.agent.embed.im_feishu import router as im_feishu_router
from geo.agent.embed.feishu_isv import router as feishu_isv_router
from geo.agent.embed.im_wecom import router as im_wecom_router
from geo.agent.embed.im_dingtalk import router as im_dingtalk_router

app = FastAPI(title="Vigilath GEO Agent Service", version="0.1")

# 对外 /api/agent/v1/* 走 Bearer token(非 cookie),CORS 用 "*" 且不带 credentials 是安全的。
# 浏览器直连场景的精细 Origin 白名单在 token 层(agent_tokens.origins)另校验。
_origins = [o.strip() for o in (os.environ.get("AGENT_EMBED_ORIGINS") or "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router, prefix="/api", tags=["agent"])          # 内部:/api/agent/*(登录 JWT)
app.include_router(embed_router, prefix="/api", tags=["agent-embed"])    # 对外:/api/agent/v1/*(embed token)
app.include_router(im_feishu_router, prefix="/api", tags=["agent-im"])   # IM 自建:/api/agent/im/feishu/callback
app.include_router(feishu_isv_router, prefix="/api", tags=["agent-im-isv"])  # IM ISV:/api/agent/im/feishu-isv/callback
app.include_router(im_wecom_router, prefix="/api", tags=["agent-im-wecom"])  # IM 企微:/api/agent/im/wecom/callback
app.include_router(im_dingtalk_router, prefix="/api", tags=["agent-im-dingtalk"])  # IM 钉钉:/api/agent/im/dingtalk/callback


@app.get("/health")
def health():
    return {"status": "ok", "service": "geo-agent"}
