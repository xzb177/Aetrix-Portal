<script setup lang="ts">
/**
 * 求片限制卡片
 *
 * 显示用户的求片配额、已使用次数、剩余次数等信息
 */
import { ref, onMounted, computed } from 'vue'
import { Film } from 'lucide-vue-next'
import { requestApi } from '@/api'

interface RequestLimit {
  limit: number
  used: number
  remaining: number
  period: string  // total, monthly, weekly
  is_vip: boolean
  vip_bonus: number
}

const props = defineProps<{
  isVIP?: boolean
}>()

const limitInfo = ref<RequestLimit | null>(null)
const loading = ref(true)

const periodText = computed(() => {
  if (!limitInfo.value) return ''
  const map = {
    total: '总计',
    monthly: '本月',
    weekly: '本周'
  }
  return map[limitInfo.value.period as keyof typeof map] || '总计'
})

const percentage = computed(() => {
  if (!limitInfo.value || limitInfo.value.limit === 0) return 0
  return Math.min(100, (limitInfo.value.used / limitInfo.value.limit) * 100)
})

const barColor = computed(() => {
  const p = percentage.value
  if (p >= 100) return '#ef4444'  // red - 已用尽
  if (p >= 75) return '#f59e0b'   // amber - 即将用尽
  return '#10b981'                // green - 充足
})

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

onMounted(() => {
  fetchLimit()
})

defineExpose({
  refresh: fetchLimit
})
</script>

<template>
  <div class="request-limit-card bg-card">
    <div class="card-header">
      <div class="header-left">
        <div class="icon-wrapper">
          <Film :size="18" class="icon" />
        </div>
        <span class="card-title">求片配额</span>
      </div>
      <div v-if="limitInfo" class="header-right">
        <span v-if="limitInfo.limit === 0" class="unlimited-badge">无限制</span>
        <span v-else class="limit-badge">{{ limitInfo.remaining }}/{{ limitInfo.limit }}</span>
      </div>
    </div>

    <!-- Loading 状态 -->
    <div v-if="loading" class="card-content">
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>

    <!-- 内容 -->
    <div v-else-if="limitInfo" class="card-content">
      <div v-if="limitInfo.limit === 0" class="unlimited-info">
        <p class="unlimited-text">您当前拥有无限求片次数</p>
        <p v-if="limitInfo.is_vip" class="vip-tag">VIP 用户</p>
      </div>

      <div v-else>
        <!-- 进度条 -->
        <div class="progress-bar-wrapper">
          <div class="progress-bar">
            <div
              class="progress-fill"
              :style="{ width: `${percentage}%`, backgroundColor: barColor }"
            ></div>
          </div>
          <span class="percentage-text">{{ Math.round(percentage) }}%</span>
        </div>

        <!-- 详细信息 -->
        <div class="limit-details">
          <div class="detail-item">
            <span class="detail-label">统计周期</span>
            <span class="detail-value">{{ periodText }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">已使用</span>
            <span class="detail-value">{{ limitInfo.used }} 次</span>
          </div>
          <div class="detail-item" v-if="limitInfo.is_vip">
            <span class="detail-label">VIP 加成</span>
            <span class="detail-value vip-value">+{{ limitInfo.vip_bonus }} 次</span>
          </div>
        </div>

        <!-- 提示信息 -->
        <div v-if="limitInfo.remaining === 0" class="alert-box exhausted">
          <p>您的求片次数已用尽，成为 VIP 可获得额外 {{ limitInfo.vip_bonus }} 次求片额度</p>
        </div>
        <div v-else-if="percentage >= 75" class="alert-box warning">
          <p>您的求片次数即将用尽，还剩 {{ limitInfo.remaining }} 次</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.request-limit-card {
  border-radius: 1rem;
  padding: 1rem;
  overflow: hidden;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.875rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.icon-wrapper {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(16, 185, 129, 0.12);
  display: grid;
  place-items: center;
}

.icon {
  color: #34d399;
}

.card-title {
  font-size: 0.938rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.limit-badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.625rem;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(52, 211, 153, 0.25);
  border-radius: 6px;
  color: #34d399;
}

.unlimited-badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.625rem;
  background: rgba(251, 191, 36, 0.15);
  border: 1px solid rgba(251, 191, 36, 0.3);
  border-radius: 6px;
  color: #fbbf24;
}

.card-content {
  min-height: 60px;
}

/* 骨架屏 */
.skeleton-line {
  height: 12px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
  margin-bottom: 0.5rem;
  animation: pulse 1.5s ease-in-out infinite;
}

.skeleton-line.short {
  width: 60%;
}

@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.8; }
}

/* 无限制状态 */
.unlimited-info {
  text-align: center;
  padding: 0.5rem 0;
}

.unlimited-text {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.7);
  margin: 0 0 0.5rem 0;
}

.vip-tag {
  display: inline-block;
  font-size: 0.75rem;
  padding: 0.25rem 0.75rem;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  border-radius: 20px;
  color: white;
  font-weight: 500;
  margin: 0;
}

/* 进度条 */
.progress-bar-wrapper {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease, background-color 0.3s ease;
}

.percentage-text {
  font-size: 0.75rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.8);
  min-width: 36px;
  text-align: right;
}

/* 详细信息 */
.limit-details {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.detail-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
}

.detail-label {
  color: rgba(255, 255, 255, 0.5);
}

.detail-value {
  color: rgba(255, 255, 255, 0.9);
  font-weight: 500;
}

.vip-value {
  color: #fbbf24;
}

/* 提示框 */
.alert-box {
  padding: 0.625rem 0.75rem;
  border-radius: 8px;
  font-size: 0.75rem;
}

.alert-box.exhausted {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.alert-box.exhausted p {
  color: rgba(248, 113, 113, 0.9);
  margin: 0;
}

.alert-box.warning {
  background: rgba(251, 191, 36, 0.1);
  border: 1px solid rgba(251, 191, 36, 0.2);
}

.alert-box.warning p {
  color: rgba(251, 191, 36, 0.9);
  margin: 0;
}
</style>
