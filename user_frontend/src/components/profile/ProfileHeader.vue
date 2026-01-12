<script setup lang="ts">
import { computed } from 'vue'
import { User } from 'lucide-vue-next'

interface Profile {
  username: string
  id: number
  points?: number  // @deprecated 旧字段，使用 balance
  balance?: number  // 新字段，单位：分
}

interface Props {
  profile: Profile | null
  isVIP?: boolean
  /** @deprecated use isVIP instead */
  isVIP_v2?: boolean
  vipExpiry?: string
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isVIP: false,
  loading: false
})

// 兼容两种 prop 名称
const effectiveIsVIP = computed(() => props.isVIP ?? props.isVIP_v2 ?? false)

// 余额显示（优先使用 balance，单位是分，需要转换为元）
const displayBalance = computed(() => {
  const balanceInCents = props.profile?.balance ?? props.profile?.points ?? 0
  return (balanceInCents / 100).toFixed(2)
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
  <div v-else-if="profile" class="profile-header flex items-center gap-3 px-4 py-3 bg-card border-b border-white/6">
    <!-- Avatar -->
    <div class="w-12 h-12 rounded-lg bg-elevated flex items-center justify-center border border-white/10 shadow-card">
      <User :size="22" class="text-white/60" />
    </div>

    <!-- User Info -->
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2">
        <span class="text-white font-semibold text-base truncate">{{ profile.username }}</span>
        <span v-if="effectiveIsVIP && vipExpiry" class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/10 text-accent whitespace-nowrap">
          VIP {{ getDaysRemaining(vipExpiry) }}天
        </span>
      </div>
      <div class="text-white/50 text-sm">ID: {{ profile.id }}</div>
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
