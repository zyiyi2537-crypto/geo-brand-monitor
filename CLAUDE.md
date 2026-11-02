# Vigilath Development Guide

## Project scope

Vigilath is a multi-service GEO/AEO and AI visibility platform. It includes a
React frontend, a FastAPI backend, a reusable audit package and CLI, an
isolated Pydantic AI agent, and browser, telemetry, monitoring, and proxy
services.

## Audit-engine source of truth

There are three related audit-engine copies, but only one is active:

| Location | Status | Modification policy |
| --- | --- | --- |
| `backend/geo_checker/` | Active package used by FastAPI and the installed CLI | Make all fixes and features here |
| `geo_checker.py` | Frozen pre-refactor standalone baseline | Do not modify |
| `archive/geo_checker_v1_baseline.py` | Frozen historical baseline | Do not modify |

When porting an upstream change, inspect the baseline diff and manually apply
the relevant behavior to `backend/geo_checker/`.

## Main components

- `frontend/`: React 19, TypeScript, Vite, TanStack Query, i18next.
- `backend/geo/`: main FastAPI service on port 8070.
- `backend/geo/agent/`: isolated agent service on port 8010.
- `services/sentinel-service/`: PostgreSQL-backed, multi-tenant brand
  monitoring on port 8090.
- `services/browser-service/`: Playwright browser automation.
- `services/telemetry-service/`: AI visibility telemetry and gateway.
- `skills/vigilath-geo/`: standalone skill client.

## Dependency boundary

The main backend pins FastAPI 0.104.1 and Pydantic 2.5.0. Pydantic AI requires
newer Pydantic and FastAPI versions, so the agent must run in its own virtual
environment using `backend/requirements-agent.txt`. Do not install agent
requirements into the main backend environment.

## CLI modes

Free modes:

- default 25-category audit
- `--fix`
- `--compare`
- `--crawl-check`
- `--crawl-test`
- `--authority-audit`
- `--aeo-visibility`

Credential-backed modes:

- `--citation-check`
- `--ai-visibility`
- `--entity`

Use `geo-checker --help` as the source of truth for arguments and required
credentials.

## Development rules

- Keep documentation and new code comments in English.
- Never commit credentials, environment files, session exports, cookies,
  private keys, or database passwords.
- Use `backend/.env.example` only as a schema; put real values in ignored
  environment files or a secret manager.
- Keep user changes outside the task intact.
- Add or update tests for behavior changes.
- Treat `backend/geo_checker/orchestrate.py::CHECK_REGISTRY` as the source of
  truth for default audit category names and order.

## Running locally

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/geo-checker https://example.com

cd backend
python -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
venv/bin/python -m uvicorn geo.main:app --port 8070 --reload

cd ../frontend
npm ci
npm run dev
```

The frontend listens on port 3000 and proxies `/api` to port 8070.
