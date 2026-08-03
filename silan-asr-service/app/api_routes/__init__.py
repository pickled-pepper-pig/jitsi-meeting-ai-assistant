# HTTP API 路由 - tokens / meetings / participants / audio sessions / bot

import logging
import time
import asyncio
from flask import Blueprint, request, jsonify

from app.auth import (
    verify_token,
    is_moderator,
    generate_jitsi_token,
    generate_dev_tokens,
    generate_moderator_token,
    generate_participant_token,
)
from app.meeting_state import (
    get_or_create_meeting,
    enable_ai,
    disable_ai,
    add_participant,
    add_asr_session,
    claim_moderator,
    get_first_moderator,
    get_ai_bot,
    check_name_conflict,
    meeting_exists,
    end_meeting,
    get_asr_model,
    set_asr_model,
)
from app.audit_log import get_logs as get_audit_logs

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


def _run_async(coro, timeout: float = 30.0):
    """在主事件循环中调度协程并同步等待结果（供 Flask 路由调用 async 函数）"""
    from app.audio_gateway.ws_server import get_main_loop
    loop = get_main_loop()
    if loop is None:
        raise RuntimeError("主事件循环未启动")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@api_bp.route("/health")
def health():
    """健康检查：同时反映 WebSocket 事件循环是否存活（被同步代码卡死时返回 degraded）"""
    from app.audio_gateway.ws_server import get_loop_lag_ms

    lag_ms = get_loop_lag_ms()
    healthy = 0 <= lag_ms < 5000
    return jsonify({
        "status": "ok" if healthy else "degraded",
        "wsLoopLagMs": round(lag_ms, 1),
        "timestamp": time.time(),
    }), (200 if healthy else 503)


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
    """开发环境：生成测试 JWT Token（保留旧入口）"""
    data = request.get_json(silent=True) or {}
    room_id = data.get("roomId")
    user_id = data.get("userId")

    if not room_id or not user_id:
        return jsonify({"error": "roomId 和 userId 必填"}), 400

    tokens = generate_dev_tokens(room_id, user_id)
    return jsonify(tokens)


@api_bp.route("/api/join", methods=["POST"])
def join_meeting():
    """加入会议：服务端判定主持人资格并签发对应 token

    Body: { "roomId": "...", "userId": "...", "userName": "...", "asModerator": true/false }

    规则：
      - asModerator=true 且房间 firstModeratorId 为空 → 写入并签发 moderator token
      - asModerator=true 且 userId==firstModeratorId → 重连签发 moderator token
      - asModerator=true 且其他人已占 → 409 拒绝
      - asModerator=false → 签发 participant token（任何人随时可拿）
    """
    data = request.get_json(silent=True) or {}
    room_id = data.get("roomId")
    user_id = data.get("userId")
    user_name = data.get("userName")
    as_moderator = bool(data.get("asModerator", False))
    asr_model = data.get("asrModel") or "paraformer-zh-streaming"

    if not room_id or not user_id:
        return jsonify({"error": "roomId 和 userId 必填"}), 400

    # 用户名查重：同一 userId 视为重连，允许同名
    conflict = check_name_conflict(room_id, user_id, user_name or "")
    if conflict:
        return jsonify({
            "error": "name_conflict",
            "message": conflict,
        }), 409

    if as_moderator:
        claim = claim_moderator(room_id, user_id, user_name)
        if not claim["ok"]:
            moderator_name = claim.get("firstModeratorName") or claim["firstModeratorId"]
            return jsonify({
                "error": "moderator_occupied",
                "message": f"「{moderator_name}」已是本会议主持人。如需加入，请取消勾选「以主持人身份加入」后再试。",
                "currentModeratorId": claim["firstModeratorId"],
                "currentModeratorName": claim.get("firstModeratorName"),
            }), 409
        token = generate_moderator_token(room_id, user_id, user_name)
        # 主持人也写入 participants 表，用于后续 join 的名字查重
        add_participant(room_id, {"id": user_id, "name": user_name, "role": "moderator"})
        # 主持人设置会议的 ASR 模型
        set_asr_model(room_id, asr_model)
        return jsonify({
            "token": token,
            "role": "moderator",
            "roomId": room_id,
            "userId": user_id,
            "reconnect": claim.get("reconnect", False),
            "history_cleared": claim.get("history_cleared", False),
            "asrModel": asr_model,
        })
    else:
        # 非主持人加入：必须先有主持人创建会议
        if not meeting_exists(room_id):
            return jsonify({
                "error": "meeting_not_exists",
                "message": f"会议「{room_id}」尚未创建，请先以主持人身份创建会议",
            }), 404
        token = generate_participant_token(room_id, user_id, user_name)
        # 在 meeting_state 中顺便把参会者落表（用于后续 join 的名字查重）
        add_participant(room_id, {"id": user_id, "name": user_name, "role": "participant"})
        # 非主持人读取当前会议的 ASR 模型
        current_asr_model = get_asr_model(room_id)
        return jsonify({
            "token": token,
            "role": "participant",
            "roomId": room_id,
            "userId": user_id,
            "asrModel": current_asr_model,
        })


