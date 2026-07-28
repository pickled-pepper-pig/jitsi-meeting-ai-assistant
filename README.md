# 🤖 Meeting AI Assistant

集成 Jitsi Meet 视频会议的 AI 助手，提供实时 ASR 转写、聊天展示和会议总结功能。

---

## ✨ 功能

- **实时聊天**：捕获并同步 Jitsi 会议聊天消息
- **会议总结**：主持人一键生成会议纪要
- **ASR 转写**：FunASR Paraformer 流式语音识别
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
| 后端 | Python (websockets + Flask) | 3.x |
| ASR | FunASR Paraformer (流式) | - |
| 通信 | 原生 WebSocket | websockets |
| 认证 | JWT (RS256) | PyJWT |
| 缓存 | Redis | redis-py |
| 视频 | Jitsi Meet (Docker) | - |
| 语言 | TypeScript (前端) / Python (后端) | 5.3 / 3.x |

---

## 📁 结构

```
meeting-ai-assistant/
├── silan-asr-service/          # Python 统一后端服务
│   ├── app/
│   │   ├── auth/               # JWT 认证（RS256）
│   │   ├── api_routes/         # HTTP API 路由
│   │   ├── meeting_ws/         # WebSocket 会议事件处理
│   │   ├── meeting_state/      # Redis + 内存会议状态
│   │   ├── llm_service/        # Mock LLM 会议总结
│   │   ├── audit_log/          # 审计日志
│   │   ├── audio_gateway/      # WebSocket 网关入口
│   │   ├── asr_worker/         # FunASR 推理 Worker
│   │   ├── session_manager/    # ASR 会话管理
│   │   ├── transcript_service/ # 转写结果分发
│   │   └── config/             # 配置管理
│   ├── keys/                   # RSA 密钥对
│   └── main.py                 # 服务入口
├── frontend/
│   ├── src/
│   │   ├── components/         # React 组件
│   │   ├── hooks/              # WebSocket Hook
│   │   ├── services/           # 音频采集服务
│   │   ── types/              # 类型定义
│   └── package.json
├── jitsi/
│   ├── docker-compose.yml
│   ├── .env.example
│   └── start.sh
└── README.md
```

---

##  快速开始

### 1. 启动 Jitsi（Docker）

```bash
cd jitsi
docker compose up -d
# Jitsi 运行在 https://localhost:8443
```

> Jitsi 是开源视频会议引擎，包含 web、prosody、jicofo、jvb 四个容器，官方推荐 Docker Compose 部署。

### 2. 启动后端 ASR 服务（Python）

```bash
# 使用 conda asr 环境（已预装所有依赖）
conda activate asr
cd silan-asr-service
python main.py --device cpu
# WebSocket 监听 0.0.0.0:50051
# Flask HTTP API 监听 127.0.0.1:50053（自动启动）
```

### 3. 启动前端（Vite）

```bash
cd frontend
npm install
npx vite --port 3000 --host
# 前端运行在 https://localhost:3000
```

### 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | https://localhost:3000 | AI 侧边栏界面 |
| ASR WebSocket | ws://localhost:50051 | 音频转写 + 会议信令 |
| 后端 HTTP API | http://localhost:50053 | REST 接口（端口 = WS + 2） |
| Jitsi | https://localhost:8443 | 视频会议引擎 |

### 完整启动顺序

```bash
# 1. 启动 Jitsi
cd /Users/apple/Projects/silan/jitsi/jitsi && docker compose up -d

# 2. 启动后端（新终端）
cd /Users/apple/Projects/silan/jitsi/silan-asr-service
/Users/apple/miniconda3/envs/asr/bin/python main.py --device cpu

# 3. 启动前端（新终端）
cd /Users/apple/Projects/silan/jitsi/frontend
npx vite --port 3000 --host
```

---

## 🔧 配置

### 后端端口

编辑 `silan-asr-service/app/config/settings.py`：

```python
port: int = 50051  # WebSocket 端口，Flask API 自动运行在 port + 2
```

### 切换 Jitsi 服务

