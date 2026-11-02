# GEO 品牌监测中心

GEO 品牌监测中心（`geo-brand-monitor`）用于记录品牌在 AI 回答中的提及、目标品牌排名、竞品排名和引用来源，并生成带问题明细和饼图的报告。

当前网页工作台入口为 `/unified-monitor`，重点接入 DeepSeek、豆包、元宝、文心一言、通义千问。管理员登录后可以填写各模型服务的 HTTPS 请求地址、模型名和 API Key，并执行连接测试。API Key 在服务器上加密保存，不会随本仓库发布。

模型 API 回答与对应 App、网页的回答可能不同。当前浏览器会话状态可查询，网页内扫码授权流程尚未接通；五个平台的真实 API 也尚未全部实测。部署与当前限制见 [网页监测工作台说明](docs/new-geo-monitor.md)。

本项目基于 Vigilath 扩展，保留上游的 MIT 许可证及以下项目文档。

## Upstream: Vigilath

Vigilath is an open-source GEO and AI-visibility platform for measuring how websites, brands, and content appear across generative search engines and AI assistants. It combines website audits, AI visibility measurement, citation analysis, brand monitoring, and content operations in one extensible stack.

## Repository Navigation

This repository contains the web application, audit engine, supporting services, and developer tooling.

- `frontend/`: React, TypeScript, and Vite web application.
- `backend/geo/`: Main FastAPI application and API routes.
- `backend/geo_checker/`: Active GEO audit package and CLI.
- `backend/geo/agent/`: Isolated conversational agent.
- `backend/api_engine/`: API-based AI engine adapters.
- `backend/browser_engine/`: Browser-engine abstractions and session handling.
- `services/`: Browser automation, telemetry, sentiment monitoring, and egress proxies.
- `skills/vigilath-geo/`: Installable agent skill and standalone client.
- `tests/integration/`: Playwright and SSE integration probes.
- `docs/`: Architecture, deployment, operations, and user documentation.

For a detailed map of the documentation set, see [`docs/README.md`](docs/README.md). Start with [`docs/architecture.md`](docs/architecture.md) for the runtime model.

## Core Capabilities

- **GEO auditing**: score websites across 25 technical, content, authority, discovery, and AI-readiness categories.
- **AI visibility measurement**: query multiple AI engines and track mentions, rankings, citations, and answer coverage.
- **AEO and citation analysis**: inspect answer-engine readiness, citation evidence, entities, and authority signals.
- **Brand monitoring**: collect multi-source mentions, classify sentiment and risk, and support response workflows.
- **Content operations**: expand queries, generate drafts, review content, schedule publication, and attribute citations.
- **Agent workflows**: use a conversational agent for diagnostics and long-running GEO operations.
- **API and CLI access**: run audits interactively, in CI, or through the FastAPI service.

## New Web-First Monitor

The new API-first control console lives at [`/unified-monitor`](frontend/src/pages/UnifiedMonitor.tsx). It is backed by the unified routes in [`backend/geo/api/unified.py`](backend/geo/api/unified.py), which choose API engines before browser sessions and expose brand mention/ranking, pie-chart summaries, and citation ranking in one evidence report. See [`docs/new-geo-monitor.md`](docs/new-geo-monitor.md) and `docker-compose.server.yml` for the server deployment profile.
## Quick Start

For the five-platform GEO monitoring workflow and its readable report, see [QUICKSTART.md](QUICKSTART.md). The desktop entry point is `GEO-Monitor.pyw`; enter a brand, published article URLs, and keywords directly in the task form.

### Prerequisites

- Python 3.12 recommended for the backend; Python 3.9+ for the standalone CLI.
- Node.js `^20.19.0 || >=22.12.0` and npm (required by the current Vite 8 frontend).
- Git. Docker and Docker Compose are optional for local service orchestration.

### CLI installation

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/geo-checker https://example.com
```

Common modes include `--compare`, `--crawl-test`, `--authority-audit`, `--aeo-visibility`, `--citation-check`, `--ai-visibility`, and `--entity`. JSON and HTML reports are supported; the PDF path is not production-ready.

### Web application

Start the backend:

```bash
cd backend
python -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
venv/bin/python -m uvicorn geo.main:app --host 127.0.0.1 --port 8070 --reload
```

In a second terminal, start the frontend:

```bash
cd frontend
npm ci
npm run dev
```

The Vite development server uses port 3000 and proxies `/api` to the backend.

### Docker Compose

```bash
docker compose up --build
```

The root Compose stack is intended for local development. Agent, browser, telemetry, proxy, and payment services may require additional environment configuration.

## Security and Deployment Considerations

- Copy `backend/.env.example` to a local `.env`; never commit real credentials.
- Store API keys, OAuth secrets, payment credentials, private keys, cookies, browser sessions, and database passwords in a secret manager or protected runtime environment.
- Generate `SECRET_KEY` with a cryptographically secure random generator.
- Configure explicit authentication, quotas, and account isolation before exposing services publicly.
- Review [`docs/deployment-guide.md`](docs/deployment-guide.md) before deploying and [`SECURITY.md`](SECURITY.md) before reporting a vulnerability.
- Historical credentials were removed from the rewritten Git history. Delete old clones, backups, and caches before distributing a copy.

## Development and Testing

```bash
python -m pytest
cd frontend
npm run lint
npm run build
```

Some integration tests require external services and credentials. Keep test fixtures synthetic and avoid recording customer data or browser sessions.

## Support and Contribution

- Read the architecture, deployment, performance, and user guides under [`docs/`](docs/).
- Report reproducible bugs and feature requests through GitHub Issues.
- Submit focused pull requests with tests or a clear verification note.
- Keep new maintained documentation in English and update [`docs/README.md`](docs/README.md) when adding or retiring documents.

## Citation

```bibtex
@software{vigilath,
  author    = {Zen7 Labs},
  title     = {Vigilath: GEO and AI Visibility Platform},
  publisher = {GitHub},
  url       = {https://github.com/sr007-cxy/Vigilath}
}
```

## License

MIT License. See [`LICENSE`](LICENSE).




The current preview opens the monitor directly. An administrator must sign in before using the unified API. Model API keys are created in the relevant provider console, saved through the monitor configuration form, and verified with the connection test action. Create the administrator from the backend directory with `python -m scripts.create_unified_admin`.
