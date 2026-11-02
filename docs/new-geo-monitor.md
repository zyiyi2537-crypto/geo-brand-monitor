# GEO 品牌监测中心

This web workbench extends the desktop GEO-Monitor workflow with a unified monitoring page at `/unified-monitor`. Its current provider list is DeepSeek, Doubao, Yuanbao, Wenxin, and Qwen.

## Current workflow

1. Start the backend and frontend, then open `/unified-monitor`.
2. Create an administrator from the backend directory with `python -m scripts.create_unified_admin`, then sign in on the page.
3. Configure each provider with its HTTPS Chat Completions endpoint, model name, and provider API key. The application does not issue provider keys.
4. Use the connection test for each configured provider before starting a monitoring run. Tests send real requests and may incur provider charges.
5. Enter the target brand, aliases, competitor brands, published article URLs, and questions. Choose the providers and start a batch.
6. Inspect target-brand mention flags and ranks, competitor rankings, charts, answer evidence, and citation links. Download the report or JSON evidence export.

All `/api/unified` endpoints require an administrator login. Saved keys are encrypted on the backend using a key derived from `UNIFIED_CREDENTIAL_KEY` or `SECRET_KEY`; these values must remain stable across restarts. Provider configuration lives in `backend/data/unified-providers.enc` by default and reports live under `reports/unified/`. These runtime files are excluded from Git.

## Local preview

Install the backend requirements in a virtual environment, copy `backend/.env.example` to `backend/.env`, and configure a strong `SECRET_KEY` and a working database. Then run:

```powershell
cd backend
python -m scripts.create_unified_admin
python -m uvicorn geo.main:app --host 127.0.0.1 --port 8070 --reload
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000/unified-monitor`. Set `VITE_API_PROXY` when the backend uses another address.

## Server deployment

`docker-compose.server.yml` provides a server deployment template with PostgreSQL, Redis, the API, telemetry, browser workers, and a frontend server. Copy `.env.server.example` to `.env`, set the database password and stable encryption secret, then build the stack:

```bash
docker compose -f docker-compose.server.yml up -d --build
docker compose -f docker-compose.server.yml exec api python -m scripts.create_unified_admin
```

Configure the five providers through the authenticated workbench after startup. Provider variables retained in the environment template belong to older adapters; the current unified API uses the configurations saved through the workbench. Persistent volumes must preserve the database, backend configuration, reports, and any browser sessions. Protect externally reachable services with appropriate authentication and HTTPS.

## Current limits

- Only OpenAI-compatible Chat Completions requests are supported by the unified API configuration. The Responses protocol requires another adapter.
- Model API answers can differ from the corresponding consumer app or website. Reports must be interpreted according to the transport actually used.
- The workbench shows saved browser-session status; this does not confirm that a platform login is still valid. In-page QR authorization is not connected yet.
- The configuration and monitoring workflow has been verified with a simulated upstream. All five real provider APIs have not yet been tested together.
- Active monitoring jobs are stored in process memory, while completed reports are saved to disk. Multiple API replicas require shared job coordination before use.
- The server deployment template has not yet been validated as a complete production deployment.
