"""Audio Chunk WebSocket 接收端（Day 1-B 落地）

职责：
- 监听 WebSocket `/ws/recorder/{meeting_id}`（bot 推 PCM 上来）
- 验证 bot_token → 查 BotManager
- 解析 audio_chunk 消息 → AudioChunk
- 按 speaker_id 落 wav（WavWriterPool）
- 处理 participant_joined / participant_left 事件，注册参会者

协议（浏览器 → Python）：
  hello              → { type, botToken, meetingId }
  audio_chunk        → { type, meetingId, participantId, trackId, timestamp, sampleRate, pcm(base64) }
  participant_joined → { type, meetingId, participantId, displayName }
  participant_left   → { type, meetingId, participantId }
  track_capture_started → { type, meetingId, participantId, trackId, participantName }
  track_capture_stopped → { type, meetingId, participantId, trackId }
  bot_joined         → { type, meetingId, botId }

协议（Python → 浏览器）：
  welcome              → { type, meetingId, botId }
  participant_registered → { type, participantId, speakerId }
  error                → { type, message }
"""
from __future__ import annotations

import logging
import json
import time
from typing import Optional, Dict, Any

from ..models import AudioChunk
from ..manager.bot_manager import get_bot_manager
from .wav_writer import WavWriterPool

logger = logging.getLogger(__name__)

# 全局 WavWriter 池（按 meeting_id + speaker_id 落盘）
_wav_pool: Optional[WavWriterPool] = None


def _get_wav_pool() -> WavWriterPool:
    global _wav_pool
    if _wav_pool is None:
        _wav_pool = WavWriterPool(base_dir="recordings")
    return _wav_pool


