#!/bin/bash
# Setup x11vnc on vm03 attached to the existing Xvfb :99 display
# (the same display browser-service uses for headed Chrome).
#
# Usage (on the browser-service host):
#   export VNC_PASSWORD="a-long-random-secret"
#   bash /opt/browser-service/setup_vnc.sh
#
# After this:
#   1. Open SSH tunnel from your Mac:
#        ssh -L 5900:127.0.0.1:5900 user@browser-host
#   2. On Mac, open VNC client to vnc://127.0.0.1:5900
#      - macOS Finder: Cmd+K → vnc://127.0.0.1:5900
#      - Or: open vnc://127.0.0.1:5900
#   3. You'll see the same display browser-service runs Chrome on.

set -euo pipefail

VNC_PASSWORD="${VNC_PASSWORD:?Set VNC_PASSWORD to a strong secret before running this script}"
VNC_PORT=5900
DISPLAY_NUM=":99"

echo "[1/4] Installing x11vnc..."
if ! command -v x11vnc >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q x11vnc xdotool xfonts-base
fi

echo "[2/4] Verifying Xvfb on $DISPLAY_NUM..."
if ! pgrep -f "Xvfb $DISPLAY_NUM" >/dev/null; then
    echo "  Xvfb not running on $DISPLAY_NUM."
    echo "  browser-service starts it lazily — trigger it once first:"
    echo "    curl -s -X POST http://127.0.0.1:8092/search -H 'Content-Type: application/json' \\"
    echo "      -d '{\"engine\":\"doubao\",\"query\":\"warmup\"}' &"
    echo "  Then re-run this script."
    exit 1
fi

echo "[3/4] Setting up VNC password..."
mkdir -p /root/.vnc
x11vnc -storepasswd "$VNC_PASSWORD" /root/.vnc/passwd >/dev/null

echo "[4/4] Starting x11vnc on port $VNC_PORT (display $DISPLAY_NUM)..."
# Kill old x11vnc instances
pkill -f "x11vnc.*-rfbport $VNC_PORT" 2>/dev/null || true
sleep 1

# Start x11vnc bound to localhost only (we tunnel via SSH)
x11vnc \
    -display "$DISPLAY_NUM" \
    -rfbauth /root/.vnc/passwd \
    -rfbport "$VNC_PORT" \
    -localhost \
    -bg \
    -forever \
    -shared \
    -noxdamage \
    -repeat \
    -ncache 0 \
    -o /var/log/x11vnc.log

sleep 1
if pgrep -f "x11vnc.*-rfbport $VNC_PORT" >/dev/null; then
    echo "  x11vnc started (PID: $(pgrep -f "x11vnc.*-rfbport $VNC_PORT"))"
    echo "  log: /var/log/x11vnc.log"
else
    echo "  ERROR: x11vnc failed to start. Check /var/log/x11vnc.log"
    tail /var/log/x11vnc.log 2>/dev/null
    exit 1
fi

echo
echo "============================================================"
echo "  VNC ready on 127.0.0.1:$VNC_PORT (localhost-only)"
echo "  Password: use the value supplied through VNC_PASSWORD"
echo
echo "  From your Mac:"
echo "    ssh -L $VNC_PORT:127.0.0.1:$VNC_PORT user@browser-host"
echo "    open vnc://127.0.0.1:$VNC_PORT"
echo "============================================================"
