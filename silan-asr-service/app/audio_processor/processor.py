import numpy as np
from app.config.settings import AudioProcessorConfig


class AudioProcessor:
    def __init__(self, config: AudioProcessorConfig = None):
        self.config = config or AudioProcessorConfig()
        self._resample_buffer = {}
    
    def process(self, audio_data: np.ndarray, sample_rate: int) -> dict:
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
            is_speech = self._detect_speech(audio_data)
            result["is_speech"] = is_speech
        
        result["audio"] = audio_data
        return result
    
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
    
    def _detect_speech(self, audio: np.ndarray) -> bool:
        max_amplitude = np.max(np.abs(audio))
        return max_amplitude > self.config.vad_threshold
    
    def get_chunk_size(self) -> int:
        return int(self.config.sample_rate * self.config.chunk_duration_ms / 1000)
