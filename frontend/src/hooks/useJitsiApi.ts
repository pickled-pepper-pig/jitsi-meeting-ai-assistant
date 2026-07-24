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
  const callbacksRef = useRef(callbacks);
  const optionsRef = useRef(options);
  const initializedRef = useRef(false);

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
          },
          interfaceConfigOverwrite: {
            SHOW_JITSI_WATERMARK: false,
            SHOW_WATERMARK_FOR_GUESTS: false,
            SHOW_PROMOTIONAL_CLOSE_PAGE: false,
            HIDE_INVITE_MORE_HEADER: true,
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

        api.addListener('ready', () => {
          if (disposed) return;
          console.log('[Jitsi] Ready');
          setIsReady(true);
          setError(null);
          callbacksRef.current.onReady?.();
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

        api.addListener('videoConferenceLeft', () => {
          callbacksRef.current.onVideoConferenceLeft?.();
        });

        api.addListener('participantJoined', (e: any) => {
          callbacksRef.current.onParticipantJoined?.(e.id, e.displayName || '未知用户');
        });

        api.addListener('participantLeft', (e: any) => {
          callbacksRef.current.onParticipantLeft?.(e.id);
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

  return { api: apiRef.current, isReady, error };
}