@api_bp.route("/api/meetings/<room_id>/moderator", methods=["GET"])
def get_meeting_moderator(room_id: str):
    """获取当前房间的主持人信息（用于前端在 join 前预判是否同人重连）"""
    meeting = get_or_create_meeting(room_id)
    moderator_id = meeting.get("firstModeratorId")
    if not moderator_id:
        return jsonify({"hasModerator": False, "roomId": room_id})
    return jsonify({
        "hasModerator": True,
        "roomId": room_id,
        "moderatorId": moderator_id,
        "moderatorName": meeting.get("firstModeratorName"),
    })


@api_bp.route("/api/meetings/<room_id>/messages", methods=["GET"])
def get_meeting_messages(room_id: str):
    """获取房间的历史消息（chat + summary）

    用于：
      - 刷新页面后通过 HTTP 兜底加载历史纪要（不依赖 WebSocket）
      - 新用户加入会议后即可看到进入之前的全部消息

    可选参数：since_seq（只返回 seq 大于该值的消息，用于增量同步）
    """
    token = request.args.get("token", "")
    if not token:
        return jsonify({"error": "token 必填"}), 400
    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401

    meeting = get_or_create_meeting(room_id)
    messages = list(meeting.get("messages", []))
    since_seq = int(request.args.get("since_seq", "0"))
    if since_seq > 0:
        messages = [m for m in messages if m.get("seq", 0) > since_seq]

    return jsonify({
        "roomId": room_id,
        "lastSeq": meeting.get("seq", 0),
        "messages": messages,
        "aiBot": get_ai_bot(room_id),
    })


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


@api_bp.route("/api/meetings/<room_id>/end", methods=["POST"])
def end_meeting_api(room_id: str):
    """结束会议：仅主持人可调。释放主持人占位 + 清空参会者，
    使同一主持人重新进入时被视为「创建新会议」，自动清空上一轮纪要。"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400
    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401
    if payload.get("role") != "moderator":
        return jsonify({"error": "只有主持人可以结束会议"}), 403
    end_meeting(room_id)
    return jsonify({"ok": True, "roomId": room_id})


@api_bp.route("/api/meetings/<room_id>/clear-history", methods=["POST"])
def clear_history_api(room_id: str):
    """清空会议纪要：仅主持人可调。
    用于异常退出（关浏览器/刷新）后重连时，主持人主动清空上一轮纪要。"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400
    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401
    if payload.get("role") != "moderator":
        return jsonify({"error": "只有主持人可以清空纪要"}), 403
    meeting = get_or_create_meeting(room_id)
    meeting["messages"] = []
    meeting["seq"] = 0
    from app.meeting_state import _save_to_redis
    _save_to_redis(room_id, meeting)
    return jsonify({"ok": True, "roomId": room_id})


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


# ---------------------------------------------------------------------------
# Meeting Agent Bot 管理
# ---------------------------------------------------------------------------

