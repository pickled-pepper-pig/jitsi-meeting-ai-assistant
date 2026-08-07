# ASR 测试客户端

模拟前端 `audioCapture.ts` 协议，把本地音频流式发送到 ASR 服务，验证：
- 模型识别能力
- 流式 partial/final 合并逻辑
- WebSocket 传输延迟
- 文本去重（aggregator merge）

## 工具列表

| 脚本 | 用途 |
|---|---|
| `gen_test_audio.py` | 用 TTS 生成测试音频（macOS say / edge-tts） |
| `wav_stream_client.py` | 实时流式发送 wav，观察 partial/final |
| `eval_wav.py` | **评估 ASR 识别质量**（CER/WER） |

## 快速开始

### 1. 准备测试音频

如果有 wav（自己的录音），跳过这一步。

否则生成：

```bash
# macOS TTS（英文效果好，中文只能蹦单字）
python -m test_client.gen_test_audio

# 微软 Azure TTS（推荐，中英文都好）
pip install edge-tts
python -m test_client.gen_test_audio --engine edge
```

### 2. 启动 ASR 服务

```bash
python main.py --device cpu --port 8087 --host 0.0.0.0
```

### 3. 评估识别质量

**模式 1：只跑识别、看结果**

```bash
python -m test_client.eval_wav --wav test_audio/short_greeting.wav
```

输出：
```
📄 short_greeting.wav
   时长: 1.96s, 振幅: 0.772
   Partial: 2, Final: 1
   识别文本: 你好，我们开始吧。
```

**模式 2：有 ground truth 算 CER/WER**

```bash
python -m test_client.eval_wav \
  --wav test_audio/short_greeting.wav \
  --gt "你好，我们开始吧。"
```

输出：
```
📄 short_greeting.wav
   识别文本: 你好，我们开始吧。
   原始文本: 你好，我们开始吧。
   📊 CER: 0.0%, WER: 0.0%
   🟢 优秀
```

**模式 3：批量评估（回归测试）**

准备 manifest.jsonl：
```jsonl
{"wav": "test_audio/short_greeting.wav", "gt": "你好，我们开始吧。"}
{"wav": "test_audio/long_sentence.wav", "gt": "今天我们讨论一下半导体行业的最新发展。..."}
{"wav": "test_audio/with_pauses.wav", "gt": "我觉得这个方案，需要重新设计。"}
```

跑：
```bash
python -m test_client.eval_wav --batch test_audio/manifest.jsonl
```

汇总输出：
```
📊 批量汇总 (3 个有效样本)
   平均 CER: 8.3%
   平均 WER: 8.3%
   🟡 良好
```

### 4. 实时观察流式过程

```bash
# 半速播放，方便观察 partial 累积
python -m test_client.wav_stream_client --wav test_audio/long_sentence.wav --speed 0.5
```

输出：
```
🔵 [  52ms] transcript_partial | 你好
🔵 [  55ms] transcript_partial | 你好，
🔵 [  60ms] transcript_partial | 你好，我们
🟢 [3520ms] transcript_final   | 你好，我们开始吧。
```

## 关键指标

| 指标 | 优秀 | 可接受 | 异常 |
|---|---|---|---|
| CER（字符错误率） | < 5% | < 15% | > 30% |
| Partial 延迟 | < 500ms | < 800ms | > 1500ms |
| Final 延迟 | < 4s | < 6s | > 10s |
| Final 完整度 | 完整句+标点 | 完整句无标点 | 截断/重复 |

## 调参

`ws_server.py` 中：
```python
self.transcript_aggregator = TranscriptAggregator(
    silence_timeout_ms=3000,   # 静音超时（句尾判断）
    max_utterance_duration_s=60.0,  # 单句最大时长
    punc_model=self.asr_worker.punc_model,  # 标点模型
)
```

调小 silence_timeout → final 切分更频繁（适合快速响应）
调大 silence_timeout → final 切分更少（适合长会议）

## 多说话人模拟

```python
# multi_user_test.py (待实现)
import asyncio
from test_client.asr_client import ASRClient

async def simulate_user(user_id, wav_path):
    client = ASRClient(
        ws_url="ws://127.0.0.1:8087",
        meeting_id="multi-test",
        participant_id=user_id,
        participant_name=f"用户{user_id}",
    )
    await client.connect()
    audio = load_wav_as_float32(wav_path)
    for i in range(0, len(audio), 1600):
        await client.send_chunk(audio[i:i+1600])
        await asyncio.sleep(0.1)
    await client.end()

async def main():
    await asyncio.gather(
        simulate_user("user1", "user1.wav"),
        simulate_user("user2", "user2.wav"),
    )

asyncio.run(main())
```
