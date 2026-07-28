# Mock LLM 服务 - 会议总结
# 后续可替换为真实 LLM（OpenAI、通义千问等）

import asyncio
import logging
import time
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


async def generate_summary(room_id: str, messages: List[Dict[str, Any]]) -> str:
    """
    模拟 LLM 生成会议总结。
    真实环境下应调用 LLM API，这里返回基于消息内容的简单摘要。
    """
    # 模拟网络延迟
    await asyncio.sleep(1.5)

    if not messages:
        return "本次会议暂无聊天记录。"

    # 按 sender 分组统计
    sender_stats: Dict[str, int] = {}
    for msg in messages:
        if msg.get("type") == "text":
            sender = msg.get("sender", "unknown")
            sender_stats[sender] = sender_stats.get(sender, 0) + 1

    start_time = datetime.fromtimestamp(messages[0]["timestamp"] / 1000).strftime("%H:%M:%S")
    end_time = datetime.fromtimestamp(messages[-1]["timestamp"] / 1000).strftime("%H:%M:%S")

    lines = [
        "📋 会议纪要",
        "═══════════════════════════════",
        "",
        f"时间范围：{start_time} - {end_time}",
        f"消息总数：{len(messages)} 条",
        f"参与发言：{len(sender_stats)} 人",
        "",
        "👤 发言统计：",
    ]
    for sender, count in sender_stats.items():
        lines.append(f"  • {sender}：{count} 条消息")

    lines.append("")
    lines.append("💬 聊天摘要：")
    for i, msg in enumerate(messages[:10]):
        content = msg.get("content", "")[:50]
        if len(msg.get("content", "")) > 50:
            content += "..."
        lines.append(f"  {i + 1}. [{msg.get('sender', '')}] {content}")

    if len(messages) > 10:
        lines.append(f"\n  ... 还有 {len(messages) - 10} 条消息")

    lines.extend([
        "",
        "⚡ 待办事项（Mock）：",
        "  • 整理会议中提到的关键任务",
        "  • 跟踪未完成的讨论项",
    ])

    return "\n".join(lines)
