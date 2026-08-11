import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List


PROJECT_ROOT = Path(__file__).parent.parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources" / "vocab"


@dataclass
class AudioProcessorConfig:
    sample_rate: int = 16000
    channel_count: int = 1
    # VAD 配置
    # vad_threshold > 0 时启用 VAD：
    #   - vad_model == "silero"  → 用 Silero VAD 神经网络（精度高，CPU 也能跑）
    #   - 其它值                   → 回退到能量阈值（兼容老配置）
    vad_threshold: float = 0.5          # Silero 语音概率阈值（0-1，越大越严格）
    vad_model: str = "silero"           # "silero" | "energy"
    vad_min_speech_ms: int = 250        # 短于该时长的语音片段忽略（过滤噪声）
    vad_min_silence_ms: int = 100       # 连续静音多久判定句尾
    agc_enabled: bool = False  # 浏览器 getUserMedia 已做 AGC，后端不再重复处理
    denoise_enabled: bool = False  # 浏览器已做降噪
    echo_cancel_enabled: bool = False
    chunk_duration_ms: int = 60


@dataclass
class ASRWorkerConfig:
    model_name: str = "paraformer-zh-streaming"
    device: str = "cpu"
    max_batch_size: int = 32
    batch_timeout_ms: int = 50
    max_concurrent_sessions: int = 100
    hotword_file: str = str(RESOURCES_DIR / "semiconductor_vocab.txt")


@dataclass
class SessionManagerConfig:
    session_timeout_sec: int = 300
    max_reconnect_attempts: int = 3
    reconnect_delay_sec: int = 5


@dataclass
class AudioGatewayConfig:
    host: str = "0.0.0.0"
    port: int = 19087
    max_concurrent_streams: int = 1000


@dataclass
class KafkaConfig:
    bootstrap_servers: str = "localhost:9092"
    topic_transcript: str = "asr-transcripts"
    topic_events: str = "asr-events"
    group_id: str = "asr-consumer-group"


@dataclass
class NormalizationConfig:
    industry_term_file: str = str(RESOURCES_DIR / "semiconductor_vocab.txt")
    enable_entity_recognition: bool = False


@dataclass
class TranscriptServiceConfig:
    enable_kafka_publish: bool = False
    websocket_port: int = 8765
    kafka: KafkaConfig = field(default_factory=KafkaConfig)


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = "https://slapi.silan.com.cn/v1"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: int = 60


@dataclass
class SenseVoiceConfig:
    """SenseVoice ASR API 配置（通过 SiLAN 网关调用，非本地推理）"""
    api_key: str = ""               # 与 LLM 共用同一个 API Key
    base_url: str = "https://slapi.silan.com.cn/v1"
    model: str = "SenseVoiceSmall"
    timeout: int = 30               # 请求超时（秒）


@dataclass
class AppConfig:
    audio_processor: AudioProcessorConfig = field(default_factory=AudioProcessorConfig)
    asr_worker: ASRWorkerConfig = field(default_factory=ASRWorkerConfig)
    session_manager: SessionManagerConfig = field(default_factory=SessionManagerConfig)
    audio_gateway: AudioGatewayConfig = field(default_factory=AudioGatewayConfig)
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    transcript_service: TranscriptServiceConfig = field(default_factory=TranscriptServiceConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    sensevoice: SenseVoiceConfig = field(default_factory=SenseVoiceConfig)


def load_config() -> AppConfig:
    config = AppConfig()
    
    config.asr_worker.device = os.getenv("ASR_DEVICE", "cpu")
    config.asr_worker.max_batch_size = int(os.getenv("ASR_MAX_BATCH_SIZE", "32"))
    config.asr_worker.max_concurrent_sessions = int(os.getenv("ASR_MAX_SESSIONS", "100"))
    
    config.audio_gateway.port = int(os.getenv("GATEWAY_PORT", "19087"))
    config.audio_gateway.host = os.getenv("GATEWAY_HOST", "0.0.0.0")
    
    config.kafka.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    
    config.asr_worker.hotword_file = os.getenv(
        "HOTWORD_FILE", 
        str(RESOURCES_DIR / "semiconductor_vocab.txt")
    )
    config.normalization.industry_term_file = os.getenv(
        "INDUSTRY_TERM_FILE",
        str(RESOURCES_DIR / "semiconductor_vocab.txt")
    )

    # LLM 配置
    config.llm.api_key = os.getenv("LLM_API_KEY", "")
    config.llm.base_url = os.getenv("LLM_BASE_URL", "https://slapi.silan.com.cn/v1")
    config.llm.model = os.getenv("LLM_MODEL", "deepseek-v4-flash")
    config.llm.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    config.llm.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    config.llm.timeout = int(os.getenv("LLM_TIMEOUT", "60"))

    # SenseVoice API 配置（默认与 LLM 共用同一个 API Key）
    config.sensevoice.api_key = os.getenv("SENSEVOICE_API_KEY", config.llm.api_key)
    config.sensevoice.base_url = os.getenv("SENSEVOICE_BASE_URL", "https://slapi.silan.com.cn/v1")
    config.sensevoice.model = os.getenv("SENSEVOICE_MODEL", "SenseVoiceSmall")
    config.sensevoice.timeout = int(os.getenv("SENSEVOICE_TIMEOUT", "30"))

    return config
