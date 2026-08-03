# WebSocket Gateway Server - 原生 WebSocket 协议
# websockets 主线程处理 WebSocket，Flask 后台线程处理 HTTP API

import asyncio
import base64
import json
import logging
import os
import ssl
import threading
import time
import uuid
from typing import Dict, Optional, Set

import numpy as np
from flask import Flask

from websockets.asyncio.server import serve, ServerConnection

from app.config.settings import AudioGatewayConfig, AppConfig, load_config
from app.audio_processor.processor import AudioProcessor
from app.session_manager.manager import AudioSessionManager
from app.session_manager.session import SessionStatus
from app.asr_worker.worker import ASRWorker
from app.transcript_service.service import TranscriptService
from app.audio_gateway.transcript_aggregator import TranscriptAggregator
from app.api_routes import api_bp
from app.auth import verify_token, is_moderator
from app.meeting_state import (
    get_or_create_meeting,
    add_message,
    get_messages_after_seq,
    get_all_messages,
    set_ai_bot,
    get_ai_bot,
    get_asr_model,
)
from app.audit_log import audit_log
from app.llm_service import generate_summary

logger = logging.getLogger(__name__)

# 事件循环心跳时间戳：用于健康检查，暴露「事件循环是否被同步代码卡死」
_loop_last_tick: float = 0.0

# 主事件循环引用：供 Flask 后台线程通过 run_coroutine_threadsafe 调度协程
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def get_loop_lag_ms() -> float:
    """返回事件循环心跳滞后毫秒数；心跳未启动时返回 -1"""
    if not _loop_last_tick:
        return -1.0
    return (time.time() - _loop_last_tick) * 1000


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """返回主事件循环（供 Flask 线程调度协程用）"""
    return _main_loop


