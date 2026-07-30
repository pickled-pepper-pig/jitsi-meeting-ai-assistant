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
  onStopBot?: () => void;
  botStatus?: 'idle' | 'starting' | 'started' | 'stopping';
  audioState?: AudioCaptureState | null;
  micMuted?: boolean;
  remoteCaptureCount?: number;
  // 旁观者侧收到的实时 partial 转写（来自操作者的 ASR）
  remotePartial?: { text: string; participant: string } | null;
  // 真实参会者数量（含自己，来自 Jitsi IFrame API）
  participantsCount?: number;
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
  micMuted = false,
  remoteCaptureCount = 0,
  remotePartial = null,
  participantsCount = 0,
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
        {isModerator ? (
          (() => {
            // 处于"未启动"状态且用户麦克风已静音时，禁用开启按钮 + 显示 tooltip
            const blockedByMute = botStatus === 'idle' && micMuted;
            const tipText = blockedByMute
              ? '请先取消 Jitsi 工具栏的麦克风静音，再开启 AI 语音识别'
              : undefined;
            const isDisabled = botStatus === 'starting' || botStatus === 'stopping' || blockedByMute;
            return (
              <>
                <button
                  className={`bot-btn ${botStatus === 'started' ? 'bot-active' : ''} ${botStatus === 'stopping' ? 'bot-stopping' : ''} ${blockedByMute ? 'bot-blocked' : ''}`}
                  onClick={botStatus === 'started' ? onStopBot : onStartBot}
                  disabled={isDisabled}
                  title={tipText}
                  aria-disabled={isDisabled || undefined}
                >
                  {botStatus === 'idle' && '🎙️ 开启 AI 语音识别'}
                  {botStatus === 'starting' && '⏳ 连接中...'}
                  {botStatus === 'started' && '⏹ 停止录制'}
                  {botStatus === 'stopping' && '⏳ 停止中...'}
                </button>
                {blockedByMute && (
                  <p className="bot-tip bot-tip-warn">麦克风已静音，请先在 Jitsi 工具栏取消静音</p>
                )}
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
                <p className="bot-tip">点击后开始采集音频并发送给 ASR 服务</p>
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
              <div className="audio-status">
                <div className="audio-status-item">
                  <span className="audio-status-label">参会者:</span>
                  <span className="audio-status-value">{participantsCount} 人</span>
                </div>
              </div>
            </div>
          ) : null
        )}
      </div>

      <MessageList messages={messages} />

      {/* 实时转写指示器 - 显示当前正在说的内容 */}
      {(audioState?.partialText || remotePartial) && (
        <div className="partial-transcript">
          <div className="partial-header">
            <span className="partial-dot"></span>
            <span className="partial-speaker">
              {remotePartial ? remotePartial.participant : audioState?.partialParticipant}
            </span>
            <span className="partial-label">正在说...</span>
          </div>
          <div className="partial-text">
            {remotePartial ? remotePartial.text : audioState?.partialText}
          </div>
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
