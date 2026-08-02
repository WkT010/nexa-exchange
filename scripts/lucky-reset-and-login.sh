#!/usr/bin/env bash
# ExplicitEncryption / ImplicitEncryption is a setting for reverseproxy etc.
# Let's try different approach: use lucky's command line `-rResetUser` which should reset user to default 666/666
# Actually wait - lucky needs to be running for -r flags (remote control).
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# Restart lucky again so we don't exceed login attempts
pkill -9 -f lucky; sleep 1
cd /goodluck && nohup /opt/lucky_v2.13.4 -c /goodluck/lucky.conf > /tmp/lucky.log 2>&1 &
sleep 7

# Reset user via -rResetUser while running
/opt/lucky_v2.13.4 -cd /goodluck -rResetUser 2>&1
echo "Reset user exit=$?"
sleep 2

# Now try login with default 666/666
echo "=== Login POST body Account=666, Password=666 ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
    -d '{"Account":"666","Password":"666"}' \
    -c "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
echo ""
echo "=== GET /api/status with cookie ==="
"$CURL" -s --noproxy '*' -G -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/status" 2>&1 | cut -c1-200
