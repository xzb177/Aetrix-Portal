<script setup lang="ts">
/**
 * BridgeDebugSheet - 舰桥调试模式面板
 *
 * 隐藏彩蛋：长按 Holo-ID 身份卡 1 秒触发
 *
 * 功能：
 * - 环境信息展示
 * - 性能概览（页面渲染耗时、刷新时间）
 * - 缓存概览（localStorage 统计）
 * - Feature Flags 状态
 * - 线路信息
 * - 复制诊断信息
 * - 刷新页面
 */
import { ref, computed, onMounted, watch } from 'vue'
import { Copy, RefreshCw, X, Cpu, HardDrive, Zap, Network, Flag, Shield, Info } from 'lucide-vue-next'
import BottomSheet from '@/components/ui/BottomSheet.vue'
import { useToast } from '@/composables/useToast'
import type { FeatureFlagConfig } from '@/config/featureFlags'

interface Props {
  show: boolean
  featureFlags?: FeatureFlagConfig
  pageLoadTime?: number
}

interface Emits {
  (e: 'update:show', value: boolean): void
  (e: 'refresh'): void
}

const props = withDefaults(defineProps<Props>(), {
  show: false,
  pageLoadTime: 0
})

const emit = defineEmits<Emits>()
const toast = useToast()

// ==================== 调试数据 ====================

// 环境信息
const envInfo = ref({
  domain: '',
  userAgent: '',
  language: '',
  timezone: '',
  buildVersion: 'v1.0.0',
  buildEnv: 'production'
})

// 性能数据
const perfInfo = ref({
  renderTime: 0,
  refreshTime: '',
  memoryUsage: 0
})

// 缓存数据
const cacheInfo = ref({
  keyCount: 0,
  estimatedSize: 0,
  keys: [] as string[]
})

// 线路信息（模拟数据，实际从 API 或配置获取）
const lineInfo = ref({
  current: '自动选择',
  recommended: '暂无数据',
  latency: 0
})

// ==================== 计算属性 ====================

// 敏感字段遮罩
const maskValue = (value: string, visibleLast = 4): string => {
  if (!value) return '-'
  if (value.length <= visibleLast) return '*'.repeat(value.length)
  return '*'.repeat(value.length - visibleLast) + value.slice(-visibleLast)
}

// 格式化文件大小
const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return (bytes / Math.pow(k, i)).toFixed(i > 0 ? 2 : 0) + ' ' + sizes[i]
}

// 格式化时间
const formatTime = (ms: number): string => {
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

// 获取页面加载性能
const getPagePerformance = () => {
  if (typeof window === 'undefined' || !window.performance) return 0

  const perfData = window.performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming
  if (!perfData) return 0

  // DOM 渲染完成时间
  return perfData.domContentLoadedEventEnd - perfData.fetchStart
}

// 获取内存使用情况（如果可用）
const getMemoryUsage = (): number => {
  if (typeof window !== 'undefined' && 'memory' in performance) {
    const mem = (performance as any).memory
    return mem.usedJSHeapSize ? mem.usedJSHeapSize / 1024 / 1024 : 0
  }
  return 0
}

// 计算 localStorage 大小
const calculateLocalStorageSize = (): { count: number; size: number; keys: string[] } => {
  if (typeof window === 'undefined') {
    return { count: 0, size: 0, keys: [] }
  }

  let totalSize = 0
  const keys: string[] = []

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key) {
      const value = localStorage.getItem(key) || ''
      totalSize += key.length + value.length
      keys.push(key)
    }
  }

  return { count: keys.length, size: totalSize, keys }
}

// ==================== 诊断信息生成 ====================

const generateDiagnosticInfo = (): string => {
  const timestamp = new Date().toISOString()
  const flagList = props.featureFlags
    ? Object.entries(props.featureFlags)
        .map(([k, v]) => `  ${k}: ${v}`)
        .join('\n')
    : '  (无)'

  // 遮罩敏感信息
  const maskedDomain = envInfo.value.domain ? maskValue(envInfo.value.domain, 8) : '-'
  const maskedKeys = cacheInfo.value.keys
    .filter(k => !k.includes('token') && !k.includes('password') && !k.includes('secret'))
    .slice(0, 10)

  return `=== 舰桥诊断信息 ===
生成时间: ${timestamp}

【环境信息】
域名: ${maskedDomain}
语言: ${envInfo.value.language || '-'}
时区: ${envInfo.value.timezone || '-'}
版本: ${envInfo.value.buildVersion}

【性能概览】
渲染耗时: ${formatTime(perfInfo.value.renderTime)}
内存占用: ${perfInfo.value.memoryUsage > 0 ? `${perfInfo.value.memoryUsage.toFixed(2)} MB` : '不支持'}

【缓存概览】
存储项数: ${cacheInfo.value.keyCount}
估算大小: ${formatBytes(cacheInfo.value.estimatedSize)}

【Feature Flags】
${flagList}

【线路信息】
当前线路: ${lineInfo.value.current}
推荐线路: ${lineInfo.value.recommended}

【存储键列表】(部分)
${maskedKeys.map(k => `  - ${k}`).join('\n')}

=== 诊断结束 ===`
}

