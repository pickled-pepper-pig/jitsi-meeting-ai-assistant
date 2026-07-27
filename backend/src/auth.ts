// JWT 认证模块 - Phase 2 使用 RS256 非对称签名

import jwt from 'jsonwebtoken';
import fs from 'fs';
import path from 'path';
import { JwtPayload } from './types';

const PRIVATE_KEY_PATH = path.join(__dirname, '../keys/private.pem');
const PUBLIC_KEY_PATH = path.join(__dirname, '../keys/public.pem');

let privateKey: string;
let publicKey: string;

try {
  privateKey = fs.readFileSync(PRIVATE_KEY_PATH, 'utf8');
  publicKey = fs.readFileSync(PUBLIC_KEY_PATH, 'utf8');
} catch {
  console.warn('密钥文件未找到，将使用环境变量中的密钥');
  privateKey = process.env.JWT_PRIVATE_KEY || '';
  publicKey = process.env.JWT_PUBLIC_KEY || '';
}

const JWT_ISSUER = process.env.JWT_ISSUER || 'meeting-ai';
const JWT_AUDIENCE = 'jitsi';
const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || '24h';

export function signToken(payload: Omit<JwtPayload, 'iat' | 'exp'>): string {
  return jwt.sign(payload, privateKey, {
    algorithm: 'RS256',
    expiresIn: JWT_EXPIRES_IN,
  });
}

export function verifyToken(token: string): JwtPayload | null {
  try {
    const decoded = jwt.verify(token, publicKey, {
      algorithms: ['RS256'],
      issuer: JWT_ISSUER,
      audience: JWT_AUDIENCE,
    }) as JwtPayload;
    return decoded;
  } catch {
    return null;
  }
}

export function isModerator(token: string): boolean {
  const payload = verifyToken(token);
  return payload?.role === 'moderator';
}

export function generateJitsiToken(roomId: string, userId: string, role: 'moderator' | 'participant', userName?: string): string {
  const payload: JwtPayload = {
    iss: JWT_ISSUER,
    sub: roomId,
    aud: JWT_AUDIENCE,
    room: roomId,
    userId,
    role,
    context: userName ? { user: { name: userName } } : undefined,
  };
  return signToken(payload);
}

export function generateDevTokens(roomId: string, userId: string) {
  return {
    moderator: generateJitsiToken(roomId, userId, 'moderator'),
    participant: generateJitsiToken(roomId, userId, 'participant'),
  };
}