export interface TranscriptResult {
  type: 'partial' | 'final';
  roomId: string;
  participantId: string;
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
