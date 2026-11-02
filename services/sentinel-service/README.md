# Sentinel Service

Sentinel is the brand-monitoring microservice used by the Vigilath backend. It
collects posts from multiple sources, performs LLM-assisted analysis, creates
briefs, and drafts responses.

## API

| Method | Path | Purpose | LLM key required |
| --- | --- | --- | --- |
| POST | `/run-monitor` | Plan, collect, and persist posts | Yes |
| POST | `/run-analyze` | Analyze unprocessed posts | Yes |
| POST | `/run-brief` | Generate a Markdown brief | Yes |
| POST | `/run-respond` | Generate response variants | Yes |
| POST | `/run-crawl-eastmoney` | Crawl Eastmoney directly | No |
| GET | `/accounts/{id}/posts` | List posts and analyses | No |
| GET | `/accounts/{id}/briefs` | List briefs | No |
| GET | `/accounts/{id}/briefs/{brief_id}` | Get a brief | No |
| GET | `/accounts/{id}/drafts` | List drafts | No |
| GET | `/health` | Health check | No |

An `X-OpenAI-Key` request header overrides the service-level
`OPENAI_API_KEY` environment variable.

## Tenant isolation

Tenant data is stored in PostgreSQL. Each account receives a schema named
`tenant_<account_id>`; the storage layer sets `search_path` for every
tenant-bound connection.

Set `DATABASE_URL` before starting the service.

## Development

```bash
cd services/sentinel-service
python -m venv .venv
.venv/bin/pip install -e .
export DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/DB'
export OPENAI_API_KEY='replace-with-a-secret-from-your-secret-manager'
.venv/bin/uvicorn service:app --reload --port 8090
```

Do not commit either value.

## Container

```bash
docker compose up sentinel-service
```

The main backend calls this service through
`backend/geo/services/sentinel_client.py`.
