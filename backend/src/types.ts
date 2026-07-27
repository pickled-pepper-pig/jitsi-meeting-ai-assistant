// 后端类型定义

/** 聊天消息类型 */
export interface ChatMessage {
  id: string;
  seq: number;
  roomId: string;
  sender: string;
  content: string;
  timestamp: number;
  type: 'text' | 'system' | 'summary';
}

/** WebSocket 客户端消息 */
export type ClientMessage =
  | { action: 'join'; roomId: string; token: string }
  | { action: 'leave'; roomId: string }
  | { action: 'chat'; roomId: string; token: string; content: string; sender: string }
  | { action: 'summarize'; roomId: string; token: string }
  | { action: 'sync'; roomId: string; lastSeq: number };

/** WebSocket 服务端消息 */
export type ServerMessage =
  | { type: 'joined'; roomId: string; lastSeq: number }
  | { type: 'chat'; payload: ChatMessage }
  | { type: 'summary'; roomId: string; summary: string; timestamp: number }
  | { type: 'error'; message: string }
  | { type: 'synced'; messages: ChatMessage[] };

/** 会议状态 */
export interface MeetingState {
  roomId: string;
  seq: number;
  messages: ChatMessage[];
  startedAt: number;
  endedAt: boolean;
}

/** Jitsi JWT Payload */
export interface JwtPayload {
  iss: string;
  sub: string;
  aud: 'jitsi';
  room: string;
  userId: string;
  role: 'moderator' | 'participant';
  context?: {
    user?: {
      name?: string;
      email?: string;
    };
    group?: string;
  };
  iat?: number;
  exp?: number;
}