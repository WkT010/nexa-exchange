#!/usr/bin/env bash
# Look for encryption key in localStorage or the request wrapper.
# Lucky encrypts passwords using RSA with public key, obtained from login flow.
# Let's check lucky_Login* imports.
set -uo pipefail
grep -oE '"[A-Za-z0-9/_-]{30,}"' /tmp/lucky_index.js | grep -iE 'key|encrypt|rsa|aes|pub|priv' | sort -u | head -20
echo "---"
# Also search for actual encrypt function calls
grep -oE '[a-zA-Z_$][a-zA-Z0-9_$]*\.encrypt\([^)]{0,80}\)' /tmp/lucky_index.js | sort -u | head -20
echo "---"
# Search for patterns of base64 encoded public keys (starts with MII...)
grep -oE 'MIIB[A-Za-z0-9+/=]{80,}' /tmp/lucky_index.js | sort -u | head -5
echo "---"
# Or patterns like -----BEGIN PUBLIC KEY-----
grep -oE 'BEGIN PUBLIC KEY[A-Za-z0-9+/=\s-]{40,}' /tmp/lucky_index.js | head -2
