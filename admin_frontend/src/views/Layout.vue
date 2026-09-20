<script setup lang="ts">
/** 管理后台布局：左侧导航 + 顶栏 + 内容区 */
import { ref } from 'vue'
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import {
  LayoutDashboard, Users, Ticket, Megaphone, Film, ScrollText,
  KeyRound, MessageSquareDashed, LogOut, Menu, X,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sidebarOpen = ref(false)

const nav = [
  { path: '/', label: '数据概览', icon: LayoutDashboard },
  { path: '/users', label: '用户管理', icon: Users },
  { path: '/codes', label: '注册码', icon: KeyRound },
  { path: '/announcements', label: '公告管理', icon: Megaphone },
  { path: '/tickets', label: '工单管理', icon: Ticket },
  { path: '/media-seek', label: '求片管理', icon: MessageSquareDashed },
  { path: '/emby', label: '媒体库', icon: Film },
  { path: '/logs', label: '操作日志', icon: ScrollText },
]

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="admin-layout">
    <!-- 移动端遮罩 -->
    <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false" />

    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-brand">
        <span class="brand-dot" />
        <span>RoyalBot Admin</span>
        <button class="sidebar-close" @click="sidebarOpen = false"><X :size="18" /></button>
      </div>
      <nav class="sidebar-nav">
        <RouterLink
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: route.path === item.path }"
          @click="sidebarOpen = false"
        >
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <div class="admin-who">
          <div class="who-avatar">{{ auth.admin?.username?.charAt(0).toUpperCase() || 'A' }}</div>
          <div class="who-info">
            <div class="who-name">{{ auth.admin?.username || '管理员' }}</div>
            <div class="who-role">管理员</div>
          </div>
        </div>
        <button class="logout-btn" @click="logout">
          <LogOut :size="16" />
          <span>退出登录</span>
        </button>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="admin-main">
      <header class="admin-topbar">
        <button class="menu-btn" @click="sidebarOpen = true"><Menu :size="20" /></button>
        <h1 class="topbar-page-title">{{ route.meta.title || '管理后台' }}</h1>
        <span class="topbar-badge">v2.2.0</span>
      </header>
      <main class="admin-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.admin-layout {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg-primary, #0a0a0a);
}

/* ===== 侧边栏 ===== */
.sidebar {
  width: 232px;
  flex-shrink: 0;
  background: var(--color-bg-secondary, #141414);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px;
  font-weight: 700;
  font-size: 15px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.brand-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.6);
}

.sidebar-close { display: none; margin-left: auto; background: none; border: none; color: inherit; cursor: pointer; }

.sidebar-nav {
  flex: 1;
  padding: 12px 10px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  color: var(--color-text-secondary, #a3a3a3);
  text-decoration: none;
  font-size: 14px;
  margin-bottom: 2px;
  transition: all 0.15s ease;
}

.nav-item:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.05);
}

.nav-item.active {
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
}

.sidebar-footer {
  padding: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.admin-who {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.who-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #10b981, #059669);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
}

.who-name { font-size: 13px; font-weight: 600; }
.who-role { font-size: 11px; color: var(--color-text-muted, #737373); }

.logout-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: transparent;
  color: var(--color-text-secondary, #a3a3a3);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.logout-btn:hover { color: #ef4444; border-color: rgba(239, 68, 68, 0.3); }

/* ===== 主区 ===== */
.admin-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.admin-topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  position: sticky;
  top: 0;
  background: rgba(10, 10, 10, 0.85);
  backdrop-filter: blur(10px);
  z-index: 10;
}

.menu-btn { display: none; background: none; border: none; color: inherit; cursor: pointer; }

.topbar-page-title { font-size: 16px; font-weight: 600; margin: 0; }

.topbar-badge {
  margin-left: auto;
  font-size: 11px;
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
  padding: 3px 10px;
  border-radius: 999px;
}

.admin-content {
  flex: 1;
  padding: 20px;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
}

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
  }
  .sidebar.open { transform: translateX(0); }
  .sidebar-close { display: block; }
  .sidebar-mask {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    z-index: 40;
  }
  .menu-btn { display: block; }
  .admin-content { padding: 14px; }
}
</style>
