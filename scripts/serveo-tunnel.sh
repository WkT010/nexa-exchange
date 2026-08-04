#!/usr/bin/env bash
# Serveo.net SSH reverse tunnel for intranet penetration.
# Exposes the local api-gateway (port 8080) to the public internet via serveo.net.
# Uses the HTTP proxy (127.0.0.1:18080) via nc ProxyCommand since the sandbox
# has no direct outbound internet access.
#
# Usage: ./scripts/serveo-tunnel.sh [local_port]
#   local_port defaults to 8080

set -uo pipefail

LOCAL_PORT="${1:-8080}"
LOG_FILE="${TUNNEL_LOG:-/tmp/serveo-tunnel.log}"
PID_FILE="${TUNNEL_PID:-/tmp/serveo-tunnel.pid}"
PROXY="${http_proxy:-http://127.0.0.1:18080}"
# nc -x expects host:port without scheme
PROXY_HOSTPORT="${PROXY#http://}"
PROXY_HOSTPORT="${PROXY_HOSTPORT#https://}"
PROXY_HOSTPORT="${PROXY_HOSTPORT%%/*}"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

# Kill any existing tunnel
if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        log "[INFO] killing previous tunnel (pid=$old_pid)"
        kill "$old_pid" 2>/dev/null || true
        sleep 1
    fi
fi
pkill -f "ssh.*serveo.net" 2>/dev/null || true
sleep 1

start_tunnel() {
    log "[INFO] starting serveo tunnel for port $LOCAL_PORT..."
    setsid ssh \
        -o StrictHostKeyChecking=no \
        -o ServerAliveInterval=60 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o ProxyCommand="nc -X connect -x $PROXY_HOSTPORT %h %p" \
        -R 80:localhost:"$LOCAL_PORT" \
        serveo.net > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    log "[INFO] tunnel pid=$pid, waiting for URL..."
    sleep 8
}

# Extract the public URL from the log
get_url() {
    grep -o 'https://[a-z0-9-]*\.serveousercontent\.com' "$LOG_FILE" | tail -1
}

start_tunnel

URL=$(get_url)
if [ -n "$URL" ]; then
    log "[OK] tunnel established: $URL"
    echo "$URL" > /tmp/serveo-url.txt
    echo "============================================"
    echo "  PUBLIC URL: $URL"
    echo "============================================"
else
    log "[WARN] no URL found in log, retrying..."
    sleep 5
    URL=$(get_url)
    if [ -n "$URL" ]; then
        log "[OK] tunnel established (retry): $URL"
        echo "$URL" > /tmp/serveo-url.txt
        echo "============================================"
        echo "  PUBLIC URL: $URL"
        echo "============================================"
    else
        log "[ERROR] failed to establish tunnel"
        cat "$LOG_FILE"
    fi
fi