编辑 `frontend/src/config.ts`：

```typescript
export const CURRENT_JITSI = 'local'; // 'public' | 'local'
```

### JWT 配置

后端使用 RS256 非对称签名：
- 私钥：`silan-asr-service/keys/private.pem`
- 公钥：`silan-asr-service/keys/public.pem`
- 环境变量：`JWT_ISSUER`、`JWT_EXPIRES_IN`

### Redis 配置

默认地址：`redis://localhost:6379`，通过 `REDIS_URL` 环境变量覆盖。未配置时自动降级为内存存储。

---

## 🔌 API 接口

### 健康检查

```bash
GET /health
```

### Token 管理

```bash
# 获取 Jitsi JWT Token
POST /api/tokens
Content-Type: application/json

{
  "roomId": "room-a",
  "userId": "user-001",
  "role": "moderator",
  "userName": "张三"
}

# 验证 Token
POST /api/tokens/verify
{"token": "your-jwt-token"}

# 检查是否主持人
POST /api/tokens/is-moderator
{"token": "your-jwt-token"}

# 开发环境生成测试 Token
POST /api/dev/tokens
Content-Type: application/json

{
  "roomId": "room-a",
  "userId": "user-001"
}
```

### 会议 AI 管理

```bash
# 开启 AI 助手
POST /api/meetings/{roomId}/ai/start
Content-Type: application/json

{
  "token": "your-jwt-token"
}

# 停止 AI 助手
POST /api/meetings/{roomId}/ai/stop
Content-Type: application/json

{
  "token": "your-jwt-token"
}

# 获取会议 AI 状态
GET /api/meetings/{roomId}/ai/status?token=your-jwt-token
```

### 参会者 & ASR Session

```bash
# 注册参会者
POST /api/meetings/{roomId}/participants
Content-Type: application/json

{
  "token": "your-jwt-token",
  "participant": {"id": "p1", "name": "张三"}
}

# 注册 ASR Session
POST /api/meetings/{roomId}/asr-sessions
Content-Type: application/json

{
  "token": "your-jwt-token",
  "participantId": "p1",
  "sessionId": "sess-001"
}
```

### 审计日志

```bash
GET /api/audit-logs?roomId=room-a
```

---

## 🔗 WebSocket 事件

前端通过原生 WebSocket 与后端通信：

### 会议信令

| 客户端事件 | 说明 |
|-----------|------|
| `{"action": "join"}` | 加入会议房间 |
| `{"action": "leave"}` | 离开会议房间 |
| `{"action": "chat"}` | 发送聊天消息 |
| `{"action": "summarize"}` | 请求生成会议总结（仅主持人） |
| `{"action": "sync"}` | 同步断线期间错过的消息 |

| 服务端事件 | 说明 |
|-----------|------|
| `meeting_joined` | 确认加入，返回 lastSeq |
| `meeting_chat` | 广播聊天消息 |
| `meeting_summary` | 广播会议总结 |
| `meeting_synced` | 返回错过的消息列表 |
| `meeting_error` | 错误提示 |
| `meeting_status` | 状态更新 |

### 音频转写

| 客户端事件 | 说明 |
|-----------|------|
| `{"action": "create_session", ...}` | 创建 ASR 会话 |
| `{"action": "audio_chunk", ...}` | 发送音频数据（base64） |
| `{"action": "end_session", ...}` | 结束会话 |

| 服务端事件 | 说明 |
|-----------|------|
| `connected` | 连接确认 |
| `session_created` | 会话创建成功 |
| `transcript` | 转写结果（interim + final） |
| `session_finalized` | 会话结束 |

---

## 📄 许可证

MIT License

---

## 📌 待办

- [x] JWT 认证（RS256）
- [x] AI Gateway 模块
- [x] Redis Meeting State
- [x] 后端迁移至 Python 统一服务 (silan-asr-service)
- [x] 前后端统一为原生 WebSocket 协议
- [ ] Recorder Bot 获取个人音频轨道
- [ ] Streaming ASR 实时转写（集成 FunASR）
- [ ] 对象存储集成
