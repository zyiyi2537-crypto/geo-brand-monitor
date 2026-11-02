# Content and Workbench Workflow

Owner: content, AI telemetry, and admin-workbench components
Last reviewed: 2026-08-28

This document describes the maintained product workflow from brand setup to
measurement. API routes, permission checks, and persisted state remain
authoritative.

## Roles

- **Administrator**: creates projects, edits profiles, starts runs, reviews
  generated material, and manages publication state.
- **Customer**: views reports, evidence, brand-growth metrics, and published
  outcomes for accounts they can access.
- **Worker**: owns asynchronous execution, retries, idempotency, and progress
  updates.

Every mutation must be account-scoped and auditable. Long-running work must
expose pending, running, completed, and failed states.

## End-to-end pipeline

1. Create or update a brand profile.
2. Generate and review query seeds.
3. Expand and classify queries.
4. Run GEO and AI-visibility checks.
5. Generate content under template, source, and platform constraints.
6. Review and approve material.
7. Publish through a configured connector and record the outcome.
8. Measure mentions, citations, sentiment, and downstream results.

The customer can read completed results without a separate manual audit-approval
gate. Content publication remains a reviewed action unless a connector and
explicit automation policy are configured.

## Template model

Templates are persisted in `content_templates` and managed through
`/api/admin/content-templates`. A template has scope, kind, prompt content,
and lock state. Once locked, prompt and kind are read-only through the API.

Generation may combine a brand profile's creation directions and copywriting
types. Each generated document preserves its source query, template, direction,
copywriting type, platform, and owning topic so the output can be reproduced and
reviewed.

Template requirements:

- separate system policy from user and source material;
- include audience, objective, tone, language, facts, and platform constraints;
- render only documented variables and reject unsupported combinations;
- return structured content suitable for review before publication;
- never embed provider keys, customer secrets, or private infrastructure data.

## State and failure behavior

- Workers, not UI components, own retries and scheduling.
- A retry must be idempotent and must not create duplicate documents or
  publications.
- Partial provider failure must remain visible with evidence and a retry path.
- Publication records must distinguish draft, approved, publishing, published,
  and failed states.
- The UI must link operational state to the route or service responsible for it.

## Implementation map

- Content templates: `backend/geo/api/content_templates.py`
- Content generation: `backend/geo/services/content_generator.py`
- Scheduling: `backend/geo/services/content_scheduler.py`
- Content APIs: `backend/geo/api/content.py`
- Admin review: `backend/geo/api/admin_content_review.py`
- Workbench UI: `frontend/src/pages/Workbench/`
- Customer outcomes: `frontend/src/pages/BrandGrowth/Published.tsx`

Agent methods for automatic publication and proactive notification still contain
unimplemented paths. Do not describe those paths as generally available until
their implementations and permission checks are complete.
