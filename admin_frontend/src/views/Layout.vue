<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  Home,
  Users,
  CreditCard,
  MessageSquare,
  Megaphone,
  Settings,
  LogOut,
  Menu,
  Server,
  FileText,
  Flame,
  Film,
  X,
  Gift,
  ChevronRight,
  Zap,
  Eye,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import DrawerNav from '@/components/navigation/DrawerNav.vue'
import AppBar from '@/components/navigation/AppBar.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// 侧边栏展开状态
const sidebarOpen = ref(false)
const sidebarCollapsed = ref(false)

// 侧边栏宽度状态 - EmbyController 风格可拖动
const sidebarWidth = ref(256)
const minWidth = 200
const maxWidth = 400
const isResizing = ref(false)

// 菜单项配置（支持二级菜单）
interface MenuItem {
  path: string
  title: string
  icon: any
  permission: string
  children?: MenuItem[]
}

// 完整菜单配置 - 参考 EmbyController 精简结构
const allMenuItems: MenuItem[] = [
  // 核心导航（10个主要菜单，参考 EmbyController）
  { path: '/', title: '数据概览', icon: Home, permission: 'stats.view' },

  // 用户管理
  { path: '/portal-users', title: '门户用户', icon: Users, permission: 'users.view' },

  // 兑换码管理
  { path: '/exchange-codes', title: '兑换码管理', icon: Gift, permission: 'users.view' },

  // 邀请管理
  { path: '/invitations', title: '邀请管理', icon: Users, permission: 'users.view' },

  // 订阅管理
  { path: '/subscriptions', title: '订阅套餐', icon: CreditCard, permission: 'subscriptions.view' },

  // Emby 管理
  { path: '/emby-servers', title: 'Emby服务器', icon: Server, permission: 'emby.view' },
  { path: '/online-sessions', title: '在线用户', icon: Eye, permission: 'emby.view' },
  { path: '/transcoding', title: '转码监控', icon: Zap, permission: 'emby.view' },

  // Emby 数据（子菜单概念）
  { path: '/heatmap', title: '播放热力', icon: Flame, permission: 'stats.view' },

  // 工单系统
  { path: '/tickets', title: '工单系统', icon: MessageSquare, permission: 'tickets.view' },

  // 内容管理
  { path: '/media-requests', title: '求片管理', icon: Film, permission: 'content.view' },

  // 公告管理
  { path: '/announcements', title: '公告管理', icon: Megaphone, permission: 'announcements.view' },

  // 系统日志
  { path: '/system-logs', title: '操作日志', icon: FileText, permission: 'system.logs' },

  // 系统配置
  { path: '/system-config', title: '系统配置', icon: Settings, permission: 'system.config' },

  // 系统设置
  { path: '/settings', title: '个人设置', icon: Settings, permission: 'system.config' },
]

// 检查菜单是否激活
const isMenuActive = (path: string): boolean => {
  return path === route.path
}

// 根据权限过滤菜单
const menuItems = computed<MenuItem[]>(() => {
  return allMenuItems.filter(item => authStore.hasPermission(item.permission))
})

// ==================== DrawerNav 分组菜单配置 ====================
interface DrawerMenuItem {
  id: string
  label: string
  icon: string
  path: string
  disabled?: boolean
}

interface MenuGroup {
  title: string
  items: DrawerMenuItem[]
}

// 图标名称映射（DrawerNav 使用 SVG symbol）
const iconMap: Record<string, string> = {
  [Home.name]: 'icon-home',
  [Users.name]: 'icon-users',
  [CreditCard.name]: 'icon-credit-card',
  [MessageSquare.name]: 'icon-message',
  [Megaphone.name]: 'icon-megaphone',
  [Settings.name]: 'icon-settings',
  [Server.name]: 'icon-server',
  [FileText.name]: 'icon-file-text',
  [Flame.name]: 'icon-flame',
  [Film.name]: 'icon-film',
  [Gift.name]: 'icon-gift',
  [Zap.name]: 'icon-zap',
  [Eye.name]: 'icon-eye',
}

