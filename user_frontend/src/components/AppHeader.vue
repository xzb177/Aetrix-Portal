<script setup lang="ts">
import { RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import {
  Clapperboard, Menu, X, User, LogOut, Film, Ticket, Inbox, Crown,
  Wallet, CalendarCheck, Gift, MessageSquareDashed, Zap, History,
  Search, Heart,
} from 'lucide-vue-next'
import api from '@/api'
import { pointsApi } from '@/api/economy'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

const mobileMenuOpen = ref(false)
const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
const unreadCount = ref(0)
const pointsBalance = ref<number | null>(null)

// 导航分组：内容 → 运营 → 支持，视觉上以细分隔线区隔
const navGroups = [
  {
    items: [
      { name: '首页', path: '/' },
      { name: '媒体库', path: '/media' },
      { name: '收藏', path: '/favorites' },
      { name: '观看记录', path: '/history' },
    ],
  },
  { items: [{ name: '钱包', path: '/wallet' }, { name: '签到', path: '/checkin' }, { name: '邀请', path: '/invite' }] },
  { items: [{ name: '求片', path: '/request' }, { name: '工单', path: '/tickets' }] },
]

// 移动端抽屉（底部导航坞之外的长尾入口）
const mobileLinks = [
  { name: '搜索片名', path: '/search', icon: Search },
  { name: '我的收藏', path: '/favorites', icon: Heart },
  { name: '观看记录', path: '/history', icon: History },
  { name: '邀请返利', path: '/invite', icon: Gift },
  { name: '求片中心', path: '/request', icon: MessageSquareDashed },
  { name: '工单支持', path: '/tickets', icon: Ticket },
  { name: '消息中心', path: '/messages', icon: Inbox },
  { name: '个人中心', path: '/profile', icon: User },
]

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
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

async function refreshPoints() {
  if (!userStore.isLoggedIn) return
  try {
    const log = await pointsApi.log({ limit: 1 })
    pointsBalance.value = log.balance
  } catch {
    /* 静默 */
  }
}

async function poll() {
  if (!userStore.isLoggedIn) return
  try {
    const res = await api.get<never, { unread_count: number }>('/api/user/messages/unread-count')
    unreadCount.value = res?.unread_count || 0
  } catch {
    /* 静默失败 */
  }
  refreshPoints()
}

// 签到 / 钱包操作后回到顶栏时，积分徽章即时刷新
watch(() => route.path, (p, old) => {
  const economyPaths = ['/wallet', '/checkin']
  if (userStore.isLoggedIn && (economyPaths.includes(old || '') || economyPaths.includes(p))) {
    refreshPoints()
  }
})

watch(() => userStore.isLoggedIn, (loggedIn) => {
  if (loggedIn) poll()
  else {
    unreadCount.value = 0
    pointsBalance.value = null
  }
})

onMounted(() => {
  document.addEventListener('click', onDocClick)
  poll()
  window.setInterval(poll, 60_000)
})
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <header class="app-header">
    <div class="header-container">
      <RouterLink to="/" class="header-logo" @click="closeMenus">
        <span class="logo-mark">
          <Clapperboard :size="17" />
        </span>
        <span class="logo-text">Aetrix</span>
      </RouterLink>

      <!-- 桌面导航：内容 / 运营 / 支持 三组 -->
      <nav class="desktop-nav">
        <template v-for="(group, gi) in navGroups" :key="gi">
          <span v-if="gi > 0" class="nav-divider" aria-hidden="true" />
          <RouterLink
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-link"
            :class="{ 'nav-link-active': isActive(item.path) }"
          >
            {{ item.name }}
          </RouterLink>
        </template>
      </nav>

      <!-- 右侧用户区 -->
      <div class="user-section">
        <template v-if="userStore.isLoggedIn">
          <!-- 全局搜索：跨库检索 -->
          <RouterLink to="/search" class="icon-btn" title="搜索片名">
            <Search :size="18" />
          </RouterLink>

          <!-- 积分徽章：点击进入钱包 -->
          <RouterLink to="/wallet" class="points-chip" title="积分余额 · 进入钱包">
            <Zap :size="13" />
            <span class="points-num">{{ pointsBalance === null ? '—' : pointsBalance.toLocaleString() }}</span>
          </RouterLink>

          <RouterLink to="/messages" class="msg-btn" title="消息中心">
            <Inbox :size="18" />
            <span v-if="unreadCount > 0" class="msg-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </RouterLink>

          <div ref="userMenuRef" class="user-menu">
            <button class="user-btn" @click="userMenuOpen = !userMenuOpen">
              <span class="avatar">{{ (userStore.user?.username || 'U').charAt(0).toUpperCase() }}</span>
              <span class="user-name">{{ userStore.user?.username || '用户' }}</span>
            </button>

            <Transition name="dd">
              <div v-if="userMenuOpen" class="user-dropdown">
                <div class="dropdown-head">
                  <span class="dropdown-username">{{ userStore.user?.username }}</span>
                  <span v-if="userStore.isVIP" class="dropdown-vip">
                    <Crown :size="11" /> VIP
                  </span>
                </div>
                <RouterLink to="/profile" class="dropdown-item" @click="closeMenus">
                  <User :size="15" /> 个人中心
                </RouterLink>
                <RouterLink to="/wallet" class="dropdown-item" @click="closeMenus">
                  <Wallet :size="15" /> 我的钱包
                </RouterLink>
                <RouterLink to="/invite" class="dropdown-item" @click="closeMenus">
                  <Gift :size="15" /> 邀请返利
                </RouterLink>
                <button class="dropdown-item dropdown-logout" @click="handleLogout">
                  <LogOut :size="15" /> 退出登录
                </button>
              </div>
            </Transition>
          </div>
        </template>

        <template v-else>
          <RouterLink to="/login" class="login-btn">登录</RouterLink>
        </template>

        <button class="mobile-toggle" @click="mobileMenuOpen = !mobileMenuOpen">
          <X v-if="mobileMenuOpen" :size="19" />
          <Menu v-else :size="19" />
        </button>
      </div>
    </div>

    <!-- 移动端抽屉：长尾入口（主导航在底部导航坞） -->
    <Transition name="mm">
      <div v-if="mobileMenuOpen" class="mobile-menu">
        <template v-if="userStore.isLoggedIn">
          <RouterLink v-for="item in mobileLinks" :key="item.path" :to="item.path" class="mobile-link" @click="closeMenus">
            <component :is="item.icon" :size="17" />
            {{ item.name }}
            <span v-if="item.path === '/messages' && unreadCount > 0" class="mobile-msg-badge">{{ unreadCount }}</span>
          </RouterLink>
          <button class="mobile-link logout" @click="handleLogout">
            <LogOut :size="17" />
            退出登录
          </button>
        </template>
        <template v-else>
          <RouterLink to="/login" class="mobile-link" @click="closeMenus">
            <User :size="17" />
            登录 / 注册
          </RouterLink>
        </template>
      </div>
    </Transition>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(7, 11, 18, 0.78);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--au-border);
}

