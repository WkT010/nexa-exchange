#!/usr/bin/env bash
# Kill any existing chrome
pkill -9 -f chrome 2>/dev/null; sleep 1

# Start chrome with debugging port
nohup google-chrome \
    --no-sandbox \
    --headless=new \
    --disable-gpu \
    --disable-software-rasterizer \
    --remote-debugging-port=9222 \
    --remote-debugging-address=127.0.0.1 \
    --user-data-dir=/tmp/chrome-profile \
    > /tmp/chrome.log 2>&1 &
echo "Chrome PID=$!"
sleep 5
curl -s --noproxy '*' http://127.0.0.1:9222/json/version 2>&1 | head -20