// Jitsi IFrame API Hook - 封装会议嵌入和事件监听

import { useRef, useEffect, useState } from 'react';
import { getJitsiBoshUrl, getJitsiWebsocketUrl } from '../config';

interface JitsiOptions {
  domain: string;
  protocol: 'http:' | 'https:';
  roomName: string;
  displayName: string;
  parentNode: HTMLElement | null;
  token?: string;
}

interface JitsiEventCallbacks {
  onIncomingMessage?: (sender: string, message: string, timestamp: string) => void;
  onOutgoingMessage?: (message: string) => void;
  onVideoConferenceLeft?: () => void;
  onReady?: () => void;
  onParticipantJoined?: (participantId: string, displayName: string) => void;
  onParticipantLeft?: (participantId: string) => void;
  // 参会者数量变化（含自己）
  onParticipantsChange?: (count: number) => void;
  onMicMuteChange?: (muted: boolean) => void;
  // 新轨道事件：Jitsi 发布/移除任意轨道时触发（含 local 和 remote，video/audio）
  onTrackAdded?: (info: { participantId: string; participantName: string; track: MediaStreamTrack; kind: 'audio' | 'video'; local: boolean }) => void;
  onTrackRemoved?: (info: { participantId: string; track: MediaStreamTrack; kind: 'audio' | 'video'; local: boolean }) => void;
}

let scriptLoadPromise: Promise<void> | null = null;
let lastScriptSrc: string | null = null;

