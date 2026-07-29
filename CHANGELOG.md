# 变更日志

本项目的所有重要变更都会记录在此文件中。

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