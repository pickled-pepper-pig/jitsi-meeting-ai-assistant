# 🤖 Meeting AI Assistant

集成 Jitsi Meet 视频会议的 AI 助手，提供实时聊天展示和会议总结功能。

---

## ✨ 功能特性

- **实时聊天展示**：捕获 Jitsi 会议中的聊天消息，通过 WebSocket 实时同步到所有参会者
- **会议总结**：主持人可生成会议纪要，基于聊天记录自动生成摘要
- **断线重连**：WebSocket 断线自动重连，自动补齐错过的消息
- **角色权限**：区分主持人和参会者，只有主持人可以生成总结
- **本地部署**：支持本地 Docker 部署 Jitsi Meet 服务

---

## 🛠️ 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 前端框架 | React | 18.2 |
| 前端构建 | Vite | 5.0 |
| 后端框架 | Express | 4.18 |
| WebSocket | ws | 8.16 |
| 认证 | JWT | 9.0 |
| 视频会议 | Jitsi Meet | - |
| 容器化 | Docker Compose | - |
| 语言 | TypeScript | 5.3 |

---

## 📁 项目结构

```
meeting-ai-assistant/
├── backend/                    # 后端服务
│   ├── src/
│   │   ├── index.ts            # 入口文件（HTTP + WebSocket）
│   │   ├── wsServer.ts         # WebSocket 服务器
│   │   ├── meetingState.ts     # 会议状态管理
│   │   ├── auth.ts             # 权限校验（Mock JWT）
│   │   ├── mockLLM.ts          # Mock LLM 服务
│   │   └── types.ts            # 类型定义
│   └── package.json
│
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── App.tsx             # 主应用组件
│   │   ├── config.ts           # 配置文件
│   │   ├── components/         # UI 组件
│   │   │   ├── JitsiMeeting.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── MessageList.tsx
│   │   │   └── SummaryButton.tsx
│   │   ├── hooks/              # 自定义 Hooks
│   │   │   ├── useJitsiApi.ts
│   │   │   └── useWebSocket.ts
│   │   └── utils/              # 工具函数
│   │       └── messageBuffer.ts
│   └── package.json
│
└── jitsi/                      # 本地 Jitsi 部署
    ├── docker-compose.yml      # Docker Compose 配置
    ├── .env.example            # 环境变量示例
    ├── jitsi-meet-cfg/         # Jitsi 配置模板
    ├── start.sh
    └── stop.sh
```

---

## 🚀 快速开始

### 环境要求

- Node.js >= 18
- npm >= 9
- Docker & Docker Compose（本地 Jitsi 部署）

### 启动服务

```bash
# 1. 启动后端服务
cd backend
npm install
npm run dev

# 2. 启动前端服务
cd frontend
npm install
npm run dev

# 3. （可选）启动本地 Jitsi 服务
cd jitsi
cp .env.example .env
# 编辑 .env，修改 PUBLIC_URL 和 JVB_ADVERTISE_IPS 为你的 IP
./start.sh
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | https://localhost:3000 |
| 后端 API | http://localhost:8080 |
| Jitsi Meet | https://localhost:8443 |

### 使用公共 Jitsi 服务

默认使用本地 Jitsi 部署。如需使用公共服务（meet.jit.si），修改 `frontend/src/config.ts`：

```typescript
export const CURRENT_JITSI = 'public' as 'public' | 'local';
```

> **注意**：公共服务有 5 分钟通话限制，适合开发测试。

---

## 📝 API 接口

### 获取开发 Token

```
POST /api/dev/tokens
```

请求体：
```json
{
  "roomId": "meeting-room",
  "userId": "user-123"
}
```

响应：
```json
{
  "moderator": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "participant": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

---

## 🧪 WebSocket 消息协议

### 客户端发送

| Action | 说明 | 参数 |
|--------|------|------|
| `join` | 加入房间 | `roomId`, `token` |
| `leave` | 离开房间 | `roomId` |
| `chat` | 发送消息 | `roomId`, `token`, `content`, `sender` |
| `summarize` | 生成总结 | `roomId`, `token` |
| `sync` | 同步消息 | `roomId`, `lastSeq` |

### 服务端推送

| Type | 说明 | 数据 |
|------|------|------|
| `joined` | 加入成功 | `roomId`, `lastSeq` |
| `chat` | 聊天消息 | `payload` (ChatMessage) |
| `summary` | 会议总结 | `roomId`, `summary`, `timestamp` |
| `synced` | 同步完成 | `messages` |
| `error` | 错误信息 | `message` |

---

## 🔧 配置说明

### 前端配置

编辑 `frontend/src/config.ts`：

```typescript
// 切换 Jitsi 服务
export const CURRENT_JITSI = 'local'; // 'public' | 'local'

// API 配置
export const API_CONFIG = {
  baseUrl: '',
  wsUrl: `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`,
};
```

### Jitsi 配置

复制 `jitsi/.env.example` 为 `jitsi/.env`，修改以下参数：

```bash
# 服务器 IP 地址
PUBLIC_URL=https://your-server-ip:8443
JVB_ADVERTISE_URLS=wss://your-server-ip:8443
JVB_ADVERTISE_IPS=your-server-ip

# 密码配置（建议修改）
JVB_AUTH_PASSWORD=your-jvb-auth-password
JICOFO_AUTH_PASSWORD=your-jicofo-auth-password
JICOFO_COMPONENT_SECRET=your-component-secret
```

---

## 📄 许可证

MIT License

---

## 📌 Phase 2 待办

- [ ] 对接真实 Jitsi JWT 认证
- [ ] 接入真实 LLM 服务（OpenAI、通义千问等）
- [ ] 连续同发言者话语合并
- [ ] 音频播放自动滚动
- [ ] 完善配置管理（环境变量）
- [ ] 添加单元测试