const drawerMenuGroups = computed<MenuGroup[]>(() => {
  // 根据权限过滤后的菜单项
  const availableItems = menuItems.value

  return [
    {
      title: '概览',
      items: availableItems
        .filter(item => item.path === '/')
        .map(item => ({
          id: item.path,
          label: item.title,
          icon: iconMap[item.icon.name] || 'icon-home',
          path: item.path,
        })),
    },
    {
      title: '用户',
      items: availableItems
        .filter(item =>
          ['/portal-users', '/subscriptions', '/exchange-codes', '/invitations'].includes(item.path)
        )
        .map(item => ({
          id: item.path,
          label: item.title,
          icon: iconMap[item.icon.name] || 'icon-users',
          path: item.path,
        })),
    },
    {
      title: '业务',
      items: availableItems
        .filter(item =>
          ['/tickets', '/media-requests', '/announcements', '/messages'].includes(item.path)
        )
        .map(item => ({
          id: item.path,
          label: item.title,
          icon: iconMap[item.icon.name] || 'icon-message',
          path: item.path,
        })),
    },
    {
      title: '资源与服务',
      items: availableItems
        .filter(item =>
          ['/emby-servers', '/online-sessions', '/transcoding', '/heatmap', '/payment-orders'].includes(item.path)
        )
        .map(item => ({
          id: item.path,
          label: item.title,
          icon: iconMap[item.icon.name] || 'icon-server',
          path: item.path,
        })),
    },
    {
      title: '系统',
      items: availableItems
        .filter(item =>
          ['/system-logs', '/system-config', '/settings', '/admins', '/roles', '/security', '/payment-config'].includes(item.path)
        )
        .map(item => ({
          id: item.path,
          label: item.title,
          icon: iconMap[item.icon.name] || 'icon-settings',
          path: item.path,
        })),
    },
  ].filter(group => group.items.length > 0)
})

// 当前激活的菜单项
const activeMenu = computed(() => route.path)

// ==================== 移动端检测 ====================
const isMobile = ref(false)
const MOBILE_BREAKPOINT = 1024

const checkMobile = () => {
  isMobile.value = window.innerWidth < MOBILE_BREAKPOINT
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})

// ==================== 移动端 AppBar ====================
// 移动端页面标题
const mobilePageTitle = computed(() => {
  return route.meta.title as string || '控制台'
})

// 跳转到指定路径
const navigateTo = (path: string) => {
  router.push(path)
  if (window.innerWidth < 1024) {
    sidebarOpen.value = false
  }
}

// 登出
const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}

// 获取页面标题
const getPageTitle = (path: string): string => {
  const item = allMenuItems.find(i => i.path === path)
  return item?.title || route.meta.title as string || '控制台'
}

const pageTitle = computed(() => getPageTitle(route.path))

