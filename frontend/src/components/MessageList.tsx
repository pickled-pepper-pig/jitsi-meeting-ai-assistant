// 消息列表组件 - 展示实时聊天消息

import { Fragment, useEffect, useRef } from 'react';
import { ChatMessage } from '../types';

interface MessageListProps {
  messages: ChatMessage[];
  onScrollToSummary?: (id: string) => void;
  showSummaryNav?: boolean; // 是否显示左侧总结导航
  summaryNavItems?: Array<{ id: string; num: number; theme: typeof SUMMARY_THEMES[number] }>; // 导航数据（独立于 messages，用于聊天记录 Tab 也显示）
  // 折叠区间：key 为 summaryId，value 表示该 summary 到上一条 summary 之间的消息是否折叠
  // 折叠展示在聊天 Tab 中（会议总结 Tab 不参与折叠）
  collapsedRanges?: Set<string>;
  onToggleRange?: (summaryId: string) => void;
  // 是否渲染 summary 卡片。聊天记录 Tab = false（用折叠条代替），会议总结 Tab = true（只显示卡片）
  renderSummaryCards?: boolean;
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
  let hash = 0;
  for (let i = 0; i < sender.length; i++) {
    hash = (hash * 31 + sender.charCodeAt(i)) >>> 0;
  }
  return SPEAKER_COLORS[hash % SPEAKER_COLORS.length];
}

function getInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return '?';
  return trimmed.charAt(0).toUpperCase();
}

// 会议总结主题：左侧色条 + 标题色 + 浅背景
const SUMMARY_THEMES = [
  { bar: '#a855f7', bg: '#faf5ff', title: '#7c3aed', icon: '📋' },
  { bar: '#0ea5e9', bg: '#f0f9ff', title: '#0284c7', icon: '📝' },
  { bar: '#22c55e', bg: '#f0fdf4', title: '#16a34a', icon: '✅' },
  { bar: '#f59e0b', bg: '#fffbeb', title: '#d97706', icon: '📌' },
  { bar: '#ec4899', bg: '#fdf2f8', title: '#db2777', icon: '🎯' },
];

// 把 LLM 的 Markdown 格式总结渲染成结构化 HTML
// 支持：### 标题 / **加粗** / - 列表 / - [ ] 待办
function renderSummaryMarkdown(md: string): JSX.Element[] {
  const lines = md.split('\n');
  const blocks: JSX.Element[] = [];
  let listBuffer: string[] = [];
  let key = 0;

  const flushList = () => {
    if (listBuffer.length === 0) return;
    blocks.push(
      <ul key={key++} className="summary-list">
        {listBuffer.map((item, i) => (
          <li
            key={i}
            className={
              item.startsWith('[x]') || item.startsWith('[X]')
                ? 'summary-list-item checked'
                : item.startsWith('[ ]')
                  ? 'summary-list-item todo'
                  : 'summary-list-item'
            }
            dangerouslySetInnerHTML={{ __html: formatInline(item) }}
          />
        ))}
      </ul>
    );
    listBuffer = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();

    if (line.startsWith('### ')) {
      flushList();
      blocks.push(
        <div key={key++} className="summary-section">
          <h4 className="summary-h">{line.slice(4)}</h4>
        </div>
      );
    } else if (line.startsWith('- ') || line.startsWith('- [ ]') || line.startsWith('- [x]') || line.startsWith('- [X]')) {
      listBuffer.push(line.slice(2));
    } else if (line === '') {
      flushList();
    } else {
      flushList();
      blocks.push(
        <p
          key={key++}
          className="summary-p"
          dangerouslySetInnerHTML={{ __html: formatInline(line) }}
        />
      );
    }
  }
  flushList();
  return blocks;
}

