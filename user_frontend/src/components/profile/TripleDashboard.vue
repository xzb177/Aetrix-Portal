<script setup lang="ts">
/**
 * TripleDashboard - 三联仪表盘
 *
 * 特性：
 * - 左：余额/积分
 * - 中：求片统计 + 环形进度条
 * - 右：VIP 状态倒计时
 * - SVG 环形进度条动画
 * - 支持 reduced-motion 降级
 */
import { ref, computed, onMounted, watch } from 'vue'
import { Wallet, Film, Crown, TrendingUp, Clock } from 'lucide-vue-next'
import { requestApi } from '@/api'

interface RequestLimit {
  limit: number
  used: number
  remaining: number
  period: string
  is_vip: boolean
  vip_bonus: number
}

interface Props {
  isVIP?: boolean
  vipExpiry?: string
  balance?: number
  completedRequests?: number
}

const props = withDefaults(defineProps<Props>(), {
  isVIP: false,
  balance: 0,
  completedRequests: 0
})

// 求片配额数据
const limitInfo = ref<RequestLimit | null>(null)
const loading = ref(true)

// 动画进度
const animatedProgress = ref(0)

// 求片配额百分比
const percentage = computed(() => {
  if (!limitInfo.value || limitInfo.value.limit === 0) return 0
  return Math.min(100, (limitInfo.value.used / limitInfo.value.limit) * 100)
})

// 进度条颜色
const gaugeColor = computed(() => {
  const p = percentage.value
  if (p >= 100) return 'var(--neo-gauge-danger, #EF4444)'
  if (p >= 75) return 'var(--neo-gauge-warning, #F59E0B)'
  return 'var(--neo-gauge-primary, #10B981)'
})

// 周期文字
const periodText = computed(() => {
  if (!limitInfo.value) return ''
  const map: Record<string, string> = {
    total: '总计',
    monthly: '本月',
    weekly: '本周'
  }
  return map[limitInfo.value.period] || '总计'
})

// 余额显示
const displayBalance = computed(() => {
  return (props.balance / 100).toFixed(2)
})

// VIP 剩余天数
const vipDaysRemaining = computed(() => {
  if (!props.vipExpiry) return 0
  const now = new Date()
  const expiry = new Date(props.vipExpiry)
  const diff = expiry.getTime() - now.getTime()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
})

// VIP 进度（假设 30 天为一个周期）
const vipProgress = computed(() => {
  const days = vipDaysRemaining.value
  if (days >= 30) return 100
  return Math.max(0, (days / 30) * 100)
})

// SVG 圆环参数
const radius = 40
const circumference = 2 * Math.PI * radius
const strokeDashoffset = computed(() => {
  return circumference - (animatedProgress.value / 100) * circumference
})

// VIP 圆环偏移
const vipStrokeDashoffset = computed(() => {
  return circumference - (vipProgress.value / 100) * circumference
})

// 获取求片配额
async function fetchLimit() {
  try {
    const data = await requestApi.getMyLimit()
    limitInfo.value = data as RequestLimit
  } catch (error) {
    console.error('Failed to fetch request limit:', error)
  } finally {
    loading.value = false
  }
}

// 动画进度条
function animateProgress() {
  const target = percentage.value
  const duration = 1000
  const startTime = performance.now()
  const startValue = animatedProgress.value

  function update(currentTime: number) {
    const elapsed = currentTime - startTime
    const progress = Math.min(elapsed / duration, 1)
    const easeProgress = 1 - Math.pow(1 - progress, 3) // ease-out cubic

    animatedProgress.value = startValue + (target - startValue) * easeProgress

    if (progress < 1) {
      requestAnimationFrame(update)
    }
  }

  requestAnimationFrame(update)
}

// 监听 percentage 变化，触发动画
watch(percentage, () => {
  animateProgress()
})

onMounted(() => {
  fetchLimit()
  // 初始动画
  setTimeout(() => animateProgress(), 300)
})

defineExpose({
  refresh: fetchLimit
})
</script>

