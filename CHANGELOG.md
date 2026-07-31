# 变更日志

本项目的所有重要变更都会记录在此文件中。

## [1.8.0] - 2026-07-31

### feat（新功能）
- 名字查重：加入会议时检查房间内用户名是否被占用，避免重复
- 主持人创建会议时自动清空上一轮会议的历史纪要，所有参会者从空白开始
- 页面刷新自动重连：URL 带 room + name 时无需手动重新输入

### fix（修复）
- BotManager 复用单例 BrowserController，修复 kill 失效（之前每次 new 新实例导致 _browsers 字典为空）
- Bot 元数据持久化到 Redis，进程重启后标记 stale 并提示，避免误判"已有运行 Bot"
- recorder.html 注入 URL 的 room_url 用 full encode，修复 `://` 被破坏导致加入会议失败
- Bot 失败时显式标记 failed，避免 kill 走 noop 分支

### refactor（重构）
- 主持人不再启动本端 `AudioCaptureService`，统一由 Bot 在 Playwright 里采集所有参会者音频，避免重复 transcript
- 用户名冲突前端 alert 提示，区分 409（moderator_occupied / name_conflict）

### style（样式）
- sidebar 消息样式优化：头像、自定义滚动条、hover 阴影、summary 渐变背景

## [1.7.0] - 2026-07-31

### feat（新功能）
- 多 Speaker 转写：主持人端开 AI 后，Bot 自动接管所有参会者音频采集，sidebar 按 speaker 区分转写来源
- 主持人名字标注：主持人本地视角下自己的消息标注「（主持人）」
- Speaker 颜色区分：transcript 消息按 sender 名字哈希生成稳定莫兰迪色，左色条 + sender 同色
- 前端集成 Bot 生命周期：开/停止 AI 自动 spawn/kill 后端 Bot，无需手动 curl
- Bot recorder 兼容 Int16 PCM：检测到 Int16 自动 remap 到 Float32，避免 ASR 解析失败

### fix（修复）
- Bot 静态 tracks 不曝光问题：等 participantDisplayName 出现后再注册 ASR session，避免 "未知参与者"
- audioCapture `sendAudioChunk` 添加 maxAbs 调试日志，便于线上判断 mic 是静音还是有采集

### perf（性能）
- WS 主循环 audio_chunk 改为 fire-and-forget 投递线程池，解除多 session 串行等待 VAD/降噪导致的 wsLoopLag 飙升（2 并发 653ms → 60ms）

### test（测试）
- 新增 `tools/stress_test.py` 并发压测脚本：模拟 N 个 speaker 同时喂数据，监视 wsLoopLag / partials / finals

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