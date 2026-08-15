import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8080'

  return {
    plugins: [
      react(),
      tailwindcss(),
    ],
    build: {
      chunkSizeWarningLimit: 900, // vendor chunk 按需加载，非首屏
      // P3-1: vendor 分包——共享依赖单独 chunk，首屏只加载核心 React
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return undefined;
            if (
              id.includes('react-markdown') ||
              id.includes('remark-') ||
              id.includes('react-syntax-highlighter') ||
              id.includes('refractor')
            ) {
              return 'vendor-markdown';
            }
            if (id.includes('recharts') || id.includes('victory') || id.includes('/d3-')) {
              return 'vendor-charts';
            }
            if (
              id.includes('/react/') ||
              id.includes('react-router') ||
              id.includes('zustand') ||
              id.includes('scheduler')
            ) {
              return 'vendor-react';
            }
            return undefined;
          },
        },
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true
        },
        '/admin/auth': {
          target: proxyTarget,
          changeOrigin: true
        },
        '/manage': {
          target: proxyTarget,
          changeOrigin: true
        }
      }
    }
  }
})
