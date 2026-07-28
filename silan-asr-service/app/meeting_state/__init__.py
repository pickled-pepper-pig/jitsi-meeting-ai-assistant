# 会议状态管理 - 内存 + Redis 降级

import json
import logging
import time
import threading
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis 可选导入
# ---------------------------------------------------------------------------
_redis_client = None
_redis_enabled = False

try:
    import redis

    _redis_client = redis.Redis.from_url(
        "redis://localhost:6379", decode_responses=True
    )
    _redis_client.ping()
    _redis_enabled = True
    logger.info("[Redis] 连接成功")
except Exception:
    logger.warning("[Redis] 连接失败，降级到内存模式")
    _redis_client = None
    _redis_enabled = False

REDIS_KEY_PREFIX = "meeting:"
REDIS_TTL = 24 * 60 * 60  # 24h

# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------
_meetings: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _redis_key(room_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}{room_id}"


def _save_to_redis(room_id: str, meeting: Dict[str, Any]) -> None:
    if not (_redis_enabled and _redis_client):
        return
    try:
        _redis_client.set(_redis_key(room_id), json.dumps(meeting, ensure_ascii=False), ex=REDIS_TTL)
    except Exception:
        logger.warning("[Redis] 写入失败")


def _load_from_redis(room_id: str) -> Optional[Dict[str, Any]]:
    if not (_redis_enabled and _redis_client):
        return None
    try:
        cached = _redis_client.get(_redis_key(room_id))
        if cached:
            return json.loads(cached)
    except Exception:
        logger.warning("[Redis] 读取失败")
    return None


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------

def get_or_create_meeting(room_id: str) -> Dict[str, Any]:
    """获取或创建会议状态"""
    with _lock:
        # 先查 Redis
        cached = _load_from_redis(room_id)
        if cached:
            return cached

        if room_id not in _meetings:
            _meetings[room_id] = {
                "roomId": room_id,
                "seq": 0,
                "messages": [],
                "startedAt": int(time.time() * 1000),
                "endedAt": False,
                "aiEnabled": False,
                "botStatus": "not_started",
                "participants": [],
                "asrSessions": [],
            }
        return _meetings[room_id]


def add_message(room_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
    """添加一条聊天消息"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["seq"] += 1
        full_message = {
            **message,
            "id": f"{room_id}-{meeting['seq']}-{int(time.time() * 1000)}",
            "seq": meeting["seq"],
            "roomId": room_id,
        }
        meeting["messages"].append(full_message)
        _save_to_redis(room_id, meeting)
        return full_message


def get_messages_after_seq(room_id: str, last_seq: int) -> List[Dict[str, Any]]:
    """获取 seq 之后的所有消息"""
    meeting = get_or_create_meeting(room_id)
    return [m for m in meeting["messages"] if m["seq"] > last_seq]


def get_all_messages(room_id: str) -> List[Dict[str, Any]]:
    """获取所有消息"""
    meeting = get_or_create_meeting(room_id)
    return list(meeting["messages"])


def end_meeting(room_id: str) -> None:
    """结束会议"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["endedAt"] = True
        _save_to_redis(room_id, meeting)


def enable_ai(room_id: str, user_id: str) -> None:
    """开启 AI 助手"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["aiEnabled"] = True
        meeting["botStatus"] = "starting"
        _save_to_redis(room_id, meeting)


def disable_ai(room_id: str) -> None:
    """停止 AI 助手"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["aiEnabled"] = False
        meeting["botStatus"] = "stopped"
        _save_to_redis(room_id, meeting)


def update_bot_status(room_id: str, status: str) -> None:
    """更新 Bot 状态"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["botStatus"] = status
        _save_to_redis(room_id, meeting)


def add_participant(room_id: str, participant: Dict[str, Any]) -> None:
    """注册参会者"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        existing = next((p for p in meeting["participants"] if p["id"] == participant["id"]), None)
        if not existing:
            participant.setdefault("joinedAt", int(time.time() * 1000))
            meeting["participants"].append(participant)
        else:
            existing.update(participant)
        _save_to_redis(room_id, meeting)


def remove_participant(room_id: str, participant_id: str) -> None:
    """移除参会者"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        participant = next((p for p in meeting["participants"] if p["id"] == participant_id), None)
        if participant:
            participant["leftAt"] = int(time.time() * 1000)
        _save_to_redis(room_id, meeting)


def add_asr_session(room_id: str, participant_id: str, session_id: str) -> None:
    """注册 ASR Session"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        existing = next((s for s in meeting["asrSessions"] if s["participantId"] == participant_id), None)
        if not existing:
            meeting["asrSessions"].append({"participantId": participant_id, "sessionId": session_id})
        else:
            existing["sessionId"] = session_id
        _save_to_redis(room_id, meeting)


def remove_asr_session(room_id: str, participant_id: str) -> None:
    """移除 ASR Session"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["asrSessions"] = [s for s in meeting["asrSessions"] if s["participantId"] != participant_id]
        _save_to_redis(room_id, meeting)
