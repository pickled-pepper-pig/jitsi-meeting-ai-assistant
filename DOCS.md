# Jitsi 会议 AI 助手 — 技术文档

> 局域网自部署的 Jitsi Meet 视频会议 + 实时语音转写 + AI 会议纪要一体化系统。

---

## 一、项目结构

```
jitsi/
├── jitsi/                        # Jitsi Meet（Docker Compose）
│   ├── docker-compose.yml        # 编排 Web / Jicofo / JVB / Prosody
│   ├── jitsi-meet-cfg/           # 各组件配置 + JWT 鉴权
│   ├── certs/                    # mkcert 自签证书（8443 端口）
│   ├── start.sh                  # 一键启动脚本（自动检测 IP + 重新生成证书）
│   ├── stop.sh                   # 停止脚本
│   └── .env                      # 局域网 IP / 鉴权开关
│
├── silan-asr-service/            # 后端 ASR + 会议服务（Python）
│   ├── main.py                   # 启动入口（WebSocket 8080 + Flask HTTP 8082）
│   ├── app/
│   │   ├── audio_gateway/        # WS 网关 + 转写聚合器
│   │   │   ├── ws_server.py      #   WebSocket 服务（会议房间 + ASR 音频）
│   │   │   └── transcript_aggregator.py  # 流式 partial 累积 + 句尾检测
│   │   ├── asr_worker/           # FunASR 双模型识别
│   │   │   └── worker.py         #   Paraformer 流式 + SenseVoice 段批
│   │   ├── audio_processor/      # 重采样 / Silero VAD
│   │   ├── meeting_agent/        # Meeting Agent Bot（Playwright）
│   │   │   ├── browser/          #   Headless Chromium 控制器
│   │   │   ├── audio/            #   Bot 音频接收 + WAV 落盘
│   │   │   ├── manager/          #   Bot 生命周期管理
│   │   │   └── participant/      #   参会者跟踪
│   │   ├── meeting_state/        # Redis 状态持久化
│   │   ├── llm_service/          # LLM 会议纪要生成
│   │   ├── auth/                 # JWT 鉴权（HS256）
│   │   ├── config/               # 全局配置
│   │   └── api_routes/           # HTTP API（token / bot spawn / summary）
│   ├── resources/vocab/          # 热词词表
│   └── test_client/              # wav 流式回放测试工具
│
└── frontend/                     # 前端（React 18 + TS + Vite 5）
    └── src/
        ├── App.tsx               # 主页（加入会议 + 录制控制 + 可拖动分割线）
        ├── components/           # JitsiMeeting / Sidebar / MessageList
        ├── hooks/                # useJitsiApi / useWebSocket
        └── services/             # audioCapture / participantAudioReceiver / pcmConverter
```

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  浏览器 (React + Jitsi IFrame API)                           │
│                                                             │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ Jitsi IFrame │  │ ParticipantAudio  │  │ useWebSocket  │  │
│  │ (8443 HTTPS) │  │ Receiver          │  │ (会议房间消息) │  │
│  │              │  │ (远程参会者音频)    │  │               │  │
│  └──────┬───────┘  └────────┬─────────┘  └──────┬────────┘  │
│         │ postMessage        │ WebSocket          │ WebSocket│
│         │ (Track 事件)       │ (audio_chunk)      │ (房间消息) │
└─────────┼───────────────────┼────────────────────┼──────────┘
          │                   │                    │
