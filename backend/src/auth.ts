// 权限校验 - Phase 1 使用 Mock JWT
// 第二阶段对接真实 Jitsi JWT 后替换此文件

import jwt from 'jsonwebtoken';
import { JwtPayload } from './types';

// Phase 1 Mock 密钥，生产环境必须替换
const MOCK_JWT_SECRET = 'phase1-dev-secret-change-in-production';

/** 签发 Mock JWT（Phase 1 开发用） */
export function signMockToken(payload: Omit<JwtPayload, 'iat' | 'exp'>): string {
  return jwt.sign(payload, MOCK_JWT_SECRET, { expiresIn: '24h' });
}

/** 验证 JWT 并解析 payload */
export function verifyToken(token: string): JwtPayload | null {
  try {
    const decoded = jwt.verify(token, MOCK_JWT_SECRET) as JwtPayload;
    return decoded;
  } catch {
    return null;
  }
}

/** 判断是否为主持人 */
export function isModerator(token: string): boolean {
  const payload = verifyToken(token);
  return payload?.role === 'moderator';
}

/** 开发环境：生成测试 token */
export function generateDevTokens(roomId: string, userId: string) {
  return {
    moderator: signMockToken({ userId, roomId, role: 'moderator' }),
    participant: signMockToken({ userId, roomId, role: 'participant' }),
  };
}
