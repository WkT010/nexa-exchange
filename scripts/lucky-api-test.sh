#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
BASE="http://localhost:16601"

echo "=== POST /api/login ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
    -d '{"Account":"666","Password":"666"}' \
    -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' \
    --max-time 3 "${BASE}/api/login" 2>&1

echo ""
echo "=== POST /api/reverseproxy/list ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
    -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' \
    --max-time 3 "${BASE}/api/reverseproxy/list" 2>&1 | head -200
