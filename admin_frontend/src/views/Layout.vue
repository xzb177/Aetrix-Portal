<script setup lang="ts">
/**
 * 管理后台外壳（Console v6）
 *
 * 结构：固定侧边栏（≤1024px 变抽屉）+ 顶栏（页面标题 / 刷新 / 管理员菜单）+ 内容区。
 * 导航按业务域分组，可折叠（状态记在 localStorage），当前页所在分组自动展开；
 * 手机上抽屉打开时锁背景滚动、Esc / 点遮罩 / 切路由都能关。
 *
 * v2.25.0：一级导航按**交付链**重组（仪表盘 / 用户与账号 / 媒体与交付 / 求片与内容 /
 * 运营中心 / 服务支持 / 系统与审计）——“多服”不再是要先理解的一级概念：
 * 服与线路的归属关系在「服务器与线路」页按范围看，顶栏那个切换器只管当前作用域。
 * 所有页面路径一个字没动（旧收藏、外部链接照旧打开），改的只是分组与名称。
 */
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  LayoutDashboard, Users, Package, Film, Ticket, Settings, Server,
  Menu, X, ChevronDown, RefreshCw, LogOut, KeyRound, ExternalLink, Tv,
  CheckCircle2, Route as RealmIcon, Lock, Search, Wallet, Crown, MessageSquareDashed,
  TriangleAlert,
  Sun, Moon, MonitorSmartphone,
} from 'lucide-vue-next'
import { changePassword, fetchMe } from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
import { useRealmStore } from '@/stores/realm'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { useFocusTrap } from '@/composables/useFocusTrap'
import CommandPalette, { type PaletteItem } from '@/components/CommandPalette.vue'
// v2.42.4：后台白日/黑暗双主题（与用户端同一套三档口径）
import { useAdminTheme } from '@/composables/useTheme'
// 站名 / Logo 来自「站点与品牌」能力（改完刷新即生效，不用重新构建）
import { APP_VERSION as APP_VERSION_BASE, branding, siteName } from '@/composables/branding'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const realm = useRealmStore()
const { isTablet } = useBreakpoint()
// 外观三档：跟随系统 / 白日 / 黑暗。composable 自带 onMounted 挂监听，
// 切换只改 html[data-theme]，浅色令牌全在 tokens.css 的浅色块里
const { preference: themePreference, setPreference: setThemePreference } = useAdminTheme()

interface ThemeOption {
  value: 'system' | 'light' | 'dark'
  label: string
  title: string
}

const themeOptions: ThemeOption[] = [
  { value: 'system', label: '自动', title: '跟随系统' },
  { value: 'light', label: '白日', title: '白日模式' },
  { value: 'dark', label: '黑暗', title: '黑暗模式' },
]

/** 顶栏外观按钮（v2.42.9）：侧栏 foot 那排三段切换器**已删**，外观在本端只剩这一枚按钮，
 * 点一下轮换一档：跟随系统 → 白日 → 黑暗。
 *
 * 「自动」必须进这个环：旧版按钮只在白日/黑暗之间来回、「自动」档得去侧栏选，
 * 侧栏那排删掉后就再也回不到跟随系统了——这是本轮唯一的功能性取舍，在这里备查。 */
function cycleTheme() {
  const idx = themeOptions.findIndex((o) => o.value === themePreference.value)
  setThemePreference(themeOptions[(idx + 1) % themeOptions.length].value)
}

/** 当前档 / 下一档：按钮只有图标，说明全在 title / aria-label 里 */
const themeCurrent = computed(
  () => themeOptions.find((o) => o.value === themePreference.value) || themeOptions[0],
)
const themeNext = computed(
  () => themeOptions[(themeOptions.indexOf(themeCurrent.value) + 1) % themeOptions.length],
)
const themeTitle = computed(() => `外观：${themeCurrent.value.label}（点击切到${themeNext.value.label}）`)

