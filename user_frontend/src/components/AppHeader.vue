<script setup lang="ts">
import { RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { Clapperboard, Menu, X, User, LogOut, Film, Ticket, Inbox, Crown } from 'lucide-vue-next'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

const mobileMenuOpen = ref(false)
const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)

const navItems = computed(() => [
  { name: '首页', path: '/' },
  { name: '求片', path: '/requests' },
  { name: '工单', path: '/tickets' },
  { name: '消息', path: '/messages' },
])

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value
}

function closeMenus() {
  mobileMenuOpen.value = false
  userMenuOpen.value = false
}

async function handleLogout() {
  closeMenus()
  await userStore.logout()
  router.push('/login')
}

function onDocClick(e: MouseEvent) {
  if (userMenuRef.value && !userMenuRef.value.contains(e.target as Node)) {
    userMenuOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <header class="app-header">
    <div class="header-container">
      <!-- Logo -->
      <RouterLink to="/" class="header-logo" @click="closeMenus">
        <span class="logo-mark">
          <Clapperboard :size="18" />
        </span>
        <span class="logo-text">Aetrix</span>
      </RouterLink>

      <!-- Desktop Navigation -->
      <nav class="desktop-nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          :class="{ 'nav-link-active': isActive(item.path) }"
        >
          {{ item.name }}
        </RouterLink>
      </nav>

      <!-- User Section -->
      <div class="user-section">
        <template v-if="userStore.isLoggedIn">
          <div ref="userMenuRef" class="user-menu">
            <button class="user-btn" @click="toggleUserMenu">
              <User :size="16" />
              <span class="user-name">{{ userStore.user?.username || '用户' }}</span>
            </button>

            <div v-if="userMenuOpen" class="user-dropdown">
              <div class="dropdown-head">
                <span class="dropdown-username">{{ userStore.user?.username }}</span>
                <span v-if="userStore.isVIP" class="dropdown-vip">
                  <Crown :size="11" />
                  VIP
                </span>
              </div>
              <RouterLink to="/profile" class="dropdown-item" @click="closeMenus">
                <User :size="15" />
                个人中心
              </RouterLink>
              <RouterLink to="/messages" class="dropdown-item" @click="closeMenus">
                <Inbox :size="15" />
                消息中心
              </RouterLink>
              <button class="dropdown-item dropdown-logout" @click="handleLogout">
                <LogOut :size="15" />
                退出登录
              </button>
            </div>
          </div>
        </template>

        <template v-else>
          <RouterLink to="/login" class="login-btn">登录</RouterLink>
        </template>

        <!-- Mobile toggle -->
        <button class="mobile-toggle" @click="mobileMenuOpen = !mobileMenuOpen">
          <X v-if="mobileMenuOpen" :size="18" />
          <Menu v-else :size="18" />
        </button>
      </div>
    </div>

    <!-- Mobile menu -->
    <div v-if="mobileMenuOpen" class="mobile-menu">
      <template v-if="userStore.isLoggedIn">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="mobile-link" @click="closeMenus">
          <component :is="item.path === '/requests' ? Film : item.path === '/tickets' ? Ticket : Inbox" v-if="item.path !== '/'" :size="16" />
          {{ item.name }}
        </RouterLink>
        <RouterLink to="/profile" class="mobile-link" @click="closeMenus">
          <User :size="16" />
          个人中心
        </RouterLink>
        <button class="mobile-link logout" @click="handleLogout">
          <LogOut :size="16" />
          退出登录
        </button>
      </template>
      <template v-else>
        <RouterLink to="/login" class="mobile-link" @click="closeMenus">
          <User :size="16" />
          登录 / 注册
        </RouterLink>
      </template>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(5, 7, 10, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.header-container {
  max-width: 880px;
  margin: 0 auto;
  padding: 0 1.25rem;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.header-logo {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  text-decoration: none;
}

.logo-mark {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #10b981;
}

.logo-text {
  font-size: 1.0625rem;
  font-weight: 700;
  color: #fafafa;
  letter-spacing: -0.01em;
}

.desktop-nav {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.nav-link {
  padding: 0.4375rem 0.75rem;
  border-radius: 9px;
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.55);
  text-decoration: none;
  transition: all 0.15s ease;
}

.nav-link:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.05);
}

.nav-link-active {
  color: #10b981;
  background: rgba(16, 185, 129, 0.08);
}

/* 用户区 */
.user-section {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.user-menu {
  position: relative;
}

.user-btn {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  height: 34px;
  padding: 0 0.75rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.user-btn:hover {
  background: rgba(255, 255, 255, 0.09);
  color: #fff;
}

.user-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 0.5rem);
  width: 180px;
  background: #10161d;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 13px;
  padding: 0.375rem;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
  animation: dropIn 0.18s ease;
}

@keyframes dropIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

.dropdown-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.625rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 0.25rem;
}

.dropdown-username {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #fafafa;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown-vip {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  color: #f59e0b;
  font-size: 0.6875rem;
  font-weight: 700;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.5625rem;
  width: 100%;
  padding: 0.5625rem 0.625rem;
  background: transparent;
  border: none;
  border-radius: 9px;
  color: rgba(255, 255, 255, 0.75);
  font-size: 0.8125rem;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.15s ease;
}

.dropdown-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.dropdown-logout {
  color: #f87171;
}

.dropdown-logout:hover {
  background: rgba(239, 68, 68, 0.08);
  color: #f87171;
}

.login-btn {
  display: inline-flex;
  align-items: center;
  height: 34px;
  padding: 0 1rem;
  background: linear-gradient(135deg, #10b981, #059669);
  border-radius: 10px;
  color: #fff;
  font-size: 0.8125rem;
  font-weight: 600;
  text-decoration: none;
  transition: box-shadow 0.2s ease;
}

.login-btn:hover {
  box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3);
}

.mobile-toggle {
  display: none;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
}

/* 移动端 */
.mobile-menu {
  display: none;
}

@media (max-width: 768px) {
  .desktop-nav {
    display: none;
  }

  .mobile-toggle {
    display: flex;
  }

  .user-name {
    display: none;
  }

  .mobile-menu {
    display: flex;
    flex-direction: column;
    padding: 0.5rem 1.25rem 0.875rem;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .mobile-link {
    display: flex;
    align-items: center;
    gap: 0.5625rem;
    padding: 0.6875rem 0.375rem;
    color: rgba(255, 255, 255, 0.75);
    font-size: 0.875rem;
    text-decoration: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .mobile-link:last-child {
    border-bottom: none;
  }

  .mobile-link.logout {
    color: #f87171;
  }
}
</style>
