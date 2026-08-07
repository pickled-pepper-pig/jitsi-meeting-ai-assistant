"""Playwright + Chromium 控制器

职责：
- 启动/停止 Headless Chromium
- 加载 recorder.html（注入 Jitsi + lib-jitsi-meet + audio pipeline）
- 通过 ?meeting_id=xxx&room_url=xxx&bot_jwt=xxx&bot_token=xxx&ws_url=xxx 参数传递上下文
- Day 1-B：传递 ws_url，让 recorder.html 把 PCM 推给 Python receiver
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# 浏览器注入页所在路径
RECORDER_HTML_PATH = Path(__file__).parent / "recorder.html"


def _build_recorder_ws_url(meeting_id: str) -> str:
    """构造 recorder WS URL（与 ws_server.py 的 SSL 检测逻辑一致）

    - SSL_CERT_DIR 配置了证书 → wss://
    - 否则 → ws://（Bot 本地连接，无需 SSL）
    """
    port = int(os.getenv("GATEWAY_PORT", "19087"))
    host = os.getenv("GATEWAY_HOST", "0.0.0.0")
    # Bot 与 Python 服务在同一台机器，直接走 127.0.0.1
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "") else host

    cert_dir = os.environ.get("SSL_CERT_DIR", "")
    proto = "wss"
    if not cert_dir:
        proto = "ws"
    else:
        cert_path = os.path.join(cert_dir, "localhost+3.pem")
        if not os.path.exists(cert_path):
            proto = "ws"

    return f"{proto}://{connect_host}:{port}/ws/recorder/{quote(meeting_id, safe='')}"


class BrowserController:
    """管理一个或多个 Chromium 实例（按 bot_id 区分）"""

    def __init__(self):
        self._playwright = None
        self._browsers: Dict[str, "BrowserHandle"] = {}
        self._lock = asyncio.Lock()

    async def launch(
        self,
        bot_id: str,
        meeting_id: str,
        room_url: str,
        bot_jwt: str,
        bot_token: str,
    ) -> None:
        """启动一个 Chromium 加载 recorder.html"""
        from playwright.async_api import async_playwright

        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()

            # 构造注入页 URL（带参数，URL 编码保证 JWT / 特殊字符安全）
            # 注意：room_url 用 safe='' 全编码，URLSearchParams.get 会自动解码
            # 之前 safe=':' 导致 :// 变 :%2F%2F，recorder.html 拿到的 room_url 是坏的
            ws_url = _build_recorder_ws_url(meeting_id)
            file_url = f"file://{RECORDER_HTML_PATH.absolute()}"
            params = (
                f"?meeting_id={quote(meeting_id, safe='')}"
                f"&room_url={quote(room_url, safe='')}"
                f"&bot_jwt={quote(bot_jwt, safe='')}"
                f"&bot_token={quote(bot_token, safe='')}"
                f"&ws_url={quote(ws_url, safe='')}"
            )
            page_url = file_url + params

            # headless 通过环境变量控制：
            #   - 本机 macOS（有显示器）：headless=False，浏览器真实启动，能拿到 WebRTC 远端音频
            #   - Linux 服务器（无 X server）：headless=True，必须设置
            # 注意：旧版 headless=True 在 Mac 上会让 WebRTC 远端 audio track 不产 PCM 帧 → 全 0 静音
            headless_mode = os.getenv("BOT_HEADLESS", "false").lower() == "true"
            # headless 模式专属参数：去掉 fake-ui（需要窗口系统），加 --headless=new
            # 否则在无 X server 的服务器上 chrome 会按 headed 启动 → Missing X server
            launch_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
                # 忽略自签名证书（Jitsi HTTPS + 本地 WSS）
                "--ignore-certificate-errors",
            ]
            if headless_mode:
                launch_args += [
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                ]
            else:
                launch_args += [
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                ]
            browser = await self._playwright.chromium.launch(
                headless=headless_mode,
                args=launch_args,
            )
            context = await browser.new_context(
                permissions=["microphone", "camera"],
                # Playwright 层面也忽略 HTTPS 错误（覆盖 Jitsi 自签名证书）
                ignore_https_errors=True,
            )
            page = await context.new_page()

            # 监听 console 日志（调试用）
            page.on("console", lambda msg: logger.info(f"[Bot-{bot_id}] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda exc: logger.error(f"[Bot-{bot_id}] page error: {exc}"))

            await page.goto(page_url, wait_until="domcontentloaded")
            logger.info(f"[Bot-{bot_id}] 已加载 recorder.html: {page_url}")

            # 模拟用户手势以激活 AudioContext（Chrome autoplay policy 要求）
            # 不点的话 audioContext.resume() 在无手势上下文中会被拒绝
            try:
                await page.click("body", timeout=2000)
                logger.info(f"[Bot-{bot_id}] 模拟 click 激活 AudioContext")
            except Exception as e:
                logger.warning(f"[Bot-{bot_id}] 模拟 click 失败（不影响后续）: {e}")

            self._browsers[bot_id] = BrowserHandle(
                bot_id=bot_id,
                browser=browser,
                context=context,
                page=page,
            )

    async def kill(self, bot_id: str) -> None:
        async with self._lock:
            handle = self._browsers.pop(bot_id, None)
            if handle is None:
                return
            try:
                await handle.page.close()
                await handle.context.close()
                await handle.browser.close()
            except Exception as e:
                logger.warning(f"[Bot-{bot_id}] kill 异常: {e}")

    async def shutdown(self):
        async with self._lock:
            for bot_id in list(self._browsers.keys()):
                await self.kill(bot_id)
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None


class BrowserHandle:
    """单个 Chromium 实例的句柄"""
    def __init__(self, bot_id: str, browser, context, page):
        self.bot_id = bot_id
        self.browser = browser
        self.context = context
        self.page = page