/** 当前账号是不是超级管理员（角色见 backend/admin_roles.py）：只影响导航上的标记 */
const isSuper = computed(() => auth.admin?.is_super !== false)
/** 为什么有些入口标着锁：不是 super 时那些页面只能看、不能改 */
const SUPER_ONLY_HINT = '需要超级管理员角色：可以查看，保存会被服务端拒绝'
/** 侧边栏里的角色名（来自后端 /auth/me）：以前写死「超级管理员」，有角色后就不再真实了 */
const roleLabel = computed(() => auth.admin?.role_label || '超级管理员')

const APP_VERSION = APP_VERSION_BASE
const OPEN_GROUPS_KEY = 'admin_nav_groups'

const drawerOpen = ref(false)

/** 移动端抽屉模式下的 focus trap：窄屏侧边栏是覆盖层抽屉，Tab 不能跑到背后去 */
const sidebarRef = ref<HTMLElement | null>(null)
const sidebarTrapActive = computed(() => drawerOpen.value && isTablet.value)
useFocusTrap(sidebarRef, sidebarTrapActive)

interface NavItem {
  path: string
  label: string
  /** 仅超级管理员可写（v2.26.0）：其他角色能看，改不了——入口上直接标出来 */
  superOnly?: boolean
}

interface NavGroup {
  title: string
  icon: unknown
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  { title: '仪表盘', icon: LayoutDashboard, items: [{ path: '/', label: '仪表盘' }] },
  {
    title: '用户与账号',
    icon: Users,
    items: [
      { path: '/users', label: '用户' },
      { path: '/subscriptions', label: '订阅与权益' },
      { path: '/devices', label: '设备与安全' },
      // 客户端能做什么（转码 / 清晰度 / 准入 / 下载与设备）：与「设备与安全」互为补充
      { path: '/client-policy', label: '客户端策略', superOnly: true },
      { path: '/login-logs', label: '登录日志' },
    ],
  },
  {
    // 交付链：谁在出流 → 内容从哪来 → 内容怎么组织（旧页里的 服管理 不再占一个一级入口）
    title: '媒体与交付',
    icon: Server,
    items: [
      { path: '/servers', label: '服务器与线路' },
      { path: '/emby', label: '媒体库' },
      // 条目级的元数据（重刮 / 绑定 TMDB / 补全进度）与「按库配置」分开一处
      { path: '/metadata-sources', label: '元数据来源' },
      { path: '/mounts', label: '存储来源' },
      { path: '/pan115', label: '115 账号' },
    ],
  },
  {
    title: '求片与内容',
    icon: Film,
    items: [
      { path: '/media-seek', label: '求片管理' },
      { path: '/announcements', label: '公告管理' },
    ],
  },
  {
    title: '运营中心',
    icon: Package,
    items: [
      { path: '/goods', label: '商品与套餐' },
      { path: '/orders', label: '订单' },
      { path: '/exchange-codes', label: '兑换码' },
      { path: '/coupons', label: '优惠券' },
      { path: '/invitations', label: '邀请与积分' },
      { path: '/codes', label: '卡码管理' },
    ],
  },
  { title: '服务支持', icon: Ticket, items: [{ path: '/tickets', label: '工单' }] },
  {
    title: '系统与审计',
    icon: Settings,
    items: [
      { path: '/admins', label: '管理员与权限', superOnly: true },
      { path: '/settings', label: '系统设置', superOnly: true },
      { path: '/logs', label: '操作日志' },
      { path: '/health', label: '服务健康' },
    ],
  },
]

/**
 * 不占导航位置、但仍要归属到某个分组的页面（服管理 = 媒体与交付里的一条支线）
 *
 * 放进导航就会让「多服」又变成要先理解的一级概念——它的入口在「服务器与线路」页里，
 * 这里只负责面包屑归属与分组展开。
 */
const OFF_NAV_GROUP: Record<string, string> = { '/realms': '媒体与交付' }

