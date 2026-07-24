// 后端入口 - 启动 HTTP + WebSocket 服务

import express from 'express';
import http from 'http';
import cors from 'cors';
import { initWebSocketServer } from './wsServer';
import { generateDevTokens } from './auth';

const app = express();
const server = http.createServer(app);

app.use(cors());
app.use(express.json());

// 健康检查
app.get('/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: Date.now() });
});

/**
 * 开发环境：生成测试 JWT Token
 * Phase 1 专用，生产环境删除此接口
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
  console.log(`  Meeting AI Server (Phase 1)`);
  console.log(`  HTTP:  http://localhost:${PORT}`);
  console.log(`  WS:    ws://localhost:${PORT}/ws`);
  console.log(`═══════════════════════════════════════`);
});

// 初始化 WebSocket
initWebSocketServer(server);
