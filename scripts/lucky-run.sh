#!/usr/bin/env bash
# Save a clean lucky startup script to the workspace for reuse.
set -uo pipefail

LUCKY_BIN="/opt/lucky_v2.13.4"
CONF_DIR="/goodluck"
LOG_FILE="/tmp/lucky.log"
PID_FILE="/tmp/lucky.pid"

# Kill existing lucky by PID file
if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        kill -9 "$old_pid" 2>/dev/null || true
        sleep 1
    fi
fi

mkdir -p "$CONF_DIR"
cd "$CONF_DIR" || exit 1
setsid "$LUCKY_BIN" -c "$CONF_DIR/lucky.conf" > "$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"
echo "Lucky started, pid=$pid"
sleep 5

# Print listening ports (if ss available)
if command -v ss >/dev/null; then
    echo "--- Listening ports related to lucky ---"
    ss -tlnp 2>/dev/null | grep "lucky" || ss -tlnp 2>/dev/null | grep -E '(16601|8081)'
fi
