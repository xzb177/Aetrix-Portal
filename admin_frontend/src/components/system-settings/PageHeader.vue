<!--
  PageHeader.vue
  iOS 风格系统配置页面 - 顶部 Sticky Header

  功能：
  - 左侧：菜单按钮
  - 中间：标题"系统配置"
  - 右侧：更多菜单(…)
-->
<script setup lang="ts">
import { MoreFilled } from '@element-plus/icons-vue'

interface Emits {
  (e: 'menuClick'): void
}

defineEmits<Emits>()
</script>

<template>
  <header class="page-header">
    <!-- 左侧菜单按钮 -->
    <button class="menu-btn" @click="$emit('menuClick')">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M3 6H17M3 10H17M3 14H17" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      </svg>
    </button>

    <!-- 中间标题 -->
    <h1 class="page-title">系统配置</h1>

    <!-- 右侧插槽（用于放置更多菜单等） -->
    <div class="header-actions">
      <slot name="actions"></slot>
    </div>
  </header>
</template>

<style scoped>
.page-header {
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 16px;
  background-color: #0B0D10;
  border-bottom: 1px solid #232A33;
}

/* 菜单按钮 */
.menu-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  color: #E7ECF2;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.menu-btn:hover {
  background-color: #171C23;
}

.menu-btn:active {
  background-color: #232A33;
  transform: scale(0.96);
}

/* 页面标题 */
.page-title {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #E7ECF2;
  pointer-events: none;
}

/* 右侧操作区 */
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 更多菜单按钮（默认样式，可被 slot 覆盖） */
:deep(.btn-more) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  color: #E7ECF2;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

:deep(.btn-more:hover) {
  background-color: #171C23;
}

:deep(.btn-more:active) {
  background-color: #232A33;
  transform: scale(0.96);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .page-header {
    height: 50px;
    padding: 0 12px;
  }

  .page-title {
    font-size: 16px;
  }
}
</style>