┌─────────▼─────────┐  ┌──────▼───────────────────▼──────────┐
│  Jitsi Docker      │  │  silan-asr-service (Python)          │
│  Web/Jicofo/JVB/   │  │                                      │
│  Prosody           │  │  ┌─────────────┐  ┌──────────────┐   │
│  JWT 鉴权(HS256)    │  │  │ WS 网关 8080 │  │ Flask 8082   │   │
│  8443/10000/5222   │  │  │  会议房间     │  │  HTTP API    │   │
└────────────────────┘  │  │  ASR 音频     │  │  Bot Spawn   │   │
                        │  └──────┬──────┘  └──────┬───────┘   │
                        │         │                │           │
                        │  ┌──────▼──────┐  ┌──────▼──────┐    │
                        │  │ ASR Worker  │  │ Meeting Agent│    │
                        │  │ Paraformer  │  │ Bot(Playwright│   │
                        │  │ SenseVoice  │  │ Headless铬)  │    │
                        │  └──────┬──────┘  └──────┬──────┘    │
                        │  ┌──────▼────────────────▼──────┐    │
                        │  │ TranscriptAggregator + Redis  │    │
                        │  └──────────────────────────────┘    │
                        └──────────────────────────────────────┘
```

---

## 二.5、为什么用 Docker 部署 Jitsi

Jitsi Meet 由 4 个独立服务组件组成，手动部署需要分别安装配置，依赖关系复杂：

| 组件 | 职责 | 手动部署的痛点 |
|---|---|---|
| Prosody (XMPP) | 身份认证 + 房间管理 + 消息路由 | 需手动配置 Lua 脚本、JWT 模块、MUC 组件 |
| Jicofo | 会议调度（分配 JVB、管理参与者） | 需配置 XMPP 连接、JVB 池 |
| JVB (Jitsi VideoBridge) | 媒体转发（WebRTC SFU） | 需配置 UDP 端口、ICE/STUN、DTLS 证书 |
| Jitsi Web | 前端页面 + BOSH/WebSocket 接入 | 需配置 Nginx 反代 + HTTPS 证书 |

**Docker 解决的问题**：

1. **一键编排** — `docker compose up -d` 自动拉起 4 个组件，按正确顺序启动和连接
2. **环境隔离** — 各组件在独立容器中运行，不污染宿主机（无需安装 Prosody/Nginx 等）
3. **版本一致** — 官方 Docker 镜像版本匹配，避免组件间版本不兼容
4. **配置统一** — 所有配置通过 `.env` + `docker-compose.yml` 管理，JWT 密钥、域名、端口集中配置
5. **SSL 证书简化** — 用 mkcert 生成自签证书挂载进容器，局域网内 HTTPS 即可工作
6. **IP 变更友好** — `start.sh` 检测局域网 IP 变化后自动更新 `.env` + 重新生成证书 + 重启容器

本项目的 `docker-compose.yml` 还集成了 JWT 鉴权配置（Prosody 加载 `jwt_auth` 模块），与后端共享 `JWT_APP_SECRET`，保证只有持有有效 Token 的用户才能加入会议。

---

## 三、前端技术方案

### 3.1 Jitsi IFrame 嵌入

前端通过 Jitsi Meet External API 将视频会议嵌入为 iframe，不直接渲染视频流，而是通过 `postMessage` 与 iframe 内的 Jitsi 客户端通信。

**加载流程**：
1. 动态加载 `https://{host}:8443/external_api.js`（`useJitsiApi.ts`）
2. 用 `new JitsiMeetExternalAPI(domain, options)` 创建 iframe
3. 通过 `executeCommand` / `addEventListener` 控制 会议

**关键事件监听**：
- `incomingMessage` / `outgoingMessage`：Jitsi 聊天消息
- `audioAdded` / `audioRemoved`：参会者音频轨道变化（核心 — 用于多参会者音频采集）
- `participantKickedOut` / `videoConferenceLeft`：会议退出
- `micMuteStatusChanged`：静音状态

**JWT 注入**：加入会议时传入后端签发的 JWT Token，Prosody 校验通过后才允许加入。

### 3.2 双 WebSocket 通道

前端同时维护两条 WebSocket 连接，职责分离：

