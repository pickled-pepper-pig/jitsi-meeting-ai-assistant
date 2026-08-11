// 合规提示组件 - "AI 正在处理会议"
// 首次进入显示，点击「知道了」后写入 localStorage，之后不再显示

import { useState } from 'react';

interface ComplianceNoticeProps {
  visible: boolean;
}

const STORAGE_KEY = 'complianceNoticeDismissed';

function readDismissed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function markDismissed() {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, '1');
  } catch {
    // localStorage 不可用时静默跳过（每次都会显示）
  }
}

export function ComplianceNotice({ visible }: ComplianceNoticeProps) {
  const [dismissed, setDismissed] = useState(readDismissed);

  if (!visible || dismissed) return null;

  return (
    <div className="compliance-notice">
      <div className="notice-content">
        <span className="notice-icon">🔔</span>
        <span className="notice-text">
          本次会议正在被 AI 处理（转写/总结），会议内容将被记录
        </span>
        <button
          className="notice-close"
          onClick={() => {
            markDismissed();
            setDismissed(true);
          }}
        >
          知道了
        </button>
      </div>
    </div>
  );
}
