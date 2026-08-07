"""ASR 识别质量评估工具

两种模式：
  1. 无 ground truth：只跑识别，把 final 文本整理成可读格式输出
  2. 有 ground truth：跑识别 + 算 CER（字符错误率）/ WER（词错误率）

使用：
  # 只看识别结果
  python -m test_client.eval_wav --wav test_audio/short_greeting.wav

  # 有 ground truth 时计算准确率
  python -m test_client.eval_wav \
    --wav test_audio/meeting_summary.wav \
    --gt "今天的会议主要讨论三个议题..."

  # 批量评估（推荐用于回归测试）
  python -m test_client.eval_wav --batch test_audio/manifest.jsonl
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_client.asr_client import ASRClient, load_wav_as_float32


def normalize_text(text: str) -> str:
    """归一化文本（去标点、去空格、转小写），用于 CER/WER 计算"""
    text = re.sub(r'[\s，。！？、；：""\'\'《》（）,.!?;:"\'()【】\-—\.\.]+', '', text)
    return text.lower()


def levenshtein(a: str, b: str) -> int:
    """计算编辑距离（用于 CER/WER）"""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    """字符错误率：编辑距离 / 参考文本字符数"""
    ref = normalize_text(ref)
    hyp = normalize_text(hyp)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def wer(ref: str, hyp: str) -> float:
    """词错误率：按词切分（中文按字符）"""
    ref = list(normalize_text(ref))  # 中文按字
    hyp = list(normalize_text(hyp))
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


async def eval_single_wav(
    wav_path: Path,
    ground_truth: str = None,
    ws_url: str = "ws://127.0.0.1:8087",
    speed: float = 1.0,
    verbose: bool = False,
) -> dict:
    """跑一个 wav，返回评估结果"""
    audio = load_wav_as_float32(str(wav_path), target_sr=16000)
    duration = len(audio) / 16000
    max_amp = float(abs(audio).max())

    client = ASRClient(
        ws_url=ws_url,
        meeting_id="eval",
        participant_name=wav_path.stem,
        sample_rate=16000,
        chunk_ms=100,
    )

    try:
        await client.connect()
        if verbose:
            print(f"▶️  播放: {wav_path.name} (时长 {duration:.1f}s)")

        chunk_samples = client.chunk_samples
        real_interval = 0.1 / speed
        for i in range(0, len(audio), chunk_samples):
            chunk = audio[i:i + chunk_samples]
            if len(chunk) < chunk_samples:
                chunk = __import__('numpy').pad(chunk, (0, chunk_samples - len(chunk)))
            await client.send_chunk(chunk)
            if real_interval > 0:
                await asyncio.sleep(real_interval)

        await client.end()
    except Exception as e:
        return {"wav": str(wav_path), "error": str(e)}

    # 收集 final 文本
    finals = [t for t in client.result.transcripts if t.type == "final"]
    recognized = "".join(t.text for t in finals)
    partials_count = sum(1 for t in client.result.transcripts if t.type == "partial")

    result = {
        "wav": str(wav_path),
        "duration_s": round(duration, 2),
        "max_amplitude": round(max_amp, 3),
        "partials_count": partials_count,
        "finals_count": len(finals),
        "recognized_text": recognized,
    }

    if ground_truth:
        result["ground_truth"] = ground_truth
        result["cer"] = round(cer(ground_truth, recognized), 4)
        result["wer"] = round(wer(ground_truth, recognized), 4)
        # 字符级 diff
        ref_n = normalize_text(ground_truth)
        hyp_n = normalize_text(recognized)
        result["ref_chars"] = len(ref_n)
        result["hyp_chars"] = len(hyp_n)
        result["common_chars"] = sum(1 for c in ref_n if c in hyp_n)

    return result


def print_result(r: dict, verbose: bool = False):
    """打印评估结果"""
    if "error" in r:
        print(f"❌ {r['wav']}: {r['error']}")
        return
    print(f"📄 {Path(r['wav']).name}")
    print(f"   时长: {r['duration_s']}s, 振幅: {r['max_amplitude']}")
    print(f"   Partial: {r['partials_count']}, Final: {r['finals_count']}")
    print(f"   识别文本: {r['recognized_text']}")
    if "ground_truth" in r:
        print(f"   原始文本: {r['ground_truth']}")
        print(f"   📊 CER: {r['cer'] * 100:.1f}%, WER: {r['wer'] * 100:.1f}%")
        if verbose:
            ref_n = normalize_text(r['ground_truth'])
            hyp_n = normalize_text(r['recognized_text'])
            print(f"   ref({len(ref_n)}): {ref_n}")
            print(f"   hyp({len(hyp_n)}): {hyp_n}")
    print()


async def main():
    parser = argparse.ArgumentParser(description="ASR 识别质量评估")
    parser.add_argument("--wav", help="WAV 文件路径")
    parser.add_argument("--gt", "--ground-truth", help="ground truth 文本")
    parser.add_argument("--ws", default="ws://127.0.0.1:8087", help="ASR WebSocket 地址")
    parser.add_argument("--speed", type=float, default=1.0, help="播放速度")
    parser.add_argument("--batch", help="批量评估清单 JSONL，每行 {wav, gt}")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    if not args.wav and not args.batch:
        parser.error("需要指定 --wav 或 --batch")

    if args.batch:
        # 批量模式
        manifest_path = Path(args.batch)
        if not manifest_path.exists():
            print(f"❌ 清单文件不存在: {manifest_path}")
            sys.exit(1)
        results = []
        with open(manifest_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                item = json.loads(line)
                wav = Path(item["wav"])
                if not wav.is_absolute():
                    wav = manifest_path.parent / wav
                r = await eval_single_wav(wav, item.get("gt"), args.ws, args.speed, args.verbose)
                results.append(r)
                print_result(r, args.verbose)
        # 汇总
        valid = [r for r in results if "error" not in r and "cer" in r]
        if valid:
            avg_cer = sum(r["cer"] for r in valid) / len(valid)
            avg_wer = sum(r["wer"] for r in valid) / len(valid)
            print("=" * 60)
            print(f"📊 批量汇总 ({len(valid)} 个有效样本)")
            print(f"   平均 CER: {avg_cer * 100:.1f}%")
            print(f"   平均 WER: {avg_wer * 100:.1f}%")
            print()
            if avg_cer < 0.05:
                print("   🟢 优秀（CER < 5%）")
            elif avg_cer < 0.15:
                print("   🟡 良好（CER < 15%）")
            elif avg_cer < 0.30:
                print("   🟠 一般（CER < 30%）")
            else:
                print("   🔴 较差（CER ≥ 30%，建议优化：加热词 / VAD / 音频质量）")
    else:
        # 单文件模式
        wav = Path(args.wav)
        if not wav.exists():
            print(f"❌ 文件不存在: {wav}")
            sys.exit(1)
        r = await eval_single_wav(wav, args.gt, args.ws, args.speed, args.verbose)
        print_result(r, args.verbose)
        if "cer" in r:
            print(f"📊 CER: {r['cer'] * 100:.1f}%")
            if r['cer'] < 0.05:
                print("   🟢 优秀")
            elif r['cer'] < 0.15:
                print("   🟡 良好")
            elif r['cer'] < 0.30:
                print("   🟠 一般")
            else:
                print("   🔴 较差")


if __name__ == "__main__":
    asyncio.run(main())
