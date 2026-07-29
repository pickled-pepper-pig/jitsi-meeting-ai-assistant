export interface TranscriptResult {
  type: 'partial' | 'final';
  roomId: string;
  participantId: string;
  participantName?: string;  // 说话人的显示名（来自 ASR 服务回调）
  text: string;
  timestamp: number;
  confidence?: number;
  segmentId?: string;
}

export interface AudioCaptureConfig {
  roomId: string;
  participantId: string;
  participantName: string;
  wsUrl: string;
  token?: string;  // 主持人 JWT（开启 AI 鉴权用）
  sampleRate?: number;
  chunkSize?: number;
}

export interface AudioCaptureState {
  status: 'idle' | 'connecting' | 'recording' | 'stopped';
  participants: Array<{
    id: string;
    name: string;
    isLocal: boolean;
  }>;
  transcripts: TranscriptResult[];
  partialText: string;  // 当前正在说的文本（实时更新）
  partialParticipant: string;  // 正在说话的人
  audioChunks: number;
  startTime?: number;
}

export type StateListener = (state: AudioCaptureState) => void;
