<script setup lang="ts">
/**
 * ActivityTimeline - 活动时间线组件
 *
 * 特性：
 * - 垂直时间线展示
 * - 事件图标 + 描述 + 时间戳
 * - 支持自定义事件列表
 * - 空状态展示
 */
import { computed } from 'vue'
import { Film, DollarSign, Calendar, CheckCircle, Clock } from 'lucide-vue-next'

export interface TimelineEvent {
  id: string
  type: 'request' | 'recharge' | 'subscription' | 'system'
  title: string
  description?: string
  timestamp: string
  icon?: any
  status?: 'success' | 'pending' | 'failed'
}

interface Props {
  events?: TimelineEvent[]
  loading?: boolean
  maxItems?: number
}

const props = withDefaults(defineProps<Props>(), {
  events: () => [],
  loading: false,
  maxItems: 5
})

// 显示的事件列表（限制数量）
const displayEvents = computed(() => {
  return props.events.slice(0, props.maxItems)
})

// 是否为空
const isEmpty = computed(() => {
  return !props.loading && props.events.length === 0
})

// 获取事件图标
const getEventIcon = (event: TimelineEvent) => {
  if (event.icon) return event.icon

  switch (event.type) {
    case 'request':
      return Film
    case 'recharge':
      return DollarSign
    case 'subscription':
      return Calendar
    default:
      return CheckCircle
  }
}

// 获取事件颜色
const getEventColor = (event: TimelineEvent) => {
  switch (event.type) {
    case 'request':
      return 'text-blue-400'
    case 'recharge':
      return 'text-emerald-400'
    case 'subscription':
      return 'text-amber-400'
    default:
      return 'text-gray-400'
  }
}

// 获取状态图标
const getStatusIcon = (event: TimelineEvent) => {
  switch (event.status) {
    case 'success':
      return CheckCircle
    case 'pending':
      return Clock
    default:
      return null
  }
}

// 格式化时间
const formatTime = (timestamp: string) => {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  // 小于 1 小时
  if (diff < 60 * 60 * 1000) {
    const minutes = Math.floor(diff / (60 * 1000))
    return `${minutes} 分钟前`
  }

  // 小于 1 天
  if (diff < 24 * 60 * 60 * 1000) {
    const hours = Math.floor(diff / (60 * 60 * 1000))
    return `${hours} 小时前`
  }

  // 小于 7 天
  if (diff < 7 * 24 * 60 * 60 * 1000) {
    const days = Math.floor(diff / (24 * 60 * 60 * 1000))
    return `${days} 天前`
  }

  // 其他情况显示日期
  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric'
  })
}
</script>

<template>
  <div class="activity-timeline">
    <div class="timeline-header">
      <h3 class="timeline-title">最近活动</h3>
      <span v-if="!loading && events.length > 0" class="timeline-count">{{ events.length }} 项</span>
    </div>

    <!-- Loading 状态 -->
    <div v-if="loading" class="timeline-loading">
      <div v-for="i in 3" :key="i" class="timeline-skeleton">
        <div class="skeleton-dot"></div>
        <div class="skeleton-content">
          <div class="skeleton-line"></div>
          <div class="skeleton-line short"></div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="isEmpty" class="timeline-empty">
      <Calendar :size="24" class="empty-icon" />
      <p class="empty-text">暂无活动记录</p>
    </div>

    <!-- 时间线内容 -->
    <div v-else class="timeline-content">
      <div
        v-for="(event, index) in displayEvents"
        :key="event.id"
        class="timeline-item"
        :class="{ 'is-last': index === displayEvents.length - 1 }"
      >
        <!-- 时间线 -->
        <div class="timeline-line" v-if="index !== displayEvents.length - 1"></div>

        <!-- 事件点 -->
        <div class="timeline-dot" :class="getEventColor(event)">
          <component :is="getEventIcon(event)" :size="14" />
        </div>

        <!-- 事件内容 -->
        <div class="event-card">
          <div class="event-header">
            <span class="event-title">{{ event.title }}</span>
            <component
              v-if="getStatusIcon(event)"
              :is="getStatusIcon(event)"
              :size="14"
              class="event-status"
              :class="{
                'status-success': event.status === 'success',
                'status-pending': event.status === 'pending'
              }"
            />
          </div>
          <p v-if="event.description" class="event-description">{{ event.description }}</p>
          <span class="event-time">{{ formatTime(event.timestamp) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 容器 ==================== */
.activity-timeline {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-2, 8px);
  width: 100%;
}

/* ==================== 头部 ==================== */
.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--neo-space-1, 4px);
}

.timeline-title {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.timeline-count {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  padding: 2px 8px;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-xs, 8px);
}

/* ==================== Loading 状态 ==================== */
.timeline-loading {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-3, 12px);
}

.timeline-skeleton {
  display: flex;
  align-items: flex-start;
  gap: var(--neo-space-2, 8px);
}

.skeleton-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  animation: pulse 1.5s ease-in-out infinite;
  flex-shrink: 0;
}

.skeleton-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-1, 4px);
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

/* ==================== 空状态 ==================== */
.timeline-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--neo-space-6, 24px) var(--neo-space-4, 16px);
}

.empty-icon {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin-bottom: var(--neo-space-2, 8px);
}

.empty-text {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin: 0;
}

/* ==================== 时间线内容 ==================== */
.timeline-content {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: var(--neo-space-3, 12px);
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-md, 14px);
}

/* 时间线项目 */
.timeline-item {
  display: flex;
  gap: var(--neo-space-2, 8px);
  position: relative;
}

.timeline-item.is-last {
  margin-bottom: 0;
}

/* 垂直线 */
.timeline-line {
  position: absolute;
  left: 27px;
  top: 32px;
  bottom: -16px;
  width: 2px;
  background: var(--neo-divider, rgba(255, 255, 255, 0.06));
}

/* 时间点 */
.timeline-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.08));
  border: 2px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.1));
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  z-index: 1;
}

.timeline-dot.text-blue-400 {
  background: rgba(59, 130, 246, 0.12);
  border-color: rgba(59, 130, 246, 0.3);
  color: #60a5fa;
}

.timeline-dot.text-emerald-400 {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.3);
  color: #34d399;
}

.timeline-dot.text-amber-400 {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.3);
  color: #fbbf24;
}

/* 事件卡片 */
.event-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-1, 4px);
  padding: var(--neo-space-2, 8px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.04));
  border-radius: var(--neo-radius-sm, 12px);
  margin-bottom: var(--neo-space-2, 8px);
}

.event-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--neo-space-1, 4px);
}

.event-title {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
}

.event-status {
  flex-shrink: 0;
}

.event-status.status-success {
  color: var(--neo-success, #10B981);
}

.event-status.status-pending {
  color: var(--neo-warning, #F59E0B);
}

.event-description {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
  margin: 0;
  line-height: 1.4;
}

.event-time {
  font-size: 10px;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

/* 图标颜色 */
.text-blue-400 {
  color: #60a5fa;
}

.text-emerald-400 {
  color: #34d399;
}

.text-amber-400 {
  color: #fbbf24;
}

.text-gray-400 {
  color: #9ca3af;
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .skeleton-dot,
  .skeleton-line {
    animation: none;
  }
}
</style>
