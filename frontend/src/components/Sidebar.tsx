// 侧边栏组件 - 集成消息列表、总结按钮、合规提示

import { useState, useEffect, type CSSProperties } from 'react';
import { ChatMessage, ConnectionStatus } from '../types';
import { AudioCaptureState } from '../services/audioTypes';
import { MessageList } from './MessageList';
import { SummaryButton } from './SummaryButton';
import { ComplianceNotice } from './ComplianceNotice';

// 根据 speaker 名字生成稳定的颜色（与 MessageList 保持一致的调色板）
// 莫兰迪色系：低饱和、带灰调；稍加深保证在浅色背景上可读
const SPEAKER_COLORS = [
  '#5B7A8C', '#6B8E7A', '#A8896E', '#7D6E8C', '#A8706E', '#5E8B8E',
];

function getSpeakerColor(speaker: string): string {
  let hash = 0;
  for (let i = 0; i < speaker.length; i++) {
    hash = (hash * 31 + speaker.charCodeAt(i)) >>> 0;
  }
  return SPEAKER_COLORS[hash % SPEAKER_COLORS.length];
}

interface SidebarProps {
  messages: ChatMessage[];
  onSummarize: () => void;
  connectionStatus: ConnectionStatus;
  isModerator: boolean;
  aiEnabled: boolean;
  summaryLoading: boolean;
  onCopyInvite?: () => void;
  inviteCopied?: boolean;
  onStartBot?: () => void;
  onStopBot?: () => void;
  botStatus?: 'idle' | 'starting' | 'started' | 'stopping';
  audioState?: AudioCaptureState | null;
  remoteCaptureCount?: number;
  // 多 speaker 实时 partial：按 participant_id 聚合，支持用户点击头像聚焦某个 speaker
  remotePartials?: Record<string, { text: string; name: string; id: string; ts: number; isProcessing?: boolean }>;
  // 用户选中聚焦查看的 participant_id；null 表示自动跟随最新说话的人
  focusedSpeakerId?: string | null;
  onFocusSpeaker?: (id: string | null) => void;
  // 真实参会者数量（含自己，来自 Jitsi IFrame API）
  participantsCount?: number;
  // 离开会议回调
  onLeave?: () => void;
  // 动态宽度（由外部分割线控制）
  style?: CSSProperties;
}

