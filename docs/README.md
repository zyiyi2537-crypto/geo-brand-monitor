# Documentation index

This directory contains the maintained architecture, operations, product, and
engineering documentation for Vigilath. Source code and automated tests remain
authoritative when a document and the implementation disagree.

## Status definitions

- **Normative** — a contract or operational procedure that must be kept in sync
  with implementation changes.
- **Maintained** — reviewed overview or guidance, but not an API contract.
- **Historical** — retained only for context and never an operational source of
  truth.

## Start here

| Document | Purpose | Status |
| --- | --- | --- |
| [architecture.md](architecture.md) | Runtime topology, component ownership, data stores, and scaling boundaries | Maintained |
| [deployment-guide.md](deployment-guide.md) | Local Compose constraints and production release, backup, and rollback procedures | Normative |
| [user-guide.md](user-guide.md) | End-user audit workflow and result interpretation | Maintained |

## Contracts and engineering

| Document | Purpose | Status |
| --- | --- | --- |
| [contracts/url-and-outbound-fetch-security.md](contracts/url-and-outbound-fetch-security.md) | Shared URL syntax contract and required server-side outbound-fetch controls | Normative |
| [engineering/checker-reliability-and-performance.md](engineering/checker-reliability-and-performance.md) | Timeouts, variability, retries, performance, and AI cost controls | Maintained |
| [i18n-status.md](i18n-status.md) | Frontend locale loading behavior and translation review checklist | Normative |

## Product workflows

| Document | Purpose | Status |
| --- | --- | --- |
| [product/content-workflow.md](product/content-workflow.md) | Brand profile, query, content generation, review, publication, and measurement workflow | Maintained |
| [product/ai-telemetry.md](product/ai-telemetry.md) | Brand Growth information architecture, KPI contracts, and implementation map | Maintained |

## Integrations and runbooks

| Document | Purpose | Status |
| --- | --- | --- |
| [integrations/sentinel.md](integrations/sentinel.md) | Current Sentinel architecture, capability boundaries, and detailed service references | Maintained |
| [runbooks/public-site-geo-checklist.md](runbooks/public-site-geo-checklist.md) | Public-site identity and discovery-file verification | Normative |

## Documentation outside this directory

Component-specific operational details should stay next to the component:

- `services/sentinel-service/README.md` is the current Sentinel service entry
  point.
- `services/*/docs/` may contain implementation PRDs and historical designs;
  each such document must state whether it describes current or target state.
- `backend/deploy/` contains deployable systemd and nginx assets.
- `skills/vigilath-geo/README.md` documents the installable agent skill.

Root-level `COMPARISON.md`, `ENHANCEMENT.md`, and `OPTIMIZATION.md` are planning
or analysis records. They are not operational sources of truth.

## Maintenance policy

- Write maintained documentation in English.
- Add an owner or owning component and a last-reviewed date to documents whose
  facts can drift.
- Update a normative document in the same change as its implementation.
- Prefer one maintained entry point per subject. Mark superseded designs as
  historical and link to their replacement.
- Never store credentials, browser sessions, cookies, customer data, or private
  infrastructure details in documentation.
