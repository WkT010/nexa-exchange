#!/usr/bin/env bash
# Alternative approach: use node or python to directly call javascript JSEncrypt,
# but actually let's just use a different simpler tool for this.
#
# Since browser is not available (Chrome not installed), and we can't reverse the password,
# Let's just install nginx or Caddy as reverse proxy directly instead.
#
# Check what's available
which nginx caddy haproxy envoy traefik 2>/dev/null
dpkg -l 2>/dev/null | grep -iE 'nginx|caddy|haproxy|traefik' | head -5
echo "---"
apt list --installed 2>/dev/null | grep -iE 'nginx|caddy' | head -5
echo "---"
# Check if we can use Go (there's a go.mod already!)
which go
go version 2>/dev/null
