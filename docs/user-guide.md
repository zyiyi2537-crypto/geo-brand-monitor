# Vigilath User Guide

Owner: frontend product experience
Last reviewed: 2026-08-28

Vigilath measures how websites, brands, and content are prepared for and appear
in generative search engines and AI assistants.

## Run a website audit

1. Open the Vigilath website and enter an HTTP or HTTPS website URL.
2. Start the GEO readiness check.
3. Keep the page open while the request is running.
4. Review the score, grade, summary counts, evidence, and recommendations.

A default audit often completes in tens of seconds, but slow target sites and
external probes can take several minutes. Advanced browser- and AI-assisted
modes can take up to roughly 15 minutes under the current request budget.

## Understand a default result

- **AI Visibility Score**: normalized website readiness score from 0 to 100.
- **Grade**: A+ for 90–100, A for 80–89, B for 70–79, C for 60–69, D for
  50–59, and F below 50.
- **PASS**: the tested signal met the current rule.
- **WARN**: the signal was present but can be improved.
- **FAIL**: the signal was missing or did not meet the rule.
- **INFO**: evidence that does not directly change the score.

Scores are a time-bound measurement, not a permanent property. Pages, search
indexes, provider responses, and network availability can change between runs.
Use the evidence and recommendations rather than relying only on the total.

## Advanced analysis

Depending on account permissions and configured providers, advanced modes can
include comparison, crawl testing, authority auditing, AEO visibility, citation
checking, AI visibility, and entity analysis. These modes may use external AI
providers or browser workers and can return partial results when an upstream
service is unavailable.

## Brand Growth

Authenticated users can use Brand Growth to inspect sources, engine
performance, competitors, monitored queries, query-engine matrices, original
responses, insights, and published outcomes. Missing or failed observations
should be treated as unknown rather than as a zero result.

## Privacy and responsible use

The checker reads public pages and does not modify the target website. Do not
submit private URLs, credentials, session-bearing URLs, or customer data.

## When to rerun

Rerun after material content, structured-data, crawl policy, canonical-host, or
site-architecture changes. For ongoing monitoring, compare runs taken under
similar conditions and retain their timestamps and evidence.
