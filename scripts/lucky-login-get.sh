#!/usr/bin/env bash
# Lucky uses GET for API calls. And password is likely encrypted on client side.
# Let's try to look for the "encrypt/ /api/login with GET
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# GET /api/login?Account=666&Password=...
echo "=== GET /api/login?Account=666&Password=666 ==="
"$CURL" -s --noproxy '*' -G -c "$COOKIE" -b "$COOKIE" \
    --data-urlencode "Account=666" \
    --data-urlencode "Password=666" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
echo ""

# D() call returns ret==0 twoFAEnable
echo "=== GET /api/status before login ==="
"$CURL" -s --noproxy '*' -G -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/status" 2>&1
echo ""

# Check if password needs to be hashed differently (R = encryptedPassword)
echo "=== Try GET with empty login GET params: /api/login with md5 password"
MD5_666=$(echo -n "666" | md5sum | cut -d' ' -f1)
echo "MD5 666 = $MD5_666"
"$CURL" -s --noproxy '*' -G -c "$COOKIE" -b "$COOKIE" \
    --data-urlencode "Account=666" \
    --data-urlencode "Password=$MD5_666" \
    --data-urlencode "TwoFA=" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
echo ""

# Also try Password666 or some other common patterns
# Let's try:  echo "=== Try reverseproxy endpoint with raw md5 twice"
MD5_2=$(echo -n "$MD5_666" | md5sum | cut -d' ' -f1)
echo "MD5x2 666 = $MD5_2"
"$CURL" -s --noproxy '*' -G -c "$COOKIE" -b "$COOKIE" \
    --data-urlencode "Account=666" \
    --data-urlencode "Password=$MD5_2" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
