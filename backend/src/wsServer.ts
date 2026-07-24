// WebSocket 服务器 - 处理实时消息广播

import { WebSocketServer, WebSocket } from 'ws';
import { ClientMessage, ServerMessage, ChatMessage } from './types';
import { addMessage, getMessagesAfterSeq, getAllMessages, getOrCreateMeeting } from './meetingState';
import { verifyToken, isModerator } from './auth';
import { auditLog } from './auditLog';
import { generateSummary } from './mockLLM';

/** 每个 WebSocket 连接绑定的房间和用户信息 */
interface ClientSession {
  ws: WebSocket;
  roomId?: string;
  userId?: string;
}

const sessions = new Map<WebSocket, ClientSession>();

/** 按 roomId 分组，方便广播 */
const roomClients = new Map<string, Set<WebSocket>>();

export function initWebSocketServer(server: any): void {
  const wss = new WebSocketServer({ server, path: '/ws' });

  wss.on('connection', (ws: WebSocket) => {
    console.log('[WS] 新连接已建立');
    sessions.set(ws, { ws });

    ws.on('message', async (data: Buffer) => {
      try {
        const message = JSON.parse(data.toString()) as ClientMessage;
        await handleMessage(ws, message);
      } catch (err) {
        console.error('[WS] 消息解析失败:', err);
        sendToClient(ws, { type: 'error', message: '消息格式错误' });
      }
    });

    ws.on('close', () => {
      const session = sessions.get(ws);
      if (session?.roomId) {
        const clients = roomClients.get(session.roomId);
        if (clients) {
          clients.delete(ws);
          if (clients.size === 0) {
            roomClients.delete(session.roomId);
          }
        }
        console.log(`[WS] 用户 ${session.userId} 离开房间 ${session.roomId}`);
      }
      sessions.delete(ws);
    });

    ws.on('error', (err: Error) => {
      console.error('[WS] 连接错误:', err);
    });
  });

  console.log('[WS] WebSocket 服务器已启动，路径: /ws');
}

async function handleMessage(ws: WebSocket, message: ClientMessage): Promise<void> {
  const session = sessions.get(ws);
  if (!session) return;

  switch (message.action) {
    case 'join': {
      const payload = verifyToken(message.token);
      if (!payload) {
        sendToClient(ws, { type: 'error', message: 'Token 无效' });
        return;
      }
      session.roomId = message.roomId;
      session.userId = payload.userId;

      // 加入房间
      if (!roomClients.has(message.roomId)) {
        roomClients.set(message.roomId, new Set());
      }
      roomClients.get(message.roomId)!.add(ws);

      const meeting = getOrCreateMeeting(message.roomId);
      sendToClient(ws, { type: 'joined', roomId: message.roomId, lastSeq: meeting.seq });

      auditLog('join', payload.userId, message.roomId, `role=${payload.role}`);
      console.log(`[WS] 用户 ${payload.userId} 加入房间 ${message.roomId}（角色: ${payload.role}）`);
      break;
    }

    case 'leave': {
      if (session.roomId) {
        const clients = roomClients.get(session.roomId);
        clients?.delete(ws);
        auditLog('leave', session.userId || 'unknown', session.roomId);
      }
      break;
    }

    case 'chat': {
      if (!session.roomId) {
        sendToClient(ws, { type: 'error', message: '未加入会议' });
        return;
      }
      // Phase 1: 允许所有已认证用户发送聊天
      const payload = verifyToken(message.token);
      if (!payload) {
        sendToClient(ws, { type: 'error', message: 'Token 无效' });
        return;
      }

      const chatMessage = addMessage(session.roomId, {
        sender: message.sender,
        content: message.content,
        timestamp: Date.now(),
        type: 'text',
      });

      broadcastToRoom(session.roomId, { type: 'chat', payload: chatMessage });
      console.log(`[CHAT] [${session.roomId}] ${message.sender}: ${message.content.substring(0, 50)}`);
      break;
    }

    case 'summarize': {
      if (!session.roomId) {
        sendToClient(ws, { type: 'error', message: '未加入会议' });
        return;
      }

      // 只有主持人可以触发总结
      if (!isModerator(message.token)) {
        sendToClient(ws, { type: 'error', message: '只有主持人可以生成会议总结' });
        auditLog('summarize_denied', 'unknown', session.roomId, '非主持人尝试总结');
        return;
      }

      const payload = verifyToken(message.token);
      auditLog('summarize_start', payload!.userId, session.roomId);

      const messages = getAllMessages(session.roomId);
      sendToClient(ws, { type: 'error', message: '正在生成会议总结...' });

      const summary = await generateSummary(session.roomId, messages);
      const summaryMessage: ChatMessage = addMessage(session.roomId, {
        sender: 'AI 助手',
        content: summary,
        timestamp: Date.now(),
        type: 'summary',
      });

      broadcastToRoom(session.roomId, { type: 'summary', roomId: session.roomId, summary, timestamp: Date.now() });
      broadcastToRoom(session.roomId, { type: 'chat', payload: summaryMessage });

      auditLog('summarize_done', payload!.userId, session.roomId);
      break;
    }

    case 'sync': {
      // 断线重连后，补齐错过的消息
      if (!session.roomId) {
        sendToClient(ws, { type: 'error', message: '未加入会议' });
        return;
      }
      const missedMessages = getMessagesAfterSeq(session.roomId, message.lastSeq);
      sendToClient(ws, { type: 'synced', messages: missedMessages });
      console.log(`[SYNC] 房间 ${session.roomId} 补齐 ${missedMessages.length} 条消息（lastSeq=${message.lastSeq}）`);
      break;
    }
  }
}

/** 广播消息到房间内所有客户端 */
function broadcastToRoom(roomId: string, message: ServerMessage): void {
  const clients = roomClients.get(roomId);
  if (!clients) return;
  const data = JSON.stringify(message);
  clients.forEach((ws) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  });
}

/** 发送消息给单个客户端 */
function sendToClient(ws: WebSocket, message: ServerMessage): void {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
  }
}
