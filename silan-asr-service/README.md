# SiLAN FunASR 实时会议转写服务

基于 FunASR 的实时语音识别服务，支持 WebSocket 协议，适用于会议实时字幕、语音转写等场景。

## 特性

- 🎙️ **实时流式 ASR** - 基于 FunASR Paraformer 模型的流式识别
- 🌐 **WebSocket 协议** - 支持浏览器原生 WebSocket 连接
- 🔄 **多会话并发** - 支持多个用户同时进行音频转写
- 🎯 **行业术语增强** - 内置半导体行业热词库
- 🔍 **音频预处理** - 自动重采样、降噪、VAD 语音检测
- ⚡ **批处理优化** - Batch Scheduler 提升推理效率

## 快速开始

### 环境要求

- Python 3.8+
- 支持 CPU 或 CUDA 的 Python 环境

### 安装

```bash
cd silan-asr-service
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 启动服务

```bash
# 使用默认配置启动
python main.py

# 自定义端口和设备
python main.py --port 50051 --device cpu

# 生产环境 (建议)
python main.py --host 0.0.0.0 --port 50051 --log-level INFO
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | 50051 | 服务端口号 |
| `--host` | 0.0.0.0 | 服务监听地址 |
| `--device` | cpu | 推理设备 (cpu/cuda) |
| `--log-level` | INFO | 日志级别 |

## API 协议

### WebSocket 事件

#### 客户端 → 服务端

| 事件名 | 参数 | 说明 |
|--------|------|------|
| `create_session` | `meeting_id`, `participant_id`, `participant_name` | 创建新会话 |
| `audio_chunk` | `session_id`, `audio`(base64), `sample_rate` | 发送音频数据块 |
| `end_session` | `session_id` | 结束当前会话 |

#### 服务端 → 客户端

| 事件名 | 参数 | 说明 |
|--------|------|------|
| `connected` | `client_id` | 连接成功 |
| `session_created` | `session_id`, `meeting_id`, `status` | 会话创建成功 |
| `audio_received` | `session_id`, `status` | 音频接收确认 |
| `transcript` | `session_id`, `interim_text`/`final_text`, `is_final` | 转写结果 |
| `session_finalized` | `session_id`, `finalized` | 会话结束确认 |
| `error` | `message` | 错误信息 |

### 客户端示例

```javascript
const socket = io('http://localhost:50051');

// 创建会话
socket.emit('create_session', {
    meeting_id: 'meeting_001',
    participant_id: 'user_001',
    participant_name: '张三'
});

// 发送音频 (每200ms发送一次)
socket.emit('audio_chunk', {
    session_id: sessionId,
    audio: base64AudioData,
    sample_rate: 16000
});

// 接收转写结果
socket.on('transcript', (data) => {
    console.log('转写结果:', data.interim_text);
});

// 结束会话
socket.emit('end_session', { session_id: sessionId });
```

### Python 客户端示例

```python
import socketio
import base64
import numpy as np

sio = socketio.Client()

@sio.on('connect')
def on_connect():
    sio.emit('create_session', {
        'meeting_id': 'meeting_001',
        'participant_id': 'user_001',
        'participant_name': '测试用户'
    })

@sio.on('transcript')
def on_transcript(data):
    print(f"转写: {data['interim_text']}")

# 发送音频
audio = np.sin(2 * np.pi * 440 * np.linspace(0, 0.96, 9600))
audio_base64 = base64.b64encode(audio.tobytes()).decode()
sio.emit('audio_chunk', {
    'session_id': session_id,
    'audio': audio_base64,
    'sample_rate': 16000
})

sio.connect('http://localhost:50051')
```

## 项目结构

```
silan-asr-service/
├── app/
│   ├── asr_worker/          # ASR 推理 Worker
│   │   └── worker.py            # 核心推理逻辑、批处理调度
│   ├── audio_gateway/       # WebSocket 网关
│   │   └── ws_server.py         # WebSocket 服务器实现
│   ├── audio_processor/     # 音频预处理
│   │   └── processor.py         # 重采样、降噪、VAD
│   ├── config/              # 配置管理
│   │   └── settings.py          # 全局配置
│   ├── normalization/       # 文本归一化
│   │   └── service.py           # 行业术语纠正
│   ├── session_manager/     # 会话管理
│   │   ├── manager.py           # 会话生命周期管理
│   │   └── session.py           # 会话数据结构
│   └── transcript_service/  # 转写服务
│       └── service.py           # 转写结果处理与分发
├── resources/
│   └── vocab/
│       └── semiconductor_vocab.txt  # 半导体行业热词库
├── main.py                  # 服务入口
├── requirements.txt        # Python 依赖
├── .env.example             # 环境变量模板
└── .gitignore
```

## 音频格式要求

- **采样率**: 16000 Hz (其他采样率会自动重采样)
- **位深度**: 16-bit PCM (float32)
- **通道数**: 单声道 (多声道会自动转换)
- **编码格式**: base64 编码的原始 PCM 数据

## 性能优化

1. **批处理调度**: 多个音频块会被合并为一次模型推理
2. **会话缓存**: 每个会话维护独立的流式状态
3. **异步广播**: 转写结果通过 eventlet 协程异步推送

## 故障排查

### 模型加载失败
```bash
# 检查 CUDA 可用性
python -c "import torch; print(torch.cuda.is_available())"

# 强制使用 CPU
python main.py --device cpu
```

### 端口被占用
```bash
# 查看端口占用
lsof -i :50051

# 停止占用进程
kill -9 <PID>
```

### 内存不足
```bash
# 降低批处理大小
ASR_MAX_BATCH_SIZE=16 python main.py
```

## 许可证

SiLAN 内部使用
