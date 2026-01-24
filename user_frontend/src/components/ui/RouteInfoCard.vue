<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouteStore } from '@/stores/route'
import { useFeatureFlags } from '@/composables/useFeatureFlags'
import { useToast } from '@/composables/useToast'

const routeStore = useRouteStore()
const { ROUTE_CONFIG } = useFeatureFlags()
const toast = useToast()

const copying = ref(false)
const showFullDebug = ref(false)

// 是否显示线路信息（功能开关开启且有可用线路）
const shouldShow = computed(() => {
  return ROUTE_CONFIG.value && routeStore.hasRoutes
})

// 线路状态文本
const routeStatusText = computed(() => {
  if (!routeStore.selectedRoute) {
    return '未连接'
  }
  if (routeStore.isUsingDefault) {
    return '默认线路'
  }
  return '已分配'
})

// 线路状态颜色
const statusColor = computed(() => {
  if (!routeStore.selectedRoute) return 'text-gray-400'
  if (routeStore.isUsingDefault) return 'text-amber-400'
  return 'text-emerald-400'
})

// 复制诊断信息
async function copyDiagnostic() {
  copying.value = true
  try {
    const success = await routeStore.copyDebugInfo()
    if (success) {
      toast.success('诊断信息已复制到剪贴板')
    } else {
      toast.error('复制失败，请手动复制')
    }
  } finally {
    setTimeout(() => {
      copying.value = false
    }, 1000)
  }
}

// 刷新线路配置
async function refreshRoutes() {
  await routeStore.refresh()
  toast.success('线路配置已刷新')
}

// 重置失败记录
function resetFailed() {
  routeStore.resetFailedRecords()
  toast.success('失败记录已重置')
}

// 获取简短诊断信息
const shortDebugInfo = computed(() => {
  if (!routeStore.selectionResult) return ''
  const r = routeStore.selectionResult
  const route = routeStore.selectedRoute
  return `[${route?.id}] ${route?.name} | ${route?.domain} | bucket: ${r.bucket}`
})

onMounted(() => {
  // 初始化时获取线路配置
  if (ROUTE_CONFIG.value) {
    routeStore.fetchRoutes()
  }
})
</script>

<template>
  <div v-if="shouldShow" class="route-info-card">
    <!-- 简洁模式 -->
    <div class="route-info-compact">
      <div class="route-info-header">
        <div class="route-info-title">
          <span class="route-icon">🌐</span>
          <span class="route-label">当前线路</span>
          <span :class="['route-status', statusColor]">
            {{ routeStatusText }}
          </span>
        </div>
        <div class="route-info-actions">
          <button
            class="icon-btn"
            @click="showFullDebug = !showFullDebug"
            title="显示详细信息"
          >
            {{ showFullDebug ? '▲' : '▼' }}
          </button>
        </div>
      </div>

      <div v-if="routeStore.selectedRoute" class="route-info-content">
        <div class="route-info-row">
          <span class="route-info-label">线路名称</span>
          <span class="route-info-value">{{ routeStore.selectedRoute.name }}</span>
        </div>
        <div class="route-info-row">
          <span class="route-info-label">服务器</span>
          <span class="route-info-value route-domain">
            {{ routeStore.selectedRoute.domain }}
          </span>
        </div>
        <div v-if="routeStore.selectionResult" class="route-info-row">
          <span class="route-info-label">Hash Bucket</span>
          <span class="route-info-value">{{ routeStore.selectionResult.bucket }}/100</span>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-else-if="routeStore.loading" class="route-info-loading">
        <span class="spinner"></span>
        <span>检测最优线路...</span>
      </div>

      <!-- 错误状态 -->
      <div v-else class="route-info-error">
        <span>⚠️ 线路检测失败</span>
        <button class="retry-btn" @click="refreshRoutes">重试</button>
      </div>
    </div>

    <!-- 详细调试信息 -->
    <div v-if="showFullDebug" class="route-info-debug">
      <div class="debug-header">
        <span class="debug-title">诊断信息</span>
        <button
          :class="['copy-btn', { copying }]"
          @click="copyDiagnostic"
        >
          {{ copying ? '已复制' : '复制' }}
        </button>
      </div>

      <pre class="debug-content">{{ routeStore.getDebugInfo() }}</pre>

      <div class="debug-actions">
        <button class="action-btn" @click="refreshRoutes">
          🔄 刷新配置
        </button>
        <button class="action-btn" @click="resetFailed">
          🔃 重置失败记录
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.route-info-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  overflow: hidden;
}

.route-info-compact {
  padding: 16px;
}

.route-info-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.route-info-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.route-icon {
  font-size: 16px;
}

.route-label {
  color: rgba(255, 255, 255, 0.7);
}

.route-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.05);
}

.route-info-actions {
  display: flex;
  gap: 8px;
}

.icon-btn {
  background: rgba(255, 255, 255, 0.05);
  border: none;
  color: rgba(255, 255, 255, 0.5);
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
}

.route-info-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.route-info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.route-info-label {
  color: rgba(255, 255, 255, 0.5);
}

.route-info-value {
  color: rgba(255, 255, 255, 0.9);
}

.route-domain {
  font-family: monospace;
  color: #10b981;
}

.route-info-loading,
.route-info-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 8px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.retry-btn {
  padding: 4px 12px;
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 4px;
  color: #10b981;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.retry-btn:hover {
  background: rgba(16, 185, 129, 0.3);
}

.route-info-debug {
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding: 16px;
  background: rgba(0, 0, 0, 0.2);
}

.debug-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.debug-title {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
}

.copy-btn {
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.copy-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.copy-btn.copying {
  background: rgba(16, 185, 129, 0.2);
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.debug-content {
  margin: 0;
  padding: 12px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 6px;
  font-size: 11px;
  font-family: monospace;
  color: rgba(255, 255, 255, 0.7);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.debug-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.action-btn {
  flex: 1;
  padding: 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}
</style>
