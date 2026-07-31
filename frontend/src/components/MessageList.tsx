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
  '#7E8C5E', // 橄榄灰
  '#A36E5E', // 砖红灰
  '#6E6E8C', // 暮色蓝
  '#5E8E7E', // 灰湖绿
];

function getSpeakerColor(sender: string): string {
  // 简单字符串哈希：累加 charCode
  let hash = 0;
  for (let i = 0; i < sender.length; i++) {
    hash = (hash * 31 + sender.charCodeAt(i)) >>> 0;
  }
  return SPEAKER_COLORS[hash % SPEAKER_COLORS.length];
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
      second: '2-digit',
    });
  };

  if (messages.length === 0) {
    return (
      <div className="message-list empty" ref={listRef}>
        <div className="empty-tip">
          暂无消息
          <br />
          开始聊天后，消息会实时显示在这里
        </div>
      </div>
    );
  }

  return (
    <div className="message-list" ref={listRef}>
      {messages.map((msg) => {
        // transcript 类消息按 sender 着色；其他类型保留默认样式
        const isTranscript = msg.type === 'text';
        const speakerColor = isTranscript ? getSpeakerColor(msg.sender) : undefined;
        return (
        <div
          key={msg.id}
          className={`message-item message-${msg.type}`}
          style={isTranscript ? { borderLeft: `3px solid ${speakerColor}` } : undefined}
        >
          {msg.type === 'summary' ? (
            <div className="message-summary">
              <div className="message-summary-header">📋 会议总结</div>
              <pre className="message-summary-content">{msg.content}</pre>
              <span className="message-time">{formatTime(msg.timestamp)}</span>
            </div>
          ) : (
            <>
              <div className="message-header">
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
