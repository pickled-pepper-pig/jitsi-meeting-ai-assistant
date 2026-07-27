// 后端入口 - 启动 HTTP + WebSocket 服务

import express from 'express';
import http from 'http';
import cors from 'cors';
import { initWebSocketServer } from './wsServer';
import { generateDevTokens, generateJitsiToken, verifyToken, isModerator } from './auth';
import { enableAI, disableAI, getOrCreateMeeting, addParticipant, addAsrSession } from './meetingState';

const app = express();
const server = http.createServer(app);

app.use(cors());
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: Date.now() });
});

// AI Gateway 模块 - Phase 2
// 管理会议生命周期、权限校验、Bot管理

/**
 * 获取 Jitsi JWT Token
 * POST /api/tokens
 * 
 * 请求体: { roomId, userId, role, userName? }
 */
app.post('/api/tokens', (req, res) => {
  const { roomId, userId, role, userName } = req.body;
  if (!roomId || !userId || !role) {
    return res.status(400).json({ error: 'roomId、userId、role 必填' });
  }
  if (role !== 'moderator' && role !== 'participant') {
    return res.status(400).json({ error: 'role 必须是 moderator 或 participant' });
  }
  const token = generateJitsiToken(roomId, userId, role, userName);
  res.json({ token });
});

/**
 * 验证 JWT Token
 * POST /api/tokens/verify
 */
app.post('/api/tokens/verify', (req, res) => {
  const { token } = req.body;
  if (!token) {
    return res.status(400).json({ error: 'token 必填' });
  }
  const payload = verifyToken(token);
  if (!payload) {
    return res.status(401).json({ valid: false, error: 'token 无效' });
  }
  res.json({ valid: true, payload });
});

/**
 * 检查是否为主持人
 * POST /api/tokens/is-moderator
 */
app.post('/api/tokens/is-moderator', (req, res) => {
  const { token } = req.body;
  if (!token) {
    return res.status(400).json({ error: 'token 必填' });
  }
  const result = isModerator(token);
  res.json({ isModerator: result });
});

/**
 * 会议 AI 管理接口
 */

/**
 * 开启 AI 助手
 * POST /api/meetings/:roomId/ai/start
 */
app.post('/api/meetings/:roomId/ai/start', async (req, res) => {
  const { roomId } = req.params;
  const { token } = req.body;

  if (!token) {
    return res.status(400).json({ error: 'token 必填' });
  }

  if (!isModerator(token)) {
    return res.status(403).json({ error: '只有主持人可以开启 AI 助手' });
  }

  const payload = verifyToken(token);
  if (!payload || payload.room !== roomId) {
    return res.status(401).json({ error: 'token 无效或与房间不匹配' });
  }

  await enableAI(roomId, payload.userId);

  res.json({
    success: true,
    message: 'AI 助手已启动',
    roomId,
    startedBy: payload.userId,
  });
});

/**
 * 停止 AI 助手
 * POST /api/meetings/:roomId/ai/stop
 */
app.post('/api/meetings/:roomId/ai/stop', async (req, res) => {
  const { roomId } = req.params;
  const { token } = req.body;

  if (!token) {
    return res.status(400).json({ error: 'token 必填' });
  }

  if (!isModerator(token)) {
    return res.status(403).json({ error: '只有主持人可以停止 AI 助手' });
  }

  const payload = verifyToken(token);
  if (!payload || payload.room !== roomId) {
    return res.status(401).json({ error: 'token 无效或与房间不匹配' });
  }

  await disableAI(roomId);

  res.json({
    success: true,
    message: 'AI 助手已停止',
    roomId,
    stoppedBy: payload.userId,
  });
});

/**
 * 获取会议 AI 状态
 * GET /api/meetings/:roomId/ai/status
 */
app.get('/api/meetings/:roomId/ai/status', async (req, res) => {
  const { roomId } = req.params;
  const { token } = req.query;

  if (!token) {
    return res.status(400).json({ error: 'token 必填' });
  }

  const payload = verifyToken(token as string);
  if (!payload || payload.room !== roomId) {
    return res.status(401).json({ error: 'token 无效或与房间不匹配' });
  }

  const meeting = await getOrCreateMeeting(roomId);
  res.json({
    roomId,
    aiEnabled: meeting.aiEnabled,
    botStatus: meeting.botStatus,
    participants: meeting.participants,
    asrSessions: meeting.asrSessions,
  });
});

/**
 * 注册参会者
 * POST /api/meetings/:roomId/participants
 */
app.post('/api/meetings/:roomId/participants', async (req, res) => {
  const { roomId } = req.params;
  const { token, participant } = req.body;

  if (!token) {
    return res.status(400).json({ error: 'token 必填' });
  }

  const payload = verifyToken(token);
  if (!payload || payload.room !== roomId) {
    return res.status(401).json({ error: 'token 无效或与房间不匹配' });
  }

  await addParticipant(roomId, participant);

  res.json({
    success: true,
    message: '参会者已注册',
    roomId,
    participant,
  });
});

/**
 * 注册 ASR Session
 * POST /api/meetings/:roomId/asr-sessions
 */
app.post('/api/meetings/:roomId/asr-sessions', async (req, res) => {
  const { roomId } = req.params;
  const { token, participantId, sessionId } = req.body;

  if (!token) {
    return res.status(400).json({ error: 'token 必填' });
  }

  const payload = verifyToken(token);
  if (!payload || payload.room !== roomId) {
    return res.status(401).json({ error: 'token 无效或与房间不匹配' });
  }

  await addAsrSession(roomId, participantId, sessionId);

  res.json({
    success: true,
    message: 'ASR Session 已注册',
    roomId,
    participantId,
    sessionId,
  });
});

/**
 * 开发环境：生成测试 JWT Token
 * Phase 2 保留用于开发测试，生产环境删除此接口
 */
app.post('/api/dev/tokens', (req, res) => {
  const { roomId, userId } = req.body;
  if (!roomId || !userId) {
    return res.status(400).json({ error: 'roomId 和 userId 必填' });
  }
  const tokens = generateDevTokens(roomId, userId);
  res.json(tokens);
});

const PORT = Number(process.env.PORT) || 8080;

server.listen(PORT, '0.0.0.0', () => {
  console.log(`═══════════════════════════════════════`);
  console.log(`  Meeting AI Server (Phase 2)`);
  console.log(`  HTTP:  http://localhost:${PORT}`);
  console.log(`  WS:    ws://localhost:${PORT}/ws`);
  console.log(`═══════════════════════════════════════`);
});

initWebSocketServer(server);