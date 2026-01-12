<script setup lang="ts">
/**
 * AppBar - 应用顶部导航栏组件（重构版）
 *
 * 规则：
 * - 右侧只显示"页面主操作"（通过 slot 传入）
 * - 其他操作折叠到"更多"菜单
 */

import { ref } from 'vue'

interface Props {
  title?: string
  showMenu?: boolean
}

withDefaults(defineProps<Props>(), {
  title: '',
  showMenu: true,
})

const emit = defineEmits<{
  menuClick: []
  moreClick: [key: string]
}>()

// 更多菜单展开状态
const moreMenuOpen = ref(false)

// 更多菜单项
interface MoreMenuItem {
  key: string
  label: string
  icon: string
  action?: () => void
}

const moreMenuItems: MoreMenuItem[] = [
  { key: 'search', label: '搜索', icon: 'search' },
  { key: 'notifications', label: '通知', icon: 'bell' },
  { key: 'refresh', label: '刷新', icon: 'refresh' },
]

const handleMoreClick = (item: MoreMenuItem) => {
  moreMenuOpen.value = false
  if (item.action) {
    item.action()
  } else {
    emit('moreClick', item.key)
  }
}
</script>

<template>
  <!-- 固定顶部导航栏 -->
  <header class="admin-appbar">
    <div class="admin-appbar__content">
      <!-- 左侧：菜单按钮 + 标题 -->
      <div class="admin-appbar__left">
        <button
          v-if="showMenu"
          @click="emit('menuClick')"
          class="admin-appbar__menu-btn"
          aria-label="菜单"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>

        <h1 class="admin-appbar__title">{{ title }}</h1>
      </div>

      <!-- 右侧：主操作 + 更多菜单 -->
      <div class="admin-appbar__right">
        <!-- 页面主操作（由父组件传入） -->
        <div v-if="$slots.primary" class="admin-appbar__primary">
          <slot name="primary" />
        </div>

        <!-- 更多菜单按钮 -->
        <div class="admin-appbar__more-wrapper">
          <button
            @click="moreMenuOpen = !moreMenuOpen"
            class="admin-appbar__more-btn"
            aria-label="更多"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
            </svg>
          </button>

          <!-- 更多菜单下拉 -->
          <div v-if="moreMenuOpen" class="admin-appbar__more-menu">
            <button
              v-for="item in moreMenuItems"
              :key="item.key"
              @click="handleMoreClick(item)"
              class="admin-appbar__more-item"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <!-- 搜索图标 -->
                <path v-if="item.key === 'search'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                <!-- 通知图标 -->
                <path v-else-if="item.key === 'notifications'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                <!-- 刷新图标 -->
                <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              <span>{{ item.label }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </header>

  <!-- 占位：固定顶部的高度 -->
  <div class="admin-appbar__spacer"></div>

  <!-- 点击外部关闭更多菜单 -->
  <div
    v-if="moreMenuOpen"
    @click="moreMenuOpen = false"
    class="admin-appbar__overlay"
  ></div>
</template>

<style scoped>
.admin-appbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 200;
  height: 56px;
  background: rgba(20, 20, 20, 0.9);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.admin-appbar__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  padding: 0 16px;
  max-width: 100%;
}

.admin-appbar__left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.admin-appbar__menu-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 50%;
  color: rgba(255, 255, 255, 0.85);
  cursor: pointer;
  flex-shrink: 0;
}

.admin-appbar__menu-btn:active {
  background: rgba(255, 255, 255, 0.1);
}

.admin-appbar__title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
  color: #ffffff;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-appbar__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-appbar__primary {
  display: flex;
  align-items: center;
}

.admin-appbar__more-wrapper {
  position: relative;
}

.admin-appbar__more-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 50%;
  color: rgba(255, 255, 255, 0.85);
  cursor: pointer;
}

.admin-appbar__more-btn:active {
  background: rgba(255, 255, 255, 0.1);
}

.admin-appbar__more-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 160px;
  background: rgba(30, 30, 30, 0.95);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.admin-appbar__more-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  background: transparent;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  cursor: pointer;
  text-align: left;
}

.admin-appbar__more-item:active {
  background: rgba(255, 255, 255, 0.1);
}

.admin-appbar__spacer {
  height: 56px;
}

.admin-appbar__overlay {
  position: fixed;
  top: 56px;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 199;
  background: transparent;
}
</style>
