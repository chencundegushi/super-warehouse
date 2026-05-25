/**
 * Vite 构建配置
 * 配置 React 插件、路径别名和后端 API 代理
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 禁用代理缓冲，确保 SSE 流式响应实时传递
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              // 确保不缓冲 SSE 响应
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['x-accel-buffering'] = 'no'
              // 禁用分块编码压缩，防止事件被合并
              delete proxyRes.headers['content-encoding']
            }
          })
        },
      },
    },
  },
})
