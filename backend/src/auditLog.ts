// 操作审计日志 - 记录关键操作

type LogEntry = {
  timestamp: number;
  action: string;
  userId: string;
  roomId: string;
  detail?: string;
};

const logs: LogEntry[] = [];
const MAX_LOGS = 1000;

export function auditLog(action: string, userId: string, roomId: string, detail?: string): void {
  const entry: LogEntry = {
    timestamp: Date.now(),
    action,
    userId,
    roomId,
    detail,
  };
  logs.push(entry);
  if (logs.length > MAX_LOGS) {
    logs.shift();
  }
  console.log(`[AUDIT] ${new Date(entry.timestamp).toISOString()} | ${action} | user=${userId} | room=${roomId}${detail ? ` | ${detail}` : ''}`);
}

export function getLogs(roomId?: string): LogEntry[] {
  if (roomId) {
    return logs.filter((l) => l.roomId === roomId);
  }
  return [...logs];
}
