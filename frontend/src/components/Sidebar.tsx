// 侧边栏组件 - 集成消息列表、总结按钮、合规提示

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
  onCopyInvite?: () => void;
  inviteCopied?: boolean;
  onStartBot?: () => void;
  onStopBot?: () => void;
  botStatus?: 'idle' | 'starting' | 'started' | 'stopping';
  audioState?: AudioCaptureState | null;
  remoteCaptureCount?: number;
  // 多 speaker 实时 partial：按 participant_id 聚合，支持用户点击头像聚焦某个 speaker
  remotePartials?: Record<string, { text: string; name: string; id: string; ts: number }>;
  // 用户选中聚焦查看的 participant_id；null 表示自动跟随最新说话的人
  focusedSpeakerId?: string | null;
  onFocusSpeaker?: (id: string | null) => void;
  // 真实参会者数量（含自己，来自 Jitsi IFrame API）
  participantsCount?: number;
  // 主持人名字标注函数（在自己作为主持人的本地视角下，给自己消息加 "（主持人）" 后缀）
  tagModerator?: (name: string) => string;
}

export function Sidebar({
  messages,
  onSummarize,
  connectionStatus,
  isModerator,
  aiEnabled,
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
  tagModerator = (s) => s,
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

  return (
    <div className="sidebar">
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
                <p className="bot-tip">
                  {botStatus === 'idle'
                    ? '点击后开始 AI 实时转写'
                    : '正在转写中，点击按钮可随时停止'}
                </p>
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

      <MessageList messages={messages} />

      {/* 实时转写指示器 - 多 speaker 头像列表 + 选中聚焦查看 */}
      {Object.keys(remotePartials).length > 0 && (
        (() => {
          // 头像列表按"首次说话"顺序展示（Object.values 保持插入序，不重排），
          // 避免 partial 更新时头像跳来跳去。
          const speakers = Object.values(remotePartials);
          // 聚焦展示谁：用户选中 > 自动跟随最新（按最新 ts 选）
          const latest = speakers.reduce((a, b) => (a.ts >= b.ts ? a : b), speakers[0]);
          const focusedId = focusedSpeakerId && remotePartials[focusedSpeakerId]
            ? focusedSpeakerId
            : latest?.id;
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
                    <span className="partial-label">正在说...</span>
                  </div>
                  <div className="partial-text">
                    {focused.text}
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
            disabled={!aiEnabled}
            status={connectionStatus}
            isModerator={isModerator}
          />
        </div>
      )}
    </div>
  );
}
