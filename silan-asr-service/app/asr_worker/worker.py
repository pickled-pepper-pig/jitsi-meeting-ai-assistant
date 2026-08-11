import logging
import re
import threading
import time
import numpy as np
import io
import wave
import json
import urllib.request
import urllib.error
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field
from app.config.settings import ASRWorkerConfig


logger = logging.getLogger(__name__)


@dataclass
class AudioTask:
    session_id: str
    audio_data: bytes
    sample_rate: int
    timestamp: int
    asr_model: str = "paraformer-zh-streaming"
    callback: Optional[Callable] = None


class BatchScheduler:
    def __init__(self, max_batch_size: int = 32, batch_timeout_ms: int = 50):
        self.max_batch_size = max_batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.tasks: list = []
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.is_running = False
        self._batch_callback = None
    
    def set_batch_callback(self, callback: Callable) -> None:
        self._batch_callback = callback
    
    def submit(self, session_id: str, audio_data: bytes, sample_rate: int,
               timestamp: int, asr_model: str = "paraformer-zh-streaming",
               callback: Optional[Callable] = None) -> None:
        task = AudioTask(
            session_id=session_id,
            audio_data=audio_data,
            sample_rate=sample_rate,
            timestamp=timestamp,
            asr_model=asr_model,
            callback=callback
        )
        
        with self.lock:
            self.tasks.append(task)
            
            if len(self.tasks) >= self.max_batch_size:
                self.condition.notify()
    
    def start(self) -> None:
        if self.is_running:
            return
        
        self.is_running = True
        thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        thread.start()
        logger.info("Batch scheduler started")
    
    def stop(self) -> None:
        self.is_running = False
        with self.lock:
            self.condition.notify()
        logger.info("Batch scheduler stopped")
    
    def _scheduler_loop(self) -> None:
        while self.is_running:
            batch = self._collect_batch()
            
            if batch and self._batch_callback:
                try:
                    self._batch_callback(batch)
                except Exception as e:
                    logger.error(f"Batch processing error: {e}")
            
            time.sleep(0.001)
    
    def _collect_batch(self) -> list:
        with self.lock:
            if not self.tasks:
                self.condition.wait(timeout=self.batch_timeout_ms / 1000)
            
            if not self.tasks:
                return []
            
            batch = self.tasks[:self.max_batch_size]
            self.tasks = self.tasks[self.max_batch_size:]
            
            return batch
    
    def get_pending_count(self) -> int:
        with self.lock:
            return len(self.tasks)


