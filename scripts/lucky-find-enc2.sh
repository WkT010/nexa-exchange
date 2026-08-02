#!/usr/bin/env bash
# Let's find the encryption logic differently: look for Password being transformed
# Right before login, password is encrypted. Search for Password assignment
set -uo pipefail
grep -oE 'Password[^:]{0,10}:[^,)]{0,200}' /tmp/lucky_index.js | grep -iv 'placeholder\|label\|text\|model\|loginPage\|Remember' | sort -u | head -15
echo "---"
# Search for string with "encrypt" in context
grep -oE '[^,;{}]{0,60}encrypt[^,;{}]{0,100}' /tmp/lucky_index.js | sort -u | head -20
