import logging
import threading
import time
from typing import Dict, Optional, List
from .session import AudioSession, SessionStatus
from app.config.settings import SessionManagerConfig


logger = logging.getLogger(__name__)


class AudioSessionManager:
    def __init__(self, config: SessionManagerConfig = None):
        self.config = config or SessionManagerConfig()
        self.sessions: Dict[str, AudioSession] = {}
        self.worker_sessions: Dict[str, List[str]] = {}
        self.client_sessions: Dict[str, List[str]] = {}
        # 必须是可重入锁：部分方法（如清理逻辑）会调用其他同样加锁的方法，
        # 使用普通 Lock 会导致同一线程二次获取时永久自死锁，进而拖死整个网关。
        self.lock = threading.RLock()
        self._start_cleanup_thread()
    
    def create_session(self, session_id: str, meeting_id: str, 
                      participant_id: str, participant_name: str,
                      client_id: str = None,
                      sample_rate: int = 16000) -> AudioSession:
        with self.lock:
            if session_id in self.sessions:
                logger.warning(f"Session {session_id} already exists")
                return self.sessions[session_id]
            
            session = AudioSession(
                session_id=session_id,
                meeting_id=meeting_id,
                participant_id=participant_id,
                participant_name=participant_name,
                sample_rate=sample_rate,
                client_id=client_id
            )
            self.sessions[session_id] = session
            
            if client_id:
                if client_id not in self.client_sessions:
                    self.client_sessions[client_id] = []
                self.client_sessions[client_id].append(session_id)
            
            logger.info(f"Created session: {session_id}")
            return session
    
    def get_session(self, session_id: str) -> Optional[AudioSession]:
        with self.lock:
            return self.sessions.get(session_id)
    
    def update_session_activity(self, session_id: str) -> None:
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.update_activity()
    
    def start_streaming(self, session_id: str) -> bool:
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            session.mark_streaming()
            logger.info(f"Session {session_id} started streaming")
            return True
    
    def pause_session(self, session_id: str) -> bool:
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            session.mark_paused()
            logger.info(f"Session {session_id} paused")
            return True
    
    def resume_session(self, session_id: str) -> bool:
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            session.mark_streaming()
            logger.info(f"Session {session_id} resumed")
            return True
    
    def close_session(self, session_id: str) -> bool:
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return False

            if session.status == SessionStatus.CLOSED:
                return True

            session.mark_closed()

            if session.worker_id and session.worker_id in self.worker_sessions:
                if session_id in self.worker_sessions[session.worker_id]:
                    self.worker_sessions[session.worker_id].remove(session_id)

            if session.client_id and session.client_id in self.client_sessions:
                if session_id in self.client_sessions[session.client_id]:
                    self.client_sessions[session.client_id].remove(session_id)

            logger.info(f"Session {session_id} closed")
            return True
    
    def assign_worker(self, session_id: str, worker_id: str) -> bool:
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            if session.worker_id and session.worker_id in self.worker_sessions:
                self.worker_sessions[session.worker_id].remove(session_id)
            
            session.assign_worker(worker_id)
            
            if worker_id not in self.worker_sessions:
                self.worker_sessions[worker_id] = []
            self.worker_sessions[worker_id].append(session_id)
            
            logger.info(f"Assigned session {session_id} to worker {worker_id}")
            return True
    
    def get_sessions_by_worker(self, worker_id: str) -> List[str]:
        with self.lock:
            return self.worker_sessions.get(worker_id, [])
    
    def get_sessions_by_client(self, client_id: str) -> List[str]:
        with self.lock:
            return self.client_sessions.get(client_id, [])
    
    def get_session_count(self) -> int:
        with self.lock:
            return len(self.sessions)
    
    def get_active_sessions(self) -> List[AudioSession]:
        with self.lock:
            return [s for s in self.sessions.values() 
                    if s.status in [SessionStatus.CREATED, SessionStatus.STREAMING, SessionStatus.PAUSED]]
    
    def add_audio_buffer(self, session_id: str, audio_data) -> None:
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.add_audio_buffer(audio_data)
    
    def get_buffered_audio(self, session_id: str):
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                return session.get_buffered_audio()
        return None
    
    def _start_cleanup_thread(self) -> None:
        def cleanup():
            while True:
                time.sleep(60)
                try:
                    self._cleanup_timeout_sessions()
                except Exception as e:
                    logger.error(f"Session cleanup error: {e}", exc_info=True)

        thread = threading.Thread(target=cleanup, daemon=True, name="session-cleanup")
        thread.start()

    def _cleanup_timeout_sessions(self) -> None:
        # 锁内只做「收集」，关闭与移除放到锁外执行，避免嵌套加锁
        with self.lock:
            timeout_ids: List[str] = []
            purge_ids: List[str] = []
            for session_id, session in self.sessions.items():
                if not session.is_timeout(self.config.session_timeout_sec):
                    continue
                if session.status == SessionStatus.CLOSED:
                    purge_ids.append(session_id)
                else:
                    timeout_ids.append(session_id)

        for session_id in timeout_ids:
            logger.warning(f"Cleaning up timeout session: {session_id}")
            self.close_session(session_id)

        # 已关闭且超时的 session 彻底移除，避免 sessions 表无限增长
        if purge_ids:
            with self.lock:
                for session_id in purge_ids:
                    self.sessions.pop(session_id, None)
            logger.info(f"Purged {len(purge_ids)} closed sessions")
