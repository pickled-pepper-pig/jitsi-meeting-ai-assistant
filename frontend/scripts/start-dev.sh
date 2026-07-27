#!/bin/bash
# 前端开发环境启动脚本
# 使用方法：npm run dev

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=========================================="
echo "  Meeting AI Frontend 开发环境启动"
echo "=========================================="
echo ""

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

# 检查证书是否需要更新
CERT_FILE="localhost+3.pem"
if [ -f "$CERT_FILE" ]; then
    CERT_IPS=$(openssl x509 -in "$CERT_FILE" -text -noout 2>/dev/null | grep -o 'IP Address:[0-9.]*' | awk '{print $2}')
    
    if ! echo "$CERT_IPS" | grep -q "$CURRENT_IP"; then
        echo "🔄 证书不包含当前 IP，重新生成..."
        mkcert localhost 127.0.0.1 "$CURRENT_IP" ::1 > /dev/null 2>&1
        echo "✅ 证书已更新"
        echo ""
    else
        echo "✅ 证书已包含当前 IP"
        echo ""
    fi
else
    echo "📜 首次启动，生成开发证书..."
    mkcert localhost 127.0.0.1 "$CURRENT_IP" ::1 > /dev/null 2>&1
    echo "✅ 证书已生成"
    echo ""
fi

echo "🚀 启动 Vite 开发服务器..."
exec vite