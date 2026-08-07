import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'
import { fileURLToPath, URL } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const keyPath = path.join(__dirname, 'localhost+3-key.pem')
const certPath = path.join(__dirname, 'localhost+3.pem')
const useSsl = fs.existsSync(keyPath) && fs.existsSync(certPath)

// Flask HTTP API (后台线程，端口 19089，避免与 Jitsi JVB 19088 冲突)
const FLASK_TARGET = 'http://127.0.0.1:19089'
// WebSocket 服务 (主线程，端口 19087)
const WS_TARGET = 'http://127.0.0.1:19087'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 19307,
    strictPort: false,
    https: useSsl ? {
      key: fs.readFileSync(keyPath),
      cert: fs.readFileSync(certPath),
    } : undefined,
    proxy: {
      // HTTP API → Flask (19089)
      '/api': {
        target: FLASK_TARGET,
        changeOrigin: true,
        secure: false,
      },
      '/health': {
        target: FLASK_TARGET,
        changeOrigin: true,
        secure: false,
      },
      // WebSocket 升级 → WebSocket 服务 (19087)
      // 原生 WebSocket 连接会走这个代理
      '/ws': {
        target: WS_TARGET,
        changeOrigin: true,
        ws: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/ws/, ''),
      },
    },
  },
})