// 侧边栏宽度拖动功能 - EmbyController 风格
const startResize = (e: MouseEvent) => {
  e.preventDefault()
  isResizing.value = true
  document.addEventListener('mousemove', handleResize)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

const handleResize = (e: MouseEvent) => {
  if (!isResizing.value) return
  const newWidth = e.clientX
  if (newWidth >= minWidth && newWidth <= maxWidth) {
    sidebarWidth.value = newWidth
  }
}

const stopResize = () => {
  isResizing.value = false
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// 清理事件监听
onUnmounted(() => {
  if (isResizing.value) {
    stopResize()
  }
})
</script>

<template>
  <div class="layout">
    <!-- ==================== 移动端：顶部 AppBar ==================== -->
    <AppBar
      v-if="isMobile"
      :title="mobilePageTitle"
      :show-search="false"
      :show-notification="false"
      :show-menu="true"
      @menu-click="sidebarOpen = true"
    />

    <!-- ==================== 移动端：Drawer 导航 ==================== -->
    <Teleport to="body">
      <!-- SVG 图标定义（供 DrawerNav 使用） -->
      <svg class="hidden">
        <!-- 概览 -->
        <symbol id="icon-home" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" stroke-linecap="round" stroke-linejoin="round"/>
          <polyline points="9,22 9,12 15,12 15,22" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 用户 -->
        <symbol id="icon-users" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="9" cy="7" r="4"/>
          <path d="M23 21v-2a4 4 0 0 0-3-3.87" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M16 3.13a4 4 0 0 1 0 7.75" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 订阅/卡片 -->
        <symbol id="icon-credit-card" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="1" y="4" width="22" height="16" rx="2" ry="2" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="1" y1="10" x2="23" y2="10" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 消息/工单 -->
        <symbol id="icon-message" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 公告 -->
        <symbol id="icon-megaphone" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 11l6-6v12l-6-6z" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M17.57 11.57a2 2 0 0 0 0-2.83l-1.41-1.41a2 2 0 0 0-2.83 0L9 11" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M3 11v4a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-4" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 设置 -->
        <symbol id="icon-settings" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </symbol>
        <!-- 服务器/Emby -->
        <symbol id="icon-server" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="2" width="20" height="8" rx="2" ry="2" stroke-linecap="round" stroke-linejoin="round"/>
          <rect x="2" y="14" width="20" height="8" rx="2" ry="2" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="6" y1="6" x2="6.01" y2="6" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="6" y1="18" x2="6.01" y2="18" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 日志/文件 -->
        <symbol id="icon-file-text" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke-linecap="round" stroke-linejoin="round"/>
          <polyline points="14,2 14,8 20,8" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="16" y1="13" x2="8" y2="13" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="16" y1="17" x2="8" y2="17" stroke-linecap="round" stroke-linejoin="round"/>
          <polyline points="10,9 9,9 8,9" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 热力/火焰 -->
        <symbol id="icon-flame" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 电影/求片 -->
        <symbol id="icon-film" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="7" y1="2" x2="7" y2="22" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="17" y1="2" x2="17" y2="22" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="2" y1="12" x2="22" y2="12" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="2" y1="7" x2="7" y2="7" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="2" y1="17" x2="7" y2="17" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="17" y1="17" x2="22" y2="17" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="17" y1="7" x2="22" y2="7" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 礼物/兑换码 -->
        <symbol id="icon-gift" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20,12 20,22 4,22 4,12" stroke-linecap="round" stroke-linejoin="round"/>
          <rect x="2" y="7" width="20" height="5" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="12" y1="22" x2="12" y2="7" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 闪电/转码 -->
        <symbol id="icon-zap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="13,2 3,14 12,14 11,22 21,10 12,10 13,2" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
        <!-- 眼睛/在线 -->
        <symbol id="icon-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke-linecap="round" stroke-linejoin="round"/>
          <circle cx="12" cy="12" r="3" stroke-linecap="round" stroke-linejoin="round"/>
        </symbol>
      </svg>

      <!-- Drawer 导航（移动端 + 桌面端侧边栏收起时） -->
      <DrawerNav
        :open="sidebarOpen && isMobile"
        :groups="drawerMenuGroups"
        @close="sidebarOpen = false"
      />
    </Teleport>

    <!-- ==================== 桌面端：侧边栏 + 遮罩 ==================== -->
    <!-- 移动端遮罩 -->
    <Transition name="fade">
      <div
        v-if="sidebarOpen"
        class="sidebar-overlay"
        @click="sidebarOpen = false"
      />
    </Transition>

    <!-- 侧边栏 - 仅桌面端显示 -->
    <aside
      :class="[
        'sidebar',
        sidebarOpen ? 'sidebar-open' : '',
        sidebarCollapsed ? 'sidebar-collapsed' : ''
      ]"
      :style="!sidebarCollapsed ? { width: `${sidebarWidth}px` } : {}"
    >
      <!-- Logo 区域 -->
      <div class="sidebar-logo">
        <div class="logo-wrapper">
          <div class="logo-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <Transition name="slide">
            <div v-if="!sidebarCollapsed" class="logo-text">
              <span class="logo-name">Aetrix</span>
              <span class="logo-tag">管理后台</span>
            </div>
          </Transition>
        </div>
        <button class="mobile-close" @click="sidebarOpen = false">
          <X :size="18" />
        </button>
      </div>

      <!-- 导航菜单 -->
      <nav class="sidebar-nav">
        <button
          v-for="item in menuItems"
          :key="item.path"
          :class="[
            'nav-item',
            isMenuActive(item.path) ? 'nav-item-active' : ''
          ]"
          @click="navigateTo(item.path)"
        >
          <component :is="item.icon" :size="18" />
          <Transition name="slide">
            <span v-if="!sidebarCollapsed" class="nav-label">{{ item.title }}</span>
          </Transition>
          <ChevronRight
            v-if="!sidebarCollapsed && isMenuActive(item.path)"
            :size="14"
            class="nav-arrow"
          />
        </button>
      </nav>

      <!-- 底部用户区 -->
      <div class="sidebar-footer">
        <div v-if="!sidebarCollapsed" class="user-info">
          <div class="user-avatar">
            {{ authStore.adminInfo?.username?.charAt(0).toUpperCase() || 'A' }}
          </div>
          <div class="user-details">
            <p class="user-name">{{ authStore.adminInfo?.username || 'Admin' }}</p>
            <p class="user-role">管理员</p>
          </div>
        </div>
        <div v-else class="user-avatar-only">
          {{ authStore.adminInfo?.username?.charAt(0).toUpperCase() || 'A' }}
        </div>
        <button
          v-if="!sidebarCollapsed"
          class="logout-link"
          @click="handleLogout"
        >
          <LogOut :size="16" />
          <span>退出登录</span>
        </button>
        <button v-else class="logout-icon" @click="handleLogout">
          <LogOut :size="16" />
        </button>
      </div>

      <!-- 拖动调整手柄 - EmbyController 风格 -->
      <div
        v-if="!sidebarCollapsed"
        class="resizer"
        @mousedown="startResize"
        :class="{ 'resizing': isResizing }"
      >
        <div class="resizer-line"></div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="main">
      <!-- 顶部栏 -->
      <header class="header">
        <div class="header-content">
          <!-- 左侧 -->
          <div class="header-left">
            <button class="menu-toggle" @click="sidebarOpen = !sidebarOpen">
              <Menu :size="20" />
            </button>
            <h1 class="page-title">{{ pageTitle }}</h1>
          </div>

          <!-- 右侧 -->
          <div class="header-right">
            <button
              class="icon-btn hidden lg:flex"
              @click="sidebarCollapsed = !sidebarCollapsed"
              title="折叠侧边栏"
            >
              <Menu :size="18" />
            </button>
          </div>
        </div>
      </header>

      <!-- 内容区 -->
      <main class="content">
        <Transition name="page" mode="out-in">
          <router-view :key="route.path" />
        </Transition>
      </main>
    </div>
  </div>
