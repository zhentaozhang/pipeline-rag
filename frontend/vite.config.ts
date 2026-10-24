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
      // 首屏不允许再出现 >400 kB 的 chunk：最大的图表库已经被关在
      // AdminMetricsView 这个懒加载路由里（约 357 kB），再大就说明分包退化了。
      chunkSizeWarningLimit: 400,
      rollupOptions: {
        output: {
          // P4 分包：按"依赖链"分组，且只对**首屏必须的**依赖分组。
          //
          // 关键约束（rolldown/vite 8 的行为，实测）：manualChunks 返回的分组会把
          // 该组模块的共享依赖一起卷进同一个 chunk。所以一旦给 recharts 单独建组，
          // 它依赖的 react / react-dom / clsx 就全落进 vendor-charts，
          // 而 vendor-charts 会被入口静态 import → 图表库被 modulepreload 到首屏
          //（改动前就是这样：index.html 里预加载了 357 kB 的图表库）。
          // 现在不给 recharts 建组：它只被懒加载的 AdminMetricsView 引用，
          // 自然落在那个路由 chunk 里，聊天页永远不会加载它。
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return undefined;
            // react-dom 单独成块：体积最大（~178 kB）且发版频率最低，
            // 业务代码更新时它可以继续命中缓存。
            if (id.includes('/react-dom/')) {
              return 'vendor-react-dom';
            }
            if (
              id.includes('/react/') ||
              id.includes('react-router') ||
              id.includes('zustand') ||
              id.includes('scheduler')
            ) {
              return 'vendor-react';
            }
            // 语法高亮（prism + 11 种语言）与 markdown 解析是两条独立依赖链，
            // 拆开后各自都 <140 kB，可以并行下载，缓存粒度也更细。
            if (
              id.includes('react-syntax-highlighter') ||
              id.includes('refractor') ||
              id.includes('prismjs') ||
              id.includes('highlight.js')
            ) {
              return 'vendor-highlight';
            }
            if (
              id.includes('react-markdown') ||
              id.includes('remark-') ||
              id.includes('micromark') ||
              id.includes('mdast-') ||
              id.includes('hast-') ||
              id.includes('unified') ||
              id.includes('unist-') ||
              id.includes('vfile')
            ) {
              return 'vendor-markdown';
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
