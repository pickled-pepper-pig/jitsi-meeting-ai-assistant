// 前端类型定义

export interface ChatMessage {
  id: string;
  seq: number;
  roomId: string;
  sender: string;
  content: string;
  timestamp: number;
  type: 'text' | 'system' | 'summary';
}

/** WebSocket 服务端消息 */
export type ServerMessage =
  | { type: 'joined'; roomId: string; lastSeq: number }
  | { type: 'chat'; payload: ChatMessage }
  | { type: 'summary'; roomId: string; summary: string; timestamp: number }
  | { type: 'error'; message: string }
  | { type: 'synced'; messages: ChatMessage[] };

/** WebSocket 客户端消息 */
export type ClientMessage =
  | { action: 'join'; roomId: string; token: string }
  | { action: 'leave'; roomId: string }
  | { action: 'chat'; roomId: string; token: string; content: string; sender: string }
  | { action: 'summarize'; roomId: string; token: string }
  | { action: 'sync'; roomId: string; lastSeq: number };

/** 连接状态 */
export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

/** Jitsi IFrame API 声明 */
declare global {
  interface Window {
    JitsiMeetExternalAPI: any;
  }
}