| 连接 | 用途 | 端口 | 生命周期 |
|---|---|---|---|
| `useWebSocket` | 会议房间消息（聊天 / 转写 / AI 状态 / 同步） | 8080 | 加入会议后持续 |
| `audioCapture` / `ParticipantAudioReceiver` | ASR 音频上传（audio_chunk） | 8080 | 录制期间 |

两者连接同一个后端 WS 服务（`ws_server.py`），但通过不同的 `action` 消息分流：会议消息走 `join` / `chat` / `sync`，音频走 `create_session` / `audio_chunk`。

### 3.3 多参会者音频采集方案

这是系统的核心设计。音频采集分两条路径：

**路径 A：Meeting Agent Bot（当前主力方案）**

主持人点击「开启 AI 语音识别」后，后端 spawn 一个 Headless Chromium Bot（Playwright），Bot 以独立身份加入 Jitsi 会议，通过 `lib-jitsi-meet` 库接收所有参会者的音频轨道，将 PCM 数据通过 WebSocket 推送给后端 ASR 服务。

```
主持人点击「开启 AI」
  → POST /api/meetings/{room}/bot/spawn
  → BotManager 启动 Headless Chromium
  → Chromium 加载 recorder.html
  → recorder.html 用 lib-jitsi-meet 加入会议
  → 接收每个参会者的 audio track
  → PCM 16kHz → WebSocket → /ws/recorder/{meeting_id}
  → 后端 receiver.py → ingest → ASR Worker
```

**优势**：Bot 统一采集所有参会者音频（包括主持人自己），避免浏览器端重复采集和去重难题。所有音频走 `/ws/recorder/{meeting_id}` 通道，转写结果通过 `meeting_transcript` 事件广播给房间所有人。

**路径 B：浏览器端 ParticipantAudioReceiver（降级方案）**

当 Bot 方案不可用时，前端可通过 Jitsi IFrame API 的 `audioAdded` 事件拿到远程参会者的 `MediaStreamTrack`，用 `AudioContext` + `ScriptProcessorNode` 采集 PCM，转 base64 后通过独立 WebSocket 上传到后端。

> 注意：当前主力方案为路径 A（Meeting Agent Bot），路径 B 的代码保留但默认不启用。若同时使用两条路径会导致主持人语音被 Bot 和浏览器各采一遍，产生重复转写。

```
Jitsi IFrame → audioAdded 事件 → MediaStreamTrack
  → AudioContext (16kHz) → ScriptProcessor (4096 samples)
  → Float32 → PCM16 → base64
  → WebSocket audio_chunk → 后端 WS 网关
```

**静音处理**：`ParticipantAudioReceiver` 监听 `MediaStreamTrack` 的 `mute` / `unmute` 事件，参会者在 Jitsi 工具栏点静音时自动停止上传 `audio_chunk`，取消静音后恢复上传。

### 3.4 可拖动分割线布局

左侧 Jitsi IFrame 与右侧「会议纪要」Sidebar 之间有可拖动分割线：
- 鼠标按住分割线拖动 → 实时调整 Sidebar 宽度（320px ~ 720px）
- 拖动时给 IFrame 区域设置 `pointer-events: none`，防止鼠标事件被 iframe 吞没
- 松开鼠标恢复 iframe 交互

### 3.5 实时转写展示

会议纪要区域有两种实时状态：

| 状态 | 显示 | 触发条件 |
|---|---|---|
| 正在说话（SenseVoice） | 头像 + 说话人名 + 三点跳动动画 | 后端 `sv_processing` 信号（语音能量 ≥ 0.010） |
| 正在说（Paraformer） | 头像 + 说话人名 + 累积文本 | 后端 `transcript_partial` 消息 |
| 最终文本 | 消息列表中正式记录 | 后端 `transcript_final` 消息 |

多 Speaker 场景按 `participant_id` 聚合，头像列表展示所有说话人，点击可聚焦查看某个说话人的实时文本。

过期清理：`isProcessing` 状态超过 10s 无后续消息自动清除，防止停止录制/静音后残留。