// ==================== 操作方法 ====================

// 复制诊断信息
const copyDiagnosticInfo = async () => {
  try {
    const info = generateDiagnosticInfo()
    await navigator.clipboard.writeText(info)
    toast.success('诊断信息已复制到剪贴板')
  } catch (err) {
    // 降级方案
    try {
      const textarea = document.createElement('textarea')
      textarea.value = generateDiagnosticInfo()
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      toast.success('诊断信息已复制')
    } catch {
      toast.error('复制失败')
    }
  }
}

// 刷新页面
const refreshPage = () => {
  emit('refresh')
  location.reload()
}

// 关闭面板
const close = () => {
  emit('update:show', false)
}

// ==================== 数据初始化 ====================

const initDebugInfo = () => {
  if (typeof window === 'undefined') return

  // 环境信息
  envInfo.value = {
    domain: window.location.hostname,
    userAgent: navigator.userAgent,
    language: navigator.language,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    buildVersion: import.meta.env.VITE_APP_VERSION || 'v1.0.0',
    buildEnv: import.meta.env.MODE || 'production'
  }

  // 性能信息
  perfInfo.value = {
    renderTime: props.pageLoadTime || getPagePerformance(),
    refreshTime: new Date().toLocaleString('zh-CN'),
    memoryUsage: getMemoryUsage()
  }

  // 缓存信息
  const cacheData = calculateLocalStorageSize()
  cacheInfo.value = {
    keyCount: cacheData.count,
    estimatedSize: cacheData.size,
    keys: cacheData.keys
  }
}

// 监听显示状态，每次打开时刷新数据
watch(() => props.show, (isShow) => {
  if (isShow) {
    initDebugInfo()
  }
})

onMounted(() => {
  initDebugInfo()
})
</script>

<template>
  <BottomSheet
    :show="show"
    @update:show="close"
    :max-height="'80vh'"
    close-on-mask-click
    close-on-swipe-down
  >
    <template #default>
      <!-- 自定义头部 -->
      <div class="debug-sheet-header">
        <div class="debug-title-row">
          <div class="debug-icon">
            <Shield :size="20" />
          </div>
          <div>
            <h3 class="debug-title">舰桥调试模式</h3>
            <p class="debug-subtitle">Bridge Debug Sheet</p>
          </div>
        </div>
        <button class="debug-close" @click="close">
          <X :size="18" />
        </button>
      </div>

      <!-- 内容区域 -->
      <div class="debug-content">
        <!-- A) 环境信息 -->
        <section class="debug-section">
          <div class="section-header">
            <Cpu :size="16" class="section-icon" />
            <span class="section-title">环境信息</span>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">域名</span>
              <span class="info-value">{{ maskValue(envInfo.domain, 8) || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">环境</span>
              <span class="info-value">{{ envInfo.buildEnv }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">版本</span>
              <span class="info-value">{{ envInfo.buildVersion }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">语言</span>
              <span class="info-value">{{ envInfo.language }}</span>
            </div>
          </div>
        </section>

        <!-- B) 性能概览 -->
        <section class="debug-section">
          <div class="section-header">
            <Zap :size="16" class="section-icon" />
            <span class="section-title">性能概览</span>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">渲染耗时</span>
              <span class="info-value">{{ formatTime(perfInfo.renderTime) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">内存占用</span>
              <span class="info-value">
                {{ perfInfo.memoryUsage > 0 ? `${perfInfo.memoryUsage.toFixed(2)} MB` : '不支持' }}
              </span>
            </div>
            <div class="info-item full-width">
              <span class="info-label">最近刷新</span>
              <span class="info-value">{{ perfInfo.refreshTime }}</span>
            </div>
          </div>
        </section>

        <!-- C) 缓存概览 -->
        <section class="debug-section">
          <div class="section-header">
            <HardDrive :size="16" class="section-icon" />
            <span class="section-title">缓存概览</span>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">存储项</span>
              <span class="info-value">{{ cacheInfo.keyCount }} 个</span>
            </div>
            <div class="info-item">
              <span class="info-label">估算大小</span>
              <span class="info-value">{{ formatBytes(cacheInfo.estimatedSize) }}</span>
            </div>
          </div>
        </section>

        <!-- D) Flags 状态 -->
        <section v-if="featureFlags" class="debug-section">
          <div class="section-header">
            <Flag :size="16" class="section-icon" />
            <span class="section-title">Feature Flags</span>
          </div>
          <div class="flags-list">
            <div
              v-for="(value, key) in featureFlags"
              :key="key"
              class="flag-item"
              :class="{ 'flag-active': value }"
            >
              <span class="flag-name">{{ key }}</span>
              <span class="flag-status" :class="value ? 'status-on' : 'status-off'">
                {{ value ? 'ON' : 'OFF' }}
              </span>
            </div>
          </div>
        </section>

        <!-- E) 线路信息 -->
        <section class="debug-section">
          <div class="section-header">
            <Network :size="16" class="section-icon" />
            <span class="section-title">线路信息</span>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">当前线路</span>
              <span class="info-value">{{ lineInfo.current }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">推荐线路</span>
              <span class="info-value">{{ lineInfo.recommended }}</span>
            </div>
          </div>
        </section>

        <!-- 提示信息 -->
        <div class="debug-tip">
          <Info :size="12" />
          <span>所有敏感信息已遮罩处理</span>
        </div>
      </div>

      <!-- 底部操作按钮 -->
      <div class="debug-actions">
        <button class="debug-btn debug-btn-secondary" @click="copyDiagnosticInfo">
          <Copy :size="16" />
          <span>复制诊断信息</span>
        </button>
        <button class="debug-btn debug-btn-primary" @click="refreshPage">
          <RefreshCw :size="16" />
          <span>刷新页面</span>
        </button>
      </div>

      <!-- 安全区域 -->
      <div class="debug-safe-area"></div>
    </template>
  </BottomSheet>
</template>

<style scoped>
/* ==================== 自定义头部 ==================== */
.debug-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md, 16px);
  padding-bottom: var(--space-sm, 12px);
  border-bottom: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
}

.debug-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 12px);
}