@api_bp.route("/api/meetings/<room_id>/bot/spawn", methods=["POST"])
def bot_spawn(room_id: str):
    """拉起 Recorder Bot 加入会议

    Body: { "token": "...", "roomUrl": "https://192.0.36.227:8443" }
    需要 moderator token。
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    room_url = data.get("roomUrl")

    if not token:
        return jsonify({"error": "token 必填"}), 400
    if not room_url:
        return jsonify({"error": "roomUrl 必填（Jitsi 房间 URL）"}), 400
    if not is_moderator(token):
        return jsonify({"error": "只有主持人可以拉起 Bot"}), 403

    payload = verify_token(token)
    if not payload or payload.get("room") != room_id:
        return jsonify({"error": "token 无效或与房间不匹配"}), 401

    # bot_jwt 由服务器用 bot 自己的身份重新签发，
    # 这样 Bot 永远以 "AI Assistant" 身份加会议，不依赖调用方的 token
    from app.auth import generate_jitsi_token
    bot_jwt = generate_jitsi_token(
        room_id=room_id,
        user_id=f"ai-bot-{int(time.time()*1000)}",
        user_name="AI Assistant",
        role="moderator",        # Bot 仍以 moderator 进会议（拿 owner）
    )

    try:
        from app.meeting_agent.manager.bot_manager import get_bot_manager
        bot_manager = get_bot_manager()
        bot = _run_async(
            bot_manager.spawn_bot(
                meeting_id=room_id,
                room_url=room_url,
                bot_jwt=bot_jwt,
            ),
            timeout=30.0,
        )
        return jsonify({
            "success": True,
            "botId": bot.bot_id,
            "meetingId": bot.meeting_id,
            "status": bot.status,
        })
    except Exception as e:
        logger.exception(f"Bot spawn 失败: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/api/meetings/<room_id>/bot/kill", methods=["POST"])
def bot_kill(room_id: str):
    """停止 Recorder Bot"""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not token:
        return jsonify({"error": "token 必填"}), 400
    if not is_moderator(token):
        return jsonify({"error": "只有主持人可以停止 Bot"}), 403

    try:
        from app.meeting_agent.manager.bot_manager import get_bot_manager
        bot_manager = get_bot_manager()
        killed = _run_async(bot_manager.kill_bot(room_id), timeout=10.0)
        return jsonify({
            "success": killed,
            "meetingId": room_id,
        })
    except Exception as e:
        logger.exception(f"Bot kill 失败: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/api/meetings/<room_id>/bot/status", methods=["GET"])
def bot_status(room_id: str):
    """查询 Bot 状态"""
    token = request.args.get("token", "")
    if not token:
        return jsonify({"error": "token 必填"}), 400
    if not is_moderator(token):
        return jsonify({"error": "只有主持人可以查看 Bot 状态"}), 403

    from app.meeting_agent.manager.bot_manager import get_bot_manager
    bot_manager = get_bot_manager()
    bot = bot_manager.get_bot(room_id)
    if bot is None:
        return jsonify({"meetingId": room_id, "bot": None})
    return jsonify({"meetingId": room_id, "bot": bot.to_dict()})


@api_bp.route("/api/bots", methods=["GET"])
def bot_list():
    """列出所有 Bot（调试用）"""
    from app.meeting_agent.manager.bot_manager import get_bot_manager
    bot_manager = get_bot_manager()
    bots = bot_manager.list_bots()
    return jsonify({"bots": [b.to_dict() for b in bots]})


# ---------------------------------------------------------------------------
# 调试：原始音频 dump（Bot 落盘的 Int16 LE WAV 文件下载/列出）
# 用于排查 ASR 输入原始音频形态，不进入生产路径
# ---------------------------------------------------------------------------

@api_bp.route("/api/debug/raw-audio/<meeting_id>", methods=["GET"])
def debug_list_raw_audio(meeting_id: str):
    """列出某会议在 recordings/ 下落盘的 WAV 文件（Bot 路径）"""
    from pathlib import Path
    base = Path("recordings") / meeting_id
    if not base.exists():
        return jsonify({"meeting_id": meeting_id, "files": []})
    files = []
    for p in sorted(base.glob("*.wav")):
        st = p.stat()
        files.append({
            "name": p.name,
            "path": str(p),
            "size_bytes": st.st_size,
            "mtime": int(st.st_mtime * 1000),
            "download_url": f"/api/debug/raw-audio/{meeting_id}/{p.name}",
        })
    return jsonify({"meeting_id": meeting_id, "files": files})


@api_bp.route("/api/debug/raw-audio/<meeting_id>/<filename>", methods=["GET"])
def debug_download_raw_audio(meeting_id: str, filename: str):
    """下载会议下指定的 WAV 文件（限制在 recordings/{meeting_id}/ 内，防穿越）"""
    from pathlib import Path
    from flask import send_file, abort
    # 防止 path traversal：只允许 recordings/{meeting_id}/{filename}
    if "/" in filename or ".." in filename or "\\" in filename:
        abort(400, description="非法文件名")
    p = Path("recordings") / meeting_id / filename
    if not p.exists() or not p.is_file():
        abort(404, description="文件不存在")
    return send_file(str(p), mimetype="audio/wav", as_attachment=True, download_name=filename)
