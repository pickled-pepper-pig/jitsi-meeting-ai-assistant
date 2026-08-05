# 会议状态管理 - 内存 + Redis 降级 + SQLite 持久化

import json
import logging
import time
import threading
from typing import Dict, List, Optional, Any

from app.meeting_state import sqlite_store

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
# 必须是可重入锁：enable_ai / add_message / add_participant 等函数在持锁状态下
# 会再次调用 get_or_create_meeting()。若用普通 Lock，同一线程二次获取即永久死锁，
# 锁永远不会释放，之后所有涉及会议状态的 HTTP/WebSocket 请求都会被挂死。
_lock = threading.RLock()


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

def meeting_exists(room_id: str) -> bool:
    """判断会议是否已存在（且被主持人创建过）。
    规则：firstModeratorId 为空意味着还没人创建会议，视为不存在。"""
    with _lock:
        cached = _load_from_redis(room_id)
        if cached:
            return bool(cached.get("firstModeratorId"))
        meeting = _meetings.get(room_id)
        if meeting:
            return bool(meeting.get("firstModeratorId"))
        return False


def get_asr_model(room_id: str) -> str:
    """获取会议当前使用的 ASR 模型名"""
    with _lock:
        cached = _load_from_redis(room_id)
        if cached:
            return cached.get("asrModel") or "paraformer-zh-streaming"
        meeting = _meetings.get(room_id)
        if meeting:
            return meeting.get("asrModel") or "paraformer-zh-streaming"
        return "paraformer-zh-streaming"


def set_asr_model(room_id: str, model: str) -> None:
    """设置会议使用的 ASR 模型"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["asrModel"] = model
        _save_to_redis(room_id, meeting)


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
                "firstModeratorId": None,  # 第一个以主持人身份加入的用户 ID
                "firstModeratorName": None,  # 第一个主持人的昵称（用于前端展示）
                "asrModel": "paraformer-zh-streaming",  # 会议选择的 ASR 模型
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
        sqlite_store.save_message(full_message)
        return full_message


def get_messages_after_seq(room_id: str, last_seq: int) -> List[Dict[str, Any]]:
    """获取 seq 之后的所有消息"""
    meeting = get_or_create_meeting(room_id)
    return [m for m in meeting["messages"] if m["seq"] > last_seq]


def get_all_messages(room_id: str) -> List[Dict[str, Any]]:
    """获取所有消息"""
    meeting = get_or_create_meeting(room_id)
    return list(meeting["messages"])


def clear_messages(room_id: str) -> None:
    """清空房间的历史消息，seq 归零

    用于主持人「创建会议」时清空上一轮会议的纪要，
    让本次会议的所有人（含后加入者）都从空纪要开始。
    """
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["messages"] = []
        meeting["seq"] = 0
        _save_to_redis(room_id, meeting)
        sqlite_store.clear_room_data(room_id)
        logger.info(f"[meeting_state] 已清空房间 {room_id} 的历史消息")


def end_meeting(room_id: str) -> None:
    """结束会议：释放主持人占位，清空参会者列表和历史纪要。
    这样同一房间重新进入时不会看到上一轮的会议总结/聊天/转写。"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["endedAt"] = True
        meeting["firstModeratorId"] = None
        meeting["firstModeratorName"] = None
        meeting["participants"] = []
        meeting["messages"] = []
        meeting["seq"] = 0
        _save_to_redis(room_id, meeting)
        sqlite_store.clear_room_data(room_id)
        sqlite_store.upsert_meeting(room_id, status="finished", ended_at=int(time.time() * 1000))


def set_ai_bot(room_id: str, status: str, started_by: str = None) -> Dict[str, Any]:
    """设置 AI Bot 状态（房间级别，所有人可见）

    status: 'idle' | 'starting' | 'started' | 'stopping'
    started_by: 开启 AI 的用户 ID（停止时清空）
    """
    with _lock:
        meeting = get_or_create_meeting(room_id)
        meeting["botStatus"] = status
        if status == "started" and started_by:
            meeting["aiEnabled"] = True
            meeting["aiStartedBy"] = started_by
        elif status == "idle":
            meeting["aiEnabled"] = False
            meeting["aiStartedBy"] = None
        _save_to_redis(room_id, meeting)
        return {
            "roomId": room_id,
            "status": meeting["botStatus"],
            "aiEnabled": meeting["aiEnabled"],
            "startedBy": meeting.get("aiStartedBy"),
        }


def get_ai_bot(room_id: str) -> Dict[str, Any]:
    """获取 AI Bot 当前状态（用于 sync 时补发）"""
    meeting = get_or_create_meeting(room_id)
    return {
        "roomId": room_id,
        "status": meeting.get("botStatus", "idle"),
        "aiEnabled": meeting.get("aiEnabled", False),
        "startedBy": meeting.get("aiStartedBy"),
    }


def enable_ai(room_id: str, user_id: str) -> None:
    """开启 AI 助手（兼容旧调用）"""
    set_ai_bot(room_id, "started", user_id)


def disable_ai(room_id: str) -> None:
    """停止 AI 助手（兼容旧调用）"""
    set_ai_bot(room_id, "idle", None)


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
    sqlite_store.add_participant(
        room_id=room_id,
        user_id=participant.get("id"),
        display_name=participant.get("name"),
        role=participant.get("role", "participant"),
        joined_at=participant.get("joinedAt"),
    )


