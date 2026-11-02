# GEO Checker Reliability, Performance, and Cost

Owner: GEO checker and advanced-runners components
Last reviewed: 2026-08-28

Vigilath combines live web requests, search indexes, browser automation, and
probabilistic AI providers. Latency, cost, and result variability must therefore
be managed as one operational concern.

## Request budgets

The frontend GEO API client currently permits a request to run for up to 900
seconds. Individual default page fetches normally use a 15-second timeout;
several specialized probes and AI calls have their own smaller or larger
budgets. nginx and upstream load-balancer timeouts must be configured from the
actual endpoint budget rather than a single global assumption.

Advanced operations should prefer asynchronous task APIs or streaming progress
over holding one HTTP request open. Any change to the 900-second client timeout
must be coordinated with backend, nginx, load-balancer, and worker limits.

## Sources of variability

Results can differ between runs because:

1. target pages, cache variants, and availability change;
2. search and social indexes update asynchronously;
3. AI providers sample responses and change models;
4. retries, rate limits, and timeouts alter available evidence;
5. parallel checks can expose shared mutable state or ordering dependencies.

Record the URL, timestamp, checker version, provider, model, query, retry count,
and evidence used by each run. Scoring should remain deterministic after
evidence collection.

## Performance priorities

1. Run independent default checks concurrently while preserving dependencies
   such as sitemap discovery.
2. Keep all state request-local; remove broad locks and module-global mutable
   scores or caches.
3. Use bounded exponential backoff with jitter for rate-limited providers.
4. Return partial results when a non-critical upstream fails.
5. Track P50, P95, and P99 latency, upstream error rate, queue time, retries,
   cancellation, and worker utilization.

Timing instrumentation is implemented in `backend/geo/utils/timing.py`.
Production diagnostics can use `geo.timing` records and the
`X-Process-Time` response header.

## AI workload and cost model

Do not hard-code provider prices in this repository. Prices and model
availability change; obtain current rates from the provider before setting
quotas.

Estimate a run with:

```text
run cost =
  sum over provider calls(
    input_tokens / 1,000,000 * input_rate
    + output_tokens / 1,000,000 * output_rate
  )
  + browser/session infrastructure cost
```

Visibility is usually the largest workload because it expands across query and
engine combinations. Entity and citation modes make several provider calls.
AEO is mainly local page analysis.

For every call, record account, run, provider, model, input tokens, output
tokens, status, latency, and retry count. Enforce quotas before dispatch and
bound both output tokens and retries.

## Testing

- Use recorded pages and fixed provider responses for deterministic regression
  tests.
- Keep live smoke tests separate; they verify availability, not exact scores.
- Compare scores and evidence before and after concurrency changes.
- Load-test representative default, visibility, entity, and citation workloads.

Implementation references:

- `backend/geo_checker/`
- `backend/geo/services/advanced_runners.py`
- `backend/geo/utils/timing.py`
- `frontend/src/services/geoApi.ts`
