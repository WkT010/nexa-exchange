#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# Reset user first (runs against running lucky)
/opt/lucky_v2.13.4 -cd /goodluck -rResetUser 2>&1
echo "Reset exit=$?"
sleep 2

# Try all credential combinations
for BODY in \
    '{"Account":"666","Password":"666"}' \
    '{"Account":"666","Password":"666","TwoFA":""}' \
    '{"Account":"admin","Password":"admin"}' \
    '{"Account":"lucky","Password":"666"}' \
    '{"Account":"666","Password":"lucky"}' \
    '{"Account":"root","Password":"666"}'; do
    echo "body=$BODY"
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        --max-time 3 "${BASE}/api/login" 2>&1
    echo ""
done
