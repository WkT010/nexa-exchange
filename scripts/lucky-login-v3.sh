#!/usr/bin/env bash
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# So D() is /api/status which returns twoFAEnable
echo "=== POST /api/status ==="
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' -d '{}' \
    -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/status" 2>&1
echo ""

# Now check the login page placeholder says default666. But password must be encrypted.
# Login uses R(o.value) with Account, Password, TwoFA.
# We need to figure out if password is hashed. Try md5("666") and md5(md5("666"))
echo "=== Try MD5(666) as password ==="
MD5_666=$(echo -n "666" | md5sum | cut -d' ' -f1)
echo "MD5(666) = $MD5_666"
"$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
    -d "{\"Account\":\"666\",\"Password\":\"$MD5_666\",\"TwoFA\":\"\"}" \
    -c "$COOKIE" -b "$COOKIE" \
    -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1

echo "=== Try base64(666) or just plaintext empty Account ==="
# Try empty Account/Password (from reset state)
for BODY in \
    "{\"Account\":\"\",\"Password\":\"\",\"TwoFA\":\"\"}" \
    "{\"Account\":\"666\",\"Password\":\"$(echo -n "666" | sha256sum | cut -d' ' -f1)\",\"TwoFA\":\"\"}" \
    "{\"Account\":\"666\",\"Password\":\"666666\",\"TwoFA\":\"\"}" \
    "{\"Account\":\"admin\",\"Password\":\"admin\",\"TwoFA\":\"\"}" \
    "{\"Account\":\"root\",\"Password\":\"root\",\"TwoFA\":\"\"}"; do
    echo "body=$BODY"
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        -w '\nHTTP: %{http_code}\n' --max-time 3 "${BASE}/api/login" 2>&1
done
