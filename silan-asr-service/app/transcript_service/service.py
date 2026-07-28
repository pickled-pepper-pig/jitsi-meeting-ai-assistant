import logging
import json
import time
import threading
from typing import Dict, Optional, Callable
from app.config.settings import TranscriptServiceConfig
from app.normalization.service import NormalizationService


logger = logging.getLogger(__name__)


class TranscriptService:
    def __init__(self, config: TranscriptServiceConfig = None):
        self.config = config or TranscriptServiceConfig()
        self.normalization = NormalizationService()
        self._kafka_producer = None
        self._websocket_clients: Dict[str, list] = {}
        self._websocket_callback: Optional[Callable] = None
        self.lock = threading.Lock()
        
        if self.config.enable_kafka_publish:
            self._init_kafka()
    
    def _init_kafka(self) -> None:
        try:
            from kafka import KafkaProducer
            
            self._kafka_producer = KafkaProducer(
                bootstrap_servers=self.config.kafka.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            logger.info("Kafka producer initialized")
        except ImportError:
            logger.warning("kafka-python not installed, skipping Kafka initialization")
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
    
    def set_websocket_callback(self, callback: Callable) -> None:
        self._websocket_callback = callback
    
    def process_transcripts(self, transcripts: list) -> None:
        for transcript in transcripts:
            self._process_single(transcript)
    
    def _process_single(self, transcript: dict) -> None:
        try:
            text = transcript.get("interim_text", "")
            
            normalized_text = self.normalization.normalize(text)
            
            transcript["normalized_text"] = normalized_text
            
            self._publish_to_websocket(transcript)
            
            if self.config.enable_kafka_publish:
                self._publish_to_kafka(transcript)
            
            logger.debug(f"Processed transcript for {transcript['session_id']}: {normalized_text[:50]}")
        
        except Exception as e:
            logger.error(f"Processing transcript error: {e}")
    
    def _publish_to_websocket(self, transcript: dict) -> None:
        if self._websocket_callback:
            try:
                self._websocket_callback(transcript)
            except Exception as e:
                logger.error(f"Publishing to WebSocket error: {e}")
    
    def _publish_to_kafka(self, transcript: dict) -> None:
        if not self._kafka_producer:
            return
        
        try:
            self._kafka_producer.send(
                self.config.kafka.topic_transcript,
                value=transcript
            )
        except Exception as e:
            logger.error(f"Publishing to Kafka error: {e}")
    
    def register_websocket_client(self, meeting_id: str, client_id: str) -> None:
        with self.lock:
            if meeting_id not in self._websocket_clients:
                self._websocket_clients[meeting_id] = []
            if client_id not in self._websocket_clients[meeting_id]:
                self._websocket_clients[meeting_id].append(client_id)
    
    def unregister_websocket_client(self, meeting_id: str, client_id: str) -> None:
        with self.lock:
            if meeting_id in self._websocket_clients:
                if client_id in self._websocket_clients[meeting_id]:
                    self._websocket_clients[meeting_id].remove(client_id)
    
    def get_clients_for_meeting(self, meeting_id: str) -> list:
        with self.lock:
            return self._websocket_clients.get(meeting_id, [])
    
    def finalize_session(self, session_id: str) -> dict:
        final_transcript = {
            "session_id": session_id,
            "finalized": True,
            "timestamp": int(time.time() * 1000)
        }
        
        if self.config.enable_kafka_publish:
            self._publish_to_kafka(final_transcript)
        
        return final_transcript
