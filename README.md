# 🤖 Meeting AI Assistant

集成 Jitsi Meet 视频会议的 AI 助手，提供实时聊天展示和会议总结功能。

---

## ✨ 功能

- **实时聊天**：捕获并同步 Jitsi 会议聊天消息
- **会议总结**：主持人一键生成会议纪要
- **断线重连**：WebSocket 自动重连 + 消息补齐
- **角色权限**：主持人/参会者区分
- **AI Gateway**：会议生命周期管理、权限校验、Bot 管理
- **JWT 认证**：RS256 非对称签名，支持 Jitsi 集成
- **Redis 状态**：会议状态持久化，支持内存降级
- **本地部署**：Docker 一键部署 Jitsi

---

## 🛠️ 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 前端 | React + Vite | 18.2 / 5.0 |
| 后端 | Express + ws | 4.18 / 8.16 |
| 认证 | JWT (RS256) | 9.0 |
| 缓存 | Redis | 4.6 |
| 视频 | Jitsi Meet | - |
| 语言 | TypeScript | 5.3 |

---

## 📁 结构

```
meeting-ai-assistant/
├── backend/
│   ├── src/
│   │   ├── auth.ts          # JWT 认证（RS256）
│   │   ├── index.ts         # HTTP 服务 + AI Gateway
│   │   ├── wsServer.ts      # WebSocket 服务器
│   │   ├── meetingState.ts  # Redis + 内存会议状态
│   │   ├── mockLLM.ts       # Mock LLM 总结
│   │   └── types.ts         # 类型定义
│   ├── keys/                # RSA 密钥对
│   └── package.json
├── frontend/
│   ├── src/
│   └── package.json
├── jitsi/
│   ├── docker-compose.yml
│   ├── .env.example
│   └── start.sh
├── CHANGELOG.md
└── README.md
```

---

## 🚀 快速开始

### 启动服务

```bash
# 后端 (端口 8080)
cd backend && npm install && npm run dev

# 前端 (端口 3000)
cd frontend && npm install && npm run dev

# 本地 Jitsi (端口 8443)
cd jitsi && cp .env.example .env && ./start.sh
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | https://localhost:3000 |
| 后端 | http://localhost:8080 |
| Jitsi | https://localhost:8443 |

---

## 🔧 配置

### 切换 Jitsi 服务

编辑 `frontend/src/config.ts`：

```typescript
export const CURRENT_JITSI = 'local'; // 'public' | 'local'
```

### JWT 配置

后端使用 RS256 非对称签名：
- 私钥：`backend/keys/private.pem`
- 公钥：`backend/keys/public.pem`
- 环境变量：`JWT_ISSUER`、`JWT_EXPIRES_IN`

### Redis 配置

默认地址：`redis://localhost:6379`，通过 `REDIS_URL` 环境变量覆盖。

---

## 🔌 API 接口

### 获取 JWT Token

```bash
POST /api/tokens
Content-Type: application/json

{
  "roomId": "room-a",
  "userId": "user-001",
  "role": "moderator",
  "userName": "张三"
}
```

### 开启 AI 助手

```bash
POST /api/meetings/{roomId}/ai/start
Content-Type: application/json

{
  "token": "your-jwt-token"
}
```

### 获取会议状态

```bash
GET /api/meetings/{roomId}/ai/status?token=your-jwt-token
```

---

## 📄 许可证

MIT License

---

## 📌 Phase 2 待办

- [x] JWT 认证升级（RS256）
- [x] AI Gateway 模块
- [x] Redis Meeting State
- [ ] Recorder Bot 获取个人音频轨道
- [ ] Streaming ASR 实时转写
- [ ] 对象存储集成