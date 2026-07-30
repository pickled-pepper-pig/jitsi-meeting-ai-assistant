"""Meeting Agent - 会议 AI 智能体

接管 Jitsi 会议的"听觉/听觉接管"：
- 主持人在前端点击「开启 AI 助手」
- Bot Manager 拉起一个 Headless Chromium（Playwright 控制）
- Chromium 加载 Jitsi Meet，作为隐藏参会者加入会议
- 注入 JS：监听 TRACK_ADDED → AudioContext → PCM16 → WebSocket 推 Python
- Python 接 PCM → 落 wav + 推 ASR 实时转写

模块划分：
- manager/    生命周期：spawn / kill / health check
- browser/    Playwright 控制器 + 浏览器端 JS（注入 lib-jitsi-meet）
- audio/      WebSocket 接收 + wav 落盘 + 重采样
- participant/  participant_id ↔ speaker_id 映射
"""
