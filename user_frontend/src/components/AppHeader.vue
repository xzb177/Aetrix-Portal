<script setup lang="ts">
import { RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import {
  Clapperboard, LogOut, Ticket, Inbox, Crown, Sparkles,
  Gift, Megaphone, AlertCircle, Clock, Sun, Moon, MonitorSmartphone, Bell,
  ChevronRight, LayoutDashboard, Check,
} from 'lucide-vue-next'
import api, {
  messageApi, announcementApi, isExpiringSoon, subscriptionApi,
  type StationMessage, type Announcement,
} from '@/api'
import type { MySubscription } from '@/api'
import { primaryNav, menuSections } from '@/config/navigation'
// 站名与 Logo 来自「站点与品牌」能力（没配就用默认值，不会出现空标题）
import { branding } from '@/composables/useBranding'
// 三档外观（跟随系统 / 白日 / 黑暗），见 useTheme.ts 的口径说明
import { useTheme } from '@/composables/useTheme'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()
const { preference: themePreference, setPreference: setThemePreference } = useTheme()

/**
 * 外观（v2.42.9 二改）：顶栏常驻一枚圆形图标按钮，点开一个**三选一的小菜单**
 * （跟随系统 / 白日 / 黑暗），当前档用品牌色勾选。
 *
 * 演进：三段切换器原在头像菜单里（占一整行、移动端点不到，见 a69f5ea）→ 一改
 * 搬到顶栏改成「点一下轮换一档」的单枚圆钮——只有图标，发现性差：没人知道
 * 能点、点了会切到哪（线上反馈「外观切换器被删了」）。二改改成点开菜单直接
 * 选：明确列出三档 + 当前档打勾，不是旧版三段式，也不需要盲猜轮换顺序；
 * 按钮仍放在登录判断之外（未登录也能切主题）。
 */
const themeModes = [
  { value: 'system', label: '跟随系统', icon: MonitorSmartphone },
  { value: 'light', label: '白日', icon: Sun },
  { value: 'dark', label: '黑暗', icon: Moon },
] as const

/** 当前档在环上的位置：脏存储值落到第一档（与 useTheme 的读法一致，不会出现 undefined） */
const themeIndex = computed(() => {
  const idx = themeModes.findIndex((m) => m.value === themePreference.value)
  return idx < 0 ? 0 : idx
})
const themeCurrent = computed(() => themeModes[themeIndex.value])
/** 图标按钮没有文字：当前档写进 title / aria-label，展开后菜单里三档可选 */
const themeTitle = computed(() => `外观：${themeCurrent.value.label}（点击选择）`)

const themeMenuOpen = ref(false)
const themeMenuRef = ref<HTMLElement | null>(null)

function toggleThemeMenu() {
  userMenuOpen.value = false
  msgMenuOpen.value = false
  themeMenuOpen.value = !themeMenuOpen.value
}

function pickTheme(value: 'system' | 'light' | 'dark') {
  setThemePreference(value)
  themeMenuOpen.value = false
}

const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
const navRef = ref<HTMLElement | null>(null)
const unreadCount = ref(0)

/**
 * 会员状态（v2.42.8 起只留在头像菜单里）：顶栏那两颗常驻 pill（积分 / 会员生效中）
 * 已按设计稿删除——积分由首页「我的资产」与钱包承接，会员状态由菜单头部承接。
 * 与轮询同频刷新：购买 / 续费后回到任何页面都能立刻看到新状态。
 */
const activeSub = ref<MySubscription | null>(null)

const subPillExpiring = computed(() => (activeSub.value ? isExpiringSoon(activeSub.value) : false))

/** 菜单头部的状态徽章：会员金 / 公益服青，与资产卡同一套色彩编码 */
const menuBadge = computed(() => {
  if (activeSub.value) {
    return {
      icon: Crown,
      text: subPillExpiring.value ? `剩 ${activeSub.value.days_left} 天` : '会员生效中',
      cls: 'gold',
    }
  }
  if (userStore.isFreeRealm) {
    return { icon: Sparkles, text: '公益服 · 免费', cls: 'cyan' }
  }
  return { icon: Crown, text: '未开通会员', cls: 'muted' }
})

/** 用户菜单里的操作项（纸片人式列表）；退出登录独立成红色分区，不混在列表里 */
const menuActions = computed(() => menuSections.flatMap((g) => g.items))

/** 昵称展示：登录名可能是一长串邮箱，头像旁只取 @ 前段；@id 用数字 id */
const displayName = computed(() => {
  const raw = userStore.user?.username || ''
  const at = raw.indexOf('@')
  return at > 0 ? raw.slice(0, at) : raw || '用户'
})

const userIdLabel = computed(() => (userStore.user?.id ? `@${userStore.user.id}` : ''))

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
 */

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function closeMenus() {
  userMenuOpen.value = false
  msgMenuOpen.value = false
  themeMenuOpen.value = false
}

async function handleLogout() {
  closeMenus()
  await userStore.logout()
  router.push('/login')
}

function onDocClick(e: MouseEvent) {
  const target = e.target as Node
  // 下拉已 Teleport 到 body：判断「点在不在菜单里」时把传送出去的面板也算自己人，
  // 否则菜单内任何一次点击都会被当成外部点击而立刻关闭
  const el = target instanceof Element ? target : null
  if (
    userMenuRef.value &&
    !userMenuRef.value.contains(target) &&
    !el?.closest('.user-dropdown')
  ) {
    userMenuOpen.value = false
  }
  if (
    msgMenuRef.value &&
    !msgMenuRef.value.contains(target) &&
    !el?.closest('.msg-dropdown')
  ) {
    msgMenuOpen.value = false
  }
  // 外观菜单不 Teleport：按钮与小菜单同在一个相对定位容器里，
  // contains 一把就能同时盖住「点按钮」与「点选项」
  if (
    themeMenuRef.value &&
    !themeMenuRef.value.contains(target)
  ) {
    themeMenuOpen.value = false
  }
}

async function refreshSubscription() {
  if (!userStore.isLoggedIn) return
  try {
    const subs = await subscriptionApi.getMine()
    activeSub.value = (Array.isArray(subs) ? subs : []).find(
      (s) => s.status === 'active' && s.days_left > 0,
    ) || null
  } catch {
    /* 静默：订阅态拿不到就不显示 pill，不为此报错打扰 */
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
  refreshSubscription()
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

// 签到 / 钱包操作后回到任意页面时，头像菜单里的会员状态即时刷新
watch(() => route.path, (p, old) => {
  const economyPaths = ['/wallet', '/checkin']
  if (userStore.isLoggedIn && (economyPaths.includes(old || '') || economyPaths.includes(p))) {
    refreshSubscription()
  }
})

watch(() => userStore.isLoggedIn, (loggedIn) => {
  if (loggedIn) poll()
  else {
    unreadCount.value = 0
    activeSub.value = null
    msgPreview.value = []
    msgMenuOpen.value = false
    userMenuOpen.value = false
    themeMenuOpen.value = false
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
          <img decoding="async" v-if="branding.logo_url" :src="branding.logo_url" :alt="branding.site_name" />
          <Clapperboard v-else :size="17" />
        </span>
        <span class="logo-text">{{ branding.site_name }}</span>
      </RouterLink>

      <!-- 主导航（全断点唯一一套）：≥900px 横排在品牌与账号操作之间，
           769~900px 落到第二行、变成可横向滑动的选项卡，
           ≤768px 整条让位给底部导航坞（AppDock） -->
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

      <!-- 右侧用户区（v2.42.9）：外观 + 消息 + 头像，三枚同一配方的圆形图标按钮，
           与管理后台顶栏同一形态；积分 / 会员 pill 与昵称都从顶栏撤下。
           外观按钮放在登录判断**之外**：未登录也能切主题（原先藏在头像菜单里，
           没登录时根本没有入口） -->
      <div class="user-section">
        <div ref="themeMenuRef" class="theme-menu">
          <button
            class="theme-btn round-btn"
            :class="{ auto: themePreference === 'system' }"
            :aria-expanded="themeMenuOpen"
            aria-haspopup="menu"
            :title="themeTitle"
            :aria-label="themeTitle"
            @click="toggleThemeMenu"
          >
            <component :is="themeCurrent.icon" :size="18" />
          </button>

          <!-- 外观小菜单（v2.42.9 二改）：三选一直选，替代「点一下轮换」。
               不 Teleport：小面板锚在按钮正下方，顶栏（sticky，无 overflow 裁剪）
               里的绝对定位后代照常溢出显示，头部 z-index:50 的堆叠上下文
               天然盖过底部坞（40） -->
          <Transition name="dd">
            <div v-if="themeMenuOpen" class="theme-dropdown" role="menu" aria-label="外观">
              <button
                v-for="m in themeModes"
                :key="m.value"
                class="theme-drop-item"
                :class="{ active: themePreference === m.value }"
                role="menuitemradio"
                :aria-checked="themePreference === m.value"
                @click="pickTheme(m.value)"
              >
                <span class="theme-drop-ic">
                  <component :is="m.icon" :size="15" />
                </span>
                <span class="theme-drop-label">{{ m.label }}</span>
                <Check
                  v-if="themePreference === m.value"
                  :size="14"
                  class="theme-drop-check"
                />
              </button>
            </div>
          </Transition>
        </div>

        <template v-if="userStore.isLoggedIn">
          <!-- 消息：保持一个安静的音铃（不在顶栏抢文案），点开先给预览 -->
          <div ref="msgMenuRef" class="msg-menu">
            <button
              class="msg-btn round-btn"
              :class="{ alert: unreadCount > 0, open: msgMenuOpen }"
              :title="unreadCount > 0 ? `${unreadCount} 条未读消息` : '消息中心'"
              @click="toggleMsgMenu"
            >
              <Inbox :size="18" />
              <span v-if="unreadCount > 0" class="msg-badge">
                {{ unreadCount > 99 ? '99+' : unreadCount }}
              </span>
            </button>

            <!-- 下拉用 Teleport 挂到 body：header 的 backdrop-filter 会把它变成
                 fixed 后代的包含块，fixed 定位会相对 header 而非视口（真机自测抓到过） -->
            <Teleport to="body">
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
            </Teleport>
          </div>

          <div ref="userMenuRef" class="user-menu">
            <button
              class="user-btn round-btn"
              :aria-expanded="userMenuOpen"
              aria-haspopup="menu"
              :aria-label="`${displayName} · 账号菜单`"
              :title="displayName"
              @click="userMenuOpen = !userMenuOpen"
            >
              <span class="avatar">{{ displayName.charAt(0).toUpperCase() }}</span>
            </button>

            <Teleport to="body">
            <Transition name="dd">
              <!-- 用户菜单（v2.42.3 纸片人式重做）。Teleport 到 body 后 fixed 定位真正相对视口：
                   ≤768px 底边锚在拇指区（底部坞）之上、内部滚动；z-index 60 在根层高于
                   顶栏（50）与底部坞（在其上下文内），低于 Toast（120）与弹窗（80 不冲突：
                   弹窗打开时应盖住菜单）。点击外部关闭的判定见 onDocClick 的 closest 兼容 -->
              <div v-if="userMenuOpen" class="user-dropdown" role="menu">
                <!-- ① 头部：头像 + 昵称 + @id + 状态徽章 -->
                <div class="dropdown-head">
                  <span class="avatar dropdown-avatar">{{ displayName.charAt(0).toUpperCase() }}</span>
                  <span class="dropdown-id">
                    <span class="dropdown-username">{{ displayName }}</span>
                    <span v-if="userIdLabel" class="dropdown-uid">{{ userIdLabel }}</span>
                  </span>
                  <span v-if="menuBadge" class="dropdown-status" :class="menuBadge.cls">
                    <component :is="menuBadge.icon" :size="11" />
                    {{ menuBadge.text }}
                  </span>
                </div>

                <!-- ② 操作项列表（外观三段切换器已删：v2.42.9 搬到顶栏那枚圆形按钮） -->
                <RouterLink
                  v-for="item in menuActions"
                  :key="item.path"
                  :to="item.path"
                  class="dropdown-item"
                  role="menuitem"
                  @click="closeMenus"
                >
                  <component :is="item.icon" :size="15" /> {{ item.name }}
                  <span
                    v-if="item.path === '/messages' && unreadCount > 0"
                    class="dropdown-badge"
                  >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
                </RouterLink>

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

                <!-- ③ 退出登录：独立红色分区（border-t 分隔） -->
                <button class="dropdown-item dropdown-logout" role="menuitem" @click="handleLogout">
                  <LogOut :size="15" /> 退出登录
                </button>
              </div>
            </Transition>
            </Teleport>
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
  /* 装饰圆要裁在顶栏内（下拉都 Teleport 到 body，不会被裁到） */
  overflow: hidden;
}

/* 顶栏也撒一颗品牌色装饰圆（v2.42.9，纸片人做法：见 HomeView 的 .hero-orb）：
   右上一团 5% 品牌色 + 64px 模糊，纯静态单次合成、不参与动画。
   深色下让顶栏右上角有一点品牌色呼吸，浅色下是一团极淡的色渍 */
.app-header::after {
  content: '';
  position: absolute;
  top: -64px;
  right: 6%;
  width: 200px;
  height: 200px;
  border-radius: 50%;
  background: var(--au-primary);
  opacity: 0.05;
  filter: blur(64px);
  pointer-events: none;
}

.header-container {
  position: relative;
  /* 压住上面的装饰圆：伪元素是同层的最后一个盒子，抬一层才不会被它蒙住 */
  z-index: 1;
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
  gap: 0.375rem;
  min-width: 0;
}

/* 导航「片」（v2.42.9 纸片人化）：默认是一枚描边透明的空片，悬停时浮出浅表面 +
   细描边，当前页用品牌色实底压出来 —— 与外观按钮、菜单里的选中态同一套语言
   （同一件事只有一种表达）。描边常驻而非 hover 才加，避免悬停时 1px 的布局跳动 */
.nav-link {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 0.75rem;
  border: 1px solid transparent;
  border-radius: var(--au-r-full);
  font-size: 0.875rem;
  font-weight: 500;
  white-space: nowrap;
  color: var(--au-text-2);
  text-decoration: none;
  transition: background var(--au-fast) var(--au-ease),
    border-color var(--au-fast) var(--au-ease),
    color var(--au-fast) var(--au-ease),
    box-shadow var(--au-fast) var(--au-ease);
}

.nav-link svg { opacity: 0.75; }

.nav-link:hover {
  color: var(--au-text);
  background: var(--au-surface-2);
  border-color: var(--au-border);
}

.nav-link:active { transform: scale(0.98); }

/* 当前页：主色实底 + on-primary 字（浅色主题 #0891b2 配白字，深色主题 #22d3ee
   配近黑字）+ 微光晕。旧版只有 12% 主色淡底，在顶栏这种低对比区域里几乎看不出
   当前在哪一页 */
.nav-link-active,
.nav-link-active:hover {
  color: var(--au-on-primary);
  background: var(--au-primary);
  border-color: var(--au-primary);
  font-weight: 600;
  box-shadow: 0 2px 10px var(--au-primary-glow);
}

.nav-link-active svg { opacity: 1; }

/* 键盘焦点环：与全站其余可聚焦元素同一配方（替代掉的 .theme-opt:focus-visible 同源） */
.nav-link:focus-visible {
  outline: 2px solid var(--au-border-focus);
  outline-offset: 2px;
}

.user-section {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  min-width: 0;
}

/* ==================== 右侧圆形图标按钮（v2.42.8） ====================
   与管理后台顶栏同一形态：一枚圆形按钮（浅色表面 + 1px 描边 + 居中的图标），
   hover 时描边与底色各抬一档。顶栏因此只剩「品牌 · 消息 · 头像」三件事——
   原常驻的积分 pill 与「会员生效中」pill 已删（图 4 圈出的两颗），
   积分仍在首页「我的资产」/ 钱包、会员状态仍在头像菜单头部各有入口。 */
.round-btn {
  position: relative;
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  background: var(--au-surface);
  color: var(--au-text-2);
  cursor: pointer;
  transition: background var(--au-fast) var(--au-ease),
    border-color var(--au-fast) var(--au-ease),
    color var(--au-fast) var(--au-ease);
}

.round-btn:hover {
  color: var(--au-text);
  background: var(--au-surface-2);
  border-color: var(--au-border-strong);
}

.round-btn:active { transform: scale(0.96); }

.round-btn:focus-visible {
  outline: 2px solid var(--au-border-focus);
  outline-offset: 2px;
}

/* ==================== 顶栏外观（v2.42.9 二改） ====================
   一改把外观从用户菜单搬到顶栏、做成「点一下轮换一档」的单枚圆钮——
   只有图标，发现性差（线上反馈「切换器被删了」）。二改：同一枚圆钮改成
   点开三选一的小菜单，当前档在菜单里用品牌色勾选——不是旧版三段切换器，
   也不需要盲猜轮换顺序。按钮的选中态分两类、靠底色一眼区分：
   · 手动指定档（白日 / 黑暗）→ 品牌色实底 + on-primary 图标 + 微光晕
     （与主导航当前页、菜单选中态同一套「主色实底压出来」的配方）；
   · 跟随系统 → 中性表面 + 品牌色细环 —— 表示这一档是生效中的「自动」，
     而不是「哪一个都没选」。 */
.theme-menu { position: relative; }

.theme-btn.auto { border-color: var(--au-primary-border); }
.theme-btn.auto:hover { border-color: var(--au-primary); }

.theme-btn:not(.auto) {
  background: var(--au-primary);
  border-color: var(--au-primary);
  color: var(--au-on-primary);
  box-shadow: 0 2px 10px var(--au-primary-glow);
}

.theme-btn:not(.auto):hover {
  background: var(--au-primary-strong);
  border-color: var(--au-primary-strong);
  color: var(--au-on-primary);
}

/* 外观小菜单：锚在按钮正下方的窄面板（小面板不需要 Teleport 那套
   fixed 底部锚定——它不会伸进底部坞的拇指区） */
.theme-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  min-width: 176px;
  padding: 0.375rem;
  background: var(--au-overlay-menu);
  border: 1px solid var(--au-border-strong);
  border-radius: var(--au-r-lg);
  box-shadow: var(--au-shadow-2);
  z-index: 60;
}

.theme-drop-item {
  display: flex;
  align-items: center;
  gap: 0.5625rem;
  width: 100%;
  padding: 0.5rem 0.5rem 0.5rem 0.4375rem;
  border: 0;
  border-radius: var(--au-r-md);
  background: transparent;
  color: var(--au-text-2);
  font-size: 0.8125rem;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: background var(--au-fast) var(--au-ease),
    color var(--au-fast) var(--au-ease);
}
.theme-drop-item:hover {
  background: var(--au-surface-2);
  color: var(--au-text);
}
.theme-drop-item:focus-visible {
  outline: 2px solid var(--au-border-focus);
  outline-offset: 1px;
}
.theme-drop-ic {
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
.theme-drop-label { flex: 1; }
.theme-drop-item.active { color: var(--au-primary); }
.theme-drop-item.active .theme-drop-ic {
  background: var(--au-primary);
  color: var(--au-on-primary);
}
.theme-drop-check { color: var(--au-primary); flex-shrink: 0; }

/* 消息入口：圆形图标按钮（配方见 .round-btn），有未读时才点一颗小数字 */
.msg-menu { position: relative; }

.msg-btn.open {
  color: var(--au-text);
  background: var(--au-surface-3);
  border-color: var(--au-border-strong);
}
.msg-btn.alert { color: var(--au-warning); border-color: var(--au-warning-border); }

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
  font-size: 0.75rem;
  font-weight: 800;
  border-radius: var(--au-r-full);
  /* 与页面底色同色的描边环，把徽章从任何背景上“抠”出来 */
  box-shadow: 0 0 0 2px var(--au-overlay);
}

/* msg-dropdown / user-dropdown 及其内部样式已移至下方全局块（Teleport 到 body 后 scoped 不生效） */

.user-menu { position: relative; }

/* 头像按钮：与消息按钮同一配方（.round-btn），里面正好嵌一颗 30px 头像
   （昵称不再出现在顶栏 → 菜单头部那一行仍是完整身份展示） */
.user-btn { padding: 3px; }

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

/* ==================== 用户菜单样式已移至全局块（Teleport） ==================== */

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

/* 过渡：柔和上浮淡入（opacity+transform，合成器友好） */
.dd-enter-active, .dd-leave-active { transition: opacity var(--au-med) var(--au-ease), transform var(--au-med) var(--au-ease); }
.dd-enter-from, .dd-leave-to { opacity: 0; transform: translateY(-6px) scale(0.98); }

@media (prefers-reduced-motion: reduce) {
  .dd-enter-active, .dd-leave-active { transition: none; }
}

/* 窄屏：导航条目收窄（顶栏右侧只剩两枚圆形按钮，不再需要给用户名让宽度） */
@media (max-width: 1080px) {
  .nav-link { padding: 0.4688rem 0.625rem; }
}

/* 900~980px：品牌与账号操作都在一行时先去掉导航图标（比换行更像一根导航条） */
@media (max-width: 980px) and (min-width: 901px) {
  .nav-link { gap: 0; }
  .nav-link svg { display: none; }
}

/* 769~900px：窄屏保留两行形态（顶栏主导航仍是唯一导航，底部坞未出现） */
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

  .msg-dropdown { width: min(292px, calc(100vw - 1.5rem)); }
}

</style>

<!-- 下拉已 Teleport 到 body，scoped 样式不跨树：两个下拉的完整样式放全局块。
     data-v- 剔除后由类名本身保证作用域（user-dropdown / msg-dropdown 只在这一处渲染） -->
<style>
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

.user-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: 236px;
  background: var(--au-overlay-menu);
  border: 1px solid var(--au-border-strong);
  border-radius: var(--au-r-lg);
  box-shadow: var(--au-shadow-2);
  overflow-y: auto;
  overscroll-behavior: contain;
  max-height: min(70vh, 480px);
  z-index: 60;
  scrollbar-width: thin;
}

@media (max-width: 768px) {
  /* 挂到 body 后 fixed 终于是真视口定位：底边锚在拇指区之上（--au-dock-space
     由 aurora.css 按断点定义），宽度留 12px 呼吸边，高过视口时内部滚 */
  .user-dropdown,
  .msg-dropdown {
    position: fixed;
    top: auto;
    right: 12px;
    bottom: calc(var(--au-dock-space) + 12px);
    width: min(320px, calc(100vw - 24px));
    max-height: calc(100dvh - 140px);
    overflow-y: auto;
  }
}

/* msg-dropdown 内部（原 scoped 规则原样搬来） */
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
  font-size: 0.75rem;
  font-weight: 700;
}
.msg-drop-clear { font-size: 0.75rem; color: var(--au-text-3); }
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
.msg-drop-ic.hot { background: var(--au-warning-soft); color: var(--au-warning); }
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
.msg-drop-meta { font-size: 0.75rem; color: var(--au-text-3); }
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
  color: var(--au-text-3);
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

/* user-dropdown 内部 */
.dropdown-head {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.875rem 1rem;
  border-bottom: 1px solid var(--au-border);
}
.dropdown-avatar {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  font-size: 0.9375rem;
  box-shadow: 0 0 0 2px var(--au-primary-soft);
}
.dropdown-id {
  display: flex;
  flex-direction: column;
  gap: 0.0625rem;
  min-width: 0;
  flex: 1;
}
.dropdown-username {
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dropdown-uid {
  font-size: 0.75rem;
  color: var(--au-text-3);
  font-variant-numeric: tabular-nums;
}
.dropdown-status {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  padding: 0.1875rem 0.5rem;
  border-radius: var(--au-r-full);
  font-size: 0.6875rem;
  font-weight: 700;
}
.dropdown-status.gold {
  background: var(--au-warning-soft);
  border: 1px solid var(--au-warning-border);
  color: var(--au-warning);
}
.dropdown-status.cyan {
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  color: var(--au-primary);
}
.dropdown-status.muted {
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  color: var(--au-text-3);
}
/* 外观三段切换器（.theme-seg / .theme-opt）与它的分组标题（.dropdown-group-title）
   已在 v2.42.9 删除：外观改由顶栏那枚圆形图标按钮承担（.theme-btn） */
.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  min-height: 40px;
  padding: 0.625rem 1rem;
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
.dropdown-item:active { background: var(--au-surface-3); }
.dropdown-item svg { color: var(--au-text-3); transition: color var(--au-fast) var(--au-ease); }
.dropdown-item:hover svg { color: var(--au-primary); }
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
  font-size: 0.75rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}
.dropdown-logout {
  color: var(--au-danger);
  border-top: 1px solid var(--au-border);
}
.dropdown-logout svg { color: var(--au-danger); }
.dropdown-logout:hover { background: var(--au-danger-soft); color: var(--au-danger); }
.dropdown-logout:hover svg { color: var(--au-danger); }
</style>

<style scoped>
/* ≤768px：顶栏退成单行（品牌 + 消息 + 头像），主导航交给底部坞（AppDock）。
   两个下拉都改成 fixed 面板：① 挂在 header 的堆叠上下文里但 z 高于坞的绘制顺序问题
   已不存在——fixed 仍受 header 的 z-index:50 上下文约束，因此坞提到 40、
   下拉保持 60（见 AppDock 同步调整），同一上下文内 60 > 50 稳赢；
   ② max-height + 内部滚动保证菜单永不伸进底部坞的拇指区 */
@media (max-width: 768px) {
  .header-container {
    flex-wrap: nowrap;
    padding: 0 1rem;
    min-height: 54px;
    /* 手机顶栏是「品牌 + 外观 + 消息 + 头像」四件事（v2.42.9 起外观也常驻顶栏），
       间距用正常口径；双 pill 时代为塞下胶囊才把它压到 0.25rem */
    gap: 0.625rem;
  }

  /* 主导航整条让位给底部坞（AppDock）；圆形按钮保持桌面口径不缩水 */
  .main-nav { display: none; }

  .header-logo { gap: 0.375rem; }
  .logo-mark { width: 30px; height: 30px; border-radius: 10px; }
}

/* 超窄屏（≤400px，含 iPhone SE（375））：两侧再各收 4px。
   三枚圆形按钮是拇指目标，尺寸不跟着缩——现在空出的宽度足够放下它们
   （375px 下：内距 24 + 品牌 ~91 + 三枚 114 + 两个 8px 间距 = ~245px） */
@media (max-width: 400px) {
  .header-container { padding: 0 0.75rem; gap: 0.5rem; }
}
</style>
