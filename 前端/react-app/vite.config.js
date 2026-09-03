import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置：
// - dev 模式跑在 5173，把 API 请求代理到 FastAPI(8000)
// - build 产物输出到 ../dist，由 FastAPI 直接托管（生产模式一键启动）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      [
        '/ask',
        '/listing',
        '/tariff',
        '/currency',
        '/stats',
        '/health',
        '/auth',
        '/sessions',
        '/collection',
        '/kb',
        '/eval',
        '/video',
        '/image',
        '/support'
      ].map((p) => [p, 'http://127.0.0.1:8000'])
    )
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true
  }
})
