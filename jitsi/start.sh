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

# 获取当前局域网 IP
get_local_ip() {
    local ip=""
    for iface in en0 en1; do
        ip=$(ipconfig getifaddr "$iface" 2>/dev/null)
        if [ -n "$ip" ] && [[ "$ip" != "127."* ]]; then
            echo "$ip"
            return 0
        fi
    done
    echo "127.0.0.1"
}

CURRENT_IP=$(get_local_ip)
echo "📍 当前局域网 IP: $CURRENT_IP"
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

# 检查并更新配置
if [ -f .env ]; then
    OLD_IP=$(grep '^LOCAL_IP=' .env | cut -d'=' -f2)
    
    if [ "$CURRENT_IP" != "$OLD_IP" ]; then
        echo "🔄 IP 地址已变化：$OLD_IP → $CURRENT_IP"
        echo "📝 更新 .env 中的 LOCAL_IP..."
        
        sed -i '' "s|^LOCAL_IP=.*|LOCAL_IP=$CURRENT_IP|" .env
        
        echo "📜 重新生成 Jitsi 证书（8447）..."
        mkdir -p certs
        mkcert -cert-file certs/jitsi.crt -key-file certs/jitsi.key localhost 127.0.0.1 "$CURRENT_IP" ::1 > /dev/null 2>&1
        
        echo "📜 重新生成前端 Vite 证书（3007）..."
        FRONTEND_DIR="$SCRIPT_DIR/../frontend"
        if [ -d "$FRONTEND_DIR" ]; then
            mkcert -cert-file "$FRONTEND_DIR/localhost+3.pem" -key-file "$FRONTEND_DIR/localhost+3-key.pem" localhost 127.0.0.1 "$CURRENT_IP" ::1 > /dev/null 2>&1
        fi
        
        echo "🔄 重启 Jitsi 容器以加载新证书..."
        docker compose restart web prosody jicofo jvb > /dev/null 2>&1
        sleep 5
        
        echo "✅ 配置已更新"
        echo ""
    else
        echo "✅ IP 地址未变化"
        echo ""
    fi
else
    echo "⚠️  未找到 .env 文件，请先创建"
    echo ""
fi

# 启动 Jitsi 服务
echo "🚀 启动 Jitsi 服务..."
echo "   - Web:  http://localhost:8007"
echo "   - HTTPS: https://localhost:8447 (自签名证书，浏览器会警告)"
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
echo "    - HTTP:  http://localhost:8007"
echo "    - HTTPS: https://localhost:8447"
echo "    - 局域网: https://$CURRENT_IP:8447"
echo ""
echo "  注意事项："
echo "    1. HTTPS 是自签名证书，浏览器会提示不安全，点击'继续访问'即可"
echo "    2. 停止服务：./stop.sh 或 docker compose down"
echo "    3. 查看日志：docker compose logs -f"
echo ""
echo "  切换前端到本地 Jitsi："
echo "    编辑 frontend/src/config.ts，将 CURRENT_JITSI 改为 'local'"
echo ""