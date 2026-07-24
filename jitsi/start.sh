#!/bin/bash
# Jitsi 本地开发环境启动脚本
# 使用方法：./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  Jitsi 本地开发环境启动"
echo "=========================================="
echo ""

# 创建数据目录
mkdir -p jitsi-meet-cfg/{web/custom,web/letsencrypt,prosody/config,jicofo,jvb,transcripts}

# 检查 Docker 是否运行
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker 未运行，请先启动 Docker"
    exit 1
fi

echo "✅ Docker 正在运行"
echo ""

# 启动 Jitsi 服务
echo "🚀 启动 Jitsi 服务..."
echo "   - Web:  http://localhost:8000"
echo "   - HTTPS: https://localhost:8443 (自签名证书，浏览器会警告)"
echo ""
echo "   ⚠️  首次启动需要下载镜像，可能需要几分钟..."
echo ""

docker compose up -d

echo ""
echo "⏳ 等待服务启动..."
sleep 10

# 检查服务状态
echo ""
echo "📊 服务状态："
docker compose ps

echo ""
echo "=========================================="
echo "  Jitsi 本地服务已启动"
echo "=========================================="
echo ""
echo "  访问地址："
echo "    - HTTP:  http://localhost:8000"
echo "    - HTTPS: https://localhost:8443"
echo ""
echo "  注意事项："
echo "    1. HTTPS 是自签名证书，浏览器会提示不安全，点击'继续访问'即可"
echo "    2. 停止服务：./stop.sh 或 docker compose down"
echo "    3. 查看日志：docker compose logs -f"
echo ""
echo "  切换前端到本地 Jitsi："
echo "    编辑 frontend/src/config.ts，将 CURRENT_JITSI 改为 'local'"
echo ""
