<template>
  <button
    :class="['theme-toggle', { 'theme-toggle--active': isActive }]"
    @click="handleToggle"
    :aria-label="`当前主题：${themeLabel}`"
  >
    <Transition name="theme-icon" mode="out-in">
      <component :is="currentIcon" :key="resolvedTheme" class="theme-icon" />
    </Transition>
    <span class="theme-label" v-if="showLabel">{{ themeLabel }}</span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useThemeSingleton } from '@/composables/useTheme'

interface Props {
  showLabel?: boolean
  size?: 'sm' | 'md' | 'lg'
}

const props = withDefaults(defineProps<Props>(), {
  showLabel: false,
  size: 'md'
})

const { theme, resolvedTheme, toggleTheme, isDark } = useThemeSingleton()

const isActive = computed(() => isDark())

const themeLabel = computed(() => {
  switch (theme.value) {
    case 'auto':
      return '自动'
    case 'light':
      return '浅色'
    case 'dark':
      return '深色'
  }
})

// SVG 图标组件
const SunIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="5"/>
      <line x1="12" y1="1" x2="12" y2="3"/>
      <line x1="12" y1="21" x2="12" y2="23"/>
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
      <line x1="1" y1="12" x2="3" y2="12"/>
      <line x1="21" y1="12" x2="23" y2="12"/>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
    </svg>
  `
}

const MoonIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  `
}

const AutoIcon = {
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7H9V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  `
}

const currentIcon = computed(() => {
  if (resolvedTheme.value === 'dark') {
    return theme.value === 'auto' ? AutoIcon : MoonIcon
  }
  return SunIcon
})

const handleToggle = () => {
  toggleTheme()
}
</script>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--bg-glass);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border-glass);
  border-radius: 0.5rem;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-toggle:hover {
  background: var(--bg-elevated-hover);
  border-color: var(--border-glass-light);
}

.theme-toggle:active {
  transform: scale(0.98);
}

.theme-toggle--active {
  border-color: var(--brand-primary);
}

.theme-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.theme-label {
  font-size: 0.875rem;
  font-weight: 500;
}

/* 尺寸变体 */
.theme-toggle[data-size="sm"] {
  padding: 0.375rem 0.75rem;
}

.theme-toggle[data-size="sm"] .theme-icon {
  width: 16px;
  height: 16px;
}

.theme-toggle[data-size="sm"] .theme-label {
  font-size: 0.75rem;
}

.theme-toggle[data-size="lg"] {
  padding: 0.625rem 1.25rem;
}

.theme-toggle[data-size="lg"] .theme-icon {
  width: 24px;
  height: 24px;
}

.theme-toggle[data-size="lg"] .theme-label {
  font-size: 1rem;
}

/* 图标切换动画 */
.theme-icon-enter-active,
.theme-icon-leave-active {
  transition: all 0.2s ease;
}

.theme-icon-enter-from {
  opacity: 0;
  transform: scale(0.5) rotate(-180deg);
}

.theme-icon-leave-to {
  opacity: 0;
  transform: scale(0.5) rotate(180deg);
}
</style>