class ASRWorker:
    def __init__(self, worker_id: str, config: ASRWorkerConfig = None):
        self.worker_id = worker_id
        self.config = config or ASRWorkerConfig()
        self.scheduler = BatchScheduler(
            max_batch_size=self.config.max_batch_size,
            batch_timeout_ms=self.config.batch_timeout_ms
        )
        self.scheduler.set_batch_callback(self._process_batch)
        
        self.model = None
        self.punc_model = None  # 标点恢复模型
        # SenseVoice 不再本地加载模型，改为通过 API 调用
        self.sensevoice_model = None
        self._sv_config = None  # SenseVoice API 配置，由外部注入
        # SenseVoice 累积音频 buffer：session_id -> {pcm: np.ndarray, last_speech_time: float}
        self._sv_buffers: Dict[str, dict] = {}
        self._sv_lock = threading.Lock()
        self.session_states: Dict[str, object] = {}
        self._transcript_callback: Optional[Callable] = None
        
        # 流式 ASR 参数：
        # - chunk_size=[0, 10, 5]：当前块 10 帧 = 600ms（决定 partial 延迟）
        # - encoder_chunk_look_back=10：encoder 看前 10 块 = 6s 上下文（识别连贯性）
        # - decoder_chunk_look_back=4：decoder 看前 4 块 = 2.4s 上下文（修正回退）
        # 增大 look_back 能让模型看到更多历史，partial 不再"只识别第一个字"
        # 保持 chunk_size 不变以维持低延迟
        self.chunk_size = [0, 10, 5]
        self.encoder_chunk_look_back = 10
        self.decoder_chunk_look_back = 4
        
        self._load_model()
    
    def _load_model(self) -> None:
        try:
            from funasr import AutoModel
            
            logger.info(f"Loading ASR model: {self.config.model_name}")
            
            model_args = {
                "model": self.config.model_name,
                "disable_pbar": True
            }
            
            if self.config.device == "cuda":
                model_args["device"] = "cuda"
            
            self.model = AutoModel(**model_args)
            logger.info(f"ASR model loaded successfully on {self.config.device}")

            # SenseVoice 不再本地加载，改为通过 SiLAN 网关 API 调用

            # 加载标点恢复模型（CT-Transformer）
            try:
                logger.info("Loading punctuation model: ct-punc")
                punc_model_args = {
                    "model": "ct-punc",
                    "disable_pbar": True
                }
                if self.config.device == "cuda":
                    punc_model_args["device"] = "cuda"
                self.punc_model = AutoModel(**punc_model_args)
                logger.info("Punctuation model loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load punctuation model, will skip punctuation restoration: {e}")
                self.punc_model = None
            
            if self.config.hotword_file:
                self._load_hotwords()
        
        except Exception as e:
            logger.error(f"Failed to load ASR model: {e}")
            raise
    
    def _load_hotwords(self) -> None:
        try:
            with open(self.config.hotword_file, "r", encoding="utf-8") as f:
                hotwords = f.read().strip().split("\n")
            
            logger.info(f"Loaded {len(hotwords)} hotwords from {self.config.hotword_file}")
            
            if hasattr(self.model, 'set_hotword'):
                self.model.set_hotword(hotwords)
        except Exception as e:
            logger.warning(f"Failed to load hotwords: {e}")
    
    def set_transcript_callback(self, callback: Callable) -> None:
        self._transcript_callback = callback
    
    def set_sensevoice_config(self, sv_config) -> None:
        """注入 SenseVoice API 配置（从 AppConfig.sensevoice 传入）"""
        self._sv_config = sv_config
        logger.info(f"[SenseVoice] API 配置已注入: base_url={sv_config.base_url}, model={sv_config.model}")
    
    def _call_sensevoice_api(self, audio_np: np.ndarray) -> Optional[str]:
        """通过 SiLAN 网关 /v1/audio/transcriptions 调用 SenseVoice ASR
        
        Args:
            audio_np: float32 numpy array, 16kHz 单声道, [-1.0, 1.0]
            
        Returns:
            识别文本，失败返回 None
        """
        if not self._sv_config or not self._sv_config.api_key:
            logger.warning("[SenseVoice] API Key 未配置，无法调用")
            return None
        
        # float32 → int16 → WAV bytes
        audio_int16 = (audio_np * 32768).astype(np.int16)
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_int16.tobytes())
        wav_bytes = wav_buf.getvalue()
        
        # multipart/form-data 边界
        boundary = "----SenseVoiceBoundary" + str(int(time.time() * 1000))
        
        # 构建 multipart body
        body = b""
        # file 字段
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        body += b"Content-Type: audio/wav\r\n\r\n"
        body += wav_bytes
        body += b"\r\n"
        # model 字段
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
        body += self._sv_config.model.encode()
        body += b"\r\n"
        # 结束边界
        body += f"--{boundary}--\r\n".encode()
        
        url = f"{self._sv_config.base_url}/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self._sv_config.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self._sv_config.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                # OpenAI 兼容格式: {"text": "..."} 
                text = result.get("text", "")
                logger.info(f"[SenseVoice] API 识别结果: '{text}'")
                return text if text.strip() else None
        except urllib.error.HTTPError as e:
            logger.error(f"[SenseVoice] API 调用失败 HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}")
            return None
        except Exception as e:
            logger.error(f"[SenseVoice] API 调用异常: {e}")
            return None
    
    def start(self) -> None:
        self.scheduler.start()
        logger.info(f"ASR Worker {self.worker_id} started")
    
    def stop(self) -> None:
        self.scheduler.stop()
        logger.info(f"ASR Worker {self.worker_id} stopped")
    
    def submit_audio(self, session_id: str, audio_data: bytes, 
                     sample_rate: int = 16000, timestamp: int = 0,
                     asr_model: str = "paraformer-zh-streaming") -> None:
        self.scheduler.submit(
            session_id=session_id,
            audio_data=audio_data,
            sample_rate=sample_rate,
            timestamp=timestamp,
            asr_model=asr_model,
        )
    
    def _process_batch(self, batch: list) -> None:
        if not batch or not self.model:
            return
        
        try:
            results = []
            
            for task in batch:
                result = self._process_single(task)
                if result:
                    results.append(result)
                # 每个 chunk 处理后释放 GIL，让 WebSocket 事件循环有机会运行
                time.sleep(0)
            
            if results and self._transcript_callback:
                self._transcript_callback(results)
        
        except Exception as e:
            logger.error(f"Batch processing error: {e}")
    
    def _process_single(self, task: AudioTask) -> Optional[dict]:
        try:
            # 兼容两种 PCM 编码：
            #  - Float32 LE（-1.0~1.0）：audioCapture 主路径
            #  - Int16 LE（-32768~32767）：ParticipantAudioReceiver / Bot recorder
            # 服务端统一按 Float32 拆；若数值范围 << 1e-3 说明是 Int16 误拆，重拆
            audio_np = np.frombuffer(task.audio_data, dtype=np.float32)
            if audio_np.size > 0:
                # Int16 误拆成 Float32 后：
                #  - 典型幅值可能在 1e-38（极小）或 1e+38（爆 Float32 范围）
                #  - 正常 Float32 PCM 在 [-1.0, 1.0]，max_abs 应该在 [0, 1]
                max_abs_original = float(np.nanmax(np.abs(audio_np)))
                if max_abs_original < 1e-3 or max_abs_original > 1.0 or np.isnan(max_abs_original):
                    audio_int16 = np.frombuffer(task.audio_data, dtype=np.int16)
                    audio_np = audio_int16.astype(np.float32) / 32768.0

            if task.sample_rate != 16000:
                audio_np = self._resample(audio_np, task.sample_rate, 16000)

            # 根据会议选择的模型分流
            if task.asr_model == "SenseVoiceSmall" and self._sv_config is not None:
                return self._process_sensevoice(task, audio_np)
            
            # 默认走 Paraformer 流式
            return self._process_paraformer(task, audio_np)

        except Exception as e:
            logger.error(f"Processing session {task.session_id} error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _process_paraformer(self, task: AudioTask, audio_np: np.ndarray) -> Optional[dict]:
        """Paraformer 流式处理（原有逻辑）"""
        logger.info(f"Processing audio: session={task.session_id}, samples={len(audio_np)}, sr={task.sample_rate}")

        if task.session_id not in self.session_states:
            self.session_states[task.session_id] = {}
            logger.info(f"Created new session state for {task.session_id}")

        result = self.model.generate(
            input=audio_np,
            cache=self.session_states[task.session_id],
            is_final=False,
            chunk_size=self.chunk_size,
            encoder_chunk_look_back=self.encoder_chunk_look_back,
            decoder_chunk_look_back=self.decoder_chunk_look_back,
            use_itn=True,
        )

        logger.info(f"Model result: {result}")

        if result and len(result) > 0:
            text = result[0].get("text", "")
            logger.info(f"Recognized text: '{text}'")

            return {
                "session_id": task.session_id,
                "interim_text": text,
                "final_text": "",
                "timestamp": task.timestamp,
                "confidence": result[0].get("confidence", 0.0)
            }
        return None

    def _process_sensevoice(self, task: AudioTask, audio_np: np.ndarray) -> Optional[dict]:
        """SenseVoice 段批处理：累积音频，静音超时后整段识别
        
        工作方式：
        1. 每个 chunk 累积到 session 的 buffer
        2. 检测静音（能量 < 阈值持续 > 1s）
        3. 静音触发：把累积的音频整段送 SenseVoice 识别
        4. 识别结果作为 final 返回，清空 buffer
        """
        SV_SILENCE_THRESHOLD = 0.025  # 静音能量阈值（RMS）：噪声/呼吸声 < 此值视为静音
        SV_SILENCE_DURATION = 1.5     # 静音持续多久触发识别（秒）
        SV_MAX_BUFFER = 30.0          # buffer 最大时长（秒），超过强制识别
        SV_MIN_SEGMENT_DURATION = 0.5  # 最短片段时长（秒），太短的跳过
        SV_MIN_TEXT_LENGTH = 4        # 识别结果最短字符数（过滤"嗯"、"。"等碎片）
        SV_MIN_SEGMENT_ENERGY = 0.020  # 片段整体最低 RMS 能量：低于此值视为纯噪声，不送识别
        # 语音活动检测阈值（低于静音阈值，用于发 processing 信号）
        # 只要有轻微语音能量就通知前端"正在说话"，不同于静音判定
        SV_SPEECH_THRESHOLD = 0.010
        # SenseVoice 典型幻觉碎片（≤5 字命中即过滤）
        SV_HALLUCINATION_KEYWORDS = (
            "嗯对", "对不去", "就清楚", "就天", "知楚", "便宜",
            "屁弟", "出来", "嗯嗯", "在那个", "谢谢", "你好",
            "就是", "然后", "好的", "可以",
        )
        SR = 16000

        now = time.time()
        # 检测当前 chunk 是否静音
        energy = float(np.sqrt(np.mean(audio_np ** 2))) if audio_np.size > 0 else 0.0
        is_silence = energy < SV_SILENCE_THRESHOLD
        has_speech = energy >= SV_SPEECH_THRESHOLD

        with self._sv_lock:
            buf = self._sv_buffers.get(task.session_id)
            if buf is None:
                buf = {"pcm": np.array([], dtype=np.float32), "last_speech_time": now, "last_emit_time": 0.0}
                self._sv_buffers[task.session_id] = buf

            buf["pcm"] = np.concatenate([buf["pcm"], audio_np])

            if not is_silence:
                buf["last_speech_time"] = now

            buffer_duration = len(buf["pcm"]) / SR
            silence_elapsed = now - buf["last_speech_time"]
            # 触发整段识别条件：静音超时 或 buffer 太长
            should_emit = (is_silence and silence_elapsed >= SV_SILENCE_DURATION and buffer_duration > 0.5) or \
                          (buffer_duration >= SV_MAX_BUFFER)

            if not should_emit:
                # 有人在说话（检测到语音能量）且 buffer 已积累 0.5s+：发 processing 信号
                if has_speech and buffer_duration > 0.5:
                    return {
                        "session_id": task.session_id,
                        "sv_processing": True,
                        "timestamp": task.timestamp,
                    }
                return None

            # 取出 buffer 整段识别
            segment = buf["pcm"]
            buf["pcm"] = np.array([], dtype=np.float32)
            buf["last_emit_time"] = now

        if len(segment) < SR * SV_MIN_SEGMENT_DURATION:  # 小于最短时长的片段跳过
            return None

        # ── 帧级语音占比检测（比整体 RMS 更精准）──
        # 把片段切成 30ms 的帧，统计有多少帧能量超过语音阈值
        # 真正说话的片段，语音帧占比应 > 30%；噪声/幻觉段绝大多数帧是静音
        frame_size = int(SR * 0.03)  # 30ms
        n_frames = len(segment) // frame_size
        if n_frames > 0:
            frames = segment[:n_frames * frame_size].reshape(n_frames, frame_size)
            frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
            speech_frames = np.sum(frame_rms >= SV_SPEECH_THRESHOLD)
            speech_ratio = speech_frames / n_frames
        else:
            speech_ratio = 0.0
        segment_rms = float(np.sqrt(np.mean(segment ** 2))) if segment.size > 0 else 0.0

        # 过滤条件：整体 RMS 太低 或 语音帧占比 < 30%（噪声脉冲不适合送识别）
        if segment_rms < SV_MIN_SEGMENT_ENERGY or speech_ratio < 0.3:
            logger.info(f"[SenseVoice] Skipping low-speech segment: session={task.session_id}, "
                        f"duration={len(segment)/SR:.1f}s, rms={segment_rms:.4f}, "
                        f"speech_ratio={speech_ratio:.2f} ({int(speech_ratio*n_frames)}/{n_frames} frames)")
            return None

        logger.info(f"[SenseVoice] Recognizing segment: session={task.session_id}, "
                    f"duration={len(segment)/SR:.1f}s, rms={segment_rms:.4f}, "
                    f"speech_ratio={speech_ratio:.2f}")

        # 通过 SiLAN 网关 API 调用 SenseVoice
        text = self._call_sensevoice_api(segment)
        if not text:
            return None

        # 去除 SenseVoice 情感/事件 emoji（😊😔😡😰🤢😮🎼👏😀😭🤧❓等）
        text = re.sub(r'[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\u2764\ufe0f\u2763\ufe0f❓]', '', text).strip()
        # 去除标点后检查实际文字长度，过滤"嗯"、"。"等无意义碎片
        clean_text = re.sub(r'[，。？！、\s\u200b\U0001f000-\U0001ffff〈〈》]', '', text).strip()
        logger.info(f"[SenseVoice] Recognized: '{text}' (clean: '{clean_text}', len={len(clean_text)})")

        if len(clean_text) >= SV_MIN_TEXT_LENGTH:
            # 过滤 SenseVoice 典型幻觉碎片：短文本且命中关键词
            if len(clean_text) <= 5 and any(kw in clean_text for kw in SV_HALLUCINATION_KEYWORDS):
                logger.info(f"[SenseVoice] Filtered hallucination: '{clean_text}'")
                return None
            return {
                "session_id": task.session_id,
                # SenseVoice 整段识别直接返回 final，不区分 partial
                "interim_text": "",
                "final_text": "",
                # 通过 special flag 让 aggregator 直接跳过累积逻辑
                "sv_final_text": text,
                "timestamp": task.timestamp,
                "confidence": 1.0,
                "is_final": True,
            }
        return None
    
    def _resample(self, audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        if src_rate == dst_rate:
            return audio
        
        length = len(audio)
        new_length = int(length * dst_rate / src_rate)
        indices = np.linspace(0, length - 1, new_length)
        return np.interp(indices, np.arange(length), audio).astype(audio.dtype)
    
    def _add_punctuation(self, text: str) -> str:
        """
        使用标点恢复模型为文本添加标点符号
        
        Args:
            text: 原始文本（无标点）
            
        Returns:
            带标点的文本，如果标点模型不可用则返回原文本
        """
        if not self.punc_model or not text.strip():
            return text
        
        try:
            result = self.punc_model.generate(input=text)
            if result and len(result) > 0:
                punctuated_text = result[0].get("text", text)
                logger.debug(f"Punctuation added: '{text}' -> '{punctuated_text}'")
                return punctuated_text
            return text
        except Exception as e:
            logger.warning(f"Failed to add punctuation: {e}")
            return text
    
    def finalize_session(self, session_id: str) -> Optional[dict]:
        try:
            # 先处理 SenseVoice 残余 buffer
            with self._sv_lock:
                buf = self._sv_buffers.pop(session_id, None)
            if buf is not None and self._sv_config is not None:
                segment = buf["pcm"]
                if len(segment) >= 16000 * 0.3:
                    logger.info(f"[SenseVoice] Finalizing segment: session={session_id}, duration={len(segment)/16000:.1f}s")
                    text = self._call_sensevoice_api(segment)
                    if text:
                        text = re.sub(r'[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\u2764\ufe0f\u2763\ufe0f❓]', '', text).strip()
                        if text.strip():
                            return {
                                "session_id": session_id,
                                "final_text": text,
                                "timestamp": int(time.time() * 1000),
                                "is_final": True,
                            }

            if session_id not in self.session_states:
                return None
            
            result = self.model.generate(
                input=np.zeros(1600, dtype=np.float32),
                cache=self.session_states[session_id],
                is_final=True,
                chunk_size=self.chunk_size,
                encoder_chunk_look_back=self.encoder_chunk_look_back,
                decoder_chunk_look_back=self.decoder_chunk_look_back,
                use_itn=True,
            )
            
            del self.session_states[session_id]
            
            if result and len(result) > 0:
                text = result[0].get("text", "")
                # 对 final 文本进行标点恢复
                punctuated_text = self._add_punctuation(text)
                return {
                    "session_id": session_id,
                    "final_text": punctuated_text,
                    "timestamp": int(time.time() * 1000)
                }
            return None
        
        except Exception as e:
            logger.error(f"Finalizing session {session_id} error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_session_count(self) -> int:
        return len(self.session_states)
