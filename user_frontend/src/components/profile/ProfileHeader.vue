<script setup lang="ts">
import { computed } from 'vue'
import { User, Award, Sparkles } from 'lucide-vue-next'
import { useLongPress } from '@/composables/useLongPress'

interface Profile {
  username: string
  id: number
  points?: number  // @deprecated 旧字段，使用 balance
  balance?: number  // 新字段，单位：分
  completed_requests_count?: number  // 成功求片入库数量
  total_requests_count?: number  // 总求片数量
}

interface Props {
  profile: Profile | null
  isVIP?: boolean
  /** @deprecated use isVIP instead */
  isVIP_v2?: boolean
  vipExpiry?: string
  loading?: boolean
  /** 是否启用彩蛋功能（通过 Feature Flag 控制） */
  enableEasterEgg?: boolean
}

interface Emits {
  (e: 'longPress'): void
}

const props = withDefaults(defineProps<Props>(), {
  isVIP: false,
  loading: false,
  enableEasterEgg: false
})

const emit = defineEmits<Emits>()

// 长按检测（仅当启用彩蛋时）
const { longPressProps, isPressing } = useLongPress({
  delay: 1000,
  onLongPress: () => {
    emit('longPress')
  }
})

// 兼容两种 prop 名称
const effectiveIsVIP = computed(() => props.isVIP ?? props.isVIP_v2 ?? false)

// 余额显示（优先使用 balance，单位是分，需要转换为元）
const displayBalance = computed(() => {
  const balanceInCents = props.profile?.balance ?? props.profile?.points ?? 0
  return (balanceInCents / 100).toFixed(2)
})

// 求片统计
const completedRequests = computed(() => props.profile?.completed_requests_count || 0)
const totalRequests = computed(() => props.profile?.total_requests_count || 0)

// 求片徽章等级
const requestBadge = computed(() => {
  const count = completedRequests.value
  if (count >= 50) return { level: '求片传说', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', icon: Sparkles }
  if (count >= 20) return { level: '求片大师', color: '#a855f7', bg: 'rgba(168, 85, 247, 0.15)', icon: Award }
  if (count >= 10) return { level: '求片专家', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)', icon: Award }
  if (count >= 5) return { level: '求片达人', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)', icon: Award }
  if (count >= 1) return { level: '求片新手', color: '#6b7280', bg: 'rgba(107, 114, 128, 0.15)', icon: null }
  return null
})

function getDaysRemaining(expiryDate?: string) {
  if (!expiryDate) return 0
  const now = new Date()
  const expiry = new Date(expiryDate)
  const diff = expiry.getTime() - now.getTime()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
}
</script>

<template>
  <!-- Loading Skeleton -->
  <div v-if="loading" class="profile-header flex items-center gap-3 px-4 py-3">
    <div class="w-12 h-12 rounded-lg bg-elevated animate-pulse"></div>
    <div class="flex-1 min-w-0">
      <div class="h-4 w-28 bg-elevated rounded animate-pulse mb-2"></div>
      <div class="h-3 w-20 bg-elevated/50 rounded animate-pulse"></div>
    </div>
    <div class="w-16 text-right">
      <div class="h-3 w-10 bg-elevated/50 rounded animate-pulse mx-auto mb-1"></div>
      <div class="h-5 w-14 bg-elevated rounded animate-pulse mx-auto"></div>
    </div>
  </div>

  <!-- Normal State -->
  <div
    v-else-if="profile"
    class="profile-header flex items-center gap-3 px-4 py-3 bg-card border-b border-white/6"
    :class="{ 'is-pressing': isPressing && enableEasterEgg }"
    v-bind="enableEasterEgg ? longPressProps : {}"
  >
    <!-- Avatar -->
    <div class="w-12 h-12 rounded-lg bg-elevated flex items-center justify-center border border-white/10 shadow-card relative">
      <User :size="22" class="text-white/60" />
      <!-- 求片徽章图标 -->
      <div v-if="requestBadge && completedRequests > 0" class="badge-icon" :style="{ backgroundColor: requestBadge.color }">
        <component :is="requestBadge.icon" :size="10" class="text-white" />
      </div>
    </div>

    <!-- User Info -->
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-white font-semibold text-base truncate">{{ profile.username }}</span>
        <!-- VIP 标签 -->
        <span v-if="effectiveIsVIP && vipExpiry" class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent whitespace-nowrap">
          VIP {{ getDaysRemaining(vipExpiry) }}天
        </span>
        <!-- 求片徽章 -->
        <span v-if="requestBadge && completedRequests > 0" class="request-badge" :style="{
          backgroundColor: requestBadge.bg,
          color: requestBadge.color
        }">
          <component v-if="requestBadge.icon" :is="requestBadge.icon" :size="10" />
          {{ requestBadge.level }}
        </span>
      </div>
      <div class="text-white/50 text-sm flex items-center gap-2">
        <span>ID: {{ profile.id }}</span>
        <span v-if="totalRequests > 0" class="text-xs text-white/30">· 已求片 {{ totalRequests }} 部</span>
      </div>
    </div>

    <!-- Balance -->
    <div class="text-right">
      <div class="text-xs text-white/40">余额</div>
      <div class="text-white font-semibold tabular-nums">¥{{ displayBalance }}</div>
    </div>
  </div>
</template>

<style scoped>
.profile-header {
  background: var(--bg-card);
  transition: background-color 0.2s ease, transform 0.15s ease;
}

/* 长按时的视觉反馈 */
.profile-header.is-pressing {
  background: rgba(16, 185, 129, 0.08);
}

/* 动效降级 */
@media (prefers-reduced-motion: reduce) {
  .profile-header {
    transition: none;
  }
}

.bg-elevated {
  background: var(--bg-elevated);
}

.bg-card {
  background: var(--bg-card);
}

.bg-accent {
  background: var(--accent);
}

.text-accent {
  color: var(--accent);
}

.badge-icon {
  position: absolute;
  bottom: -4px;
  right: -4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bg-card);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.request-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.bg-accent\/10 {
  background: rgba(16, 185, 129, 0.1);
}

.border-white\/6 {
  border-color: rgba(255, 255, 255, 0.06);
}

.border-white\/10 {
  border-color: rgba(255, 255, 255, 0.1);
}

.text-white\/60 {
  color: rgba(255, 255, 255, 0.6);
}

.text-white\/50 {
  color: rgba(255, 255, 255, 0.5);
}

.text-white\/40 {
  color: rgba(255, 255, 255, 0.4);
}

.text-white\/30 {
  color: rgba(255, 255, 255, 0.3);
}

.shadow-card {
  box-shadow: var(--shadow-card);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.animate-pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
</style>
