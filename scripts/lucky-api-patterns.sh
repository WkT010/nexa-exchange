#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
BASE="http://localhost:16601"

# Try broader list of common API patterns from Lucky source
for path in \
    "/api/login/GetKey" "/api/login/getkey" "/api/login/GetPublicKey" \
    "/api/getLoginKey" "/api/LoginKey" "/api/loginKey" \
    "/api/BaseConfInfo" "/api/baseConfInfo" "/api/info" \
    "/api/status" "/api/Status"; do
    echo "=== $path ==="
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
        -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}${path}" 2>&1 | cut -c1-300
done
