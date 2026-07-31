import numpy as np
from app.config.settings import AudioProcessorConfig


class AudioProcessor:
    def __init__(self, config: AudioProcessorConfig = None):
        self.config = config or AudioProcessorConfig()
        self._resample_buffer = {}
        # Silero VAD 模型（全局共享，线程安全用于推理）
        self._vad_model = None
        self._vad_utils = None
        # per-session VADIterator（有状态，必须按 session 隔离）
        # key: session_id, value: VADIterator
        self._vad_iterators: dict = {}
        self._vad_available = False
        self._init_vad()

    def _init_vad(self) -> None:
        """启动时加载 Silero VAD 模型。失败则回退到能量阈值。"""
        if self.config.vad_model != "silero":
            return
        try:
            from silero_vad import load_silero_vad, VADIterator
            self._vad_model = load_silero_vad(onnx=False)
            self._vad_utils = (VADIterator,)
            self._vad_available = True
            print("[AudioProcessor] Silero VAD 已加载")
        except Exception as e:
            print(f"[AudioProcessor] Silero VAD 加载失败，回退能量阈值: {e}")
            self._vad_available = False

    def process(self, audio_data: np.ndarray, sample_rate: int, session_id: str = None) -> dict:
        result = {
            "audio": audio_data,
            "sample_rate": sample_rate,
            "is_speech": True,
            "processed": False
        }

        if sample_rate != self.config.sample_rate:
            audio_data = self._resample(audio_data, sample_rate, self.config.sample_rate)
            result["audio"] = audio_data
            result["sample_rate"] = self.config.sample_rate
            result["processed"] = True

        if audio_data.ndim > 1 and audio_data.shape[0] > 1:
            audio_data = self._stereo_to_mono(audio_data)
            result["audio"] = audio_data
            result["processed"] = True

        if self.config.agc_enabled:
            audio_data = self._apply_agc(audio_data)
            result["audio"] = audio_data
            result["processed"] = True

        if self.config.denoise_enabled:
            audio_data = self._apply_denoise(audio_data)
            result["audio"] = audio_data
            result["processed"] = True

        if self.config.vad_threshold > 0:
            if self._vad_available and session_id:
                is_speech = self._detect_speech_silero(audio_data, session_id)
            else:
                is_speech = self._detect_speech_energy(audio_data, self.config.vad_threshold)
            result["is_speech"] = is_speech

        result["audio"] = audio_data
        return result

    def _detect_speech_silero(self, audio: np.ndarray, session_id: str) -> bool:
        """用 Silero VADIterator 判断当前 chunk 是否含语音。
        VADIterator 有状态（LSTM hidden state），必须 per-session。"""
        VADIterator = self._vad_utils[0]
        it = self._vad_iterators.get(session_id)
        if it is None:
            it = VADIterator(
                self._vad_model,
                threshold=self.config.vad_threshold,
                min_silence_duration_ms=self.config.vad_min_silence_ms,
                speech_pad_ms=30,
            )
            self._vad_iterators[session_id] = it
        # 复杂环境：只关注"当前 chunk 是否在语音段内"
        # VADIterator 在语音开始/结束时会返回 dict，中间 chunk 返回 None
        # 我们把"返回非 None"或"iterator 当前在语音态"都判为有语音
        try:
            # Silero 需要 torch tensor，float32，16kHz
            import torch
            t = torch.from_numpy(audio).float()
            result = it(t, return_seconds=False)
            # result 非 None 表示状态切换（start/end），None 表示延续当前状态
            if result is not None:
                # 'start' → 有语音；'end' → 语音结束（但本 chunk 仍属于语音尾）
                return 'start' in result or 'end' in result
            # None：用 iterator 内部 is_speech 状态
            return getattr(it, 'is_speech', False) or getattr(it, 'triggered', False)
        except Exception:
            return self._detect_speech_energy(audio, self.config.vad_threshold)

    def release_session(self, session_id: str) -> None:
        """session 销毁时调用，释放 VADIterator 状态。"""
        it = self._vad_iterators.pop(session_id, None)
        if it is not None:
            try:
                it.reset_states()
            except Exception:
                pass
    
    def _resample(self, audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        if src_rate == dst_rate:
            return audio
        
        length = len(audio)
        new_length = int(length * dst_rate / src_rate)
        indices = np.linspace(0, length - 1, new_length)
        return np.interp(indices, np.arange(length), audio).astype(audio.dtype)
    
    def _stereo_to_mono(self, audio: np.ndarray) -> np.ndarray:
        if audio.ndim == 2:
            return np.mean(audio, axis=0)
        return audio
    
    def _apply_agc(self, audio: np.ndarray) -> np.ndarray:
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            target_level = 0.5
            gain = target_level / max_val
            audio = audio * gain
        return audio.clip(-1.0, 1.0)
    
    def _apply_denoise(self, audio: np.ndarray) -> np.ndarray:
        try:
            import noisereduce as nr
            return nr.reduce_noise(y=audio, sr=self.config.sample_rate)
        except ImportError:
            return audio
    
    def _detect_speech_energy(self, audio: np.ndarray, threshold: float) -> bool:
        """能量阈值 VAD（回退方案）。"""
        max_amplitude = np.max(np.abs(audio))
        return max_amplitude > threshold
    
    def get_chunk_size(self) -> int:
        return int(self.config.sample_rate * self.config.chunk_duration_ms / 1000)
