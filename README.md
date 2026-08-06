# 🤖 Meeting AI Assistant

集成 Jitsi Meet 视频会议的 AI 助手，提供实时 ASR 转写、聊天展示和会议总结功能。

---

## ✨ 功能

- **实时聊天**：捕获并同步 Jitsi 会议聊天消息
- **会议总结**：主持人一键生成会议纪要
- **ASR 流式转写**：FunASR Paraformer 流式识别 + Silero VAD 神经网络前端，跨句累积不切碎、自动加标点
- **断线重连**：WebSocket 自动重连 + 消息补齐
- **角色权限**：主持人/参会者区分，一房一主持人
- **房间级 AI 广播**：主持人开启 AI 后，房间内所有人实时看到转写内容
- **AI Gateway**：会议生命周期管理、权限校验、Bot 管理
- **Meeting Agent**：Playwright + Headless Chromium 控制的 Recorder Bot，作为隐藏参会者加入会议捕获音频
- **JWT 认证**：HS256 共享密钥，支持 Jitsi XMPP affiliation
- **Redis 状态**：会议状态持久化，支持内存降级
- **本地部署**：Docker 一键部署 Jitsi

---

## 🛠️ 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 前端 | React + Vite | 18.2 / 5.0 |
| 后端 | Python (websockets + Flask-SocketIO) | 3.x |
| ASR | FunASR Paraformer (流式) | 1.3.30 |
| 通信 | 原生 WebSocket + Socket.IO | websockets / flask-socketio |
| 认证 | JWT (HS256) | PyJWT |
| 缓存 | Redis | redis-py |
| 视频 | Jitsi Meet (Docker) | - |
| 语言 | TypeScript (前端) / Python (后端) | 5.3 / 3.x |

---

## 📁 结构

```
silan-jitsi/
├── silan-asr-service/          # Python 统一后端服务
│   ├── app/
│   │   ├── asr_worker/         # FunASR 推理 Worker
│   │   ├── audio_gateway/      # WebSocket 网关入口
│   │   ├── audio_processor/    # 音频预处理
│   │   ├── session_manager/    # ASR 会话管理
│   │   ├── transcript_service/ # 转写结果分发
│   │   ├── normalization/      # 行业术语归一化
│   │   ├── api_routes/         # HTTP API 路由
│   │   ├── meeting_ws/         # 会议 WebSocket 处理
│   │   ├── meeting_state/      # Redis 会议状态
│   │   ├── meeting_agent/      # Meeting Agent（Playwright + Chromium Recorder Bot）
│   │   │   ├── manager/        # Bot 生命周期管理（spawn/kill/status）
│   │   │   ├── browser/        # Playwright 控制器 + recorder.html
│   │   │   ├── audio/          # Bot 侧 PCM 接收 + 重采样 + wav 落盘
│   │   │   └── participant/    # participant_id ↔ speaker_id 映射
│   │   ├── auth/               # JWT 认证
│   │   ├── llm_service/        # Mock LLM 总结
│   │   ├── audit_log/          # 审计日志
│   │   └── config/            # 配置管理
│   ├── resources/vocab/        # 行业热词库
│   ├── tests/                  # 测试
│   ├── test_client/            # ASR 测试工具（TTS 生成 / 流式回放 / CER 评估）
│   ├── main.py                 # 服务入口
│   └── requirements.txt        # Python 依赖
├── frontend/
│   ├── src/
│   │   ├── components/         # React 组件
│   │   ├── hooks/              # WebSocket Hook
│   │   ├── services/           # 音频采集服务
│   │   └── types/              # 类型定义
│   ├── public/bot.html         # Bot 加入页
│   └── package.json
├── jitsi/                      # Jitsi Docker 部署
├── DOCS.md                     # 技术架构文档
├── README.md
├── CHANGELOG.md
└── .gitignore
```

---

## 🔌 端口配置

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 (Vite) | **3000** | https://localhost:3000 |
| ASR WebSocket | **8080** | ws://localhost:8080 |
| 后端 HTTP API | **8082** | http://localhost:8082（Flask，自动 = WS + 2） |
| Jitsi Meet | **8443** | https://localhost:8443 |

---

## 快速开始

### 1. 启动 Jitsi（Docker）

```bash
cd jitsi/jitsi
./start.sh          # macOS
./start-linux.sh    # Linux 服务器
# Jitsi 运行在 https://localhost:8443
```