function loadScript(protocol: string, domain: string): Promise<void> {
  const protoNoColon = protocol.replace(':', '');
  const src = `${protoNoColon}://${domain}/external_api.js`;

  if (typeof window !== 'undefined' && window.JitsiMeetExternalAPI && lastScriptSrc === src) {
    return Promise.resolve();
  }
  if (scriptLoadPromise && lastScriptSrc === src) return scriptLoadPromise;

  // 域名变更时，清理之前失败的 script 标签
  document.querySelectorAll('script[src*="external_api.js"]').forEach(el => {
    if (el.getAttribute('src') !== src) el.remove();
  });

  lastScriptSrc = src;
  scriptLoadPromise = new Promise((resolve, reject) => {
    // 检查全局 API 是否已存在
    if (window.JitsiMeetExternalAPI) {
      resolve();
      return;
    }

    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (window.JitsiMeetExternalAPI) {
        resolve();
      } else {
        existing.addEventListener('load', () => resolve());
        existing.addEventListener('error', () => reject(new Error('Failed to load Jitsi script')));
      }
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load Jitsi external_api.js from ${src}`));
    document.head.appendChild(script);
  });

  return scriptLoadPromise;
}

export function useJitsiApi(options: JitsiOptions, callbacks: JitsiEventCallbacks) {
  const apiRef = useRef<any>(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [micMuted, setMicMuted] = useState(false);
  const callbacksRef = useRef(callbacks);
  const optionsRef = useRef(options);
  const initializedRef = useRef(false);
  // 维护当前房间的参会者集合（含自己），用于推导真实参会者数量
  const participantsRef = useRef<Set<string>>(new Set());

  callbacksRef.current = callbacks;
  optionsRef.current = options;

  useEffect(() => {
    const { domain, protocol, roomName, displayName, parentNode, token } = options;

    if (!parentNode || !roomName || !displayName) return;

    let disposed = false;

    const init = async () => {
      // 防止重复初始化
      if (initializedRef.current) {
        if (apiRef.current) {
          try { apiRef.current.dispose(); } catch {}
          apiRef.current = null;
        }
        initializedRef.current = false;
        participantsRef.current.clear();
        setIsReady(false);
      }

      try {
        await loadScript(protocol, domain);

        if (disposed) return;
        if (!window.JitsiMeetExternalAPI) {
          throw new Error('JitsiMeetExternalAPI not available');
        }

        const jitsiOptions: any = {
          roomName,
          width: '100%',
          height: '100%',
          parentNode,
          protocol: protocol,
          configOverwrite: {
            disableDeepLinking: true,
            startWithAudioMuted: false,
            startWithVideoMuted: false,
            prejoinConfig: { enabled: false },
            enableWelcomePage: false,
            requireDisplayName: false,
            bosh: getJitsiBoshUrl(),
            websocket: getJitsiWebsocketUrl(),
            disableInviteFunctions: true,
            // 关闭"主持人"指示器（小红点、底部弹窗）
            disableModeratorIndicator: true,
            // 关闭"你现在是主持人了"这种 notification
            notifications: [],
            // 不让客户端根据"JWT 中没有 owner affiliation"自动升级
            enableUserRolesBasedOnToken: true,
          },
          interfaceConfigOverwrite: {
            SHOW_JITSI_WATERMARK: false,
            SHOW_WATERMARK_FOR_GUESTS: false,
            SHOW_PROMOTIONAL_CLOSE_PAGE: false,
            HIDE_INVITE_MORE_HEADER: true,
            // 隐藏"你是主持人"的角色标签
            DISABLE_VIDEO_BACKGROUND: false,
            // 完全不显示"你现在是主持人了"的提示
            DISABLE_RINGING: false,
          },
          userInfo: {
            displayName,
          },
        };

        if (token) {
          jitsiOptions.jwt = token;
        }

        const api = new window.JitsiMeetExternalAPI(domain, jitsiOptions);
        apiRef.current = api;
        initializedRef.current = true;

        // 确保 iframe 有完整的 allow 权限
        const iframe = parentNode.querySelector('iframe');
        if (iframe) {
          iframe.setAttribute('allow', 'microphone; camera; fullscreen; autoplay; display-capture; clipboard-write; clipboard-read');
          iframe.setAttribute('allowfullscreen', 'true');
        }

        const refreshParticipantsCount = () => {
          // 每次都拿全量 Jitsi 参会者信息，避免增量跟踪漏算"对方在我 ready 前已进入"的情况
          try {
            const list = api.getParticipantsInfo?.();
            if (Array.isArray(list)) {
              // 部分 Jitsi 版本 getParticipantsInfo 不含自己，兜底用 max(1, size)
              const count = Math.max(1, list.length);
              participantsRef.current = new Set(
                list.map((p: any) => p.participantId).filter(Boolean),
              );
              callbacksRef.current.onParticipantsChange?.(count);
            }
          } catch {
            // 兜底：保持 participantsRef 至少 1 人（自己）
            if (participantsRef.current.size === 0) {
              callbacksRef.current.onParticipantsChange?.(1);
            }
          }
        };

        api.addListener('ready', () => {
          if (disposed) return;
          console.log('[Jitsi] Ready');
          setIsReady(true);
          setError(null);
          callbacksRef.current.onReady?.();
          // ready 时主动拉一次全量参会者（自己的 participantJoined 不会触发）
          refreshParticipantsCount();
        });

        api.addListener('participantJoined', (e: any) => {
          if (e.id) participantsRef.current.add(e.id);
          callbacksRef.current.onParticipantJoined?.(e.id, e.displayName || '未知用户');
          // 增量 + 1（同时用全量刷新兜底，确保新计算正确）
          refreshParticipantsCount();
        });

        api.addListener('participantLeft', (e: any) => {
          if (e.id) participantsRef.current.delete(e.id);
          callbacksRef.current.onParticipantLeft?.(e.id);
          refreshParticipantsCount();
        });

        api.addListener('error', (err: any) => {
          console.error('[Jitsi] Error:', err);
          if (!disposed) {
            setError(err?.message || String(err));
          }
        });

        api.addListener('incomingMessage', (e: any) => {
          callbacksRef.current.onIncomingMessage?.(
            e.from || e.nick || '未知用户',
            e.message || e.text || '',
            e.timestamp || new Date().toISOString()
          );
        });

        api.addListener('outgoingMessage', (e: any) => {
          callbacksRef.current.onOutgoingMessage?.(e.message || e.text || '');
        });

        api.addListener('videoConferenceJoined', () => {
          // 我已加入会议：此时 getParticipantsInfo() 才会返回房间内所有人
          // （ready 只代表 IFrame 加载完成，不代表已 join 房间）
          if (disposed) return;
          setTimeout(refreshParticipantsCount, 300);
          setTimeout(refreshParticipantsCount, 1500);  // 兜底二次刷新
        });

        api.addListener('videoConferenceLeft', () => {
          callbacksRef.current.onVideoConferenceLeft?.();
        });

        // Jitsi 工具栏麦克风按钮的 mute 状态变化（包括"开始就静音"）
        api.addListener('audioMuteStatusChanged', (e: any) => {
          const muted = !!(e?.muted ?? false);
          setMicMuted(muted);
          callbacksRef.current.onMicMuteChange?.(muted);
        });

        // 任何参与者发布/移除轨道（本地 + 远程；audio + video）
        // 通过这里把 Jitsi 的 MediaStreamTrack 暴露给上层，让上层决定要不要采集
        api.addListener('trackAdded', (e: any) => {
          console.log('[useJitsiApi] trackAdded event:', JSON.stringify({ participantId: e?.participantId, participantDisplayName: e?.participantDisplayName, type: e?.type, kind: e?.track?.kind, local: e?.local, hasTrack: !!e?.track }));
          const track: MediaStreamTrack | undefined = e?.track;
          if (!track) {
            console.warn('[useJitsiApi] trackAdded 但 e.track 为空', e);
            return;
          }
          const kind = (track.kind || e?.type || 'video') as 'audio' | 'video';
          callbacksRef.current.onTrackAdded?.({
            participantId: e?.participantId || '',
            participantName: e?.participantDisplayName || e?.displayName || '未知参与者',
            track,
            kind,
            local: !!e?.local,
          });
        });

        api.addListener('trackRemoved', (e: any) => {
          const track: MediaStreamTrack | undefined = e?.track;
          if (!track) return;
          const kind = (track.kind || e?.type || 'video') as 'audio' | 'video';
          callbacksRef.current.onTrackRemoved?.({
            participantId: e?.participantId || '',
            track,
            kind,
            local: !!e?.local,
          });
        });

      } catch (err: any) {
        console.error('[Jitsi] Init failed:', err);
        if (!disposed) {
          setError(err.message || 'Failed to load Jitsi');
        }
      }
    };

    init();

    return () => {
      disposed = true;
      if (apiRef.current) {
        try { apiRef.current.dispose(); } catch {}
        apiRef.current = null;
      }
      initializedRef.current = false;
      setIsReady(false);
    };
  }, [options.domain, options.protocol, options.roomName, options.displayName, options.parentNode, options.token]);

  return { api: apiRef.current, isReady, error, micMuted };
}
