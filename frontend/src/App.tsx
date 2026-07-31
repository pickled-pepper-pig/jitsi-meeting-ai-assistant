// 主应用组件

import { useState, useCallback, useRef, useEffect } from 'react';
import { JitsiMeeting } from './components/JitsiMeeting';
import { Sidebar } from './components/Sidebar';
import { useWebSocket } from './hooks/useWebSocket';
import { MessageBuffer } from './utils/messageBuffer';
import { ChatMessage, ServerMessage } from './types';
import { getJitsiDomain, getJitsiProtocol, API_CONFIG } from './config';
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
  // 解决 React 闭包陷阱：handleTrackAdded 用 ref 取最新值，而不是闭包旧值
  const botStatusRef = useRef<'idle' | 'starting' | 'started' | 'stopping'>('idle');
  const updateBotStatus = (status: typeof botStatusRef.current) => {
    botStatusRef.current = status;
    setBotStatus(status);
  };

  // 给 speaker 名字加主持人标注（仅在自己作为主持人的本地视角生效）
  // 其他参会者看到的字幕里仍只是名字，无主持人身份信息
  const tagModerator = (speaker: string): string => {
    if (!isModerator) return speaker;
    if (!speaker) return speaker;
    const localName = displayName.trim();
    if (localName && speaker === localName) {
      return `${speaker}（主持人）`;
    }
    return speaker;
  };
  const [audioState, setAudioState] = useState<AudioCaptureState | null>(null);
  // 旁观者侧收到的实时 partial 转写（来自操作者的 ASR 流）
  const [remotePartial, setRemotePartial] = useState<{ text: string; participant: string } | null>(null);
  // 真实参会者数量（含自己，来自 Jitsi IFrame API 的 participantJoined/Left 事件）
  const [participantsCount, setParticipantsCount] = useState(1);

  const tokenRef = useRef<string>('');
  const userIdRef = useRef<string>('');
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
          updateBotStatus('started');
        } else if (message.status === 'idle') {
          // 任何人关闭都会收到
          isBotOperatorRef.current = false;
          updateBotStatus('idle');
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
            const speakerName = tagModerator(t.participant_name || 'AI 转写');
            const ts = t.timestamp || Date.now();
            // 收到 final：清掉之前的 partial
            setRemotePartial(null);
            setMessages(prev => {
              // 去重：同内容 + 1.5s 内视为重复（跨链路去重：主持人本端 audioCapture 也可能产生同一条）
              // 不要求 sender 完全相等：本路径 sender=wei（主持人），本端路径可能 sender=wei
              const last = prev[prev.length - 1];
              if (last && last.content === t.text && Math.abs(last.timestamp - ts) < 1500) {
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
              participant: tagModerator(t.participant_name || 'AI 转写'),
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
      if (data?.error === 'name_conflict') {
        const err: Error & { code?: string } = new Error(data.message || '该用户名已在会议中');
        err.code = 'name_conflict';
        throw err;
      }
      // 默认 409 视为 moderator_occupied
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

      // HTTP 兜底拉取房间历史消息（chat + summary）：
      // - 即便 WS 还没建连/握手失败，新用户也能立刻看到进入前的会议纪要
      // - 与 WS 的 room_state_snapshot 互为冗余，messageBuffer 按 seq 去重
      try {
        const historyRes = await fetch(
          `${API_CONFIG.baseUrl}/api/meetings/${encodeURIComponent(roomName.trim())}/messages?token=${encodeURIComponent(result.token)}`,
        );
        if (historyRes.ok) {
          const history = await historyRes.json();
          if (Array.isArray(history.messages) && history.messages.length > 0) {
            messageBufferRef.current.addBatch(history.messages);
            refreshMessages();
            console.log(`[App] 加载历史 ${history.messages.length} 条消息`);
          }
        }
      } catch {
        // 拉取失败不阻塞加入，WS 后续 snapshot 会补齐
      }

      setJoined(true);
      connect(roomName.trim(), result.token);
    } catch (err: any) {
      if (err?.code === 'moderator_occupied') {
        // 显示提示窗，不进入会议界面
        setModeratorOccupiedMessage(err.message || '此房间已有人以主持人身份加入');
        setShowModeratorOccupied(true);
        return;
      }
      if (err?.code === 'name_conflict') {
        alert(err.message || '该用户名已在会议中，请换一个名字');
        return;
      }
      alert('无法连接到后端服务，请检查网络');
    }
  };

  // 刷新页面后自动重新加入会议：URL 里带 room + name 时触发
  // 用 ref 存 handleJoin 避免 useEffect 依赖重建导致的重复触发
  const handleJoinRef = useRef(handleJoin);
  handleJoinRef.current = handleJoin;
  useEffect(() => {
    const r = getUrlParam('room');
    const n = getUrlParam('name');
    if (r && n) {
      console.log('[App] 检测到 URL 带 room + name，自动重新加入会议');
      handleJoinRef.current();
    }
    // 只在挂载时跑一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    // 离开时不再需要停 audioService（已改为 Bot 统一采集，前端无本地采集）
    send({ action: 'leave', roomId: roomName });
    setJoined(false);
    setAiEnabled(false);
    updateBotStatus('idle');
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
    console.log(`[App] TRACK_ADDED: pid=${info.participantId}, name=${info.participantName}, local=${info.local}, botStatus=${botStatusRef.current}, hasReceiver=${!!participantAudioReceiverRef.current}`);
    // bot 已启动 + 是 remote audio → 立即接入（用 ref 解决闭包陷阱）
    if (info.local === false && botStatusRef.current === 'started' && participantAudioReceiverRef.current) {
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
      await receiver.connectBackendForSession(participantId, API_CONFIG.wsUrl, tokenRef.current);
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
    updateBotStatus('starting');

    try {
      isBotOperatorRef.current = true;

      // 只 spawn Meeting Agent Bot，由 Bot 在 Playwright 里统一采集所有参会者音频
      // （包括主持人自己）。不再启动浏览器本端 AudioCaptureService——否则主持人语音
      // 会被浏览器 + Bot 各采一遍，导致 transcript 重复且去重困难（ASR 识别有微小差异）。
      // Bot 采到的音频走 /ws/recorder/* → ingest_bot_audio → ASR，所有 transcript 通过
      // meeting_transcript 事件广播给房间所有人（包括主持人自己）。
      try {
        const token = tokenRef.current;
        // getJitsiProtocol() 返回 'https:'（带冒号，与 window.location.protocol 一致），
        // 拼接时只需一个 '/'，否则会变成 'https:://...'
        const roomUrl = `${getJitsiProtocol()}//${getJitsiDomain()}/${roomName}`;
        const spawnRes = await fetch(
          `${API_CONFIG.baseUrl}/api/meetings/${roomName}/bot/spawn`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, roomUrl }),
          },
        );
        if (!spawnRes.ok) {
          console.warn('[App] Bot spawn 失败:', await spawnRes.text());
        } else {
          const spawnData = await spawnRes.json();
          console.log('[App] Bot 已启动:', spawnData.botId);
        }
      } catch (e) {
        console.warn('[App] Bot spawn 异常:', e);
      }

      updateBotStatus('started');
      console.log('[App] AI Bot 已启动，Bot 统一采集所有参会者音频');
    } catch (err) {
      console.error('[App] AI Bot 启动失败:', err);
      isBotOperatorRef.current = false;
      updateBotStatus('idle');
    }
  };

  const handleStopBot = async () => {
    if (botStatus !== 'started') return;
    if (!isBotOperatorRef.current) return;  // 旁观者没权利停
    updateBotStatus('stopping');
    try {
      setAudioState(null);
      setRemoteCaptureCount(0);

      // 调用后端 kill Meeting Agent Bot
      try {
        const token = tokenRef.current;
        await fetch(
          `${API_CONFIG.baseUrl}/api/meetings/${roomName}/bot/kill`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token }),
          },
        );
        console.log('[App] Bot kill 请求已发送');
      } catch (e) {
        console.warn('[App] Bot kill 异常:', e);
      }

      isBotOperatorRef.current = false;
      updateBotStatus('idle');
      console.log('[App] AI Bot 已停止');
    } catch (err) {
      console.error('[App] AI Bot 停止失败:', err);
      isBotOperatorRef.current = false;
      updateBotStatus('idle');
    }
  };

  // 麦克风静音状态只控制"本端是否上传 audio_chunk"，不再触发 AI Bot 启停
  // （AI 开关由主持人独立控制；参会者静音也只是过滤自己的数据）

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
            {isModerator ? '创建会议' : '加入会议'}
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
          onMicMuteChange={() => { /* 静音状态已下沉到 audioCapture / ParticipantAudioReceiver 内部处理 */ }}
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
        remoteCaptureCount={remoteCaptureCount}
        remotePartial={remotePartial}
        participantsCount={participantsCount}
        tagModerator={tagModerator}
      />
      <button className="leave-btn" onClick={handleLeave}>
        离开会议
      </button>
    </div>
  );
}
