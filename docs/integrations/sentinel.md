# Sentinel Integration

Owner: Sentinel service and backend sentiment integration
Last reviewed: 2026-08-28

Sentinel collects brand mentions, performs LLM-assisted analysis, creates
briefs, and drafts response variants. The current storage implementation uses
PostgreSQL with one schema per account.

## Current architecture

- The main backend owns account configuration, scheduling, permissions, and the
  customer-facing sentiment API.
- `services/sentinel-service/` owns collection, search recall, analysis,
  briefs, drafts, and tenant-bound storage.
- Tenant data is isolated with PostgreSQL schemas named
  `tenant_<account_id>`; `DATABASE_URL` is required.
- The backend calls Sentinel through
  `backend/geo/services/sentinel_client.py`.

The root Compose file does not currently provision PostgreSQL or provide
`DATABASE_URL` to Sentinel. A Compose deployment must supply an external
database and the missing environment value before sentiment operations are
usable.

## Capability boundaries

Current capabilities include multi-source collection, deduplication, sentiment
and risk analysis, briefs, response drafts, and account-scoped retrieval.
Coverage and reliability vary by source because public endpoints, cookies,
anti-bot controls, and index freshness differ.

Gaps that require explicit tracking include:

- measurable recall by source and representative fixture;
- alert-latency and deduplication service levels;
- membership entitlement and quota enforcement in the main backend;
- retention and cleanup for run history;
- operational capacity for PostgreSQL and long-running analysis jobs.

## Detailed references

- Current service entry point:
  `services/sentinel-service/README.md`
- Current PostgreSQL storage:
  `services/sentinel-service/storage/db.py`
- Source research:
  `services/sentinel-service/docs/search-engine-recall-2026-05-11.md`
- Source expansion notes:
  `services/sentinel-service/docs/sentiment-sources-weixin-newsnow.md`

`sentiment-architecture.md` describes the pre-PostgreSQL design.
`sentiment-architecture-v2.md` is a historical MySQL target design and does
not describe the current storage implementation. Neither should be used as an
operations runbook.