.debug-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--neo-radius-sm, 12px);
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(5, 150, 105, 0.1) 100%);
  border: 1px solid rgba(16, 185, 129, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-primary, #10B981);
}

.debug-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  margin: 0;
  line-height: 1.2;
}

.debug-subtitle {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin: 2px 0 0 0;
  font-family: ui-monospace, monospace;
  letter-spacing: 0.05em;
}

.debug-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-xs, 8px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.debug-close:active {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.08));
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
}

/* ==================== 内容区域 ==================== */
.debug-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-md, 16px);
  padding: var(--space-md, 16px);
}

/* ==================== 调试区块 ==================== */
.debug-section {
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-md, 14px);
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  gap: var(--space-xs, 6px);
  padding: var(--space-sm, 12px) var(--space-md, 16px);
  padding-bottom: var(--space-xs, 6px);
  border-bottom: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.04));
}

.section-icon {
  color: var(--neo-primary, #10B981);
  flex-shrink: 0;
}

.section-title {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
  letter-spacing: 0.02em;
}

/* ==================== 信息网格 ==================== */
.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-xs, 6px);
  padding: var(--space-sm, 12px) var(--space-md, 16px);
  padding-bottom: var(--space-md, 16px);
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-item.full-width {
  grid-column: 1 / -1;
}

.info-label {
  font-size: 10px;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.info-value {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  font-family: ui-monospace, monospace;
}

/* ==================== Flags 列表 ==================== */
.flags-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs, 4px);
  padding: var(--space-sm, 12px) var(--space-md, 16px);
  padding-bottom: var(--space-md, 16px);
}

.flag-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-xs, 6px) var(--space-sm, 12px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-xs, 8px);
  transition: background var(--neo-duration-fast, 150ms) ease;
}

.flag-item.flag-active {
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.15);
}

.flag-name {
  font-size: var(--neo-font-size-xs, 11px);
  font-family: ui-monospace, monospace;
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
}

.flag-status {
  font-size: 10px;
  font-weight: var(--neo-font-weight-semibold, 600);
  padding: 2px 8px;
  border-radius: var(--neo-radius-xs, 6px);
  font-family: ui-monospace, monospace;
}

.status-on {
  background: rgba(16, 185, 129, 0.15);
  color: var(--neo-primary, #10B981);
}

.status-off {
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.08));
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

/* ==================== 提示信息 ==================== */
.debug-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs, 6px);
  padding: var(--space-sm, 12px);
  background: rgba(16, 185, 129, 0.06);
  border: 1px dashed rgba(16, 185, 129, 0.2);
  border-radius: var(--neo-radius-sm, 12px);
}

.debug-tip svg {
  color: var(--neo-primary, #10B981);
  flex-shrink: 0;
}

.debug-tip span {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-primary, #10B981);
}

/* ==================== 操作按钮 ==================== */
.debug-actions {
  display: flex;
  gap: var(--space-sm, 12px);
  padding: 0 var(--space-md, 16px);
  padding-bottom: var(--space-md, 16px);
}

.debug-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs, 6px);
  padding: var(--space-sm, 12px);
  border-radius: var(--neo-radius-sm, 12px);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) ease;
  border: none;
}

.debug-btn-secondary {
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.08));
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
  border: 1px solid var(--neo-border-default, rgba(255, 255, 255, 0.08));
}

.debug-btn-secondary:active {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.12));
  transform: scale(var(--neo-scale-press, 0.98));
}

.debug-btn-primary {
  background: var(--neo-primary, #10B981);
  color: white;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25);
}

.debug-btn-primary:active {
  background: var(--neo-primary-hover, #059669);
  transform: scale(var(--neo-scale-press, 0.98));
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.2);
}

/* ==================== 安全区域 ==================== */
.debug-safe-area {
  height: env(safe-area-inset-bottom, 0px);
  min-height: var(--space-sm, 12px);
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .debug-btn:active {
    transform: none;
  }
}
</style>
