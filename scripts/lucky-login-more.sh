#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# Try lucky's default admin/admin as first
for BODY in \
    '{"Account":"admin","Password":"admin"}' \
    '{"Account":"admin","Password":"666"}' \
    '{"Account":"666","Password":"admin"}' \
    '{"Account":"","Password":""}' \
    '{"Account":"lucky","Password":"lucky"}'; do
    echo "=== $BODY ==="
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        -w '\nHTTP: %{http_code}\n' \
        --max-time 3 "${BASE}/api/login" 2>&1
done