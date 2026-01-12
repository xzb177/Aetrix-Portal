<script setup lang="ts">
/**
 * TabBar - 底部导航栏组件
 *
 * 固定在页面底部的标签导航栏，高度 64-72px。
 *
 * @props
 * - tabs: 标签配置数组 { key, label, icon }
 * - active: 当前激活的标签 key
 */

export interface Tab {
  key: string
  label: string
  icon: string  // 图标 URL
  badge?: number | string  // 徽章数字/文字
}

interface Props {
  tabs: Tab[]
  active: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  change: [key: string]
}>()

const handleChange = (key: string) => {
  emit('change', key)
}
</script>

<template>
  <nav class="ui-tabbar">
    <div class="ui-tabbar__content">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="ui-tabbar__item"
        :class="{ 'ui-tabbar__item--active': tab.key === active }"
        @click="handleChange(tab.key)"
      >
        <div class="ui-tabbar__icon-wrapper">
          <img :src="tab.icon" alt="" class="ui-tabbar__icon">
          <span v-if="tab.badge" class="ui-tabbar__badge">{{ tab.badge }}</span>
        </div>
        <span class="ui-tabbar__label">{{ tab.label }}</span>
      </button>
    </div>
    <!-- 安全区域适配 -->
    <div class="ui-tabbar__safe-area"></div>
  </nav>
</template>

<style scoped>
.ui-tabbar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--tabbar-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--tabbar-border);
  z-index: var(--z-tabbar);
  padding-bottom: env(safe-area-inset-bottom, 0);
}

.ui-tabbar__content {
  display: flex;
  height: var(--tabbar-height);
  max-width: 600px;
  margin: 0 auto;
}

.ui-tabbar__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 0;
  transition: color var(--duration-fast) var(--ease-out);
}

.ui-tabbar__icon-wrapper {
  position: relative;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ui-tabbar__icon {
  width: 24px;
  height: 24px;
  color: var(--tabbar-inactive);
  transition: color var(--duration-fast) var(--ease-out);
}

.ui-tabbar__item--active .ui-tabbar__icon {
  color: var(--tabbar-active);
}

.ui-tabbar__badge {
  position: absolute;
  top: -4px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  background: var(--color-danger);
  color: white;
  font-size: 10px;
  font-weight: 600;
  line-height: 16px;
  text-align: center;
  border-radius: 8px;
}

.ui-tabbar__badge:not(:empty) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.ui-tabbar__label {
  font-size: 11px;
  font-weight: 500;
  line-height: 1.3;
  color: var(--tabbar-inactive);
  transition: color var(--duration-fast) var(--ease-out);
}

.ui-tabbar__item--active .ui-tabbar__label {
  color: var(--tabbar-active);
}

.ui-tabbar__item:active {
  opacity: 0.7;
}

/* 安全区域占位（非刘海屏） */
.ui-tabbar__safe-area {
  display: none;
}

@supports (padding-bottom: env(safe-area-inset-bottom)) {
  .ui-tabbar__safe-area {
    display: none;
  }
}
</style>
