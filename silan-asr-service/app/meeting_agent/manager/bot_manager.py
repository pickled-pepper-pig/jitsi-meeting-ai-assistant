"""Bot 生命周期管理

职责：
- 维护 meeting_id → MeetingBot 映射（内存 + Redis）
- 生成 bot_token（短期、不可伪造）
- 启停 Headless Chromium（委托给 browser/controller.py，**复用单例 controller**避免 kill 失效）
- 健康检查 / 异常恢复
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Optional, List

from ..models import MeetingBot, ParticipantState

logger = logging.getLogger(__name__)

# Redis 键前缀与 TTL
REDIS_BOT_KEY_PREFIX = "meeting_bot:"
REDIS_BOT_TTL = 6 * 60 * 60  # 6h（Bot 生命周期一般 < 会议时长）


def _redis_client():
    """惰性获取 Redis 客户端，避免循环依赖"""
    try:
        from app.meeting_state import _redis_client as rc, _redis_enabled
        if _redis_enabled and rc:
            return rc
    except Exception:
        return None
    return None


class BotManager:
    """全局 Bot 管理器（单例）"""

    def __init__(self):
        self._bots: Dict[str, MeetingBot] = {}     # meeting_id -> MeetingBot
        # Flask 后台线程没有 event loop，延迟到主线程首次使用时创建 asyncio.Lock
        self._lock = None
        # BrowserController 复用单例：kill 时必须用同一个实例才能找到 browser 句柄
        # （之前每次 new 新实例导致 _browsers 字典永远为空 → kill 实际关不掉 browser）
        self._browser_controller = None
        # 健康检查任务
        self._health_task: Optional[asyncio.Task] = None
        # 启动时标记：避免重复加载 Redis 里的 stale bot
        self._recovered = False

    async def _ensure_lock(self):
        """惰性创建 asyncio.Lock（在主线程的 event loop 内调用）"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_browser_controller(self):
        """惰性初始化 BrowserController 单例"""
        if self._browser_controller is None:
            from ..browser.controller import BrowserController
            self._browser_controller = BrowserController()
        return self._browser_controller

    # ------------------------------------------------------------------
    # Redis 持久化（元数据级，Chromium 进程无法跨进程恢复）
    # ------------------------------------------------------------------
    def _persist_bot(self, bot: MeetingBot) -> None:
        """把 bot 元数据写 Redis（status=running/spawning 时才写）"""
        rc = _redis_client()
        if rc is None:
            return
        try:
            key = f"{REDIS_BOT_KEY_PREFIX}{bot.meeting_id}"
            rc.set(key, json.dumps(bot.to_dict(), ensure_ascii=False), ex=REDIS_BOT_TTL)
        except Exception as e:
            logger.warning(f"[BotManager] Redis 写入 bot 失败: {e}")

    def _delete_bot_from_redis(self, meeting_id: str) -> None:
        rc = _redis_client()
        if rc is None:
            return
        try:
            rc.delete(f"{REDIS_BOT_KEY_PREFIX}{meeting_id}")
        except Exception:
            pass

    def _load_stale_bots(self) -> None:
        """进程启动时加载 Redis 里的 bot 记录，标记为 stale（无法恢复 Chromium 进程）

        这些记录主要用于：
        1. 让 /bot/status 能查到历史（明确告诉调用方是 stale）
        2. 避免下一次 spawn 误判"已有运行 bot"而复用空壳
        """
        rc = _redis_client()
        if rc is None:
            return
        try:
            for key in rc.scan_iter(f"{REDIS_BOT_KEY_PREFIX}*"):
                raw = rc.get(key)
                if not raw:
                    continue
                data = json.loads(raw)
                meeting_id = data.get("meetingId")
                if not meeting_id or meeting_id in self._bots:
                    continue
                # 重启后的 bot 一定是 stale（Chromium 进程已死）
                stale_bot = MeetingBot(
                    bot_id=data.get("botId", ""),
                    meeting_id=meeting_id,
                    bot_token="",  # token 不持久化，重启后无法验证新 WS
                    status="stale",
                    created_at=data.get("createdAt", 0),
                    error="进程重启，Chromium 已失联（stale）",
                )
                self._bots[meeting_id] = stale_bot
                logger.warning(f"[BotManager] 发现 stale bot: meeting={meeting_id}, oldBotId={stale_bot.bot_id}")
            # 清掉所有 stale 标记的 Redis 记录（避免下次启动再加载）
            for key in rc.scan_iter(f"{REDIS_BOT_KEY_PREFIX}*"):
                rc.delete(key)
        except Exception as e:
            logger.warning(f"[BotManager] 加载 stale bots 失败: {e}")

    # ------------------------------------------------------------------
    # spawn / kill
    # ------------------------------------------------------------------
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
        # 首次 spawn 时惰性加载 stale bots
        if not self._recovered:
            self._load_stale_bots()
            self._recovered = True
            self._start_health_check()

        lock = await self._ensure_lock()
        async with lock:
            existing = self._bots.get(meeting_id)
            if existing and existing.status in ("running", "spawning"):
                logger.warning(f"[BotManager] 房间 {meeting_id} 已有运行中的 Bot，复用")
                return existing
            # stale/failed/killed 的清理掉，允许重新 spawn
            if existing:
                logger.info(f"[BotManager] 清理旧 bot（status={existing.status}）后重新 spawn")
                self._bots.pop(meeting_id, None)
                self._delete_bot_from_redis(meeting_id)

            bot_id = f"bot-{uuid.uuid4().hex[:8]}"
            bot_token = self._generate_bot_token(bot_id, meeting_id)

            bot = MeetingBot(
                bot_id=bot_id,
                meeting_id=meeting_id,
                bot_token=bot_token,
                status="spawning",
            )
            self._bots[meeting_id] = bot
            self._persist_bot(bot)
            try:
                from app.meeting_state import sqlite_store
                sqlite_store.save_bot_instance(meeting_id, bot_id, "spawning")
            except Exception:
                pass

            # 启动 Chromium（复用单例 controller！这是 kill bug 的关键修复）
            controller = self._get_browser_controller()
            try:
                await controller.launch(
                    bot_id=bot_id,
                    meeting_id=meeting_id,
                    room_url=room_url,
                    bot_jwt=bot_jwt,
                    bot_token=bot_token,
                )
                bot.status = "running"
                self._persist_bot(bot)
                logger.info(f"[BotManager] Bot {bot_id} 启动成功，房间 {meeting_id}")
                try:
                    from app.meeting_state import sqlite_store
                    sqlite_store.update_bot_status(bot_id, "running")
                except Exception:
                    pass
            except Exception as e:
                bot.status = "failed"
                bot.error = str(e)
                self._persist_bot(bot)
                logger.exception(f"[BotManager] Bot {bot_id} 启动失败: {e}")
                try:
                    from app.meeting_state import sqlite_store
                    sqlite_store.update_bot_status(bot_id, "failed")
                except Exception:
                    pass
                raise

            return bot

    async def kill_bot(self, meeting_id: str) -> bool:
        """停止一个 Bot

        修复点：必须用 spawn 时的同一个 BrowserController 实例，
        否则 _browsers 字典在新实例里是空的，kill 调用等于 no-op。
        """
        lock = await self._ensure_lock()
        async with lock:
            bot = self._bots.get(meeting_id)
            if not bot:
                return False

            # stale bot（进程重启遗留）：直接清理内存 + Redis，没有 Chromium 要关
            if bot.status == "stale":
                logger.info(f"[BotManager] 清理 stale bot: meeting={meeting_id}")
                self._bots.pop(meeting_id, None)
                self._delete_bot_from_redis(meeting_id)
                return True

            # 关键修复：复用单例 controller，而不是 new BrowserController()
            controller = self._get_browser_controller()
            try:
                await controller.kill(bot.bot_id)
            except Exception as e:
                logger.warning(f"[BotManager] kill {bot.bot_id} 异常: {e}")

            bot.status = "killed"
            self._bots.pop(meeting_id, None)
            self._delete_bot_from_redis(meeting_id)
            logger.info(f"[BotManager] Bot {bot.bot_id} 已停止")
            try:
                from app.meeting_state import sqlite_store
                sqlite_store.update_bot_status(bot.bot_id, "killed", stopped_at=int(time.time() * 1000))
            except Exception:
                pass
            return True

    # ------------------------------------------------------------------
    # 健康检查 + 自动恢复
    # ------------------------------------------------------------------
    def _start_health_check(self) -> None:
        """启动后台健康检查任务（每 30s 一次）

        检查项：
        - Chromium page 是否还活着（isClosed）
        - Bot WS 是否还在（通过 receiver 间接判断，这里只查 page）
        """
        if self._health_task is not None and not self._health_task.done():
            return
        try:
            self._health_task = asyncio.create_task(self._health_loop())
        except RuntimeError:
            # 无事件循环时跳过（如 Flask 线程里调用）
            pass

    async def _health_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                await self._health_check_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[BotManager] health loop 异常: {e}")

    async def _health_check_once(self) -> None:
        """单次健康检查：把崩溃的 Bot 标记为 failed 并清理"""
        controller = self._browser_controller
        if controller is None:
            return

        stale_meetings: List[str] = []
        lock = await self._ensure_lock()
        async with lock:
            for meeting_id, bot in list(self._bots.items()):
                if bot.status != "running":
                    continue
                handle = controller._browsers.get(bot.bot_id)
                if handle is None:
                    # controller 里没句柄 = 已被 kill 或崩溃
                    logger.warning(f"[BotManager] 健康检查发现 bot {bot.bot_id} 无 browser 句柄，标记 failed")
                    bot.status = "failed"
                    bot.error = "Chromium 句柄丢失"
                    stale_meetings.append(meeting_id)
                    continue
                # 检查 page 是否已被关闭
                try:
                    if handle.page.is_closed():
                        logger.warning(f"[BotManager] 健康检查发现 bot {bot.bot_id} page 已关闭，标记 failed")
                        bot.status = "failed"
                        bot.error = "Chromium page 已关闭"
                        stale_meetings.append(meeting_id)
                except Exception as e:
                    logger.warning(f"[BotManager] 健康检查 page 异常 {bot.bot_id}: {e}")
                    bot.status = "failed"
                    bot.error = f"健康检查异常: {e}"
                    stale_meetings.append(meeting_id)

        # 失败的 Bot 从内存清掉（Redis 记录保留 6h 供审计）
        for mid in stale_meetings:
            self._bots.pop(mid, None)
            # 不删 Redis，让 status=failed 留痕；但更新它
            bot = self._bots.get(mid)
            if bot:
                self._persist_bot(bot)

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
        """生成 Bot 短期 JWT token

        复用项目 JWT_SHARED_SECRET（HS256）签名，receiver.py 用 verify_bot_jwt 校验。
        payload 里带 bot_id / meeting_id / role=bot，exp 1h（Bot 寿命通常 < 会议时长）。
        """
        import time as _time
        try:
            from app.auth import sign_token, JWT_ISSUER, JWT_AUDIENCE
            payload = {
                "iss": JWT_ISSUER,
                "aud": JWT_AUDIENCE,
                "sub": bot_id,
                "room": meeting_id,
                "botId": bot_id,
                "meetingId": meeting_id,
                "role": "bot",
                "iat": int(_time.time()),
                "exp": int(_time.time()) + 3600,  # 1h
            }
            return sign_token(payload)
        except Exception as e:
            logger.error(f"[BotManager] 签发 bot JWT 失败，回退到 uuid: {e}")
            # 兜底：JWT 密钥未配置时仍能跑（开发环境）
            return f"{bot_id}:{meeting_id}:{uuid.uuid4().hex}"

    def verify_bot_token(self, bot_token: str) -> Optional[MeetingBot]:
        """验证 bot_token，返回对应 Bot（不通过返回 None）

        先尝试按 JWT 校验；失败则回退到旧的 uuid 格式（兼容开发期未配密钥的环境）。
        """
        # 路径 1：JWT 校验
        try:
            from app.auth import verify_token
            payload = verify_token(bot_token)
            if payload and payload.get("role") == "bot":
                meeting_id = payload.get("meetingId") or payload.get("room")
                bot_id = payload.get("botId") or payload.get("sub")
                if meeting_id and bot_id:
                    bot = self._bots.get(meeting_id)
                    if bot and bot.bot_id == bot_id:
                        return bot
        except Exception:
            pass

        # 路径 2：旧 uuid 格式兜底（未配 JWT_SHARED_SECRET 时）
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
