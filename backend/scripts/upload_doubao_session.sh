#!/usr/bin/env bash
# Upload a local Doubao browser session using SSH key authentication.
#
# Required:
#   export VM_HOST="browser.example.com"
#
# Optional:
#   export VM_USER="ubuntu"
#   export PROXY_JUMP="bastion.example.com"
#   export REMOTE_PATH="/opt/browser-service/data/browser_sessions/doubao.json"

set -euo pipefail

SESSION_FILE="${SESSION_FILE:-backend/data/browser_sessions/doubao.json}"
VM_HOST="${VM_HOST:?Set VM_HOST to the destination hostname}"
VM_USER="${VM_USER:-ubuntu}"
PROXY_JUMP="${PROXY_JUMP:-}"
REMOTE_PATH="${REMOTE_PATH:-/opt/browser-service/data/browser_sessions/doubao.json}"

if [[ ! -f "$SESSION_FILE" ]]; then
    echo "Missing $SESSION_FILE."
    echo "Run the local Doubao login script first."
    exit 1
fi

ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=yes)
if [[ -n "$PROXY_JUMP" ]]; then
    ssh_options+=(-o "ProxyJump=$PROXY_JUMP")
fi

echo "Uploading browser session to $VM_HOST..."
scp "${ssh_options[@]}" "$SESSION_FILE" "$VM_USER@$VM_HOST:$REMOTE_PATH"

echo "Verifying remote file..."
ssh "${ssh_options[@]}" "$VM_USER@$VM_HOST" "test -s '$REMOTE_PATH'"
echo "Upload complete."
