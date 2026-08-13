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
- **首次安全确认引导**：自签名证书环境首次进入会议时，内嵌两步向导引导用户打开信任窗口完成确认，无需手动复制粘贴地址
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
│   │   ├── llm_service/        # LLM 会议总结（OpenAI 兼容 API）
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
| 前端 (Vite) | **19307** | https://localhost:19307 |
| ASR WebSocket | **19087** | ws://localhost:19087 |
| 后端 HTTP API | **19089** | http://localhost:19089（Flask，自动 = WS + 2） |
| Jitsi Meet | **19447** | https://localhost:19447 |

---

## 快速开始

> 默认端口：前端 19307 / ASR WS 19087 / ASR HTTP 19089 / Jitsi 19447 / JVB UDP 19107

### 一、本地部署（macOS）

```bash
# 1. Jitsi
cd jitsi/jitsi && ./start.sh

# 2. 后端 ASR
cd silan-asr-service && conda activate asr
python main.py --device cpu

# 3. 前端
cd frontend && npm install && npx vite --port 19307 --host
```

浏览器打开 `https://localhost:19307`。停止 Jitsi：`./stop.sh`

### 二、服务端部署（Linux）

> 详细问题排查见 `SERVER_DEPLOY_GUIDE.md`（不进 git）

**前置**：Docker、conda、mkcert、Node.js 22+

```bash
# 1. 拉代码
cd meeting-ai-assistant
git pull origin main

# 2. Jitsi（改 .env 的 LOCAL_IP 为服务器 IP，生成证书，启动）
cd jitsi
# sed -i 's/LOCAL_IP=.*/LOCAL_IP=<SERVER_IP>/' .env
mkcert -key-file certs/jitsi.key -cert-file certs/jitsi.crt localhost 127.0.0.1 <SERVER_IP> ::1
./start-linux.sh

# 3. 后端 ASR（conda 环境，先杀旧进程再后台运行）
cd ../silan-asr-service
conda activate asr
pkill -f "python main.py" 2>/dev/null; sleep 1
# pip install -r requirements.txt && playwright install chromium
setsid nohup env BOT_HEADLESS=true \
    /home/asr/bin/python main.py --device cpu --host 0.0.0.0 --port 19087 \
    > logs/asr.log 2>&1 < /dev/null & disown
tail -f logs/asr.log

# 4. 前端（先杀旧进程再后台运行）
cd ../frontend
# npm install
pkill -f "vite" 2>/dev/null; sleep 1
mkcert -key-file localhost+3-key.pem -cert-file localhost+3.pem localhost 127.0.0.1 <SERVER_IP> ::1
setsid nohup npx vite --port 19307 --host > vite.log 2>&1 < /dev/null & disown
tail -f vite.log

# 5. 防火墙
sudo iptables -I INPUT -p tcp --dport 19307 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 19447 -j ACCEPT
sudo iptables -I INPUT -p udp --dport 19107 -j ACCEPT
```

验证：`curl -s http://localhost:19089/health`，浏览器打开 `https://<SERVER_IP>:19307`

**停止**：`cd jitsi && docker compose down` / `pkill -f "python main.py"` / `pkill -f vite`

---

## 🔧 配置

### 后端端口

编辑 `silan-asr-service/app/config/settings.py`：

```python
port: int = 19087  # WebSocket 端口，Flask API 自动运行在 port + 2
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

### LLM 配置（会议总结）

复制 `silan-asr-service/.env.example` 为 `.env`，填写 LLM 相关配置：

```bash
cd silan-asr-service
cp .env.example .env
```

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_API_KEY` | （无） | LLM API 密钥，未配置时回退到简单统计模式 |
| `LLM_BASE_URL` | `https://slapi.silan.com.cn/v1` | OpenAI 兼容 API 地址 |
| `LLM_MODEL` | `deepseek-v4-flash` | 模型名称 |
| `LLM_TEMPERATURE` | `0.3` | 生成温度（0-1，越低越确定） |
| `LLM_MAX_TOKENS` | `4096` | 最大输出 token 数 |
| `LLM_TIMEOUT` | `60` | 请求超时（秒） |
| `LLM_MAX_INPUT_CHARS` | `60000` | 输入文本最大字符数（超长时截取最近对话） |

---

##  WebSocket 事件

前端通过原生 WebSocket 与后端通信（开发时通过 Vite 代理 `/ws` → `ws://localhost:19087`）。
同时通过 Socket.IO 订阅房间级广播事件（开发时 Vite 代理 `/socket.io` → `http://localhost:19089`）。

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
| `--port` | 19087 | WebSocket 服务端口 |
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
lsof -i :19087

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
- [x] LLM 接入真实大模型（OpenAI 兼容 API，deepseek-v4-flash）
- [ ] Kafka 异步事件流集成（转写结果 → Kafka → 下游消费）
- [ ] 多会议并发压测与性能优化
- [ ] 会议录音文件云端归档（S3/OSS）
