"""生成测试音频文件（macOS say 或 edge-tts）

使用方式：
  # macOS 原生 TTS（中文效果差，只能单字）
  python -m test_client.gen_test_audio

  # 微软 Azure TTS（推荐，需要 pip install edge-tts）
  python -m test_client.gen_test_audio --engine edge
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path


# 中文测试语料
TEST_TEXTS = {
    "short_greeting": "你好，我们开始吧。",
    "long_sentence": (
        "今天我们讨论一下半导体行业的最新发展。"
        "首先看看台积电最近的财报，再来谈一下 EUV 光刻机的供货情况。"
        "最后我会总结一下 HBM 内存的市场需求。"
    ),
    "with_pauses": (
        "我觉得这个方案，需要重新设计。"
        "你看这里，CoWoS 封装良率太低了。"
        "我们换个思路试试。"
    ),
    "meeting_summary": (
        "今天的会议主要讨论三个议题。"
        "第一，半导体制程工艺的升级路径。"
        "第二，CoWoS 先进封装的产能分配。"
        "第三，下一季度 HBM 内存的需求预测。"
        "请各位同事会后提交书面意见。"
    ),
}

# 英文测试语料（macOS say 英文支持好）
TEST_TEXTS_EN = {
    "short_greeting_en": "Hello everyone, let's get started.",
    "long_meeting_en": (
        "Today we will discuss the latest developments in the semiconductor industry. "
        "First, let's look at TSMC's recent earnings report. "
        "Then we will talk about EUV lithography equipment supply. "
        "Finally, I will summarize the HBM memory market demand."
    ),
}


def gen_with_say(text: str, output_path: Path, voice: str = "Tingting", rate: int = 180):
    """macOS say + ffmpeg"""
    aiff_path = output_path.with_suffix(".aiff")
    print(f"  🎤 say: {text[:40]}... -> {output_path.name}")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff_path), text], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(aiff_path), "-ar", "16000", "-ac", "1", "-f", "wav", str(output_path)],
        check=True, capture_output=True,
    )
    aiff_path.unlink(missing_ok=True)


async def gen_with_edge_tts(text: str, output_path: Path, voice: str = "zh-CN-XiaoxiaoNeural"):
    """微软 Azure TTS（需要 pip install edge-tts）"""
    try:
        import edge_tts
    except ImportError:
        print("  ❌ 需要安装 edge-tts：pip install edge-tts")
        sys.exit(1)
    print(f"  🎤 edge-tts ({voice}): {text[:40]}... -> {output_path.name}")
    communicate = edge_tts.Communicate(text, voice)
    mp3_path = output_path.with_suffix(".mp3")
    await communicate.save(str(mp3_path))
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "16000", "-ac", "1", "-f", "wav", str(output_path)],
        check=True, capture_output=True,
    )
    mp3_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="生成测试音频")
    parser.add_argument("--out", default="test_audio", help="输出目录")
    parser.add_argument("--engine", choices=["say", "edge"], default="say", help="TTS 引擎")
    parser.add_argument("--voice", default=None, help="覆盖默认 TTS 语音")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.engine == "edge":
        default_voice = args.voice or "zh-CN-XiaoxiaoNeural"
    else:
        default_voice = args.voice or "Tingting"

    print(f"📁 输出目录: {out_dir.absolute()}")
    print(f"� 引擎: {args.engine}, 语音: {default_voice}")
    print()

    # 中文语料
    for name, text in TEST_TEXTS.items():
        output_path = out_dir / f"{name}.wav"
        try:
            if args.engine == "edge":
                asyncio.run(gen_with_edge_tts(text, output_path, default_voice))
            else:
                gen_with_say(text, output_path, default_voice)
        except subprocess.CalledProcessError as e:
            print(f"  ❌ 生成失败: {e}")
            continue
        except FileNotFoundError as e:
            print(f"  ❌ 命令未找到: {e}")
            sys.exit(1)

    # 英文语料（用 macOS Samantha 测英文链路）
    if args.engine == "say":
        for name, text in TEST_TEXTS_EN.items():
            output_path = out_dir / f"{name}.wav"
            try:
                gen_with_say(text, output_path, "Samantha", rate=200)
            except Exception as e:
                print(f"  ❌ 生成失败: {e}")
                continue

    print()
    print("✅ 测试音频已生成。开始测试：")
    print(f"   python -m test_client.wav_stream_client --wav {out_dir}/short_greeting.wav")


if __name__ == "__main__":
    main()

