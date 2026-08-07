#!/usr/bin/env python3
"""
并发压测脚本：模拟 N 个参会者同时进入会议 + 同时喂数据，测试服务端 ASR 并发处理能力。

用法：
  python tools/stress_test.py --speakers 4 --duration 30 --room stress

参数：
  --speakers   并发参会者数量（默认 4）
  --duration   每个参会者持续喂音频的秒数（默认 30）
  --room       房间 ID（默认 stress）
  --server     WS 服务器 URL（默认 ws://localhost:19087）
  --token      JWT token（必填，会自动申请，无需手动传）

测试内容：
  - N 个 ws 并行连接
  - 每个 ws 走完整流程：join → create_session → 持续 audio_chunk
  - 服务端处理每个 audio_chunk 的延迟（看 wsLoopLagMs）
  - 转写结果的速率（partial/final 数量）
  - 内存和 CPU 占用（通过 /health 拿 wsLoopLagMs）

输出：
  每 5 秒打印各 speaker 状态 + 服务端状态
  结束时打印汇总：总 chunk 数、平均 RTT、转写数
"""

import asyncio
import base64
import json
import math
import struct
import time
import argparse
import urllib.request
import wave
import os
from typing import Optional

try:
    import websockets
except ImportError:
    raise SystemExit("需要 websockets: pip install websockets")


def http_post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))


def http_get(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode('utf-8'))


def make_test_pcm_float32(samples: int = 4096, freq: float = 440.0, sr: int = 16000) -> bytes:
    """生成正弦波 Float32 PCM（模拟语音信号）"""
    # Float32 PCM：[-1.0, 1.0]
    pts = []
    for i in range(samples):
        t = i / sr
        # 440Hz 正弦波 + 缓慢振幅调制，制造类似语音的起伏
        amp = 0.3 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.5 * t))
        v = amp * math.sin(2 * math.pi * freq * t)
        pts.append(v)
    return struct.pack(f'{samples}f', *pts)


# 默认使用的真实语音样本（项目自带）
DEFAULT_WAV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'test_audio', 'long_sentence.wav',
)


def load_wav_pcm_float32(path: str, target_sr: int = 16000) -> bytes:
    """从 WAV 读取 PCM，转成 Float32 LE。
    支持 8/16/32-bit PCM 或 Float32 WAV。自动 resample 到 target_sr（仅支持 /2 整数倍）。
    返回：Float32 LE bytes。
    """
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        n = wf.getnframes()
        raw = wf.readframes(n)
    # 解码为 int16/float
    if sw == 2:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        # 可能是 int32 或 float32，看是否在 [-1, 1]
        arr_i32 = np.frombuffer(raw, dtype=np.int32)
        if np.nanmax(np.abs(arr_i32)) > 2 ** 20:
            arr = arr_i32.astype(np.float32) / (2 ** 31 - 1)
        else:
            arr = np.frombuffer(raw, dtype=np.float32)
    elif sw == 1:
        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        raise ValueError(f'Unsupported sample width: {sw}')
    if nch > 1:
        arr = arr[::nch]
    # 简单 downsample（线性）
    if sr != target_sr:
        if sr % target_sr == 0:
            step = sr // target_sr
            arr = arr[::step]
        else:
            # 用 numpy 线性插值
            idx_old = np.linspace(0, len(arr) - 1, int(len(arr) * target_sr / sr))
            idx_old = idx_old.astype(np.int32)
            arr = arr[idx_old]
    return arr.tobytes()


import numpy as np  # noqa: E402  (放后面，减少初始化开销)


