import logging
import threading
import time
import numpy as np
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
               timestamp: int, callback: Optional[Callable] = None) -> None:
        task = AudioTask(
            session_id=session_id,
            audio_data=audio_data,
            sample_rate=sample_rate,
            timestamp=timestamp,
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
    
    def start(self) -> None:
        self.scheduler.start()
        logger.info(f"ASR Worker {self.worker_id} started")
    
    def stop(self) -> None:
        self.scheduler.stop()
        logger.info(f"ASR Worker {self.worker_id} stopped")
    
    def submit_audio(self, session_id: str, audio_data: bytes, 
                     sample_rate: int = 16000, timestamp: int = 0) -> None:
        self.scheduler.submit(
            session_id=session_id,
            audio_data=audio_data,
            sample_rate=sample_rate,
            timestamp=timestamp
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
            audio_np = np.frombuffer(task.audio_data, dtype=np.float32)
            
            logger.info(f"Processing audio: session={task.session_id}, samples={len(audio_np)}, sr={task.sample_rate}")
            
            if task.sample_rate != 16000:
                audio_np = self._resample(audio_np, task.sample_rate, 16000)
            
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
                
                # 如果有标点模型，对 final 文本进行标点恢复
                # 注意：partial 结果不做标点恢复，避免性能开销
                return {
                    "session_id": task.session_id,
                    "interim_text": text,  # partial 不带标点
                    "final_text": "",
                    "timestamp": task.timestamp,
                    "confidence": result[0].get("confidence", 0.0)
                }
            return None
        
        except Exception as e:
            logger.error(f"Processing session {task.session_id} error: {e}")
            import traceback
            traceback.print_exc()
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
