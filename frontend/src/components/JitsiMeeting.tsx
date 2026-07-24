// Jitsi 会议组件 - 嵌入 Jitsi IFrame

import { useState } from 'react';
import { useJitsiApi } from '../hooks/useJitsiApi';

interface JitsiMeetingProps {
  domain: string;
  protocol: 'http:' | 'https:';
  roomName: string;
  displayName: string;
  token?: string;
  onIncomingMessage: (sender: string, message: string, timestamp: string) => void;
  onOutgoingMessage: (message: string) => void;
  onVideoConferenceLeft: () => void;
}

export function JitsiMeeting({
  domain,
  protocol,
  roomName,
  displayName,
  token,
  onIncomingMessage,
  onOutgoingMessage,
  onVideoConferenceLeft,
}: JitsiMeetingProps) {
  const [container, setContainer] = useState<HTMLElement | null>(null);

  const { isReady, error } = useJitsiApi(
    { domain, protocol, roomName, displayName, parentNode: container, token },
    { onIncomingMessage, onOutgoingMessage, onVideoConferenceLeft }
  );

  return (
    <div className="jitsi-container">
      <div ref={setContainer} className="jitsi-frame" />
      {error && (
        <div className="jitsi-error">
          <p>加载会议失败</p>
          <p className="error-detail">{error}</p>
        </div>
      )}
      {!isReady && !error && (
        <div className="jitsi-loading">
          正在加载会议...
        </div>
      )}
    </div>
  );
}
