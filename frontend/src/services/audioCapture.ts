// 音频采集服务 - 原生 WebSocket 连接后端 ASR 服务

import { TranscriptResult, AudioCaptureConfig, AudioCaptureState, StateListener } from './audioTypes';

export class AudioCaptureService {
  private config: AudioCaptureConfig;
  private ws: WebSocket | null = null;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private state: AudioCaptureState;
  private listeners: Set<StateListener> = new Set();
  private sessionId: string | null = null;

  constructor(config: AudioCaptureConfig) {
    this.config = {
      sampleRate: 16000,
      chunkSize: 4096,
      ...config,
    };
    this.state = {
      status: 'idle',
      participants: [],
      transcripts: [],
      audioChunks: 0,
    };
  }

  subscribe(listener: StateListener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    this.state = { ...this.state };
    this.listeners.forEach(l => l(this.state));
  }

  async start(): Promise<void> {
    this.updateState({ status: 'connecting' });

    try {
      await this.connectWebSocket();
      await this.createSession();
      await this.startLocalCapture();

      this.updateState({ status: 'recording', startTime: Date.now() });
      console.log('[AudioCapture] Recording started');
    } catch (err) {
      console.error('[AudioCapture] Start failed:', err);
      this.updateState({ status: 'idle' });
      throw err;
    }
  }

  private connectWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsUrl = this.config.wsUrl.replace(/^http/, 'ws');
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[AudioCapture] WebSocket connected');
        resolve();
      };

      this.ws.onmessage = (event) => {
        this.handleServerMessage(event.data);
      };

      this.ws.onerror = () => {
        reject(new Error('WebSocket connection error'));
      };

      this.ws.onclose = () => {
        console.log('[AudioCapture] WebSocket closed');
        if (this.state.status === 'recording') {
          this.updateState({ status: 'idle' });
        }
      };

      setTimeout(() => reject(new Error('WebSocket connection timeout')), 5000);
    });
  }

  private createSession(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'));
        return;
      }

      const sessionId = `session-${Date.now()}`;
      this.sessionId = sessionId;

      const onMessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'session_created' && msg.session_id === sessionId) {
            this.ws!.removeEventListener('message', onMessage);
            resolve();
          } else if (msg.type === 'error') {
            this.ws!.removeEventListener('message', onMessage);
            reject(new Error(msg.message));
          }
        } catch {}
      };

      this.ws.addEventListener('message', onMessage);

      this.ws.send(JSON.stringify({
        action: 'create_session',
        session_id: sessionId,
        meeting_id: this.config.roomId,
        participant_id: this.config.participantId,
        participant_name: this.config.participantName,
      }));

      setTimeout(() => {
        this.ws!.removeEventListener('message', onMessage);
        reject(new Error('Session creation timeout'));
      }, 5000);
    });
  }

  private async startLocalCapture(): Promise<void> {
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });

      this.addParticipant(this.config.participantId, this.config.participantName, true);
      this.setupAudioProcessing();
    } catch (err) {
      console.error('[AudioCapture] Failed to get media:', err);
      throw err;
    }
  }

  private setupAudioProcessing(): void {
    if (!this.mediaStream) return;

    this.audioContext = new AudioContext({ sampleRate: this.config.sampleRate });
    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);

    const bufferSize = this.config.chunkSize || 4096;
    this.processor = this.audioContext.createScriptProcessor(bufferSize, 1, 1);

    this.processor.onaudioprocess = (event) => {
      if (this.state.status !== 'recording') return;

      const inputBuffer = event.inputBuffer.getChannelData(0);
      // 发送 float32 PCM 数据（base64 编码）
      this.sendAudioChunk(this.config.participantId, inputBuffer);
      this.updateState({ audioChunks: this.state.audioChunks + 1 });
    };

    this.sourceNode.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
  }

  private floatToBase64(float32: Float32Array): string {
    const bytes = new Uint8Array(float32.buffer, float32.byteOffset, float32.byteLength);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  private sendAudioChunk(_participantId: string, pcmData: Float32Array): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    if (!this.sessionId) return;

    this.ws.send(JSON.stringify({
      action: 'audio_chunk',
      session_id: this.sessionId,
      audio: this.floatToBase64(pcmData),
      sample_rate: this.config.sampleRate,
    }));
  }

  private handleServerMessage(data: string): void {
    try {
      const msg = JSON.parse(data);
      if (msg.type === 'transcript') {
        this.handleTranscript(msg);
      }
    } catch {}
  }

  private handleTranscript(result: any): void {
    const transcript: TranscriptResult = {
      type: result.is_final ? 'final' : 'partial',
      roomId: result.meeting_id || this.config.roomId,
      participantId: result.participant_id || '',
      text: result.interim_text || result.final_text || '',
      timestamp: result.timestamp || Date.now(),
    };
    this.state.transcripts = [...this.state.transcripts, transcript];
    if (this.state.transcripts.length > 100) {
      this.state.transcripts = this.state.transcripts.slice(-100);
    }
    this.notify();
  }

  private addParticipant(id: string, name: string, isLocal: boolean): void {
    if (!this.state.participants.find(p => p.id === id)) {
      this.state.participants.push({ id, name, isLocal });
      this.notify();
    }
  }

  private updateState(partial: Partial<AudioCaptureState>): void {
    this.state = { ...this.state, ...partial };
    this.notify();
  }

  async stop(): Promise<void> {
    this.updateState({ status: 'stopped' });

    // 结束音频 session
    if (this.ws && this.ws.readyState === WebSocket.OPEN && this.sessionId) {
      this.ws.send(JSON.stringify({
        action: 'end_session',
        session_id: this.sessionId,
      }));
    }

    if (this.processor) this.processor.disconnect();
    if (this.sourceNode) this.sourceNode.disconnect();
    if (this.mediaStream) this.mediaStream.getTracks().forEach(t => t.stop());
    if (this.audioContext) await this.audioContext.close();
    if (this.ws) this.ws.close();

    this.updateState({ status: 'idle', audioChunks: 0, startTime: undefined });
    console.log('[AudioCapture] Stopped');
  }
}
