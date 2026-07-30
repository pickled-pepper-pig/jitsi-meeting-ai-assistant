# 变更日志

本项目的所有重要变更都会记录在此文件中。

## [1.6.0] - 2026-07-30

### feat（新功能）
- 会议纪要历史共享：新加入者通过 HTTP + WS `room_state_snapshot` 双重兜底拉到进入前的全部历史（chat/summary/transcript）
- 静音与 AI 开关解耦：静音只控制本端音频上传，不影响 AI 启停；参会者 track 静音自动暂停上传
- transcript 持久化：`transcript_final` 写入 meeting_state，后加入者可见
- 参会者人数实时刷新：监听 `videoConferenceJoined` 事件兜底全量刷新
- 邀请链接图标化 + 旁观者视图 UI 紧凑化

### fix（修复）
- 多房间隔离加固：`_handle_audio` 强制从 `client.room_id` 取会话归属
- 修复 `NameError: client` 与 end_session 误清其他参会者操作者标记
- 修复 `_finalize_session_blocking` 用错事件循环导致旁观者收不到「停止 AI」状态
- 取消 transcript 广播按 userId 跳过操作者的逻辑（前端已有去重）
- 空 summary 不再持久化，避免占位消息残留
- 前端 ws 建连后先 join 再 create_session

### chore（维护）
- `ChatMessage.type` 扩展为 `text|system|summary|transcript`
- 清理旧 invite/旁观者视图样式

## [1.5.0] - 2026-07-30

### feat（新功能）
- Meeting Agent 基础设施：Playwright + Headless Chromium 控制的 Recorder Bot，模块化目录 `manager/browser/audio/participant`
- Bot 生命周期 API：`/api/meetings/{roomId}/bot/{spawn,kill,status}`，仅主持人可调用，Bot JWT 由服务端重签为 "AI Assistant"
- WebSocket 路径分发：`/ws/recorder/*` 走 Bot recorder receiver，与会议/ASR 通道隔离
- 房间级 AI 操作者去重：transcript 广播时按 userId 跳过操作者本人 ws，避免重复显示
- 中途加入者补发 `ai_bot_status`，让旁观者立刻看到当前是否在录音
- 前端多路远程音频接收器 `ParticipantAudioReceiver`：每个参会者一个 session + 一个 ws
- 前端 partial 转写实时显示（`meeting_transcript_partial` 事件）
- userId 解析顺序优化：localStorage 优先 → 后端主持人昵称匹配 → 临时生成，避免重连身份漂移
- 新增 `GET /api/meetings/{roomId}/moderator` 接口，供前端 join 前预判是否同人重连

### fix（修复）
- 移除代理/VPN 检测弹窗，健康检查失败时静默处理
- 修复 JVB 容器 IP 配置（172.18.0.4 → 172.18.0.2）

### chore（维护）
- 清理根目录误建的 `app/` 空目录（真实代码在 `silan-asr-service/app/meeting_agent/`）

## [1.4.0] - 2026-07-29

### feat（新功能）
- ASR 流式识别优化：整句累积不切碎、跨句自动加标点
- 房间级 AI Bot 状态广播：主持人开启后所有成员实时同步转写
- 主持人鉴权：一房一主持人，先到先得；JWT 带 XMPP affiliation 修复 participant 自动升级
- WebSocket 保活：每 25s ping/pong，断开自动停止 audio 计数
- 测试工具集：TTS 生成、wav 流式回放、单文件 + 批量 CER/WER 评估

### docs（文档）
- 新增 `DOCS.md`：项目架构、关键链路、核心实现要点

## [1.3.1] - 2026-07-28

### fix（修复）
- 修复 ASR 服务模型加载失败：funasr 升级到 1.3.30，模型切换到 paraformer-zh-streaming

### feat（新功能）
- 新增转写结果聚合器（按句合并 partial/final）
- 新增 PCM 转换与参与者音频接收模块
- 音频捕获支持实时电平监测和后端推送
- 前端新增邀请链接复制、iframe 权限补全

### chore（维护）
- 更新 JVB 配置和 Jitsi web 配置

## [1.3.0] - 2026-07-28

### feat（新功能）
- Recorder Bot Spike v3：模块化音轨捕获工具，5 步可视化验证流水线
- 核心链路打通：Jitsi 远程音轨 → MediaStream → AudioContext → PCM16 → WAV

## [1.2.1] - 2026-07-28

### feat（新功能）
- Recorder Bot Spike v2：改用 lib-jitsi-meet 低层 API 直接获取 MediaStreamTrack
- AudioContext 采样率自动检测 + 线性重采样到 16kHz

### fix（修复）
- 修复 bot.html 参数名 `room` → `roomId` 对齐后端

## [1.2.0] - 2026-07-28

### feat（新功能）
- Recorder Bot Spike 初版：基于 Jitsi IFrame API 实现音轨捕获

## [1.1.1] - 2026-07-28

### fix（修复）
- 统一端口配置：WebSocket 8080 / Flask 8082 / 前端 3000
- 修复 settings.py 与 main.py 默认端口不一致

### refactor（重构）
- ASR 文档与 .gitignore 合并到项目根目录
- 重写根 README 整合端口表、API 文档、ASR 服务详情

### docs（文档）
- README 新增端口配置表和 ASR 服务详情章节

## [1.1.0] - 2026-07-27

### feat（新功能）
- 后端迁移到 Python ASR 服务（silan-asr-service/）
  - FunASR Paraformer 流式推理 Worker（CPU）
  - WebSocket 音频网关（多会话并发）
  - 音频处理模块（重采样/降噪/VAD）
  - ASR 会话管理、转写结果分发
  - 半导体行业热词库（84 热词 + 62 术语）
- 新增前端音频采集服务和 Bot 加入页
- 旧 Node.js 后端（backend/ 11 文件）下线

### refactor（重构）
- 前后端 UI 组件和 WebSocket Hook 更新适配新协议
- Vite 配置支持 Jitsi iframe 代理

## [1.0.0] - 2026-07-24

### 初始版本
- Jitsi Meet iframe 集成
- 实时聊天展示
- Mock LLM 会议总结
- WebSocket 断线重连和消息同步
- 主持人/参会者角色区分
- 本地 Jitsi Docker 部署