.header-container {
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 1.25rem;
  height: 62px;
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
  flex-shrink: 0;
}

.logo-mark {
  width: 33px;
  height: 33px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  background: var(--au-gradient);
  color: #05141c;
  box-shadow: 0 3px 12px var(--au-primary-glow);
}

.logo-text {
  font-size: 1.125rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  background: var(--au-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.desktop-nav {
  display: flex;
  align-items: center;
  gap: 0.125rem;
}

.nav-divider {
  width: 1px;
  height: 16px;
  margin: 0 0.5rem;
  background: var(--au-border-strong);
  flex-shrink: 0;
}

.nav-link {
  padding: 0.4688rem 0.8125rem;
  border-radius: var(--au-r-sm);
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--au-text-2);
  text-decoration: none;
  transition: all var(--au-fast) var(--au-ease);
}

.nav-link:hover {
  color: var(--au-text);
  background: var(--au-surface-2);
}

.nav-link-active {
  color: var(--au-primary);
  background: var(--au-primary-soft);
}

.user-section {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

/* 积分徽章 */
.points-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  height: 30px;
  padding: 0 0.6875rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-full);
  color: var(--au-primary);
  text-decoration: none;
  transition: all var(--au-fast) var(--au-ease);
}

.points-chip:hover {
  background: rgba(34, 211, 238, 0.2);
  box-shadow: 0 0 14px var(--au-primary-glow);
}

