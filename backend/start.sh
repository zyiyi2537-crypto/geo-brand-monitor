#!/usr/bin/env bash
set -euo pipefail

export DOTENV_SKIP_LOAD=true
export GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-test-google-client-id}"
: "${SECRET_KEY:?Set SECRET_KEY to a unique value of at least 32 characters}"

python3 -m uvicorn geo.main:app --host 0.0.0.0 --port 8070 --reload