/** 某个路径归哪个分组（含不占导航位置的页面，见 OFF_NAV_GROUP） */
function groupOf(path: string): NavGroup | undefined {
  const group = navGroups.find((g) => g.items.some((i) => i.path === path))
  if (group) return group
  const title = OFF_NAV_GROUP[path]
  return title ? navGroups.find((g) => g.title === title) : undefined
}

/** 当前路由所在分组 */
const activeGroup = computed(() => groupOf(route.path))

const pageTitle = computed(() => (route.meta.title as string) || '管理后台')
const crumbGroup = computed(() => (activeGroup.value?.items.length ? activeGroup.value.title : ''))

// ==================== 分组折叠（记住上次展开状态）====================

function loadOpenGroups(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(OPEN_GROUPS_KEY)
    if (raw) return JSON.parse(raw) as Record<string, boolean>
  } catch {
    /* 忽略损坏的缓存 */
  }
  return {}
}

const openGroups = reactive<Record<string, boolean>>(loadOpenGroups())

function persistOpenGroups() {
  try {
    localStorage.setItem(OPEN_GROUPS_KEY, JSON.stringify(openGroups))
  } catch {
    /* 隐私模式等场景写入失败不影响使用 */
  }
}

function isOpen(title: string): boolean {
  return !!openGroups[title]
}

function toggleGroup(title: string) {
  if (navGroups.find((g) => g.title === title)?.items.length === 1) return
  openGroups[title] = !openGroups[title]
  persistOpenGroups()
}

// ==================== 抽屉 ====================

function closeDrawer() {
  drawerOpen.value = false
}

watch(drawerOpen, (open) => {
  // 抽屉打开时锁住背景滚动（否则手机上滚的是底下的内容）
  document.body.style.overflow = open && isTablet.value ? 'hidden' : ''
})

function onKeydown(e: KeyboardEvent) {
  // ⌘K / Ctrl+K：全局命令搜索。面板自己会处理 Esc / 方向键 / Enter，
  // 这里只管开关（开着的时候按一下是收起来）
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
    // 命令面板与侧边栏抽屉都是浮层：开着抽屉时开面板，先把抽屉收掉，不叠两层遮罩
    if (paletteOpen.value) closeDrawer()
    return
  }
  if (e.key === 'Escape' && !paletteOpen.value) closeDrawer()
}

// ==================== 全局命令搜索（Phase 5） ====================

const paletteOpen = ref(false)

/** 命令面板里的「常用定位」：与仪表盘 KPI 用同一套深链，落地页筛选口径一致 */
const QUICK_JUMPS: PaletteItem[] = [
  { id: 'jump-tickets', label: '待处理工单', group: '常用定位', to: '/tickets?status=open', icon: Ticket, hint: '只看进行中的工单' },
  { id: 'jump-seeks', label: '待审求片', group: '常用定位', to: '/media-seek?status=pending', icon: MessageSquareDashed, hint: '只看待审核的求片' },
  { id: 'jump-orders', label: '待支付订单', group: '常用定位', to: '/orders?status=pending', icon: Wallet, hint: '只看待支付的订单' },
  { id: 'jump-expiring', label: '7 天内到期订阅', group: '常用定位', to: '/subscriptions?status=expiring', icon: Crown, hint: '续费窗口里的会员' },
]

/** 侧边栏的页面清单（含不占导航位置的 /realms）——命令面板不维护第二份 */
const pageCommands = computed<PaletteItem[]>(() => {
  const items: PaletteItem[] = []
  for (const group of navGroups) {
    for (const item of group.items) {
      // 超级管理员限定的页（如客户端策略 / 系统设置）与侧边栏同一个口径：
      // 不藏起来（藏了就找不到了），但在提示里说清「进去也没用」
      const locked = Boolean(item.superOnly) && !isSuper.value
      items.push({
        id: `page-${item.path}`,
        label: item.label,
        group: group.title,
        to: item.path,
        icon: group.icon,
        hint: locked ? SUPER_ONLY_HINT : item.path,
        keywords: locked ? '仅超级管理员' : undefined,
      })
    }
  }
  for (const [path, groupTitle] of Object.entries(OFF_NAV_GROUP)) {
    items.push({
      id: `page-${path}`,
      label: '服管理',
      group: groupTitle,
      to: path,
      icon: RealmIcon,
      hint: path,
      keywords: 'realm 服 切换',
    })
  }
  return items
})