---

## 四、前后端音频传递方案

### 4.1 音频格式

| 阶段 | 格式 | 采样率 | 声道 |
|---|---|---|---|
| 浏览器采集 | Float32 PCM | 16kHz | 单声道 |
| WebSocket 传输 | base64(PCM16) | 16kHz | 单声道 |
| 后端处理 | numpy float32 | 16kHz | 单声道 |
| ASR 输入 | numpy float32 | 16kHz | 单声道 |

浏览器端 `AudioContext` 设为 16kHz 采样率，`ScriptProcessorNode` 每 4096 samples（约 256ms）触发一次回调，`PCMConverter` 将 Float32 转为 Int16 PCM 再 base64 编码。

### 4.2 WebSocket 消息协议

**浏览器 → 后端**：
```json
{ "action": "audio_chunk", "session_id": "xxx", "participant_id": "xxx",
  "participant_name": "张三", "sample_rate": 16000, "audio": "<base64>", "timestamp": 1234567890 }
```

**Bot → 后端**（recorder WS）：
```json
{ "type": "audio_chunk", "meetingId": "xxx", "participantId": "xxx",
  "trackId": "xxx", "timestamp": 123, "sampleRate": 16000, "pcm": "<base64>" }
```

**后端 → 前端**：
```json
{ "type": "transcript_partial", "session_id": "xxx", "participant_id": "xxx",
  "participant_name": "张三", "text": "今天我们讨论", "is_processing": false }

{ "type": "transcript_final", "session_id": "xxx", "participant_id": "xxx",
  "participant_name": "张三", "text": "今天我们讨论一下上半年的市场情况。" }
```

### 4.3 信号链路

```
音频源 (Bot/浏览器)
  → WebSocket audio_chunk
  → ws_server._process_and_submit_audio()
  → AudioProcessor (Silero VAD 过滤静音帧)
  → ASRWorker.submit_audio()
  → Paraformer 流式识别 / SenseVoice 段批识别
  → TranscriptAggregator (累积 + 句尾检测 + 标点恢复)
  → transcript_partial / transcript_final
  → ws_server 广播到会议房间所有 WebSocket 客户端
  → useWebSocket → meeting_transcript / meeting_transcript_partial
  → App.tsx → Sidebar 渲染
```

---

## 五、多用户隔离方案

### 5.1 会议房间隔离

每个会议通过 `room_id`（房间名）隔离。后端 `ws_server.py` 维护：

```python
self._clients: Dict[ws_id, {ws, room_id, user_id}]  # 连接 → 房间映射
self._rooms: Dict[room_id, Set[ws_id>]              # 房间 → 连接集合
```

- WebSocket 连接时必须先 `join` 指定 `room_id`
- `create_session` 时强制使用 ws client 已 join 的 `room_id`（不信任前端传入的 `meeting_id`，防止串扰）
- 转写消息广播时只发给同一 `room_id` 的客户端

### 5.2 ASR 会话隔离

每个参会者的音频采集对应一个独立的 `session_id`：

```python
AudioSession:
  session_id: str        # 唯一标识
  meeting_id: str        # 所属会议
  participant_id: str    # 参会者 ID
  participant_name: str  # 显示名
  status: SessionStatus  # CREATED → STREAMING → CLOSED
```

- Paraformer 模式：每个 `session_id` 有独立的 `session_states`（模型缓存）
- SenseVoice 模式：每个 `session_id` 有独立的 `_sv_buffers`（音频累积 buffer）
- `TranscriptAggregator` 按 `session_id` 维护独立的 `UtteranceBuffer`

### 5.3 Bot 隔离

每个会议的 Meeting Agent Bot 有独立的 `bot_id`：
- `BotManager` 维护 `meeting_id → MeetingBot` 映射
- 每个 Bot 启动独立的 Headless Chromium 实例
- Bot 有独立的 `bot_token`（短期 JWT），与用户 JWT 分离
- kill Bot 时通过 `bot_id` 精确定位，不影响其他会议

