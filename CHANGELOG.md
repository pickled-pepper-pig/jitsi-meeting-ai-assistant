# 变更日志

本项目的所有重要变更都会记录在此文件中。

## [1.1.0]

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