class SpeakerClient:
    def __init__(self, idx: int, room: str, server: str, token: str):
        self.idx = idx
        self.name = f'stress-speaker-{idx}'
        self.room = room
        self.server = server
        self.token = token
        self.session_id = f'stress-session-{int(time.time()*1000)}-{idx}'
        self.ws: Optional[object] = None
        self.chunks_sent = 0
        self.partials_received = 0
        self.finals_received = 0
        self.last_recv_ts = 0
        self.connected_at = 0

    async def connect(self) -> bool:
        import websockets
        try:
            self.ws = await websockets.connect(self.server, max_size=2**24)
            self.connected_at = time.time()
            # 1. join
            await self.ws.send(json.dumps({
                'action': 'join',
                'roomId': self.room,
                'token': self.token,
            }))
            # 2. 等 join 完成（监听任意响应即可，不强制 type）
            try:
                await asyncio.wait_for(self.ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                print(f'[{self.name}] join 超时')
                return False
            # 3. create_session
            await self.ws.send(json.dumps({
                'action': 'create_session',
                'session_id': self.session_id,
                'meeting_id': self.room,
                'participant_id': f'stress-{self.idx}',
                'participant_name': self.name,
                'token': self.token,
            }))
            # 等待 session_created（可能夹杂 broadcast 的 ai_bot_status，跳过）
            deadline = time.time() + 5
            got = False
            while time.time() < deadline:
                try:
                    r = await asyncio.wait_for(self.ws.recv(), timeout=2)
                    d = json.loads(r)
                    if d.get('type') == 'session_created':
                        got = True
                        break
                except asyncio.TimeoutError:
                    continue
            if not got:
                print(f'[{self.name}] create_session 超时未收到 session_created')
                return False
            return True
        except Exception as e:
            print(f'[{self.name}] 连接失败: {e}')
            return False

    async def feed_audio(self, duration_s: int, sample_rate: int = 16000, chunk_samples: int = 4096, audio_bytes: bytes = None):
        """以 chunk_samples 为单位按真实时间喂 PCM。
        若提供 audio_bytes（Float32 LE PCM），则从中切片循环喂；否则合成正弦波。"""
        # 真实时间发送：16kHz × 4096 samples = 256ms 每 chunk
        interval = chunk_samples / sample_rate
        if audio_bytes:
            samples_arr = np.frombuffer(audio_bytes, dtype=np.float32)
            # 切片并循环到足够长度
            if len(samples_arr) < chunk_samples * 4:
                reps = (chunk_samples * 4 + len(samples_arr) - 1) // len(samples_arr)
                samples_arr = np.tile(samples_arr, reps)
        else:
            samples_arr = np.frombuffer(make_test_pcm_float32(chunk_samples, sr=sample_rate), dtype=np.float32)

        end_time = time.time() + duration_s
        offset = 0
        while time.time() < end_time:
            if not self.ws:
                break
            # 兼容新旧 websockets API
            try:
                closed = self.ws.closed if hasattr(self.ws, 'closed') else (not self.ws.open)
            except Exception:
                closed = False
            if closed:
                break
            # 切下一个 chunk（循环复用音频源）
            chunk = samples_arr[offset:offset + chunk_samples]
            if len(chunk) < chunk_samples:
                # 回绕补齐
                chunk = np.concatenate([chunk, samples_arr[:chunk_samples - len(chunk)]])
            offset = (offset + chunk_samples) % len(samples_arr)
            pcm_b64 = base64.b64encode(chunk.tobytes()).decode('ascii')
            try:
                await self.ws.send(json.dumps({
                    'action': 'audio_chunk',
                    'session_id': self.session_id,
                    'audio': pcm_b64,
                    'sample_rate': sample_rate,
                }))
                self.chunks_sent += 1
            except Exception as e:
                print(f'[{self.name}] send 失败: {e}')
                break
            await asyncio.sleep(interval)

    async def recv_loop(self):
        """后台接收消息，统计 partial/final"""
        try:
            while True:
                if not self.ws:
                    break
                try:
                    closed = self.ws.closed if hasattr(self.ws, 'closed') else (not self.ws.open)
                except Exception:
                    closed = False
                if closed:
                    break
                try:
                    r = await asyncio.wait_for(self.ws.recv(), timeout=1)
                    self.last_recv_ts = time.time()
                    d = json.loads(r)
                    t = d.get('type', '')
                    if t == 'transcript_partial':
                        self.partials_received += 1
                    elif t == 'transcript_final':
                        self.finals_received += 1
                except asyncio.TimeoutError:
                    continue
        except Exception:
            pass

    async def close(self):
        if self.ws:
            try:
                closed = self.ws.closed if hasattr(self.ws, 'closed') else (not self.ws.open)
            except Exception:
                closed = True
            if not closed:
                try:
                    await self.ws.send(json.dumps({
                        'action': 'end_session',
                        'session_id': self.session_id,
                    }))
                except Exception:
                    pass
                try:
                    await self.ws.close()
                except Exception:
                    pass


async def monitor(clients: list, stop_event: asyncio.Event, flask_url: str, interval: int = 5):
    """监控打印：每隔 interval 秒打印各 speaker 状态 + 服务端状态"""
    start = time.time()
    while not stop_event.is_set():
        await asyncio.sleep(interval)
        elapsed = time.time() - start
        # 服务端状态
        try:
            h = http_get(f'{flask_url}/health')
            ws_lag = h.get('wsLoopLagMs', 0)
        except Exception:
            ws_lag = -1
        # 各 client 状态
        total_chunks = sum(c.chunks_sent for c in clients)
        total_partials = sum(c.partials_received for c in clients)
        total_finals = sum(c.finals_received for c in clients)
        print(f'[{elapsed:5.1f}s] wsLag={ws_lag:.1f}ms | chunks={total_chunks:4d} partials={total_partials:3d} finals={total_finals:3d} | per-speaker: ' + ' '.join(f'{c.name.split("-")[-1]}:{c.chunks_sent}' for c in clients))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--speakers', type=int, default=4, help='并发参会者数量')
    parser.add_argument('--duration', type=int, default=30, help='每个参会者持续喂音频的秒数')
    parser.add_argument('--room', type=str, default='stress', help='房间 ID')
    parser.add_argument('--server', type=str, default='ws://localhost:19087', help='WS 服务器 URL')
    parser.add_argument('--flask', type=str, default='http://localhost:19089', help='Flask API URL')
    parser.add_argument('--wav', type=str, default=DEFAULT_WAV, help='真实语音 WAV 文件路径（默认 long_sentence.wav）')
    args = parser.parse_args()

    print(f'=== 并发压测：{args.speakers} speakers × {args.duration}s ===')
    print(f'音频源: {args.wav}')

    # 加载真实语音 PCM
    print('加载 WAV 样本...')
    try:
        wav_pcm = load_wav_pcm_float32(args.wav, target_sr=16000)
        print(f'WAV 已加载: {len(wav_pcm) // 4} samples ({len(wav_pcm) // 4 / 16000:.1f}s @ 16kHz)')
    except Exception as e:
        print(f'WAV 加载失败 ({e})，退回正弦波')
        wav_pcm = None

    # 申请 JWT
    print('申请 JWT...')
    try:
        token_resp = http_post(
            f'{args.flask}/api/tokens',
            {'roomId': args.room, 'userId': 'stress-driver', 'userName': 'stress-driver', 'role': 'moderator'},
        )
        token = token_resp['token']
    except Exception as e:
        print(f'申请 JWT 失败: {e}')
        return

    # 创建 N 个 SpeakerClient 并并行连接
    print(f'启动 {args.speakers} 个并行 SpeakerClient...')
    clients = [SpeakerClient(i, args.room, args.server, token) for i in range(args.speakers)]
    connect_results = await asyncio.gather(*[c.connect() for c in clients])
    if not all(connect_results):
        success = sum(connect_results)
        print(f'连接完成：{success}/{args.speakers} 成功')
        if success == 0:
            return
        clients = [c for c, ok in zip(clients, connect_results) if ok]
        print(f'用 {len(clients)} 个 client 继续测试')

    # 启动接收 task
    recv_tasks = [asyncio.create_task(c.recv_loop()) for c in clients]
    # 启动监控 task
    stop_monitor = asyncio.Event()
    monitor_task = asyncio.create_task(monitor(clients, stop_monitor, args.flask))

    # 并行喂数据
    print(f'开始喂数据 {args.duration}s ...')
    start_feed = time.time()
    await asyncio.gather(*[c.feed_audio(args.duration, audio_bytes=wav_pcm) for c in clients])
    feed_duration = time.time() - start_feed

    # 让接收 task 多跑 5 秒接收最终的 final
    print(f'喂完，等待 5s 接收剩余 final...')
    await asyncio.sleep(5)

    # 停止
    stop_monitor.set()
    await monitor_task
    for t in recv_tasks:
        t.cancel()

    # 关闭连接
    await asyncio.gather(*[c.close() for c in clients], return_exceptions=True)

    # 汇总
    print('\n=== 压测汇总 ===')
    total_chunks = sum(c.chunks_sent for c in clients)
    total_partials = sum(c.partials_received for c in clients)
    total_finals = sum(c.finals_received for c in clients)
    print(f'实际喂时长: {feed_duration:.1f}s')
    print(f'实际参会者: {len(clients)} 个')
    print(f'总 chunk 数: {total_chunks}')
    print(f'每秒 chunk 总速率: {total_chunks/feed_duration:.1f} chunks/s (约 {total_chunks/feed_duration*4096/16000:.1f} 秒音频/秒)')
    print(f'transcript_partial 总数: {total_partials}')
    print(f'transcript_final   总数: {total_finals}')
    print(f'每 speaker 平均 chunk: {total_chunks/len(clients):.0f}')
    print(f'每 speaker 平均 partial: {total_partials/len(clients):.0f}')
    print(f'每 speaker 平均 final: {total_finals/len(clients):.0f}')
    print('\n各 speaker 明细:')
    for c in clients:
        print(f'  {c.name}: chunks={c.chunks_sent}, partials={c.partials_received}, finals={c.finals_received}')

    # 服务端最终状态
    try:
        h = http_get(f'{args.flask}/health')
        print(f'\n服务端最终状态: wsLoopLagMs={h.get("wsLoopLagMs"):.1f}')
    except Exception as e:
        print(f'\n服务端状态查询失败: {e}')


if __name__ == '__main__':
    asyncio.run(main())
