"""WAV 文件流式发送客户端

模拟前端 audioCapture.ts 的行为：
  - 读取 wav 文件
  - 按 chunk_ms 切分（默认 100ms / 1600 samples @16kHz）
  - 按实时速度发送（time.sleep(0.1) 模拟说话节奏）
  - 收集 partial/final 消息

使用：
  python -m test_client.wav_stream_client --wav test.wav
  python -m test_client.wav_stream_client --wav test.wav --ws ws://192.168.1.10:19087
  python -m test_client.wav_stream_client --wav test.wav --speed 0.5  # 半速（更易观察 partial）
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

# 支持 python -m test_client.wav_stream_client
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_client.asr_client import ASRClient, load_wav_as_float32


async def main():
    parser = argparse.ArgumentParser(description="WAV 流式 ASR 测试客户端")
    parser.add_argument("--wav", required=True, help="WAV 文件路径（任意采样率/通道数，自动转 16k mono）")
    parser.add_argument("--ws", default="ws://127.0.0.1:19087", help="ASR WebSocket 地址")
    parser.add_argument("--meeting", default="test-meeting", help="会议 ID")
    parser.add_argument("--user", default="测试用户", help="参与者名称")
    parser.add_argument("--speed", type=float, default=1.0, help="播放速度（1.0=实时，0.5=半速，2.0=2 倍速）")
    parser.add_argument("--chunk-ms", type=int, default=100, help="每块时长 ms（默认 100ms）")
    args = parser.parse_args()

    wav_path = Path(args.wav)
    if not wav_path.exists():
        print(f"❌ 文件不存在: {wav_path}")
        sys.exit(1)

    print(f"📂 加载 WAV: {wav_path}")
    audio = load_wav_as_float32(str(wav_path), target_sr=16000)
    duration = len(audio) / 16000
    print(f"   时长: {duration:.2f}s, 样本数: {len(audio)}, max_amp: {abs(audio).max():.3f}")

    client = ASRClient(
        ws_url=args.ws,
        meeting_id=args.meeting,
        participant_name=args.user,
        sample_rate=16000,
        chunk_ms=args.chunk_ms,
    )

    try:
        await client.connect()
        print(f"▶️  开始流式发送 (speed={args.speed}x, chunk={args.chunk_ms}ms)")
        print()

        chunk_samples = client.chunk_samples
        real_chunk_interval = args.chunk_ms / 1000.0 / args.speed

        for i in range(0, len(audio), chunk_samples):
            chunk = audio[i:i + chunk_samples]
            if len(chunk) < chunk_samples:
                # 最后一帧补零
                chunk = __import__('numpy').pad(chunk, (0, chunk_samples - len(chunk)))
            await client.send_chunk(chunk)
            # 模拟实时发送节奏
            if real_chunk_interval > 0:
                await asyncio.sleep(real_chunk_interval)

        print()
        print(f"⏹  音频发送完成，等待 final 触发...")
        await client.end()
        client.print_summary()

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