/** 外观命令的提示写「点一下会切到哪一档」，免得点完不知道变成什么了 */
const themeCommandHint = computed(() => `切到${themeNext.value.label}`)

const actionCommands = computed<PaletteItem[]>(() => [
  { id: 'act-refresh', label: '刷新当前页', group: '操作', icon: RefreshCw, hint: '重新加载整页' },
  { id: 'act-theme', label: '切换外观', group: '操作', icon: MonitorSmartphone, hint: themeCommandHint.value },
  { id: 'act-password', label: '修改密码', group: '操作', icon: KeyRound, hint: '当前管理员账号' },
  { id: 'act-logout', label: '退出登录', group: '操作', icon: LogOut, hint: '清掉本地会话', danger: true },
  { id: 'act-danger', label: '危险操作', group: '操作', icon: TriangleAlert, hint: '熔断器 / 缓存 / 日志', keywords: '清理 清空 删除' },
].map((item) => ({ ...item, run: actionRun(item.id) })))

/** 动作命令统一走一张表 → 实际执行；`act-danger` 走深链（给 useQueryFilter 接住） */
function actionRun(id: string): () => void {
  if (id === 'act-refresh') return refreshPage
  if (id === 'act-theme') return cycleTheme
  if (id === 'act-password') return openPwdDialog
  if (id === 'act-danger') return () => router.push({ name: 'Settings', query: { tab: 'danger' } })
  return logout
}

const paletteItems = computed<PaletteItem[]>(() => [
  ...QUICK_JUMPS,
  ...pageCommands.value,
  ...actionCommands.value,
])

function onPaletteRun(item: PaletteItem) {
  if (item.to) {
    // 同一页只改 query 时 vue-router 不会重建组件，所以关面板 + 让目标页自己 watch query
    router.push(item.to)
    return
  }
  item.run?.()
}

watch(
  () => route.path,
  (path) => {
    closeDrawer()
    const group = groupOf(path)
    // 单项目分组不需要记忆；多项目分组进入时自动展开当前所在分组
    if (group && group.items.length > 1 && !openGroups[group.title]) {
      openGroups[group.title] = true
      persistOpenGroups()
    }
  },
)

function refreshPage() {
  router.go(0)
}

function logout() {
  auth.logout()
  router.push('/login')
}

// ==================== 修改密码 ====================

const pwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

function openPwdDialog() {
  pwdForm.old_password = ''
  pwdForm.new_password = ''
  pwdForm.confirm = ''
  pwdVisible.value = true
}

async function submitPwd() {
  if (pwdForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdLoading.value = true
  try {
    await changePassword({ old_password: pwdForm.old_password, new_password: pwdForm.new_password })
    ElMessage.success('密码已修改，请重新登录')
    pwdVisible.value = false
    auth.logout()
    router.push('/login')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '修改失败')
  } finally {
    pwdLoading.value = false
  }
}

function onAdminCommand(cmd: string) {
  if (cmd === 'password') openPwdDialog()
  else if (cmd === 'logout') logout()
}

// ==================== 当前服（多服运营）====================

/** 切换当前服：各页的作用域跟着切，所以切完整页重载一次，避免停在旧服的数据上 */
async function onRealmCommand(cmd: number | string) {
  if (cmd === '__manage') {
    router.push('/realms')
    return
  }
  const id = Number(cmd)
  if (!id || id === realm.activeId) return
  try {
    await realm.switchTo(id)
    ElMessage.success(`已切换到「${realm.activeName() || id}」`)
    window.setTimeout(() => window.location.reload(), 400)
  } catch {
    /* 拦截器已提示 */
  }
}

