// 后端类型定义

/** 聊天消息类型 */
export interface ChatMessage {
  id: string;           // 服务端生成的唯一消息ID，用于去重
  seq: number;          // 会议内自增序号，用于补齐空洞
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
  | { action: 'sync'; roomId: string; lastSeq: number }; // 断线重连后补齐

/** WebSocket 服务端消息 */
export type ServerMessage =
  | { type: 'joined'; roomId: string; lastSeq: number }
  | { type: 'chat'; payload: ChatMessage }
  | { type: 'summary'; roomId: string; summary: string; timestamp: number }
  | { type: 'error'; message: string }
  | { type: 'synced'; messages: ChatMessage[] }; // 返回断线期间错过的消息

/** 会议状态 */
export interface MeetingState {
  roomId: string;
  seq: number;
  messages: ChatMessage[];
  startedAt: number;
  endedAt: boolean;
}

/** JWT payload */
export interface JwtPayload {
  userId: string;
  roomId: string;
  role: 'moderator' | 'participant';
  iat?: number;
  exp?: number;
}
