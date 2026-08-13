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

# 兼容 macOS 与 Linux：
#   macOS 用 ipconfig；Linux 用 hostname -I（需 iproute2）
get_local_ip() {
    local ip=""
    if command -v ipconfig >/dev/null 2>&1; then
        for iface in en0 en1; do
            ip=$(ipconfig getifaddr "$iface" 2>/dev/null)
            if [ -n "$ip" ] && [[ "$ip" != "127."* ]]; then
                echo "$ip"
                return 0
            fi
        done
    fi
    if command -v hostname >/dev/null 2>&1; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
        if [ -n "$ip" ] && [[ "$ip" != "127."* ]]; then
            echo "$ip"
            return 0
        fi
    fi
    echo "127.0.0.1"
}

CURRENT_IP=$(get_local_ip)
echo "📍 当前局域网 IP: $CURRENT_IP"

# 可选域名（供服务器通过 FRONTEND_DOMAIN=dify.silan.com 注入，证书同时包含域名）
CERT_DOMAIN="${FRONTEND_DOMAIN:-}"
if [ -n "$CERT_DOMAIN" ]; then
    echo "📍 证书额外包含域名: $CERT_DOMAIN"
fi
echo ""

# 检查证书是否需要更新/重新生成
CERT_FILE="localhost+3.pem"
REGEN=0
if [ ! -f "$CERT_FILE" ]; then
    echo "📜 首次启动，生成开发证书..."
    REGEN=1
else
    CERT_IPS=$(openssl x509 -in "$CERT_FILE" -text -noout 2>/dev/null | grep -o 'IP Address:[0-9.]*' | awk '{print $2}')
    if ! echo "$CERT_IPS" | grep -q "$CURRENT_IP"; then
        REGEN=1
    fi
    if [ -n "$CERT_DOMAIN" ]; then
        CERT_DNS=$(openssl x509 -in "$CERT_FILE" -text -noout 2>/dev/null | grep -o 'DNS:[a-zA-Z0-9._-]*')
        if ! echo "$CERT_DNS" | grep -q "DNS:${CERT_DOMAIN}"; then
            REGEN=1
        fi
    fi
fi

if [ "$REGEN" = "1" ]; then
    echo "🔄 证书不完整，重新生成..."
    # shellcheck disable=SC2086
    mkcert localhost 127.0.0.1 "$CURRENT_IP" $CERT_DOMAIN ::1 > /dev/null 2>&1
    echo "✅ 证书已重新生成"
    echo ""
else
    echo "✅ 证书已包含当前 IP 与域名"
    echo ""
fi

echo "🚀 启动 Vite 开发服务器..."
exec vite