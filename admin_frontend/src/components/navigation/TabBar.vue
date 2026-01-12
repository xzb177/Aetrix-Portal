<script setup lang="ts">
/**
 * TabBar - 底部 Tab 导航组件
 *
 * 管理后台专用，固定 5 个 Tab：首页/用户/Emby/工单/设置
 *
 * @props
 * - tabs: Tab 配置数组
 * - active: 当前激活的 Tab key
 */

export interface Tab {
  key: string
  label: string
  icon: string
  iconActive: string
  defaultRoute: string
}

interface Props {
  tabs: Tab[]
  active: string
}

interface Emits {
  (e: 'change', key: string): void
}

defineProps<Props>()
const emit = defineEmits<Emits>()

const handleClick = (key: string) => {
  emit('change', key)
}
</script>

<template>
  <nav class="admin-tabbar">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      class="admin-tabbar__item"
      :class="{ 'admin-tabbar__item--active': tab.key === active }"
      @click="handleClick(tab.key)"
    >
      <div class="admin-tabbar__icon-wrapper">
        <img
          :src="tab.key === active ? tab.iconActive : tab.icon"
          :alt="tab.label"
          class="admin-tabbar__icon"
        >
      </div>
      <span class="admin-tabbar__label">{{ tab.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.admin-tabbar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  background: rgba(20, 20, 20, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  z-index: 100;
  padding-bottom: env(safe-area-inset-bottom, 0);
}

.admin-tabbar__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 0;
  min-height: 56px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.5);
  transition: color 0.2s ease;
}

.admin-tabbar__item--active {
  color: #10b981;
}

.admin-tabbar__item:active {
  opacity: 0.7;
}

.admin-tabbar__icon-wrapper {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.admin-tabbar__icon {
  width: 24px;
  height: 24px;
}

.admin-tabbar__label {
  font-size: 11px;
  font-weight: 500;
  line-height: 1.3;
}
</style>