</template>

<style scoped>
/* ==================== Layout - 统一暗色玻璃态风格 ==================== */
.layout {
  display: flex;
  min-height: 100vh;
  background: #0a0a0a;
}

/* ==================== Sidebar - 暗色玻璃态（仅桌面端） ==================== */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  width: 256px;
  background: rgba(20, 20, 20, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  display: flex;
  flex-direction: column;
  z-index: 50;
  transition: transform 0.3s ease, width 0.1s ease;
  border-right: 1px solid rgba(255, 255, 255, 0.1);
}

/* 移动端：完全隐藏侧边栏 */
@media (max-width: 1023px) {
  .sidebar {
    display: none;
  }
}

/* 桌面端：始终显示侧边栏 */
@media (min-width: 1024px) {
  .sidebar {
    transform: translateX(0);
    display: flex;
  }
}

.sidebar-open {
  transform: translateX(0) !important;
}

.sidebar-collapsed {
  width: 70px !important;
}

/* 遮罩 */
.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  z-index: 40;
}

@media (min-width: 1024px) {
  .sidebar-overlay {
    display: none;
  }
}

/* Logo */
.sidebar-logo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  min-height: 65px;
}

.logo-wrapper {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo-icon {
  width: 34px;
  height: 34px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.85);
  flex-shrink: 0;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.2);
}

.logo-icon svg {
  width: 18px;
  height: 18px;
}

.logo-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo-name {
  font-size: 0.95rem;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: -0.02em;
}

.logo-tag {
  font-size: 0.65rem;
  color: #673AB7;
  font-weight: 500;
}

.mobile-close {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #737373;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

@media (min-width: 1024px) {
  .mobile-close {
    display: none;
  }
}

.mobile-close:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
}

/* 导航 */
.sidebar-nav {
  flex: 1;
  padding: 1rem 0.75rem;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar-nav::-webkit-scrollbar {
  width: 3px;
}

.sidebar-nav::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.7rem 0.875rem;
  margin-bottom: 0.25rem;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: #a3a3a3;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
  position: relative;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #ffffff;
}