.points-num {
  font-size: 0.75rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  max-width: 88px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 图标按钮（搜索） */
.icon-btn {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-md);
  color: var(--au-text-2);
  transition: all var(--au-fast);
}
.icon-btn:hover { color: var(--au-primary); background: var(--au-surface-2); }

/* 消息铃铛 */
.msg-btn {
  position: relative;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-md);
  color: var(--au-text-2);
  transition: all var(--au-fast);
}
.msg-btn:hover { color: var(--au-text); background: var(--au-surface-2); }

.msg-badge {
  position: absolute;
  top: 3px;
  right: 3px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-gradient-warm);
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
  box-shadow: 0 2px 6px rgba(244, 114, 182, 0.4);
}

.user-menu { position: relative; }

.user-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3125rem 0.75rem 0.3125rem 0.3125rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  cursor: pointer;
  transition: all var(--au-fast);
}
.user-btn:hover { background: var(--au-surface-2); border-color: var(--au-border-strong); }

.avatar {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--au-gradient);
  color: #05141c;
  font-size: 0.8125rem;
  font-weight: 800;
}

.user-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: 200px;
  background: rgba(10, 16, 26, 0.97);
  border: 1px solid var(--au-border-strong);
  border-radius: var(--au-r-lg);
  box-shadow: var(--au-shadow-2);
  overflow: hidden;
  z-index: 60;
}

.dropdown-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem 1rem;
  border-bottom: 1px solid var(--au-border);
}

.dropdown-username {
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--au-text);
}

.dropdown-vip {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  padding: 0.125rem 0.5rem;
  background: var(--au-gradient-warm);
  border-radius: var(--au-r-full);
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  padding: 0.6875rem 1rem;
  background: none;
  border: none;
  color: var(--au-text-2);
  font-size: 0.8125rem;
  text-decoration: none;
  cursor: pointer;
  transition: all var(--au-fast);
  text-align: left;
}
.dropdown-item:hover { background: var(--au-surface-2); color: var(--au-text); }
.dropdown-logout { color: var(--au-danger); border-top: 1px solid var(--au-border); }
.dropdown-logout:hover { background: var(--au-danger-soft); color: var(--au-danger); }

.login-btn {
  display: inline-flex;
  align-items: center;
  height: 36px;
  padding: 0 1.125rem;
  background: var(--au-gradient);
  color: #05141c;
  border-radius: var(--au-r-md);
  font-size: 0.8125rem;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 0 3px 12px var(--au-primary-glow);
  transition: transform var(--au-fast);
}
.login-btn:hover { transform: translateY(-1px); }

.mobile-toggle {
  display: none;
  width: 38px;
  height: 38px;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: var(--au-text-2);
  cursor: pointer;
  border-radius: var(--au-r-md);
}
.mobile-toggle:hover { background: var(--au-surface-2); color: var(--au-text); }

.mobile-menu {
  display: none;
  border-top: 1px solid var(--au-border);
  padding: 0.5rem 1rem 0.875rem;
  background: rgba(7, 11, 18, 0.97);
}

.mobile-link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0.625rem;
  color: var(--au-text-2);
  font-size: 0.9375rem;
  text-decoration: none;
  border-radius: var(--au-r-md);
  transition: all var(--au-fast);
  width: 100%;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  position: relative;
}
.mobile-link:hover { background: var(--au-surface-2); color: var(--au-text); }
.mobile-link.logout { color: var(--au-danger); }

.mobile-msg-badge {
  margin-left: auto;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-gradient-warm);
  color: #fff;
  font-size: 0.6875rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

/* 过渡 */
.dd-enter-active, .dd-leave-active { transition: opacity var(--au-fast), transform var(--au-fast); }
.dd-enter-from, .dd-leave-to { opacity: 0; transform: translateY(-6px); }

.mm-enter-active, .mm-leave-active { transition: opacity var(--au-med), transform var(--au-med); }
.mm-enter-from, .mm-leave-to { opacity: 0; transform: translateY(-8px); }

@media (max-width: 900px) {
  .desktop-nav { display: none; }
  .points-chip { display: none; }
  .mobile-toggle { display: flex; }
  .mobile-menu { display: flex; flex-direction: column; }
  .user-name { display: none; }
}
</style>