### 5.4 JWT 鉴权

```
前端 → POST /api/dev/tokens {user, room, moderator}
后端 → 签发 HS256 JWT（iss=meeting-ai, aud=jitsi, sub=user, room=...）
前端 → Jitsi IFrame API jwt={token} 嵌入会议
Prosody → 校验 JWT → 允许加入房间
```

- 主持人 Token 含 `moderator: true`，只有主持人能开启/关闭 AI 语音识别
- Bot 有独立的 `bot_token`，权限受限
- Prosody 和后端共用 `JWT_APP_SECRET`，保证 Token 互认

---

## 六、服务端处理方案

### 6.1 双模型 ASR 架构

系统支持两个识别引擎，运行时按会议选择切换：

| 模型 | 架构 | 处理方式 | 延迟 | 准确率 | 适用场景 |
|---|---|---|---|---|---|
| Paraformer-zh-streaming | 非自回归流式 | 每 600ms chunk 推一次，实时出 partial | 低（~600ms） | CER 5.1% | 快速对话、实时字幕 |
| SenseVoice-Small | 非自回归段批 | 累积音频，静音 1.5s 后整段识别 | 较高（依句子长度） | CER 3.8% | 高准度纪要 |

**Paraformer 流式参数**：
```python
chunk_size = [0, 10, 5]              # 10 帧 = 600ms
encoder_chunk_look_back = 10         # 6s 上下文
decoder_chunk_look_back = 4          # 2.4s 上下文
```

**SenseVoice 段批参数**：
```python
SV_SILENCE_THRESHOLD = 0.025   # 静音 RMS 阈值
SV_SILENCE_DURATION = 1.5      # 静音超时触发识别（秒）
SV_MAX_BUFFER = 30.0           # buffer 上限强制截断（秒）
SV_SPEECH_THRESHOLD = 0.010    # 语音活动检测阈值（发 processing 信号）
SV_MIN_SEGMENT_ENERGY = 0.020  # 片段最低 RMS（过滤噪声）
```

**SenseVoice 防幻觉机制**：
1. 帧级语音占比检测：30ms 帧切片，语音帧占比 < 30% 的片段不送识别
2. 片段整体 RMS 校验：低于 0.020 的纯噪声段直接丢弃
3. 幻觉关键词黑名单：≤5 字命中"嗯对""出来""屁弟"等典型碎片直接过滤
4. 最短文本长度：去标点后 < 4 字的碎片丢弃
5. emoji 过滤：`rich_transcription_postprocess` 输出的情感 emoji 全部移除

### 6.2 TranscriptAggregator 聚合器

将 ASR 流式片段聚合成完整句子，核心算法：

**Paraformer 模式** — 最大后缀匹配：
```
partial: 今         → emitted: 今
partial: 天我们     → delta: 天我们,    emitted: 今天我们
partial: 讨论以     → delta: 讨论以,    emitted: 今天我们讨论以
...
is_final=True 或 silence_timeout(3s) → 推送 final，ct-punc 加标点
```

**SenseVoice 模式** — 段批直出：
- `sv_processing` 信号 → 前端显示"正在说话..."动画
- `sv_final_text` → 直接作为 final 推送（SenseVoice 自带标点，无需 ct-punc）

### 6.3 Meeting Agent Bot

主持人开启 AI 语音识别时，后端 spawn 一个 Headless Chromium Bot：

```
POST /api/meetings/{room}/bot/spawn
  → BotManager.create_bot()
  → BrowserController.launch()  (Playwright)
  → Chromium 加载 recorder.html
  → recorder.html 参数: meeting_id, room_url, bot_jwt, bot_token, ws_url
  → lib-jitsi-meet 加入会议
  → 接收所有参会者 audio track
  → PCM 16kHz → WebSocket /ws/recorder/{meeting_id}
  → receiver.py → gateway.ingest_bot_audio()
  → ASR Worker 识别
```