export function Sidebar({
  messages,
  onSummarize,
  connectionStatus,
  isModerator,
  aiEnabled,
  summaryLoading,
  onCopyInvite,
  inviteCopied,
  onStartBot,
  onStopBot,
  botStatus = 'idle',
  audioState,
  remoteCaptureCount = 0,
  remotePartials = {},
  focusedSpeakerId = null,
  onFocusSpeaker,
  participantsCount = 0,
  onLeave,
  style,
}: SidebarProps) {
  const statusText: Record<ConnectionStatus, string> = {
    connected: '已连接',
    connecting: '连接中...',
    reconnecting: '重连中...',
    disconnected: '已断开',
  };

  const statusClass: Record<ConnectionStatus, string> = {
    connected: 'status-connected',
    connecting: 'status-connecting',
    reconnecting: 'status-reconnecting',
    disconnected: 'status-disconnected',
  };

  // Tab 切换：聊天记录 / 会议总结
  const [activeTab, setActiveTab] = useState<'chat' | 'summary'>('chat');
  // 聊天记录 Tab：显示所有消息（chat + summary），summary 卡片作为"分隔点"，
  // 它前面到上一条 summary 之间的聊天会被折叠。
  // 会议总结 Tab：只显示 summary 卡片（不带折叠聊天段）。
  const summaryMessages = messages.filter((m) => m.type === 'summary');

  // 折叠的聊天区间：key 是 summaryId，value 表示该 summary 到上一条 summary 之间的消息是否折叠
  // 新生成的总结默认折叠，让用户聚焦于最新总结
  const [collapsedRanges, setCollapsedRanges] = useState<Set<string>>(new Set());
  const toggleRange = (summaryId: string) => {
    setCollapsedRanges((prev) => {
      const next = new Set(prev);
      if (next.has(summaryId)) next.delete(summaryId);
      else next.add(summaryId);
      return next;
    });
  };

  // 监听新增 summary：新总结产生时，把对应区间默认加入折叠集合，
  // 并自动切到会议总结 Tab
  useEffect(() => {
    if (summaryMessages.length === 0) return;
    const latestSummary = summaryMessages[summaryMessages.length - 1];
    setCollapsedRanges((prev) => {
      if (prev.has(latestSummary.id)) return prev;
      const next = new Set(prev);
      next.add(latestSummary.id);
      return next;
    });
    // 仅在总结 Tab 不可见时切换，避免用户主动浏览时被强制跳转
    setActiveTab('summary');
  }, [summaryMessages.length]);

  // 总结导航数据（从所有 summary 中提取，独立于当前 Tab，
  // 让聊天记录 Tab 也能显示左侧目录跳转到对应总结）
  const SUMMARY_NAV_THEMES = [
    { bar: '#a855f7', bg: '#faf5ff', title: '#7c3aed', icon: '📋' },
    { bar: '#0ea5e9', bg: '#f0f9ff', title: '#0284c7', icon: '📝' },
    { bar: '#22c55e', bg: '#f0fdf4', title: '#16a34a', icon: '✅' },
    { bar: '#f59e0b', bg: '#fffbeb', title: '#d97706', icon: '📌' },
    { bar: '#ec4899', bg: '#fdf2f8', title: '#db2777', icon: '🎯' },
  ];
  const summaryNavItems = summaryMessages.map((msg, i) => ({
    id: msg.id,
    num: i + 1,
    theme: SUMMARY_NAV_THEMES[i % SUMMARY_NAV_THEMES.length],
  }));

  // 切换 Tab 时滚动到底部（让最新内容可见）
  const switchTab = (tab: 'chat' | 'summary') => {
    setActiveTab(tab);
    requestAnimationFrame(() => {
      const list = document.querySelector('.message-list');
      if (list) list.scrollTop = list.scrollHeight;
    });
  };

  return (
    <div className="sidebar" style={style}>
      <div className="sidebar-header">
        <div className="sidebar-title">
          <h3>会议纪要</h3>
          {onCopyInvite && (
            <button
              className="invite-icon-btn"
              onClick={onCopyInvite}
              title={inviteCopied ? '邀请链接已复制' : '复制邀请链接'}
              aria-label="复制邀请链接"
            >
              {inviteCopied ? '✓' : '📋'}
            </button>
          )}
        </div>
        <div className="header-right">
          <span className={`connection-status ${statusClass[connectionStatus]}`}>
            <span className="status-dot"></span>
            {statusText[connectionStatus]}
          </span>
          {onLeave && (
            <button
              className="leave-icon-btn"
              onClick={onLeave}
              title="离开会议"
              aria-label="离开会议"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <ComplianceNotice visible={aiEnabled} />

      <div className="bot-section">
        {isModerator ? (
          (() => {
            // AI 按钮只受主持人权限 + 当前状态控制，不再受麦克风静音影响
            // 麦克风静音只是"本端是否上传音频"的开关，不影响 AI 功能开关
            const isDisabled = botStatus === 'starting' || botStatus === 'stopping';
            return (
              <>
                <button
                  className={`bot-btn ${botStatus === 'started' ? 'bot-active' : ''} ${botStatus === 'stopping' ? 'bot-stopping' : ''}`}
                  onClick={botStatus === 'started' ? onStopBot : onStartBot}
                  disabled={isDisabled}
                >
                  {botStatus === 'idle' && '🎙️ 开启 AI 语音识别'}
                  {botStatus === 'starting' && '⏳ 连接中...'}
                  {botStatus === 'started' && '⏹ 停止录制'}
                  {botStatus === 'stopping' && '⏳ 停止中...'}
                </button>
                {audioState && audioState.status === 'recording' && (
                  <div className="audio-status">
                    <div className="audio-status-item">
                      <span className="audio-status-label">参会者:</span>
                      <span className="audio-status-value">{participantsCount} 人</span>
                    </div>
                    <div className="audio-status-item">
                      <span className="audio-status-label">音频块:</span>
                      <span className="audio-status-value">{audioState.audioChunks}</span>
                    </div>
                    {remoteCaptureCount > 0 && (
                      <div className="audio-status-item">
                        <span className="audio-status-label">远程:</span>
                        <span className="audio-status-value">{remoteCaptureCount} 路</span>
                      </div>
                    )}
                    <div className="audio-wave-indicator">
                      <div className="audio-bar"></div>
                      <div className="audio-bar"></div>
                      <div className="audio-bar"></div>
                      <div className="audio-bar"></div>
                      <div className="audio-bar"></div>
                    </div>
                  </div>
                )}
              </>
            );
          })()
        ) : (
          // 旁观者视角（没开 AI；或别人开 AI 时）：
          // 1) botStatus === 'started'：显示 AI 转写进行中 + 参会者人数
          // 2) botStatus === 'idle' 且纯旁观：什么都不显示，避免和操作者侧 UI 混淆
          botStatus === 'started' ? (
            <div className="bot-view-only">
              <div className="bot-view-only-indicator">
                <span className="recording-dot"></span>
                <span>AI 正在转写中</span>
              </div>
              <p className="bot-tip">由会议主持人开启，转写内容会实时显示在下方面板</p>
              <p className="bot-tip"><strong>参会者:</strong> <span className="participants-count-value">{participantsCount}</span> 人</p>
            </div>
          ) : null
        )}
      </div>

      <div className="sidebar-tabs">
        <button
          className={`sidebar-tab ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => switchTab('chat')}
        >
          聊天记录
          {messages.some((m) => m.type !== 'summary') && (
            <span className="tab-badge">{messages.filter((m) => m.type !== 'summary').length}</span>
          )}
        </button>
        <button
          className={`sidebar-tab ${activeTab === 'summary' ? 'active' : ''}`}
          onClick={() => switchTab('summary')}
        >
          会议总结
          {summaryMessages.length > 0 && (
            <span className="tab-badge">{summaryMessages.length}</span>
          )}
        </button>
      </div>

      <MessageList
        messages={activeTab === 'chat' ? messages : summaryMessages}
        showSummaryNav={false}
        summaryNavItems={summaryNavItems}
        collapsedRanges={collapsedRanges}
        onToggleRange={toggleRange}
        renderSummaryCards={activeTab === 'summary'}
      />

      {/* 实时转写指示器 - 多 speaker 头像列表 + 选中聚焦查看 */}
      {Object.keys(remotePartials).length > 0 && (
        (() => {
          // 头像列表按"首次说话"顺序展示（Object.values 保持插入序，不重排），
          // 避免 partial 更新时头像跳来跳去。
          const speakers = Object.values(remotePartials);
          // 聚焦展示谁：用户选中 > 第一个说话的 speaker（保持不变，新说话人只加头像）
          const firstSpeaker = speakers[0]; // 首次说话顺序保持不变
          const focusedId = focusedSpeakerId && remotePartials[focusedSpeakerId]
            ? focusedSpeakerId
            : firstSpeaker?.id;
          const focused = focusedId ? remotePartials[focusedId] : null;
          return (
            <div className="partial-transcript">
              {/* speaker 头像列表 */}
              <div className="partial-speakers">
                {speakers.map((s) => {
                  const color = getSpeakerColor(s.name);
                  const isActive = s.id === focusedId;
                  const initial = (s.name || '?').charAt(0).toUpperCase();
                  return (
                    <button
                      key={s.id}
                      className={`speaker-chip ${isActive ? 'speaker-chip-active' : ''}`}
                      onClick={() => onFocusSpeaker?.(isActive ? null : s.id)}
                      title={isActive ? `取消聚焦（${s.name}）` : `聚焦 ${s.name}`}
                    >
                      <span
                        className="speaker-avatar"
                        style={{ backgroundColor: color }}
                      >
                        {initial}
                      </span>
                      <span className="speaker-name" style={{ color }}>{s.name}</span>
                    </button>
                  );
                })}
              </div>
              {/* 聚焦 speaker 的实时文本 */}
              {focused && (
                <>
                  <div className="partial-header">
                    <span className="partial-dot"></span>
                    <span className="partial-speaker" style={{ color: getSpeakerColor(focused.name) }}>
                      {focused.name}
                    </span>
                    <span className="partial-label">
                      {focused.isProcessing ? '正在说话...' : '正在说...'}
                    </span>
                  </div>
                  <div className="partial-text">
                    {focused.isProcessing
                      ? <span className="partial-processing-dots"><span></span><span></span><span></span></span>
                      : focused.text}
                  </div>
                </>
              )}
            </div>
          );
        })()
      )}

      {isModerator && (
        <div className="sidebar-footer">
          <SummaryButton
            onSummarize={onSummarize}
            disabled={!aiEnabled || messages.length === 0}
            status={connectionStatus}
            isModerator={isModerator}
            loading={summaryLoading}
          />
        </div>
      )}
    </div>
  );
}
