# Jitsi 会议 AI 助手 - 技术文档

> 局域网自部署的 Jitsi Meet 视频会议 + 实时语音转写 + 会议纪要 一体化系统。

## 一、项目结构

```
jitsi/
├── jitsi/                    # Jitsi Meet（Docker Compose）
│   ├── docker-compose.yml    # 编排 Web / Jicofo / JVB / Prosody
│   ├── jitsi-meet-cfg/       # 各组件配置 + JWT 鉴权
│   └── .env                  # 局域网 IP / 鉴权开关
│
├── silan-asr-service/        # 后端 ASR + 会议服务（Python）
│   ├── main.py               # 启动入口（Flask HTTP + WebSocket）
│   ├── app/
│   │   ├── audio_gateway/    # WS 网关 + 转写聚合器
│   │   ├── asr_worker/       # FunASR 流式识别
│   │   ├── audio_processor/  # 重采样 / VAD / 降噪
│   │   ├── meeting_ws/       # Socket.IO 房间广播
│   │   ├── meeting_state/    # 会议状态（Redis）
│   │   ├── transcript_service/ # 转写持久化
│   │   ├── llm_service/      # 会议纪要生成
│   │   ├── auth/             # JWT 鉴权（HS256）
│   │   └── api_routes/       # HTTP API（token / 健康检查）
│   └── test_client/          # wav 流式回放测试工具
│
└── frontend/                 # 前端（React + TS + Vite）
    └── src/
        ├── App.tsx           # 主页（加入会议 + 录制控制）
        ├── components/       # Jitsi IFrame / Sidebar / 总结按钮
        ├── hooks/            # useWebSocket / useJitsiApi
        └── services/         # audioCapture（麦克风→WS）
```

## 二、整体架构

```
┌─────────────────────────────────────────────────────┐
│   浏览器 (React + Jitsi IFrame API)                 │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │ Jitsi Web  │  │ 麦克风采集  │  │ Socket.IO 客户端│  │
│  └─────┬──────┘  └─────┬──────┘  └──────┬────────┘  │
└────────┼───────────────┼────────────────┼───────────┘
         │ HTTPS         │ WebSocket      │ Socket.IO
         │ (8443)        │ (8080)         │ (8082)
┌────────▼───────────────▼────────────────▼───────────┐
│  Docker Compose: Jitsi Meet                         │
│  - Web (8443) / Jicofo / JVB (10000) / Prosody      │
│  - JWT 鉴权 (HS256)                                 │
└──────────────────────┬──────────────────────────────┘
                       │ 音频流
┌──────────────────────▼──────────────────────────────┐
│  silan-asr-service (Python)                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │ WS 网关  │→│ VAD/重采样│→│FunASR    │→│ 聚合器  │  │
│  │ 8080     │ │          │ │paraformer│ │ 加标点  │  │
│  └────┬─────┘ └──────────┘ └──────────┘ └────┬───┘  │
│       │                                       │      │
│  ┌────▼─────┐  ┌──────────┐  ┌────────────┐  │      │
│  │ Redis    │  │ LLM 服务  │  │ Socket.IO  │◄─┘      │
│  │ 状态持久化│  │ 纪要生成  │  │ 房间广播   │         │
│  └──────────┘  └──────────┘  └──────────┘         │
└────────────────────────────────────────────────────┘
```

## 三、技术选型

| 层 | 技术 | 说明 |
|---|---|---|
| 视频会议 | Jitsi Meet（Docker） | Web 8443 / JVB 10000 UDP / Prosody 5222 |
| 鉴权 | JWT HS256 共享密钥 | Prosody + 后端共用 `JWT_APP_SECRET` |
| 前端 | React 18 + TypeScript + Vite 5 | `localhost+3` 自签证书（HTTPS） |
| 前端-Jitsi | iframe API + postMessage | `<script src="external_api.js">` |
| 前端-AI | `getUserMedia` + AudioContext | 16kHz mono float32, ScriptProcessor 切片 |
| 后端 WS | Python `websockets` | 8080 端口，协议与前端 audioCapture 对齐 |
| 后端 HTTP | Flask + flask-socketio | 8082 端口，提供 token / 总结 / 健康检查 |
| 语音识别 | FunASR `paraformer-zh-streaming` | 阿里达摩院流式模型，10 帧 chunk + 6s look-back |
| 标点恢复 | FunASR `ct-punc` | CT-Transformer，final 文本加句号/逗号 |
| 状态 | Redis 7 | 会议消息 / 参与者 / 转写持久化 |
| 总结 | LLM（可插拔） | 主持人点击"总结会议"触发 |

## 四、关键链路

### 1. 加入会议

