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
    current_text: str = ""        # ASR 最近一次返回的"窗口文本"（不是累积全文）
    emitted_text: str = ""        # 已发送给前端的"累积全文"（emit_delta 拼接结果）
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
        punc_model=None,                   # 可选：ct-punc 标点恢复模型（用于 final 句）
    ):
        self.silence_timeout = silence_timeout_ms / 1000.0
        self.min_text_length = min_text_length
        self.max_utterance_duration = max_utterance_duration_s
        self.punc_model = punc_model
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
        """注册会话（幂等：已存在则只更新 participant_name，不覆盖 buffer）"""
        with self._lock:
            existing = self._buffers.get(session_id)
            if existing is not None:
                # 已注册：只更新名称（可能之前是 "未知参与者"）
                if participant_name and existing.participant_name != participant_name:
                    existing.participant_name = participant_name
                    logger.info(f"[Aggregator] Updated session name: {session_id} → {participant_name}")
                return
            self._buffers[session_id] = UtteranceBuffer(
                session_id=session_id,
                participant_id=participant_id,
                participant_name=participant_name,
                meeting_id=meeting_id,
                start_time=time.time(),
                last_update_time=time.time(),
            )
        logger.info(f"[Aggregator] Registered session: {session_id} ({participant_name})")

    def touch_session(self, session_id: str) -> None:
        """刷新会话的最后活跃时间（用于音频帧到达时重置静音计时器）

        即便模型暂时返回空文本（如句中换气、说话停顿），只要有音频帧
        进来就应该刷新 last_update_time，避免 silence_timeout 误判句尾。
        """
        with self._lock:
            buf = self._buffers.get(session_id)
            if buf:
                buf.last_update_time = time.time()

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
                "interim_text": str,   # ASR 当前识别的文本（累积式：从开头到当前 chunk）
                "is_final": bool,       # 是否为最终结果
                "timestamp": int,
            }
        """
        session_id = result.get("session_id", "")

        # SenseVoice 处理中信号：有人在说话，音频正在积累但还没触发识别
        # 转成 transcript_partial 发给前端，前端显示"正在处理..."
        if result.get("sv_processing"):
            with self._lock:
                buf = self._buffers.get(session_id)
                if buf and self._callback:
                    self._callback({
                        "type": "transcript_partial",
                        "session_id": buf.session_id,
                        "meeting_id": buf.meeting_id,
                        "participant_id": buf.participant_id,
                        "participant_name": buf.participant_name,
                        "text": "",  # 空文本 = 处理中，前端用占位文字
                        "is_processing": True,
                        "timestamp": int(time.time() * 1000),
                    })
            return

        # SenseVoice 段批处理模式：直接走 final 通路
        sv_text = result.get("sv_final_text")
        if sv_text:
            with self._lock:
                buf = self._buffers.get(session_id)
                if not buf:
                    logger.warning(f"[Aggregator] No buffer for session: {session_id}")
                    return
                # SenseVoice 自带标点，不需要 _add_punctuation
                buf.is_finalized = True
                if self._callback:
                    self._callback({
                        "type": "transcript_final",
                        "session_id": buf.session_id,
                        "meeting_id": buf.meeting_id,
                        "participant_id": buf.participant_id,
                        "participant_name": buf.participant_name,
                        "text": sv_text,
                        "start_time": int(buf.start_time * 1000),
                        "end_time": int(time.time() * 1000),
                        "timestamp": int(time.time() * 1000),
                    })
                logger.info(f"[Aggregator] SenseVoice final: '{sv_text}' ({buf.participant_name})")
                # 重置 buffer
                buf.current_text = ""
                buf.emitted_text = ""
                buf.start_time = time.time()
                buf.last_update_time = time.time()
                buf.is_finalized = False
            return

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

                # 流式 ASR partial 文本的特性：
                # - paraformer-zh-streaming 在流式模式下每次返回"最近窗口"的识别结果
                # - 窗口会随音频输入滚动：今 → 天我们 → 讨论以 → ... → 的市场
                # - 窗口之间有重叠（"讨论以"尾部"以"和"下半导"头部"下"无重叠，
                #   但"体行"尾部"行"和"业的最"头部"业"无重叠）
                # 我们的任务：从每个窗口中提取"新增"片段，累积成完整全文 emit 给前端。
                prev_window = buf.current_text
                prev_emitted = buf.emitted_text

                # 计算 delta：new_window 中"还没发出过"的部分
                delta = self._extract_delta(prev_emitted, text)

                # 总是更新 current_text（保留 ASR 最新窗口的"快照"）
                buf.current_text = text

                if delta is not None:  # 找到边界（哪怕 delta 为空字符串）
                    buf.emitted_text = prev_emitted + delta
                    logger.debug(
                        f"[Aggregator] window='{text}' delta='{delta}' "
                        f"emitted='{buf.emitted_text}'"
                    )

                    if is_final:
                        # ASR 标记为最终结果，把已累积全文 emit final
                        self._emit_final_with_text(buf, buf.emitted_text)
                        # 重置 buffer 准备下一句
                        buf.current_text = ""
                        buf.emitted_text = ""
                        buf.start_time = time.time()
                        buf.last_update_time = time.time()
                        buf.is_finalized = False
                    else:
                        # 发送累积 partial（前端展示的是"累积全文"而不是"窗口片段"）
                        self._emit_partial_with_text(buf, buf.emitted_text)

    @staticmethod
    def _merge_text(prev: str, new_full: str) -> str:
        """
        合并 ASR 流式结果：基于最长公共前缀 + 字符级 LCS 兜底，提取新增部分。

        paraformer-zh-streaming 流式返回的是"从开头到当前 chunk 的完整识别结果"。
        因此需要从 new_full 中提取"相对 prev 的新增片段"，避免重复累积。

        设计权衡：当 prev 和 new_full 没有公共边界时，保留 prev 而不是用更短的
        覆盖更长的（partial 阶段保守更安全，避免把已经显示的字幕改回错的）。
        """
        if not prev:
            return new_full
        if not new_full:
            return prev
        if new_full == prev:
            return prev

        # 情况1：new_full 是 prev 的扩展（最常见，模型只是在尾部加了字）
        if new_full.startswith(prev):
            return new_full
        if prev.startswith(new_full):
            # 模型回退了（少识别几个字），取更长的
            return prev

        # 情况2：前缀完全不一致，但 prev 的尾部是 new_full 的前缀（修正型扩展）
        # 例如 prev="我们自己"、new="我先去"：尾部"们自己"不和"我先去"前缀匹配 → 保留 prev
        # 这种情况下保守地保留 prev，等到 final 时由静音超时触发
        max_overlap = min(len(prev), len(new_full))
        for k in range(max_overlap, 0, -1):
            if prev.endswith(new_full[:k]):
                tail = new_full[k:]
                return prev + tail

        # 情况3：找不到公共边界（识别结果大幅变化，例如重新开始说话）
        # 此时保留 prev 较安全，避免在 partial 阶段用更短的覆盖更长的。
        # final 时刻由静音超时（1.5s）触发，可以接受少量错误。
        return prev
    
    @staticmethod
    def _extract_delta(prev_emitted: str, new_window: str) -> str:
        """从 ASR 新窗口中提取"相对已发出全文的新增片段"。

        流式 ASR 的特性：每次返回的是"最近窗口"的识别结果，窗口会滚动。
        我们的目标：把每个窗口的"还没发出去"的部分提取出来，拼接成完整全文。

        返回值：始终返回 str（哪怕是空字符串）。调用方无需处理 None。

        例子：
          prev_emitted="今天我们", new_window="我们讨论一下"
          → 公共子串 "我们"，delta="讨论一下"
          → 新 emitted="今天我们讨论一下"

          prev_emitted="今", new_window="天我们"
          → 没有公共字符，但 prev_emitted 是 new_window 的"前文"
          → delta = new_window 全部 ("天我们")
          → 新 emitted="今天我们"
        """
        if not new_window:
            return ""
        if not prev_emitted:
            return new_window

        # 找 prev_emitted 在 new_window 中的最长后缀匹配
        # 也就是 prev_emitted 末尾的 k 个字符 == new_window 开头的 k 个字符
        max_k = min(len(prev_emitted), len(new_window))
        for k in range(max_k, 0, -1):
            if prev_emitted.endswith(new_window[:k]):
                return new_window[k:]

        # 找 new_window 在 prev_emitted 中的最长前缀匹配
        # new_window 全部是 prev_emitted 已发出过的内容（模型回退或重复识别）
        for k in range(len(new_window), 0, -1):
            if prev_emitted.endswith(new_window[:k]):
                return ""  # 全部已发出，无新增

        # 没有任何重叠边界：prev_emitted 和 new_window 是"完全不同的片段"
        # 这种情况下直接把 new_window 当作新增（避免丢内容）
        # 接受可能产生的少量重复（前缀重叠失败了，宁可重复也别丢）
        return new_window

    def _emit_partial(self, buf: UtteranceBuffer) -> None:
        """发送 partial 消息（实时中间状态）— 兼容旧调用"""
        self._emit_partial_with_text(buf, buf.emitted_text or buf.current_text)

    def _emit_partial_with_text(self, buf: UtteranceBuffer, text: str) -> None:
        """发送 partial 消息（累积全文）"""
        if not text or len(text) < self.min_text_length:
            return
        if self._callback:
            self._callback({
                "type": "transcript_partial",
                "session_id": buf.session_id,
                "meeting_id": buf.meeting_id,
                "participant_id": buf.participant_id,
                "participant_name": buf.participant_name,
                "text": text,
                "timestamp": int(time.time() * 1000),
            })

    def _emit_final(self, buf: UtteranceBuffer) -> None:
        """发送 final 消息 — 兼容旧调用"""
        self._emit_final_with_text(buf, buf.emitted_text or buf.current_text)

    def _emit_final_with_text(self, buf: UtteranceBuffer, text: str) -> None:
        """发送 final 消息（累积全文）"""
        if not text or len(text) < self.min_text_length:
            return
        buf.is_finalized = True
        final_text = self._add_punctuation(text)
        if self._callback:
            self._callback({
                "type": "transcript_final",
                "session_id": buf.session_id,
                "meeting_id": buf.meeting_id,
                "participant_id": buf.participant_id,
                "participant_name": buf.participant_name,
                "text": final_text,
                "start_time": int(buf.start_time * 1000),
                "end_time": int(time.time() * 1000),
                "timestamp": int(time.time() * 1000),
            })
        logger.info(f"[Aggregator] Final utterance: '{final_text}' ({buf.participant_name})")

    def _add_punctuation(self, text: str) -> str:
        """使用 ct-punc 标点模型为 final 文本添加标点（partial 不加，避免性能开销）"""
        if not self.punc_model or not text.strip():
            return text
        try:
            result = self.punc_model.generate(input=text)
            if result and len(result) > 0:
                punctuated = result[0].get("text", text)
                if punctuated and punctuated != text:
                    logger.debug(f"[Aggregator] Punctuation: '{text}' -> '{punctuated}'")
                return punctuated
            return text
        except Exception as e:
            logger.warning(f"[Aggregator] Punctuation failed: {e}")
            return text
    
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
                    if not buf.current_text and not buf.emitted_text:
                        continue

                    elapsed = now - buf.last_update_time
                    duration = now - buf.start_time

                    # 触发 final 的条件：
                    # 1. 静音超时（默认 1.5s）
                    # 2. 或者单句持续时间超过 max_utterance_duration（默认 30s）
                    if elapsed >= self.silence_timeout or duration >= self.max_utterance_duration:
                        reason = "silence" if elapsed >= self.silence_timeout else "max_duration"
                        # 用累积的 emitted_text 作为 final（而不是 current_text 窗口片段）
                        final_text = buf.emitted_text or buf.current_text
                        logger.info(
                            f"[Aggregator] {reason} timeout for {buf.session_id}: "
                            f"'{final_text}' (elapsed={elapsed:.1f}s, duration={duration:.1f}s)"
                        )
                        self._emit_final_with_text(buf, final_text)
                        # 重置 buffer
                        buf.current_text = ""
                        buf.emitted_text = ""
                        buf.start_time = now
                        buf.last_update_time = now
                        buf.is_finalized = False
