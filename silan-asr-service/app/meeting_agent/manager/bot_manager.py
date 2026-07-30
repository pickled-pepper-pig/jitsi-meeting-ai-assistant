"""Bot 生命周期管理

职责：
- 维护 meeting_id → MeetingBot 映射（内存 + Redis）
- 生成 bot_token（短期、不可伪造）
- 启停 Headless Chromium（委托给 browser/controller.py）
- 健康检查 / 异常重连
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Dict, Optional, List

from ..models import MeetingBot, ParticipantState

logger = logging.getLogger(__name__)


class BotManager:
    """全局 Bot 管理器（单例）"""

    def __init__(self):
        self._bots: Dict[str, MeetingBot] = {}     # meeting_id -> MeetingBot
        self._lock = asyncio.Lock()
        # TODO: Redis 持久化（Day 2+）

    async def spawn_bot(
        self,
        meeting_id: str,
        room_url: str,
        bot_jwt: str,
    ) -> MeetingBot:
        """为一个会议拉起一个 Bot

        Args:
            meeting_id: Jitsi 房间 ID
            room_url:   Jitsi 房间 URL（带 jwt）
            bot_jwt:    Bot 加入会议用的 JWT（与 Jitsi 鉴权一致）

        Returns:
            MeetingBot 实例
        """
        async with self._lock:
            if meeting_id in self._bots and self._bots[meeting_id].status == "running":
                logger.warning(f"[BotManager] 房间 {meeting_id} 已有运行中的 Bot，复用")
                return self._bots[meeting_id]

            bot_id = f"bot-{uuid.uuid4().hex[:8]}"
            bot_token = self._generate_bot_token(bot_id, meeting_id)

            bot = MeetingBot(
                bot_id=bot_id,
                meeting_id=meeting_id,
                bot_token=bot_token,
                status="spawning",
            )
            self._bots[meeting_id] = bot

            # 启动 Chromium（异步，导入放这里避免循环依赖）
            from ..browser.controller import BrowserController
            controller = BrowserController()
            try:
                await controller.launch(
                    bot_id=bot_id,
                    meeting_id=meeting_id,
                    room_url=room_url,
                    bot_jwt=bot_jwt,
                    bot_token=bot_token,
                )
                bot.status = "running"
                logger.info(f"[BotManager] Bot {bot_id} 启动成功，房间 {meeting_id}")
            except Exception as e:
                bot.status = "failed"
                bot.error = str(e)
                logger.exception(f"[BotManager] Bot {bot_id} 启动失败: {e}")
                raise

            return bot

    async def kill_bot(self, meeting_id: str) -> bool:
        """停止一个 Bot"""
        async with self._lock:
            bot = self._bots.get(meeting_id)
            if not bot:
                return False

            from ..browser.controller import BrowserController
            controller = BrowserController()
            try:
                await controller.kill(bot.bot_id)
            except Exception as e:
                logger.warning(f"[BotManager] kill {bot.bot_id} 异常: {e}")

            bot.status = "killed"
            del self._bots[meeting_id]
            logger.info(f"[BotManager] Bot {bot.bot_id} 已停止")
            return True

    def get_bot(self, meeting_id: str) -> Optional[MeetingBot]:
        return self._bots.get(meeting_id)

    def list_bots(self) -> List[MeetingBot]:
        return list(self._bots.values())

    def register_participant(
        self,
        meeting_id: str,
        participant_id: str,
        display_name: str = "",
    ) -> Optional[ParticipantState]:
        """注册一个参会者，返回带 speaker_id 的状态"""
        bot = self._bots.get(meeting_id)
        if not bot:
            return None

        if participant_id in bot.participants:
            return bot.participants[participant_id]

        # 服务端分配 speaker_id（不可伪造，浏览器拿不到）
        speaker_id = f"speaker-{uuid.uuid4().hex[:8]}"
        state = ParticipantState(
            participant_id=participant_id,
            display_name=display_name,
            speaker_id=speaker_id,
        )
        bot.participants[participant_id] = state
        logger.info(f"[BotManager] 注册 participant {participant_id} → {speaker_id}")
        return state

    @staticmethod
    def _generate_bot_token(bot_id: str, meeting_id: str) -> str:
        """生成 Bot 短期 token（Day 1 用 uuid 简化，Day 2 换 JWT）"""
        return f"{bot_id}:{meeting_id}:{uuid.uuid4().hex}"

    def verify_bot_token(self, bot_token: str) -> Optional[MeetingBot]:
        """验证 bot_token，返回对应 Bot（不通过返回 None）"""
        try:
            bot_id, meeting_id, _ = bot_token.split(":", 2)
        except ValueError:
            return None

        bot = self._bots.get(meeting_id)
        if bot and bot.bot_token == bot_token:
            return bot
        return None


# 全局单例
_bot_manager: Optional[BotManager] = None


def get_bot_manager() -> BotManager:
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = BotManager()
    return _bot_manager
