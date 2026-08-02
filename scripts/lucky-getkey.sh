#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
BASE="http://localhost:16601"

for path in "/api/publicKey" "/api/rsakey" "/api/getPublicKey" "/api/login/publicKey" "/api/key" "/api/getkey" "/api/loginKey"; do
    echo "=== GET $path ==="
    "$CURL" -s --noproxy '*' -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}${path}" 2>&1 | cut -c1-200
    echo ""
done

echo "=== POST /api/getKey (empty body) ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/getKey" 2>&1 | cut -c1-300
echo ""

echo "=== POST /api/login/getKey ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login/getKey" 2>&1 | cut -c1-300
