# SQLite 持久化 - 会议数据落库（7 张表）
#
# 表关系：
#   meetings
#     ├── 1:N → meeting_participants
#     ├── 1:N → transcript_messages
#     ├── 1:N → chat_messages
#     ├── 1:N → asr_sessions
#     ├── 1:N → bot_instances
#     └── 1:N → audio_recordings
#
# 设计原则：
#   - SQLite 写入异步执行，不阻塞实时链路（ASR → Redis → WebSocket → 用户）
#   - 只存 final 结果，不存 partial（partial 在内存中处理）
#   - meeting_id 用 INTEGER 自增主键，room_id 是 Jitsi 房间号（可重复使用）

import json
import logging
import socket
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# .db 文件路径：项目根目录 data/meeting.db
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_DB_DIR = _PROJECT_ROOT / "data"
_DB_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = str(_DB_DIR / "meeting.db")

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_executor: Optional[threading.Thread] = None
_queue: List[tuple] = []
_queue_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 连接 & 建表
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")       # WAL 模式：读写不互斥
        _conn.execute("PRAGMA foreign_keys=ON")
        _init_db(_conn)
        logger.info(f"[SQLite] 已连接 {_DB_PATH}")
    return _conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    -- 1. meetings（会议表）
    CREATE TABLE IF NOT EXISTS meetings (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id               TEXT NOT NULL,
        status                TEXT DEFAULT 'created',        -- created / running / finished
        first_moderator_id    TEXT,
        first_moderator_name  TEXT,
        config_json           TEXT,                          -- {"asr_model":"paraformer","ai_enabled":true}
        started_at            INTEGER,
        ended_at              INTEGER,
        created_at            TEXT DEFAULT (datetime('now', 'localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_meetings_room ON meetings (room_id);

    -- 2. meeting_participants（参会者表）
    CREATE TABLE IF NOT EXISTS meeting_participants (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id            INTEGER NOT NULL REFERENCES meetings(id),
        user_id               TEXT,
        jitsi_participant_id  TEXT,
        display_name          TEXT,
        role                  TEXT DEFAULT 'participant',    -- moderator / participant
        joined_at             INTEGER,
        left_at               INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_mp_meeting ON meeting_participants (meeting_id);

    -- 3. transcript_messages（ASR 转写表，独立于聊天）
    CREATE TABLE IF NOT EXISTS transcript_messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id      INTEGER NOT NULL REFERENCES meetings(id),
        asr_session_id  TEXT,
        speaker_id      TEXT,               -- Bot 分配的 speaker_id
        speaker_name    TEXT,
        content         TEXT,
        is_final        INTEGER DEFAULT 1,
        seq             INTEGER,
        start_time_ms   INTEGER,            -- 音频段相对会议开始的偏移
        end_time_ms     INTEGER,
        timestamp       INTEGER,
        created_at      TEXT DEFAULT (datetime('now', 'localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_tm_meeting ON transcript_messages (meeting_id);
    CREATE INDEX IF NOT EXISTS idx_tm_session ON transcript_messages (asr_session_id);

    -- 4. chat_messages（Jitsi 聊天 + 会议总结）
    CREATE TABLE IF NOT EXISTS chat_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id  INTEGER NOT NULL REFERENCES meetings(id),
        user_id     TEXT,
        user_name   TEXT,
        type        TEXT NOT NULL,          -- chat / summary
        content     TEXT,
        seq         INTEGER,
        timestamp   INTEGER,
        created_at  TEXT DEFAULT (datetime('now', 'localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_cm_meeting ON chat_messages (meeting_id);

    -- 5. asr_sessions（ASR 会话表）
    CREATE TABLE IF NOT EXISTS asr_sessions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id    INTEGER NOT NULL REFERENCES meetings(id),
        speaker_id    TEXT,
        session_id    TEXT UNIQUE,
        model         TEXT,
        status        TEXT DEFAULT 'active',   -- active / ended
        sample_rate   INTEGER DEFAULT 16000,
        channels      INTEGER DEFAULT 1,
        started_at    INTEGER,
        ended_at      INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_as_meeting ON asr_sessions (meeting_id);

    -- 6. bot_instances（Bot 实例表，1:N 与 meeting）
    CREATE TABLE IF NOT EXISTS bot_instances (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id  INTEGER NOT NULL REFERENCES meetings(id),
        bot_id      TEXT,
        status      TEXT,                     -- spawning / running / killed / failed / stale
        started_by  TEXT,
        hostname    TEXT,
        started_at  INTEGER,
        stopped_at  INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_bi_meeting ON bot_instances (meeting_id);

    -- 7. audio_recordings（录音文件表）
    CREATE TABLE IF NOT EXISTS audio_recordings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id      INTEGER NOT NULL REFERENCES meetings(id),
        asr_session_id  TEXT,
        file_path       TEXT,
        duration_sec    REAL,
        sample_rate     INTEGER DEFAULT 16000,
        status          TEXT DEFAULT 'recording',  -- recording / completed / failed
        created_at      TEXT DEFAULT (datetime('now', 'localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_ar_meeting ON audio_recordings (meeting_id);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# 异步写入队列
# ---------------------------------------------------------------------------

def _async_execute(fn, *args):
    """把写操作丢到队列，后台线程异步执行，不阻塞调用方"""
    with _queue_lock:
        _queue.append((fn, args))
        if _executor is None or not _executor.is_alive():
            _start_executor()


def _start_executor():
    global _executor
    _executor = threading.Thread(target=_drain_queue, daemon=True, name="sqlite-writer")
    _executor.start()


def _drain_queue():
    while True:
        with _queue_lock:
            if not _queue:
                break
            batch = _queue[:]
            _queue.clear()
        for fn, args in batch:
            try:
                fn(*args)
            except Exception as e:
                logger.warning(f"[SQLite] 异步写入失败: {e}")


# ---------------------------------------------------------------------------
# meetings
# ---------------------------------------------------------------------------

def upsert_meeting(room_id: str, status: str = None, first_moderator_id: str = None,
                   first_moderator_name: str = None, config_json: dict = None,
                   started_at: int = None, ended_at: int = None) -> int:
    """创建或更新会议记录，返回 meeting_id"""
    def _do():
        conn = _get_conn()
        with _lock:
            row = conn.execute("SELECT id FROM meetings WHERE room_id = ? ORDER BY id DESC LIMIT 1", (room_id,)).fetchone()
            if row:
                updates = []
                vals = []
                for col, val in [("status", status), ("first_moderator_id", first_moderator_id),
                                 ("first_moderator_name", first_moderator_name),
                                 ("config_json", json.dumps(config_json) if config_json else None),
                                 ("started_at", started_at), ("ended_at", ended_at)]:
                    if val is not None:
                        updates.append(f"{col} = ?")
                        vals.append(val)
                if updates:
                    vals.append(row["id"])
                    conn.execute(f"UPDATE meetings SET {', '.join(updates)} WHERE id = ?", vals)
                    conn.commit()
                return row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO meetings (room_id, status, first_moderator_id, first_moderator_name, config_json, started_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (room_id, status or "created", first_moderator_id, first_moderator_name,
                     json.dumps(config_json) if config_json else None, started_at or int(time.time() * 1000))
                )
                conn.commit()
                return cur.lastrowid
    return _do()


def get_meeting_id(room_id: str) -> Optional[int]:
    """通过 room_id 查 meeting_id"""
    conn = _get_conn()
    with _lock:
        row = conn.execute("SELECT id FROM meetings WHERE room_id = ? ORDER BY id DESC LIMIT 1", (room_id,)).fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# meeting_participants
# ---------------------------------------------------------------------------

def add_participant(room_id: str, user_id: str, jitsi_participant_id: str = None,
                    display_name: str = None, role: str = "participant",
                    joined_at: int = None) -> None:
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "INSERT INTO meeting_participants (meeting_id, user_id, jitsi_participant_id, display_name, role, joined_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (meeting_id, user_id, jitsi_participant_id, display_name, role, joined_at or int(time.time() * 1000))
            )
            conn.commit()
    _async_execute(_do)


def update_participant_left(room_id: str, user_id: str) -> None:
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "UPDATE meeting_participants SET left_at = ? WHERE meeting_id = ? AND user_id = ? AND left_at IS NULL",
                (int(time.time() * 1000), meeting_id, user_id)
            )
            conn.commit()
    _async_execute(_do)


# ---------------------------------------------------------------------------
# transcript_messages
# ---------------------------------------------------------------------------

def save_transcript(room_id: str, speaker_id: str = None, speaker_name: str = None,
                    content: str = None, asr_session_id: str = None, seq: int = None,
                    timestamp: int = None, start_time_ms: int = None, end_time_ms: int = None) -> None:
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "INSERT INTO transcript_messages "
                "(meeting_id, asr_session_id, speaker_id, speaker_name, content, is_final, seq, start_time_ms, end_time_ms, timestamp) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (meeting_id, asr_session_id, speaker_id, speaker_name, content, seq, start_time_ms, end_time_ms,
                 timestamp or int(time.time() * 1000))
            )
            conn.commit()
    _async_execute(_do)


# ---------------------------------------------------------------------------
# chat_messages
# ---------------------------------------------------------------------------

def save_chat(room_id: str, msg_type: str, user_id: str = None, user_name: str = None,
              content: str = None, seq: int = None, timestamp: int = None) -> None:
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "INSERT INTO chat_messages (meeting_id, user_id, user_name, type, content, seq, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (meeting_id, user_id, user_name, msg_type, content, seq, timestamp or int(time.time() * 1000))
            )
            conn.commit()
    _async_execute(_do)


# ---------------------------------------------------------------------------
# asr_sessions
# ---------------------------------------------------------------------------

def save_asr_session(room_id: str, session_id: str, speaker_id: str = None,
                     model: str = None, sample_rate: int = 16000, channels: int = 1) -> None:
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "INSERT OR REPLACE INTO asr_sessions "
                "(meeting_id, speaker_id, session_id, model, status, sample_rate, channels, started_at) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (meeting_id, speaker_id, session_id, model, sample_rate, channels, int(time.time() * 1000))
            )
            conn.commit()
    _async_execute(_do)


def end_asr_session(session_id: str) -> None:
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "UPDATE asr_sessions SET status = 'ended', ended_at = ? WHERE session_id = ?",
                (int(time.time() * 1000), session_id)
            )
            conn.commit()
    _async_execute(_do)


# ---------------------------------------------------------------------------
# bot_instances
# ---------------------------------------------------------------------------

def save_bot_instance(room_id: str, bot_id: str, status: str, started_by: str = None,
                      started_at: int = None, stopped_at: int = None) -> None:
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    hostname = socket.gethostname()
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "INSERT INTO bot_instances (meeting_id, bot_id, status, started_by, hostname, started_at, stopped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (meeting_id, bot_id, status, started_by, hostname, started_at or int(time.time() * 1000), stopped_at)
            )
            conn.commit()
    _async_execute(_do)


def update_bot_status(bot_id: str, status: str, stopped_at: int = None) -> None:
    def _do():
        conn = _get_conn()
        with _lock:
            # SQLite UPDATE 不支持 ORDER BY LIMIT，用子查询取最新一条
            conn.execute(
                "UPDATE bot_instances SET status = ?, stopped_at = ? "
                "WHERE id = (SELECT id FROM bot_instances WHERE bot_id = ? ORDER BY id DESC LIMIT 1)",
                (status, stopped_at, bot_id)
            )
            conn.commit()
    _async_execute(_do)


# ---------------------------------------------------------------------------
# audio_recordings
# ---------------------------------------------------------------------------

def save_recording(room_id: str, asr_session_id: str, file_path: str,
                   sample_rate: int = 16000) -> None:
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    def _do():
        conn = _get_conn()
        with _lock:
            conn.execute(
                "INSERT INTO audio_recordings (meeting_id, asr_session_id, file_path, sample_rate, status) "
                "VALUES (?, ?, ?, ?, 'recording')",
                (meeting_id, asr_session_id, file_path, sample_rate)
            )
            conn.commit()
    _async_execute(_do)


def update_recording_status(file_path: str, status: str, duration_sec: float = None) -> None:
    def _do():
        conn = _get_conn()
        with _lock:
            if duration_sec is not None:
                conn.execute(
                    "UPDATE audio_recordings SET status = ?, duration_sec = ? WHERE file_path = ?",
                    (status, duration_sec, file_path)
                )
            else:
                conn.execute(
                    "UPDATE audio_recordings SET status = ? WHERE file_path = ?",
                    (status, file_path)
                )
            conn.commit()
    _async_execute(_do)


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------

def clear_room_data(room_id: str) -> None:
    """清空指定房间的所有数据（会议重建时调用）"""
    meeting_id = get_meeting_id(room_id)
    if not meeting_id:
        return
    def _do():
        conn = _get_conn()
        with _lock:
            for tbl in ["transcript_messages", "chat_messages", "meeting_participants",
                        "asr_sessions", "bot_instances", "audio_recordings"]:
                conn.execute(f"DELETE FROM {tbl} WHERE meeting_id = ?", (meeting_id,))
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            conn.commit()
        logger.info(f"[SQLite] 已清空房间 {room_id} 的所有数据")
    _async_execute(_do)


# ---------------------------------------------------------------------------
# 兼容旧接口（messages 表 → 路由到 transcript / chat）
# ---------------------------------------------------------------------------

def save_message(message: Dict[str, Any]) -> None:
    """兼容旧 add_message 调用，按 type 路由到 transcript / chat"""
    room_id = message.get("roomId", "")
    msg_type = message.get("type", "")
    seq = message.get("seq", 0)
    timestamp = message.get("timestamp")
    content = message.get("text") or message.get("content", "")

    if msg_type in ("transcript", "transcript_final"):
        save_transcript(
            room_id=room_id,
            speaker_id=message.get("participant_id"),
            speaker_name=message.get("participant_name") or message.get("sender"),
            content=content,
            asr_session_id=message.get("session_id"),
            seq=seq, timestamp=timestamp,
        )
    else:
        save_chat(
            room_id=room_id,
            msg_type=msg_type,
            user_id=message.get("userId"),
            user_name=message.get("userName"),
            content=content,
            seq=seq, timestamp=timestamp,
        )


def get_db_path() -> str:
    return _DB_PATH
