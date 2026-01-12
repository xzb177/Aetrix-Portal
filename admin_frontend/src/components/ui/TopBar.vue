<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, MoreVertical } from 'lucide-vue-next'

interface Props {
  title?: string
  subtitle?: string
  showBack?: boolean
  fixed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showBack: false,
  fixed: true,
})

const emit = defineEmits<{
  (e: 'back'): void
  (e: 'menu'): void
}>()
</script>

<template>
  <div :class="['topbar', { 'topbar-fixed': fixed }]">
    <!-- 左侧：返回按钮 + 标题 -->
    <div class="topbar-left">
      <button
        v-if="showBack"
        class="icon-btn"
        @click="emit('back')"
      >
        <ArrowLeft :size="20" />
      </button>
      <div class="topbar-title-section">
        <h1 class="topbar-title">{{ title }}</h1>
        <p v-if="subtitle" class="topbar-subtitle">{{ subtitle }}</p>
      </div>
    </div>

    <!-- 右侧：操作区域 -->
    <div class="topbar-right">
      <slot name="actions">
        <button class="icon-btn" @click="emit('menu')">
          <MoreVertical :size="20" />
        </button>
      </slot>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  height: 56px;
  padding: 0 var(--space-4);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  transition: transform var(--transition-base) ease;
}

.topbar-fixed {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
}

.topbar-title-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.topbar-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  line-height: var(--line-height-tight);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topbar-subtitle {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  line-height: var(--line-height-normal);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.icon-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.icon-btn:active {
  background: var(--bg-card-hover);
  transform: scale(0.95);
}
</style>