const initial = computed(() => (auth.admin?.username || 'A').charAt(0).toUpperCase())

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  // 当前服（服务端 active_realm_id 是权威来源）；失败不阻断后台，只是顶栏不显示服名
  realm.load().catch(() => undefined)
  // 进入后台时校正一次管理员身份（令牌失效 / 权限被回收时会被拦截器送回登录页）
  try {
    const me = await fetchMe()
    if (auth.token) auth.setSession(auth.token, me)
  } catch {
    /* 拦截器已处理 */
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <div class="shell admin-layout">
    <!-- 抽屉遮罩（窄屏点它关闭） -->
    <transition name="mask">
      <div v-if="drawerOpen" class="shell-mask" @click="closeDrawer" />
    </transition>

    <!-- 侧边栏：宽屏常驻，≤1024px 变抽屉 -->
    <aside
      ref="sidebarRef"
      class="sidebar"
      :class="{ open: drawerOpen }"
      :role="isTablet ? 'dialog' : undefined"
      :aria-modal="isTablet ? 'true' : undefined"
      aria-label="管理导航"
    >
      <div class="brand">
        <span class="brand-mark">
          <img v-if="branding.logo_url" :src="branding.logo_url" :alt="branding.site_name" />
          <Tv v-else :size="18" />
        </span>
        <div class="brand-text">
          <strong>{{ siteName() }}</strong>
          <span>管理控制台</span>
        </div>
        <button class="icon-btn brand-close" aria-label="关闭菜单" @click="closeDrawer">
          <X :size="18" />
        </button>
      </div>

      <nav class="nav">
        <template v-for="(group, gi) in navGroups" :key="group.title">
          <!-- 单项分组：直接是入口 -->
          <RouterLink
            v-if="group.items.length === 1"
            :to="group.items[0].path"
            class="nav-group-head nav-single"
            :class="{ active: route.path === group.items[0].path }"
          >
            <component :is="group.icon" :size="18" />
            <span>{{ group.title }}</span>
          </RouterLink>

          <!-- 多项分组：可折叠 -->
          <div v-else class="nav-group">
            <button
              class="nav-group-head"
              :class="{ active: activeGroup?.title === group.title && !isOpen(group.title) }"
              :aria-expanded="isOpen(group.title)"
              :aria-controls="`nav-group-${gi}`"
              @click="toggleGroup(group.title)"
            >
              <component :is="group.icon" :size="18" />
              <span>{{ group.title }}</span>
              <ChevronDown :size="15" class="chev" :class="{ open: isOpen(group.title) }" />
            </button>
            <div v-show="isOpen(group.title)" :id="`nav-group-${gi}`" class="nav-items">
              <RouterLink
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                class="nav-item"
                :class="{ active: route.path === item.path }"
              >
                <span class="nav-label">{{ item.label }}</span>
                <Lock v-if="item.superOnly && !isSuper" :size="12" class="nav-super" :title="SUPER_ONLY_HINT" />
              </RouterLink>
            </div>
          </div>
        </template>
      </nav>

      <div class="sidebar-foot">
        <!-- 外观三段切换器（.theme-row）已删（v2.42.9）：外观只剩顶栏那一枚圆形按钮，
             侧栏不再为「换主题」占一整块，腾出的空间留给账号块与页脚 -->
        <div class="who">
          <span class="who-avatar">{{ initial }}</span>
          <div class="who-info">
            <div class="who-name">{{ auth.admin?.username || '管理员' }}</div>
            <div class="who-role">{{ roleLabel }}</div>
          </div>
        </div>
        <div class="foot-links">
          <button class="foot-link" @click="openPwdDialog">
            <KeyRound :size="15" />修改密码
          </button>
          <a class="foot-link" href="/">
            <ExternalLink :size="15" />回到前台
          </a>
          <button class="foot-link danger" @click="logout">
            <LogOut :size="15" />退出登录
          </button>
        </div>
        <div class="foot-version">{{ siteName() }} {{ APP_VERSION }}</div>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main">
      <header class="topbar">
        <button class="icon-btn menu-btn" aria-label="打开菜单" @click="drawerOpen = true">
          <Menu :size="20" />
        </button>

        <div class="topbar-title">
          <h1>{{ pageTitle }}</h1>
          <span v-if="crumbGroup" class="topbar-crumb">{{ crumbGroup }}</span>
        </div>

        <div class="topbar-actions">
          <!-- 命令搜索（Phase 5）：桌面带 ⌘K 提示，手机只留图标（顶栏本来就很挤） -->
          <button
            class="cmd-btn"
            title="命令搜索（⌘K / Ctrl+K）"
            aria-label="命令搜索"
            @click="paletteOpen = true; closeDrawer()"
          >
            <Search :size="15" />
            <span class="cmd-btn-text">搜索</span>
            <kbd class="cmd-btn-kbd">⌘K</kbd>
          </button>

          <!-- 当前服：面板可以同时运营多个服，切完各页的作用域跟着走 -->
          <el-dropdown v-if="realm.realms.length" trigger="click" @command="onRealmCommand">
            <button class="realm-chip" aria-label="切换当前服">
              <RealmIcon :size="15" />
              <span class="realm-chip-name">{{ realm.activeName() || '当前服' }}</span>
              <ChevronDown :size="14" class="chip-chev" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="r in realm.realms"
                  :key="r.id"
                  :command="r.id"
                  :disabled="!r.is_active && r.id !== realm.activeId"
                >
                  <CheckCircle2
                    v-if="r.id === realm.activeId"
                    :size="14"
                    style="margin-right: 6px"
                  />
                  <span v-else style="display: inline-block; width: 20px" />
                  {{ r.name }}
                  <span v-if="!r.is_active" class="realm-off">（已停用）</span>
                </el-dropdown-item>
                <el-dropdown-item divided command="__manage">管理服…</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <!-- 外观（v2.42.9）：侧栏那排三段切换器删掉后，这里是本端唯一入口——
               图标即当前档（跟随系统 / 白日 / 黑暗），点一下轮换一档；
               手动指定档时品牌色实底，跟随系统时中性底 + 品牌色细环 -->
          <button
            class="icon-btn theme-quick"
            :class="{ auto: themePreference === 'system' }"
            :title="themeTitle"
            :aria-label="themeTitle"
            @click="cycleTheme"
          >
            <MonitorSmartphone v-if="themePreference === 'system'" :size="17" />
            <Sun v-else-if="themePreference === 'light'" :size="17" />
            <Moon v-else :size="17" />
          </button>
          <button class="icon-btn" title="刷新当前页" aria-label="刷新当前页" @click="refreshPage">
            <RefreshCw :size="17" />
          </button>
          <el-dropdown trigger="click" @command="onAdminCommand">
            <button class="admin-chip" aria-label="管理员菜单">
              <span class="chip-avatar">{{ initial }}</span>
              <span class="chip-name">{{ auth.admin?.username || '管理员' }}</span>
              <ChevronDown :size="14" class="chip-chev" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">
                  <KeyRound :size="15" style="margin-right: 8px" />修改密码
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>
                  <LogOut :size="15" style="margin-right: 8px" />退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content admin-content">
        <RouterView />
      </main>
    </div>

    <CommandPalette
      v-model="paletteOpen"
      :items="paletteItems"
      @run="onPaletteRun"
    />

    <el-dialog v-model="pwdVisible" title="修改密码" width="420px">
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="当前密码">
          <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="请输入当前密码" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="submitPwd">确认修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  min-height: 100dvh;
  background: transparent;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.icon-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

/* ==================== 外观（v2.42.9） ====================
   侧栏 foot 的三档分段（自动 / 白日 / 黑暗）已删，外观只剩顶栏这一枚圆形按钮：
   图标即当前档，点一下轮换一档。选中态分两类、靠底色一眼区分：
   · 手动指定档（白日 / 黑暗）→ 品牌色实底 + on-primary 图标 + 微光晕，
     与侧栏导航选中项、用户端顶栏同一套「主色实底压出来」的配方；
   · 跟随系统 → 中性底部 + 品牌色细环（表示这一档是生效中的「自动」，
     而不是「哪一个都没选」） */
.theme-quick { width: 32px; height: 32px; border-radius: var(--radius-full); }
.theme-quick.auto { border-color: var(--primary-border); }
.theme-quick.auto:hover { border-color: var(--primary); }
.icon-btn.theme-quick:not(.auto) {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--primary-on);
  box-shadow: 0 2px 10px var(--primary-glow);
}
.icon-btn.theme-quick:not(.auto):hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  color: var(--primary-on);
}

