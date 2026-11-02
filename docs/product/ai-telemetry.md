# AI Telemetry and Brand Growth

Owner: AI telemetry backend and Brand Growth frontend
Last reviewed: 2026-08-28

AI telemetry measures whether engines discover, retrieve, cite, summarize, and
recommend a brand. Brand Growth presents those observations as sources,
engines, competitors, query matrices, responses, insights, and publication
outcomes.

## Information architecture

| Area | Primary question |
| --- | --- |
| Overview | Is visibility improving, and what changed? |
| Sources | Which domains and pages are cited? |
| Engines | How does performance differ by engine? |
| Competitors | Which brands appear instead of the target? |
| Queries and matrix | Which query-engine combinations were run and hit? |
| Responses | What evidence appeared in the original answer? |
| Insights | What likely explains missed or gained visibility? |
| Published | What was released, and what happened afterward? |

## KPI contract

Core KPI groups are:

- **Discovery**: crawl coverage, indexed URLs, and retrieval success.
- **Visibility**: mention rate, rank, share of voice, and query coverage.
- **Citation**: citation frequency, source quality, and linked-page coverage.
- **Sentiment**: positive, neutral, and negative mention ratios.
- **Conversion**: qualified visits, leads, and downstream outcomes when
  attribution data is available.

Every displayed value must define:

- raw observation source;
- numerator and denominator;
- aggregation window and timezone;
- account and topic scope;
- freshness and last successful run;
- behavior for missing, partial, and failed data.

Missing data must not silently render as zero. Store raw observations separately
from derived aggregates so metrics can be recomputed.

## Processing contract

1. Expand approved seeds into monitored queries.
2. Dispatch query-engine work idempotently.
3. Preserve raw responses, citations, timestamps, engine, and model metadata.
4. Match mentions and sources using versioned rules.
5. Compute aggregates from raw observations.
6. Generate optional diagnostics and recommendations with their model and
   evidence provenance.
7. Surface retryable failures without converting them into negative results.

## Implementation map

- API: `backend/geo/api/ai_telemetry.py`
- Models: `backend/geo/models/ai_telemetry.py`
- Service workers: `services/telemetry-service/app/`
- Frontend: `frontend/src/pages/BrandGrowth/`
- API client: `frontend/src/services/aiTelemetryApi.ts`

Detailed implementation PRDs under `services/telemetry-service/docs/` contain
historical phase plans. They are useful design context, but current routes,
schemas, and this maintained contract take precedence.
