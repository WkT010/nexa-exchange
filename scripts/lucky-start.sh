#!/usr/bin/env bash
# Lucky 二进制启动脚本
# 由于沙箱环境 Docker 受限（iptables/mount namespace 不可用），
# 改为直接使用 Lucky 官方二进制部署。
#
# 部署方式：
#   - 二进制路径: /opt/lucky/lucky
#   - 配置目录:   /goodluck (与 Docker 容器路径保持一致)
#   - Web 端口:   16601 (HTTP/HTTPS)
#   - 默认账号:   666 / 666 (首次登录后请立即修改)

set -uo pipefail

LUCKY_BIN="${LUCKY_BIN:-/opt/lucky/lucky}"
LUCKY_CONF="${LUCKY_CONF:-/goodluck/lucky.conf}"
LUCKY_LOG="${LUCKY_LOG:-/tmp/lucky.log}"
LUCKY_PID_FILE="${LUCKY_PID_FILE:-/tmp/lucky.pid}"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}

# 如果二进制不存在，自动下载
if [ ! -x "$LUCKY_BIN" ]; then
    log "[INFO] Lucky binary not found, downloading..."
    mkdir -p /opt/lucky /goodluck
    LUCKY_VERSION="2.15.10"
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64) ARCH="x86_64" ;;
        aarch64|arm64) ARCH="arm64" ;;
        *) log "[ERROR] unsupported arch: $ARCH"; exit 1 ;;
    esac
    URL="https://github.com/gdy666/lucky/releases/download/v${LUCKY_VERSION}/lucky_${LUCKY_VERSION}_Linux_${ARCH}.tar.gz"
    curl -L -o /tmp/lucky.tar.gz "$URL" || { log "[ERROR] download failed"; exit 1; }
    tar -xzf /tmp/lucky.tar.gz -C /opt/lucky
    chmod +x "$LUCKY_BIN"
    log "[OK] downloaded Lucky v${LUCKY_VERSION}"
fi

# 杀掉已有进程
if [ -f "$LUCKY_PID_FILE" ]; then
    old_pid=$(cat "$LUCKY_PID_FILE" 2>/dev/null || true)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        log "[INFO] killing previous Lucky (pid=$old_pid)"
        kill "$old_pid" 2>/dev/null || true
        sleep 1
    fi
fi
pkill -f "/opt/lucky/lucky" 2>/dev/null || true
sleep 1

# 启动 Lucky
log "[INFO] starting Lucky..."
cd /goodluck
setsid bash -c "$LUCKY_BIN -c $LUCKY_CONF > $LUCKY_LOG 2>&1" < /dev/null &
echo $! > "$LUCKY_PID_FILE"
sleep 4

# 验证
if curl -sf -o /dev/null --max-time 5 http://localhost:16601/ 2>/dev/null; then
    log "[OK] Lucky is running on http://localhost:16601"
    echo "============================================"
    echo "  Lucky 后台: http://localhost:16601"
    echo "  默认账号:   666 / 666"
    echo "  配置目录:   /goodluck"
    echo "  日志:       $LUCKY_LOG"
    echo "============================================"
else
    log "[ERROR] Lucky failed to start, check $LUCKY_LOG"
    tail -20 "$LUCKY_LOG"
    exit 1
fi
