import { PCMConverter, WAVResult } from './pcmConverter';

export interface ParticipantTrackInfo {
  participantId: string;
  participantName: string;
  trackId: string;
  isLocal: boolean;
}

export interface CaptureState {
  participantId: string;
  participantName: string;
  isCapturing: boolean;
  chunksCount: number;
  startedAt: number | null;
  audioLevel: number;
}

export type CaptureEventListener = (state: CaptureState) => void;
export type WAVReadyListener = (info: ParticipantTrackInfo, wav: WAVResult) => void;
export type ErrorListener = (participantId: string, error: Error) => void;

export class ParticipantAudioReceiver {
  private audioContext: AudioContext | null = null;
  private audioContextRate: number = 16000;
  private isInitialized = false;

  private captures = new Map<string, CaptureSession>();
  private stateListeners = new Map<string, Set<CaptureEventListener>>();
  private wavListeners = new Set<WAVReadyListener>();
  private errorListeners = new Set<ErrorListener>();

  private totalChunks = 0;

  async initialize(targetSampleRate: number = PCMConverter.TARGET_SAMPLE_RATE): Promise<void> {
    if (this.isInitialized) return;
    this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
      sampleRate: targetSampleRate,
    });
    this.audioContextRate = this.audioContext.sampleRate;
    this.isInitialized = true;
  }

  getAudioContextRate(): number {
    return this.audioContextRate;
  }

  subscribeState(participantId: string, listener: CaptureEventListener): () => void {
    if (!this.stateListeners.has(participantId)) {
      this.stateListeners.set(participantId, new Set());
    }
    this.stateListeners.get(participantId)!.add(listener);
    const cap = this.captures.get(participantId);
    if (cap) {
      listener(this.getCaptureState(participantId));
    }
    return () => {
      this.stateListeners.get(participantId)?.delete(listener);
    };
  }

  subscribeWAV(listener: WAVReadyListener): () => void {
    this.wavListeners.add(listener);
    return () => this.wavListeners.delete(listener);
  }

  subscribeError(listener: ErrorListener): () => void {
    this.errorListeners.add(listener);
    return () => this.errorListeners.delete(listener);
  }

  getCaptureState(participantId: string): CaptureState {
    const cap = this.captures.get(participantId);
    if (!cap) {
      return {
        participantId,
        participantName: '未知',
        isCapturing: false,
        chunksCount: 0,
        startedAt: null,
        audioLevel: 0,
      };
    }
    return {
      participantId,
      participantName: cap.info.participantName,
      isCapturing: true,
      chunksCount: cap.chunks.length,
      startedAt: cap.startedAt,
      audioLevel: cap.audioLevel,
    };
  }

  getAllCaptureStates(): CaptureState[] {
    return Array.from(this.captures.keys()).map((id) => this.getCaptureState(id));
  }

  getTotalChunks(): number {
    return this.totalChunks;
  }

  async startCapture(
    mediaTrack: MediaStreamTrack,
    info: ParticipantTrackInfo,
    options: { sendToBackend?: boolean; backendWsUrl?: string; meetingId?: string } = {},
  ): Promise<void> {
    if (!this.isInitialized || !this.audioContext) {
      throw new Error('ParticipantAudioReceiver 未初始化');
    }
    if (mediaTrack.kind !== 'audio') {
      throw new Error(`只能捕获音频轨，收到: ${mediaTrack.kind}`);
    }
    if (this.captures.has(info.participantId)) {
      const existing = this.captures.get(info.participantId)!;
      if (existing.mediaTrack.readyState === 'live') {
        return;
      }
      await this.stopCapture(info.participantId);
    }

    const stream = new MediaStream([mediaTrack]);
    const sourceNode = this.audioContext.createMediaStreamSource(stream);
    const bufferSize = 4096;
    const processor = this.audioContext.createScriptProcessor(bufferSize, 1, 1);
    const muteGain = this.audioContext.createGain();
    muteGain.gain.value = 0;

    const session: CaptureSession = {
      info,
      mediaTrack,
      stream,
      sourceNode,
      processor,
      muteGain,
      chunks: [],
      startedAt: Date.now(),
      audioLevel: 0,
      sendToBackend: options.sendToBackend ?? false,
      ws: null,
      sessionId: null,
      meetingId: options.meetingId || '',
    };

    processor.onaudioprocess = (e: AudioProcessingEvent) => {
      if (!this.captures.has(info.participantId)) return;

      const rawInput = e.inputBuffer.getChannelData(0);

      let level = 0;
      for (let i = 0; i < rawInput.length; i++) {
        const abs = Math.abs(rawInput[i]);
        if (abs > level) level = abs;
      }
      session.audioLevel = level;

      let input: Float32Array;
      if (this.audioContextRate !== PCMConverter.TARGET_SAMPLE_RATE) {
        input = PCMConverter.resampleLinear(
          rawInput,
          this.audioContextRate,
          PCMConverter.TARGET_SAMPLE_RATE,
        );
      } else {
        input = new Float32Array(rawInput);
      }

      const pcm16 = PCMConverter.floatToPCM16(input);
      session.chunks.push(pcm16);
      this.totalChunks++;

      if (session.sendToBackend && session.ws?.readyState === WebSocket.OPEN) {
        session.ws.send(
          JSON.stringify({
            action: 'audio_chunk',
            session_id: session.sessionId,
            participant_id: info.participantId,
            participant_name: info.participantName,
            sample_rate: PCMConverter.TARGET_SAMPLE_RATE,
            channels: PCMConverter.TARGET_CHANNELS,
            audio: this.pcmToBase64(pcm16),
            timestamp: Date.now(),
          }),
        );
      }

      this.notifyState(info.participantId);
    };

    sourceNode.connect(processor);
    processor.connect(muteGain);
    muteGain.connect(this.audioContext.destination);

    mediaTrack.addEventListener('ended', () => {
      this.stopCapture(info.participantId).catch(() => {});
    });

    this.captures.set(info.participantId, session);
    this.notifyState(info.participantId);
  }

  async stopCapture(participantId: string): Promise<void> {
    const cap = this.captures.get(participantId);
    if (!cap) return;

    try {
      cap.processor.disconnect();
      cap.sourceNode.disconnect();
      cap.muteGain.disconnect();
      cap.stream.getTracks().forEach((t) => t.stop());
    } catch {}

    if (cap.sendToBackend && cap.ws?.readyState === WebSocket.OPEN && cap.sessionId) {
      try {
        cap.ws.send(
          JSON.stringify({
            action: 'end_session',
            session_id: cap.sessionId,
          }),
        );
      } catch {}
    }

    // 关闭该 session 的独立 ws 连接
    if (cap.ws) {
      try {
        cap.ws.close();
      } catch {}
    }

    try {
      const wav = await PCMConverter.saveAsWAV(
        cap.chunks,
        PCMConverter.TARGET_SAMPLE_RATE,
        cap.startedAt,
        `${cap.info.participantName}_${Date.now()}.wav`,
      );
      for (const listener of this.wavListeners) {
        listener(cap.info, wav);
      }
    } catch (err) {
      for (const listener of this.errorListeners) {
        listener(participantId, err as Error);
      }
    }

    this.captures.delete(participantId);
    this.notifyState(participantId);
  }

  /**
   * 给指定 session 启动一个独立的后端 ws 连接，并发 create_session
   * 每个参会者一个 ws + 一个 session，独立 ASR 识别
   */
  async connectBackendForSession(
    participantId: string,
    wsUrl: string,
  ): Promise<void> {
    const cap = this.captures.get(participantId);
    if (!cap) throw new Error(`session not found: ${participantId}`);
    if (cap.ws && cap.ws.readyState === WebSocket.OPEN) return;  // 已连

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      const sessionId = `session-${Date.now()}-${participantId}`;

      const cleanup = () => {
        ws.removeEventListener('message', onMsg);
        ws.removeEventListener('error', onErr);
      };

      const onMsg = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'session_created' && msg.session_id === sessionId) {
            cleanup();
            cap.ws = ws;
            cap.sessionId = sessionId;
            console.log(`[PAR] Backend session created: ${sessionId} for ${cap.info.participantName}`);
            resolve();
          } else if (msg.type === 'error') {
            cleanup();
            reject(new Error(msg.message || 'create_session failed'));
          }
        } catch {}
      };

      const onErr = () => {
        cleanup();
        reject(new Error('WebSocket connection error'));
      };

      ws.addEventListener('message', onMsg);
      ws.addEventListener('error', onErr);

      ws.onopen = () => {
        ws.send(JSON.stringify({
          action: 'create_session',
          session_id: sessionId,
          meeting_id: cap.meetingId,
          participant_id: cap.info.participantId,
          participant_name: cap.info.participantName,
          token: '',
        }));
      };

      ws.onclose = () => {
        console.log(`[PAR] ws closed for ${cap.info.participantName}`);
        if (cap.ws === ws) {
          cap.ws = null;
          cap.sessionId = null;
        }
      };
    });
  }

  async stopAll(): Promise<void> {
    const ids = Array.from(this.captures.keys());
    for (const id of ids) {
      await this.stopCapture(id);
    }
  }

  async destroy(): Promise<void> {
    await this.stopAll();
    if (this.audioContext) {
      try {
        await this.audioContext.close();
      } catch {}
      this.audioContext = null;
    }
    this.isInitialized = false;
  }

  getCaptureWAV(participantId: string): WAVResult | null {
    return this._pendingWAVs.get(participantId) || null;
  }

  downloadAll(): void {
    for (const [id, wav] of this._pendingWAVs) {
      const cap = this.captures.get(id);
      const name = cap?.info.participantName || id;
      PCMConverter.downloadWAV(wav, `${name}_${Date.now()}.wav`);
    }
    this._pendingWAVs.clear();
  }

  private _pendingWAVs = new Map<string, WAVResult>();

  private notifyState(participantId: string): void {
    const state = this.getCaptureState(participantId);
    const listeners = this.stateListeners.get(participantId);
    if (listeners) {
      for (const l of listeners) {
        try {
          l(state);
        } catch {}
      }
    }
  }

  private pcmToBase64(int16: Int16Array): string {
    const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(
        null,
        Array.from(bytes.subarray(i, i + chunkSize)) as unknown as number[],
      );
    }
    return btoa(binary);
  }
}

interface CaptureSession {
  info: ParticipantTrackInfo;
  mediaTrack: MediaStreamTrack;
  stream: MediaStream;
  sourceNode: MediaStreamAudioSourceNode;
  processor: ScriptProcessorNode;
  muteGain: GainNode;
  chunks: Int16Array[];
  startedAt: number;
  audioLevel: number;
  sendToBackend: boolean;
  ws: WebSocket | null;
  sessionId: string | null;
  meetingId: string;
}
