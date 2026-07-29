// 主应用组件

import { useState, useCallback, useRef, useEffect } from 'react';
import { JitsiMeeting } from './components/JitsiMeeting';
import { Sidebar } from './components/Sidebar';
import { useWebSocket } from './hooks/useWebSocket';
import { MessageBuffer } from './utils/messageBuffer';
import { ChatMessage, ServerMessage } from './types';
import { getJitsiDomain, getJitsiProtocol, API_CONFIG } from './config';
import { AudioCaptureService } from './services/audioCapture';
import { AudioCaptureState } from './services/audioTypes';
import './App.css';

const JITSI_DOMAIN = getJitsiDomain();
const JITSI_PROTOCOL = getJitsiProtocol();

export default function App() {
  const getUrlParam = (name: string) => {
    if (typeof window === 'undefined') return '';
    const params = new URLSearchParams(window.location.search);
    return params.get(name) || '';
  };

  const [roomName, setRoomName] = useState(getUrlParam('room'));
  const [displayName, setDisplayName] = useState(getUrlParam('name'));
  const [isModerator, setIsModerator] = useState(true);
  const [joined, setJoined] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showProxyWarning, setShowProxyWarning] = useState(false);
  const [showModeratorOccupied, setShowModeratorOccupied] = useState(false);
  const [moderatorOccupiedMessage, setModeratorOccupiedMessage] = useState('');
  const [botStatus, setBotStatus] = useState<'idle' | 'starting' | 'started' | 'stopping'>('idle');
  const [audioState, setAudioState] = useState<AudioCaptureState | null>(null);

  const tokenRef = useRef<string>('');
  const userIdRef = useRef<string>('');
  const audioServiceRef = useRef<AudioCaptureService | null>(null);
  // 标记"当前用户是否就是开启 AI 的人"——区分自己开 vs 别人开后只能查看
  const isBotOperatorRef = useRef<boolean>(false);

  const messageBufferRef = useRef(new MessageBuffer());
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  useEffect(() => {
    if (joined && roomName) {
      const url = new URL(window.location.href);
      url.searchParams.set('room', roomName);
      window.history.replaceState({}, '', url.toString());
    }
  }, [joined, roomName]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const hostname = window.location.hostname;
    if (hostname === 'localhost' || hostname === '127.0.0.1') return;

    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), 3000);

    fetch('/health', { signal: abortController.signal })
      .then((res) => {
        if (!res.ok) throw new Error('Health check failed');
      })
      .catch(() => {
        setShowProxyWarning(true);
      })
      .finally(() => {
        clearTimeout(timeoutId);
      });
  }, []);

  const copyInviteLink = useCallback(() => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    url.searchParams.set('room', roomName);
    url.searchParams.delete('name');
    navigator.clipboard.writeText(url.toString()).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [roomName]);

  const refreshMessages = useCallback(() => {
    setMessages(messageBufferRef.current.getAll());
  }, []);

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
        break;
      case 'ai_bot_status':
        // 房间级 AI Bot 状态（自己或别人开启都会收到）
        console.log('[App] AI Bot 状态:', message);
        if (message.status === 'started' && message.startedBy === userIdRef.current) {
          // 自己开启的（已通过本地 handleStartBot 切到 started，不重复处理）
          isBotOperatorRef.current = true;
        } else if (message.status === 'started') {
          // 别人开启的 → 旁观者视角
          isBotOperatorRef.current = false;
          setBotStatus('started');
        } else if (message.status === 'idle') {
          // 任何人关闭都会收到
          isBotOperatorRef.current = false;
          setBotStatus('idle');
        }
        break;
      case 'meeting_transcript':
        // 旁观者收到主持人的 final 转写 → 推入消息列表
        {
          const t = message as unknown as {
            text: string;
            participant_id?: string;
            participant_name?: string;
            timestamp?: number;
          };
          if (t.text) {
            const speakerName = t.participant_name || 'AI 转写';
            const ts = t.timestamp || Date.now();
            setMessages(prev => {
              // 去重：同 speaker + 同内容 + 1s 内的视为同一条
              const last = prev[prev.length - 1];
              if (last && last.sender === speakerName && last.content === t.text && Math.abs(last.timestamp - ts) < 1000) {
                return prev;
              }
              return [...prev, {
                id: `remote-transcript-${ts}-${Math.random()}`,
                seq: Date.now(),
                roomId: roomName,
                sender: speakerName,
                content: t.text,
                timestamp: ts,
                type: 'text' as const,
              }];
            });
          }
        }
        break;
      case 'error':
        console.warn('[App] 服务端提示:', message.message);
        break;
    }
  }, [refreshMessages, roomName]);

  const { connect, send, status } = useWebSocket({
    url: API_CONFIG.wsUrl,
    onMessage: handleWsMessage,
  });

  const fetchJoinToken = async (roomId: string, userId: string, userName: string, asModerator: boolean) => {
    const res = await fetch(`${API_CONFIG.baseUrl}/api/join`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roomId, userId, userName, asModerator }),
    });
    if (res.status === 409) {
      const data = await res.json().catch(() => ({}));
      const err: Error & { code?: string; currentModeratorId?: string } = new Error(
        data.message || '此房间已有人以主持人身份加入',
      );
      err.code = 'moderator_occupied';
      err.currentModeratorId = data.currentModeratorId;
      throw err;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json() as Promise<{ token: string; role: 'moderator' | 'participant' }>;
  };

  const handleJoin = async () => {
    if (!roomName.trim() || !displayName.trim()) {
      alert('请填写房间名和用户名');
      return;
    }

    const userId = `user-${Date.now()}`;
    userIdRef.current = userId;

    try {
      const result = await fetchJoinToken(roomName.trim(), userId, displayName.trim(), isModerator);
      tokenRef.current = result.token;
      // 真实角色由后端决定（避免前端伪造）
      setIsModerator(result.role === 'moderator');
      setAiEnabled(true);
      setJoined(true);
      connect(roomName.trim(), result.token);
    } catch (err: any) {
      if (err?.code === 'moderator_occupied') {
        // 显示提示窗，不进入会议界面
        setModeratorOccupiedMessage(err.message || '此房间已有人以主持人身份加入');
        setShowModeratorOccupied(true);
        return;
      }
      setShowProxyWarning(true);
    }
  };

  const handleIncomingMessage = useCallback((sender: string, message: string, _timestamp: string) => {
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

  const handleSummarize = useCallback(() => {
    send({
      action: 'summarize',
      roomId: roomName,
      token: tokenRef.current,
    });
  }, [send, roomName]);

  const handleLeave = async () => {
    if (audioServiceRef.current) {
      await audioServiceRef.current.stop();
      audioServiceRef.current = null;
    }
    send({ action: 'leave', roomId: roomName });
    setJoined(false);
    setAiEnabled(false);
    setBotStatus('idle');
    setAudioState(null);
    messageBufferRef.current.clear();
    setMessages([]);
  };

  const handleStartBot = async () => {
    if (botStatus !== 'idle') return;
    if (!isModerator) {
      alert('只有主持人可以开启 AI 语音识别');
      return;
    }
    setBotStatus('starting');

    try {
      // 直接连接后端 WebSocket 服务（不走 Vite 代理）
      const wsUrl = API_CONFIG.wsUrl;

      const audioService = new AudioCaptureService({
        roomId: roomName,
        participantId: userIdRef.current,
        participantName: displayName,
        wsUrl,
        token: tokenRef.current,
      });

      audioServiceRef.current = audioService;
      audioService.subscribe((state) => {
        setAudioState(state);
        // 主持人本人收到的 final → 直接进消息列表（不通过 Socket.IO 中转）
        if (state.transcripts.length > 0) {
          const latestTranscript = state.transcripts[state.transcripts.length - 1];
          if (latestTranscript.text && latestTranscript.type === 'final') {
            const speakerName = latestTranscript.participantName || 'AI 转写';
            setMessages(prev => {
              const lastMsg = prev[prev.length - 1];
              if (lastMsg && lastMsg.sender === speakerName && lastMsg.content === latestTranscript.text) {
                return prev;
              }
              return [...prev, {
                id: `transcript-${latestTranscript.timestamp}`,
                seq: Date.now(),
                roomId: roomName,
                sender: speakerName,
                content: latestTranscript.text,
                timestamp: latestTranscript.timestamp,
                type: 'text' as const,
              }];
            });
          }
        }
      });
      await audioService.start();
      isBotOperatorRef.current = true;
      setBotStatus('started');
      console.log('[App] AI Bot 已启动，音频采集中...');
    } catch (err) {
      console.error('[App] AI Bot 启动失败:', err);
      isBotOperatorRef.current = false;
      setBotStatus('idle');
    }
  };

  const handleStopBot = async () => {
    if (botStatus !== 'started') return;
    if (!isBotOperatorRef.current) return;  // 旁观者没权利停
    setBotStatus('stopping');
    try {
      await audioServiceRef.current?.stop();
      audioServiceRef.current = null;
      setAudioState(null);
      isBotOperatorRef.current = false;
      setBotStatus('idle');
      console.log('[App] AI Bot 已停止');
    } catch (err) {
      console.error('[App] AI Bot 停止失败:', err);
      isBotOperatorRef.current = false;
      setBotStatus('idle');
    }
  };

  if (!joined) {
    return (
      <div className="join-page">
        {showProxyWarning && (
          <div className="proxy-warning-overlay">
            <div className="proxy-warning-modal">
              <div className="proxy-warning-icon">⚠️</div>
              <h3>检测到代理/VPN</h3>
              <p>当前网络环境可能使用了代理或VPN，这会导致无法正常访问会议服务。</p>
              <div className="proxy-warning-steps">
                <h4>请按以下步骤操作：</h4>
                <ol>
                  <li>打开「系统设置」→「网络」→「Wi-Fi」→「详细信息」</li>
                  <li>点击「代理」标签页</li>
                  <li>取消勾选「Web 代理 (HTTP)」和「安全 Web 代理 (HTTPS)」</li>
                  <li>或在「绕过代理服务器的主机与域名」中添加当前 IP 地址</li>
                </ol>
              </div>
              <button className="proxy-warning-btn" onClick={() => setShowProxyWarning(false)}>
                我已关闭代理
              </button>
            </div>
          </div>
        )}
        {showModeratorOccupied && (
          <div className="proxy-warning-overlay">
            <div className="proxy-warning-modal">
              <div className="proxy-warning-icon">🔒</div>
              <h3>无法以主持人身份加入</h3>
              <p>{moderatorOccupiedMessage}</p>
              <p style={{ fontSize: 13, color: '#6b7280', marginTop: 8 }}>
                取消勾选「以主持人身份加入」可作为参会者加入
              </p>
              <button
                className="proxy-warning-btn"
                onClick={() => {
                  setShowModeratorOccupied(false);
                  setIsModerator(false);
                }}
              >
                知道了
              </button>
            </div>
          </div>
        )}
        <div className="join-card">
          <h1>Jitsi 会议 AI 助手</h1>
          <p className="subtitle">实时语音转写 + 会议纪要</p>

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
              <li>填好房间名与昵称即可加入会议</li>
              <li>点「开启 AI 语音识别」开始实时转写为文字</li>
              <li>主持人可点「总结会议」一键生成纪要</li>
              <li>网络中断会自动重连，不丢失已记录内容</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

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
        onStartBot={handleStartBot}
        onStopBot={handleStopBot}
        botStatus={botStatus}
        audioState={audioState}
      />
      <button className="leave-btn" onClick={handleLeave}>
        离开会议
      </button>
    </div>
  );
}
