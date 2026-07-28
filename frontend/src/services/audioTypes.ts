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
  audioChunks: number;
  startTime?: number;
}

export type StateListener = (state: AudioCaptureState) => void;
