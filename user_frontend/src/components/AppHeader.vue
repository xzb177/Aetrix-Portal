<script setup lang="ts">
import { RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import {
  Clapperboard, Menu, X, User, LogOut, Film, Ticket, Inbox, Crown,
  Wallet, CalendarCheck, Gift, MessageSquareDashed, Zap, History,
  Search, Heart, Bell, Megaphone, AlertCircle, Clock, ChevronRight,
} from 'lucide-vue-next'
import api, {
  messageApi, announcementApi,
  type StationMessage, type Announcement,
} from '@/api'
import { pointsApi } from '@/api/economy'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

const mobileMenuOpen = ref(false)
const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
const unreadCount = ref(0)
const pointsBalance = ref<number | null>(null)

// 顶栏消息入口：既显示「几条未读」，点开还能先看预览再决定要不要进消息中心
const msgMenuOpen = ref(false)
const msgMenuRef = ref<HTMLElement | null>(null)
const msgPreview = ref<MsgPreviewItem[]>([])
const msgLoading = ref(false)

interface MsgPreviewItem {
  key: string
  title: string
  meta: string
  to: string
  icon: unknown
  unread: boolean
}

// 消息类型 → 图标（与消息中心的分类保持一致；只取预览需要的几种）
const MSG_ICONS: Record<string, unknown> = {
  system: AlertCircle,
  ticket: Ticket,
  announcement: Megaphone,
  subscription: Gift,
  media_seek: Clock,
  exchange_code: Gift,
}

const MSG_LABELS: Record<string, string> = {
  system: '系统',
  ticket: '工单',
  announcement: '公告',
  subscription: '订阅',
  media_seek: '求片',
  exchange_code: '兑换',
}

function relTime(iso?: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const mins = Math.floor((Date.now() - t) / 60_000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return iso.slice(0, 10)
}

async function loadMsgPreview() {
  msgLoading.value = true
  try {
    // 只拉未读：预览要回答的是「有什么在等我」，而不是「最近收到了什么」
    const [msgs, notices] = await Promise.all([
      messageApi.getMessages({ unread_only: true, limit: 3 }).catch((): StationMessage[] => []),
      announcementApi.getAnnouncements().catch((): Announcement[] => []),
    ])
    const unread = (msgs || []).filter((m) => !m.is_read).slice(0, 3)
    const pinned = [...(notices || [])]
      .sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned))
      .slice(0, 2)
    msgPreview.value = [
      ...unread.map((m) => ({
        key: `m${m.id}`,
        title: m.title,
        meta: `${MSG_LABELS[m.message_type] || '通知'} · ${relTime(m.created_at)}`,
        to: '/messages',
        icon: MSG_ICONS[m.message_type] || Bell,
        unread: true,
      })),
      ...pinned.map((a) => ({
        key: `a${a.id}`,
        title: a.title,
        meta: `公告 · ${relTime(a.created_at)}`,
        to: '/messages',
        icon: Megaphone,
        unread: false,
      })),
    ]
  } finally {
    msgLoading.value = false
  }
}

function toggleMsgMenu() {
  userMenuOpen.value = false
  msgMenuOpen.value = !msgMenuOpen.value
  if (msgMenuOpen.value) loadMsgPreview()
}

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
  msgMenuOpen.value = false
}

async function handleLogout() {
  closeMenus()
  await userStore.logout()
  router.push('/login')
}

