# Vigilath GEO Skill

This skill connects a compatible AI agent to the Vigilath GEO agent API. It
supports audit, diagnosis, optimization, monitoring, and reporting workflows.

The client uses only the Python standard library. Authentication uses a
long-lived account token, which must be treated like an API key.

## Install

Obtain a token from the Vigilath integration page, then run:

```bash
curl -fsSL https://geo.vigilath.com/skill/install.sh | bash -s -- --token 'YOUR_TOKEN'
```

The installer copies the skill to a detected skills directory, writes the
credential to `~/.vigilath/config` with mode 600, and runs a connectivity
check. Use `--dir PATH` to choose a destination.

Passing a token on a command line may expose it through shell history or the
process list. Prefer a protected environment or an interactive secret-injection
mechanism when available.

## Manual installation

Copy `vigilath-geo/` into the host agent's skills directory. Configure the
token in one of these locations:

```text
~/.vigilath/config:
VIGILATH_AGENT_TOKEN=...
```

or:

```bash
export VIGILATH_AGENT_TOKEN='...'
```

Never hard-code, print, or commit the token.

## Verify

```bash
python3 ~/.claude/skills/vigilath-geo/scripts/geo_client.py capabilities
python3 ~/.claude/skills/vigilath-geo/scripts/geo_client.py data today
python3 ~/.claude/skills/vigilath-geo/scripts/geo_client.py chat "How many monitored questions mention my brand?"
```

`chat` returns natural-language output and structured card JSON. `data`
retrieves structured data without an LLM call.

## Scope

- Engine selection, schedules, and collection frequency are controlled by the
  Vigilath platform.
- External publishing remains behind platform guardrails.
- HTTP 401 means the token is invalid or expired.

The API under `/api/agent/v1/*` uses regular HTTP. `chat` returns SSE;
`data/*` and `meta/*` return JSON. Send the token as
`Authorization: Bearer <token>`.
