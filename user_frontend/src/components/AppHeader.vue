<script setup lang="ts">
import { RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { computed, ref } from 'vue'
import { Menu, X, User, LogOut, Crown, Tv, ChevronDown } from 'lucide-vue-next'
import NotificationCenter from '@/components/NotificationCenter.vue'
import BrandIcon from '@/components/BrandIcon.vue'
import { useAuthSheet } from '@/composables/useAuthSheet'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()
const { openAuthSheet } = useAuthSheet()

const mobileMenuOpen = ref(false)
const userMenuOpen = ref(false)

function handleLogin() {
  openAuthSheet()
  mobileMenuOpen.value = false
}

const navItems = computed(() => {
  const items = [
    { name: '首页', path: '/' },
  ]

  if (userStore.isLoggedIn) {
    items.push(
      { name: '求片', path: '/request' },
      { name: '订阅', path: '/subscription' },
      { name: '充值', path: '/recharge' },
      { name: '邀请', path: '/invite' },
    )
  }

  return items
})

function toggleMobileMenu() {
  mobileMenuOpen.value = !mobileMenuOpen.value
}

function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value
}

async function handleLogout() {
  userMenuOpen.value = false
  mobileMenuOpen.value = false
  userStore.logout()
  router.push('/')
}

function handleClickOutside() {
  mobileMenuOpen.value = false
  userMenuOpen.value = false
}
</script>

<template>
  <header class="app-header">
    <div class="header-container">
      <!-- Logo -->
      <RouterLink to="/" class="header-logo" @click="handleClickOutside">
        <BrandIcon :size="40" class="shrink-0" />
        <span class="logo-text">Aetrix</span>
      </RouterLink>

      <!-- Desktop Navigation -->
      <nav class="desktop-nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          :class="{ 'nav-link-active': route.path === item.path }"
        >
          {{ item.name }}
        </RouterLink>
      </nav>

      <!-- User Section -->
      <div class="user-section">
        <template v-if="userStore.isLoggedIn">
          <!-- 通知中心 - 前后台联动 -->
          <NotificationCenter />

          <!-- VIP Badge -->
          <div v-if="userStore.isVIP" class="vip-badge">
            <Crown :size="12" />
            <span>VIP</span>
          </div>

          <!-- User Menu -->
          <div class="user-menu">
            <button @click="toggleUserMenu" class="user-btn">
              <User :size="18" />
              <span>{{ userStore.user?.username || '用户' }}</span>
              <ChevronDown :size="14" :class="{ 'rotate-180': userMenuOpen }" />
            </button>

            <!-- Dropdown -->
            <div v-if="userMenuOpen" class="user-dropdown">
              <RouterLink to="/messages" class="dropdown-item" @click="toggleUserMenu">
                <svg :width="16" :height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                </svg>
                消息中心
              </RouterLink>
              <RouterLink to="/profile" class="dropdown-item" @click="toggleUserMenu">
                <User :size="16" />
                个人中心
              </RouterLink>
              <button @click="handleLogout" class="dropdown-item dropdown-logout">
                <LogOut :size="16" />
                退出登录
              </button>
            </div>
          </div>
        </template>

        <!-- 未登录时只保留菜单图标，去掉登录/注册按钮避免多入口冲突 -->
        <!-- Apple TV 风格：首屏只有一个主 CTA -->

        <!-- Mobile Menu Button -->
        <button @click="toggleMobileMenu" class="mobile-btn">
          <Menu v-if="!mobileMenuOpen" :size="22" />
          <X v-else :size="22" />
        </button>
      </div>
    </div>

    <!-- Mobile Menu -->
    <Transition name="mobile-menu">
      <div v-if="mobileMenuOpen" class="mobile-menu">
        <div class="mobile-menu-container">
          <RouterLink
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            @click="handleClickOutside"
            class="mobile-link"
            :class="{ 'mobile-link-active': route.path === item.path }"
          >
            {{ item.name }}
          </RouterLink>

          <div v-if="userStore.isLoggedIn" class="mobile-divider"></div>

          <template v-if="userStore.isLoggedIn">
            <RouterLink to="/messages" @click="handleClickOutside" class="mobile-link">
              <svg :width="18" :height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
                <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
              </svg>
              消息中心
            </RouterLink>
            <RouterLink to="/profile" @click="handleClickOutside" class="mobile-link">
              <User :size="18" />
              个人中心
            </RouterLink>
            <button @click="handleLogout" class="mobile-link mobile-link-logout">
              <LogOut :size="18" />
              退出登录
            </button>
          </template>

          <template v-else>
            <button @click="handleLogin" class="mobile-link mobile-link-primary">
              登录 / 注册
            </button>
          </template>
        </div>
      </div>
    </Transition>
  </header>
