# 🤖 Meeting AI Assistant

集成 Jitsi Meet 视频会议的 AI 助手，提供实时聊天展示和会议总结功能。

---

## ✨ 功能

- **实时聊天**：捕获并同步 Jitsi 会议聊天消息
- **会议总结**：主持人一键生成会议纪要
- **断线重连**：WebSocket 自动重连 + 消息补齐
- **角色权限**：主持人/参会者区分
- **本地部署**：Docker 一键部署 Jitsi

---

## 🛠️ 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 前端 | React + Vite | 18.2 / 5.0 |
| 后端 | Express + ws | 4.18 / 8.16 |
| 认证 | JWT | 9.0 |
| 视频 | Jitsi Meet | - |
| 语言 | TypeScript | 5.3 |

---

## 📁 结构

```
meeting-ai-assistant/
├── backend/          # Express + WebSocket 服务
├── frontend/         # React 前端应用
├── jitsi/            # 本地 Jitsi Docker 部署
├── CHANGELOG.md      # 变更日志
└── README.md
```

---

## 🚀 快速开始

### 启动服务

```bash
# 后端 (端口 8080)
cd backend && npm install && npm run dev

# 前端 (端口 3000)
cd frontend && npm install && npm run dev

# 本地 Jitsi (端口 8443)
cd jitsi && cp .env.example .env && ./start.sh
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | https://localhost:3000 |
| 后端 | http://localhost:8080 |
| Jitsi | https://localhost:8443 |

---

## 🔧 配置

### 切换 Jitsi 服务

编辑 `frontend/src/config.ts`：

```typescript
export const CURRENT_JITSI = 'local'; // 'public' | 'local'
```

- `public`: 使用 meet.jit.si（5分钟限制）
- `local`: 使用本地 Docker 部署

---

## 📄 许可证

MIT License

---

## 📌 Phase 2 待办

- [ ] 真实 Jitsi JWT 认证
- [ ] 接入真实 LLM 服务
- [ ] Recorder Bot 获取个人音频轨道
- [ ] Streaming ASR 实时转写
- [ ] 对象存储集成