> 使用启动脚本而非 `docker compose up -d`。脚本会自动检测局域网 IP，
> 当 IP 变化时自动更新 `.env`、重新生成 SSL 证书并重启容器，
> 避免 WSS 连接因证书 IP 不匹配导致"你已断开连接"。
>
> - **macOS** 用 `./start.sh`（通过 `ipconfig getifaddr` 获取 IP）
> - **Linux** 用 `./start-linux.sh`（通过 `ip route` / `hostname -I` 获取 IP，`sed -i` 语法兼容 GNU）
>
> 停止服务：`./stop.sh`

### 2. 启动后端 ASR 服务（Python）

```bash
# 使用 conda asr 环境
conda activate asr
cd silan-asr-service
python main.py --device cpu
# WebSocket 监听 0.0.0.0:8080
# Flask HTTP API 自动监听 127.0.0.1:8082
```

### 3. 启动前端（Vite）

```bash
cd frontend
npm install
npx vite --port 3000 --host
# 前端运行在 https://localhost:3000
```

### 4. ASR 链路测试

```bash
# 流式回放 wav 模拟真实会议
python -m test_client.wav_stream_client --wav path/to/audio.wav
```

### 完整启动顺序

```bash
# 1. 启动 Jitsi
cd /Users/apple/Projects/silan/jitsi/jitsi/jitsi && ./start.sh

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
port: int = 8080  # WebSocket 端口，Flask API 自动运行在 port + 2
```

### 切换 Jitsi 服务

编辑 `frontend/src/config.ts`：

```typescript
export const CURRENT_JITSI = 'local'; // 'public' | 'local'
```

### JWT 配置

后端使用 HS256 共享密钥（与 Jitsi Prosody 共享）：
- 环境变量：`JWT_SHARED_SECRET`、`JWT_ALGORITHM=HS256`
- 与 Prosody 的 `JWT_APP_ID` / `JWT_APP_SECRET` 完全一致
- JWT payload 含 `role`（moderator/participant）+ `affiliation`（owner/member）

### Redis 配置

默认地址：`redis://localhost:6379`，通过 `REDIS_URL` 环境变量覆盖。未配置时自动降级为内存存储。

---

## 🔌 API 接口

### 健康检查

```bash
GET http://localhost:8082/health
```

### Token 管理

```bash
# 获取 Jitsi JWT Token
POST http://localhost:8082/api/tokens
Content-Type: application/json

{
  "roomId": "room-a",
  "userId": "user-001",
  "role": "moderator",
  "userName": "张三"
}

# 验证 Token
POST http://localhost:8082/api/tokens/verify
{"token": "your-jwt-token"}

# 检查是否主持人
POST http://localhost:8082/api/tokens/is-moderator
{"token": "your-jwt-token"}

# 开发环境生成测试 Token
POST http://localhost:8082/api/dev/tokens
Content-Type: application/json

{
  "roomId": "room-a",
  "userId": "user-001"
}
```

### 会议 AI 管理

```bash
# 开启 AI 助手
POST http://localhost:8082/api/meetings/{roomId}/ai/start
Content-Type: application/json

{
  "token": "your-jwt-token"
}

# 停止 AI 助手
POST http://localhost:8082/api/meetings/{roomId}/ai/stop
Content-Type: application/json

{
  "token": "your-jwt-token"
}

# 获取会议 AI 状态
GET http://localhost:8082/api/meetings/{roomId}/ai/status?token=your-jwt-token
```

### 参会者 & ASR Session

```bash
# 注册参会者
POST http://localhost:8082/api/meetings/{roomId}/participants
Content-Type: application/json

{
  "token": "your-jwt-token",
  "participant": {"id": "p1", "name": "张三"}
}

# 注册 ASR Session
POST http://localhost:8082/api/meetings/{roomId}/asr-sessions
Content-Type: application/json

{
  "token": "your-jwt-token",
  "participantId": "p1",
  "sessionId": "sess-001"
}
```

### 审计日志

```bash
GET http://localhost:8082/api/audit-logs?roomId=room-a
```

### 会议历史消息

```bash
# 拉取指定房间的所有历史消息（chat / summary / transcript）
# 支持 since_seq 增量参数
GET http://localhost:8082/api/meetings/{roomId}/messages?token=your-jwt-token[&since_seq=0]
```

新加入者通过此接口 + WS `room_state_snapshot` 双重兜底拉到进入前的会议纪要。

### Meeting Agent Bot 管理

仅主持人 token 可调用。Bot JWT 由服务端重签为 "AI Assistant" 身份，不依赖调用方 token。

```bash
# 拉起 Recorder Bot 加入会议
POST http://localhost:8082/api/meetings/{roomId}/bot/spawn
Content-Type: application/json

{
  "token": "your-moderator-token",
  "roomUrl": "https://192.0.36.227:8443"
}

# 停止 Bot
POST http://localhost:8082/api/meetings/{roomId}/bot/kill
Content-Type: application/json

{
  "token": "your-moderator-token"
}

# 查询 Bot 状态
GET http://localhost:8082/api/meetings/{roomId}/bot/status?token=your-moderator-token

# 列出所有 Bot（调试用）
GET http://localhost:8082/api/bots
```

