import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'
import { compression } from 'vite-plugin-compression2'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // 生产环境分析包大小
    visualizer({
      open: false,
      gzipSize: true,
      brotliSize: true,
      filename: 'dist/stats.html',
    }),
    // Gzip 压缩
    compression({
      algorithm: 'gzip',
      threshold: 10240, // 只压缩大于 10KB 的文件
    }),
    // Brotli 压缩（更好的压缩率）
    compression({
      algorithm: 'brotliCompress',
      threshold: 10240,
    }),
  ],
  base: '/admin/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_BASE_URL || 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 目标浏览器
    target: 'es2015',
    // 代码分割优化
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true, // 生产环境移除 console
        drop_debugger: true,
      },
    },
    // 优化 chunk 大小
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        // 文件名哈希
        entryFileNames: `assets/[name]-[hash].js`,
        chunkFileNames: `assets/[name]-[hash].js`,
        assetFileNames: `assets/[name]-[hash].[ext]`,
        // 手动代码分割
        manualChunks: {
          // Vue 核心单独打包
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          // Element Plus 单独打包
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          // 图标库单独打包
          'icons': ['lucide-vue-next'],
          // 工具库单独打包
          'utils': ['axios', '@vueuse/core'],
        },
      },
    },
    // CSS 代码分割
    cssCodeSplit: true,
  },
  // 优化预加载
  optimizeDeps: {
    include: ['vue', 'vue-router', 'pinia', 'axios', 'element-plus'],
  },
})