def check_name_conflict(room_id: str, user_id: str, user_name: str) -> Optional[str]:
    """检查房间内用户名是否重复。

    返回：
      - None：无冲突，可以使用该名字
      - str：冲突信息，说明该名字已被谁占用（用于前端提示）

    规则：
      - 同一 userId 视为重连，允许同名（刷新页面场景）
      - 主持人名字也参与查重（避免参会者用主持人名字）
      - 不同 userId 用了同名 → 冲突
    """
    if not user_name:
        return None
    with _lock:
        meeting = get_or_create_meeting(room_id)
        # 检查主持人名字：只要有主持人同名就拒绝，不比较 user_id。
        # 重连场景（同一 user_id）由 claim_moderator 的 current==user_id 单独处理，
        # 不应该在这里放行——否则同一浏览器 localStorage 复用 userId 会绕过查重。
        mod_name = meeting.get("firstModeratorName")
        if mod_name and mod_name == user_name:
            # 例外：如果请求者就是主持人本人（user_id 匹配），允许重连
            mod_id = meeting.get("firstModeratorId")
            if mod_id and mod_id == user_id:
                return None
            return f"主持人「{mod_name}」已在会议中，请换一个名字"
        # 检查其他参会者名字
        for p in meeting["participants"]:
            if p.get("name") == user_name and p.get("id") != user_id and not p.get("leftAt"):
                return f"参会者「{user_name}」已在会议中，请换一个名字"
        return None


# ---------------------------------------------------------------------------
# 主持人占位（一个房间只有一个主持人）
# ---------------------------------------------------------------------------

def claim_moderator(room_id: str, user_id: str, user_name: Optional[str] = None) -> Dict[str, Any]:
    """尝试认领主持人位置。

    返回：
      - {"ok": True, "firstModeratorId": "...", "firstModeratorName": "..."}：成功认领（房间无主持人 / 是同一人重连）
      - {"ok": False, "firstModeratorId": "...", "firstModeratorName": "..."}：被占用了

    规则：
      - firstModeratorId 为空 → 写入并返回 ok
      - user_id == firstModeratorId → 重连场景，允许
      - 否则 → 拒绝，返回已有人 userId / userName
    """
    with _lock:
        meeting = get_or_create_meeting(room_id)
        current = meeting.get("firstModeratorId")
        if not current:
            # 首次认领 = 主持人「创建会议」：清空上一轮会议的历史纪要，
            # 让本次会议的所有人（含后加入者）都从空纪要开始。
            # 重连场景（current == user_id）不清空。
            meeting["firstModeratorId"] = user_id
            if user_name:
                meeting["firstModeratorName"] = user_name
            meeting["messages"] = []
            meeting["seq"] = 0
            _save_to_redis(room_id, meeting)
            sqlite_store.clear_room_data(room_id)
            sqlite_store.upsert_meeting(
                room_id, status="running",
                first_moderator_id=user_id, first_moderator_name=user_name,
                started_at=int(time.time() * 1000),
            )
            logger.info(f"[meeting_state] 主持人 {user_name or user_id} 创建会议 {room_id}，已清空历史纪要")
            return {
                "ok": True,
                "firstModeratorId": user_id,
                "firstModeratorName": meeting.get("firstModeratorName"),
            }
        if current == user_id:
            # 重连场景：根据上次会议是否正常结束决定是否清空纪要
            ended = meeting.get("endedAt", False)
            if ended:
                # 上次已正常结束（点了离开/挂断），本次视为新一轮会议：清空纪要
                meeting["messages"] = []
                meeting["seq"] = 0
                meeting["endedAt"] = False
                meeting["participants"] = []
                _save_to_redis(room_id, meeting)
                sqlite_store.clear_room_data(room_id)
                logger.info(f"[meeting_state] 主持人 {user_name or user_id} 重连会议 {room_id}（上次已结束），清空历史纪要")
            return {
                "ok": True,
                "firstModeratorId": current,
                "firstModeratorName": meeting.get("firstModeratorName"),
                "reconnect": True,
                "history_cleared": ended,
            }
        return {
            "ok": False,
            "firstModeratorId": current,
            "firstModeratorName": meeting.get("firstModeratorName"),
        }


def get_first_moderator(room_id: str) -> Optional[str]:
    """获取当前房间的主持人 userId（无则返回 None）"""
    meeting = get_or_create_meeting(room_id)
    return meeting.get("firstModeratorId")


def remove_participant(room_id: str, participant_id: str) -> None:
    """移除参会者"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        participant = next((p for p in meeting["participants"] if p["id"] == participant_id), None)
        if participant:
            participant["leftAt"] = int(time.time() * 1000)
        _save_to_redis(room_id, meeting)
    sqlite_store.update_participant_left(room_id, participant_id)


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
    model = meeting.get("asrModel", "paraformer-zh-streaming")
    sqlite_store.save_asr_session(room_id, session_id, speaker_id=participant_id, model=model)


def remove_asr_session(room_id: str, participant_id: str) -> None:
    """移除 ASR Session"""
    with _lock:
        meeting = get_or_create_meeting(room_id)
        session = next((s for s in meeting["asrSessions"] if s["participantId"] == participant_id), None)
        meeting["asrSessions"] = [s for s in meeting["asrSessions"] if s["participantId"] != participant_id]
        _save_to_redis(room_id, meeting)
    if session:
        sqlite_store.end_asr_session(session.get("sessionId"))