.nav-item-active {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.2) 0%, rgba(103, 58, 183, 0.2) 100%);
  color: #4CAF50;
  box-shadow: 0 0 20px rgba(76, 175, 80, 0.15);
}

.nav-item-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 60%;
  background: linear-gradient(180deg, #4CAF50 0%, #673AB7 100%);
  border-radius: 0 2px 2px 0;
  box-shadow: 0 0 10px rgba(76, 175, 80, 0.5);
}

.nav-item-active:hover {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.25) 0%, rgba(103, 58, 183, 0.25) 100%);
}

.nav-arrow {
  margin-left: auto;
  opacity: 0.7;
}

.nav-label {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 二级菜单 */
.submenu {
  padding-left: 0.5rem;
  margin-bottom: 0.25rem;
}

.submenu-enter-active,
.submenu-leave-active {
  transition: all 0.2s ease;
}

.submenu-enter-from,
.submenu-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.submenu-item {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  padding: 0.6rem 0.875rem;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #a3a3a3;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
  margin-bottom: 0.125rem;
}

.submenu-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #ffffff;
}

.submenu-item-active {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
  font-weight: 500;
}

/* 底部用户区 */
.sidebar-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.2);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  flex: 1;
  overflow: hidden;
}

.user-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #4CAF50 0%, #673AB7 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 600;
  color: white;
  flex-shrink: 0;
}

.user-avatar-only {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #4CAF50 0%, #673AB7 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 600;
  color: white;
}

.user-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.user-name {
  font-size: 0.8rem;
  font-weight: 500;
  color: #ffffff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 0.7rem;
  color: #737373;
}

.logout-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #737373;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.logout-link:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.logout-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #737373;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.logout-icon:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

/* ==================== 拖动调整手柄 ==================== */
.resizer {
  position: absolute;
  top: 0;
  right: 0;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
  transition: background 0.2s ease;
}

.resizer:hover,
.resizer.resizing {
  background: rgba(76, 175, 80, 0.3);
}

.resizer-line {
  position: absolute;
  top: 0;
  right: 2px;
  width: 2px;
  height: 100%;
  background: transparent;
  transition: background 0.2s ease;
}

.resizer:hover .resizer-line,
.resizer.resizing .resizer-line {
  background: #4CAF50;
}

/* ==================== Main ==================== */
.main {
  flex: 1;
  margin-left: 0;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: #0a0a0a;
  transition: margin-left 0.3s ease;
}

/* 移动端：无左边距，内容全宽，无底部导航 */
@media (max-width: 1023px) {
  .main {
    margin-left: 0;
    padding-top: 56px; /* 为移动端 AppBar 预留空间 */
    padding-bottom: 0; /* 移除底部导航预留空间 */
  }
}

/* 桌面端：侧边栏显示时，主内容区有左边距 */
@media (min-width: 1024px) {
  .main {
    margin-left: 256px;
  }

  .sidebar-collapsed ~ .main {
    margin-left: 70px;
  }
}

/* ==================== Header - 仅桌面端 ==================== */
.header {
  position: sticky;
  top: 0;
  z-index: 30;
  height: 60px;
  background: rgba(20, 20, 20, 0.8);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

/* 移动端：隐藏顶部栏 */
@media (max-width: 1023px) {
  .header {
    display: none;
  }
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  padding: 0 1.5rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.menu-toggle {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: #a3a3a3;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

@media (min-width: 1024px) {
  .menu-toggle {
    display: none;
  }
}

.menu-toggle:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #ffffff;
}

.page-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #ffffff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: none;
  background: transparent;
  color: #737373;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #ffffff;
}

/* ==================== Content ==================== */
.content {
  flex: 1;
  padding: 1.5rem;
  min-height: calc(100vh - 60px);
}

/* 移动端：内容区高度仅减去 AppBar */
@media (max-width: 1023px) {
  .content {
    min-height: calc(100vh - 56px); /* 仅减去 AppBar 高度 */
  }
}

@media (max-width: 768px) {
  .content {
    padding: 1rem;
  }
}

/* ==================== Transitions ==================== */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  width: 0;
}

.page-enter-active {
  transition: all 0.3s ease;
}

.page-leave-active {
  transition: all 0.2s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(12px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
