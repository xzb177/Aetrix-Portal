<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, AlertTriangle, Clock, FileText, Server, Gift } from 'lucide-vue-next'
import type { Component } from 'vue'

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

export interface TodoItem {
  id: string
  title: string
  count: number
  icon?: Component
  riskLevel: RiskLevel
  route: string
  badgeText?: string
}

interface Props {
  items: TodoItem[]
  maxItems?: number
}

const props = withDefaults(defineProps<Props>(), {
  maxItems: 5,
})

const emit = defineEmits<{
  click: [item: TodoItem]
}>()

// 默认图标映射
const defaultIcons: Record<string, Component> = {
  ticket: FileText,
  expiring: Clock,
  server: Server,
  pending: Clock,
  stock: Gift,
  alert: AlertTriangle,
}

const displayItems = computed(() => {
  return props.items.slice(0, props.maxItems)
})

// 计算总数（用于徽章）
const totalCount = computed(() => {
  return props.items.reduce((sum, item) => sum + item.count, 0)
})

// 风险等级样式
const riskClass = (level: RiskLevel) => {
  const map = {
    low: 'risk-low',
    medium: 'risk-medium',
    high: 'risk-high',
    critical: 'risk-critical',
  }
  return map[level]
}

// 获取图标
const getIcon = (item: TodoItem) => {
  return item.icon || defaultIcons[item.id] || AlertTriangle
}

function handleClick(item: TodoItem) {
  emit('click', item)
}
</script>

<template>
  <div class="todo-list-section">
    <div class="todo-header">
      <h2 class="todo-title">待办事项</h2>
      <span v-if="totalCount > 0" class="todo-count">{{ totalCount }}</span>
    </div>

    <div class="todo-list">
      <div
        v-for="item in displayItems"
        :key="item.id"
        class="todo-item"
        :class="[riskClass(item.riskLevel)]"
        @click="handleClick(item)"
      >
        <!-- 图标 -->
        <div class="todo-icon" :class="`todo-icon-${item.riskLevel}`">
          <component :is="getIcon(item)" :size="16" />
        </div>

        <!-- 标题 -->
        <span class="todo-label">{{ item.title }}</span>

        <!-- Badge 区域 -->
        <div class="todo-right">
          <!-- 数量 Badge -->
          <template v-if="item.count > 0">
            <span class="todo-badge" :class="`badge-${item.riskLevel}`">
              {{ item.badgeText || item.count }}
            </span>
          </template>
          <!-- 空状态箭头 -->
          <ChevronRight v-else :size="14" class="todo-arrow" />
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="displayItems.length === 0" class="todo-empty">
        <AlertTriangle :size="20" />
        <span>暂无待办事项</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.todo-list-section {
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  overflow: hidden;
}

.todo-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.todo-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.todo-count {
  padding: 4px 10px;
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.todo-list {
  display: flex;
  flex-direction: column;
}

.todo-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  min-height: 56px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  transition: background 150ms ease;
}

.todo-item:last-child {
  border-bottom: none;
}

.todo-item:active {
  background: rgba(255, 255, 255, 0.05);
}

/* 风险等级边框高亮 */
.todo-item.risk-critical {
  border-left: 2px solid #dc2626;
}

.todo-item.risk-high {
  border-left: 2px solid #ef4444;
}

.todo-item.risk-medium {
  border-left: 2px solid #f59e0b;
}

.todo-item.risk-low {
  border-left: 2px solid #10b981;
}

/* 图标背景色 */
.todo-icon {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.todo-icon-critical {
  background: rgba(220, 38, 38, 0.15);
  color: #dc2626;
  animation: pulse-red 2s ease-in-out infinite;
}

.todo-icon-high {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.todo-icon-medium {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.todo-icon-low {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

@keyframes pulse-red {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(220, 38, 38, 0);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.1);
  }
}

.todo-label {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.todo-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.todo-badge {
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.badge-critical {
  background: rgba(220, 38, 38, 0.15);
  color: #dc2626;
  animation: pulse-badge 2s ease-in-out infinite;
}

.badge-high {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.badge-medium {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.badge-low {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

@keyframes pulse-badge {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
}

.todo-arrow {
  color: var(--text-tertiary);
}

.todo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  gap: 12px;
  color: var(--text-tertiary);
  font-size: 14px;
}

.todo-empty svg {
  opacity: 0.5;
}
</style>
