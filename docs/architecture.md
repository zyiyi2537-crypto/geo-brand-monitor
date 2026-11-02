# Vigilath Architecture

Owner: application architecture
Last reviewed: 2026-08-28

This document describes the current runtime architecture of Vigilath, a GEO and AI-visibility platform.

## System overview

Vigilath combines a React web application, a FastAPI API, a reusable GEO audit engine, an isolated conversational agent, browser automation, telemetry, and sentiment monitoring.

Core capabilities:

- Run a 25-category GEO audit and produce a 0-100 AI Visibility Score.
- Measure AI-engine mentions, citations, rankings, and query coverage.
- Generate, review, schedule, and publish optimization content.
- Monitor brand sentiment and generate briefs and response drafts.
- Provide account, membership, quota, and payment workflows.

## Service topology

```text
Browser
  |
  v
React/Vite frontend (:3000)
  |
  +--> Main FastAPI backend (:8070)
  |       +--> PostgreSQL / SQLite (development)
  |       +--> Redis (optional)
  |       +--> Sentinel service (:8090)
  |
  +--> Agent service (:8010, separate environment)

Supporting services:
  browser-service, telemetry-service, openrouter-proxy, ddg-proxy, newsnow (:4444)
```

The root `docker-compose.yml` starts the frontend, backend, Sentinel, and
NewsNow. It is a development convenience, not a complete production topology:
it does not provision PostgreSQL, does not pass Sentinel's required
`DATABASE_URL`, and does not persist the backend's default SQLite database.
Browser, telemetry, proxy, and agent services use separate configurations.

## Frontend

`frontend/` is a React 19 and TypeScript application built with Vite. It uses React Router, TanStack Query, i18next, Recharts, Axios, and client-side report exporters. The development server listens on port 3000 and proxies `/api` to the backend on port 8070.

## Main backend

`backend/geo/` contains the FastAPI application. `backend/geo/main.py` mounts the API routers for audits, authentication, OAuth, accounts, membership, payments, sentiment, telemetry, content, engine sessions, administration, and contact workflows.

The backend follows an API/service/model layout:

- `api/`: HTTP routes and request/response schemas.
- `services/`: business logic, integrations, scheduling, caching, and publishing.
- `models/`: SQLAlchemy models and Pydantic schemas.
- `alembic/` and `migrations/`: database migrations.

The recommended production data store is PostgreSQL. Local development defaults
to SQLite and should use `backend/.env.example` for configuration. Legacy
single-host SQLite deployments require an explicit backup and migration plan.

## GEO audit engine

`backend/geo_checker/` is the active audit package and CLI implementation. `CHECK_REGISTRY` in `backend/geo_checker/orchestrate.py` is the single source of truth for the 25 categories.

The root `geo_checker.py` is a frozen compatibility baseline. `archive/geo_checker_v1_baseline.py` is historical reference code. New audit work belongs in `backend/geo_checker/`.

## Agent service

`backend/geo/agent/` exposes a separate FastAPI service on port 8010. It runs in an isolated environment because the conversational agent uses newer Pydantic and Pydantic AI dependencies than the main backend. The agent shares the application database and signing configuration through protected environment variables and provides typed tools for audit, content, sentiment, and knowledge workflows.

## Supporting services

- `services/browser-service/`: Playwright-based browser adapters and session handling. Login sessions must be supplied at runtime and never committed.
- `services/telemetry-service/`: AI visibility telemetry and gateway APIs.
- `services/sentinel-service/`: multi-tenant brand monitoring, crawling, search recall, sentiment analysis, briefs, and response drafting. Tenant data is isolated with PostgreSQL schemas.
- `services/openrouter-proxy/` and `services/ddg-proxy/`: optional egress/search proxies.
- `newsnow`: third-party self-hosted hot-list aggregation used by Sentinel.

## Security boundaries

Secrets, browser sessions, cookies, database credentials, and payment keys are runtime configuration. The backend requires an explicit `SECRET_KEY`; production deployments must use a secret manager or protected environment. CORS origins and service URLs should be configured for the deployment rather than copied from development examples.

## Deployment

For local development, install the component dependencies, copy the relevant `.env.example` files, and start the backend and frontend separately. For a containerized development stack, run `docker compose up --build`.

Deployment profiles, rollback procedures, systemd units, and nginx
configuration are documented in `docs/deployment-guide.md` and
`backend/deploy/`.

## Scaling constraints

The web layer is intended to use stateless workers backed by shared PostgreSQL
and optional Redis. Background schedulers use a leader guard; a durable external
task queue, distributed scheduler coordination, and database capacity planning
are still required for a multi-node deployment.

## Related maintained documentation

- [Deployment and operations](deployment-guide.md)
- [Checker reliability and performance](engineering/checker-reliability-and-performance.md)
- [Sentinel integration](integrations/sentinel.md)
- [Content workflow](product/content-workflow.md)
- [AI telemetry](product/ai-telemetry.md)
