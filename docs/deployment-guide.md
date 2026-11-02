# Deployment and Operations Guide

Owner: backend, frontend, and platform operations
Last reviewed: 2026-08-28

This guide distinguishes the repository's local Compose stack from the
recommended production topology. Keep credentials in a runtime secret store;
never commit `.env` files.

## Supported profiles

### Local development

Run the frontend and backend directly, or use the root Compose file. The backend
defaults to SQLite when `DATABASE_URL` is absent.

The current Compose file is not a self-contained production stack:

- it does not provision PostgreSQL or Redis;
- it does not persist the backend's default SQLite database;
- Sentinel requires an externally supplied PostgreSQL `DATABASE_URL`;
- browser, telemetry, proxy, agent, and payment services are not all included.

Treat Compose as a development convenience and supply the missing dependencies
explicitly when exercising Sentinel or other supporting services.

### Production

The recommended production topology uses:

- an HTTPS load balancer or reverse proxy;
- nginx for the built Vite application;
- FastAPI/Uvicorn on a private listener;
- PostgreSQL for durable application and Sentinel data;
- protected runtime configuration for credentials and service URLs;
- an external backup target and monitoring.

SQLite is suitable for local development and may exist in legacy single-host
deployments, but it is not the recommended production data store.

## Required software

- Ubuntu 22.04 or a supported equivalent
- Python compatible with the selected component; Python 3.12 is recommended
- Node.js `^20.19.0 || >=22.12.0` for the current Vite 8 frontend
- nginx and systemd for the documented single-host deployment
- PostgreSQL client and backup tools for production

## Pre-deployment checks

```bash
python -m compileall -q backend
python -m pytest
cd frontend
npm ci
npm run lint
npm run build
```

Do not deploy merely because the frontend build succeeds: lint, backend tests,
migrations, and secret scanning are separate release gates.

## Database migrations and backups

For PostgreSQL:

1. create a database backup and verify its destination;
2. record the current Alembic revision;
3. run migrations using the release's environment;
4. verify the application and Sentinel can connect;
5. retain the pre-release backup until the rollback window expires.

For a legacy SQLite deployment, stop writes or take an application-consistent
copy before migration. Record the database path explicitly; do not assume
`backend/data/geo_checker.db` without checking `DATABASE_URL`.

## Backend service

Run the main API on a private address such as `127.0.0.1:8070`. The service
must load its environment from a protected location and restart on failure.
Apply migrations before accepting traffic. The deployable agent systemd and
nginx assets are under `backend/deploy/`.

## nginx essentials

- Serve the SPA fallback while preserving real discovery files:
  `robots.txt`, `sitemap.xml`, `llms.txt`, `llms-full.txt`,
  `humans.txt`, and `/.well-known/`.
- Use immutable caching for hashed `/assets/` files.
- Proxy `/api/` to the main backend.
- Configure buffering and read timeouts per endpoint budget. Some current GEO
  operations can run for up to 900 seconds, so a 600-second proxy timeout is not
  sufficient for every synchronous path.
- Validate changes with `sudo nginx -t` before reloading nginx.

## Release workflow

1. Fetch the intended revision and confirm the working tree is clean.
2. Back up the active database.
3. Install locked backend and frontend dependencies.
4. Run the release gates above.
5. Apply migrations.
6. Publish `frontend/dist/` atomically.
7. Restart or roll the backend workers.
8. Verify `/`, `/api/health`, authentication, a representative audit, and
   public discovery files.
9. Monitor errors and latency through the rollback window.

## Rollback and monitoring

Rollback requires both the previous application artifact and a compatible
database state. Avoid reversing a migration until its downgrade behavior and
data-loss impact have been reviewed.

Monitor service restarts, migration failures, 5xx responses, queue depth,
provider failures, `X-Process-Time`, P95/P99 latency, and requests approaching
their client or proxy deadline.
