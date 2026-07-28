# WebSocket Gateway Server - 原生 WebSocket 协议
# websockets 主线程处理 WebSocket，Flask 后台线程处理 HTTP API

import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from typing import Dict, Set

import numpy as np
from flask import Flask

from websockets.asyncio.server import serve, ServerConnection

from app.config.settings import AudioGatewayConfig, AppConfig, load_config
from app.audio_processor.processor import AudioProcessor
from app.session_manager.manager import AudioSessionManager
from app.session_manager.session import SessionStatus
from app.asr_worker.worker import ASRWorker
from app.transcript_service.service import TranscriptService
from app.api_routes import api_bp
from app.auth import verify_token, is_moderator
from app.meeting_state import (
    get_or_create_meeting,
    add_message,
    get_messages_after_seq,
    get_all_messages,
)
from app.audit_log import audit_log
from app.llm_service import generate_summary

logger = logging.getLogger(__name__)


class WebSocketGatewayServer:
    def __init__(self, config: AudioGatewayConfig = None):
        self.config = config or AudioGatewayConfig()
        self.app_config = load_config()

        # Flask app (HTTP API, 后台线程运行)
        self.app = Flask(__name__)
        self.app.register_blueprint(api_bp)

        # 组件
        self.audio_processor = AudioProcessor(self.app_config.audio_processor)
        self.session_manager = AudioSessionManager(self.app_config.session_manager)
        self.asr_worker = ASRWorker("ws-gateway-worker", self.app_config.asr_worker)
        self.transcript_service = TranscriptService(self.app_config.transcript_service)

        # 会议 WebSocket 状态
        self._clients: Dict[str, dict] = {}      # ws_id -> {ws, room_id, user_id}
        self._rooms: Dict[str, Set[str]] = {}    # room_id -> set of ws_id

        self.asr_worker.start()
        self._setup_transcript_callback()
        logger.info("WebSocketGatewayServer initialized (native WebSocket)")

    def _setup_transcript_callback(self) -> None:
        self.asr_worker.set_transcript_callback(self._handle_worker_results)

    def _handle_worker_results(self, results: list) -> None:
        for result in results:
            transcript = {
                "session_id": result.get("session_id"),
                "interim_text": result.get("interim_text", ""),
                "is_final": False,
                "timestamp": result.get("timestamp", int(time.time() * 1000)),
            }
            session = self.session_manager.get_session(transcript["session_id"])
            if session:
                transcript["meeting_id"] = session.meeting_id
                transcript["participant_id"] = session.participant_id
                self._broadcast_transcript(transcript, session)

    def _broadcast_transcript(self, transcript: dict, session) -> None:
        msg = json.dumps({"type": "transcript", **transcript})
        for ws_id in self._rooms.get(session.meeting_id, set()):
            client = self._clients.get(ws_id)
            if client:
                try:
                    asyncio.run_coroutine_threadsafe(
                        client["ws"].send(msg), self._loop
                    )
                except Exception as e:
                    logger.error(f"Broadcast transcript error: {e}")

    # -----------------------------------------------------------------------
    # WebSocket handler
    # -----------------------------------------------------------------------
    async def _handler(self, websocket: ServerConnection):
        ws_id = str(uuid.uuid4())
        self._clients[ws_id] = {"ws": websocket, "room_id": None, "user_id": None}
        logger.info(f"Client connected: {ws_id}")

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
            await self._cleanup(ws_id)

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
                summary_msg = add_message(room_id, {
                    "sender": "AI 助手", "content": summary,
                    "timestamp": int(time.time() * 1000), "type": "summary",
                })
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(room_id, {"type": "summary", "roomId": room_id, "summary": summary, "timestamp": int(time.time() * 1000)}),
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
    async def _handle_audio(self, ws_id: str, msg: dict):
        action = msg["action"]

        if action == "create_session":
            session_id = msg.get("session_id") or str(uuid.uuid4())
            meeting_id = msg.get("meeting_id", "default")
            participant_id = msg.get("participant_id", "unknown")
            participant_name = msg.get("participant_name", "Unknown")
            try:
                session = self.session_manager.create_session(
                    session_id=session_id, meeting_id=meeting_id,
                    participant_id=participant_id, participant_name=participant_name,
                    client_id=ws_id,
                )
                self.transcript_service.register_websocket_client(meeting_id, ws_id)
                self._rooms.setdefault(meeting_id, set()).add(ws_id)
                await self._send(ws_id, {
                    "type": "session_created", "session_id": session.session_id,
                    "meeting_id": session.meeting_id,
                    "participant_id": session.participant_id,
                    "status": session.status.value,
                })
            except Exception as e:
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
            audio_bytes = base64.b64decode(audio_b64)
            sample_rate = msg.get("sample_rate", 16000)
            audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
            processed = self.audio_processor.process(audio_np, sample_rate)
            if not processed.get("is_speech", True):
                return
            self.asr_worker.submit_audio(
                session_id=session_id,
                audio_data=processed["audio"].tobytes(),
                sample_rate=processed["sample_rate"],
                timestamp=int(time.time() * 1000),
            )
            self.session_manager.update_session_activity(session_id)

        elif action == "end_session":
            session_id = msg.get("session_id")
            if session_id:
                session = self.session_manager.get_session(session_id)
                if session:
                    try:
                        final = self.asr_worker.finalize_session(session_id)
                        if final:
                            ft = {
                                "session_id": session_id, "meeting_id": session.meeting_id,
                                "participant_id": session.participant_id,
                                "final_text": final.get("final_text", ""),
                                "is_final": True, "timestamp": int(time.time() * 1000),
                            }
                            self._broadcast_transcript(ft, session)
                    except Exception as e:
                        logger.error(f"Finalize error: {e}")
                    self.session_manager.close_session(session_id)
                    self.transcript_service.unregister_websocket_client(session.meeting_id, ws_id)

    async def _handle_audio_binary(self, ws_id: str, data: bytes):
        pass  # 备选：二进制音频

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

        # Flask HTTP API 运行在后台线程 (端口 + 2，避免与 Jitsi JVB 8081 冲突)
        flask_port = self.config.port + 2  # +2 避免与 Jitsi JVB 的 8081 端口冲突
        threading.Thread(
            target=lambda: self.app.run(host="127.0.0.1", port=flask_port, debug=False, use_reloader=False),
            daemon=True,
        ).start()
        logger.info(f"Flask HTTP API on 127.0.0.1:{flask_port}")

        # WebSocket 主线程
        async def _run():
            self._loop = asyncio.get_running_loop()
            async with serve(self._handler, self.config.host, self.config.port):
                logger.info(f"WebSocket listening on {self.config.host}:{self.config.port}")
                await asyncio.Future()

        asyncio.run(_run())

    def stop(self) -> None:
        logger.info("Stopping WebSocket Gateway...")
        self.asr_worker.stop()
