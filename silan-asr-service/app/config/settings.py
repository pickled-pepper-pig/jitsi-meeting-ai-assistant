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
    vad_threshold: float = 0.001
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
    port: int = 8080
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
class AppConfig:
    audio_processor: AudioProcessorConfig = field(default_factory=AudioProcessorConfig)
    asr_worker: ASRWorkerConfig = field(default_factory=ASRWorkerConfig)
    session_manager: SessionManagerConfig = field(default_factory=SessionManagerConfig)
    audio_gateway: AudioGatewayConfig = field(default_factory=AudioGatewayConfig)
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    transcript_service: TranscriptServiceConfig = field(default_factory=TranscriptServiceConfig)


def load_config() -> AppConfig:
    config = AppConfig()
    
    config.asr_worker.device = os.getenv("ASR_DEVICE", "cpu")
    config.asr_worker.max_batch_size = int(os.getenv("ASR_MAX_BATCH_SIZE", "32"))
    config.asr_worker.max_concurrent_sessions = int(os.getenv("ASR_MAX_SESSIONS", "100"))
    
    config.audio_gateway.port = int(os.getenv("GATEWAY_PORT", "8080"))
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
    
    return config
