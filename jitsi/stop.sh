#!/bin/bash
# 停止 Jitsi 本地服务

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "停止 Jitsi 本地服务..."
docker compose down
echo "✅ 已停止"
