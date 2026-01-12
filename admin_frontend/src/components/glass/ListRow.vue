<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'

interface Props {
  title: string
  subtitle?: string
  icon?: Component
  iconColor?: string
  badge?: string
  badgeType?: 'success' | 'warning' | 'danger' | 'info' | 'gray' | 'primary'
  showArrow?: boolean
  clickable?: boolean
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showArrow: true,
  clickable: true,
  disabled: false,
  badgeType: 'info',
})

const emit = defineEmits<{
  click: []
}>()

const badgeClass = computed(() => {
  const typeMap = {
    success: 'bg-success-bg text-success',
    warning: 'bg-warning-bg text-warning',
    danger: 'bg-danger-bg text-danger',
    info: 'bg-info-bg text-info',
    gray: 'bg-white/5 text-text-tertiary',
    primary: 'bg-primary/10 text-primary',
  }
  return typeMap[props.badgeType]
})

function handleClick() {
  if (props.clickable && !props.disabled) {
    emit('click')
  }
}
</script>

<template>
  <div
    class="list-row"
    :class="{
      'list-row-clickable': clickable && !disabled,
      'list-row-disabled': disabled,
    }"
    @click="handleClick"
  >
    <!-- 左侧图标 -->
    <div v-if="icon" class="list-row-icon" :style="{ color: iconColor }">
      <component :is="icon" :size="20" />
    </div>

    <!-- 图标插槽 -->
    <div v-else-if="$slots.icon" class="list-row-icon">
      <slot name="icon" />
    </div>

    <!-- 内容区 -->
    <div class="list-row-content">
      <p class="list-row-title">{{ title }}</p>
      <p v-if="subtitle" class="list-row-subtitle">{{ subtitle }}</p>
      <!-- 内容插槽 -->
      <slot name="content" />
    </div>

    <!-- 右侧插槽 -->
    <div v-if="$slots.right" class="list-row-right">
      <slot name="right" />
    </div>

    <!-- 右侧徽章和箭头 -->
    <div v-else class="list-row-end">
      <span v-if="badge" class="list-row-badge" :class="badgeClass">
        {{ badge }}
      </span>
      <svg
        v-if="showArrow"
        class="list-row-arrow"
        :class="{ 'opacity-0': !clickable }"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
      </svg>
    </div>
  </div>
</template>

<style scoped>
.list-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  min-height: 56px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  transition: all 150ms ease;
}

.list-row:last-child {
  border-bottom: none;
}

.list-row-clickable {
  cursor: pointer;
}

.list-row-clickable:active {
  background: rgba(255, 255, 255, 0.05);
}

.list-row-disabled {
  opacity: 0.5;
  pointer-events: none;
}

.list-row-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--text-secondary);
}

.list-row-content {
  flex: 1;
  min-width: 0;
}

.list-row-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list-row-subtitle {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0.125rem 0 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list-row-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.list-row-end {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.list-row-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.list-row-arrow {
  width: 18px;
  height: 18px;
  color: var(--text-tertiary);
  transition: opacity 150ms ease;
}

.list-row-clickable:active .list-row-arrow {
  transform: translateX(2px);
}
</style>
