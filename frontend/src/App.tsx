// 主应用组件

import { useState, useCallback, useRef, useEffect } from 'react';
import { JitsiMeeting } from './components/JitsiMeeting';
import { Sidebar } from './components/Sidebar';
import { useWebSocket } from './hooks/useWebSocket';
import { MessageBuffer } from './utils/messageBuffer';
import { ChatMessage, ServerMessage } from './types';
import { getJitsiDomain, getJitsiProtocol, API_CONFIG } from './config';
import { AudioCaptureService } from './services/audioCapture';
import { ParticipantAudioReceiver, ParticipantTrackInfo } from './services/participantAudioReceiver';
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
  const [showModeratorOccupied, setShowModeratorOccupied] = useState(false);
  const [moderatorOccupiedMessage, setModeratorOccupiedMessage] = useState('');
  const [botStatus, setBotStatus] = useState<'idle' | 'starting' | 'started' | 'stopping'>('idle');
  const [audioState, setAudioState] = useState<AudioCaptureState | null>(null);
  const [micMuted, setMicMuted] = useState(false);  // 来自 Jitsi 工具栏的麦克风静音状态
  // 旁观者侧收到的实时 partial 转写（来自操作者的 ASR 流）
  const [remotePartial, setRemotePartial] = useState<{ text: string; participant: string } | null>(null);
  // 真实参会者数量（含自己，来自 Jitsi IFrame API 的 participantJoined/Left 事件）
  const [participantsCount, setParticipantsCount] = useState(1);

  const tokenRef = useRef<string>('');
  const userIdRef = useRef<string>('');
  const audioServiceRef = useRef<AudioCaptureService | null>(null);
  // 标记"当前用户是否就是开启 AI 的人"——区分自己开 vs 别人开后只能查看
  const isBotOperatorRef = useRef<boolean>(false);
  // 多路远程音频采集器：每个参会者一个 session + 一个 ws
  const participantAudioReceiverRef = useRef<ParticipantAudioReceiver | null>(null);
  // 缓存已知的参会者 audio track（包括 bot 未启动时）—— bot 启动时遍历并接入
  const pendingRemoteAudioRef = useRef<Map<string, { participantName: string; track: MediaStreamTrack }>>(
    new Map(),
  );
  // 当前活跃的远程采集数（用于 Sidebar 显示）
  const [remoteCaptureCount, setRemoteCaptureCount] = useState(0);

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
        // Silently ignore health check failures
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
            // 收到 final：清掉之前的 partial
            setRemotePartial(null);
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
      case 'meeting_transcript_partial':
        // 旁观者收到操作者正在说的 partial 文本（实时显示用，不入 messages 列表）
        {
          const t = message as unknown as {
            text: string;
            participant_id?: string;
            participant_name?: string;
            timestamp?: number;
          };
          if (t.text) {
            setRemotePartial({
              text: t.text,
              participant: t.participant_name || 'AI 转写',
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

    // 稳定 userId 解析顺序：
    //   1) localStorage 同名同房间 → 直接复用（同一浏览器刷新场景）
    //   2) 后端记录的当前房间主持人昵称 == 当前昵称 → 复用后端存的 userId
    //      （解决「旧的 wei 进来时 localStorage 还没建过、但后端 firstModeratorName 是 wei」这种历史数据场景）
    //   3) 都没有 → 临时生成一个新 ID 并写入 localStorage
    const trimmedRoom = roomName.trim();
    const trimmedName = displayName.trim();
    const storageKey = `meeting:userId:${trimmedRoom}:${trimmedName}`;
    let userId = '';
    try {
      userId = localStorage.getItem(storageKey) || '';
    } catch {
      // localStorage 不可用时回退到下面的查询
    }
    if (!userId) {
      try {
        const r = await fetch(
          `${API_CONFIG.baseUrl}/api/meetings/${encodeURIComponent(trimmedRoom)}/moderator`,
        );
        if (r.ok) {
          const data = await r.json();
          if (data?.hasModerator && data.moderatorName === trimmedName && data.moderatorId) {
            userId = data.moderatorId;
          }
        }
      } catch {
        // 查询失败不阻塞，按临时 ID 继续
      }
    }
    if (!userId) {
      userId = `user-${Date.now()}`;
    }
    try {
      localStorage.setItem(storageKey, userId);
    } catch {
      // 写入失败也无影响
    }
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
      alert('无法连接到后端服务，请检查网络');
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

  /**
   * Jitsi 轨道事件回调：
   * - 缓存所有 audio track（含 local 和 remote）
   * - 如果 bot 启动了 + 收到的是 remote audio track → 自动启动远程采集
   */
  const handleTrackAdded = (info: { participantId: string; participantName: string; track: MediaStreamTrack; kind: 'audio' | 'video'; local: boolean }) => {
    if (info.kind !== 'audio') return;
    if (!info.participantId) return;
    // 用 participantId 作为缓存 key
    pendingRemoteAudioRef.current.set(info.participantId, {
      participantName: info.participantName,
      track: info.track,
    });
    // bot 已启动 + 是 remote audio → 立即接入
    if (info.local === false && botStatus === 'started' && participantAudioReceiverRef.current) {
      void attachRemoteTrack(info.participantId, info.participantName, info.track);
    }
  };

  const handleTrackRemoved = (info: { participantId: string; track: MediaStreamTrack; kind: 'audio' | 'video'; local: boolean }) => {
    if (info.kind !== 'audio') return;
    if (!info.participantId) return;
    pendingRemoteAudioRef.current.delete(info.participantId);
    if (info.local === false && participantAudioReceiverRef.current) {
      void participantAudioReceiverRef.current.stopCapture(info.participantId).catch(() => {});
    }
  };

  /** 把单个远程参会者音频接入采集器（启动 capture + 连后端 ws） */
  const attachRemoteTrack = async (participantId: string, participantName: string, track: MediaStreamTrack) => {
    const receiver = participantAudioReceiverRef.current;
    if (!receiver) return;
    const info: ParticipantTrackInfo = {
      participantId,
      participantName,
      trackId: track.id,
      isLocal: false,
    };
    try {
      await receiver.startCapture(track, info, {
        sendToBackend: true,
        backendWsUrl: API_CONFIG.wsUrl,
        meetingId: roomName,
      });
      await receiver.connectBackendForSession(participantId, API_CONFIG.wsUrl);
      setRemoteCaptureCount(receiver.getAllCaptureStates().filter(s => s.isCapturing).length);
      console.log(`[App] 远程参会者音频已接入: ${participantName}`);
    } catch (err) {
      console.error(`[App] 远程参会者接入失败 [${participantName}]:`, err);
    }
  };

  const handleStartBot = async () => {
    if (botStatus !== 'idle') return;
    if (!isModerator) {
      alert('只有主持人可以开启 AI 语音识别');
      return;
    }
    if (micMuted) {
      alert('请先取消 Jitsi 工具栏的麦克风静音，再开启 AI 语音识别');
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

      // 启动多路远程音频采集器 + 接入当前已存在的 remote audio tracks
      const receiver = new ParticipantAudioReceiver();
      await receiver.initialize();
      participantAudioReceiverRef.current = receiver;
      const pending = pendingRemoteAudioRef.current;
      for (const [pid, info] of pending.entries()) {
        // local 的 track 由 audioCapture 处理，不重复接
        if (info.track.readyState === 'live') {
          // 跳过 local（pending 里也可能有 local，用 jid 前缀判断；这里用 userIdRef 简单排除）
          if (pid !== userIdRef.current) {
            await attachRemoteTrack(pid, info.participantName, info.track);
          }
        }
      }

      setBotStatus('started');
      console.log('[App] AI Bot 已启动，本地 + 远程参会者音频采集中...');
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
      // 停止本地采集
      await audioServiceRef.current?.stop();
      audioServiceRef.current = null;
      setAudioState(null);
      // 停止所有远程采集（每个 session 的 ws 会在 stopCapture 中关闭）
      if (participantAudioReceiverRef.current) {
        await participantAudioReceiverRef.current.stopAll();
        await participantAudioReceiverRef.current.destroy();
        participantAudioReceiverRef.current = null;
      }
      setRemoteCaptureCount(0);
      isBotOperatorRef.current = false;
      setBotStatus('idle');
      console.log('[App] AI Bot 已停止');
    } catch (err) {
      console.error('[App] AI Bot 停止失败:', err);
      isBotOperatorRef.current = false;
      setBotStatus('idle');
    }
  };

  // 用户在 Jitsi 工具栏点了麦克风静音 → 如果正在录制，自动停止录制
  // 配合 audioCapture 的"静音帧不发送"逻辑一起工作
  useEffect(() => {
    if (micMuted && botStatus === 'started' && isBotOperatorRef.current) {
      console.log('[App] 麦克风已静音，自动停止 AI 录制');
      handleStopBot();
    }
    // 只在意 micMuted 翻转为 true 的瞬间；handleStopBot 内部已有 started/operator 校验
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [micMuted, botStatus]);

  if (!joined) {
    return (
      <div className="join-page">
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
          onMicMuteChange={setMicMuted}
          onTrackAdded={handleTrackAdded}
          onTrackRemoved={handleTrackRemoved}
          onParticipantsChange={setParticipantsCount}
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
        micMuted={micMuted}
        remoteCaptureCount={remoteCaptureCount}
        remotePartial={remotePartial}
        participantsCount={participantsCount}
      />
      <button className="leave-btn" onClick={handleLeave}>
        离开会议
      </button>
    </div>
  );
}
