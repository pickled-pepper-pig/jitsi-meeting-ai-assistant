# LLM 服务 - 会议总结
# 调用 OpenAI 兼容 API（SiLAN 内部 LLM 网关），使用标准库 urllib，无需额外依赖

import json
import logging
import os
import urllib.request
import urllib.error
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置（从环境变量读取）
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("LLM_API_KEY", "")
_BASE_URL = os.getenv("LLM_BASE_URL", "https://slapi.silan.com.cn/v1")
_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))

# 输入文本最大字符数（约 2 万汉字，留足输出空间）
_MAX_INPUT_CHARS = int(os.getenv("LLM_MAX_INPUT_CHARS", "60000"))

# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个专业的会议纪要助手。你的任务是根据会议的实时转写文本，生成一份结构清晰、内容准确的会议总结。

## 输出格式

请按以下 Markdown 格式输出：

### 会议概览
- **时间范围**：[开始时间] - [结束时间]
- **参与人数**：[N] 人
- **发言条数**：[N] 条

### 关键议题
（列出会议讨论的主要议题，每个议题 1-2 句话概括）

### 重要结论
（列出会议达成的共识或决定）

### 待办事项
（列出需要跟进的任务，格式：- [ ] 任务内容 @负责人）
如果无法确定负责人，省略 @负责人 部分。

## 注意事项
1. 只基于转写内容生成，不要编造未提及的信息
2. 保持客观中立的语气
3. 如果转写内容太少或无实质内容，直接回复"本次会议转写内容较少，无法生成有效总结。"
4. 不要输出任何与会议纪要无关的内容
"""


def _build_user_prompt(messages: List[Dict[str, Any]]) -> str:
    """将会议消息列表格式化为 LLM 输入文本，超长时只取最近的消息"""
    if not messages:
        return "请生成会议总结。"

    lines = ["以下是会议的实时转写记录，请生成会议总结：\n"]

    # 从后往前累积，超过字符限制时截断（保留最近的对话）
    total = 0
    truncated = False
    selected = []
    for msg in reversed(messages):
        msg_type = msg.get("type", "text")
        if msg_type == "summary":
            continue
        line = f"[{datetime.fromtimestamp(msg['timestamp'] / 1000).strftime('%H:%M:%S')}] {msg.get('sender', 'unknown')}：{msg.get('content', '')}"
        total += len(line)
        if total > _MAX_INPUT_CHARS:
            truncated = True
            break
        selected.append(line)

    selected.reverse()

    if truncated:
        lines.append(f"（会议记录较长，仅截取最近 {len(selected)} 条发言）\n")

    lines.extend(selected)
    return "\n".join(lines)


async def generate_summary(room_id: str, messages: List[Dict[str, Any]]) -> str:
    """
    调用 LLM 生成会议总结。

    如果未配置 API Key，回退到简单统计模式。
    """
    if not messages:
        return "本次会议暂无聊天记录。"

    if not _API_KEY:
        logger.warning("[LLM] LLM_API_KEY 未配置，回退到简单统计模式")
        return _fallback_summary(messages)

    try:
        summary = await _call_llm(room_id, messages)
        logger.info(f"[LLM] 会议总结生成成功 room={room_id}, length={len(summary)}")
        return summary
    except Exception as e:
        logger.error(f"[LLM] 生成会议总结失败 room={room_id}: {e}")
        return _fallback_summary(messages)


async def _call_llm(room_id: str, messages: List[Dict[str, Any]]) -> str:
    """调用 LLM API（urllib 实现，阻塞调用放线程池执行）"""
    import asyncio

    user_prompt = _build_user_prompt(messages)

    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": _TEMPERATURE,
        "max_tokens": _MAX_TOKENS,
    }).encode("utf-8")

    url = f"{_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(f"[LLM] 请求 LLM room={room_id}, messages={len(messages)}, model={_MODEL}")

    # urllib 是阻塞的，放线程池里跑，不阻塞 asyncio 事件循环
    loop = asyncio.get_event_loop()

    def _do_request() -> str:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()

    return await loop.run_in_executor(None, _do_request)


def _fallback_summary(messages: List[Dict[str, Any]]) -> str:
    """简单统计模式（未配置 API Key 或调用失败时回退）"""
    sender_stats: Dict[str, int] = {}
    for msg in messages:
        if msg.get("type") == "text":
            sender = msg.get("sender", "unknown")
            sender_stats[sender] = sender_stats.get(sender, 0) + 1

    start_time = datetime.fromtimestamp(messages[0]["timestamp"] / 1000).strftime("%H:%M:%S")
    end_time = datetime.fromtimestamp(messages[-1]["timestamp"] / 1000).strftime("%H:%M:%S")

    lines = [
        "会议纪要（离线模式）",
        "",
        f"时间范围：{start_time} - {end_time}",
        f"消息总数：{len(messages)} 条",
        f"参与发言：{len(sender_stats)} 人",
        "",
        "发言统计：",
    ]
    for sender, count in sender_stats.items():
        lines.append(f"  - {sender}：{count} 条消息")

    lines.append("")
    lines.append("（未配置 LLM_API_KEY，仅显示统计信息。配置 LLM_API_KEY 后可生成 AI 总结。）")

    return "\n".join(lines)
