// 总结会议按钮组件

import { useState } from 'react';
import { ConnectionStatus } from '../types';

interface SummaryButtonProps {
  onSummarize: () => void;
  disabled: boolean;
  status: ConnectionStatus;
  isModerator: boolean;
}

export function SummaryButton({ onSummarize, disabled, status, isModerator }: SummaryButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleClick = () => {
    setLoading(true);
    onSummarize();
    // 1.5s 后恢复按钮状态（Mock LLM 延迟）
    setTimeout(() => setLoading(false), 2000);
  };

  const isConnected = status === 'connected';
  const isDisabled = disabled || loading || !isConnected || !isModerator;

  let tooltip = '';
  if (!isConnected) tooltip = '未连接到服务器';
  else if (!isModerator) tooltip = '只有主持人可以生成总结';
  else if (loading) tooltip = '正在生成总结...';

  return (
    <button
      className={`summary-btn ${loading ? 'loading' : ''}`}
      onClick={handleClick}
      disabled={isDisabled}
      title={tooltip}
    >
      {loading ? '正在生成...' : '总结会议'}
    </button>
  );
}
