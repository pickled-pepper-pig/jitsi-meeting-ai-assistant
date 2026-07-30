# 会议 WebSocket 处理器 - chat / join / leave / summarize / sync

import json
import logging
import time
from typing import Dict, Set, Optional, Any

from flask_socketio import emit, join_room, leave_room
from flask import request

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

# ---------------------------------------------------------------------------
# 连接会话管理
# ---------------------------------------------------------------------------
# sid -> { room_id, user_id }
_sessions: Dict[str, Dict[str, Optional[str]]] = {}
# room_id -> set of sid
_room_clients: Dict[str, Set[str]] = {}


def register_meeting_handlers(socketio) -> None:
    """将会议相关的 WebSocket 事件注册到 socketio"""

    @socketio.on("meeting_join")
    def handle_join(data):
        sid = request.sid
        token = data.get("token", "")
        room_id = data.get("roomId", "")

        if not token or not room_id:
            emit("meeting_error", {"message": "token 和 roomId 必填"})
            return

        payload = verify_token(token)
        if not payload:
            emit("meeting_error", {"message": "Token 无效"})
            return

        user_id = payload.get("userId", "unknown")
        role = payload.get("role", "participant")

        _sessions[sid] = {"room_id": room_id, "user_id": user_id}

        if room_id not in _room_clients:
            _room_clients[room_id] = set()
        _room_clients[room_id].add(sid)

        join_room(room_id)

        meeting = get_or_create_meeting(room_id)
        emit("meeting_joined", {
            "roomId": room_id,
            "lastSeq": meeting["seq"],
        })
        # 补发房间当前的 AI Bot 状态（让中途加入的人也能看到是否在录音）
        from app.meeting_state import get_ai_bot
        emit("ai_bot_status", get_ai_bot(room_id))

        audit_log("join", user_id, room_id, f"role={role}")
        logger.info(f"[WS] 用户 {user_id} 加入房间 {room_id}（角色: {role}）")

    @socketio.on("meeting_leave")
    def handle_leave(data):
        sid = request.sid
        session = _sessions.get(sid)
        if not session or not session.get("room_id"):
            return

        room_id = session["room_id"]
        user_id = session.get("user_id", "unknown")

        clients = _room_clients.get(room_id)
        if clients:
            clients.discard(sid)
            if not clients:
                _room_clients.pop(room_id, None)

        leave_room(room_id)
        audit_log("leave", user_id, room_id)
        logger.info(f"[WS] 用户 {user_id} 离开房间 {room_id}")

    @socketio.on("meeting_chat")
    def handle_chat(data):
        sid = request.sid
        session = _sessions.get(sid)
        if not session or not session.get("room_id"):
            emit("meeting_error", {"message": "未加入会议"})
            return

        token = data.get("token", "")
        payload = verify_token(token)
        if not payload:
            emit("meeting_error", {"message": "Token 无效"})
            return

        room_id = session["room_id"]
        sender = data.get("sender", "unknown")
        content = data.get("content", "")

        chat_message = add_message(room_id, {
            "sender": sender,
            "content": content,
            "timestamp": int(time.time() * 1000),
            "type": "text",
        })

        # 广播给房间内所有客户端
        socketio.emit("meeting_chat", {"payload": chat_message}, room=room_id)
        logger.info(f"[CHAT] [{room_id}] {sender}: {content[:50]}")

    @socketio.on("meeting_summarize")
    def handle_summarize(data):
        sid = request.sid
        session = _sessions.get(sid)
        if not session or not session.get("room_id"):
            emit("meeting_error", {"message": "未加入会议"})
            return

        token = data.get("token", "")
        if not is_moderator(token):
            emit("meeting_error", {"message": "只有主持人可以生成会议总结"})
            audit_log("summarize_denied", "unknown", session["room_id"], "非主持人尝试总结")
            return

        payload = verify_token(token)
        room_id = session["room_id"]
        audit_log("summarize_start", payload["userId"] if payload else "unknown", room_id)

        messages = get_all_messages(room_id)
        emit("meeting_status", {"message": "正在生成会议总结..."})

        # 异步生成总结
        import eventlet

        def _do_summarize():
            loop = _get_or_create_loop()
            summary = loop.run_until_complete(generate_summary(room_id, messages))

            # 空消息时 generate_summary 返回占位文案 "本次会议暂无聊天记录。"
            # 不持久化也不广播，避免下一个人加入看到一条无意义的 summary。
            if not messages or summary == "本次会议暂无聊天记录。":
                socketio.emit("meeting_status", {"message": "本次会议暂无聊天记录，已省略总结。"}, room=sid)
                return

            summary_message = add_message(room_id, {
                "sender": "AI 助手",
                "content": summary,
                "timestamp": int(time.time() * 1000),
                "type": "summary",
            })

            socketio.emit("meeting_summary", {
                "roomId": room_id,
                "summary": summary,
                "timestamp": int(time.time() * 1000),
            }, room=room_id)

            socketio.emit("meeting_chat", {"payload": summary_message}, room=room_id)
            audit_log("summarize_done", payload["userId"] if payload else "unknown", room_id)

        eventlet.spawn(_do_summarize)

    @socketio.on("meeting_sync")
    def handle_sync(data):
        sid = request.sid
        session = _sessions.get(sid)
        if not session or not session.get("room_id"):
            emit("meeting_error", {"message": "未加入会议"})
            return

        room_id = session["room_id"]
        last_seq = data.get("lastSeq", 0)

        missed = get_messages_after_seq(room_id, last_seq)
        emit("meeting_synced", {"messages": missed})
        logger.info(f"[SYNC] 房间 {room_id} 补齐 {len(missed)} 条消息（lastSeq={last_seq}）")

    @socketio.on("disconnect")
    def handle_meeting_disconnect():
        sid = request.sid
        session = _sessions.pop(sid, None)
        if session and session.get("room_id"):
            room_id = session["room_id"]
            clients = _room_clients.get(room_id)
            if clients:
                clients.discard(sid)
                if not clients:
                    _room_clients.pop(room_id, None)


def broadcast_to_room(socketio, room_id: str, message: Dict[str, Any]) -> None:
    """向指定房间广播消息"""
    socketio.emit("meeting_message", message, room=room_id)


def _get_or_create_loop():
    """获取或创建 asyncio event loop"""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


import asyncio
