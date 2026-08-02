#!/usr/bin/env bash
# Start Lucky v2.13.4 cleanly
set -uo pipefail

LUCKY_BIN="/opt/lucky_v2.13.4"
CONF_DIR="/goodluck"
LOG_FILE="/tmp/lucky-v2.13.4.log"
PID_FILE="/tmp/lucky-v2.13.4.pid"

mkdir -p "$CONF_DIR"

# Kill existing lucky processes
if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$old_pid" ]; then
        kill -9 "$old_pid" 2>/dev/null || true
    fi
fi
pkill -9 -f lucky 2>/dev/null || true
sleep 1

# Start Lucky
cd "$CONF_DIR"
nohup "$LUCKY_BIN" -c "$CONF_DIR/lucky.conf" > "$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"
echo "Lucky started, pid=$pid"

# Wait for it to come up
for i in $(seq 1 10); do
    sleep 1
    if curl -sf --noproxy '*' -o /dev/null --max-time 3 http://localhost:16601/ 2>/dev/null; then
        echo "[OK] Lucky is running on http://localhost:16601 after ${i}s"
        tail -5 "$LOG_FILE"
        exit 0
    fi
done

echo "[ERROR] Lucky failed to start"
tail -20 "$LOG_FILE"
exit 1
