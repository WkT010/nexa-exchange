#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

echo "[1] Kill/restart lucky"
pkill -9 -f lucky; sleep 1
cd /goodluck
nohup /opt/lucky_v2.13.4 -c /goodluck/lucky.conf > /tmp/lucky.log 2>&1 &
sleep 7
echo "[2] Call -rResetUser"
/opt/lucky_v2.13.4 -cd /goodluck -rResetUser 2>&1; echo "exit=$?"
sleep 2
echo "[3] Login test"
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
    -d '{"Account":"666","Password":"666"}' \
    -c "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
echo ""
echo "[4] Check status"
"$CURL" -s --noproxy '*' -G -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/status" 2>&1
