<script setup lang="ts">
/**
 * HoloIdCard - 全息身份卡片
 *
 * 特性：
 * - 3D 翻转动画（正面/反面）
 * - 全息扫描效果
 * - 点击翻转
 * - 长按触发调试模式
 * - 支持 reduced-motion 降级
 * - Safe Area 适配
 */
import { ref, computed, onMounted } from 'vue'
import { User, Award, Sparkles, Shield, Calendar } from 'lucide-vue-next'
import { useLongPress } from '@/composables/useLongPress'

interface Profile {
  username: string
  id: number
  points?: number
  balance?: number
  completed_requests_count?: number
  total_requests_count?: number
  registered_date?: string
}

interface Props {
  profile: Profile | null
  isVIP?: boolean
  vipExpiry?: string
  loading?: boolean
  enableEasterEgg?: boolean
}

interface Emits {
  (e: 'flip'): void
  (e: 'longPress'): void
}

const props = withDefaults(defineProps<Props>(), {
  isVIP: false,
  loading: false,
  enableEasterEgg: false
})

const emit = defineEmits<Emits>()

// 翻转状态
const isFlipped = ref(false)
const isHovered = ref(false)

// 长按检测
const { longPressProps, isPressing } = useLongPress({
  delay: 1000,
  onLongPress: () => {
    emit('longPress')
  },
  haptic: true
})

// 余额显示
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
  if (count >= 50) return { level: '求片传说', color: '#f59e0b', icon: Sparkles }
  if (count >= 20) return { level: '求片大师', color: '#a855f7', icon: Award }
  if (count >= 10) return { level: '求片专家', color: '#3b82f6', icon: Award }
  if (count >= 5) return { level: '求片达人', color: '#10b981', icon: Award }
  if (count >= 1) return { level: '求片新手', color: '#6b7280', icon: null }
  return null
})

// VIP 剩余天数
const getDaysRemaining = (expiryDate?: string) => {
  if (!expiryDate) return 0
  const now = new Date()
  const expiry = new Date(expiryDate)
  const diff = expiry.getTime() - now.getTime()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
}

// 格式化注册日期
const formatDate = (dateStr?: string) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

// 点击翻转
const handleClick = () => {
  if (!props.enableEasterEgg || !isPressing.value) {
    isFlipped.value = !isFlipped.value
    emit('flip')
  }
}

// 初始化时设置翻转状态（从 localStorage 恢复）
onMounted(() => {
  const savedFlip = localStorage.getItem('holo_id_flipped')
  if (savedFlip === 'true') {
    isFlipped.value = true
  }
})

// 监听翻转变化，保存状态
const saveFlipState = () => {
  localStorage.setItem('holo_id_flipped', String(isFlipped.value))
}

// 在组件卸载时保存状态
import { onUnmounted } from 'vue'
onUnmounted(() => {
  saveFlipState()
})
</script>

