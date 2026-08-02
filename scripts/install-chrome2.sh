#!/usr/bin/env bash
set -euo pipefail

# Download Chrome directly via proxy and install
export http_proxy=http://127.0.0.1:18080
export https_proxy=http://127.0.0.1:18080

cd /tmp
echo "[1] Downloading Chrome..."
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb 2>&1 | tail -5
echo "[2] Installing Chrome..."
apt-get install -y -qq /tmp/chrome.deb 2>&1 | tail -5 || dpkg -i /tmp/chrome.deb 2>&1; apt-get install -f -y -qq 2>&1 | tail -5
echo "[3] Checking..."
which google-chrome || which google-chrome-stable
google-chrome-stable --version 2>/dev/null || google-chrome --version 2>/dev/null
