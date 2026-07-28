# 操作审计日志 - 记录关键操作

import logging
import time
from typing import List, Optional, Dict, Any
from collections import deque

logger = logging.getLogger(__name__)

MAX_LOGS = 1000
_logs: deque = deque(maxlen=MAX_LOGS)


def audit_log(action: str, user_id: str, room_id: str, detail: Optional[str] = None) -> None:
    """记录一条审计日志"""
    entry = {
        "timestamp": int(time.time() * 1000),
        "action": action,
        "userId": user_id,
        "roomId": room_id,
        "detail": detail,
    }
    _logs.append(entry)
    detail_str = f" | {detail}" if detail else ""
    logger.info(f"[AUDIT] {action} | user={user_id} | room={room_id}{detail_str}")


def get_logs(room_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取审计日志，可按 roomId 过滤"""
    if room_id:
        return [log for log in _logs if log["roomId"] == room_id]
    return list(_logs)