<template>
  <!-- Loading Skeleton -->
  <div v-if="loading" class="holo-id-skeleton">
    <div class="skeleton-card">
      <div class="skeleton-avatar"></div>
      <div class="skeleton-lines">
        <div class="skeleton-line"></div>
        <div class="skeleton-line short"></div>
      </div>
    </div>
  </div>

  <!-- Holo-ID Card -->
  <div
    v-else-if="profile"
    class="holo-id-container"
    :class="{ 'is-flipped': isFlipped, 'is-pressing': isPressing && enableEasterEgg }"
    v-bind="enableEasterEgg ? longPressProps : {}"
    @click="handleClick"
  >
    <div class="holo-id-card" :class="{ 'flipped': isFlipped }">
      <!-- 正面 -->
      <div class="holo-card-face holo-card-front">
        <!-- 全息扫描效果 -->
        <div class="holo-scan"></div>
        <div class="holo-glow"></div>

        <!-- 卡片内容 -->
        <div class="holo-card-content">
          <!-- 头像区域 -->
          <div class="holo-avatar">
            <div class="avatar-inner">
              <User :size="32" class="avatar-icon" />
              <!-- VIP 徽章 -->
              <div v-if="isVIP" class="vip-badge">
                <Shield :size="12" />
              </div>
            </div>
          </div>

          <!-- 用户信息 -->
          <div class="holo-info">
            <h3 class="holo-name">{{ profile.username }}</h3>
            <div class="holo-meta">
              <!-- VIP 标签 -->
              <span v-if="isVIP && vipExpiry" class="holo-tag holo-tag-vip">
                VIP {{ getDaysRemaining(vipExpiry) }}天
              </span>
              <!-- 求片徽章 -->
              <span v-if="requestBadge" class="holo-tag holo-tag-badge" :style="{ color: requestBadge.color }">
                <component v-if="requestBadge.icon" :is="requestBadge.icon" :size="10" />
                {{ requestBadge.level }}
              </span>
            </div>
            <p v-if="totalRequests > 0" class="holo-sub">已求片 {{ totalRequests }} 部</p>
          </div>

          <!-- 钱包余额 -->
          <div class="holo-balance">
            <span class="balance-label">钱包余额</span>
            <span class="balance-value">¥{{ displayBalance }}</span>
          </div>
        </div>

        <!-- 点击提示 -->
        <div class="holo-hint">
          <span class="hint-dot"></span>
          <span class="hint-text">点击翻转</span>
        </div>
      </div>

      <!-- 反面 -->
      <div class="holo-card-face holo-card-back">
        <!-- 全息网格 -->
        <div class="holo-grid"></div>

        <!-- 卡片内容 -->
        <div class="holo-card-content">
          <!-- ID 信息 -->
          <div class="holo-id-info">
            <div class="id-icon">
              <Shield :size="20" />
            </div>
            <div class="id-details">
              <span class="id-label">USER ID</span>
              <span class="id-value">#{{ profile.id }}</span>
            </div>
          </div>

          <!-- 注册日期 -->
          <div v-if="profile.registered_date" class="holo-date-info">
            <div class="date-icon">
              <Calendar :size="16" />
            </div>
            <div class="date-details">
              <span class="date-label">注册时间</span>
              <span class="date-value">{{ formatDate(profile.registered_date) }}</span>
            </div>
          </div>

          <!-- 等级标识 -->
          <div class="holo-rank">
            <span class="rank-star">★</span>
            <span class="rank-text">BRIDGE OPERATOR</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 容器 ==================== */
.holo-id-container {
  perspective: 1000px;
  -webkit-perspective: 1000px; /* iOS Safari 需要 */
  width: 100%;
  max-width: 400px;
  margin: 0 auto;
}

/* ==================== 卡片主体 ==================== */
.holo-id-card {
  position: relative;
  width: 100%;
  min-height: 160px;
  transform-style: preserve-3d;
  -webkit-transform-style: preserve-3d; /* iOS Safari 需要 */
  transition: transform var(--neo-card-flip-duration, 600ms) var(--neo-card-flip-ease, cubic-bezier(0.4, 0, 0.2, 1));
  -webkit-transition: -webkit-transform var(--neo-card-flip-duration, 600ms) var(--neo-card-flip-ease, cubic-bezier(0.4, 0, 0.2, 1));
}

.holo-id-card.flipped {
  transform: rotateY(180deg);
  -webkit-transform: rotateY(180deg); /* iOS Safari 需要 */
}

/* ==================== 卡片面 ==================== */
.holo-card-face {
  position: absolute;
  inset: 0;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden; /* iOS Safari 需要 */
  border-radius: var(--neo-radius-lg, 18px);
  overflow: hidden;
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  box-shadow: var(--neo-shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.4));
}

.holo-card-back {
  transform: rotateY(180deg);
  -webkit-transform: rotateY(180deg); /* iOS Safari 需要 */
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(59, 130, 246, 0.08) 100%);
}

/* ==================== 正面样式 ==================== */
.holo-card-front {
  position: relative;
}

/* 全息扫描效果 */
.holo-scan {
  position: absolute;
  inset: 0;
  background: var(--neo-holo-scan, linear-gradient(180deg, transparent 0%, rgba(16, 185, 129, 0.15) 50%, transparent 100%));
  background-size: 100% 200%;
  animation: holo-scan 3s ease-in-out infinite;
  pointer-events: none;
  z-index: 1;
}

@keyframes holo-scan {
  0%, 100% { background-position: 0% -100%; }
  50% { background-position: 0% 200%; }
}

/* 全息发光 */
.holo-glow {
  position: absolute;
  inset: 0;
  background: var(--neo-holo-gradient, linear-gradient(135deg, #10B981 0%, #3B82F6 50%, #8B5CF6 100%));
  opacity: 0;
  transition: opacity var(--neo-duration-normal, 200ms) ease;
  pointer-events: none;
  z-index: 0;
}

.holo-id-container:hover .holo-glow,
.holo-id-container.is-pressing .holo-glow {
  opacity: 0.05;
}

/* 卡片内容 */
.holo-card-content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-4, 16px);
}

