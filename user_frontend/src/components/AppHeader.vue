<script setup lang="ts">
import { RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import {
  Clapperboard, LogOut, Ticket, Inbox, Crown,
  Gift, Zap, Megaphone, AlertCircle, Clock,
  ChevronRight, LayoutDashboard, Bell,
} from 'lucide-vue-next'
import api, {
  messageApi, announcementApi,
  type StationMessage, type Announcement,
} from '@/api'
import { pointsApi } from '@/api/economy'
import { primaryNav, menuSections } from '@/config/navigation'
// 站名与 Logo 来自「站点与品牌」能力（没配就用默认值，不会出现空标题）
import { branding } from '@/composables/useBranding'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
const navRef = ref<HTMLElement | null>(null)
const unreadCount = ref(0)
const pointsBalance = ref<number | null>(null)

// 顶栏消息入口（v2.10.3 起是全站唯一的消息入口）：既显示「几条未读」，
// 点开还能先看预览再决定要不要进消息中心
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
  /** 同名未读合并后的条数（1 = 真的只有一条） */
  count?: number
  /** 条数是否精确（拉取窗口被占满时，最旧那一组可能还没数完，显示成 N+） */
  countExact?: boolean
  /** 这条消息对应哪条公告（公告广播自带 related_id），用于避开同一公告列两遍 */
  announcementId?: number | null
}

/** 未读预览一次拉多少条：要够把「同名通知有几条」数准（消息很小，50 条约几十 KB） */
const UNREAD_WINDOW = 50

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

/**
 * 铃铛预览：未读优先（同名合并成一条 + 条数），再接置顶公告。
 *
 * v2.10.3：铃铛是站内消息唯一的入口——首页底部那张消息卡已去掉（它和这里列的是
 * 同一批未读）。所以这一份预览就是全站的消息预览。
 *
 * v2.10.2：
 *   - 同标题的多条未读（如 26 条「📥 新的求片请求」，内容各不相同）并排列出来像
 *     同一条消息发了好几遍；合并成一条并把条数写出来。
 *   - 公告有两种身份：发布时广播落下的站内信（`📢 标题`，带已读状态）与公告本身。
 *     已经作为未读消息在列里的公告，不再重复列一遍。
 */
