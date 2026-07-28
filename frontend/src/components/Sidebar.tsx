// 侧边栏组件 - 集成消息列表、总结按钮、合规提示

import { ChatMessage, ConnectionStatus } from '../types';
import { AudioCaptureState } from '../services/audioTypes';
import { MessageList } from './MessageList';
import { SummaryButton } from './SummaryButton';
import { ComplianceNotice } from './ComplianceNotice';

interface SidebarProps {
  messages: ChatMessage[];
  onSummarize: () => void;
  connectionStatus: ConnectionStatus;
  isModerator: boolean;
  aiEnabled: boolean;
  onCopyInvite?: () => void;
  inviteCopied?: boolean;
  onStartBot?: () => void;
  botStatus?: 'idle' | 'starting' | 'started';
  audioState?: AudioCaptureState | null;
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
  botStatus = 'idle',
  audioState,
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
        <h3>会议纪要</h3>
        <div className="header-right">
          <span className={`connection-status ${statusClass[connectionStatus]}`}>
            <span className="status-dot"></span>
            {statusText[connectionStatus]}
          </span>
        </div>
      </div>

      <ComplianceNotice visible={aiEnabled} />

      {onCopyInvite && (
        <div className="invite-section">
          <button className="invite-btn" onClick={onCopyInvite}>
            {inviteCopied ? '✓ 已复制链接' : '📋 复制邀请链接'}
          </button>
        </div>
      )}

      <div className="bot-section">
        <button 
          className={`bot-btn ${botStatus === 'started' ? 'bot-active' : ''}`}
          onClick={onStartBot}
          disabled={botStatus === 'starting' || botStatus === 'started'}
        >
          {botStatus === 'idle' && '🎙️ 开启 AI 语音识别'}
          {botStatus === 'starting' && '⏳ 连接中...'}
          {botStatus === 'started' && '🎤 正在录制中'}
        </button>
        {audioState && audioState.status === 'recording' && (
          <div className="audio-status">
            <div className="audio-status-item">
              <span className="audio-status-label">参会者:</span>
              <span className="audio-status-value">{audioState.participants.length} 人</span>
            </div>
            <div className="audio-status-item">
              <span className="audio-status-label">音频块:</span>
              <span className="audio-status-value">{audioState.audioChunks}</span>
            </div>
            <div className="audio-wave-indicator">
              <div className="audio-bar"></div>
              <div className="audio-bar"></div>
              <div className="audio-bar"></div>
              <div className="audio-bar"></div>
              <div className="audio-bar"></div>
            </div>
          </div>
        )}
        <p className="bot-tip">点击后开始采集音频并发送给 ASR 服务</p>
      </div>

      <MessageList messages={messages} />

      {/* 实时转写指示器 - 显示当前正在说的内容 */}
      {audioState && audioState.partialText && (
        <div className="partial-transcript">
          <div className="partial-header">
            <span className="partial-dot"></span>
            <span className="partial-speaker">{audioState.partialParticipant}</span>
            <span className="partial-label">正在说...</span>
          </div>
          <div className="partial-text">{audioState.partialText}</div>
        </div>
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