async def handle_recorder_ws(ws, path: str):
    """WebSocket 入口：path 形如 /ws/recorder/{meeting_id}

    浏览器连上后会先发一条 hello 消息：
      { "type": "hello", "botToken": "...", "meetingId": "..." }

    服务端验证后回：
      { "type": "welcome", "meetingId": "...", "botId": "..." }

    然后浏览器持续推 audio_chunk / participant_joined 等事件。
    """
    # 从 path 提取 meeting_id（兼容 websockets 库的 path 属性）
    path_meeting_id = _extract_meeting_id(path)
    logger.info(f"[AudioReceiver] Bot 连接: path={path}, meetingId={path_meeting_id}")

    bot_manager = get_bot_manager()
    bot = None
    meeting_id: Optional[str] = None

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"[AudioReceiver] 非 JSON 消息: {str(raw)[:100]}")
                continue

            msg_type = msg.get("type")

            # ----------------------------------------------------------
            # hello：验证 bot_token
            # ----------------------------------------------------------
            if msg_type == "hello":
                bot_token = msg.get("botToken", "")
                meeting_id = msg.get("meetingId") or path_meeting_id

                bot = bot_manager.verify_bot_token(bot_token)
                if bot is None:
                    logger.warning(f"[AudioReceiver] bot_token 验证失败: {bot_token[:30]}...")
                    await ws.send(json.dumps({
                        "type": "error",
                        "message": "bot_token 验证失败",
                    }))
                    await ws.close()
                    return

                if meeting_id and bot.meeting_id != meeting_id:
                    logger.warning(
                        f"[AudioReceiver] meetingId 不匹配: path={meeting_id} bot={bot.meeting_id}"
                    )
                    meeting_id = bot.meeting_id

                logger.info(
                    f"[AudioReceiver] Bot 验证成功: botId={bot.bot_id}, meetingId={bot.meeting_id}"
                )
                await ws.send(json.dumps({
                    "type": "welcome",
                    "meetingId": bot.meeting_id,
                    "botId": bot.bot_id,
                }))
                continue

            # 后续消息都需要已验证的 bot
            if bot is None:
                logger.warning(f"[AudioReceiver] 未验证 bot_token 就发消息: {msg_type}")
                await ws.send(json.dumps({
                    "type": "error",
                    "message": "请先发送 hello 验证身份",
                }))
                continue

            # ----------------------------------------------------------
            # participant_joined：注册参会者，分配 speaker_id
            # ----------------------------------------------------------
            if msg_type == "participant_joined":
                participant_id = msg.get("participantId", "")
                display_name = msg.get("displayName", "")
                if not participant_id:
                    continue

                state = bot_manager.register_participant(
                    meeting_id=bot.meeting_id,
                    participant_id=participant_id,
                    display_name=display_name,
                )
                if state:
                    logger.info(
                        f"[AudioReceiver] 注册参会者: {participant_id} ({display_name}) → {state.speaker_id}"
                    )
                    await ws.send(json.dumps({
                        "type": "participant_registered",
                        "participantId": participant_id,
                        "speakerId": state.speaker_id,
                        "displayName": display_name,
                    }))

            # ----------------------------------------------------------
            # participant_left：标记离开，关闭对应 WAV
            # ----------------------------------------------------------
            elif msg_type == "participant_left":
                participant_id = msg.get("participantId", "")
                if not participant_id:
                    continue
                state = bot.participants.get(participant_id)
                if state:
                    state.left_at = int(time.time() * 1000)
                    # 关闭该 speaker 的 WAV 文件
                    _get_wav_pool().close(bot.meeting_id, state.speaker_id)
                    logger.info(f"[AudioReceiver] 参会者离开: {participant_id} (speaker={state.speaker_id})")

            # ----------------------------------------------------------
            # track_capture_started：标记参会者有音频轨
            # ----------------------------------------------------------
            elif msg_type == "track_capture_started":
                participant_id = msg.get("participantId", "")
                track_id = msg.get("trackId", "")
                participant_name = msg.get("participantName", "")
                if not participant_id:
                    continue
                # 如果尚未注册，自动注册
                state = bot.participants.get(participant_id)
                if state is None:
                    state = bot_manager.register_participant(
                        meeting_id=bot.meeting_id,
                        participant_id=participant_id,
                        display_name=participant_name,
                    )
                if state:
                    state.has_audio = True
                    state.track_id = track_id
                    logger.info(
                        f"[AudioReceiver] 开始捕获: {participant_id} (speaker={state.speaker_id}, track={track_id})"
                    )

            # ----------------------------------------------------------
            # track_capture_stopped：关闭对应 speaker 的 WAV
            # ----------------------------------------------------------
            elif msg_type == "track_capture_stopped":
                participant_id = msg.get("participantId", "")
                state = bot.participants.get(participant_id)
                if state:
                    _get_wav_pool().close(bot.meeting_id, state.speaker_id)
                    logger.info(
                        f"[AudioReceiver] 停止捕获: {participant_id} (speaker={state.speaker_id})"
                    )

            # ----------------------------------------------------------
            # audio_chunk：解析 PCM，落 WAV
            # ----------------------------------------------------------
            elif msg_type == "audio_chunk":
                try:
                    chunk = AudioChunk.from_ws_message(msg)
                except (KeyError, ValueError) as e:
                    logger.warning(f"[AudioReceiver] audio_chunk 解析失败: {e}")
                    continue

                # 填充 speaker_id（服务端分配，不可伪造）
                state = bot.participants.get(chunk.participant_id)
                if state is None:
                    # 未见过的 participant，自动注册
                    state = bot_manager.register_participant(
                        meeting_id=bot.meeting_id,
                        participant_id=chunk.participant_id,
                        display_name="",
                    )
                    if state is None:
                        continue

                chunk.speaker_id = state.speaker_id

                # 落 WAV
                _get_wav_pool().write(
                    meeting_id=bot.meeting_id,
                    speaker_id=state.speaker_id,
                    pcm=chunk.pcm,
                    sample_rate=chunk.sample_rate,
                )

                # Day 2 接 ASR：此处把 chunk 推入 ASR 队列
                # TODO: await asr_queue.submit(chunk)

                # 调试日志：每 50 个块打一次，含 sequence 用于丢包检测
                if chunk.sequence % 50 == 0:
                    logger.info(
                        f"[AudioReceiver] chunk seq={chunk.sequence} "
                        f"participant={chunk.participant_id} speaker={state.speaker_id} "
                        f"pcm={len(chunk.pcm)}B"
                    )

                if state.track_id is None:
                    state.track_id = chunk.track_id
                    state.has_audio = True

            # ----------------------------------------------------------
            # bot_joined：Bot 已加入会议（信息性事件）
            # ----------------------------------------------------------
            elif msg_type == "bot_joined":
                logger.info(f"[AudioReceiver] Bot 已加入会议: {bot.meeting_id}")

            else:
                logger.warning(f"[AudioReceiver] 未知消息类型: {msg_type}")

    except Exception as e:
        logger.exception(f"[AudioReceiver] WS 异常: {e}")
    finally:
        # Bot 断开：关闭该会议所有 speaker 的 WAV
        if bot is not None:
            for pid, state in list(bot.participants.items()):
                if state.speaker_id:
                    _get_wav_pool().close(bot.meeting_id, state.speaker_id)
        logger.info(f"[AudioReceiver] Bot 断开: path={path}")


def _extract_meeting_id(path: str) -> Optional[str]:
    """从 path 中提取 meeting_id

    path 形如: /ws/recorder/{meeting_id}
    """
    if not path:
        return None
    prefix = "/ws/recorder/"
    if path.startswith(prefix):
        rest = path[len(prefix):]
        # 去掉可能的 query string
        rest = rest.split("?")[0].split("/")[0]
        return rest if rest else None
    return None
