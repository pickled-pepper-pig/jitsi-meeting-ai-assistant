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

  // Jitsi 要求房间名全小写，统一在入口处转换，避免大写字母导致
  // "Invalid conference name" 错误（Jitsi 内部 toLowerCase 后与原始名不匹配）
  const sanitizeRoomName = (name: string) => name.trim().toLowerCase();

  // 随机生成 10 位英文字母 + 数字组合的房间名
  const generateRoomName = () => {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let result = '';
    for (let i = 0; i < 10; i++) {
      result += chars[Math.floor(Math.random() * chars.length)];
    }
    return result;
  };

  const [roomName, setRoomName] = useState(() => {
    const r = getUrlParam('room');
    return r ? r.toLowerCase() : r;
  });
  const [displayName, setDisplayName] = useState(getUrlParam('name'));
  const [isModerator, setIsModerator] = useState(true);
  const [asrModel, setAsrModel] = useState<'paraformer-zh-streaming' | 'SenseVoiceSmall'>('SenseVoiceSmall');
  const [asrPanelOpen, setAsrPanelOpen] = useState(false);
  const [joined, setJoined] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(false);
  const [copied, setCopied] = useState(false);
  // 首次进入会议前，Jitsi(19447) 自签名证书未信任时的引导浮层
  const [jitsiCertPending, setJitsiCertPending] = useState(false);
  // 引导浮层的步骤：'open' 先打开信任窗口 → 'confirm' 确认已信任后进入
  const [certTrustStep, setCertTrustStep] = useState<'open' | 'confirm'>('open');

  // 探测 Jitsi 站的证书是否已被浏览器信任：
  // 未信任时浏览器会直接以 NET::ERR_CERT_AUTHORITY_INVALID 断开并 reject fetch，
  // 已信任（即使跨域 no-cors 是 opaque 响应）则 resolve。
  // 因此用 fetch 是否 reject 来判断证书是否已信任，据此决定要不要弹引导。
  // 参数 forceDebug=true 时强制返回"未信任"，仅用于 ?forceCertTrust=1 的调试复现；
  // 正常应传 false（走真实探测），这样点"我已信任，进入会议"时能真正进入。
  const checkJitsiCertTrusted = useCallback(async (forceDebug = false): Promise<boolean> => {
    if (forceDebug) return false;
    try {
      await fetch(`${getJitsiProtocol()}//${getJitsiDomain()}/`, {
        method: 'GET',
        mode: 'no-cors',
        cache: 'no-store',
      });
      return true;
    } catch {
      return false;
    }
  }, []);
  // 用 ref 提供给 handleJoin 使用，避免闭包依赖问题
  const checkJitsiCertTrustedRef = useRef(checkJitsiCertTrusted);
  checkJitsiCertTrustedRef.current = checkJitsiCertTrusted;

  // 可拖动分割线：控制 Jitsi iframe 与会议纪要 sidebar 的宽度分配
  const SIDEBAR_DEFAULT = 460;
  const SIDEBAR_MIN = 400;
  const SIDEBAR_MAX = 600;
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const [isDragging, setIsDragging] = useState(false);
  const draggingRef = useRef(false);

  // 鼠标按下分割线 → 开始拖动
  const handleDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    setIsDragging(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  // 全局 mousemove / mouseup：拖动中实时调整宽度，松开时清理状态
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      // sidebar 在右侧，宽度 = 视口宽度 - 鼠标 x 坐标
      const w = window.innerWidth - e.clientX;
      setSidebarWidth(Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, w)));
    };
    const onUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  // 定时清理过期的 processing 状态：超过 10s 没收到后续消息的自动清除
  // 防止停止录制/静音后"正在说话..."残留
  useEffect(() => {
    const interval = setInterval(() => {
      setRemotePartials(prev => {
        const now = Date.now();
        let changed = false;
        const next = { ...prev };
        for (const [pid, p] of Object.entries(next)) {
          if (p.isProcessing && now - p.ts > 10000) {
            delete next[pid];
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const [showModeratorOccupied, setShowModeratorOccupied] = useState(false);
  const [moderatorOccupiedMessage, setModeratorOccupiedMessage] = useState('');
  // 通用弹窗（替代 alert，与 moderator_occupied 弹窗保持一致的样式）
  const [customAlert, setCustomAlert] = useState<{ icon: string; title: string; message: string } | null>(null);
  const [botStatus, setBotStatus] = useState<'idle' | 'starting' | 'started' | 'stopping'>('idle');
  const [summaryLoading, setSummaryLoading] = useState(false);
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
  // 多 speaker 实时 partial：按 participant_id 聚合，支持用户选中某个 speaker 聚焦查看。
  // 之前用单条 remotePartial，两人同时说话时会互相覆盖，展示混乱。
  // key: participant_id, value: { text, name, id, ts }
  const [remotePartials, setRemotePartials] = useState<Record<string, { text: string; name: string; id: string; ts: number; isProcessing?: boolean }>>({});
  // 用户选中聚焦查看的 participant_id；null 表示自动跟随最新说话的人
  const [focusedSpeakerId, setFocusedSpeakerId] = useState<string | null>(null);
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
        if (message.payload?.type === 'summary') {
          setSummaryLoading(false);
        }
        break;
      case 'synced':
        messageBufferRef.current.addBatch(message.messages);
        refreshMessages();
        console.log(`[App] 同步完成，补齐 ${message.messages.length} 条消息`);
        break;
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
            // 收到 final：从 partial map 移除该 speaker
            const pid = t.participant_id || speakerName;
            setRemotePartials(prev => {
              if (!prev[pid]) return prev;
              const next = { ...prev };
              delete next[pid];
              return next;
            });
            // 去重：同内容 + 1.5s 内视为重复（跨链路去重）
            const current = messageBufferRef.current.getAll();
            const last = current[current.length - 1];
            if (last && last.content === t.text && Math.abs(last.timestamp - ts) < 1500) {
              return;
            }
            const seq = Date.now();
            if (messageBufferRef.current.add({
              id: `remote-transcript-${ts}-${Math.random()}`,
              seq,
              roomId: roomName,
              sender: speakerName,
              content: t.text,
              timestamp: ts,
              type: 'text',
            })) {
              refreshMessages();
            }
          }
        }
        break;
      case 'meeting_transcript_partial':
        // 多 speaker partial：按 participant_id 聚合，不互相覆盖
        {
          const t = message as unknown as {
            text: string;
            participant_id?: string;
            participant_name?: string;
            timestamp?: number;
            is_processing?: boolean;
          };
          const speakerName = tagModerator(t.participant_name || 'AI 转写');
          const pid = t.participant_id || speakerName;
          // is_processing（SenseVoice 正在处理）：text 为空，显示"正在处理..."
          if (t.is_processing) {
            setRemotePartials(prev => ({
              ...prev,
              [pid]: {
                text: '',
                name: speakerName,
                id: pid,
                ts: t.timestamp || Date.now(),
                isProcessing: true,
              },
            }));
          } else if (t.text) {
            setRemotePartials(prev => ({
              ...prev,
              [pid]: {
                text: t.text!,
                name: speakerName,
                id: pid,
                ts: t.timestamp || Date.now(),
                isProcessing: false,
              },
            }));
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

  const fetchJoinToken = async (
    roomId: string, userId: string, userName: string, asModerator: boolean,
    asrModel: string = 'paraformer-zh-streaming',
  ) => {
    const res = await fetch(`${API_CONFIG.baseUrl}/api/join`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ roomId, userId, userName, asModerator, asrModel }),
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
    if (res.status === 404) {
      const data = await res.json().catch(() => ({}));
      if (data?.error === 'meeting_not_exists') {
        const err: Error & { code?: string } = new Error(data.message || '会议尚未创建');
        err.code = 'meeting_not_exists';
        throw err;
      }
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json() as Promise<{
      token: string;
      role: 'moderator' | 'participant';
      reconnect?: boolean;
      history_cleared?: boolean;
      asrModel?: string;
    }>;
  };

  const handleJoin = async () => {
    if (!roomName.trim() || !displayName.trim()) {
      alert('请填写房间名和用户名');
      return;
    }

    // userId 生成策略：
    //   - 全局唯一 ID，首次生成后写入 localStorage（跨房间跨名字复用同一 ID）
    //   - 这样同一浏览器的同一用户（不管进哪个房间、用什么名字）都拿到同一 ID，
    //     刷新页面时重连身份保持一致。
    //   - 不同浏览器/不同人的 userId 不同，后端 check_name_conflict 才能按 user_id 区分。
    //   之前用 `room+name` 做 localStorage key，会导致同一浏览器用同名测试时
    //   复用上一个用户的 userId，绕过后端查重。
    let userId = '';
    try {
      userId = localStorage.getItem('meeting:userId') || '';
    } catch {
      // localStorage 不可用时回退到生成
    }
    if (!userId) {
      userId = `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    }
    try {
      localStorage.setItem('meeting:userId', userId);
    } catch {
      // 写入失败也无影响
    }
    userIdRef.current = userId;

    try {
      const result = await fetchJoinToken(sanitizeRoomName(roomName), userId, displayName.trim(), isModerator, asrModel);
      tokenRef.current = result.token;
      // 真实角色由后端决定（避免前端伪造）
      setIsModerator(result.role === 'moderator');
      setAiEnabled(true);
      // 同步后端确认的 ASR 模型
      if (result.asrModel) setAsrModel(result.asrModel as 'paraformer-zh-streaming' | 'SenseVoiceSmall');

      // 是否需要展示上一轮纪要由后端 claim_moderator 按会议状态决定：
      //   - 上一轮已结束（history_cleared=true）→ 后端已清空，下方 /messages 拉到空列表
      //   - 上一轮未结束（history_cleared=false）→ 后端保留，下方 /messages 继续展示
      // 因此这里不再主动清空历史，直接交给下方 HTTP 兜底加载即可。

      // HTTP 兜底拉取房间历史消息（chat + summary）：
      // - 即便 WS 还没建连/握手失败，新用户也能立刻看到进入前的会议纪要
      // - 与 WS 的 room_state_snapshot 互为冗余，messageBuffer 按 seq 去重
      try {
        const historyRes = await fetch(
          `${API_CONFIG.baseUrl}/api/meetings/${encodeURIComponent(sanitizeRoomName(roomName))}/messages?token=${encodeURIComponent(result.token)}`,
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

      // 首次进入会议前，先探测 Jitsi(19447) 自签名证书是否已被浏览器信任。
      // 未信任时 Jitsi iframe 的信令 WebSocket 会被浏览器静默拦截，表现为
      // 视频/音频按钮一直转圈。这里未信任则先弹引导浮层，让用户在该页内
      // 内嵌的 19447 iframe 里点一次"继续"完成信任，避免用户手动复制粘贴 URL。
      // 调试：URL 带 ?forceCertTrust=1 时强制按"未信任"弹引导，方便复现。
      const forceDebug = typeof window !== 'undefined'
        && new URLSearchParams(window.location.search).get('forceCertTrust') === '1';
      const trusted = await checkJitsiCertTrustedRef.current(forceDebug);
      if (!trusted) {
        setCertTrustStep('open');
        setJitsiCertPending(true);
        return;
      }

      setJoined(true);
      connect(sanitizeRoomName(roomName), result.token);
    } catch (err: any) {
      if (err?.code === 'moderator_occupied') {
        // 显示提示窗，不进入会议界面
        setModeratorOccupiedMessage(err.message || '此房间已有人以主持人身份加入');
        setShowModeratorOccupied(true);
        return;
      }
      if (err?.code === 'name_conflict') {
        setCustomAlert({
          icon: '⚠️',
          title: '用户名已占用',
          message: err.message || '该用户名已在会议中，请换一个名字',
        });
        return;
      }
      if (err?.code === 'meeting_not_exists') {
        setCustomAlert({
          icon: '📋',
          title: '会议不存在',
          message: err.message || '会议尚未创建，请先以主持人身份创建会议',
        });
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

  // 证书引导浮层里点击"我已信任，进入会议"后的处理：真实探测，通过则进入会议。
  // （这里不用 forceDebug，保证按钮能真正进入；forceDebug 只作用于初次探测）
  const enterAfterCertTrusted = useCallback(async () => {
    const trusted = await checkJitsiCertTrustedRef.current(false);
    if (!trusted) {
      // 仍未信任，停留在引导浮层（用户可能还没在 iframe 里点"继续"）
      setJitsiCertPending(true);
      return;
    }
    setJitsiCertPending(false);
    setJoined(true);
    connect(sanitizeRoomName(roomName), tokenRef.current);
  }, [roomName, connect, sanitizeRoomName]);

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
      // 通过 Jitsi 默认按钮离开时也要结束会议（释放主持人占位 + 清空纪要）
      fetch(
        `${API_CONFIG.baseUrl}/api/meetings/${encodeURIComponent(roomName)}/end`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: tokenRef.current }),
        },
      ).catch((e) => console.warn('[App] 结束会议请求失败:', e));
    }
    setJoined(false);
  }, [send, roomName, isModerator]);

  const handleSummarize = useCallback(() => {
    setSummaryLoading(true);
    send({
      action: 'summarize',
      roomId: roomName,
      token: tokenRef.current,
    });
  }, [send, roomName]);

  const handleLeave = async () => {
    // 离开时不再需要停 audioService（已改为 Bot 统一采集，前端无本地采集）
    send({ action: 'leave', roomId: roomName });
    // 主持人离开 = 结束会议：通知后端释放主持人占位 + 清空参会者，
    // 这样同一主持人重新进入时会被视为「创建新会议」，自动清空上一轮纪要。
    if (isModerator && tokenRef.current) {
      try {
        await fetch(
          `${API_CONFIG.baseUrl}/api/meetings/${encodeURIComponent(roomName)}/end`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: tokenRef.current }),
          },
        );
      } catch (e) {
        console.warn('[App] 结束会议请求失败:', e);
      }
    }
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
      setRemotePartials({});

      // 停止浏览器端所有远程参会者音频采集（关闭 WS + 断开音频处理）
      if (participantAudioReceiverRef.current) {
        void participantAudioReceiverRef.current.stopAll();
      }

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
        {jitsiCertPending && (
          <div className="proxy-warning-overlay">
            <div className="proxy-warning-modal cert-wizard-modal">
              <div className="proxy-warning-icon">🔒</div>
              <h3>首次进入需完成安全确认</h3>

              {/* 步骤进度条 */}
              <div className="cert-wizard-step">
                <div className={`cert-wizard-step-item ${certTrustStep === 'confirm' ? 'done' : 'active'}`}>
                  <span className="dot">1</span> 打开信任窗口
                </div>
                <div className={`cert-wizard-step-connector ${certTrustStep === 'confirm' ? 'done' : ''}`} />
                <div className={`cert-wizard-step-item ${certTrustStep === 'confirm' ? 'active' : ''}`}>
                  <span className="dot">2</span> 完成确认
                </div>
              </div>

              {certTrustStep === 'open' ? (
                <>
                  <p className="cert-wizard-title">打开安全确认窗口</p>
                  <p className="cert-wizard-desc">
                    点击按钮，在新页面点「高级」→「继续前往」即可，仅首次需要。
                  </p>
                  <button
                    className="cert-wizard-open"
                    onClick={() => {
                      window.open(`${getJitsiProtocol()}//${getJitsiDomain()}/`, '_blank');
                      setCertTrustStep('confirm');
                    }}
                  >
                    打开信任窗口
                  </button>
                </>
              ) : (
                <>
                  <p className="cert-wizard-title">进入会议</p>
                  <p className="cert-wizard-desc">
                    已在弹出页面点过「继续前往」，点击进入会议。
                  </p>
                  <button
                    className="cert-wizard-open"
                    onClick={() => enterAfterCertTrusted()}
                  >
                    我已信任，进入会议
                  </button>
                  <button
                    className="cert-wizard-back"
                    onClick={() => setCertTrustStep('open')}
                  >
                    ← 返回重开窗口
                  </button>
                </>
              )}
            </div>
          </div>
        )}
        {customAlert && (
          <div className="proxy-warning-overlay">
            <div className="proxy-warning-modal">
              <div className="proxy-warning-icon">{customAlert.icon}</div>
              <h3>{customAlert.title}</h3>
              <p>{customAlert.message}</p>
              <button
                className="proxy-warning-btn"
                onClick={() => setCustomAlert(null)}
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
            <div className="room-input-group">
              <input
                type="text"
                value={roomName}
                onChange={(e) => setRoomName(e.target.value.toLowerCase())}
                placeholder="请输入房间名（自动转小写），或点击右侧 🎲 随机生成"
              />
              <button
                type="button"
                className="room-random-btn"
                title="随机生成房间名"
                aria-label="随机生成房间名"
                onClick={() => setRoomName(generateRoomName())}
              >
                🎲
              </button>
            </div>
          </div>

          <div className="form-group">
            <label>用户名</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="请输入你的名字"
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

          {isModerator && (
            <div className="form-group asr-panel">
              <button
                type="button"
                className="asr-panel-header"
                onClick={() => setAsrPanelOpen(o => !o)}
                aria-expanded={asrPanelOpen}
              >
                <span className="asr-panel-label">
                  <svg className="asr-panel-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="9" y="2" width="6" height="13" rx="3" />
                    <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
                    <line x1="12" y1="19" x2="12" y2="22" />
                  </svg>
                  ASR 语音识别模型
                </span>
                <span className="cer-tooltip" tabIndex={0}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                  <span className="cer-tooltip-text">CER（字错误率）：衡量语音识别准确度的指标，越低越好</span>
                </span>
                <span className="asr-panel-current">{asrModel === 'paraformer-zh-streaming' ? 'Paraformer 流式' : 'SenseVoice 高准度'}</span>
                <svg className={`asr-panel-chevron ${asrPanelOpen ? 'asr-chevron-open' : ''}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              {asrPanelOpen && (
                <div className="asr-model-selector">
                  <label className={`asr-model-option ${asrModel === 'SenseVoiceSmall' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="asrModel"
                      value="SenseVoiceSmall"
                      checked={asrModel === 'SenseVoiceSmall'}
                      onChange={() => setAsrModel('SenseVoiceSmall')}
                    />
                    <div className="asr-model-info">
                      <span className="asr-model-name">SenseVoice-Small</span>
                      <span className="asr-model-desc">段批处理｜CER 3.8%｜适合高准度纪要</span>
                    </div>
                  </label>
                  <label className={`asr-model-option ${asrModel === 'paraformer-zh-streaming' ? 'active' : ''}`}>
                    <input
                      type="radio"
                      name="asrModel"
                      value="paraformer-zh-streaming"
                      checked={asrModel === 'paraformer-zh-streaming'}
                      onChange={() => setAsrModel('paraformer-zh-streaming')}
                    />
                    <div className="asr-model-info">
                      <span className="asr-model-name">Paraformer-zh-streaming</span>
                      <span className="asr-model-desc">流式 chunk｜CER 5.1%｜支持热词注入</span>
                    </div>
                  </label>
                </div>
              )}
            </div>
          )}

          <button className="join-btn" onClick={handleJoin}>
            {isModerator ? '创建会议' : '加入会议'}
          </button>

          <div className="tips">
            <p>使用说明</p>
            <ul>
              <li>输入房间名与昵称即可创建或加入会议</li>
              <li>首次进入会议请勾选「以主持人身份加入」，其他参会者无需勾选</li>
              <li>可在「ASR 语音识别模型」中切换识别引擎</li>
              <li>请勿使用外部 VPN，否则会导致页面无法加载</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <div className={`meeting-area${isDragging ? ' dragging' : ''}`}>
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
      <div className="sidebar-divider" onMouseDown={handleDividerMouseDown} />
      <Sidebar
        messages={messages}
        onSummarize={handleSummarize}
        connectionStatus={status}
        isModerator={isModerator}
        aiEnabled={aiEnabled}
        summaryLoading={summaryLoading}
        onCopyInvite={copyInviteLink}
        inviteCopied={copied}
        onStartBot={handleStartBot}
        onStopBot={handleStopBot}
        botStatus={botStatus}
        audioState={audioState}
        remoteCaptureCount={remoteCaptureCount}
        remotePartials={remotePartials}
        focusedSpeakerId={focusedSpeakerId}
        onFocusSpeaker={setFocusedSpeakerId}
        participantsCount={participantsCount}
        onLeave={handleLeave}
        style={{ width: sidebarWidth, minWidth: sidebarWidth }}
      />
    </div>
  );
}