// 加粗：**xxx** → <strong>xxx</strong>
function formatInline(s: string): string {
  return s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

export function MessageList({ messages, onScrollToSummary, showSummaryNav, summaryNavItems, collapsedRanges, onToggleRange, renderSummaryCards }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null);

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

  // renderMessage 提取为组件方法 - 单条消息（不含 summary）渲染
  const renderMessage = (msg: ChatMessage, _mapIdx: number, _summaryIndex: number): React.ReactNode => {
    const isTranscript = msg.type === 'text' || msg.type === 'transcript';
    const speakerColor = isTranscript ? getSpeakerColor(msg.sender) : undefined;
    const leftColor = isTranscript ? speakerColor : undefined;
    return (
      <div key={msg.id} data-msg-id={msg.id}>
        <div
          className={`message-item message-${msg.type}`}
          style={leftColor ? { borderLeftColor: leftColor } : undefined}
        >
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
        </div>
      </div>
    );
  };

  let summaryIndex = 0;

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

  // TOC：优先使用外部传入的 summaryNavItems（用于聊天记录 Tab 也能显示导航），
  // 否则从当前 messages 提取（用于会议总结 Tab）
  const tocItems = summaryNavItems
    ?? messages
      .map((m) => ({ msg: m }))
      .filter(({ msg }) => msg.type === 'summary')
      .map(({ msg }, i) => ({
        id: msg.id,
        num: i + 1,
        theme: SUMMARY_THEMES[i % SUMMARY_THEMES.length],
      }));

  return (
    <div className="message-list-wrapper">
      {/* 左侧浮动目录：仅在总结 Tab 或聊天记录 Tab 且有总结时显示 */}
      {showSummaryNav && tocItems.length > 0 && (
        <div className="summary-nav" aria-label="会议总结导航">
          <div className="summary-nav-title">会议总结</div>
          <div className="summary-nav-list">
            {tocItems.map((item) => (
              <button
                key={item.id}
                className="summary-nav-item"
                onClick={() => onScrollToSummary?.(item.id)}
                title={`跳转到 会议总结 #${item.num}`}
              >
                <span
                  className="summary-nav-dot"
                  style={{ backgroundColor: item.theme.bar }}
                />
                <span className="summary-nav-label">#{item.num}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="message-list" ref={listRef}>
      {(() => {
        // ============ 会议总结 Tab：只显示总结卡片 ============
        if (renderSummaryCards) {
          return messages.map((m) => {
            const myTheme = SUMMARY_THEMES[summaryIndex++ % SUMMARY_THEMES.length];
            const num = summaryIndex;
            const leftColor = m.type === 'summary' ? myTheme.bar : undefined;
            if (m.type !== 'summary') return null;
            return (
              <div key={m.id} data-msg-id={m.id}>
                <div
                  className={`message-item message-summary`}
                  style={{ borderLeftColor: leftColor }}
                >
                  <div
                    className="summary-card"
                    style={{ backgroundColor: myTheme.bg }}
                  >
                    <div className="summary-card-header">
                      <span
                        className="summary-card-icon"
                        style={{ backgroundColor: myTheme.bar }}
                      >
                        {myTheme.icon}
                      </span>
                      <div className="summary-card-title-wrap">
                        <span className="summary-card-title" style={{ color: myTheme.title }}>
                          会议总结 #{num}
                        </span>
                        <span className="summary-card-subtitle">
                          {new Date(m.timestamp).toLocaleString('zh-CN', {
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                      </div>
                    </div>
                    <div className="summary-card-body">
                      {renderSummaryMarkdown(m.content)}
                    </div>
                  </div>
                </div>
                <div className="summary-divider" data-summary-divider={m.id} />
              </div>
            );
          });
        }

        // ============ 聊天记录 Tab：总结过的聊天段折叠成 antd Collapse 条 ============
        // 每条 summary 把它「之前、上次总结之后」的那段聊天折叠成一个可点击条
        // 折叠条出现在那段聊天的原始位置；末尾聊天段（最后一次总结之后）永远展开
        type ChatSeg = {
          startIdx: number;
          endIdx: number;
          ownerSummaryId: string | null; // null = 末尾聊天段（不折叠）
          summaryTime?: number;          // 折叠条展示的总结时间
          summaryNum: number;            // 会议总结 #1, #2...
          messages: ChatMessage[];
          collapsed: boolean;
        };
        const chatSegs: ChatSeg[] = [];
        let cursor = 0;
        let summaryNum = 0; // 会议总结序号
        for (let i = 0; i < messages.length; i++) {
          const m = messages[i];
          if (m.type === 'summary') {
            summaryNum++; // 遇到总结，序号+1
            if (i > cursor) {
              chatSegs.push({
                startIdx: cursor,
                endIdx: i,
                ownerSummaryId: m.id,
                summaryTime: m.timestamp,
                summaryNum,
                messages: messages.slice(cursor, i),
                collapsed: collapsedRanges?.has(m.id) ?? true,
              });
            }
            cursor = i + 1;
          }
        }
        if (cursor < messages.length) {
          chatSegs.push({
            startIdx: cursor,
            endIdx: messages.length,
            ownerSummaryId: null,
            summaryNum: 0,
            messages: messages.slice(cursor),
            collapsed: false,
          });
        }

        return chatSegs.map((seg) => {
          if (seg.ownerSummaryId === null) {
            // 末尾聊天段：永远展开，正常渲染
            return (
              <Fragment key={`chat-${seg.startIdx}-${seg.endIdx}`}>
                {seg.messages.map((m, j) => renderMessage(m, seg.startIdx + j, summaryIndex))}
              </Fragment>
            );
          }
          // 被总结的聊天段：antd Collapse 条
          const isCollapsed = seg.collapsed;
          const timeLabel = seg.summaryTime
            ? new Date(seg.summaryTime).toLocaleString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
              })
            : '';
          return (
            <div
              key={`range-${seg.ownerSummaryId}`}
              className={`collapsed-range ${isCollapsed ? '' : 'is-open'}`}
            >
              <div
                className="collapsed-range-header"
                role="button"
                tabIndex={0}
                onClick={() => onToggleRange?.(seg.ownerSummaryId!)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') onToggleRange?.(seg.ownerSummaryId!);
                }}
              >
                <span className={`collapsed-range-arrow${isCollapsed ? '' : ' open'}`}>▶</span>
                <span className="collapsed-range-icon">�</span>
                <span className="collapsed-range-text">
                  会议总结 #{seg.summaryNum}
                  {timeLabel?.length ? `（${timeLabel}）` : ''}
                </span>
                <span className="collapsed-range-count">{seg.messages.length} 条</span>
                <span className="collapsed-range-chevron">
                  {isCollapsed ? '展开' : '折叠'}
                </span>
              </div>
              {isCollapsed ? (
                <div className="collapsed-range-placeholder">
                  已折叠 {seg.messages.length} 条聊天，点击上方展开
                </div>
              ) : (
                <div className="collapsed-range-body">
                  {seg.messages.map((m, j) => renderMessage(m, seg.startIdx + j, summaryIndex))}
                </div>
              )}
            </div>
          );
        });
      })()}
      </div>
    </div>
  );
}