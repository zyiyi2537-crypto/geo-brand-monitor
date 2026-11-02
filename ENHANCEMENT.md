# GEO Checker — Planned Enhancements

## Status Summary (as of 2026-04-13)

| # | Feature | Status |
|---|---------|--------|
| 1 | Competitive Comparison Analysis | ✅ DONE |
| 2 | AI Visibility Score | ✅ DONE |
| 3 | Brand Entity Establishment | ✅ DONE |
| 4 | Topical Authority & Content Depth | ⬜ Open |
| 5 | E-E-A-T Signals | ✅ DONE |
| 6 | Backlink Profile & External Mentions | ✅ DONE |
| 7 | Content Freshness & Update Cadence | ✅ DONE |
| 8 | Multi-Format Content Coverage | ✅ DONE |
| 9 | Cross-Platform Content Distribution | ✅ DONE |
| 10 | Overall GEO Report Export | ✅ DONE |
| 11 | AI Citation Tracking (`--citation-check`) | ✅ DONE |
| 11b | Expanded AI Visibility Audit (`--ai-visibility`) | ✅ DONE |
| 12 | Prompt-Aligned Content Optimization | ✅ DONE |
| 13 | Semantic Markup & Linked Data Quality | ✅ DONE |
| 14 | Content Deduplication / Cannibalization | ✅ DONE |
| 15 | AI-Specific robots.txt Granularity | ✅ DONE |
| 16 | Page-Level Entity Density | ⬜ Open |
| 17 | Conversational Content Readiness | ✅ DONE |
| 18 | AI Snippet Extraction Friendliness | ✅ DONE |
| 19 | Trust & Safety Signals | ✅ DONE |
| 20 | API & Data Feed Availability | ✅ DONE |
| 21 | Entity GEO Audit (`--entity`) | ✅ DONE |
| 22 | Keyword-Input → Entity Mode Upsell | ⬜ Open |
| 23 | Seed 4-Scene Expansion (search / qa / intent / brand) | ✅ DONE |

**Remaining open work:** #4 (topical authority / content clusters), #16 (page-level entity density), and #22 (classify brand/product keywords and upsell the Entity GEO mode). #4 and #16 both would need a deeper crawl than the current 5-page `check_multi_page` sample.

## 23. Seed 4-Scene Expansion ✅ DONE (2026-05-28)

Single seed input → server-side fan-out to 4 parallel LLM calls with scene-specific prompts → 4 categorised long-tail pools (search / Q&A / intent / brand). User ticks candidates per scene tab; each pick persists with `scene_type` on `QueryItem`. Reasoning: [`docs/geo-vs-xunling.md`](./docs/geo-vs-xunling.md) §6 #1.

Key files:
- `backend/geo/services/query_expander.py` — 4 SCENE_PROMPTS templates + `expand_one_scene`
- `backend/geo/api/ai_telemetry.py` — `expand_queries_for_topic` async fan-out via `asyncio.gather`
- `backend/geo/models/ai_telemetry.py` — `SceneType` literal, `QueryItem.scene_type`, `MonitoredQueryItem.scene_type`, `TopicOut.query_scene_types`
- `frontend/src/components/SceneExpander.tsx` — single-input + 4-checkbox + tab-based results UI
- `frontend/src/pages/User/TopicProfile.tsx` — MonitorView integration + scene badges on existing queries

## 22. Keyword-Input → Entity Mode Upsell ⬜ Open

When a user types a non-URL (brand / product / person name) on the home page — e.g. "超响应", "Notion", "iPhone 15" — the anonymous check currently fails with a generic "Unable to analyze this URL" error. Detect this case up front and convert the dead-end into a funnel:

- **Classifier** (backend, runs before `sanitize_url`): hostname is empty / has whitespace / has no dot / has a dot but TLD not in Public Suffix List → label `entity_keyword`. Raise `AppException(422, ..., details={"kind": "entity_keyword", "keyword": "<raw>"})`.
- **Frontend error branch** on `details.kind === "entity_keyword"`:
  - Free / below-Pro: CTA → open TierModal highlighting the Pro tier
  - Pro+: CTA → deep-link to `/advanced/entity` with the keyword pre-filled
  - Always expose a secondary "input a URL instead" link back to `/`
- **Logging**: `requests.jsonl` records `classified_as: "entity_keyword"` so we can measure CTA conversion.

TLD detection: hard-code a Top-200 public-suffix set to avoid adding `tldextract` as a dependency. IP addresses get a tiny `ipaddress.ip_address()` bypass so `192.168.x.x` stays classified as a URL.

Depends on: existing `error_i18n.localize()` chain, existing `TierModal`, existing `/check/advanced/entity` endpoint (all in place).

