#!/usr/bin/env bash
# Since we can't login with defaults, let's approach from the data/configuration side.
# Lucky stores config in /goodluck/lucky_*.lkcf binary files (gob encoded with XOR encryption).
# Instead of trying to reverse the encryption, try installing a DIFFERENT version of lucky that
# definitely supports default 666/666 credentials. v2.13.4 is old enough; maybe the issue is
# that the fresh lucky setup requires setting a NEW password on first login (like many UIs),
# which means the Account/Password are created on first submit.
set -uo pipefail
CURL="/usr/bin/curl"
COOKIE="/tmp/lucky-cookies.txt"
rm -f "$COOKIE"
BASE="http://localhost:16601"

# Try creating a NEW password by sending a register-like payload
for BODY in \
    '{"Account":"666","Password":"666","ConfirmPassword":"666"}' \
    '{"Account":"admin","Password":"admin123","ConfirmPassword":"admin123"}' \
    '{"Account":"666","Password":"666666","ConfirmPassword":"666666"}' \
    '{"NewAccount":"666","NewPassword":"666"}' \
    '{"account":"admin","password":"admin123","type":"register"}' \
    '{"Account":"666","Password":"666","IsFirst":true}'; do
    echo "body=$BODY"
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        --max-time 3 "${BASE}/api/login" 2>&1
    echo ""
    "$CURL" -s --noproxy '*' -X POST -H 'Content-Type: application/json' \
        -d "$BODY" \
        -c "$COOKIE" \
        --max-time 3 "${BASE}/api/register" 2>&1
    echo ""
done
