"""
Transcript Aggregator - 将 ASR 流式片段聚合成完整句子

架构：
  FunASR → TranscriptAggregator → WebSocket → Frontend

功能：
  1. partial 合并：将多个 ASR 片段合并为当前语句
  2. 句子结束检测：基于静音超时判断一句话结束
  3. 发送两种消息：
     - partial: 实时中间状态（前端灰色显示）
     - final: 完整句子（前端正式记录）
"""

import time
import threading
import logging
from typing import Optional, Callable, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UtteranceBuffer:
    """单个会话的语句缓冲区"""
    session_id: str
    participant_id: str
    participant_name: str
    meeting_id: str
    current_text: str = ""
    start_time: float = 0.0
    last_update_time: float = 0.0
    is_finalized: bool = False


class TranscriptAggregator:
    """
    ASR 转写聚合器
    
    将流式 ASR 的片段结果聚合成完整句子，通过回调发送 partial/final 消息。
    
    架构：
      FunASR → TranscriptAggregator → Punctuation Model → WebSocket → Frontend
    """
    
    def __init__(
        self,
        silence_timeout_ms: float = 1500,  # 静音超时（毫秒），超过此时间认为一句结束
        min_text_length: int = 1,           # 最小文本长度，过短的片段不发送
        max_utterance_duration_s: float = 20.0,  # 单句最大时长（秒），强制切分
    ):
        self.silence_timeout = silence_timeout_ms / 1000.0
        self.min_text_length = min_text_length
        self.max_utterance_duration = max_utterance_duration_s
        self._buffers: Dict[str, UtteranceBuffer] = {}  # session_id -> buffer
        self._lock = threading.Lock()
        self._callback: Optional[Callable] = None
        self._timer_thread: Optional[threading.Thread] = None
        self._running = False
    
    def set_callback(self, callback: Callable) -> None:
        """设置消息回调，签名: callback(message: dict)"""
        self._callback = callback
    
    def start(self) -> None:
        """启动超时检测线程"""
        self._running = True
        self._timer_thread = threading.Thread(target=self._silence_checker, daemon=True)
        self._timer_thread.start()
        logger.info(f"TranscriptAggregator started (silence_timeout={self.silence_timeout}s)")
    
    def stop(self) -> None:
        """停止聚合器"""
        self._running = False
        # 将所有未完成的 buffer 标记为 final
        with self._lock:
            for buf in self._buffers.values():
                if buf.current_text and not buf.is_finalized:
                    self._emit_final(buf)
            self._buffers.clear()
        if self._timer_thread:
            self._timer_thread.join(timeout=3)
        logger.info("TranscriptAggregator stopped")
    
    def register_session(
        self,
        session_id: str,
        participant_id: str,
        participant_name: str,
        meeting_id: str,
    ) -> None:
        """注册新会话"""
        with self._lock:
            self._buffers[session_id] = UtteranceBuffer(
                session_id=session_id,
                participant_id=participant_id,
                participant_name=participant_name,
                meeting_id=meeting_id,
                start_time=time.time(),
                last_update_time=time.time(),
            )
        logger.info(f"[Aggregator] Registered session: {session_id} ({participant_name})")
    
    def unregister_session(self, session_id: str) -> None:
        """注销会话，发送最终结果"""
        with self._lock:
            buf = self._buffers.pop(session_id, None)
        if buf and buf.current_text and not buf.is_finalized:
            self._emit_final(buf)
        logger.info(f"[Aggregator] Unregistered session: {session_id}")
    
    def on_asr_result(self, result: dict) -> None:
        """
        处理 ASR 流式结果
        
        Args:
            result: {
                "session_id": str,
                "interim_text": str,   # ASR 当前识别的文本（累积式）
                "is_final": bool,       # 是否为最终结果
                "timestamp": int,
            }
        """
        session_id = result.get("session_id", "")
        text = result.get("interim_text", "").strip()
        is_final = result.get("is_final", False)
        
        with self._lock:
            buf = self._buffers.get(session_id)
            if not buf:
                logger.warning(f"[Aggregator] No buffer for session: {session_id}")
                return
            
            # 只在有实际文本时更新最后活动时间（空结果不重置静音计时器）
            if text:
                buf.last_update_time = time.time()
                
                # FunASR paraformer-zh-streaming 返回的是当前 chunk 的识别结果
                # 需要追加到当前语句缓冲区
                if buf.current_text:
                    buf.current_text += " " + text
                else:
                    buf.current_text = text
                
                if is_final:
                    # ASR 标记为最终结果，直接发送
                    self._emit_final(buf)
                    # 重置 buffer 准备下一句
                    buf.current_text = ""
                    buf.start_time = time.time()
                    buf.last_update_time = time.time()
                    buf.is_finalized = False
                else:
                    # 发送 partial 更新
                    self._emit_partial(buf)
    
    def _emit_partial(self, buf: UtteranceBuffer) -> None:
        """发送 partial 消息（实时中间状态）"""
        if not buf.current_text or len(buf.current_text) < self.min_text_length:
            return
        if self._callback:
            self._callback({
                "type": "transcript_partial",
                "session_id": buf.session_id,
                "meeting_id": buf.meeting_id,
                "participant_id": buf.participant_id,
                "participant_name": buf.participant_name,
                "text": buf.current_text,
                "timestamp": int(time.time() * 1000),
            })
    
    def _emit_final(self, buf: UtteranceBuffer) -> None:
        """发送 final 消息（完整句子）"""
        if not buf.current_text or len(buf.current_text) < self.min_text_length:
            return
        buf.is_finalized = True
        if self._callback:
            self._callback({
                "type": "transcript_final",
                "session_id": buf.session_id,
                "meeting_id": buf.meeting_id,
                "participant_id": buf.participant_id,
                "participant_name": buf.participant_name,
                "text": buf.current_text,
                "start_time": int(buf.start_time * 1000),
                "end_time": int(time.time() * 1000),
                "timestamp": int(time.time() * 1000),
            })
        logger.info(f"[Aggregator] Final utterance: '{buf.current_text}' ({buf.participant_name})")
    
    def _silence_checker(self) -> None:
        """
        静音检测线程
        
        定期检查每个 buffer，如果超过 silence_timeout 没有新文本，
        则认为当前句子结束，发送 final 消息。
        """
        while self._running:
            time.sleep(0.5)  # 每 500ms 检查一次
            now = time.time()
            
            with self._lock:
                for buf in list(self._buffers.values()):
                    if buf.is_finalized:
                        continue
                    if not buf.current_text:
                        continue
                    
                    elapsed = now - buf.last_update_time
                    duration = now - buf.start_time
                    
                    # 触发 final 的条件：
                    # 1. 静音超时（默认 1.5s）
                    # 2. 或者单句持续时间超过 max_utterance_duration（默认 30s）
                    if elapsed >= self.silence_timeout or duration >= self.max_utterance_duration:
                        reason = "silence" if elapsed >= self.silence_timeout else "max_duration"
                        logger.info(
                            f"[Aggregator] {reason} timeout for {buf.session_id}: "
                            f"'{buf.current_text}' (elapsed={elapsed:.1f}s, duration={duration:.1f}s)"
                        )
                        self._emit_final(buf)
                        # 重置 buffer
                        buf.current_text = ""
                        buf.start_time = now
                        buf.last_update_time = now
                        buf.is_finalized = False