---

## 1. Competitive Comparison Analysis ✅ DONE
Compare GEO readiness across multiple URLs (`geo_checker.py --compare url1 url2 url3`) with a side-by-side scorecard showing which site wins on each check.

**Implementation:** `--compare` flag accepts multiple URLs. Runs all 23 checks silently on each, collects per-category scores, displays a side-by-side table with scores, percentages, overall AI Visibility Score, winner, point lead, and per-category advantages.

## 2. AI Visibility Score ✅ DONE
A metric measuring how likely a site is to appear in AI-generated answers. Combines crawlability, structured data, content quality, authority, and freshness into a single 0-100 score.

**Implementation:** All 23 check categories now track earned/max points via `track_score()`. Produces a 0-100 score with letter grade (A+ through F). Displayed at the end of every report with a per-category breakdown and visual bar chart.

## 3. Brand Entity Establishment ✅ DONE
Check if the brand exists as a recognized entity in Knowledge Graphs, Wikidata, Wikipedia — verifiable identity that AI engines trust.

**Implementation:** New `check_brand_entity_kg()` function runs in default URL mode. Derives brand candidates from JSON-LD Organization name, `og:site_name`, title suffix, and domain. Queries the Wikipedia and Wikidata search APIs. Also pulls Wikipedia backlinks (up to 50) as a proxy for external authority (#6). Scored 0-5 under `Brand Entity KG`.

## 4. Topical Authority & Content Depth
Assess whether the site covers its core topics comprehensively through interlinked content clusters, not just isolated pages.

## 5. E-E-A-T Signals ✅ DONE
Check for author bio pages, credentials, external bylines, and expertise indicators beyond basic author meta tags.

**Implementation:** `check_authority_trust()` now probes `/about`, `/about-us`, `/team`, `/authors`, `/our-team`, `/people` for a substantive bio page, then scans for credential keywords (PhD, MD, founder, formerly at, published in, etc.) and external bylines on major outlets (Medium, Substack, Forbes, HBR, arxiv, ORCID, Google Scholar).

## 6. Backlink Profile & External Mentions ✅ DONE
Assess third-party corroboration: authoritative sites linking to or mentioning the brand.

**Implementation:** Covered by `check_brand_entity_kg()` via the Wikipedia `backlinks` API — counts how many Wikipedia pages link to the brand's article. `--authority-audit` continues to handle the multi-platform probe side.

## 7. Content Freshness & Update Cadence ✅ DONE
Measure how frequently content is updated across the site, not just homepage freshness.

**Implementation:** `check_ai_optimization()` now fetches `sitemap.xml` (or `sitemap_index.xml` with child sitemap following), parses up to 200 `<lastmod>` entries, and computes median page age and the fraction updated in the last 90 days. Reports sitewide cadence as healthy / moderate / low.

## 8. Multi-Format Content Coverage ✅ DONE
Check for content diversity: video + transcripts, podcasts, PDFs, infographics — more formats = more AI surface area.

**Implementation:** `check_outbound_and_media()` now detects podcasts (audio tags, Spotify/Apple/Anchor/Soundcloud links, PodcastSeries schema), PDFs (links ending in .pdf), infographics (alt/src keywords), and slides (SlideShare, Speaker Deck). Reports total format count.

## 9. Cross-Platform Content Distribution ✅ DONE
Detect presence on YouTube, Medium, LinkedIn, Reddit, Quora — platforms AI models train on.

**Implementation:** New `check_cross_platform()` function detects brand presence on 10 platforms (X/Twitter, LinkedIn, YouTube, GitHub, Reddit, Facebook, Instagram, Medium, TikTok, Quora). Uses a two-phase approach: (1) on-page signals from sameAs JSON-LD, social links, and meta tags, (2) active URL probing for platforms not found on-page. Shows AI training context mapping each platform to the AI models it feeds. Scores 0-5 based on coverage count.

## 10. Overall GEO Report Export ✅ DONE
JSON/HTML/PDF export for stakeholders, CI/CD integration, and tracking improvements over time.

**Implementation:** Single `--report [FORMAT]` flag with `FORMAT` ∈ {`pdf`, `json`, `html`}. Bare `--report` defaults to `pdf` (paginated Courier PDF of the run's terminal output). `--report json` emits a structured JSON document (schema_version, generated_at, mode, target, overall score, grade, per-category earned/max/percent). `--report html` writes a styled standalone HTML page with score header, per-category bar chart, and captured run output. All variants write to `~/geo_reports/<timestamp>/report.<ext>` and compose with any audit mode.

## 11. AI Citation / Source Attribution Tracking ✅ DONE (v1)
Check whether the site is actually being cited by AI engines (Perplexity, ChatGPT with browsing, Gemini). This is the ultimate GEO outcome metric — measure whether AI-generated answers reference or link back to the site.

**v1 Implementation:** `--citation-check URL` flag (PAID feature, requires `PERPLEXITY_API_KEY` env var). Sends 5-6 brand-relevant queries to the Perplexity Sonar API (e.g., "What is {brand}?", "{brand} review", "Best alternatives to {brand}"). Checks if the target domain appears in the `citations` array or is mentioned in the answer text. Produces a citation rate percentage, AI Visibility grade (A-F), per-query breakdown, and actionable recommendations if citation rate is low. Handles rate limiting, auth errors, and graceful fallbacks.

### 11b. Expanded AI Visibility Audit (`--ai-visibility`) ✅ DONE v2
Evolve `--citation-check` into a comprehensive "Would AI recommend this brand for the right query?" audit. Core philosophy: **measure selection signals, not just mention counts.**

**Custom query support** — Accept `--queries "best AI payment tools" "x402 tools"` so users can test category-specific prompts relevant to their niche, not just generic brand queries.

**Entity definition consistency** — Send "What is {brand}?" and "What does {brand} do?" multiple times. Check whether AI gives a consistent, accurate definition (e.g., "MoltsPay is a payment layer for AI agents") or returns confused/contradictory answers. Flag brand confusion (e.g., AI confuses your product with wallets, exchanges, or unrelated tools).

**Competitor tracking** — For each query, report which competitors get cited alongside (or instead of) the brand. Track whether the brand is framed as a leader, alternative, or niche option. Output a competitor co-mention matrix.

**Answer stability** — Run each query 3x and classify results as: stable mention (3/3), unstable mention (1-2/3), or never mentioned (0/3). Brands want robust presence, not lucky one-off mentions.

**AI answer framing analysis** — Classify how the AI describes the brand: leader, recommended option, one-of-many, experimental, niche. Detect "recommended-action" language ("use X", "consider X", "one option is X") which is stronger than passive mentions.

**Missing-topic gap detection** — Test prompts where the brand *should* appear based on its category but doesn't. These are the highest-value content gaps to fix. Output as an actionable "create content for these topics" list.

**Category association check** — Verify AI associates the brand with the right concepts (e.g., "AI agent payments", "x402", "crypto payment SDK") rather than wrong categories. Weak association = weak entity positioning.

**Multi-model support** — Test across multiple AI engines when API keys are available:
- Perplexity (`PERPLEXITY_API_KEY`) — always-on web search with structured citations
- OpenAI (`OPENAI_API_KEY`) — ChatGPT with web search tool
- Claude (`ANTHROPIC_API_KEY`) — Claude with web search tool
- Compare visibility across engines since each has different training data and retrieval

**Composite GEO Health Score** — Output a scorecard with sub-scores:
```
Prompt Visibility:     X/20  (cited in how many target queries)
Entity Clarity:        X/20  (consistent, accurate definitions)
Source Coverage:        X/20  (present on platforms AI references)
Competitor Position:   X/20  (framing relative to competitors)
Content Gap Score:     X/20  (missing-topic coverage)
─────────────────────────────
GEO Health:           X/100
```

## 12. Prompt-Aligned Content Optimization ✅ DONE
Detect whether content answers question-style queries directly (who/what/how/why patterns). AI engines serve content that maps to how users prompt them — pages structured around natural questions rank higher in AI answers.

**Implementation:** Added a 6th check to `check_ai_answer_formats()` that regex-matches headings against question-pattern starters (who/what/how/why/when/where/is/are/can/does/do/should/will/which/whose/whom) and the trailing `?` suffix. Scores 1/6 for 3+ question headings.

## 13. Semantic Markup & Linked Data Quality ✅ DONE
Beyond basic JSON-LD detection, validate that structured data uses specific, granular schema types (e.g., `HowTo`, `Recipe`, `Product` with reviews, `FAQPage`) rather than just generic `WebPage` or `Article`. Richer schema types give AI engines more extractable facts.

**Implementation:** `check_structured_data()` now walks every JSON-LD block (including `@graph` children) and classifies types into `GRANULAR_TYPES` (HowTo, Recipe, FAQPage, QAPage, Product, Review, AggregateRating, Event, Course, JobPosting, SoftwareApplication, Dataset, Article, NewsArticle, BlogPosting, VideoObject, LocalBusiness, Organization, BreadcrumbList) vs. `GENERIC_TYPES` (Thing, WebPage, WebSite, CreativeWork). Additionally checks whether `Product` objects include `review`/`aggregateRating` fields.

## 14. Content Deduplication / Cannibalization ✅ DONE
Detect pages competing for the same topic or keywords, which confuses AI engines about which page to cite. Flag near-duplicate titles, meta descriptions, and content overlap across pages.

**Implementation:** `check_multi_page()` now collects titles alongside descriptions for duplicate detection and computes 5-gram Jaccard similarity between every pair of sampled pages. Flags any pair with ≥50% overlap as potential cannibalization and suggests consolidation or `rel=canonical`.

## 15. AI-Specific robots.txt Granularity ✅ DONE
Beyond checking if AI bots are allowed or blocked, assess whether the site has a *strategic* allow/block policy. Check for `ai.txt`, per-bot directives, and whether the policy balances crawl access (for citation) vs. training opt-out (for IP protection).

**Implementation:** `check_robots_txt()` now probes `/ai.txt` and `/.well-known/ai.txt`, reports allow-focused / disallow-focused / balanced policies based on directive mix, and awards 0-2 pts.

## 16. Page-Level Entity Density
Measure how clearly each page defines and reinforces a single entity or topic. Pages with a clear primary entity help AI engines extract clean, attributable facts rather than muddled multi-topic content.

## 17. Conversational Content Readiness ✅ DONE
Check for Q&A pairs, "People Also Ask" style content, and conversational tone that maps well to chat-based AI interfaces. Detect question headings (`<h2>How do I...?</h2>`) and direct-answer patterns.

**Implementation:** Covered by the same question-heading detection added for #12 in `check_ai_answer_formats()`.

## 18. AI Snippet Extraction Friendliness ✅ DONE
Detect whether key facts appear in extractable positions (first paragraph, table cells, list items, definition lists) vs. buried deep in prose. AI engines preferentially extract content from prominent, structured positions.

**Implementation:** `check_outbound_and_media()` now locates the first substantive paragraph inside `<main>` / `<article>` / `<body>` and checks whether it (a) contains a definition verb (is/are/means/refers to/describes) and/or (b) contains a statistic (percent, dollar amount, comma-separated number, or year) within a 25-120 word window — the ideal snippet length.

## 19. Trust & Safety Signals ✅ DONE
Check for privacy policy, terms of service, contact information completeness, DMCA/copyright pages, and business registration details. These are trust signals AI engines use to assess source credibility and determine citation-worthiness.

**Implementation:** New `check_trust_safety()` function registered in the default pipeline. Probes common paths for Privacy (/privacy, /privacy-policy, /legal/privacy, …), Terms (/terms, /tos, /terms-of-service, …), Contact (/contact, /support, /help, …), and DMCA/legal/imprint pages — falling back to homepage anchor-text matching when the path isn't standard. Also scans the footer and full page text for email, phone, physical-address hints, and legal entity markers (LLC/Inc/Ltd/GmbH/SA/EIN/VAT/SIREN/company number), and cross-checks JSON-LD Organization for `address`, `contactPoint`, and `telephone`. Scored 0-6 under `Trust & Safety`.

## 20. API & Data Feed Availability ✅ DONE
Beyond OpenAPI detection, check for RSS feed richness (full content vs. excerpts), webhook/integration documentation, and machine-readable data exports. AI agents increasingly consume structured data feeds programmatically.

**Implementation:** `check_technical_crawlability()` now fetches the discovered feed, parses its items/entries, and measures the average content length per item: ≥300 words is flagged "full content", 80-299 is "excerpts", <80 is "headlines". Also probes /api, /api/v1, /graphql, /openapi.{json,yaml}, /swagger.json, /docs/api, /webhooks, /integrations, /developers for machine-readable / integration endpoints.

## 21. Entity GEO Audit (`--entity`) ✅ DONE
Audit the GEO readiness of a **brand, product, or person** — without requiring a URL. Instead of crawling a website, this mode queries AI engines to assess how well an entity is recognized, described, and recommended across AI-powered search.

**Usage:**
```bash
# Brand
geo-checker --entity "Stripe" --entity-type brand

# Product
geo-checker --entity "ChatGPT" --entity-type product

# Person
geo-checker --entity "Andrej Karpathy" --entity-type person
```

Requires `OPENAI_API_KEY` environment variable.

**How it works:** Two-phase approach: (1) Free checks probe Wikipedia, Wikidata, and 8 major platforms for entity presence, (2) Paid checks send targeted queries to OpenAI GPT-4o-mini with web search and analyze responses. Queries are tailored per entity type — brands get competitor/market queries, products get feature/alternative queries, persons get expertise/contribution queries. All 8 dimensions support `--fix` for actionable recommendations.

### Checks & Scoring (8 dimensions, 0-20 each, 160 total)

**1. Entity Recognition (0-20)** — PAID
Ask "What is {entity}?" / "Who is {entity}?" multiple times. Score based on whether AI returns a substantive, accurate answer vs. "I don't know" or confused responses. Measures whether the entity exists in AI's knowledge at all.

**2. Entity Clarity (0-20)** — PAID
Run the same identity query 3x and compare answers for consistency. Detect contradictions, confusion with other entities, or vague/generic descriptions. High clarity = AI gives the same accurate definition every time.

**3. Category Association (0-20)** — PAID
Test whether AI associates the entity with the right concepts. For brands: industry/market category. For products: use case/problem space. For persons: field of expertise/known contributions. Score based on how strongly and correctly AI maps the entity to its domain.

**4. Competitive Position (0-20)** — PAID
For brands/products: ask "Best alternatives to {entity}" and "How does {entity} compare to competitors?" — analyze whether it's framed as a leader, recommended option, or niche player. For persons: ask about peers/leaders in their field — is the person mentioned among top experts?

**5. Sentiment & Framing (0-20)** — PAID
Analyze how AI describes the entity across all responses. Classify language as: strongly positive, positive, neutral, mixed, or negative. Detect "recommended-action" language ("use X", "consider X") which is stronger than passive mentions. For persons: detect credibility/authority language.

**6. Content Gap Analysis (0-20)** — PAID
Test queries where the entity *should* appear based on its type/category but doesn't. These represent the highest-value content creation opportunities. Output as an actionable "create content for these topics" list.

**7. Knowledge Graph Presence (0-20)** — FREE
Check if the entity exists in Wikipedia (search API), Wikidata (search API), and infer Google Knowledge Panel presence. These are the structured knowledge sources AI engines trust most — entities in knowledge graphs get cited far more reliably.

**8. Cross-Platform Footprint (0-20)** — FREE
Probe 8 major platforms AI models train on: X/Twitter, LinkedIn, YouTube, GitHub, Reddit, Facebook, Medium, TikTok. Uses the same profile URL probing and soft-404 detection logic as the URL-mode `check_cross_platform()` for consistency. Searched by name, not scraped from a URL.

### Entity-Type-Specific Queries

**Brand queries:**
- "What is {entity}?", "What does {entity} do?"
- "Is {entity} reliable/trustworthy?"
- "Best alternatives to {entity}"
- "{entity} vs competitors", "{entity} review"
- Industry/category queries (e.g., "best payment platforms")

**Product queries:**
- "What is {entity}?", "What does {entity} do?"
- "Is {entity} worth it?", "{entity} pros and cons"
- "Best alternatives to {entity}"
- "{entity} vs {competitor}" style queries
- Category queries (e.g., "best project management tools")

**Person queries:**
- "Who is {entity}?"
- "What is {entity} known for?"
- "{entity} contributions to {field}"
- "Top experts in {field}" / "Leaders in {field}"
- "{entity} publications/work/research"

### Output

```
============================================================
  ENTITY GEO AUDIT: "Stripe" (brand)
============================================================

  Entity Recognition     18/20  ██████████████████░░  90%
  Entity Clarity         16/20  ████████████████░░░░  80%
  Category Association   14/20  ██████████████░░░░░░  70%
  Competitive Position   12/20  ████████████░░░░░░░░  60%
  Sentiment & Framing    16/20  ████████████████░░░░  80%
  Content Gap            10/20  ██████████░░░░░░░░░░  50%
  ──────────────────────  ─────
  ENTITY GEO SCORE       86/120

  Grade: B

  Key Findings:
  - AI consistently recognizes Stripe as an online payment platform
  - Strong positive sentiment; frequently recommended
  - Competitors mentioned: PayPal, Square, Adyen
  - Content gaps: "Stripe for marketplaces", "Stripe vs Adyen 2024"
```

---

## Bug Fixes Applied

- **Facebook soft-404 detection** — Facebook returns HTTP 200 for non-existent pages but redirects to `/login/`. Detection now catches login redirects and expanded soft-404 phrases ("content isn't available", "does not exist", etc.).
- **GitHub detection in authority audit** — Switched from guessing `github.com/{brand}` (fails when org name differs from domain) to GitHub Search API which finds repos by name regardless of owner.
- **npm detection in authority audit** — Switched from scraping search page (returns 403) to npm registry JSON API (`registry.npmjs.org/{package}`).
- **PyPI detection in authority audit** — Switched from project page (returns captcha) to PyPI JSON API (`pypi.org/pypi/{package}/json`).
