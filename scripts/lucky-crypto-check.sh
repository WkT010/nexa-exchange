#!/usr/bin/env bash
# So /api/login is POST only (returns 404 for GET) while /api/status is GET only
# Login page uses R(o.value) where o.value = {Account,Password,TwoFA}. POST form/json.
# Since password 666 fails, maybe the default credential was updated in this build.
# Let's look at the Lucky source code patterns for default password.
# Lucky v2 uses encrypt (RSA/AES) on client for passwords. Look for JSEncrypt or CryptoJS usage.

# Check for encryption pattern in lucky modules
grep -oE '"(encrypt|decrypt|JSEncrypt|rsa|RSA|aes|AES|publickey|privateKey)[A-Za-z0-9_]*"' /tmp/lucky_index.js | sort -u | head -20

echo "---"
# Also search for the API login helper in index
# Look for Request()/fetch() wrapper that adds token
grep -oE 'login[^,]{0,30}' /tmp/lucky_index.js | sort -u | head -20