from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class SessionStatus(Enum):
    UNKNOWN = "unknown"
    CREATED = "created"
    STREAMING = "streaming"
    PAUSED = "paused"
    CLOSED = "closed"


@dataclass
class AudioSession:
    session_id: str
    meeting_id: str
    participant_id: str
    participant_name: str
    sample_rate: int = 16000
    status: SessionStatus = SessionStatus.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    last_activity_at: datetime = field(default_factory=datetime.now)
    reconnect_attempts: int = 0
    worker_id: Optional[str] = None
    audio_buffer: list = field(default_factory=list)
    client_id: Optional[str] = None
    
    def update_activity(self) -> None:
        self.last_activity_at = datetime.now()
    
    def mark_streaming(self) -> None:
        self.status = SessionStatus.STREAMING
        self.update_activity()
    
    def mark_paused(self) -> None:
        self.status = SessionStatus.PAUSED
        self.update_activity()
    
    def mark_closed(self) -> None:
        self.status = SessionStatus.CLOSED
        self.update_activity()
    
    def mark_reconnecting(self) -> None:
        self.reconnect_attempts += 1
        self.update_activity()
    
    def can_reconnect(self, max_attempts: int) -> bool:
        return self.reconnect_attempts < max_attempts
    
    def is_timeout(self, timeout_sec: int) -> bool:
        elapsed = (datetime.now() - self.last_activity_at).total_seconds()
        return elapsed > timeout_sec
    
    def assign_worker(self, worker_id: str) -> None:
        self.worker_id = worker_id
    
    def add_audio_buffer(self, audio_data) -> None:
        self.audio_buffer.append(audio_data)
    
    def get_buffered_audio(self):
        if not self.audio_buffer:
            return None
        import numpy as np
        audio = np.concatenate(self.audio_buffer)
        self.audio_buffer.clear()
        return audio
