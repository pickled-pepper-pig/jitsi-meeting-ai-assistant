# 变更日志

本项目的所有重要变更都会记录在此文件中。

## [1.3.1] - 2026-07-28

### fix（修复）
- 修复 silan-asr-service 模型加载失败：升级 funasr 1.3.14 → 1.3.30，模型名改为 `paraformer-zh-streaming`
- 相关文件：silan-asr-service/app/config/settings.py

### feat（新功能）
- 新增转写结果聚合器（transcript_aggregator.py）
- 新增 PCM 转换模块（pcmConverter.ts）
- 新增参与者音频接收模块（participantAudioReceiver.ts）
- 音频捕获服务支持实时电平监测和后端推送
- 前端新增邀请链接复制功能
- Jitsi iframe 补全 allow 权限（microphone、camera、fullscreen、autoplay、display-capture）
- 相关文件：silan-asr-service/app/audio_gateway/transcript_aggregator.py, frontend/src/services/pcmConverter.ts, frontend/src/services/participantAudioReceiver.ts, frontend/src/services/audioCapture.ts, frontend/src/services/audioTypes.ts, frontend/src/App.tsx, frontend/src/App.css, frontend/src/components/Sidebar.tsx

### chore（维护）
- 更新 JVB 配置和 Jitsi web 配置
- 相关文件：jitsi/jitsi-meet-cfg/jvb/jvb.conf, frontend/src/config.ts

## [1.3.0] - 2026-07-28

### feat（新功能）
- Recorder Bot Spike v3: 完整重写 Spike 验证工具，实现模块化架构
  - 新增 `pcmConverter.ts` 模块: PCM16 转换、重采样、WAV 编码/下载工具
  - 新增 `participantAudioReceiver.ts` 模块: 接收 Jitsi 远程音轨的核心管道
    - 订阅 `TRACK_ADDED` 事件获取 `MediaStreamTrack`
    - 自动检测 AudioContext 采样率并进行线性重采样（目标 16kHz）
    - 支持实时音频电平监测和捕获状态管理
    - 预留后端 WebSocket 音频推送接口（`sendToBackend` 选项）
  - 重构 `bot.html`: 5 步验证流水线可视化 UI
    - Step 1: 加入会议 → Step 2: 监听 TRACK_ADDED → Step 3: MediaStream → AudioContext → Step 4: PCM16 转换 → Step 5: 保存 WAV
    - 实时音频电平表显示每个参与者的音量
    - 按参与者独立保存 WAV 文件（支持离线 FunASR 验证）
  - 核心验证链路: `Jitsi Track → MediaStream → AudioContext → PCM16 → WAV`
  - 架构方向: 浏览器 Spike 验证通过后 → Node.js Bot MVP

## [1.2.1] - 2026-07-28

### feat（新功能）
- Recorder Bot Spike v2: 改用 lib-jitsi-meet 低层 API 替代 Jitsi IFrame API
  - 直接使用 `JitsiConnection` + `JitsiConference` 建立 XMPP WebSocket 连接
  - 通过 `TRACK_ADDED` / `TRACK_REMOVED` 事件直接获取远程音轨的 `MediaStreamTrack`
  - 实现 AudioContext 采样率自动检测 + 线性重采样回退（16kHz 目标）
  - 修复 IFrame API 无法获取 `MediaStreamTrack` 的限制

### fix（修复）
- 修复 bot.html API 参数名 `room` → `roomId`（与后端 API 对齐）

## [1.2.0] - 2026-07-28

### feat（新功能）
- Recorder Bot Spike: 初版 bot.html，基于 Jitsi IFrame API 实现音轨捕获

## [1.1.1] - 2026-07-28

### fix（修复）
- 统一端口配置：后端 WebSocket → 8080，Flask API → 8082，前端 → 3000
- 修复 settings.py 和 main.py 默认端口不一致问题

### refactor（重构）
- 移除 silan-asr-service/.gitignore，Python 忽略规则合并至根 .gitignore
- 移除 silan-asr-service/README.md，ASR 文档合并至根 README.md
- 重写根 README.md：统一端口表、整合 API 文档和 ASR 服务详情、修正所有端口引用

### docs（文档）
- README.md 新增端口配置表、ASR 服务详情章节
- README.md 中所有 API 地址改为 8082

## [1.1.0] - 2026-07-27

### feat（新功能）
- 迁移后端至 Python ASR 服务（`silan-asr-service/`）
  - 新增 FunASR Paraformer 流式推理 Worker（CPU 推理）
  - 新增 WebSocket 音频网关（支持多会话并发）
  - 新增音频处理模块（重采样、降噪、VAD）
  - 新增 ASR 会话管理器（创建/销毁/断线重连）
  - 新增转写结果分发服务
  - 新增半导体行业热词加载（84 热词 + 62 行业术语）
- 新增前端音频采集服务（`frontend/src/services/audioCapture.ts`）
- 新增 Bot 加入页面（`frontend/public/bot.html`）

### refactor（重构）
- 删除旧 Node.js 后端（`backend/` 目录，共 11 个文件）
- 更新前端 UI 组件（App.css、App.tsx、Sidebar.tsx）
- 更新 WebSocket Hook 支持音频转写事件
- 更新 Vite 配置支持 Jitsi iframe 代理
- 更新 JVB 配置

### feat（新功能）- 历史
- JWT 认证升级为 RS256 非对称签名
- 新增 AI Gateway 模块（会议生命周期管理、权限校验、Bot 管理）
- 新增 Redis Meeting State（支持 Redis + 内存降级）
- 添加 RSA 密钥对生成
- 添加 Jitsi 启动脚本中的 IP 自动检测
- 添加前端启动脚本中的 IP 自动检测
- 添加 JWT token 传递给 JitsiMeeting 组件

### fix（修复）
- 修复 IP 地址变化导致的 Jitsi 连接问题
- 修复 Jitsi external_api.js 的 Vite 代理配置
- 修复动态 IP 地址的证书生成问题

### docs（文档）
- 添加项目文档 README.md
- 创建 Jitsi 配置示例 .env.example
- 创建 Git 忽略规则 .gitignore
- 创建 commit-logger skill（自动更新 changelog、gitignore、readme）

### chore（维护）
- 更新 start.sh，IP 变化时自动更新 .env 和证书
- 更新 package.json 使用自定义启动脚本
- 添加 redis 依赖

## [1.0.0] - 2026-07-24

### 初始版本
- Jitsi Meet iframe 集成
- 实时聊天展示
- Mock LLM 会议总结
- WebSocket 断线重连和消息同步
- 主持人/参会者角色区分
- 本地 Jitsi Docker 部署