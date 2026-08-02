#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# The request wrapper R() is a generic http client to /api/<module>
# D() call before login is /api/<something> to get login status (twoFAEnable).
# Common lucky pattern: /api/Status or /api/Setting/Status or /api/login

# Try: /api/Setting/Status (some versions)
for path in \
    "/api/Status" "/api/Setting/Status" "/api/Settings/Get" \
    "/api/login/Status2FA" "/api/twoFA/getStatus" \
    "/api/Setting/GetLoginStatus" "/api/Base/Status"; do
    echo "=== POST $path ==="
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
        -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}${path}" 2>&1 | cut -c1-200
done
