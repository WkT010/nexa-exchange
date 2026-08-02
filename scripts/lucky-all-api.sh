#!/usr/bin/env bash
# The /api/status didn't work with POST. Let's check it with GET.
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
BASE="http://localhost:16601"

for METHOD in GET POST; do
  for path in "/api/status" "/api/Status" "/api/baseconfigure" "/api/info" "/api/modules/list" "/api/twofapassword"; do
    echo "=== $METHOD $path ==="
    if [ "$METHOD" = "GET" ]; then
      "$CURL" -s --noproxy '*' -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}${path}" 2>&1 | cut -c1-200
    else
      "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
        -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}${path}" 2>&1 | cut -c1-200
    fi
  done
done
