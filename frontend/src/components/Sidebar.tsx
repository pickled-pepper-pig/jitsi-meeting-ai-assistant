// 侧边栏组件 - 集成消息列表、总结按钮、合规提示

import { ChatMessage, ConnectionStatus } from '../types';
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
}

export function Sidebar({
  messages,
  onSummarize,
  connectionStatus,
  isModerator,
  aiEnabled,
  onCopyInvite,
  inviteCopied,
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

      <MessageList messages={messages} />

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
