"""WAV 文件写入器（按 speaker 维度落盘）

Day 1-A 占位，Day 1-B 实现：
- 每个 speaker 一个 .wav 文件
- 文件命名：recordings/{meeting_id}/{speaker_id}.wav
- 实时追加 PCM，文件头最后补
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class WavWriter:
    """实时 PCM → WAV 写入器（边收边写）"""

    def __init__(self, path: str, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self._fp = open(self.path, "wb")
        self._bytes_written = 0
        # 写 WAV 文件头（占位，最后补正 data size）
        self._fp.write(b"RIFF")
        self._fp.write(struct.pack("<I", 0))           # 整个文件大小（最后填）
        self._fp.write(b"WAVE")
        self._fp.write(b"fmt ")
        self._fp.write(struct.pack("<I", 16))          # fmt chunk size
        self._fp.write(struct.pack("<H", 1))           # PCM 格式
        self._fp.write(struct.pack("<H", channels))
        self._fp.write(struct.pack("<I", sample_rate))
        self._fp.write(struct.pack("<I", sample_rate * channels * sample_width))  # byte rate
        self._fp.write(struct.pack("<H", channels * sample_width))                # block align
        self._fp.write(struct.pack("<H", sample_width * 8))                       # bits per sample
        self._fp.write(b"data")
        self._fp.write(struct.pack("<I", 0))           # data size（最后填）

    def write(self, pcm: bytes):
        if not pcm:
            return
        self._fp.write(pcm)
        self._bytes_written += len(pcm)

    def close(self):
        if self._fp.closed:
            return
        # 回填 data size + RIFF size
        self._fp.seek(4)
        self._fp.write(struct.pack("<I", 36 + self._bytes_written))
        self._fp.seek(40)
        self._fp.write(struct.pack("<I", self._bytes_written))
        self._fp.close()
        logger.info(f"[WavWriter] 关闭 {self.path}，共 {self._bytes_written} bytes")


class WavWriterPool:
    """按 speaker_id 管理多个 WavWriter"""

    def __init__(self, base_dir: str = "recordings"):
        self.base_dir = Path(base_dir)
        self._writers: Dict[str, WavWriter] = {}

    def write(self, meeting_id: str, speaker_id: str, pcm: bytes, sample_rate: int = 16000):
        key = f"{meeting_id}::{speaker_id}"
        if key not in self._writers:
            path = self.base_dir / meeting_id / f"{speaker_id}.wav"
            self._writers[key] = WavWriter(str(path), sample_rate=sample_rate)
        self._writers[key].write(pcm)

    def close_all(self):
        for w in self._writers.values():
            w.close()
        self._writers.clear()

    def close(self, meeting_id: str, speaker_id: str):
        key = f"{meeting_id}::{speaker_id}"
        w = self._writers.pop(key, None)
        if w:
            w.close()
