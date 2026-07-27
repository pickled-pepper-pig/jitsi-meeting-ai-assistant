// 主应用组件

import { useState, useCallback, useRef, useEffect } from 'react';
import { JitsiMeeting } from './components/JitsiMeeting';
import { Sidebar } from './components/Sidebar';
import { useWebSocket } from './hooks/useWebSocket';
import { MessageBuffer } from './utils/messageBuffer';
import { ChatMessage, ServerMessage } from './types';
import { getJitsiDomain, getJitsiProtocol, API_CONFIG } from './config';
import './App.css';

const JITSI_DOMAIN = getJitsiDomain();
const JITSI_PROTOCOL = getJitsiProtocol();

export default function App() {
  // 从 URL 参数获取默认值
  const getUrlParam = (name: string) => {
    if (typeof window === 'undefined') return '';
    const params = new URLSearchParams(window.location.search);
    return params.get(name) || '';
  };

  // 配置状态
  const [roomName, setRoomName] = useState(getUrlParam('room'));
  const [displayName, setDisplayName] = useState(getUrlParam('name'));
  const [isModerator, setIsModerator] = useState(true);
  const [joined, setJoined] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(false);
  const [copied, setCopied] = useState(false);

  // Token 和用户信息
  const tokenRef = useRef<string>('');
  const userIdRef = useRef<string>('');

  // 消息缓冲
  const messageBufferRef = useRef(new MessageBuffer());
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  // 加入会议后更新 URL
  useEffect(() => {
    if (joined && roomName) {
      const url = new URL(window.location.href);
      url.searchParams.set('room', roomName);
      window.history.replaceState({}, '', url.toString());
    }
  }, [joined, roomName]);

  // 复制邀请链接
  const copyInviteLink = useCallback(() => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    url.searchParams.set('room', roomName);
    url.searchParams.delete('name');
    const inviteUrl = url.toString();
    navigator.clipboard.writeText(inviteUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [roomName]);

  // 刷新消息列表
  const refreshMessages = useCallback(() => {
    setMessages(messageBufferRef.current.getAll());
  }, []);

  // WebSocket 消息处理
  const handleWsMessage = useCallback((message: ServerMessage) => {
    switch (message.type) {
      case 'joined':
        console.log('[App] 已加入会议房间');
        break;
      case 'chat':
        if (messageBufferRef.current.add(message.payload)) {
          refreshMessages();
        }
        break;
      case 'synced':
        messageBufferRef.current.addBatch(message.messages);
        refreshMessages();
        console.log(`[App] 同步完成，补齐 ${message.messages.length} 条消息`);
        break;
      case 'summary':
        // 总结已通过 chat 类型消息广播
        break;
      case 'error':
        console.warn('[App] 服务端错误:', message.message);
        // 简单提示
        alert(message.message);
        break;
    }
  }, [refreshMessages]);

  // WebSocket 连接
  const { connect, send, status } = useWebSocket({
    url: API_CONFIG.wsUrl,
    onMessage: handleWsMessage,
  });

  // 获取开发 Token
  const fetchDevToken = async (roomId: string, userId: string, moderator: boolean) => {
    const res = await fetch(`${API_CONFIG.baseUrl}/api/dev/tokens`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roomId, userId }),
    });
    const tokens = await res.json();
    return moderator ? tokens.moderator : tokens.participant;
  };

  // 加入会议
  const handleJoin = async () => {
    if (!roomName.trim() || !displayName.trim()) {
      alert('请填写房间名和用户名');
      return;
    }

    const userId = `user-${Date.now()}`;
    userIdRef.current = userId;

    // Phase 1: 从后端获取 Mock Token
    const token = await fetchDevToken(roomName.trim(), userId, isModerator);
    tokenRef.current = token;

    setAiEnabled(true);
    setJoined(true);

    // 建立 WebSocket 连接
    connect(roomName.trim(), token);
  };

  // Jitsi 聊天消息回调
  const handleIncomingMessage = useCallback((sender: string, message: string, _timestamp: string) => {
    // 将 Jitsi 聊天消息发送到后端广播
    send({
      action: 'chat',
      roomId: roomName,
      token: tokenRef.current,
      content: message,
      sender,
    });
  }, [send, roomName]);

  const handleOutgoingMessage = useCallback((message: string) => {
    send({
      action: 'chat',
      roomId: roomName,
      token: tokenRef.current,
      content: message,
      sender: displayName,
    });
  }, [send, roomName, displayName]);

  // 会议结束自动总结
  const handleVideoConferenceLeft = useCallback(() => {
    console.log('[App] 会议结束，自动触发总结');
    if (isModerator && tokenRef.current) {
      send({
        action: 'summarize',
        roomId: roomName,
        token: tokenRef.current,
      });
    }
    setJoined(false);
  }, [send, roomName, isModerator]);

  // 手动总结
  const handleSummarize = useCallback(() => {
    send({
      action: 'summarize',
      roomId: roomName,
      token: tokenRef.current,
    });
  }, [send, roomName]);

  // 离开会议
  const handleLeave = () => {
    send({ action: 'leave', roomId: roomName });
    setJoined(false);
    setAiEnabled(false);
    messageBufferRef.current.clear();
    setMessages([]);
  };

  // 入口界面
  if (!joined) {
    return (
      <div className="join-page">
        <div className="join-card">
          <h1>会议 AI 助手</h1>
          <p className="subtitle">Phase 1 - 实时聊天展示 + 会议总结</p>

          <div className="form-group">
            <label>房间名</label>
            <input
              type="text"
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
              placeholder="输入房间名（如：team-meeting-001）"
            />
          </div>

          <div className="form-group">
            <label>用户名</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="输入你的名字"
            />
          </div>

          <div className="form-group">
            <label>
              <input
                type="checkbox"
                checked={isModerator}
                onChange={(e) => setIsModerator(e.target.checked)}
              />
              以主持人身份加入（可生成总结）
            </label>
          </div>

          <button className="join-btn" onClick={handleJoin}>
            加入会议
          </button>

          <div className="tips">
            <p>使用说明：</p>
            <ul>
              <li>使用公共 Jitsi 服务（meet.jit.si）</li>
              <li>主持人可点击「总结会议」生成纪要</li>
              <li>会议结束后自动触发总结</li>
              <li>WebSocket 断线自动重连 + 消息补齐</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

  // 会议界面
  return (
    <div className="app-container">
      <div className="meeting-area">
        <JitsiMeeting
          domain={JITSI_DOMAIN}
          protocol={JITSI_PROTOCOL}
          roomName={roomName}
          displayName={displayName}
          token={tokenRef.current}
          onIncomingMessage={handleIncomingMessage}
          onOutgoingMessage={handleOutgoingMessage}
          onVideoConferenceLeft={handleVideoConferenceLeft}
        />
      </div>
      <Sidebar
        messages={messages}
        onSummarize={handleSummarize}
        connectionStatus={status}
        isModerator={isModerator}
        aiEnabled={aiEnabled}
        onCopyInvite={copyInviteLink}
        inviteCopied={copied}
      />
      <button className="leave-btn" onClick={handleLeave}>
        离开会议
      </button>
    </div>
  );
}
