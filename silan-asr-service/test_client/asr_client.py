"""ASR 测试客户端公共工具

提供：
  - 加载 wav 文件并转换为 16kHz mono float32
  - 异步 WebSocket 客户端（与前端 audioCapture.ts 协议一致）
  - transcript_partial / transcript_final 收集
  - 延迟统计
"""

import asyncio
import base64
import json
import ssl
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed


def load_wav_as_float32(path: str, target_sr: int = 16000) -> np.ndarray:
    """读取 wav 文件并转换为目标采样率 mono float32

    支持：
      - 任意采样率（自动重采样到 target_sr）
      - 任意通道数（自动转 mono）
      - 16-bit PCM / 32-bit float wav
    """
    import wave

    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # 解码
    if sample_width == 2:  # int16
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:  # float32
        audio = np.frombuffer(raw, dtype=np.float32)
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")

    # 转 mono
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    # 重采样（如果需要）
    if sr != target_sr:
        # 简单线性重采样（避免引入 scipy 依赖）
        duration = len(audio) / sr
        new_len = int(duration * target_sr)
        audio = np.interp(
            np.linspace(0, len(audio), new_len, endpoint=False),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)

    return audio


@dataclass
class Transcript:
    type: str            # "partial" | "final"
    text: str
    send_time_ms: int    # 发送这个音频帧的时间
    recv_time_ms: int    # 收到结果的时间
    latency_ms: int      # 延迟


@dataclass
class TestResult:
    session_id: str = ""
    transcripts: List[Transcript] = field(default_factory=list)
    first_send_time: Optional[int] = None
    last_send_time: Optional[int] = None
    error: Optional[str] = None


class ASRClient:
    """模拟前端 audioCapture.ts 的 WebSocket 客户端

    协议：
      - create_session: { action, session_id, meeting_id, participant_id, participant_name, sample_rate }
      - audio_chunk:    { action, session_id, audio (base64 float32 PCM), sample_rate }
      - end_session:    { action, session_id }

      服务端推送：
      - transcript_partial: { type, text, ... }
      - transcript_final:   { type, text, start_time, end_time, ... }
    """

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:19087",
        meeting_id: str = "test-meeting",
        participant_id: str = "test-user",
        participant_name: str = "测试用户",
        sample_rate: int = 16000,
        chunk_ms: int = 100,  # 每块 100ms
    ):
        self.ws_url = ws_url
        self.meeting_id = meeting_id
        self.participant_id = participant_id
        self.participant_name = participant_name
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.chunk_samples = int(sample_rate * chunk_ms / 1000)

        self.session_id: Optional[str] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.result = TestResult()
        self._send_timestamps: List[int] = []
        self._recv_task: Optional[asyncio.Task] = None

    def make_ssl_context(self) -> Optional[ssl.SSLContext]:
        """如果 wss:// 跳过证书校验"""
        if not self.ws_url.startswith("wss://"):
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def connect(self):
        ssl_ctx = self.make_ssl_context()
        self.ws = await websockets.connect(
            self.ws_url, max_size=10 * 1024 * 1024, ssl=ssl_ctx,
        )
        # 创建 session
        self.session_id = f"test-{int(time.time() * 1000)}"
        await self.ws.send(json.dumps({
            "action": "create_session",
            "session_id": self.session_id,
            "meeting_id": self.meeting_id,
            "participant_id": self.participant_id,
            "participant_name": self.participant_name,
            "sample_rate": self.sample_rate,
        }))
        # 等 session_created
        for _ in range(5):
            msg = await asyncio.wait_for(self.ws.recv(), timeout=3)
            data = json.loads(msg)
            if data.get("type") == "session_created":
                self.result.session_id = self.session_id
                print(f"✅ Session created: {self.session_id}")
                # 启动后台接收任务
                self._recv_task = asyncio.create_task(self._recv_loop())
                return
            elif data.get("type") == "error":
                raise RuntimeError(f"Server error: {data.get('message')}")
        raise RuntimeError("No session_created response")

    async def _recv_loop(self):
        """后台循环：收集 partial/final 消息"""
        try:
            async for msg in self.ws:
                recv_ms = int(time.time() * 1000)
                try:
                    data = json.loads(msg)
                except (json.JSONDecodeError, TypeError):
                    continue
                msg_type = data.get("type")
                if msg_type not in ("transcript_partial", "transcript_final"):
                    continue
                # 找到匹配的发送时间戳（按累计发送字节数估算）
                text = data.get("text", "")
                # 用最后一帧发送时间作为参考
                ref_send = self._send_timestamps[-1] if self._send_timestamps else recv_ms
                latency = recv_ms - ref_send
                self.result.transcripts.append(Transcript(
                    type="partial" if msg_type == "transcript_partial" else "final",
                    text=text,
                    send_time_ms=ref_send,
                    recv_time_ms=recv_ms,
                    latency_ms=latency,
                ))
                emoji = "🔵" if msg_type == "transcript_partial" else "🟢"
                print(f"  {emoji} [{latency:>4}ms] {msg_type:18s} | {text}")
        except ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.result.error = str(e)

    async def send_chunk(self, pcm: np.ndarray):
        """发送一个 16kHz mono float32 块（base64 编码）"""
        if not self.ws or self.ws.state.name != "OPEN":
            return
        chunk_ms = int(time.time() * 1000)
        self._send_timestamps.append(chunk_ms)
        if self.result.first_send_time is None:
            self.result.first_send_time = chunk_ms
        self.result.last_send_time = chunk_ms

        audio_bytes = pcm.astype(np.float32).tobytes()
        await self.ws.send(json.dumps({
            "action": "audio_chunk",
            "session_id": self.session_id,
            "audio": base64.b64encode(audio_bytes).decode(),
            "sample_rate": self.sample_rate,
        }))

    async def end(self):
        """结束 session（保留 3.5s 等 silence_timeout 触发 final）"""
        if self.ws and self.ws.state.name == "OPEN":
            await self.ws.send(json.dumps({
                "action": "end_session",
                "session_id": self.session_id,
            }))
        # 等 final 触发（silence_timeout=3s + 一点缓冲）
        await asyncio.sleep(3.5)
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self.ws and self.ws.state.name == "OPEN":
            await self.ws.close()

    def print_summary(self):
        """打印测试结果统计"""
        print()
        print("=" * 70)
        print(f"📊 测试结果汇总 (session={self.result.session_id})")
        print("=" * 70)
        finals = [t for t in self.result.transcripts if t.type == "final"]
        partials = [t for t in self.result.transcripts if t.type == "partial"]

        print(f"  Partial 消息: {len(partials)}")
        print(f"  Final   消息: {len(finals)}")
        if finals:
            print()
            print("  Final 文本：")
            for t in finals:
                print(f"    [{t.latency_ms:>5}ms] {t.text}")
        if partials:
            latencies = [p.latency_ms for p in partials]
            print()
            print(f"  Partial 延迟：min={min(latencies)}ms, "
                  f"max={max(latencies)}ms, "
                  f"avg={sum(latencies) // len(latencies)}ms")
        if self.result.error:
            print(f"\n  ❌ 错误：{self.result.error}")
        print("=" * 70)
