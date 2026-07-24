// 合规提示组件 - "AI 正在处理会议"

import { useState } from 'react';

interface ComplianceNoticeProps {
  visible: boolean;
}

export function ComplianceNotice({ visible }: ComplianceNoticeProps) {
  const [dismissed, setDismissed] = useState(false);

  if (!visible || dismissed) return null;

  return (
    <div className="compliance-notice">
      <div className="notice-content">
        <span className="notice-icon">🔔</span>
        <span className="notice-text">
          本次会议正在被 AI 处理（转写/总结），会议内容将被记录
        </span>
        <button className="notice-close" onClick={() => setDismissed(true)}>
          知道了
        </button>
      </div>
    </div>
  );
}
