// 消息缓冲与去重 - 基于服务端 seq 序号

import { ChatMessage } from '../types';

export class MessageBuffer {
  private messages: Map<number, ChatMessage> = new Map();
  private maxSeq: number = 0;

  /** 添加消息，自动去重 */
  add(message: ChatMessage): boolean {
    if (this.messages.has(message.seq)) {
      return false; // 重复消息，丢弃
    }
    this.messages.set(message.seq, message);
    if (message.seq > this.maxSeq) {
      this.maxSeq = message.seq;
    }
    return true;
  }

  /** 批量添加 */
  addBatch(messages: ChatMessage[]): void {
    messages.forEach((msg) => this.add(msg));
  }

  /** 获取所有消息（按 seq 排序） */
  getAll(): ChatMessage[] {
    return Array.from(this.messages.values()).sort((a, b) => a.seq - b.seq);
  }

  /** 获取当前最大序号（用于断线重连后同步） */
  getLastSeq(): number {
    return this.maxSeq;
  }

  /** 清空 */
  clear(): void {
    this.messages.clear();
    this.maxSeq = 0;
  }
}