class WebSocketGatewayServer:
    def __init__(self, config: AudioGatewayConfig = None):
        self.config = config or AudioGatewayConfig()
        self.app_config = load_config()
        # 外部注入的 Socket.IO（用于跨通道广播 ai_bot_status / meeting_transcript）
        self._socketio = None

        # Flask app (HTTP API, 后台线程运行)
        self.app = Flask(__name__)
        self.app.register_blueprint(api_bp)

        # 组件
        self.audio_processor = AudioProcessor(self.app_config.audio_processor)
        self.session_manager = AudioSessionManager(self.app_config.session_manager)
        self.asr_worker = ASRWorker("ws-gateway-worker", self.app_config.asr_worker)
        self.transcript_service = TranscriptService(self.app_config.transcript_service)
        # 注入 ASR Worker 的标点模型，让 final 文本在 emit 时自动加标点
        # 静音超时 3000ms：会议场景用户句中可能停顿 1-2s，1.5s 太短会把一句话切碎
        # 最长单句 60s：超过强制切分，避免 buffer 累积过长
        self.transcript_aggregator = TranscriptAggregator(
            silence_timeout_ms=3000,
            max_utterance_duration_s=60.0,
            punc_model=self.asr_worker.punc_model,
        )

        # 会议 WebSocket 状态
        self._clients: Dict[str, dict] = {}      # ws_id -> {ws, room_id, user_id}
        self._rooms: Dict[str, Set[str]] = {}    # room_id -> set of ws_id
        # 房间级 AI 操作者：room_id -> 开启 AI 的 userId
        # transcript 推送时跳过该 userId 的所有 ws（操作者已从 AudioCaptureService 拿到）
        self._room_audio_operator_user: Dict[str, str] = {}

        self.asr_worker.start()
        self.transcript_aggregator.set_callback(self._handle_aggregated_transcript)
        self.transcript_aggregator.start()
        self._setup_transcript_callback()
        logger.info("WebSocketGatewayServer initialized (native WebSocket)")

    def set_socketio(self, socketio) -> None:
        """注入 Flask-SocketIO 实例（用于跨通道广播 ai_bot_status / meeting_transcript）"""
        self._socketio = socketio

    def _setup_transcript_callback(self) -> None:
        """ASR Worker 结果回调 → 送入 Aggregator 聚合"""
        self.asr_worker.set_transcript_callback(self._handle_worker_results)

    def _handle_worker_results(self, results: list) -> None:
        """将 ASR 原始结果送入 Aggregator"""
        for result in results:
            self.transcript_aggregator.on_asr_result(result)

    def _handle_aggregated_transcript(self, message: dict) -> None:
        """
        Aggregator 回调：处理聚合后的 partial/final 消息
        
        message: {
            "type": "transcript_partial" | "transcript_final",
            "session_id": str,
            "meeting_id": str,
            "participant_id": str,
            "participant_name": str,
            "text": str,
            "timestamp": int,
        }
        """
        msg_type = message["type"]
        meeting_id = message["meeting_id"]
        text = message["text"]

        logger.info(f"[Aggregator] {msg_type}: participant={message.get('participant_name')}, text='{text}'")

        # transcript_final 持久化到 meeting_state，后加入的用户可以拉到历史
        # partial 不持久化（实时显示用，会被后续 final 覆盖，持久化会导致重复）
        if msg_type == "transcript_final" and text:
            try:
                add_message(meeting_id, {
                    "sender": message.get("participant_name") or "AI 转写",
                    "content": text,
                    "timestamp": message.get("timestamp") or int(time.time() * 1000),
                    "type": "transcript",
                    "participant_id": message.get("participant_id"),
                    "session_id": message.get("session_id"),
                })
            except Exception as e:
                logger.error(f"[Aggregator] persist transcript_final error: {e}")

        # 广播到房间所有 WebSocket 客户端
        # 操作者本人会同时通过 audioCapture ws 和 useWebSocket ws 收到 transcript，
        # 但 App.tsx 的 meeting_transcript 处理已有去重逻辑（同 speaker+内容+1s），
        # 所以这里不需要按 user_id 跳过操作者——跳过反而会让操作者收不到 transcript。
        room_clients = self._rooms.get(meeting_id, set())
        if room_clients:
            msg = json.dumps(message)
            for ws_id in room_clients:
                client = self._clients.get(ws_id)
                if not client:
                    continue
                try:
                    asyncio.run_coroutine_threadsafe(
                        client["ws"].send(msg), self._loop
                    )
                except Exception as e:
                    logger.error(f"Broadcast {msg_type} error: {e}")

        # 兼容老的 Socket.IO 通道（如果仍有人在用）
        if msg_type == "transcript_final" and self._socketio:
            self._socketio.emit("meeting_transcript", message, room=meeting_id)

    # -----------------------------------------------------------------------
    # 统一音频入口：source 可以是 "bot" / "browser" / "upload"
    # Bot 从 receiver.py 调用；未来 browser 也可复用同一入口
    # -----------------------------------------------------------------------
    def ingest_bot_audio(
        self,
        *,
        meeting_id: str,
        participant_id: str,
        display_name: str,
        pcm: bytes,
        sample_rate: int = 16000,
        source: str = "bot",
    ) -> None:
        """统一音频入口：Bot / 浏览器 / 文件回放都走这里。

        session_id 全局统一格式：meeting:{meeting_id}:participant:{participant_id}
        避免和 browser 路径冲突，也方便未来多 source 共用。
        """
        if not meeting_id or not participant_id:
            logger.warning("[Ingest] missing meeting_id or participant_id, drop")
            return

        session_id = f"meeting:{meeting_id}:participant:{participant_id}"

        # 1. session_manager 注册（幂等：不存在则创建）
        try:
            existing = self.session_manager.get_session(session_id)
            if existing is None:
                self.session_manager.create_session(
                    session_id=session_id,
                    meeting_id=meeting_id,
                    participant_id=participant_id,
                    participant_name=display_name,
                    client_id=f"bot:{source}",
                    sample_rate=sample_rate,
                )
                logger.info(f"[Ingest] created session {session_id} (source={source})")
        except Exception as e:
            logger.error(f"[Ingest] create_session error: {e}")

        # 2. transcript_aggregator 注册（幂等）
        try:
            self.transcript_aggregator.register_session(
                session_id=session_id,
                participant_id=participant_id,
                participant_name=display_name or "Unknown",
                meeting_id=meeting_id,
            )
        except Exception as e:
            logger.error(f"[Ingest] aggregator register error: {e}")

        # 3. 喂给 ASR Worker（Aggregator 在 on_asr_result 中自动聚合）
        try:
            asr_model = get_asr_model(meeting_id)
            self.asr_worker.submit_audio(
                session_id=session_id,
                audio_data=pcm,
                sample_rate=sample_rate,
                timestamp=int(time.time() * 1000),
                asr_model=asr_model,
            )
        except Exception as e:
            logger.error(f"[Ingest] submit_audio error: {e}")

        # 4. 刷新 aggregator 计时（避免 silence_timeout 误判句尾）
        try:
            self.transcript_aggregator.touch_session(session_id)
        except Exception:
            pass

    def finalize_bot_session(self, *, meeting_id: str, participant_id: str) -> None:
        """Bot 路径某个 participant 离开：结束 ASR session + 收尾"""
        if not meeting_id or not participant_id:
            return
        session_id = f"meeting:{meeting_id}:participant:{participant_id}"
        try:
            self.transcript_aggregator.unregister_session(session_id)
        except Exception as e:
            logger.error(f"[Ingest] aggregator unregister error: {e}")
        try:
            self.asr_worker.finalize_session(session_id)
        except Exception as e:
            logger.error(f"[Ingest] worker finalize error: {e}")
        try:
            self.session_manager.close_session(session_id)
        except Exception as e:
            logger.error(f"[Ingest] close_session error: {e}")
        logger.info(f"[Ingest] finalized session {session_id}")

    # -----------------------------------------------------------------------
    # WebSocket handler
    # -----------------------------------------------------------------------
    async def _handler(self, websocket: ServerConnection):
        # 路径分发：/ws/recorder/* → Bot recorder receiver，其他 → 会议/ASR
        # websockets.asyncio.server API: path 在 websocket.request.path
        path = ""
        if hasattr(websocket, "request") and websocket.request:
            path = websocket.request.path or ""
        elif hasattr(websocket, "path"):
            path = websocket.path or ""
        if path.startswith("/ws/recorder/"):
            from app.meeting_agent.audio.receiver import handle_recorder_ws
            # 注入 Gateway 自身，让 Bot receiver 复用 ASR Worker / Aggregator / broadcast
            await handle_recorder_ws(websocket, path, gateway=self)
            return

        ws_id = str(uuid.uuid4())
        self._clients[ws_id] = {"ws": websocket, "room_id": None, "user_id": None}
        logger.info(f"Client connected: {ws_id}")

        # 启动 ws ping 心跳任务：每 25s 发送 ping frame，避免被 Vite/中间代理当空闲关掉
        # 注意：用 websockets 库的 ping() 协议层帧，不进应用层消息循环
        ws_ping_task = asyncio.create_task(self._ws_ping(websocket))

        try:
            async for raw in websocket:
                if isinstance(raw, bytes):
                    await self._handle_audio_binary(ws_id, raw)
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                action = msg.get("action", "")
                if action in ("join", "leave", "chat", "summarize", "sync"):
                    await self._handle_meeting(ws_id, msg)
                elif action in ("create_session", "audio_chunk", "end_session"):
                    await self._handle_audio(ws_id, msg)
                else:
                    await self._send(ws_id, {"type": "error", "message": f"unknown action: {action}"})
        except Exception as e:
            logger.error(f"Handler error {ws_id}: {e}")
        finally:
            ws_ping_task.cancel()
            try:
                await ws_ping_task
            except asyncio.CancelledError:
                pass
            await self._cleanup(ws_id)

    async def _ws_ping(self, websocket: ServerConnection):
        """每 25s 发送一次 WebSocket ping 帧（协议层），保持连接活跃
        防止 Vite/中间代理空闲超时。应用层消息循环不会收到 ping。"""
        try:
            while True:
                await asyncio.sleep(25)
                try:
                    await websocket.ping()
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    # -----------------------------------------------------------------------
    # Meeting handlers
    # -----------------------------------------------------------------------
    async def _handle_meeting(self, ws_id: str, msg: dict):
        action = msg["action"]
        client = self._clients.get(ws_id)

        if action == "join":
            token = msg.get("token", "")
            room_id = msg.get("roomId", "")
            if not token or not room_id:
                await self._send(ws_id, {"type": "error", "message": "token 和 roomId 必填"})
                return
            payload = verify_token(token)
            if not payload:
                await self._send(ws_id, {"type": "error", "message": "Token 无效"})
                return
            user_id = payload.get("userId", "unknown")
            role = payload.get("role", "participant")
            client["room_id"] = room_id
            client["user_id"] = user_id
            self._rooms.setdefault(room_id, set()).add(ws_id)
            meeting = get_or_create_meeting(room_id)
            await self._send(ws_id, {"type": "joined", "roomId": room_id, "lastSeq": meeting["seq"]})
            # 补发房间当前的 AI Bot 状态（让中途加入的旁观者也能看到是否在录音）
            await self._send(ws_id, {"type": "ai_bot_status", **get_ai_bot(room_id)})
            # 补发房间历史消息快照（chat + summary），让新加入的用户看到进入之前的会议纪要
            # messages 已带 seq，客户端可直接灌入并去重
            await self._send(ws_id, {
                "type": "room_state_snapshot",
                "roomId": room_id,
                "lastSeq": meeting["seq"],
                "messages": list(meeting.get("messages", [])),
                "participants": list(meeting.get("participants", [])),
            })
            audit_log("join", user_id, room_id, f"role={role}")
            logger.info(f"[WS] {user_id} joined {room_id} ({role})")

        elif action == "leave":
            if client and client.get("room_id"):
                room_id = client["room_id"]
                self._rooms.get(room_id, set()).discard(ws_id)
                audit_log("leave", client.get("user_id", "?"), room_id)
                client["room_id"] = None

        elif action == "chat":
            if not client or not client.get("room_id"):
                await self._send(ws_id, {"type": "error", "message": "未加入会议"})
                return
            token = msg.get("token", "")
            if not verify_token(token):
                await self._send(ws_id, {"type": "error", "message": "Token 无效"})
                return
            room_id = client["room_id"]
            sender = msg.get("sender", "unknown")
            content = msg.get("content", "")
            chat_msg = add_message(room_id, {
                "sender": sender, "content": content,
                "timestamp": int(time.time() * 1000), "type": "text",
            })
            await self._broadcast(room_id, {"type": "chat", "payload": chat_msg})

        elif action == "summarize":
            if not client or not client.get("room_id"):
                await self._send(ws_id, {"type": "error", "message": "未加入会议"})
                return
            token = msg.get("token", "")
            if not is_moderator(token):
                await self._send(ws_id, {"type": "error", "message": "只有主持人可以生成会议总结"})
                return
            payload = verify_token(token)
            room_id = client["room_id"]
            messages = get_all_messages(room_id)
            await self._send(ws_id, {"type": "status", "message": "正在生成会议总结..."})

            def _do():
                loop = asyncio.new_event_loop()
                summary = loop.run_until_complete(generate_summary(room_id, messages))
                # 空消息时 generate_summary 返回占位文案 "本次会议暂无聊天记录。"
                # 不持久化也不广播，避免下一个人加入看到一条无意义的 summary。
                if not messages or summary == "本次会议暂无聊天记录。":
                    asyncio.run_coroutine_threadsafe(
                        self._send(ws_id, {"type": "status", "message": "本次会议暂无聊天记录，已省略总结。"}),
                        self._loop,
                    )
                    return
                # summary 也走 add_message，自动获得 seq + 持久化，
                # 让后加入的用户能通过 sync/snapshot 拉到历史总结
                summary_msg = add_message(room_id, {
                    "sender": "AI 助手", "content": summary,
                    "timestamp": int(time.time() * 1000), "type": "summary",
                })
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(room_id, {"type": "summary", "roomId": room_id, "summary": summary, "timestamp": summary_msg["timestamp"], "seq": summary_msg["seq"]}),
                    self._loop,
                )
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(room_id, {"type": "chat", "payload": summary_msg}),
                    self._loop,
                )
            threading.Thread(target=_do, daemon=True).start()

        elif action == "sync":
            if not client or not client.get("room_id"):
                await self._send(ws_id, {"type": "error", "message": "未加入会议"})
                return
            room_id = client["room_id"]
            last_seq = msg.get("lastSeq", 0)
            missed = get_messages_after_seq(room_id, last_seq)
            await self._send(ws_id, {"type": "synced", "messages": missed})

    # -----------------------------------------------------------------------
    # Audio handlers
    # -----------------------------------------------------------------------
    async def _process_and_submit_audio(
        self, session_id: str, audio_bytes: bytes, sample_rate: int
    ) -> None:
        """后台处理 audio_chunk：VAD/降噪 + 提交到 ASR worker。
        被 _handle_audio 的 audio_chunk 分支以 fire-and-forget 方式调用，
        避免阻塞 WS 主循环。"""
        try:
            audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
            processed = await asyncio.to_thread(
                self.audio_processor.process, audio_np, sample_rate, session_id
            )
            # 关键：只要有音频帧进来（无论 VAD 是否判为语音），都要刷新 aggregator
            # 的 last_update_time。否则用户句中换气时模型会返回 text=''，
            # aggregator 看到空文本不更新 last_update_time，silence_timeout 误判句尾。
            self.transcript_aggregator.touch_session(session_id)
            if not processed.get("is_speech", True):
                return
            self.asr_worker.submit_audio(
                session_id=session_id,
                audio_data=processed["audio"].tobytes(),
                sample_rate=processed["sample_rate"],
                timestamp=int(time.time() * 1000),
            )
            self.session_manager.update_session_activity(session_id)
        except Exception as e:
            logger.exception(f"[WS-DEBUG] _process_and_submit_audio exception: {e}")

    async def _handle_audio(self, ws_id: str, msg: dict):
        action = msg["action"]
        # 取当前 ws 的 client 元数据（含 room_id / user_id，由前序 join 设置）
        client = self._clients.get(ws_id)

        if action == "create_session":
            session_id = msg.get("session_id") or str(uuid.uuid4())
            logger.info(f"[WS-DEBUG] create_session: ws_id={ws_id}, session_id={session_id}, client_room_id={client.get('room_id') if client else None}")
            # 强制使用 ws client 已 join 的 room_id（不信任前端传的 meeting_id），
            # 防止前端漏传/传错导致会议间串扰
            if not client or not client.get("room_id"):
                logger.info(f"[WS-DEBUG] create_session rejected: no room_id")
                await self._send(ws_id, {
                    "type": "error",
                    "message": "未加入会议，无法开启 AI 语音识别",
                })
                return
            meeting_id = client["room_id"]
            participant_id = msg.get("participant_id", "unknown")
            participant_name = msg.get("participant_name", "Unknown")
            token = msg.get("token", "")
            # 鉴权：只有主持人（moderator）能开 AI 语音识别
            if not is_moderator(token):
                logger.info(f"[WS-DEBUG] create_session rejected: not moderator")
                audit_log("ai_bot_denied", participant_id, meeting_id, "非主持人尝试开启AI")
                await self._send(ws_id, {
                    "type": "error",
                    "message": "只有主持人可以开启 AI 语音识别",
                })
                return
            try:
                session = self.session_manager.create_session(
                    session_id=session_id, meeting_id=meeting_id,
                    participant_id=participant_id, participant_name=participant_name,
                    client_id=ws_id,
                )
                self.transcript_service.register_websocket_client(meeting_id, ws_id)
                self.transcript_aggregator.register_session(
                    session_id=session_id,
                    participant_id=participant_id,
                    participant_name=participant_name,
                    meeting_id=meeting_id,
                )
                self._rooms.setdefault(meeting_id, set()).add(ws_id)
                # 记录房间级 AI 操作者的 userId：transcript 广播时跳过该 userId 的所有 ws
                self._room_audio_operator_user[meeting_id] = participant_id
                logger.info(f"[WS-DEBUG] create_session success: {session_id}, sending session_created")
                await self._send(ws_id, {
                    "type": "session_created", "session_id": session.session_id,
                    "meeting_id": session.meeting_id,
                    "participant_id": session.participant_id,
                    "status": session.status.value,
                })
                logger.info(f"[WS-DEBUG] session_created sent")
                # 房间级 AI Bot 状态：更新 + 广播给所有房间成员
                bot_state = set_ai_bot(meeting_id, "started", participant_id)
                await self._broadcast(meeting_id, {"type": "ai_bot_status", **bot_state})
            except Exception as e:
                logger.exception(f"[WS-DEBUG] create_session exception: {e}")
                await self._send(ws_id, {"type": "error", "message": str(e)})

        elif action == "audio_chunk":
            session_id = msg.get("session_id")
            if not session_id:
                return
            session = self.session_manager.get_session(session_id)
            if not session or session.status == SessionStatus.CLOSED:
                return
            if session.status == SessionStatus.CREATED:
                session.mark_streaming()
            audio_b64 = msg.get("audio")
            if not audio_b64:
                return

            # 性能修复：audio_chunk 走 fire-and-forget，不阻塞主事件循环。
            # 旧版 `await asyncio.to_thread(audio_processor.process, ...)` 让 WS 主循环
            # 串行等待 VAD/降噪完成，多个 session 并发时 wsLoopLag 会飙到 600ms+ 且
            # ASR 永远拿不到数据。现在主循环只做 base64 解码 + 投递任务，立即返回。
            audio_bytes = base64.b64decode(audio_b64)
            sample_rate = msg.get("sample_rate", 16000)
            # 投递到线程池，不 await 结果
            asyncio.ensure_future(
                self._process_and_submit_audio(session_id, audio_bytes, sample_rate)
            )

        elif action == "end_session":
            session_id = msg.get("session_id")
            if session_id:
                session = self.session_manager.get_session(session_id)
                if session:
                    # finalize 会跑模型推理（秒级），必须放到线程，否则整个网关卡死
                    await asyncio.to_thread(
                        self._finalize_session_blocking, session_id, ws_id, session.meeting_id
                    )

    def _finalize_session_blocking(self, session_id: str, ws_id: str, meeting_id: str) -> None:
        """同步收尾逻辑（在线程池执行）：注销聚合器 → 模型 finalize → 关闭 session"""
        try:
            # 通知 Aggregator 注销会话（会发送最终语句）
            self.transcript_aggregator.unregister_session(session_id)
            # 通知 ASR Worker 结束 session
            self.asr_worker.finalize_session(session_id)
            # 释放 per-session VAD 状态
            self.audio_processor.release_session(session_id)
        except Exception as e:
            logger.error(f"End session error: {e}")
        self.session_manager.close_session(session_id)
        self.transcript_service.unregister_websocket_client(meeting_id, ws_id)
        # 清理房间级 AI 操作者记录
        # 关键：必须按 session_id 查 session 的 participant_id，再判断是否清标记，
        # 避免「A 房间有 A1、A2 两个参会者，A1 end_session 时把 A2 的标记也清了」。
        # 修复：只有当记录的 userId 仍指向本会话的 participantId 时才清
        try:
            session = self.session_manager.get_session(session_id)
            if session and meeting_id in self._room_audio_operator_user:
                if self._room_audio_operator_user[meeting_id] == session.participant_id:
                    del self._room_audio_operator_user[meeting_id]
        except Exception:
            pass  # 静默失败，不影响清理
        # 房间级 AI Bot 状态：恢复 idle + 广播
        # ⚠️ 此函数在 asyncio.to_thread 线程池里执行，
        # 必须用 self._loop（主事件循环），不能用 asyncio.get_event_loop()
        # （后者在 Python 3.12+ 已废弃并在新线程里会返回新 loop / 报错）
        bot_state = set_ai_bot(meeting_id, "idle", None)
        try:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(meeting_id, {"type": "ai_bot_status", **bot_state}),
                    self._loop,
                )
            else:
                logger.warning("[finalize] main event loop not available, ai_bot_status idle broadcast skipped")
        except Exception as e:
            logger.error(f"[finalize] broadcast ai_bot_status idle error: {e}")

    async def _handle_audio_binary(self, ws_id: str, data: bytes):
        pass  # 备选：二进制音频

    async def _heartbeat(self) -> None:
        """每秒打一次事件循环心跳；滞后过大说明有同步代码阻塞了事件循环"""
        global _loop_last_tick
        while True:
            now = time.time()
            if _loop_last_tick and now - _loop_last_tick > 5:
                logger.warning(
                    f"Event loop stalled for {now - _loop_last_tick:.1f}s "
                    f"(同步阻塞调用未放入线程池?)"
                )
            _loop_last_tick = now
            await asyncio.sleep(1)

    # -----------------------------------------------------------------------
    # Cleanup & helpers
    # -----------------------------------------------------------------------
    async def _cleanup(self, ws_id: str):
        client = self._clients.pop(ws_id, None)
        if client and client.get("room_id"):
            self._rooms.get(client["room_id"], set()).discard(ws_id)
        for sid in self.session_manager.get_sessions_by_client(ws_id):
            session = self.session_manager.get_session(sid)
            if session:
                self.transcript_aggregator.unregister_session(sid)
                self.session_manager.close_session(sid)
                self.transcript_service.unregister_websocket_client(session.meeting_id, ws_id)
                self._rooms.get(session.meeting_id, set()).discard(ws_id)
        logger.info(f"Client disconnected: {ws_id}")

    async def _send(self, ws_id: str, data: dict):
        client = self._clients.get(ws_id)
        if client:
            try:
                await client["ws"].send(json.dumps(data))
            except Exception:
                pass

    async def _broadcast(self, room_id: str, data: dict):
        msg = json.dumps(data)
        for ws_id in list(self._rooms.get(room_id, set())):
            client = self._clients.get(ws_id)
            if client:
                try:
                    await client["ws"].send(msg)
                except Exception:
                    pass

    # -----------------------------------------------------------------------
    # Start / Stop
    # -----------------------------------------------------------------------
    def start(self) -> None:
        logger.info(f"Starting WebSocket Gateway on {self.config.host}:{self.config.port}")

        # 启动 Socket.IO（用于房间级 ai_bot_status / meeting_transcript 广播）
        try:
            from flask_socketio import SocketIO
            from app.meeting_ws import register_meeting_handlers
            from app.meeting_state import get_ai_bot

            socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode="threading")
            register_meeting_handlers(socketio)
            # 注入 Socket.IO 到本 server，让 Aggregator 推送 transcript_final 时也广播
            self.set_socketio(socketio)

            flask_runner = lambda: socketio.run(
                self.app, host="127.0.0.1", port=self.config.port + 2,
                debug=False, use_reloader=False, allow_unsafe_werkzeug=True,
            )
            logger.info("Socket.IO enabled (room broadcast)")
        except Exception as e:
            logger.warning(f"Socket.IO 启动失败，回退到裸 Flask: {e}")
            flask_runner = lambda: self.app.run(
                host="127.0.0.1", port=self.config.port + 2, debug=False, use_reloader=False,
            )

        flask_port = self.config.port + 2
        threading.Thread(target=flask_runner, daemon=True).start()
        logger.info(f"Flask HTTP API on 127.0.0.1:{flask_port}")

        # WebSocket 主线程（启用 SSL，因为前端是 HTTPS 页面）
        async def _run():
            global _main_loop
            self._loop = asyncio.get_running_loop()
            _main_loop = self._loop
            asyncio.create_task(self._heartbeat())

            # SSL 配置：使用前端相同的证书（覆盖 192.0.36.227）
            ssl_ctx = None
            cert_dir = os.environ.get("SSL_CERT_DIR", "")
            if cert_dir:
                cert_path = os.path.join(cert_dir, "localhost+3.pem")
                key_path = os.path.join(cert_dir, "localhost+3-key.pem")
                if os.path.exists(cert_path) and os.path.exists(key_path):
                    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ssl_ctx.load_cert_chain(cert_path, key_path)
                    logger.info(f"SSL enabled with cert: {cert_path}")
                else:
                    logger.warning("SSL cert not found, running without SSL")

            async with serve(self._handler, self.config.host, self.config.port, ssl=ssl_ctx):
                proto = "wss" if ssl_ctx else "ws"
                logger.info(f"WebSocket listening on {proto}://{self.config.host}:{self.config.port}")
                await asyncio.Future()

        asyncio.run(_run())

    def stop(self) -> None:
        logger.info("Stopping WebSocket Gateway...")
        self.transcript_aggregator.stop()
        self.asr_worker.stop()
