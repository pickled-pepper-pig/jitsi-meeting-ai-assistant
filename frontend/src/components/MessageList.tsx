// 消息列表组件 - 展示实时聊天消息

import { useEffect, useRef } from 'react';
import { ChatMessage } from '../types';

interface MessageListProps {
  messages: ChatMessage[];
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
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`message-item message-${msg.type}`}
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
                <span className="message-sender">{msg.sender}</span>
                <span className="message-time">{formatTime(msg.timestamp)}</span>
              </div>
              <div className="message-content">{msg.content}</div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
