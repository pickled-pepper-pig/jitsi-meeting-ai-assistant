// 会议状态管理 - Phase 2 支持 Redis + 内存降级

import { MeetingState, ChatMessage } from './types';

const meetings = new Map<string, MeetingState>();

let redisClient: any = null;
let redisEnabled = false;

try {
  const { createClient } = require('redis');
  redisClient = createClient({
    url: process.env.REDIS_URL || 'redis://localhost:6379',
  });
  redisClient.on('error', (err: Error) => {
    console.warn('[Redis] 连接失败，降级到内存模式:', err);
    redisEnabled = false;
  });
  redisClient.connect().then(() => {
    console.log('[Redis] 连接成功');
    redisEnabled = true;
  }).catch(() => {
    console.warn('[Redis] 连接失败，降级到内存模式');
    redisEnabled = false;
  });
} catch {
  console.warn('[Redis] 未安装 redis 包，使用内存模式');
  redisEnabled = false;
}

const REDIS_KEY_PREFIX = 'meeting:';
const REDIS_TTL = 24 * 60 * 60;

function getRedisKey(roomId: string): string {
  return `${REDIS_KEY_PREFIX}${roomId}`;
}

export async function getOrCreateMeeting(roomId: string): Promise<MeetingState> {
  if (redisEnabled && redisClient) {
    try {
      const cached = await redisClient.get(getRedisKey(roomId));
      if (cached) {
        return JSON.parse(cached);
      }
    } catch {
      console.warn('[Redis] 读取失败，使用内存模式');
    }
  }

  if (!meetings.has(roomId)) {
    meetings.set(roomId, {
      roomId,
      seq: 0,
      messages: [],
      startedAt: Date.now(),
      endedAt: false,
      aiEnabled: false,
      botStatus: 'not_started',
      participants: [],
      asrSessions: [],
    });
  }

  return meetings.get(roomId)!;
}

export async function addMessage(roomId: string, message: Omit<ChatMessage, 'id' | 'seq' | 'roomId'>): Promise<ChatMessage> {
  const meeting = await getOrCreateMeeting(roomId);
  meeting.seq += 1;
  const fullMessage: ChatMessage = {
    ...message,
    id: `${roomId}-${meeting.seq}-${Date.now()}`,
    seq: meeting.seq,
    roomId,
  };
  meeting.messages.push(fullMessage);

  if (redisEnabled && redisClient) {
    try {
      await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
    } catch {
      console.warn('[Redis] 写入失败');
    }
  }

  return fullMessage;
}

export async function getMessagesAfterSeq(roomId: string, lastSeq: number): Promise<ChatMessage[]> {
  const meeting = await getOrCreateMeeting(roomId);
  if (!meeting) return [];
  return meeting.messages.filter((m) => m.seq > lastSeq);
}

export async function getAllMessages(roomId: string): Promise<ChatMessage[]> {
  const meeting = await getOrCreateMeeting(roomId);
  if (!meeting) return [];
  return [...meeting.messages];
}

export async function endMeeting(roomId: string): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    meeting.endedAt = true;
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}

export async function enableAI(roomId: string, userId: string): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    meeting.aiEnabled = true;
    meeting.botStatus = 'starting';
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}

export async function disableAI(roomId: string): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    meeting.aiEnabled = false;
    meeting.botStatus = 'stopped';
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}

export async function updateBotStatus(roomId: string, status: string): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    meeting.botStatus = status;
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}

export async function addParticipant(roomId: string, participant: { id: string; name: string; speakerToken?: string }): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    const existing = meeting.participants.find((p) => p.id === participant.id);
    if (!existing) {
      meeting.participants.push(participant);
    } else {
      Object.assign(existing, participant);
    }
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}

export async function removeParticipant(roomId: string, participantId: string): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    meeting.participants = meeting.participants.filter((p) => p.id !== participantId);
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}

export async function addAsrSession(roomId: string, participantId: string, sessionId: string): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    const existing = meeting.asrSessions.find((s) => s.participantId === participantId);
    if (!existing) {
      meeting.asrSessions.push({ participantId, sessionId });
    } else {
      existing.sessionId = sessionId;
    }
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}

export async function removeAsrSession(roomId: string, participantId: string): Promise<void> {
  const meeting = await getOrCreateMeeting(roomId);
  if (meeting) {
    meeting.asrSessions = meeting.asrSessions.filter((s) => s.participantId !== participantId);
    if (redisEnabled && redisClient) {
      try {
        await redisClient.set(getRedisKey(roomId), JSON.stringify(meeting), { EX: REDIS_TTL });
      } catch {
        console.warn('[Redis] 写入失败');
      }
    }
  }
}