```
前端 → POST /api/dev/tokens {user, room, moderator}
后端 → 签发 HS256 JWT（iss=meeting-ai, aud=jitsi, sub=user, room=...）
前端 → Jitsi IFrame API jwt={token} 嵌入会议
Prosody → 校验 JWT → 允许加入房间
```

### 2. 实时语音转写

```
浏览器麦克风 (16kHz mono PCM)
  ↓ getUserMedia
ScriptProcessor (4096 samples / 块)
  ↓ AudioContext
WebSocket 8080 / audio_chunk { audio: base64(f32) }
  ↓ 每 25s ping 一次保活
后端 WS 网关
  ↓ 鉴权 + 音频预处理（重采样 / VAD / 降噪）
ASR Worker → FunASR 流式识别
  ↓ partial / is_final
TranscriptAggregator（去重 + 累积 + 标点）
  ↓
WebSocket 推送 transcript_partial / transcript_final
  ↓
前端 → 实时显示 partial、final 落入"会议纪要"列表
```

### 3. 会议纪要

```
主持人点击「总结会议」
  ↓ POST /api/meetings/{room}/summary
后端 → 从 meeting_state 拉取所有 final 转写
  ↓
LLM 服务（按角色 prompt 拼装）
  ↓
Socket.IO 广播 meeting_summary { roomId, summary }
  ↓
所有客户端 → 纪要渲染到 Sidebar
```

## 五、核心实现要点

### 5.1 FunASR 流式识别参数

`app/asr_worker/worker.py`：

```python
self.chunk_size = [0, 10, 5]              # 10 帧 = 600ms
self.encoder_chunk_look_back = 10         # 6s 上下文
self.decoder_chunk_look_back = 4          # 2.4s 上下文
```

每 100ms 推一个 audio_chunk，FunASR 内部累积到 600ms 才输出一次 partial（保证识别准确率的同时压低延迟）。

### 5.2 流式 partial 累积算法

FunASR 每次返回的 `text` 是"最近窗口"，不是累积全文。`TranscriptAggregator` 用最大后缀匹配提取 delta，拼接成已发出全文：

```
partial: 今         → emitted: 今
partial: 天我们     → delta: 天我们,    emitted: 今天我们
partial: 讨论以     → delta: 讨论以,    emitted: 今天我们讨论以
...
partial: 的市场     → delta: 的市场,    emitted: 今天我们讨论...的市场
```

`is_final=True` 或 silence_timeout(3s) / max_duration(60s) 触发 final 推送，ct-punc 标点。

### 5.3 WebSocket 断线保活

- 前端 `useWebSocket` hook：指数退避重连 `1s → 2s → 4s → 8s → 16s → 30s`
- 重连后用 `lastSeq` 拉取增量消息
- 后端 WS 网关每 25s 一次 ping，前端 30s 一次 pong
- AudioCapture 断开时停止 `audioChunks` 计数 + 状态切回 idle

### 5.4 JWT 鉴权

`app/auth/__init__.py` 支持 HS256 / RS256 双模式（环境变量切换）：

```python
JWT_ALGORITHM=HS256          # 默认
JWT_SHARED_SECRET=xxxxx      # 共享密钥
JWT_ACCEPTED_ISSUERS=meeting-ai
JWT_ACCEPTED_AUDIENCES=jitsi
```

Prosody 侧配置 `JWT_APP_ID` / `JWT_APP_SECRET` 与后端完全一致。

### 5.5 测试工具

`silan-asr-service/test_client/`：

```bash
# 生成测试音频（macOS TTS / edge-tts）
python -m test_client.gen_test_audio --engine edge

# 流式回放 wav 模拟真实会议
python -m test_client.wav_stream_client --wav test_audio/short_greeting.wav

# 评估识别质量（CER / WER）
python -m test_client.eval_wav --wav test_audio/short_greeting.wav \
  --gt "你好，我们开始。"
```

## 六、运行

```bash
# 1. 启动 Jitsi
cd jitsi && docker compose up -d

# 2. 启动后端
cd silan-asr-service
pip install -r requirements.txt
cp .env.example .env   # 填 JWT 密钥
python main.py --device cpu --port 8080 --host 0.0.0.0

# 3. 启动前端
cd frontend && npm install && npm run dev
# 浏览器打开 https://localhost:3000
```

## 七、端口与依赖

| 端口 | 用途 |
|---|---|
| 8443 | Jitsi Web（HTTPS） |
| 3000 | Vite 前端（开发） |
| 8080 | 后端 WebSocket（ASR 音频） |
| 8082 | 后端 HTTP（API / Socket.IO） |
| 10000/UDP | Jitsi JVB 媒体 |
| 5222 | Prosody XMPP |

后端 Python 依赖：funasr / torch / torchaudio / numpy / flask / flask-socketio / eventlet / websockets。
