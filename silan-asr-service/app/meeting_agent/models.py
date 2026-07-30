"""Meeting Agent 数据模型

协议字段（与浏览器 JS / Python 内部统一）：
- meeting_id       房间 ID
- participant_id   Jitsi participantId（浏览器带上来，**仍以服务端校验为准**）
- track_id         Jitsi trackId
- speaker_id       服务端分配（不可伪造，唯一标识一个说话人）
- bot_token        Bot 加入会议用的短期 token（由 Bot Manager 签发）
- sample_rate      PCM 采样率（目标 16kHz）
- pcm              Int16 LE PCM 字节流（base64 编码）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import time


@dataclass
class ParticipantState:
    """一个会议中的参会者状态

    由 participant/tracker.py 维护。
    """
    participant_id: str          # Jitsi participantId（来自 TRACK_ADDED）
    display_name: str = ""      # 昵称（来自 Jitsi displayName）
    speaker_id: str = ""         # 服务端分配的 speaker_id（不可伪造）
    joined_at: int = field(default_factory=lambda: int(time.time() * 1000))
    left_at: Optional[int] = None
    has_audio: bool = False      # 是否有 audio track
    track_id: Optional[str] = None
    # ASR session 关联（Day 2+）
    asr_session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "participantId": self.participant_id,
            "displayName": self.display_name,
            "speakerId": self.speaker_id,
            "joinedAt": self.joined_at,
            "leftAt": self.left_at,
            "hasAudio": self.has_audio,
            "trackId": self.track_id,
            "asrSessionId": self.asr_session_id,
        }


@dataclass
class MeetingBot:
    """一个会议的 Bot 实例状态

    由 manager/bot_manager.py 维护。
    """
    bot_id: str                  # 内部 UUID
    meeting_id: str              # Jitsi 房间 ID
    bot_token: str               # 短期 token（签发给 Chromium 验证身份）
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    status: str = "spawning"     # spawning | running | failed | killed
    playwright_page_id: Optional[str] = None
    participants: Dict[str, ParticipantState] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "botId": self.bot_id,
            "meetingId": self.meeting_id,
            "status": self.status,
            "createdAt": self.created_at,
            "participants": {pid: p.to_dict() for pid, p in self.participants.items()},
            "error": self.error,
        }


@dataclass
class AudioChunk:
    """一个 PCM 音频块（浏览器 → Python）

    字段与 JS 端 JSON 完全对齐，便于直接 dict 转换。
    """
    meeting_id: str
    participant_id: str
    track_id: str
    timestamp: int
    sample_rate: int
    pcm: bytes                   # Int16 LE 原始字节
    speaker_id: str = ""         # 由 receiver 在验证 token 后填充
    sequence: int = 0            # 块序号（用于丢包检测 / 重连补偿 / 音频排序）

    def to_dict(self) -> Dict[str, Any]:
        import base64
        return {
            "type": "audio_chunk",
            "meetingId": self.meeting_id,
            "participantId": self.participant_id,
            "trackId": self.track_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "sampleRate": self.sample_rate,
            "pcm": base64.b64encode(self.pcm).decode("ascii"),
        }

    @classmethod
    def from_ws_message(cls, msg: Dict[str, Any]) -> "AudioChunk":
        import base64
        return cls(
            meeting_id=msg["meetingId"],
            participant_id=msg["participantId"],
            track_id=msg["trackId"],
            timestamp=int(msg.get("timestamp", time.time() * 1000)),
            sample_rate=int(msg.get("sampleRate", 16000)),
            pcm=base64.b64decode(msg["pcm"]),
            sequence=int(msg.get("sequence", 0)),
        )
