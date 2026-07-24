// Mock LLM 服务 - Phase 1 模拟会议总结
// 第二阶段接入真实 LLM（如 OpenAI、通义千问等）后替换此文件

import { ChatMessage } from './types';

/**
 * 模拟 LLM 生成会议总结
 * 真实环境下应调用 LLM API，这里返回基于消息内容的简单摘要
 */
export async function generateSummary(roomId: string, messages: ChatMessage[]): Promise<string> {
  // 模拟网络延迟
  await new Promise((resolve) => setTimeout(resolve, 1500));

  if (messages.length === 0) {
    return '本次会议暂无聊天记录。';
  }

  // 按 sender 分组统计
  const senderStats = new Map<string, number>();
  for (const msg of messages) {
    if (msg.type === 'text') {
      senderStats.set(msg.sender, (senderStats.get(msg.sender) || 0) + 1);
    }
  }

  const startTime = new Date(messages[0].timestamp).toLocaleTimeString('zh-CN');
  const endTime = new Date(messages[messages.length - 1].timestamp).toLocaleTimeString('zh-CN');

  const summary = [
    '📋 会议纪要',
    '═══════════════════════════════',
    '',
    `时间范围：${startTime} - ${endTime}`,
    `消息总数：${messages.length} 条`,
    `参与发言：${senderStats.size} 人`,
    '',
    '👤 发言统计：',
    ...Array.from(senderStats.entries()).map(([sender, count]) => `  • ${sender}：${count} 条消息`),
    '',
    '💬 聊天摘要：',
    ...messages.slice(0, 10).map((m, i) => `  ${i + 1}. [${m.sender}] ${m.content.substring(0, 50)}${m.content.length > 50 ? '...' : ''}`),
    messages.length > 10 ? `\n  ... 还有 ${messages.length - 10} 条消息` : '',
    '',
    '⚡ 待办事项（Mock）：',
    '  • 整理会议中提到的关键任务',
    '  • 跟踪未完成的讨论项',
  ].join('\n');

  return summary;
}
