#!/bin/bash
set -uo pipefail

LOCAL_PORT="${1:-8080}"
LOG_FILE="/tmp/serveo-tunnel2.log"
PID_FILE="/tmp/serveo-tunnel2.pid"
PROXY="127.0.0.1:18080"

if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        kill "$old_pid" 2>/dev/null || true
        sleep 1
    fi
fi

echo "[INFO] Starting serveo tunnel for port $LOCAL_PORT with script PTY..."
script -q -c "ssh \
    -o StrictHostKeyChecking=no \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o ProxyCommand=\"nc -X connect -x $PROXY %h %p\" \
    -R 80:localhost:$LOCAL_PORT \
    serveo.net" /dev/null > "$LOG_FILE" 2>&1 &

TUNNEL_PID=$!
echo "$TUNNEL_PID" > "$PID_FILE"
echo "[INFO] Tunnel PID=$TUNNEL_PID, waiting for URL..."
sleep 12

URL=$(grep -o 'https://[a-z0-9-]*\.serveousercontent\.com' "$LOG_FILE" 2>/dev/null | tail -1)
if [ -n "$URL" ]; then
    echo "[OK] Tunnel established: $URL"
    echo "$URL" > /tmp/serveo-url.txt
    echo "PUBLIC_URL: $URL"
else
    echo "[WARN] No URL found in log"
    echo "=== LOG CONTENT ==="
    cat "$LOG_FILE" 2>/dev/null || echo "(empty log)"
    echo "=== END LOG ==="
fi