// 原生 WebSocket Hook - 连接后端 WebSocket 服务
// 自动重连 + 断线消息同步

import { useRef, useEffect, useState, useCallback } from 'react';
import { ServerMessage, ConnectionStatus, ChatMessage } from '../types';

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000];
const MAX_RECONNECT_ATTEMPTS = 6;

interface UseWebSocketOptions {
  url: string;
  onMessage: (message: ServerMessage) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
}

export function useWebSocket(options: UseWebSocketOptions) {
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

  /**
   * 将服务端 JSON 消息转换为统一的 ServerMessage 格式
   */
  const handleMessage = useCallback((raw: string) => {
    let data: any;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }

    let message: ServerMessage | null = null;

    switch (data.type) {
      case 'joined':
        message = { type: 'joined', roomId: data.roomId, lastSeq: data.lastSeq };
        lastSeqRef.current = data.lastSeq;
        break;

      case 'chat':
        if (data.payload?.seq > lastSeqRef.current) {
          lastSeqRef.current = data.payload.seq;
        }
        message = { type: 'chat', payload: data.payload };
        break;

      case 'summary':
        message = { type: 'summary', roomId: data.roomId, summary: data.summary, timestamp: data.timestamp };
        break;

      case 'synced': {
        const msgs = data.messages as ChatMessage[];
        if (msgs.length > 0) {
          const maxSeq = Math.max(...msgs.map(m => m.seq));
          if (maxSeq > lastSeqRef.current) lastSeqRef.current = maxSeq;
        }
        message = { type: 'synced', messages: msgs };
        break;
      }

      // 新用户加入时服务端一次性补发的房间历史快照（含 chat / summary 等所有消息）
      case 'room_state_snapshot': {
        const msgs = (data.messages as ChatMessage[]) || [];
        if (msgs.length > 0) {
          const maxSeq = Math.max(...msgs.map(m => m.seq));
          if (maxSeq > lastSeqRef.current) lastSeqRef.current = maxSeq;
        }
        message = { type: 'synced', messages: msgs };
        break;
      }

      case 'error':
      case 'status':
        message = { type: 'error', message: data.message };
        break;

      // 房间级 AI Bot 状态：旁观者通过此消息知道自己能不能控制 AI
      case 'ai_bot_status':
        message = {
          type: 'ai_bot_status',
          roomId: data.roomId,
          status: data.status,
          aiEnabled: !!data.aiEnabled,
          startedBy: data.startedBy ?? null,
        };
        break;

      // 旁观者收到操作者产生的 final 转写（后端 ws_server 广播）
      // 转为统一 meeting_transcript 消息给 App.tsx
      case 'transcript_final':
        message = {
          type: 'meeting_transcript',
          text: data.text || '',
          participant_id: data.participant_id,
          participant_name: data.participant_name,
          timestamp: data.timestamp,
          meeting_id: data.meeting_id,
          session_id: data.session_id,
        };
        break;

      // 旁观者收到操作者产生的 partial 转写（实时显示）
      case 'transcript_partial':
        message = {
          type: 'meeting_transcript_partial',
          text: data.text || '',
          participant_id: data.participant_id,
          participant_name: data.participant_name,
          timestamp: data.timestamp,
          meeting_id: data.meeting_id,
          session_id: data.session_id,
          is_processing: data.is_processing,
        };
        break;

      // 这些是 AudioCaptureService 自己处理的消息，旁观者连接不应该收到
      case 'transcript':
      case 'session_created':
      case 'audio_received':
      case 'session_finalized':
        break;
    }

    if (message) {
      onMessageRef.current(message);
    }
  }, []);

  const doConnect = useCallback((roomId?: string, token?: string) => {
    const wsUrl = options.url.replace(/^http/, 'ws');
    updateStatus('connecting');
    console.log('[WS] 正在连接:', wsUrl);

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WS] 连接已建立');
      reconnectAttemptsRef.current = 0;
      updateStatus('connected');

      // 如果有 roomId/token，自动 join
      if (roomId && token) {
        ws.send(JSON.stringify({ action: 'join', roomId, token }));
      }
    };

    ws.onmessage = (event) => {
      handleMessage(event.data);
    };

    ws.onclose = () => {
      console.log('[WS] 连接已关闭');
      if (!isManualCloseRef.current) {
        scheduleReconnect();
      } else {
        updateStatus('disconnected');
      }
    };

    ws.onerror = () => {
      console.error('[WS] 连接错误');
    };
  }, [options.url, updateStatus, handleMessage]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      updateStatus('disconnected');
      return;
    }
    const delay = RECONNECT_DELAYS[reconnectAttemptsRef.current] || 30000;
    reconnectAttemptsRef.current += 1;
    updateStatus('reconnecting');
    console.log(`[WS] ${delay}ms 后第 ${reconnectAttemptsRef.current} 次重连...`);

    reconnectTimerRef.current = setTimeout(() => {
      doConnect(roomIdRef.current, tokenRef.current);
      // 重连后 sync
      if (roomIdRef.current) {
        setTimeout(() => {
          const ws = wsRef.current;
          if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'sync', lastSeq: lastSeqRef.current }));
          }
        }, 500);
      }
    }, delay);
  }, [doConnect, updateStatus]);

  const connect = useCallback((roomId: string, token: string) => {
    roomIdRef.current = roomId;
    tokenRef.current = token;
    // 先标记手动关闭，避免旧 WS 的 onclose 触发重连
    isManualCloseRef.current = true;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    // 重置重连计数
    reconnectAttemptsRef.current = 0;
    // 下一轮再放开手动关闭标记，让新连接的 onclose 能正常触发重连
    isManualCloseRef.current = false;
    doConnect(roomId, token);
  }, [doConnect]);

  const send = useCallback((message: { action: string; [key: string]: any }) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] 连接未就绪');
      return false;
    }
    ws.send(JSON.stringify(message));
    return true;
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
    return () => disconnect();
  }, [disconnect]);

  return { connect, disconnect, send, status, lastSeq: lastSeqRef };
}
