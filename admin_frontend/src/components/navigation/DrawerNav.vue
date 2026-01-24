<script setup lang="ts">
/**
 * DrawerNav - 侧边抽屉导航组件（重构版）
 *
 * 使用统一的导航配置，自动从 navigation.ts 获取菜单数据
 */

import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getDrawerGroups, type DrawerGroup } from '@/routes/navigation'

interface Props {
  open?: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  close: []
}>()

const router = useRouter()
const route = useRoute()

// 从导航配置获取分组数据
const menuGroups = computed<DrawerGroup[]>(() => getDrawerGroups())

// 分组展开状态
const expandedGroups = ref<Set<string>>(new Set())

// 当前激活路径
const activePath = computed(() => route.path)

// 初始化：当前激活项所在的分组自动展开
menuGroups.value.forEach(group => {
  const hasActive = group.items.some(item =>
    activePath.value === item.path ||
    (item.path.includes(':id') && activePath.value.startsWith(item.path.split('/:')[0] + '/'))
  )
  if (hasActive) {
    expandedGroups.value.add(group.name)
  }
})

// 切换分组展开/折叠
function toggleGroup(groupName: string) {
  if (expandedGroups.value.has(groupName)) {
    expandedGroups.value.delete(groupName)
  } else {
    expandedGroups.value.add(groupName)
  }
}

// 检查分组是否展开
function isGroupExpanded(groupName: string): boolean {
  return expandedGroups.value.has(groupName)
}

// 检查分组是否有激活项
function groupHasActive(groupName: string): boolean {
  const group = menuGroups.value.find(g => g.name === groupName)
  if (!group) return false
  return group.items.some(item => {
    if (item.path.includes(':id')) {
      const basePattern = item.path.split('/:')[0]
      return activePath.value.startsWith(basePattern + '/')
    }
    return activePath.value === item.path
  })
}

// 检查菜单项是否激活
function isItemActive(itemPath: string): boolean {
  if (itemPath.includes(':id')) {
    const basePattern = itemPath.split('/:')[0]
    return activePath.value.startsWith(basePattern + '/')
  }
  return activePath.value === itemPath
}

function handleNav(path: string) {
  router.push(path)
  emit('close')
}

// 图标映射（使用 SVG path）
const iconPaths: Record<string, string> = {
  chart: 'M3 3v18h18M18 9l-5-5-4 4-3-3',
  heatmap: 'M3 3h7v7H3V3zm11 0h7v7h-7V3zM3 14h7v7H3v-7zm11 0h7v7h-7v-7z',
  fire: 'M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z',
  trending: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
  users: 'M17 20v-2a4 4 0 00-4-4H9a4 4 0 00-4 4v2M12 12a4 4 0 100-8 4 4 0 000 8z',
  crown: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z',
  ticket: 'M15 5v2M15 11v2M15 17v2M5 5h14a2 2 0 012 2v3a2 2 0 100 4v3a2 2 0 01-2 2H5a2 2 0 01-2-2v-3a2 2 0 100-4V7a2 2 0 012-2z',
  invite: 'M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71',
  server: 'M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2',
  online: 'M12 2a10 10 0 100 20 10 10 0 000-20zM12 12a2 2 0 100-4 2 2 0 000 4z',
  transcode: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
  'ticket-detail': 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
  request: 'M12 6v6m0 0v6m0-6h6m-6 0H6',
  settings: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z',
  config: 'M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4',
  shield: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
  admin: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
  role: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z',
  log: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
  announce: 'M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z',
  message: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
  payment: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
  order: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
  route: 'M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7',
  user: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
}
</script>

