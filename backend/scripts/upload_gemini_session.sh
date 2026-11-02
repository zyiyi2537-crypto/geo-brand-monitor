#!/bin/bash
# Upload Gemini session + profile to browser-service.
# Usage: BROWSER_SERVICE_URL=http://aws-server:8091 bash backend/scripts/upload_gemini_session.sh
set -euo pipefail

ENGINE="gemini"
SERVER="${BROWSER_SERVICE_URL:-http://localhost:8091}"
SESSION_DIR="backend/data/browser_sessions"
SESSION_FILE="$SESSION_DIR/${ENGINE}.json"
PROFILE_FILE="$SESSION_DIR/${ENGINE}_profile.json"

if [[ ! -f "$SESSION_FILE" ]]; then
    echo "Missing $SESSION_FILE. Run: python backend/scripts/${ENGINE}_login.py"
    exit 1
fi
if [[ ! -f "$PROFILE_FILE" ]]; then
    echo "Missing $PROFILE_FILE. Re-run: python backend/scripts/${ENGINE}_login.py (saves profile too)"
    exit 1
fi

STATE=$(cat "$SESSION_FILE")
PROFILE=$(cat "$PROFILE_FILE")
PAYLOAD=$(jq -n --argjson s "$STATE" --argjson p "$PROFILE" \
    '{storage_state: $s, profile: $p}')

echo "Uploading ${ENGINE} session + profile to ${SERVER}..."
curl -fsS -X PUT "$SERVER/sessions/${ENGINE}" \
    -H "content-type: application/json" \
    -d "$PAYLOAD"
echo
echo "Done."
