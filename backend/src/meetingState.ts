// 会议状态管理 - 按 roomId 维度管理

import { MeetingState, ChatMessage } from './types';

const meetings = new Map<string, MeetingState>();

/** 获取或创建会议状态 */
export function getOrCreateMeeting(roomId: string): MeetingState {
  if (!meetings.has(roomId)) {
    meetings.set(roomId, {
      roomId,
      seq: 0,
      messages: [],
      startedAt: Date.now(),
      endedAt: false,
    });
  }
  return meetings.get(roomId)!;
}

/** 添加消息，返回带 seq 的新消息 */
export function addMessage(roomId: string, message: Omit<ChatMessage, 'id' | 'seq' | 'roomId'>): ChatMessage {
  const meeting = getOrCreateMeeting(roomId);
  meeting.seq += 1;
  const fullMessage: ChatMessage = {
    ...message,
    id: `${roomId}-${meeting.seq}-${Date.now()}`,
    seq: meeting.seq,
    roomId,
  };
  meeting.messages.push(fullMessage);
  return fullMessage;
}

/** 获取断线期间错过的消息（seq > lastSeq） */
export function getMessagesAfterSeq(roomId: string, lastSeq: number): ChatMessage[] {
  const meeting = meetings.get(roomId);
  if (!meeting) return [];
  return meeting.messages.filter((m) => m.seq > lastSeq);
}

/** 获取会议所有消息 */
export function getAllMessages(roomId: string): ChatMessage[] {
  const meeting = meetings.get(roomId);
  if (!meeting) return [];
  return [...meeting.messages];
}

/** 标记会议结束 */
export function endMeeting(roomId: string): void {
  const meeting = meetings.get(roomId);
  if (meeting) {
    meeting.endedAt = true;
  }
}
