<script setup lang="ts">
/**
 * 管理后台外壳（Console v5）
 *
 * 结构：固定侧边栏（≤1024px 变抽屉）+ 顶栏（页面标题 / 刷新 / 管理员菜单）+ 内容区。
 * 导航按业务域分组，可折叠（状态记在 localStorage），当前页所在分组自动展开；
 * 手机上抽屉打开时锁背景滚动、Esc / 点遮罩 / 切路由都能关。
 */
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  LayoutDashboard, Users, Package, ShieldAlert, Film, Ticket, Settings,
  Menu, X, ChevronDown, RefreshCw, LogOut, KeyRound, ExternalLink, Tv,
  CheckCircle2, Route as RealmIcon,
} from 'lucide-vue-next'
import { changePassword, fetchMe } from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
import { useRealmStore } from '@/stores/realm'
import { useBreakpoint } from '@/composables/useBreakpoint'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const realm = useRealmStore()
const { isTablet } = useBreakpoint()

const APP_VERSION = 'v2.10.4'
const OPEN_GROUPS_KEY = 'admin_nav_groups'

const drawerOpen = ref(false)

interface NavItem {
  path: string
  label: string
}

interface NavGroup {
  title: string
  icon: unknown
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  { title: '概览', icon: LayoutDashboard, items: [{ path: '/', label: '数据概览' }] },
  {
    title: '用户与订阅',
    icon: Users,
    items: [
      { path: '/users', label: '用户管理' },
      { path: '/subscriptions', label: '订阅管理' },
    ],
  },
  {
    // 服的增删改查 + 归属它的服务器（EA / Emby 一个服一个）
    title: '多服运营',
    icon: RealmIcon,
    items: [
      { path: '/realms', label: '服管理' },
      // 这一页是 Emby 相关功能的唯一入口（入口 / 节点 / 挂载体检 / 库归属 + 增删改）
      { path: '/servers', label: '服务器 · Emby 总览' },
    ],
  },
  {
    title: '运营',
    icon: Package,
    items: [
      { path: '/goods', label: '商品与套餐' },
      { path: '/orders', label: '订单管理' },
      { path: '/exchange-codes', label: '兑换码' },
      { path: '/coupons', label: '优惠券' },
      { path: '/invitations', label: '邀请与积分' },
      { path: '/codes', label: '卡码管理' },
    ],
  },
  {
    title: '风控',
    icon: ShieldAlert,
    items: [
      { path: '/devices', label: '设备管理' },
      { path: '/login-logs', label: '登录与安全日志' },
    ],
  },
  {
    title: '内容',
    icon: Film,
    items: [
      { path: '/emby', label: '媒体库' },
      { path: '/mounts', label: '存储挂载' },
      { path: '/transfer-115', label: '115 转存' },
      { path: '/media-seek', label: '求片管理' },
      { path: '/announcements', label: '公告管理' },
    ],
  },
  { title: '支持', icon: Ticket, items: [{ path: '/tickets', label: '工单管理' }] },  { title: '系统',
    icon: Settings,
    items: [
      { path: '/settings', label: '系统设置' },
      { path: '/logs', label: '操作日志' },
      { path: '/health', label: '服务健康' },
    ],
  },
]

/** 当前路由所在分组 */
const activeGroup = computed(() => navGroups.find((g) => g.items.some((i) => i.path === route.path)))

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
  if (e.key === 'Escape') closeDrawer()
}

watch(
  () => route.path,
  (path) => {
    closeDrawer()
    const group = navGroups.find((g) => g.items.some((i) => i.path === path))
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
    <aside class="sidebar" :class="{ open: drawerOpen }">
      <div class="brand">
        <span class="brand-mark"><Tv :size="18" /></span>
        <div class="brand-text">
          <strong>RoyalBot</strong>
          <span>管理控制台</span>
        </div>
        <button class="icon-btn brand-close" aria-label="关闭菜单" @click="closeDrawer">
          <X :size="18" />
        </button>
      </div>

      <nav class="nav">
        <template v-for="group in navGroups" :key="group.title">
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
              @click="toggleGroup(group.title)"
            >
              <component :is="group.icon" :size="18" />
              <span>{{ group.title }}</span>
              <ChevronDown :size="15" class="chev" :class="{ open: isOpen(group.title) }" />
            </button>
            <div v-show="isOpen(group.title)" class="nav-items">
              <RouterLink
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                class="nav-item"
                :class="{ active: route.path === item.path }"
              >
                {{ item.label }}
              </RouterLink>
            </div>
          </div>
        </template>
      </nav>

      <div class="sidebar-foot">
        <div class="who">
          <span class="who-avatar">{{ initial }}</span>
          <div class="who-info">
            <div class="who-name">{{ auth.admin?.username || '管理员' }}</div>
            <div class="who-role">超级管理员</div>
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
        <div class="foot-version">RoyalBot {{ APP_VERSION }}</div>
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
  display: block;
  padding: 9px 12px 9px 41px;
  border-radius: var(--radius-md);
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.nav-item:hover { background: var(--bg-hover); color: var(--text-primary); }

.nav-item.active {
  background: var(--primary-bg);
  color: #7fe6f6;
  font-weight: var(--font-weight-semibold);
  box-shadow: inset 2px 0 0 0 var(--primary);
}

.sidebar-foot {
  padding: 12px;
  border-top: 1px solid var(--border-subtle);
  padding-bottom: calc(12px + env(safe-area-inset-bottom));
}

.who { display: flex; align-items: center; gap: 10px; padding: 4px 4px 12px; }

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
.foot-link.danger:hover { background: var(--danger-bg); color: #fda4af; }

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
  background: rgba(12, 18, 28, 0.86);
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

.admin-chip:hover { border-color: var(--border-strong); background: #1d2836; }
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
    box-shadow: 0 0 48px rgba(0, 0, 0, 0.5);
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
  .realm-chip-name { max-width: 84px; }
  .admin-chip { padding: 4px; border-radius: var(--radius-full); }
  .chip-avatar { width: 28px; height: 28px; font-size: 12px; }
  .content { padding: 12px 12px calc(28px + env(safe-area-inset-bottom)); }
  .nav-item { padding: 11px 12px 11px 41px; }
  .nav-group-head { padding: 12px; }
}
</style>
