import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发环境启用 DevTools
const isDevToolsEnabled = process.env.NODE_ENV !== 'production'

export default defineConfig({
  plugins: [
    vue(),
    // 生产环境禁用 DevTools，减小体积
    ...(isDevToolsEnabled ? [
      (await import('vite-plugin-vue-devtools')).default()
    ] : []),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  build: {
    // 启用 CSS 代码分割
    cssCodeSplit: true,
    // 设置 chunk 大小警告限制 (KB)
    chunkSizeWarningLimit: 30,
    // 使用 esbuild 压缩（更快）
    minify: 'esbuild',
    // Rollup 配置
    rollupOptions: {
      output: {
        // 手动分包策略
        manualChunks(id) {
          // Vue 核心库打包在一起
          if (id.includes('node_modules/vue/') || id.includes('node_modules/@vue/') || id.includes('node_modules/pinia/') || id.includes('node_modules/vue-router/')) {
            return 'vue-vendor'
          }
          // UI 图标库单独打包
          if (id.includes('node_modules/lucide-vue-next')) {
            return 'icons'
          }
          // axios 单独打包
          if (id.includes('node_modules/axios')) {
            return 'utils'
          }
        },
        // chunk 文件命名（使用默认格式）
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
    // 禁用源码映射
    sourcemap: false,
  },
  // CSS 配置
  css: {
    devSourcemap: false,
  },
  // 优化依赖预构建
  optimizeDeps: {
    include: ['vue', 'vue-router', 'pinia', 'lucide-vue-next'],
  },
  // 服务器配置
  server: {
    port: 5173,
    host: true,
  },
})