/* ==================== 侧边栏 ==================== */
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: var(--sidebar-w);
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-subtle);
  z-index: var(--z-sticky);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-subtle);
  min-height: var(--header-h);
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--gradient-brand);
  color: var(--primary-on);
}

.brand-text { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
.brand-text strong { font-size: var(--font-size-md); font-weight: var(--font-weight-bold); letter-spacing: 0.01em; }
.brand-text span { font-size: 11.5px; color: var(--text-muted); }
.brand-close { display: none; margin-left: auto; }

.nav {
  flex: 1;
  padding: 10px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.nav-group + .nav-group,
.nav-single + .nav-group { margin-top: 2px; }

.nav-group-head {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  text-align: left;
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.nav-group-head:hover { background: var(--bg-hover); color: var(--text-primary); }
.nav-group-head.active { background: var(--bg-active); color: var(--primary); font-weight: var(--font-weight-semibold); }
.nav-group-head .chev { margin-left: auto; color: var(--text-faint); transition: transform var(--transition-base); }
.nav-group-head .chev.open { transform: rotate(180deg); }

.nav-items { display: flex; flex-direction: column; gap: 2px; padding: 2px 0 6px; }

.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 12px 9px 41px;
  border-radius: var(--radius-md);
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.nav-item:hover { background: var(--bg-hover); color: var(--text-primary); }

.nav-label { flex: 1; min-width: 0; }
.nav-super { color: var(--text-faint); flex-shrink: 0; }

.nav-item.active {
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: var(--font-weight-semibold);
  box-shadow: inset 2px 0 0 0 var(--primary);
}

.sidebar-foot {
  padding: 12px;
  border-top: 1px solid var(--border-subtle);
  padding-bottom: calc(12px + env(safe-area-inset-bottom));
}

/* 账号块：外观切换器删掉后（v2.42.9），它就是侧栏 foot 的第一块，
   自己那条分隔线要去掉——.sidebar-foot 已有 border-top，两根挨着就是双线 */
.who {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 4px 12px;
}

.who-avatar,
.chip-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: var(--font-weight-bold);
  color: var(--primary-on);
  background: var(--gradient-brand);
}

.who-avatar { width: 34px; height: 34px; border-radius: var(--radius-full); font-size: 13px; flex-shrink: 0; }
.chip-avatar { width: 24px; height: 24px; border-radius: var(--radius-full); font-size: 11.5px; }

.who-info { flex: 1; min-width: 0; }
.who-name { font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.who-role { font-size: 11.5px; color: var(--text-muted); }

.foot-links { display: flex; flex-direction: column; gap: 2px; }

.foot-link {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
  text-align: left;
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.foot-link:hover { background: var(--bg-hover); color: var(--text-primary); }
.foot-link.danger:hover { background: var(--danger-bg); color: var(--danger); }

.foot-version {
  margin-top: 8px;
  padding: 0 12px;
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: var(--tracking-wide);
}

/* ==================== 主区域 ==================== */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  margin-left: var(--sidebar-w);
}

.topbar {
  position: sticky;
  top: 0;
  z-index: var(--z-float);
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: var(--header-h);
  padding: 0 20px;
  padding-top: env(safe-area-inset-top);
  /* 半透明表面：深浅色各由令牌分叉（color-mix 保住毛玻璃透底色的质感） */
  background: color-mix(in srgb, var(--bg-surface) 86%, transparent);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border-subtle);
}

.topbar-title { display: flex; align-items: baseline; gap: 10px; min-width: 0; }

.topbar-title h1 {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-crumb { font-size: var(--font-size-xs); color: var(--text-muted); flex-shrink: 0; }

.topbar-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

/* 命令搜索入口：与顶栏其它按钮同高；宽屏才展开文字 + ⌘K 提示 */
.cmd-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-full);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font: inherit;
  font-size: var(--font-size-xs);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}
.cmd-btn:hover { border-color: var(--primary-border); color: var(--text-primary); }
.cmd-btn-kbd {
  padding: 0 5px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  background: var(--bg-inset);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.7;
}

.admin-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px 5px 6px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: var(--bg-elevated);
  color: var(--text-primary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.admin-chip:hover { border-color: var(--border-strong); background: var(--bg-elevated); }
.chip-name { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-chev { color: var(--text-faint); }

/* 当前服：一眼看出“现在运营的是哪个服”，点开就能切 */
.realm-chip {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  transition: border-color var(--transition-fast), background var(--transition-fast);
}
.realm-chip:hover { border-color: var(--primary); color: var(--text-primary); }
.realm-chip-name { max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.realm-off { color: var(--text-faint); font-size: var(--font-size-xs); }

.content {
  flex: 1;
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
  padding: 20px;
}

/* 抽屉遮罩 */
.shell-mask {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-sticky) - 1);
  background: var(--bg-overlay);
  backdrop-filter: blur(3px);
}

.mask-enter-active,
.mask-leave-active { transition: opacity var(--transition-base); }
.mask-enter-from,
.mask-leave-to { opacity: 0; }

/* ==================== 响应式 ==================== */

/* ≤1024px（平板 / 小窗）：侧边栏收成抽屉。768~1024 这一档以前还是被挤扁的桌面布局 */
@media (max-width: 1024px) {
  .sidebar {
    z-index: var(--z-modal);
    transform: translateX(-100%);
    visibility: hidden;
    transition: transform var(--transition-base), visibility var(--transition-base);
    box-shadow: var(--shadow-lg);
  }

  .sidebar.open { transform: translateX(0); visibility: visible; }

  .brand-close { display: inline-flex; }
  .main { margin-left: 0; }
  .content { padding: 16px; }
}

@media (min-width: 1025px) {
  .menu-btn { display: none; }
  .sidebar { visibility: visible; }
}

/* 手机 */
@media (max-width: 768px) {
  .topbar { padding: 0 12px; padding-top: env(safe-area-inset-top); gap: 8px; }
  .topbar-title h1 { font-size: var(--font-size-lg); }
  .topbar-crumb { display: none; }
  .chip-name,
  .chip-chev { display: none; }
  /* 手机：只留放大镜图标，文字与 ⌘K 提示都藏起来（顶栏要留给服切换与账号） */
  .cmd-btn { width: 32px; padding: 0; justify-content: center; }
  .cmd-btn-text,
  .cmd-btn-kbd { display: none; }
  .realm-chip-name { max-width: 84px; }
  .admin-chip { padding: 4px; border-radius: var(--radius-full); }
  .chip-avatar { width: 28px; height: 28px; font-size: 12px; }
  .content { padding: 12px 12px calc(28px + env(safe-area-inset-bottom)); }
  .nav-item { padding: 11px 12px 11px 41px; }
  .nav-group-head { padding: 12px; }
}
</style>