**生命周期**：
- Bot 状态存储在 Redis（`meeting_bot:{meeting_id}`，TTL 6h）
- 主持人点击「停止」→ POST `/bot/kill` → BotManager 停止 Chromium
- 前端同步调用 `ParticipantAudioReceiver.stopAll()` 停止浏览器端采集

### 6.4 AudioProcessor 后端音频预处理

`app/audio_processor/processor.py`，音频送 ASR 前的预处理管道：

| 步骤 | 说明 | 默认 |
|---|---|---|
| 重采样 | 非 16kHz → 线性插值降到 16kHz | 启用 |
| 声道转换 | 立体声 → 单声道（取均值） | 启用 |
| Silero VAD | 神经网络判断是否含人声，非语音帧丢弃不送 ASR | 启用（阈值 0.5） |
| AGC / 降噪 | 音量归一化 / noisereduce | 关闭（浏览器端已处理） |

Silero VAD 每个 session 有独立的 `VADIterator`（LSTM 有状态，需隔离）；加载失败时回退到能量阈值检测。

### 6.5 热词支持

Paraformer 模型支持热词注入（`worker.py._load_hotwords`）：
- 热词文件：`resources/vocab/semiconductor_vocab.txt`
- 启动时调用 `model.set_hotword(hotwords)` 注入
- SenseVoice 不支持热词（端到端模型无此接口）

### 6.6 会议纪要生成

```
主持人点击「总结会议」
  → POST /api/meetings/{room}/summary
  → meeting_state 拉取所有 final 转写
  → llm_service 按 prompt 拼装（含说话人 + 时间）
  → LLM 生成总结
  → Socket.IO 广播 meeting_summary
  → 所有客户端 → Sidebar 渲染纪要
```

### 6.7 Redis 状态持久化

| 键 | 内容 | TTL |
|---|---|---|
| `meeting:{room_id}:messages` | 会议消息列表（含转写） | 无 |
| `meeting:{room_id}:participants` | 参会者列表 | 无 |
| `meeting_bot:{meeting_id}` | Bot 状态 | 6h |
| `meeting:{room_id}:ai_bot` | AI Bot 开关状态 | 无 |
| `meeting:{room_id}:asr_model` | 选择的 ASR 模型 | 无 |

新加入会议的用户通过 `sync` 消息拉取增量历史（基于 `lastSeq`）。

---

## 七、运行

```bash
# 1. 启动 Jitsi（自动检测 IP + 重新生成证书）
cd jitsi/jitsi && ./start.sh

# 2. 启动后端
cd silan-asr-service
pip install -r requirements.txt
cp .env.example .env   # 填 JWT 密钥
python main.py --device cpu --port 8080 --host 0.0.0.0

# 3. 启动前端
cd frontend && npm install && npm run dev
# 浏览器打开 https://localhost:3000
```

> `./start.sh` 会自动检测局域网 IP，当 IP 变化时自动更新 `.env`、重新生成 SSL 证书并重启容器。

---

## 八、端口与依赖

| 端口 | 用途 |
|---|---|
| 8443 | Jitsi Web（HTTPS，mkcert 自签证书） |
| 3000 | Vite 前端开发服务器（HTTPS，mkcert 自签证书） |
| 8080 | 后端 WebSocket（会议房间 + ASR 音频 + Bot recorder） |
| 8082 | 后端 Flask HTTP（API / 健康检查） |
| 10000/UDP | Jitsi JVB 媒体流 |
| 5222 | Prosody XMPP |
| 6379 | Redis（状态持久化） |

**后端 Python 依赖**：funasr / torch / torchaudio / numpy / flask / flask-socketio / websockets / playwright / redis

**前端依赖**：React 18 / TypeScript / Vite 5 / mkcert（自签证书）