<template>
  <div class="triple-dashboard">
    <!-- 左：钱包余额 -->
    <div class="dashboard-panel dashboard-balance">
      <div class="panel-icon balance-icon">
        <Wallet :size="18" />
      </div>
      <div class="panel-content">
        <span class="panel-label">钱包余额</span>
        <div class="panel-value">
          <span class="value-amount">¥{{ displayBalance }}</span>
        </div>
      </div>
    </div>

    <!-- 中：求片统计 -->
    <div class="dashboard-panel dashboard-requests">
      <div class="panel-icon requests-icon">
        <Film :size="18" />
      </div>
      <div class="panel-content">
        <span class="panel-label">求片配额</span>
        <div class="panel-gauge">
          <!-- SVG 环形进度条 -->
          <svg class="gauge-svg" viewBox="0 0 100 100">
            <!-- 背景圆环 -->
            <circle
              class="gauge-bg"
              :cx="50"
              :cy="50"
              :r="radius"
              fill="none"
              :stroke="'var(--neo-gauge-bg, rgba(255, 255, 255, 0.06))'"
              :stroke-width="6"
            />
            <!-- 进度圆环 -->
            <circle
              class="gauge-progress"
              :cx="50"
              :cy="50"
              :r="radius"
              fill="none"
              :stroke="gaugeColor"
              :stroke-width="6"
              :stroke-dasharray="circumference"
              :stroke-dashoffset="strokeDashoffset"
              stroke-linecap="round"
              transform="rotate(-90 50 50)"
            />
            <!-- 中心文字 -->
            <text
              x="50"
              y="50"
              class="gauge-text"
              :class="{ 'gauge-text-full': percentage >= 100 }"
              text-anchor="middle"
              dominant-baseline="central"
            >
              <tspan class="gauge-value">{{ Math.round(animatedProgress) }}%</tspan>
            </text>
          </svg>
        </div>
        <div class="panel-hint">
          <span v-if="!loading && limitInfo">
            <template v-if="limitInfo.limit === 0">无限制</template>
            <template v-else>{{ limitInfo.remaining }} / {{ limitInfo.limit }}</template>
          </span>
          <span v-else class="skeleton-text">--</span>
        </div>
      </div>
    </div>

    <!-- 右：VIP 状态 -->
    <div class="dashboard-panel dashboard-vip" :class="{ 'vip-active': isVIP }">
      <div class="panel-icon vip-icon">
        <Crown :size="18" />
      </div>
      <div class="panel-content">
        <span class="panel-label">VIP 状态</span>
        <div class="panel-value vip-value">
          <template v-if="isVIP">
            <span class="vip-days">{{ vipDaysRemaining }}天</span>
            <Clock :size="14" class="vip-clock" />
          </template>
          <span v-else class="vip-inactive">未激活</span>
        </div>
        <span class="panel-hint">{{ isVIP ? '尊贵会员' : '升级解锁更多' }}</span>
      </div>
      <!-- VIP 进度条 -->
      <div v-if="isVIP" class="vip-progress-bar">
        <div
          class="vip-progress-fill"
          :style="{ width: `${vipProgress}%` }"
        ></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 容器 ==================== */
.triple-dashboard {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--neo-space-2, 8px);
  width: 100%;
}

/* ==================== 通用面板样式 ==================== */
.dashboard-panel {
  position: relative;
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--neo-space-3, 12px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--neo-space-2, 8px);
  overflow: hidden;
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.dashboard-panel:active {
  background: var(--neo-bg-surface-active, rgba(255, 255, 255, 0.08));
  transform: scale(0.98);
}

/* ==================== 面板图标 ==================== */
.panel-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--neo-radius-xs, 8px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.balance-icon {
  background: rgba(16, 185, 129, 0.12);
  color: var(--neo-primary, #10B981);
}

.requests-icon {
  background: rgba(59, 130, 246, 0.12);
  color: var(--neo-info, #3B82F6);
}

.vip-icon {
  background: rgba(245, 158, 11, 0.12);
  color: var(--neo-warning, #F59E0B);
}

.dashboard-vip.vip-active .vip-icon {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(234, 179, 8, 0.2));
  color: #f59e0b;
}

/* ==================== 面板内容 ==================== */
.panel-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--neo-space-1, 4px);
  text-align: center;
}

.panel-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  letter-spacing: 0.05em;
}

.panel-value {
  display: flex;
  align-items: center;
  justify-content: center;
}

.value-amount {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  font-family: ui-monospace, monospace;
  /* iOS Safari 文字镜像修复 */
  transform: translateZ(0);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}

.panel-hint {
  font-size: 10px;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.skeleton-text {
  display: inline-block;
  min-width: 40px;
  height: 12px;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border-radius: 4px;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.8; }
}

/* ==================== 求片进度条 ==================== */
.panel-gauge {
  position: relative;
  width: 70px;
  height: 70px;
}

.gauge-svg {
  width: 100%;
  height: 100%;
  filter: drop-shadow(0 0 4px currentColor);
}

.gauge-bg {
  opacity: 0.3;
}

.gauge-progress {
  transition: stroke-dashoffset var(--neo-duration-slow, 300ms) ease;
}

.gauge-text {
  font-size: 14px;
  font-weight: var(--neo-font-weight-semibold, 600);
  fill: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
}

.gauge-text.gauge-text-full {
  fill: var(--neo-gauge-danger, #EF4444);
}

.gauge-value {
  font-family: ui-monospace, monospace;
  /* iOS Safari 文字镜像修复 */
  transform: translateZ(0);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}

/* ==================== VIP 面板 ==================== */
.vip-value {
  gap: var(--neo-space-1, 4px);
}

.vip-days {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-warning, #F59E0B);
  /* iOS Safari 文字镜像修复 */
  transform: translateZ(0);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.vip-clock {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.vip-inactive {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

/* VIP 进度条 */
.vip-progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  overflow: hidden;
}

.vip-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #f59e0b, #d97706);
  transition: width var(--neo-duration-normal, 200ms) ease;
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.5);
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .dashboard-panel:active {
    transform: none;
  }

  .gauge-progress {
    transition: none;
  }

  .vip-progress-fill {
    transition: none;
  }

  .skeleton-text {
    animation: none;
  }
}
</style>