Bot 侧 PCM 通过独立 WebSocket 路径 `/ws/recorder/{meeting_id}` 上行，与会议/ASR 通道隔离。

---

## 🔗 WebSocket 事件

前端通过原生 WebSocket 与后端通信（开发时通过 Vite 代理 `/ws` → `ws://localhost:8080`）。
同时通过 Socket.IO 订阅房间级广播事件（开发时 Vite 代理 `/socket.io` → `http://localhost:8082`）。

### 会议信令（原 WebSocket）

| 客户端事件 | 说明 |
|-----------|------|
| `{"action": "join"}` | 加入会议房间 |
| `{"action": "leave"}` | 离开会议房间 |
| `{"action": "chat"}` | 发送聊天消息 |
| `{"action": "summarize"}` | 请求生成会议总结（仅主持人） |
| `{"action": "sync"}` | 同步断线期间错过的消息 |

| 服务端事件 | 说明 |
|-----------|------|
| `joined` | 确认加入，返回 lastSeq，并立即推送 `ai_bot_status` + `room_state_snapshot` |
| `chat` | 广播聊天消息 |
| `summary` | 广播会议总结 |
| `room_state_snapshot` | 新加入者收到的一次性房间历史快照（含 chat/summary/transcript 全部消息） |
| `synced` | 返回错过的消息列表 |
| `status` | 状态更新 |
| `error` | 错误提示 |

### 音频转写

| 客户端事件 | 说明 |
|-----------|------|
| `{"action": "create_session", ...}` | 创建 ASR 会话 |
| `{"action": "audio_chunk", ...}` | 发送音频数据（base64） |
| `{"action": "end_session", ...}` | 结束会话 |

| 服务端事件 | 说明 |
|-----------|------|
| `session_created` | 会话创建成功 |
| `transcript` | 转写结果（interim + final） |
| `error` | 错误提示 |

### 房间广播（Socket.IO）

| 事件 | 说明 |
|------|------|
| `meeting_join` | 加入房间（需 token），返回 `meeting_joined` + `ai_bot_status` 补发 |
| `meeting_chat` | 房间内聊天广播 |
| `meeting_summarize` | 主持人触发总结 |
| `meeting_sync` | 断线补齐 |
| `ai_bot_status` | 房间 AI Bot 状态变化（任意人开启/关闭） |
| `meeting_transcript` | 主持人产生的 final 转写（旁观者实时接收） |

---

## 🎙️ ASR 服务详情

### 特性

- **实时流式 ASR** - 基于 FunASR Paraformer 模型的流式识别
- **多会话并发** - 支持多个用户同时进行音频转写
- **行业术语增强** - 内置半导体行业热词库（84 热词 + 62 行业术语）
- **音频预处理** - 自动重采样、降噪、Silero VAD 神经网络语音检测（per-session 状态）
- **批处理优化** - Batch Scheduler 提升推理效率

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | 8080 | WebSocket 服务端口 |
| `--host` | 0.0.0.0 | 服务监听地址 |
| `--device` | cpu | 推理设备 (cpu/cuda) |
| `--log-level` | INFO | 日志级别 |

### 音频格式要求

- **采样率**: 16000 Hz（其他采样率自动重采样）
- **位深度**: 16-bit PCM (float32)
- **通道数**: 单声道（多声道自动转换）
- **编码格式**: base64 编码的原始 PCM 数据

### 故障排查

```bash
# 端口被占用
lsof -i :8080

# 强制使用 CPU
python main.py --device cpu

# 降低批处理大小
ASR_MAX_BATCH_SIZE=16 python main.py
```

---

## 📄 许可证

MIT License

---

## 📌 待办

- [x] JWT 认证（HS256 共享密钥）
- [x] AI Gateway 模块
- [x] Redis Meeting State
- [x] 后端迁移至 Python 统一服务 (silan-asr-service)
- [x] 前后端统一为原生 WebSocket 协议
- [x] Recorder Bot Spike 验证（lib-jitsi-meet 远程音轨捕获）
- [x] ASR 服务模型修复（funasr 1.3.30 + paraformer-zh-streaming）
- [x] Streaming ASR 实时转写（FunASR 流式 + 跨句累积 + 自动加标点）
- [x] 房间级 AI 状态广播（Socket.IO 跨通道）
- [x] 一房一主持人鉴权（先到先得）
- [ ] LLM 接入真实大模型（目前为 Mock）
- [ ] 对象存储集成
