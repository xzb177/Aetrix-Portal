<script setup lang="ts">
import type { Component } from 'vue'

interface Props {
  icon?: Component
  title: string
  description?: string
  actionLabel?: string
}

const props = withDefaults(defineProps<Props>(), {
  actionLabel: '',
})

const emit = defineEmits<{
  action: []
}>()
</script>

<template>
  <div class="empty-state">
    <!-- 图标 -->
    <div v-if="icon" class="empty-icon">
      <component :is="icon" :size="48" />
    </div>

    <!-- 标题 -->
    <h3 class="empty-title">{{ title }}</h3>

    <!-- 描述 -->
    <p v-if="description" class="empty-description">{{ description }}</p>

    <!-- 操作按钮 -->
    <button v-if="actionLabel" class="empty-action" @click="emit('action')">
      {{ actionLabel }}
    </button>

    <!-- 自定义插槽 -->
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1.5rem;
  text-align: center;
}

.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--bg-input);
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}

.empty-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-secondary);
  margin: 0 0 0.5rem 0;
}

.empty-description {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0 0 1.5rem 0;
  max-width: 280px;
}

.empty-action {
  padding: 0.75rem 1.5rem;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 150ms ease;
}

.empty-action:active {
  transform: scale(0.97);
  opacity: 0.9;
}
</style>
