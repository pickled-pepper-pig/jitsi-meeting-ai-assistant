// 前端类型定义

export interface ChatMessage {
  id: string;
  seq: number;
  roomId: string;
  sender: string;
  content: string;
  timestamp: number;
  type: 'text' | 'system' | 'summary' | 'transcript';
}

/**
 * Socket.IO 服务端事件（Python Flask-SocketIO 发出）
 * 对应 silan-asr-service/app/meeting_ws/__init__.py
 */
export type ServerEvent =
  | { type: 'meeting_joined'; roomId: string; lastSeq: number }
  | { type: 'meeting_chat'; payload: ChatMessage }
  | { type: 'meeting_summary'; roomId: string; summary: string; timestamp: number }
  | { type: 'meeting_error'; message: string }
  | { type: 'meeting_synced'; messages: ChatMessage[] }
  | { type: 'meeting_status'; message: string };

/**
 * 统一消息格式，供前端组件使用（兼容旧逻辑）
 */
export type ServerMessage =
  | { type: 'joined'; roomId: string; lastSeq: number }
  | { type: 'chat'; payload: ChatMessage }
  | { type: 'summary'; roomId: string; summary: string; timestamp: number }
  | { type: 'error'; message: string }
  | { type: 'synced'; messages: ChatMessage[] }
  // 房间级 AI Bot 状态：主持人开启/关闭时全房间广播
  | { type: 'ai_bot_status'; roomId: string; status: 'idle' | 'starting' | 'started' | 'stopping'; aiEnabled: boolean; startedBy: string | null }
  // 主持人产生的 final 转写：旁观者同步接收
  | { type: 'meeting_transcript'; text: string; participant_id?: string; participant_name?: string; timestamp: number; meeting_id?: string; session_id?: string }
  // 主持人产生的 partial 转写：旁观者实时显示
  | { type: 'meeting_transcript_partial'; text: string; participant_id?: string; participant_name?: string; timestamp: number; meeting_id?: string; session_id?: string; is_processing?: boolean };

/** 连接状态 */
export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

/** Jitsi IFrame API 声明 */
declare global {
  interface Window {
    JitsiMeetExternalAPI: any;
  }
}