/* 头像 */
.holo-avatar {
  align-self: flex-start;
}

.avatar-inner {
  width: 56px;
  height: 56px;
  border-radius: var(--neo-radius-md, 14px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.08));
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.15);
}

.avatar-icon {
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
}

.vip-badge {
  position: absolute;
  bottom: -6px;
  right: -6px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: linear-gradient(135deg, #10B981, #059669);
  border: 2px solid var(--neo-bg-base, #0B0F14);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.4);
}

/* 用户信息 */
.holo-info {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-1, 4px);
}

.holo-name {
  font-size: var(--neo-font-size-xl, 18px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  margin: 0;
}

.holo-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--neo-space-1, 4px);
}

.holo-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: var(--neo-radius-xs, 8px);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.holo-tag-vip {
  background: rgba(16, 185, 129, 0.15);
  color: var(--neo-primary, #10B981);
}

.holo-tag-badge {
  background: rgba(168, 85, 247, 0.12);
  color: #a855f7;
}

.holo-sub {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin: 0;
}

/* 余额 */
.holo-balance {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--neo-space-2, 8px);
  border-top: 1px solid var(--neo-divider, rgba(255, 255, 255, 0.06));
}

.balance-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.balance-value {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-primary, #10B981);
  font-family: ui-monospace, monospace;
}

/* 点击提示 */
.holo-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--neo-space-1, 4px);
  padding-top: var(--neo-space-1, 4px);
}

.hint-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  animation: hint-pulse 2s ease-in-out infinite;
}

@keyframes hint-pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.hint-text {
  font-size: 10px;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

/* ==================== 反面样式 ==================== */
.holo-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(16, 185, 129, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(16, 185, 129, 0.03) 1px, transparent 1px);
  background-size: 20px 20px;
  pointer-events: none;
}

/* ID 信息 */
.holo-id-info {
  display: flex;
  align-items: center;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-3, 12px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-sm, 12px);
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
}

.id-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--neo-radius-xs, 8px);
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-primary, #10B981);
}

.id-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.id-label {
  font-size: 10px;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.id-value {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  font-family: ui-monospace, monospace;
}

/* 注册日期 */
.holo-date-info {
  display: flex;
  align-items: center;
  gap: var(--neo-space-2, 8px);
}

.date-icon {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.date-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.date-label {
  font-size: 10px;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.date-value {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
}

/* 等级标识 */
.holo-rank {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--neo-space-1, 4px);
  padding: var(--neo-space-2, 8px);
  background: rgba(16, 185, 129, 0.08);
  border-radius: var(--neo-radius-xs, 8px);
  border: 1px solid rgba(16, 185, 129, 0.15);
}

.rank-star {
  color: #f59e0b;
  font-size: 14px;
}

.rank-text {
  font-size: 10px;
  color: var(--neo-primary, #10B981);
  letter-spacing: 0.15em;
  font-weight: 600;
}

/* ==================== 长按反馈 ==================== */
.holo-id-container.is-pressing .holo-id-card {
  box-shadow: 0 0 0 2px var(--neo-primary, #10B981);
}

/* ==================== Loading Skeleton ==================== */
.holo-id-skeleton {
  width: 100%;
  max-width: 400px;
  margin: 0 auto;
}

.skeleton-card {
  min-height: 160px;
  border-radius: var(--neo-radius-lg, 18px);
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  padding: var(--neo-space-4, 16px);
  display: flex;
  align-items: center;
  gap: var(--neo-space-3, 12px);
}

.skeleton-avatar {
  width: 56px;
  height: 56px;
  border-radius: var(--neo-radius-md, 14px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  animation: pulse 1.5s ease-in-out infinite;
}

.skeleton-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-2, 8px);
}

.skeleton-line {
  height: 12px;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border-radius: 4px;
  animation: pulse 1.5s ease-in-out infinite;
}

.skeleton-line.short {
  width: 60%;
}

@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.8; }
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .holo-id-card {
    transition: none;
    -webkit-transition: none;
  }

  .holo-id-card.flipped {
    transform: rotateY(180deg);
    -webkit-transform: rotateY(180deg);
  }

  .holo-scan {
    animation: none;
  }

  .hint-dot {
    animation: none;
  }

  .skeleton-avatar,
  .skeleton-line {
    animation: none;
  }
}
</style>
