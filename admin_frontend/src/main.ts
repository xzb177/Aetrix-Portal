import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Element Plus - 用于 ElMessage 等基础组件
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'

// Design System V2 Tokens
import './styles/tokens.css'
import './styles/index.css'

// V2 响应式样式和 Element Plus 主题覆盖
import './styles/responsive.css'
import './styles/element-plus-theme.css'

// ============================================================
// 自诊断模式 - 全局错误捕获
// ============================================================

// 检查是否启用调试模式
const params = new URLSearchParams(window.location.search)
const isDebugEnabled = params.has('debug') && params.get('debug') !== '0'

// 创建 Debug Overlay 元素（在黑屏时也能显示）
if (isDebugEnabled) {
  const debugEl = document.createElement('div')
  debugEl.id = 'debug-overlay-container'
  debugEl.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:rgba(0,0,0,0.95);color:#0f0;font-family:monospace;font-size:12px;padding:10px;max-height:300px;overflow:auto;max-width:500px;'
  document.documentElement.appendChild(debugEl)

  const addDebugInfo = (msg: string) => {
    const div = document.createElement('div')
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`
    debugEl.appendChild(div)
    console.log('[Debug]', msg)
  }

  // 环境信息
  addDebugInfo('=== 环境信息 ===')
  addDebugInfo(`BASE_URL: ${import.meta.env.BASE_URL || '(未设置)'}`)
  addDebugInfo(`Location: ${window.location.href}`)
  addDebugInfo(`Origin: ${window.location.origin}`)

  // 检测静态资源路径
  addDebugInfo('=== 静态资源 ===')
  const scripts = document.querySelectorAll('script[src]')
  scripts.forEach((s, i) => {
    addDebugInfo(`script[${i}]: ${(s as HTMLScriptElement).src}`)
  })
  const links = document.querySelectorAll('link[href]')
  links.forEach((l, i) => {
    if (i < 5) {
      addDebugInfo(`link[${i}]: ${(l as HTMLLinkElement).href}`)
    }
  })

  // 暴露全局方法
  ;(window as any).__addDebugLog = addDebugInfo
}

// 1. window.onerror 捕获
window.onerror = (message, source, lineno, colno, error) => {
  const msg = `ERROR: ${message} at ${source}:${lineno}:${colno}`
  console.error('[Global onerror]', msg, error)
  if (isDebugEnabled && (window as any).__addDebugLog) {
    ;(window as any).__addDebugLog(msg)
  }
  // 创建错误显示到页面
  const errorDiv = document.createElement('div')
  errorDiv.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#f00;color:#fff;padding:20px;max-width:80%;z-index:999999;font-family:monospace;white-space:pre-wrap;'
  errorDiv.textContent = msg + '\n\n' + (error?.stack || '')
  document.body.appendChild(errorDiv)
  return false
}

// 2. window.onunhandledrejection 捕获
window.onunhandledrejection = (event) => {
  const msg = `Unhandled Rejection: ${event.reason}`
  console.error('[Global onunhandledrejection]', msg)
  if (isDebugEnabled && (window as any).__addDebugLog) {
    ;(window as any).__addDebugLog(msg)
  }
  const errorDiv = document.createElement('div')
  errorDiv.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#f00;color:#fff;padding:20px;max-width:80%;z-index:999998;font-family:monospace;white-space:pre-wrap;'
  errorDiv.textContent = msg
  document.body.appendChild(errorDiv)
}

// 监听资源加载错误
window.addEventListener('error', (event) => {
  if (event.target !== window) {
    const target = event.target as HTMLElement
    const src = target.getAttribute('src') || target.getAttribute('href')
    const msg = `资源加载失败 (404): ${src}`
    console.error('[Resource Error]', msg)
    if (isDebugEnabled && (window as any).__addDebugLog) {
      ;(window as any).__addDebugLog(msg)
    }
  }
}, true)

// 监听 404 资源请求 (使用 PerformanceObserver)
if ('PerformanceObserver' in window) {
  const observer = new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      const resource = entry as any
      if (resource.transferSize === 0 && resource.duration > 0) {
        const msg = `可能的 404 资源: ${resource.name}`
        if (isDebugEnabled && (window as any).__addDebugLog) {
          ;(window as any).__addDebugLog(msg)
        }
      }
    }
  })
  try {
    observer.observe({ entryTypes: ['resource'] })
  } catch (e) {
    console.log('[Debug] PerformanceObserver error:', e)
  }
}

const app = createApp(App)

// 3. Vue app.config.errorHandler 捕获
app.config.errorHandler = (err, instance, info) => {
  const msg = `Vue Error: ${err} (${info})`
  console.error('[Vue errorHandler]', err, info)
  if (isDebugEnabled && (window as any).__addDebugLog) {
    ;(window as any).__addDebugLog(msg)
  }
}

// ============================================================
// 全局 Loading 管理
// ============================================================

// 获取 app 元素并确保 loading 类存在
const appEl = document.getElementById('app')
if (!appEl) {
  console.error('[Loading] #app element not found!')
} else {
  // index.html 中已经有 loading 类了，不需要再次添加
  console.log('[Loading] #app element found, current classes:', appEl.className)
}

// 清除 loading 状态的函数
const clearLoading = () => {
  const el = document.getElementById('app')
  if (el) {
    // 强制移除 loading 类，无论当前状态如何
    el.classList.remove('loading')
    console.log('[Loading] Loading class removed, current classes:', el.className)
  } else {
    console.warn('[Loading] #app element not found when trying to clear loading')
  }
}

// Watchdog：15秒后强制清除 loading
let watchdogTimer: ReturnType<typeof setTimeout> | null = setTimeout(() => {
  console.warn('[Loading] Watchdog triggered - loading not cleared after 15s, forcing reset')
  clearLoading()
}, 15000)

// ============================================================
// Pinia & Router & Element Plus
// ============================================================

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// ============================================================
// 挂载应用
// ============================================================

try {
  app.mount('#app')

  // 挂载成功后立即清除 loading（DOM class）
  clearLoading()

  // 兜底：强制停止 loading store
  // 注意：这里需要在 Pinia 初始化后才能访问 store
  // 使用 setTimeout 确保在下一个 tick 执行
  setTimeout(() => {
    try {
      const pinia = app.config.globalProperties.$pinia
      if (pinia) {
        const { useLoadingStore } = require('./stores/loading')
        const loadingStore = useLoadingStore(pinia)
        loadingStore.ensureStopped('app.mounted')
      }
    } catch (e) {
      // store 可能还未初始化，忽略
    }
  }, 0)

  // 清除 watchdog
  if (watchdogTimer) {
    clearTimeout(watchdogTimer)
    watchdogTimer = null
  }

  // 挂载成功日志
  console.log('[App] Vue app mounted successfully')
  if (isDebugEnabled && (window as any).__addDebugLog) {
    ;(window as any).__addDebugLog('Vue app mounted ✓')
  }
} catch (error) {
  console.error('[App] Failed to mount Vue app:', error)
  // 即使挂载失败也要清除 loading，让用户能看到错误
  clearLoading()
}