async function loadMsgPreview() {
  msgLoading.value = true
  try {
    // 只拉未读：预览要回答的是「有什么在等我」，而不是「最近收到了什么」
    const [msgs, notices] = await Promise.all([
      messageApi.getMessages({ unread_only: true, limit: UNREAD_WINDOW }).catch((): StationMessage[] => []),
      announcementApi.getAnnouncements().catch((): Announcement[] => []),
    ])
    const unreadAll = (msgs || []).filter((x) => !x.is_read)

    const unreadRows: MsgPreviewItem[] = []
    const byTitle = new Map<string, MsgPreviewItem>()
    let last: MsgPreviewItem | null = null
    for (const m of unreadAll) {
      const groupKey = `${m.message_type}:${m.title}`
      const hit = byTitle.get(groupKey)
      if (hit) {
        hit.count = (hit.count || 1) + 1
        last = hit
        continue
      }
      const row: MsgPreviewItem = {
        key: `m${m.id}`,
        title: m.title,
        meta: `${MSG_LABELS[m.message_type] || '通知'} · ${relTime(m.created_at)}`,
        to: '/messages',
        icon: MSG_ICONS[m.message_type] || Bell,
        unread: true,
        count: 1,
        countExact: true,
        // related_id 只有公告广播那条才指回公告（求片/工单的 related_id 是各自的业务 id，
        // 拿来跟公告 id 比会误伤）
        announcementId: m.message_type === 'announcement' ? (m.related_id ?? null) : null,
      }
      byTitle.set(groupKey, row)
      unreadRows.push(row)
      last = row
    }
    // 窗口被未读占满时，最旧那一组可能还有下一批没拉到，标成 N+ 而不是报一个偏小的数
    if (last && unreadAll.length >= UNREAD_WINDOW) last.countExact = false

    const unread = unreadRows.slice(0, 3)
    const listedAnnouncementIds = new Set(
      unread
        .filter((r) => r.announcementId != null)
        .map((r) => Number(r.announcementId)),
    )
    const pinned = [...(notices || [])]
      .filter((a) => !listedAnnouncementIds.has(a.id))
      .sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned))
      .slice(0, 2)

    msgPreview.value = [
      ...unread,
      ...pinned.map((a) => ({
        key: `a${a.id}`,
        title: a.title,
        meta: `公告 · ${relTime(a.created_at)}`,
        // 直接落到消息中心的「公告」分类：此前只丢到消息中心首页，
        // 用户还得自己在分类里再找一遍这条公告
        to: '/messages?tab=announcement',
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

/**
 * 导航分工（v2.6.30）：全站只有一份导航定义，见 src/config/navigation.ts。
 *
 *   primaryNav   → 顶栏（宽屏横排、窄屏第二行滑动选项卡），全断点同一批条目、同一个顺序
 *   menuSections → 低频入口统一收进头像菜单（全断点一致）
 *
 * v2.10.1：搜索从「右上角图标 + 菜单条目」两处重复，改成主导航里的一项。
 *
 * 顶栏不再有第二个汉堡抽屉：同一批链接在同一屏里出现两遍，是「看着有两个导航」的根源。
 */

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function closeMenus() {
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

/**
 * 窄屏的主导航是横向滑动的选项卡：保证当前项始终看得见。
 *
 * - center=true（切换页面）：把当前项滑到中间，点完立刻能看到高亮；
 * - center=false（首次挂载）：只保证看得见（深链直接落在第 5 个入口时不用手动滑）。
 * 用 scrollBy 只滚这一条，不会带着整页横向滑动；宽屏下整条都能放下，直接返回。
 */
async function focusActiveTab(center: boolean) {
  await nextTick()
  const box = navRef.value
  const el = box?.querySelector<HTMLElement>('.nav-link-active')
  if (!box || !el) return
  if (box.scrollWidth <= box.clientWidth) return

  const boxRect = box.getBoundingClientRect()
  const elRect = el.getBoundingClientRect()

  if (center) {
    const delta = elRect.left - boxRect.left - (boxRect.width - elRect.width) / 2
    box.scrollBy({ left: delta, behavior: 'smooth' })
    return
  }
  if (elRect.left < boxRect.left || elRect.right > boxRect.right) {
    box.scrollBy({ left: elRect.left - boxRect.left - 12, behavior: 'auto' })
  }
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

// 换页后把当前选项卡滑到中间（宽屏下是空操作）
watch(() => route.path, () => focusActiveTab(true))

onMounted(() => {
  document.addEventListener('click', onDocClick)
  poll()
  window.setInterval(poll, 60_000)
  focusActiveTab(false)
})
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <header class="app-header">
    <div class="header-container">
      <RouterLink to="/" class="header-logo" @click="closeMenus">
        <span class="logo-mark">
          <img v-if="branding.logo_url" :src="branding.logo_url" :alt="branding.site_name" />
          <Clapperboard v-else :size="17" />
        </span>
        <span class="logo-text">{{ branding.site_name }}</span>
      </RouterLink>

      <!-- 主导航（全断点唯一一套）：≥900px 横排在品牌与账号操作之间，
           ≤900px 落到第二行、变成可横向滑动的选项卡（见样式里的 .main-nav） -->
      <nav ref="navRef" class="main-nav" aria-label="主导航">
        <RouterLink
          v-for="item in primaryNav"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          :class="{ 'nav-link-active': isActive(item.path) }"
        >
          <component :is="item.icon" :size="15" />
          {{ item.name }}
        </RouterLink>
      </nav>

      <!-- 右侧用户区 -->
      <div class="user-section">
        <template v-if="userStore.isLoggedIn">
          <!-- 搜索（v2.10.1）：已升为主导航的一级入口，这里不再单挂一个放大镜图标——
               图标与菜单项都指向 /search，同一件事在顶栏出现两遍就是重复入口 -->

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
                      <span class="msg-drop-meta">
                        {{ p.meta }}<template v-if="(p.count || 1) > 1"> · 同名 {{ p.count }}{{ p.countExact === false ? '+' : '' }} 条</template>
                      </span>
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

                <!-- 长尾入口：低频功能统一收在这里（全断点一致），
                     顶栏主导航只留 3 个高频目的地（首页 / 媒体库 / 我的） -->
                <template v-for="group in menuSections" :key="group.title">
                  <p class="dropdown-group-title">{{ group.title }}</p>
                  <RouterLink
                    v-for="item in group.items"
                    :key="item.path"
                    :to="item.path"
                    class="dropdown-item"
                    @click="closeMenus"
                  >
                    <component :is="item.icon" :size="15" /> {{ item.name }}
                    <span
                      v-if="item.path === '/messages' && unreadCount > 0"
                      class="dropdown-badge"
                    >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
                  </RouterLink>
                </template>

                <!-- 管理后台是另一个前端（同源 /admin/），必须用浏览器跳转：
                     写成 RouterLink 会被用户端路由当成 404 兜底页 -->
                <a
                  v-if="userStore.user?.is_staff"
                  href="/admin/"
                  class="dropdown-item"
                  @click="closeMenus"
                >
                  <LayoutDashboard :size="15" /> 管理后台
                </a>

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
      </div>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 50;
  background: var(--au-overlay);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--au-border);
}

.header-container {
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 1.25rem;
  min-height: 62px;
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
  color: var(--au-on-primary);
  box-shadow: 0 3px 12px var(--au-primary-glow);
}

.logo-mark img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: inherit;
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

.main-nav {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  min-width: 0;
}

.nav-link {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4688rem 0.75rem;
  border-radius: var(--au-r-sm);
  font-size: 0.875rem;
  font-weight: 500;
  white-space: nowrap;
  color: var(--au-text-2);
  text-decoration: none;
  transition: all var(--au-fast) var(--au-ease);
}

.nav-link svg { opacity: 0.75; }

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
  background: var(--au-primary-mid);
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
  color: var(--au-on-warning);
  font-size: 0.625rem;
  font-weight: 800;
  border-radius: var(--au-r-full);
  /* 与页面底色同色的描边环，把徽章从任何背景上“抠”出来 */
  box-shadow: 0 0 0 2px var(--au-overlay);
}

.msg-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: 292px;
  background: var(--au-overlay-menu);
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
  background: var(--au-warning-soft);
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
  background: var(--au-warning-soft);
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
  color: var(--au-on-primary);
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
  background: var(--au-overlay-menu);
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

/* 下拉里的分组标题与未读徽标：长尾入口收进来之后需要与账号项区分 */
.dropdown-group-title {
  margin: 0.375rem 0 0.125rem;
  padding: 0 1rem;
  font-size: 0.625rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--au-text-4);
}

.dropdown-badge {
  margin-left: auto;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-gradient-warm);
  color: var(--au-on-primary);
  font-size: 0.6875rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

.dropdown-vip {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  padding: 0.125rem 0.5rem;
  background: var(--au-gradient-warm);
  border-radius: var(--au-r-full);
  color: var(--au-on-primary);
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
  color: var(--au-on-primary);
  border-radius: var(--au-r-md);
  font-size: 0.8125rem;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 0 3px 12px var(--au-primary-glow);
  transition: transform var(--au-fast);
}
.login-btn:hover { transform: translateY(-1px); }

/* 过渡 */
.dd-enter-active, .dd-leave-active { transition: opacity var(--au-fast), transform var(--au-fast); }
.dd-enter-from, .dd-leave-to { opacity: 0; transform: translateY(-6px); }

/* 窄屏：导航条目收窄，先让出用户名的宽度 */
@media (max-width: 1080px) {
  .user-name { display: none; }
  .nav-link { padding: 0.4688rem 0.625rem; }
}

/* 900~980px：品牌与账号操作都在一行时先去掉导航图标（比换行更像一根导航条） */
@media (max-width: 980px) and (min-width: 901px) {
  .nav-link { gap: 0; }
  .nav-link svg { display: none; }
}

/* ≤900px：顶栏变两行 —— 第一行品牌与账号操作，第二行是可横向滑动的主导航选项卡。
   四个入口在手机上基本放得下，横滑仍然保留：以后再加条目（或换成长名字的语言）时
   入口不会被挤成两三个字的碎片，也不用再在页面底部另开一条导航。 */
@media (max-width: 900px) {
  .header-container {
    flex-wrap: wrap;
    min-height: 0;
    padding: 0.5625rem 1rem 0;
    gap: 0.5rem;
  }

  .main-nav {
    order: 3;
    flex: 1 1 100%;
    margin-top: 0.125rem;
    padding: 0.5rem 0 0.5625rem;
    border-top: 1px solid var(--au-border);
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
    -ms-overflow-style: none;
    -webkit-overflow-scrolling: touch;
    /* 左右各留 14px 渐隐：提示「这一条还能继续滑」 */
    mask-image: linear-gradient(90deg, transparent 0, #000 14px, #000 calc(100% - 14px), transparent 100%);
    -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 14px, #000 calc(100% - 14px), transparent 100%);
  }

  .main-nav::-webkit-scrollbar { display: none; }

  .nav-link {
    flex: 0 0 auto;
    padding: 0.4375rem 0.6875rem;
    border-radius: var(--au-r-full);
    font-size: 0.8125rem;
  }

  .points-chip { display: none; }
  .msg-dropdown { width: min(292px, calc(100vw - 1.5rem)); }
  .user-dropdown { width: min(240px, calc(100vw - 1.5rem)); }
}
</style>
