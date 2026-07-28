export interface PCMChunk {
  data: Int16Array;
  sampleRate: number;
  channels: number;
  timestamp: number;
}

export interface WAVResult {
  blob: Blob;
  url: string;
  sizeKB: number;
  durationSec: number;
  sampleRate: number;
  channels: number;
}

export class PCMConverter {
  static readonly TARGET_SAMPLE_RATE = 16000;
  static readonly TARGET_CHANNELS = 1;

  static floatToPCM16(float32: Float32Array): Int16Array {
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16;
  }

  static pcm16ToFloat32(int16: Int16Array): Float32Array {
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7FFF);
    }
    return float32;
  }

  static resampleLinear(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
    if (inputRate === outputRate) return input;
    const ratio = inputRate / outputRate;
    const outLen = Math.floor(input.length / ratio);
    const output = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const srcIdx = i * ratio;
      const i0 = Math.floor(srcIdx);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const frac = srcIdx - i0;
      output[i] = input[i0] * (1 - frac) + input[i1] * frac;
    }
    return output;
  }

  static stereoToMono(left: Float32Array, right: Float32Array): Float32Array {
    const len = Math.min(left.length, right.length);
    const mono = new Float32Array(len);
    for (let i = 0; i < len; i++) {
      mono[i] = (left[i] + right[i]) * 0.5;
    }
    return mono;
  }

  static mergeChunks(chunks: Int16Array[]): Int16Array {
    if (!chunks.length) return new Int16Array(0);
    const totalLen = chunks.reduce((s, c) => s + c.length, 0);
    const merged = new Int16Array(totalLen);
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.length;
    }
    return merged;
  }

  static encodeWAV(samples: Int16Array, sampleRate: number, channels: number = 1): Blob {
    const bytesPerSample = 2;
    const blockAlign = channels * bytesPerSample;
    const byteRate = sampleRate * blockAlign;
    const dataSize = samples.length * bytesPerSample;
    const bufferSize = 44 + dataSize;

    const buffer = new ArrayBuffer(bufferSize);
    const view = new DataView(buffer);
    const writeStr = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i));
      }
    };

    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, channels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, dataSize, true);

    const bytes = new Uint8Array(buffer, 44);
    bytes.set(new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength));

    return new Blob([buffer], { type: 'audio/wav' });
  }

  static async saveAsWAV(
    chunks: Int16Array[],
    sampleRate: number,
    startTime: number,
    _fileName: string,
  ): Promise<WAVResult> {
    const merged = PCMConverter.mergeChunks(chunks);
    const wavBlob = PCMConverter.encodeWAV(merged, sampleRate, PCMConverter.TARGET_CHANNELS);
    const url = URL.createObjectURL(wavBlob);
    const durationSec = ((Date.now() - startTime) / 1000).toFixed(1) as unknown as number;
    return {
      blob: wavBlob,
      url,
      sizeKB: Math.round((wavBlob.size / 1024) * 10) / 10,
      durationSec: durationSec as number,
      sampleRate,
      channels: PCMConverter.TARGET_CHANNELS,
    };
  }

  static downloadWAV(result: WAVResult, fileName?: string): void {
    const a = document.createElement('a');
    a.href = result.url;
    a.download = fileName || `recording_${Date.now()}.wav`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  static revokeWAV(result: WAVResult): void {
    URL.revokeObjectURL(result.url);
  }
}
