# GEO 优化 Agent 独立 service 部署 runbook(方案 B)

> 为什么独立:`pydantic-ai` 需 `pydantic>=2.11`,主后端钉死 `fastapi==0.104.1`+`pydantic==2.5.0`,不兼容。
> 独立 venv + 独立进程,共用同一 DB / `SECRET_KEY` / `OPENROUTER_API_KEY`,主后端零改动、零风险。

## vm02 部署步骤

```bash
cd /opt/geo

# 1) 独立 venv(与主后端 /opt/geo/backend/venv 隔离)
python3 -m venv /opt/geo/agent-venv
/opt/geo/agent-venv/bin/pip install -U pip
/opt/geo/agent-venv/bin/pip install -r /opt/geo/backend/requirements-agent.txt

# 2) 自检:能 import geo 链 + 构造 agent(dummy key,不联网)
cd /opt/geo/backend && OPENROUTER_API_KEY=dummy /opt/geo/agent-venv/bin/python \
  -c "from geo.agent.service import app; from geo.agent.agent import build_agent; build_agent(); print('OK')"

# 3) systemd
sudo cp /opt/geo/backend/deploy/geo-agent.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now geo-agent.service
curl -s -o /dev/null -w "agent /health: %{http_code}\n" http://127.0.0.1:8010/health   # 期望 200

# 4) nginx:把片段并入 server{},reload
#    (内容见 deploy/nginx-agent.conf;/api/agent/ 最长前缀优先于 /api/)
sudo nginx -t && sudo systemctl reload nginx

# 5) 冒烟
curl -s -o /dev/null -w "agent diagnose(无token): %{http_code}\n" -X POST http://127.0.0.1/api/agent/diagnose   # 期望 401(已挂载)
# 带 token + 已建主题 → 应返回 DeepSeek 出的根因(真功能冒烟)
```

## 升级 / 回滚
- 升级:`git pull` 后 `agent-venv/bin/pip install -r requirements-agent.txt`(如依赖变)+ `systemctl restart geo-agent`。
- 回滚:`systemctl stop geo-agent` —— 主后端完全不受影响(agent 是独立进程)。

## 主后端不变
主后端 venv **不要装 pydantic-ai**(`requirements.txt` 里已注释);`geo/main.py` 不挂 agent 路由。
