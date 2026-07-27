# 变更日志

本项目的所有重要变更都会记录在此文件中。

## [未发布]

### feat（新功能）
- 添加 Jitsi 启动脚本中的 IP 自动检测（`jitsi/start.sh`）
- 添加前端启动脚本中的 IP 自动检测（`frontend/scripts/start-dev.sh`）
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

## [1.0.0] - 2026-07-24

### 初始版本
- Jitsi Meet iframe 集成
- 实时聊天展示
- Mock LLM 会议总结
- WebSocket 断线重连和消息同步
- 主持人/参会者角色区分
- 本地 Jitsi Docker 部署