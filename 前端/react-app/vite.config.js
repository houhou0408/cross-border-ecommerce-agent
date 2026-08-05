import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置：
// - dev 模式跑在 5173，把 API 请求代理到 FastAPI(8000)
// - build 产物输出到 ../dist，由 FastAPI 直接托管（生产模式一键启动）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ask': 'http://localhost:8000',
      '/listing': 'http://localhost:8000',
      '/tariff': 'http://localhost:8000',
      '/currency': 'http://localhost:8000',
      '/stats': 'http://localhost:8000',
      '/health': 'http://localhost:8000'
    }
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true
  }
})
