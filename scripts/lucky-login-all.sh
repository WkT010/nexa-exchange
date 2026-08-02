#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# Try all credential formats for fresh config
for BODY in \
    '{"username":"666","password":"666"}' \
    '{"Account":"666","Password":"666"}' \
    '{"account":"666","password":"666"}' \
    '{"User":"666","Pass":"666"}'; do
    echo "=== POST /api/login body=$BODY ==="
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        -w '\nHTTP: %{http_code}\n' \
        --max-time 3 "${BASE}/api/login" 2>&1
    echo ""
done

# Also try GET login endpoints or other paths
for PATH in "/Login" "/admin/login" "/user/login" "/auth/login"; do
    echo "=== POST $PATH ==="
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d '{"Account":"666","Password":"666"}' \
        -c "$COOKIE" \
        -w '\nHTTP: %{http_code}\n' \
        --max-time 3 "${BASE}${PATH}" 2>&1
    echo ""
done
