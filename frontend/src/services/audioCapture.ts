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
      partialText: '',
      partialParticipant: '',
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
          // 自动重连（最多 3 次，间隔 1s）
          this.attemptReconnect();
        }
      };

      setTimeout(() => reject(new Error('WebSocket connection timeout')), 5000);
    });
  }

  private reconnectAttempts = 0;
  private async attemptReconnect(): Promise<void> {
    if (this.reconnectAttempts >= 3) {
      console.error('[AudioCapture] Reconnect failed after 3 attempts');
      return;
    }
    this.reconnectAttempts += 1;
    console.log(`[AudioCapture] Reconnect attempt ${this.reconnectAttempts}/3...`);
    await new Promise(r => setTimeout(r, 1000));
    try {
      await this.connectWebSocket();
      await this.createSession();
      this.reconnectAttempts = 0;
      this.updateState({ status: 'recording' });
      console.log('[AudioCapture] Reconnected successfully');
    } catch (e) {
      console.warn('[AudioCapture] Reconnect failed:', e);
      this.attemptReconnect();
    }
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
        token: this.config.token || '',
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

    // 监听系统/浏览器层麦克风 mute 状态（Jitsi 工具栏点静音时也会同步触发）
    // 一旦 mute，立即停止向服务器发送 audio_chunk；unmute 后恢复。
    const audioTrack = this.mediaStream.getAudioTracks()[0];
    if (audioTrack) {
      audioTrack.addEventListener('mute', () => {
        this.updateState({ micMuted: true });
        console.log('[AudioCapture] Mic muted, pausing audio upload');
      });
      audioTrack.addEventListener('unmute', () => {
        this.updateState({ micMuted: false });
        console.log('[AudioCapture] Mic unmuted, resuming audio upload');
      });
      // 初始化时同步一次当前状态（用户可能开会前就已经静音）
      if (audioTrack.muted) {
        this.updateState({ micMuted: true });
      }
    }

    const bufferSize = this.config.chunkSize || 4096;
    this.processor = this.audioContext.createScriptProcessor(bufferSize, 1, 1);

    this.processor.onaudioprocess = (event) => {
      if (this.state.status !== 'recording') return;

      const inputBuffer = event.inputBuffer.getChannelData(0);
      // 静音中 → 不采集也不上传（避免无效带宽 & 防止把静音帧送进 ASR）
      const track = this.mediaStream?.getAudioTracks()[0];
      if (track?.muted || this.state.micMuted) {
        return;
      }
      // 关键：先发再计数。sendAudioChunk 内部会检查 ws.readyState
      // 如果 ws 已关闭则静默丢弃；为了避免误导，我们只在 ws 还活着时计数
      if (this.ws && this.ws.readyState === WebSocket.OPEN && this.sessionId) {
        this.sendAudioChunk(this.config.participantId, inputBuffer);
        this.updateState({ audioChunks: this.state.audioChunks + 1 });
      } else {
        // ws 已断开：停止本地采集
        console.warn('[AudioCapture] WS not open, stopping local capture');
        this.processor?.disconnect();
        this.sourceNode?.disconnect();
        this.mediaStream?.getTracks().forEach(t => t.stop());
        this.updateState({ status: 'idle' });
      }
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
      if (msg.type === 'transcript_partial') {
        this.handlePartialTranscript(msg);
      } else if (msg.type === 'transcript_final') {
        this.handleFinalTranscript(msg);
      }
    } catch {}
  }

  private handlePartialTranscript(result: any): void {
    // 更新当前正在说的文本（实时显示）
    this.state.partialText = result.text || '';
    this.state.partialParticipant = result.participant_name || '';
    this.notify();
  }

  private handleFinalTranscript(result: any): void {
    // 清空 partial 显示
    this.state.partialText = '';
    this.state.partialParticipant = '';
    
    // 添加到正式转写列表
    const transcript: TranscriptResult = {
      type: 'final',
      roomId: result.meeting_id || this.config.roomId,
      participantId: result.participant_id || '',
      participantName: result.participant_name || '',
      text: result.text || '',
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
