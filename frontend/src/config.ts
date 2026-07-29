// 环境配置
// 开发阶段通过 Vite 代理转发：
//   HTTP API (/api, /health) → Flask (127.0.0.1:8082)
//   WebSocket (/ws) → WebSocket 服务 (127.0.0.1:8080)

const JITSI_PORT = '8443';
const BACKEND_PORT = '8080';

function getJitsiHost(): string {
  if (typeof window === 'undefined') return 'localhost';
  const hostname = window.location.hostname;
  if (hostname === 'localhost' || hostname === '127.0.0.1') return 'localhost';
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

function getBackendBaseUrl(): string {
  if (typeof window === 'undefined') return 'http://localhost:8082';
  return ''; // Vite 代理
}

function getBackendWsUrl(): string {
  // 开发环境通过 Vite 代理 /ws 连接后端 WebSocket（避免 WSS/WS 协议不匹配）
  if (import.meta.env.DEV) {
    return `wss://${window.location.host}/ws`;
  }
  // 生产环境直接连接后端 WebSocket 服务（WSS）
  const hostname = getJitsiHost();
  return `wss://${hostname}:${BACKEND_PORT}`;
}

export const API_CONFIG = {
  baseUrl: getBackendBaseUrl(),
  wsUrl: getBackendWsUrl(),
  backendPort: BACKEND_PORT,
};
