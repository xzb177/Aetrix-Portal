<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, User, CreditCard, AlertTriangle, FileText, Settings } from 'lucide-vue-next'
import type { Component } from 'vue'

export type ActivityType = 'user' | 'order' | 'system' | 'ticket' | 'config'

export interface ActivityItem {
  id: string
  type: ActivityType
  title: string
  description?: string
  timestamp: Date
  icon?: Component
  route?: string
}

interface Props {
  activities: ActivityItem[]
  maxItems?: number
  showViewAll?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  maxItems: 5,
  showViewAll: true,
})

const emit = defineEmits<{
  click: [activity: ActivityItem]
  viewAll: []
}>()

const displayActivities = computed(() => {
  return props.activities.slice(0, props.maxItems)
})

// 类型默认图标
const typeIcons: Record<ActivityType, Component> = {
  user: User,
  order: CreditCard,
  system: Settings,
  ticket: FileText,
  config: Settings,
}

// 类型颜色
const typeColor = (type: ActivityType) => {
  const map: Record<ActivityType, string> = {
    user: 'activity-user',
    order: 'activity-order',
    system: 'activity-system',
    ticket: 'activity-ticket',
    config: 'activity-config',
  }
  return map[type]
}

// 格式化时间
const formatTime = (date: Date): string => {
  const h = String(date.getHours()).padStart(2, '0')
  const m = String(date.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

// 计算相对时间
const timeAgo = (date: Date): string => {
  const now = new Date()
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000)

  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  const days = Math.floor(diff / 86400)
  return days === 1 ? '昨天' : `${days}天前`
}

const getIcon = (activity: ActivityItem) => {
  return activity.icon || typeIcons[activity.type] || AlertTriangle
}

function handleClick(activity: ActivityItem) {
  if (activity.route) {
    emit('click', activity)
  }
}

function handleViewAll() {
  emit('viewAll')
}
</script>

<template>
  <div class="activity-section">
    <div class="activity-header">
      <h2 class="activity-title">最近活动</h2>
      <button
        v-if="showViewAll"
        class="view-all-btn"
        @click="handleViewAll"
      >
        <span>查看全部</span>
        <ChevronRight :size="14" />
      </button>
    </div>

    <div class="activity-list">
      <div
        v-for="(activity, index) in displayActivities"
        :key="activity.id"
        class="activity-item"
        :class="[typeColor(activity.type), { 'activity-clickable': activity.route }]"
        @click="handleClick(activity)"
      >
        <!-- 时间线连接线 -->
        <div v-if="index < displayActivities.length - 1" class="activity-line" />

        <!-- 图标 -->
        <div class="activity-icon-wrapper">
          <div class="activity-icon">
            <component :is="getIcon(activity)" :size="14" />
          </div>
        </div>

        <!-- 内容 -->
        <div class="activity-content">
          <div class="activity-title-row">
            <span class="activity-name">{{ activity.title }}</span>
            <span class="activity-time">{{ formatTime(activity.timestamp) }}</span>
          </div>
          <div class="activity-meta">
            <span v-if="activity.description" class="activity-desc">{{ activity.description }}</span>
            <span class="activity-ago">{{ timeAgo(activity.timestamp) }}</span>
          </div>
        </div>

        <!-- 跳转箭头 -->
        <ChevronRight v-if="activity.route" :size="14" class="activity-arrow" />
      </div>

      <!-- 空状态 -->
      <div v-if="displayActivities.length === 0" class="activity-empty">
        <AlertTriangle :size="20" />
        <span>暂无活动记录</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.activity-section {
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  overflow: hidden;
}

.activity-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.activity-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.view-all-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--primary);
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 150ms ease;
}

.view-all-btn:active {
  opacity: 0.7;
  transform: scale(0.97);
}

.activity-list {
  position: relative;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.activity-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 8px;
  border-radius: 10px;
  transition: background 150ms ease;
}

.activity-item.activity-clickable {
  cursor: pointer;
}

.activity-item.activity-clickable:active {
  background: rgba(255, 255, 255, 0.05);
}

/* 时间线连接线 */
.activity-line {
  position: absolute;
  left: 20px;
  top: 36px;
  bottom: -16px;
  width: 2px;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0.1), transparent);
  z-index: 0;
}

.activity-icon-wrapper {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
}

.activity-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 类型颜色 */
.activity-user .activity-icon {
  background: rgba(99, 102, 241, 0.15);
  color: #6366f1;
}

.activity-order .activity-icon {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.activity-system .activity-icon {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.activity-ticket .activity-icon {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.activity-config .activity-icon {
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
}

.activity-content {
  flex: 1;
  min-width: 0;
}

.activity-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
}

.activity-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.activity-time {
  font-size: 12px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.activity-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.activity-desc {
  font-size: 12px;
  color: var(--text-secondary);
}

.activity-ago {
  font-size: 11px;
  color: var(--text-tertiary);
}

.activity-arrow {
  flex-shrink: 0;
  color: var(--text-tertiary);
  opacity: 0;
  margin-top: 2px;
  transition: opacity 150ms ease;
}

.activity-item.activity-clickable:hover .activity-arrow {
  opacity: 0.5;
}

.activity-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  gap: 12px;
  color: var(--text-tertiary);
  font-size: 14px;
}

.activity-empty svg {
  opacity: 0.5;
}
</style>