<template>
  <!-- 遮罩层 -->
  <Transition name="fade">
    <div
      v-if="open"
      class="admin-drawer__overlay"
      @click="emit('close')"
    />
  </Transition>

  <!-- 侧边栏 -->
  <Transition name="slide-left">
    <div v-if="open" class="admin-drawer">
      <!-- 顶部：关闭按钮 -->
      <div class="admin-drawer__header">
        <div class="admin-drawer__logo">
          <div class="admin-drawer__logo-icon">R</div>
          <span class="admin-drawer__logo-text">RoyalBot</span>
        </div>
        <button
          @click="emit('close')"
          class="admin-drawer__close-btn"
          aria-label="关闭"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- 菜单组 -->
      <div class="admin-drawer__content">
        <div v-for="group in menuGroups" :key="group.name" class="admin-drawer__group">
          <!-- 分组标题 -->
          <button
            @click="toggleGroup(group.name)"
            class="admin-drawer__group-header"
            :class="{ 'admin-drawer__group-header--active': groupHasActive(group.name) }"
          >
            <span>{{ group.name }}</span>
            <svg
              class="admin-drawer__group-arrow"
              :class="{ 'admin-drawer__group-arrow--expanded': isGroupExpanded(group.name) }"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          <!-- 菜单项 -->
          <Transition name="expand">
            <div v-if="isGroupExpanded(group.name)" class="admin-drawer__items">
              <button
                v-for="item in group.items"
                :key="item.path"
                @click="handleNav(item.path)"
                class="admin-drawer__item"
                :class="{ 'admin-drawer__item--active': isItemActive(item.path) }"
              >
                <svg class="admin-drawer__item-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="iconPaths[item.icon] || iconPaths.settings" />
                </svg>
                <span class="admin-drawer__item-label">{{ item.name }}</span>
                <span
                  v-if="isItemActive(item.path)"
                  class="admin-drawer__item-dot"
                />
              </button>
            </div>
          </Transition>
        </div>
      </div>

      <!-- 底部：用户信息 -->
      <div class="admin-drawer__footer">
        <button class="admin-drawer__user">
          <div class="admin-drawer__user-avatar">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <div class="admin-drawer__user-info">
            <p class="admin-drawer__user-name">管理员</p>
            <p class="admin-drawer__user-email">admin@royalbot.com</p>
          </div>
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* 遮罩层 */
.admin-drawer__overlay {
  position: fixed;
  inset: 0;
  z-index: 250;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
}

/* 侧边栏容器 */
.admin-drawer {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 250;
  width: 288px;
  max-width: 85vw;
  background: rgba(20, 20, 20, 0.98);
  border-right: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
}

/* 顶部 */
.admin-drawer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.admin-drawer__logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.admin-drawer__logo-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: white;
}

.admin-drawer__logo-text {
  font-size: 16px;
  font-weight: 600;
  color: white;
}

.admin-drawer__close-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  cursor: pointer;
}

.admin-drawer__close-btn:active {
  background: rgba(255, 255, 255, 0.1);
}

/* 内容区 */
.admin-drawer__content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 12px;
}

.admin-drawer__group {
  margin-bottom: 16px;
}

.admin-drawer__group-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: rgba(255, 255, 255, 0.4);
  border: none;
  background: transparent;
  cursor: pointer;
  transition: color 0.2s;
}

.admin-drawer__group-header:active,
.admin-drawer__group-header--active {
  color: #10b981;
}

.admin-drawer__group-arrow {
  width: 16px;
  height: 16px;
  transition: transform 0.2s;
}

.admin-drawer__group-arrow--expanded {
  transform: rotate(180deg);
}

.admin-drawer__items {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.admin-drawer__item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  padding: 0 12px;
  border: none;
  background: transparent;
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  transition: all 0.15s;
}

.admin-drawer__item:active {
  background: rgba(255, 255, 255, 0.05);
}

.admin-drawer__item--active {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.admin-drawer__item-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.admin-drawer__item-label {
  flex: 1;
  text-align: left;
  font-size: 14px;
}

.admin-drawer__item-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

/* 底部 */
.admin-drawer__footer {
  padding: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.admin-drawer__user {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-height: 48px;
  padding: 0 12px;
  border: none;
  background: transparent;
  border-radius: 10px;
  cursor: pointer;
}

.admin-drawer__user:active {
  background: rgba(255, 255, 255, 0.05);
}

.admin-drawer__user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(16, 185, 129, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #10b981;
}

.admin-drawer__user-info {
  flex: 1;
  text-align: left;
}

.admin-drawer__user-name {
  font-size: 14px;
  font-weight: 500;
  color: white;
  margin: 0;
}

.admin-drawer__user-email {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  margin: 2px 0 0 0;
}

/* 动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-left-enter-active,
.slide-left-leave-active {
  transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
}

.slide-left-enter-from,
.slide-left-leave-to {
  transform: translateX(-100%);
}

.expand-enter-active,
.expand-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 500px;
  opacity: 1;
}
</style>