</template>

<style scoped>
.app-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 50;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}

.header-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 1.5rem;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  text-decoration: none;
}

.logo-text {
  font-size: 1rem;
  font-weight: 700;
  color: #fafafa;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Desktop Nav */
.desktop-nav {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.nav-link {
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: rgba(250, 250, 250, 0.7);
  text-decoration: none;
  border-radius: 0.5rem;
  transition: all 0.2s ease;
}

.nav-link:hover {
  color: #fafafa;
  background: rgba(255, 255, 255, 0.1);
}

.nav-link-active {
  color: #fafafa;
  background: var(--brand-primary-light);
}

/* User Section */
.user-section {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.vip-badge {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.625rem;
  background: rgba(245, 158, 11, 0.9);
  border-radius: 20px;
  color: white;
  font-size: 0.75rem;
  font-weight: 500;
}

.user-menu {
  position: relative;
}

.user-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 0.875rem;
  font-weight: 500;
  color: #fafafa;
  cursor: pointer;
  transition: all 0.2s ease;
}

.user-btn:hover {
  background: rgba(255, 255, 255, 0.15);
}

.user-btn svg:last-child {
  transition: transform 0.2s ease;
}

.user-btn svg.rotate-180 {
  transform: rotate(180deg);
}

.user-dropdown {
  position: absolute;
  top: calc(100% + 0.5rem);
  right: 0;
  min-width: 160px;
  background: rgba(0, 0, 0, 0.9);
  backdrop-filter: blur(8px);
  border-radius: 0.75rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
  overflow: hidden;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.625rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: rgba(250, 250, 250, 0.8);
  text-decoration: none;
  text-align: left;
  border: none;
  background: none;
  cursor: pointer;
  transition: background 0.2s ease;
}

.dropdown-item:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fafafa;
}

.dropdown-logout {
  color: #ef4444;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.dropdown-logout:hover {
  background: rgba(239, 68, 68, 0.1);
}

/* Login Button */
.login-btn {
  padding: 0.5rem 1.25rem;
  background: var(--brand-primary);
  color: white;
  border-radius: 20px;
  font-size: 0.875rem;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.2s ease;
}

.login-btn:hover {
  background: var(--brand-primary-hover);
}

.login-btn:active {
  transform: scale(0.98);
  opacity: 0.9;
}

/* Mobile */
.mobile-btn {
  display: none;
  padding: 0.5rem;
  border: none;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 0.5rem;
  cursor: pointer;
  color: rgba(250, 250, 250, 0.8);
}

.mobile-btn svg {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mobile-menu {
  display: none;
}

.mobile-menu-container {
  background: rgba(0, 0, 0, 0.95);
  backdrop-filter: blur(8px);
  border-top: 1px solid rgba(255, 255, 255, 0.2);
  padding: 1rem 1.5rem;
}

.mobile-link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: rgba(250, 250, 250, 0.8);
  text-decoration: none;
  border-radius: 0.5rem;
  transition: background 0.2s ease;
  width: 100%;
  border: none;
  background: none;
  cursor: pointer;
}

.mobile-link:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fafafa;
}

.mobile-link-active {
  background: var(--brand-primary-light);
  color: #fafafa;
}

.mobile-link svg {
  color: rgba(250, 250, 250, 0.6);
}

.mobile-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.2);
  margin: 0.5rem 0;
}

.mobile-link-logout {
  color: #ef4444;
}

.mobile-link-primary {
  background: var(--brand-primary);
  color: white;
  justify-content: center;
}

.mobile-link-primary:hover {
  background: var(--brand-primary-hover);
}

.mobile-link-primary:active {
  transform: scale(0.98);
  opacity: 0.9;
}

/* Mobile menu transition */
.mobile-menu-enter-active,
.mobile-menu-leave-active {
  transition: all 0.2s ease;
}

.mobile-menu-enter-from,
.mobile-menu-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

@media (max-width: 768px) {
  .desktop-nav {
    display: none;
  }

  .user-menu {
    display: none;
  }

  .mobile-btn {
    display: flex;
  }

  .mobile-menu {
    display: block;
  }
}
</style>