function onDocClick(e: MouseEvent) {
  const target = e.target as Node
  if (userMenuRef.value && !userMenuRef.value.contains(target)) {
    userMenuOpen.value = false
  }
  if (msgMenuRef.value && !msgMenuRef.value.contains(target)) {
    msgMenuOpen.value = false
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
    msgPreview.value = []
    msgMenuOpen.value = false
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

          <!-- 消息：保持一个安静的音铃（不在顶栏抢文案），点开先给预览 -->
          <div ref="msgMenuRef" class="msg-menu">
            <button
              class="msg-btn"
              :class="{ alert: unreadCount > 0, open: msgMenuOpen }"
              :title="unreadCount > 0 ? `${unreadCount} 条未读消息` : '消息中心'"
              @click="toggleMsgMenu"
            >
              <Inbox :size="18" />
              <span v-if="unreadCount > 0" class="msg-badge">
                {{ unreadCount > 99 ? '99+' : unreadCount }}
              </span>
            </button>

            <Transition name="dd">
              <div v-if="msgMenuOpen" class="msg-dropdown">
                <div class="msg-drop-head">
                  <span class="msg-drop-title">消息中心</span>
                  <span v-if="unreadCount > 0" class="msg-drop-unread">{{ unreadCount > 99 ? '99+' : unreadCount }} 条未读</span>
                  <span v-else class="msg-drop-clear">已全部读完</span>
                </div>

                <p v-if="msgLoading" class="msg-drop-hint">加载中…</p>
                <template v-else-if="msgPreview.length">
                  <RouterLink
                    v-for="p in msgPreview"
                    :key="p.key"
                    :to="p.to"
                    class="msg-drop-item"
                    @click="closeMenus"
                  >
                    <span class="msg-drop-ic" :class="{ hot: p.unread }">
                      <component :is="p.icon" :size="14" />
                    </span>
                    <span class="msg-drop-body">
                      <span class="msg-drop-item-title">{{ p.title }}</span>
                      <span class="msg-drop-meta">{{ p.meta }}</span>
                    </span>
                    <span v-if="p.unread" class="msg-drop-dot" aria-hidden="true"></span>
                  </RouterLink>
                </template>
                <p v-else class="msg-drop-hint">暂时没有新消息</p>

                <RouterLink to="/messages" class="msg-drop-foot" @click="closeMenus">
                  查看全部消息
                  <ChevronRight :size="13" />
                </RouterLink>
              </div>
            </Transition>
          </div>

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
/* 消息入口：读完后是一个安静的音铃，有未读时才点一颗小数字 */
.msg-menu { position: relative; }

.msg-btn {
  position: relative;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  border-radius: var(--au-r-md);
  color: var(--au-text-2);
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}
.msg-btn:hover { color: var(--au-text); background: var(--au-surface-2); }
.msg-btn.open { color: var(--au-text); background: var(--au-surface-2); }
.msg-btn.alert { color: var(--au-warning); }

.msg-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-warning);
  color: #1a1205;
  font-size: 0.625rem;
  font-weight: 800;
  border-radius: var(--au-r-full);
  box-shadow: 0 0 0 2px rgba(7, 11, 18, 0.9);
}

.msg-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: 292px;
  background: rgba(10, 16, 26, 0.97);
  border: 1px solid var(--au-border-strong);
  border-radius: var(--au-r-lg);
  box-shadow: var(--au-shadow-2);
  overflow: hidden;
  z-index: 60;
}

.msg-drop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.8125rem 1rem;
  border-bottom: 1px solid var(--au-border);
}

.msg-drop-title { font-size: 0.875rem; font-weight: 700; color: var(--au-text); }

.msg-drop-unread {
  padding: 0.125rem 0.5rem;
  background: rgba(251, 191, 36, 0.16);
  border-radius: var(--au-r-full);
  color: var(--au-warning);
  font-size: 0.625rem;
  font-weight: 700;
}

.msg-drop-clear { font-size: 0.625rem; color: var(--au-text-4); }

.msg-drop-item {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  padding: 0.6875rem 1rem;
  text-decoration: none;
  border-bottom: 1px solid var(--au-border);
  transition: background var(--au-fast) var(--au-ease);
}
.msg-drop-item:hover { background: var(--au-surface-2); }

.msg-drop-ic {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--au-surface-2);
  color: var(--au-text-3);
}

.msg-drop-ic.hot {
  background: rgba(251, 191, 36, 0.14);
  color: var(--au-warning);
}

.msg-drop-body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
  flex: 1;
}

.msg-drop-item-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-drop-meta { font-size: 0.6875rem; color: var(--au-text-4); }

.msg-drop-dot {
  width: 6px;
  height: 6px;
  margin-top: 0.5rem;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--au-warning);
}

.msg-drop-hint {
  margin: 0;
  padding: 1.125rem 1rem;
  text-align: center;
  font-size: 0.75rem;
  color: var(--au-text-4);
  border-bottom: 1px solid var(--au-border);
}

.msg-drop-foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.1875rem;
  padding: 0.6875rem 1rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--au-primary);
  text-decoration: none;
  transition: background var(--au-fast) var(--au-ease);
}
.msg-drop-foot:hover { background: var(--au-surface-2); }

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
  .msg-dropdown { width: min(292px, calc(100vw - 2rem)); }
}
</style>
