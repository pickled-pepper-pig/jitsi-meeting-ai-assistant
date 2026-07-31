// 消息列表组件 - 展示实时聊天消息

import { useEffect, useRef } from 'react';
import { ChatMessage } from '../types';

interface MessageListProps {
  messages: ChatMessage[];
}

// 根据 sender 名字生成稳定的颜色（同一人始终用同一色，多人会议便于区分）
// 莫兰迪色系：低饱和、带灰调；稍加深保证在浅色背景上可读
const SPEAKER_COLORS = [
  '#5B7A8C', // 雾霾蓝
  '#6B8E7A', // 灰绿
  '#A8896E', // 焦糖棕
  '#7D6E8C', // 灰紫
  '#A8706E', // 豆沙红
  '#5E8B8E', // 灰青
];

function getSpeakerColor(sender: string): string {
  // 简单字符串哈希：累加 charCode
  let hash = 0;
  for (let i = 0; i < sender.length; i++) {
    hash = (hash * 31 + sender.charCodeAt(i)) >>> 0;
  }
  return SPEAKER_COLORS[hash % SPEAKER_COLORS.length];
}

// 取名字的首字符（中文取首个字，英文取首字母并大写）
function getInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return '?';
  return trimmed.charAt(0).toUpperCase();
}

export function MessageList({ messages }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null);

  // 新消息时自动滚动到底部
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (messages.length === 0) {
    return (
      <div className="message-list empty" ref={listRef}>
        <div className="empty-tip">
          <div className="empty-icon">💬</div>
          <div className="empty-title">暂无会议纪要</div>
          <div className="empty-subtitle">开启 AI 转写后，发言内容将自动记录于此</div>
        </div>
      </div>
    );
  }

  return (
    <div className="message-list" ref={listRef}>
      {messages.map((msg) => {
        const isTranscript = msg.type === 'text';
        const isSummary = msg.type === 'summary';
        const speakerColor = isTranscript ? getSpeakerColor(msg.sender) : undefined;
        return (
        <div
          key={msg.id}
          className={`message-item message-${msg.type}`}
          style={isTranscript ? { borderLeftColor: speakerColor } : undefined}
        >
          {isSummary ? (
            <div className="message-summary">
              <div className="message-summary-header">
                <span className="message-summary-icon">📋</span>
                <span className="message-summary-title">会议总结</span>
                <span className="message-time">{formatTime(msg.timestamp)}</span>
              </div>
              <pre className="message-summary-content">{msg.content}</pre>
            </div>
          ) : (
            <>
              <div className="message-header">
                <span
                  className="message-avatar"
                  style={speakerColor ? { background: speakerColor } : undefined}
                >
                  {getInitial(msg.sender)}
                </span>
                <span
                  className="message-sender"
                  style={isTranscript ? { color: speakerColor } : undefined}
                >
                  {msg.sender}
                </span>
                <span className="message-time">{formatTime(msg.timestamp)}</span>
              </div>
              <div className="message-content">{msg.content}</div>
            </>
          )}
        </div>
        );
      })}
    </div>
  );
}
