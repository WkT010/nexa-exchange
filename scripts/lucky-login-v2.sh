#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# The Login page uses placeholder "default666" meaning default Account=666, Password=666
# Login is called via R(o.value) which is a request wrapper.
# Look at D() call before login: probably /api/login/status or /api/twoFA status
# Let's try all lucky API endpoints that are common by convention from older versions

echo "=== POST /api/login/Status ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login/Status" 2>&1 | cut -c1-200
echo ""

echo "=== POST /api/TwoFA/Status ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/TwoFA/Status" 2>&1 | cut -c1-200
echo ""

echo "=== POST /api/twoFA/status ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/twoFA/status" 2>&1 | cut -c1-200
echo ""

echo "=== POST /api/login (Account=666 Password=666 TwoFA empty) ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
    -d '{"Account":"666","Password":"666","TwoFA":""}' \
    -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
echo ""

echo "=== Check if there is a RememberMe or similar field ==="
for BODY in \
    '{"Account":"666","Password":"666","TwoFA":"","RememberPassword":true}' \
    '{"Account":"666","Password":"666","RememberPassword":true}'; do
    echo "body=$BODY"
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
done
