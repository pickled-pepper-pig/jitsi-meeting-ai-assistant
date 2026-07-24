// WebSocket Hook - 带指数退避重连和断线消息同步

import { useRef, useEffect, useState, useCallback } from 'react';
import { ServerMessage, ClientMessage, ConnectionStatus } from '../types';

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]; // 指数退避
const MAX_RECONNECT_ATTEMPTS = 6;

interface WebSocketOptions {
  url: string;
  onMessage: (message: ServerMessage) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
}

export function useWebSocket(options: WebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSeqRef = useRef(0);
  const roomIdRef = useRef<string>('');
  const tokenRef = useRef<string>('');
  const isManualCloseRef = useRef(false);

  const [status, setStatus] = useState<ConnectionStatus>('disconnected');

  const { onMessage, onStatusChange } = options;
  const onMessageRef = useRef(onMessage);
  const onStatusChangeRef = useRef(onStatusChange);
  onMessageRef.current = onMessage;
  onStatusChangeRef.current = onStatusChange;

  const updateStatus = useCallback((newStatus: ConnectionStatus) => {
    setStatus(newStatus);
    onStatusChangeRef.current?.(newStatus);
  }, []);

  const connect = useCallback((roomId: string, token: string) => {
    roomIdRef.current = roomId;
    tokenRef.current = token;
    isManualCloseRef.current = false;

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.close();
    }

    updateStatus('connecting');
    console.log('[WS] 正在连接:', options.url);
    const ws = new WebSocket(options.url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WS] 连接已建立');
      reconnectAttemptsRef.current = 0;
      updateStatus('connected');

      // 发送 join 消息
      const joinMsg: ClientMessage = { action: 'join', roomId, token };
      ws.send(JSON.stringify(joinMsg));
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data) as ServerMessage;

        // 更新 lastSeq
        if (message.type === 'chat' && message.payload.seq > lastSeqRef.current) {
          lastSeqRef.current = message.payload.seq;
        }
        if (message.type === 'joined') {
          lastSeqRef.current = message.lastSeq;
        }

        onMessageRef.current(message);
      } catch (err) {
        console.error('[WS] 消息解析失败:', err);
      }
    };

    ws.onclose = (event: CloseEvent) => {
      console.log('[WS] 连接已关闭:', event.code, event.reason);
      if (!isManualCloseRef.current) {
        scheduleReconnect();
      } else {
        updateStatus('disconnected');
      }
    };

    ws.onerror = (err) => {
      console.error('[WS] 连接错误:', err, 'URL:', options.url);
    };
  }, [options.url, updateStatus]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      console.error('[WS] 达到最大重连次数，停止重连');
      updateStatus('disconnected');
      return;
    }

    const delay = RECONNECT_DELAYS[reconnectAttemptsRef.current] || 30000;
    reconnectAttemptsRef.current += 1;
    updateStatus('reconnecting');

    console.log(`[WS] ${delay}ms 后第 ${reconnectAttemptsRef.current} 次重连...`);

    reconnectTimerRef.current = setTimeout(() => {
      // 重连成功后，先 sync 补齐错过的消息
      const ws = new WebSocket(options.url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WS] 重连成功');
        reconnectAttemptsRef.current = 0;
        updateStatus('connected');

        // 先重新 join（设置 session.roomId），再 sync 补齐错过的消息
        const joinMsg: ClientMessage = {
          action: 'join',
          roomId: roomIdRef.current,
          token: tokenRef.current,
        };
        ws.send(JSON.stringify(joinMsg));

        // join 后发送 sync 请求，补齐断线期间的消息
        const syncMsg: ClientMessage = {
          action: 'sync',
          roomId: roomIdRef.current,
          lastSeq: lastSeqRef.current,
        };
        ws.send(JSON.stringify(syncMsg));
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const message = JSON.parse(event.data) as ServerMessage;
          if (message.type === 'chat' && message.payload.seq > lastSeqRef.current) {
            lastSeqRef.current = message.payload.seq;
          }
          onMessageRef.current(message);
        } catch (err) {
          console.error('[WS] 消息解析失败:', err);
        }
      };

      ws.onclose = () => {
        if (!isManualCloseRef.current) {
          scheduleReconnect();
        }
      };

      ws.onerror = () => {
        console.error('[WS] 重连失败');
      };
    }, delay);
  }, [options.url, updateStatus]);

  const send = useCallback((message: ClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
      return true;
    }
    console.warn('[WS] 连接未就绪，消息未发送');
    return false;
  }, []);

  const disconnect = useCallback(() => {
    isManualCloseRef.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    reconnectAttemptsRef.current = 0;
    updateStatus('disconnected');
  }, [updateStatus]);

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return { connect, disconnect, send, status, lastSeq: lastSeqRef };
}
