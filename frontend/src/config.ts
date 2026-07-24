// 环境配置
// 开发阶段可通过修改 CURRENT_JITSI 切换 Jitsi 服务

const JITSI_PORT = '8443';

function getJitsiHost(): string {
  if (typeof window === 'undefined') return 'localhost';
  const hostname = window.location.hostname;
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'localhost';
  }
  return hostname;
}

export function getJitsiDomain(): string {
  return `${getJitsiHost()}:${JITSI_PORT}`;
}

export function getJitsiProtocol(): 'http:' | 'https:' {
  return 'https:';
}

export function getJitsiBoshUrl(): string {
  return `https://${getJitsiHost()}:${JITSI_PORT}/http-bind`;
}

export function getJitsiWebsocketUrl(): string {
  return `wss://${getJitsiHost()}:${JITSI_PORT}/xmpp-websocket`;
}

export const CURRENT_JITSI = 'local' as 'public' | 'local';

export const API_CONFIG = {
  // 使用相对路径，通过 Vite 代理转发，避免浏览器需要信任后端证书
  baseUrl: typeof window !== 'undefined' ? '' : 'http://localhost:8080',
  wsUrl: typeof window !== 'undefined'
    ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
    : 'ws://localhost:8080/ws',
};
