#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
BASE="http://localhost:16601"

# Try different credential formats for v2.13.4
for BODY in \
    '{"username":"666","password":"666"}' \
    '{"Account":"666","Password":"666"}' \
    '{"user":"666","pass":"666"}' \
    '{"name":"666","pwd":"666"}'; do
    echo "=== body: $BODY ==="
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        -w '\nHTTP: %{http_code}\n' \
        --max-time 3 "${BASE}/api/login" 2>&1
    echo ""
done
