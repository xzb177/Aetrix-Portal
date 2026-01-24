<template>
  <div v-if="isEnabled" class="debug-overlay">
    <div class="debug-header">
      <span>🔍 Debug Overlay</span>
      <button @click="clearLogs" class="debug-btn">清空</button>
      <button @click="copyLogs" class="debug-btn">复制</button>
    </div>
    <div class="debug-content">
      <div class="debug-section">
        <strong>=== 环境信息 ===</strong>
        <div>BASE_URL: {{ importMetaEnvBaseUrl }}</div>
        <div>Location: {{ windowLocation }}</div>
        <div>User Agent: {{ navigatorUserAgent }}</div>
      </div>

      <div class="debug-section">
        <strong>=== 静态资源检测 ===</strong>
        <div v-for="(resource, idx) in resources.slice(0, 10)" :key="idx"
             :class="{'resource-error': resource.status === 404 || resource.status === 0}">
          [{{ resource.status }}] {{ resource.name }}
        </div>
      </div>

      <div class="debug-section">
        <strong>=== 路由守卫日志 ===</strong>
        <div v-for="(log, idx) in routerLogs.slice(-20)" :key="idx">{{ log }}</div>
      </div>

      <div class="debug-section">
        <strong>=== 认证状态 ===</strong>
        <div v-for="(log, idx) in authLogs.slice(-10)" :key="idx">{{ log }}</div>
      </div>

      <div class="debug-section">
        <strong>=== 错误捕获 ===</strong>
        <div v-for="(err, idx) in errors.slice(-5)" :key="idx" class="error-item">
          <div>{{ err.message }}</div>
          <div class="error-stack">{{ err.stack }}</div>
        </div>
      </div>

      <div class="debug-section">
        <strong>=== 404 资源 ===</strong>
        <div v-if="notFoundResources.length === 0">无</div>
        <div v-for="(url, idx) in notFoundResources" :key="idx" class="error-item">{{ url }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const isEnabled = ref(false)
const importMetaEnvBaseUrl = ref('')
const windowLocation = ref('')
const navigatorUserAgent = ref('')
const routerLogs = ref<string[]>([])
const authLogs = ref<string[]>([])
const errors = ref<Array<{message: string, stack: string}>>([])
const resources = ref<Array<{name: string, status: number}>>([])

// 计算出 404 的资源
const notFoundResources = computed(() => {
  return resources.value
    .filter(r => r.status === 404 || r.status === 0)
    .map(r => r.name)
})

// 检查是否启用调试模式 (?debug=1)
onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  isEnabled.value = params.has('debug') && params.get('debug') !== '0'

  // 环境信息
  importMetaEnvBaseUrl.value = (import.meta.env.BASE_URL || '未设置')
  windowLocation.value = window.location.href
  navigatorUserAgent.value = navigator.userAgent.substring(0, 100) + '...'

  // 检测静态资源 (Performance API)
  setTimeout(() => {
    const entries = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
    resources.value = entries.slice(0, 20).map(e => ({
      name: e.name.substring(0, 100),
      status: (e as any).transferSize === 0 ? 0 : 200 // 简单判断
    }))
  }, 1000)

  // 监听 404 资源
  const originalXhrOpen = XMLHttpRequest.prototype.open
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    this.addEventListener('load', function() {
      if (this.status === 404) {
        errors.value.push({
          message: `资源 404: ${url}`,
          stack: `XMLHttpRequest 404`
        })
      }
    })
    return originalXhrOpen.call(this, method, url, ...args)
  }

  // 监听 fetch 404
  const originalFetch = window.fetch
  window.fetch = function(...args) {
    return originalFetch.apply(this, args).then(response => {
      if (response.status === 404) {
        errors.value.push({
          message: `资源 404: ${args[0]}`,
          stack: `Fetch 404`
        })
      }
      return response
    })
  }
})

// 添加日志
const addRouterLog = (log: string) => {
  const timestamp = new Date().toLocaleTimeString()
  routerLogs.value.push(`[${timestamp}] ${log}`)
}

const addAuthLog = (log: string) => {
  const timestamp = new Date().toLocaleTimeString()
  authLogs.value.push(`[${timestamp}] ${log}`)
}

const addError = (message: string, stack: string) => {
  errors.value.push({ message, stack })
}

const clearLogs = () => {
  routerLogs.value = []
  authLogs.value = []
  errors.value = []
}

const copyLogs = () => {
  const text = `
=== Debug Overlay ===

环境信息:
BASE_URL: ${importMetaEnvBaseUrl.value}
Location: ${windowLocation.value}

路由守卫日志:
${routerLogs.value.join('\n')}

认证状态:
${authLogs.value.join('\n')}

错误:
${errors.value.map(e => e.message + '\n' + e.stack).join('\n\n')}

404 资源:
${notFoundResources.value.join('\n')}
  `.trim()

  navigator.clipboard.writeText(text).then(() => {
    alert('日志已复制到剪贴板')
  })
}

// 全局暴露方法供外部调用
;(window as any).__debugOverlay = {
  addRouterLog,
  addAuthLog,
  addError,
  clearLogs
}
</script>

<style scoped>
.debug-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.95);
  color: #0f0;
  font-family: monospace;
  font-size: 12px;
  z-index: 999999;
  padding: 10px;
  overflow: auto;
}

.debug-header {
  position: sticky;
  top: 0;
  background: #111;
  padding: 10px;
  border-bottom: 1px solid #0f0;
  display: flex;
  gap: 10px;
  align-items: center;
}

.debug-btn {
  background: #0f0;
  color: #000;
  border: none;
  padding: 4px 8px;
  cursor: pointer;
  font-family: monospace;
}

.debug-content {
  margin-top: 10px;
}

.debug-section {
  margin-bottom: 15px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid #333;
}

.debug-section strong {
  color: #ff0;
  display: block;
  margin-bottom: 5px;
}

.debug-section > div {
  margin: 2px 0;
  word-break: break-all;
}

.resource-error {
  color: #f55 !important;
  background: rgba(255, 0, 0, 0.1);
}

.error-item {
  color: #f55;
  margin: 5px 0;
  padding: 5px;
  background: rgba(255, 0, 0, 0.1);
}

.error-stack {
  font-size: 10px;
  opacity: 0.8;
  margin-top: 2px;
}
</style>
