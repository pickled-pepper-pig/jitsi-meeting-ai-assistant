# HTTP API 路由 - tokens / meetings / participants / audio sessions

import logging
from flask import Blueprint, request, jsonify

from app.auth import (
    verify_token,
    is_moderator,
    generate_jitsi_token,
    generate_dev_tokens,
)
from app.meeting_state import (
    get_or_create_meeting,
    enable_ai,
    disable_ai,
    add_participant,
    add_asr_session,
)
from app.audit_log import get_logs as get_audit_logs

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@api_bp.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": __import__("time").time()})


# ---------------------------------------------------------------------------
# Token 管理
# ---------------------------------------------------------------------------

@api_bp.route("/api/tokens", methods=["POST"])
def create_token():
    """获取 Jitsi JWT Token"""
    data = request.get_json(silent=True) or {}
    room_id = data.get("roomId")
    user_id = data.get("userId")
    role = data.get("role")
    user_name = data.get("userName")

    if not room_id or not user_id or not role:
        return jsonify({"error": "roomId、userId、role 必填"}), 400
    if role not in ("moderator", "participant"):
        return jsonify({"error": "role 必须是 moderator 或 participant"}), 400

    token = generate_jitsi_token(room_id, user_id, role, user_name)
    return jsonify({"token": token})


@api_bp.route("/api/tokens/verify", methods=["POST"])
def verify_token_api():
    """验证 JWT Token"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400

    payload = verify_token(token)
    if not payload:
        return jsonify({"valid": False, "error": "token 无效"}), 401
    return jsonify({"valid": True, "payload": payload})


@api_bp.route("/api/tokens/is-moderator", methods=["POST"])
def is_moderator_api():
    """检查是否为主持人"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400

    return jsonify({"isModerator": is_moderator(token)})


@api_bp.route("/api/dev/tokens", methods=["POST"])
def dev_tokens():
    """开发环境：生成测试 JWT Token"""
    data = request.get_json(silent=True) or {}
    room_id = data.get("roomId")
    user_id = data.get("userId")

    if not room_id or not user_id:
        return jsonify({"error": "roomId 和 userId 必填"}), 400

    tokens = generate_dev_tokens(room_id, user_id)
    return jsonify(tokens)


# ---------------------------------------------------------------------------
# 会议 AI 管理
# ---------------------------------------------------------------------------

@api_bp.route("/api/meetings/<room_id>/ai/start", methods=["POST"])
def ai_start(room_id: str):
    """开启 AI 助手"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400
    if not is_moderator(token):
        return jsonify({"error": "只有主持人可以开启 AI 助手"}), 403

    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401

    enable_ai(room_id, payload["userId"])
    return jsonify({
        "success": True,
        "message": "AI 助手已启动",
        "roomId": room_id,
        "startedBy": payload["userId"],
    })


@api_bp.route("/api/meetings/<room_id>/ai/stop", methods=["POST"])
def ai_stop(room_id: str):
    """停止 AI 助手"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400
    if not is_moderator(token):
        return jsonify({"error": "只有主持人可以停止 AI 助手"}), 403

    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401

    disable_ai(room_id)
    return jsonify({
        "success": True,
        "message": "AI 助手已停止",
        "roomId": room_id,
        "stoppedBy": payload["userId"],
    })


@api_bp.route("/api/meetings/<room_id>/ai/status", methods=["GET"])
def ai_status(room_id: str):
    """获取会议 AI 状态"""
    token = request.args.get("token", "")
    if not token:
        return jsonify({"error": "token 必填"}), 400

    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401

    meeting = get_or_create_meeting(room_id)
    return jsonify({
        "roomId": room_id,
        "aiEnabled": meeting["aiEnabled"],
        "botStatus": meeting["botStatus"],
        "participants": meeting["participants"],
        "asrSessions": meeting["asrSessions"],
    })


# ---------------------------------------------------------------------------
# 参会者 & ASR Session
# ---------------------------------------------------------------------------

@api_bp.route("/api/meetings/<room_id>/participants", methods=["POST"])
def register_participant(room_id: str):
    """注册参会者"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400

    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401

    participant = data.get("participant", {})
    add_participant(room_id, participant)
    return jsonify({
        "success": True,
        "message": "参会者已注册",
        "roomId": room_id,
        "participant": participant,
    })


@api_bp.route("/api/meetings/<room_id>/asr-sessions", methods=["POST"])
def register_asr_session(room_id: str):
    """注册 ASR Session"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400

    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401

    participant_id = data.get("participantId", "")
    session_id = data.get("sessionId", "")
    add_asr_session(room_id, participant_id, session_id)
    return jsonify({
        "success": True,
        "message": "ASR Session 已注册",
        "roomId": room_id,
        "participantId": participant_id,
        "sessionId": session_id,
    })


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------

@api_bp.route("/api/audit-logs", methods=["GET"])
def audit_logs_api():
    """获取审计日志"""
    room_id = request.args.get("roomId")
    logs = get_audit_logs(room_id)
    return jsonify({"logs": logs})
