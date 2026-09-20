<script setup lang="ts">
/**
 * 管理后台布局：分组侧边栏 + 面包屑顶栏 + 管理员菜单
 *
 * v2.4.0 调整：
 * - 导航按业务域分组（概览 / 用户与订阅 / 运营 / 内容 / 支持 / 系统），12 项不再平铺
 * - 顶栏改为面包屑，长页面也能知道自己在哪一层
 * - 管理员菜单接上「修改密码」（此前后端已实现、前端无处调用）
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterView, RouterLink, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  LayoutDashboard, Users, Ticket, Megaphone, Film, ScrollText,
  KeyRound, MessageSquareDashed, LogOut, Menu, X, ChevronRight,
  Wallet, Package, TicketCheck, Gift, Settings, Crown, RefreshCw,
  MonitorSmartphone, ShieldAlert,
} from 'lucide-vue-next'
import { changePassword, fetchMe } from '@/api/admin'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sidebarOpen = ref(false)

const APP_VERSION = 'v2.6.0'

interface NavItem {
  path: string
  label: string
  icon: unknown
  badge?: () => number | null
}

const navGroups: { title: string; items: NavItem[] }[] = [
  {
    title: '概览',
    items: [{ path: '/', label: '数据概览', icon: LayoutDashboard }],
  },
  {
    title: '用户与订阅',
    items: [
      { path: '/users', label: '用户管理', icon: Users },
      { path: '/subscriptions', label: '订阅管理', icon: Crown },
    ],
  },
  {
    title: '运营',
    items: [
      { path: '/goods', label: '商品与套餐', icon: Package },
      { path: '/orders', label: '订单管理', icon: Wallet },
      { path: '/exchange-codes', label: '兑换码', icon: TicketCheck },
      { path: '/invitations', label: '邀请与积分', icon: Gift },
      { path: '/codes', label: '卡码管理', icon: KeyRound },
    ],
  },
  {
    title: '风控',
    items: [
      { path: '/devices', label: '设备管理', icon: MonitorSmartphone },
      { path: '/login-logs', label: '登录与安全日志', icon: ShieldAlert },
    ],
  },
  {
    title: '内容',
    items: [
      { path: '/emby', label: '媒体库', icon: Film },
      { path: '/media-seek', label: '求片管理', icon: MessageSquareDashed },
      { path: '/announcements', label: '公告管理', icon: Megaphone },
    ],
  },
  {
    title: '支持',
    items: [{ path: '/tickets', label: '工单管理', icon: Ticket }],
  },
  {
    title: '系统',
    items: [
      { path: '/settings', label: '系统设置', icon: Settings },
      { path: '/logs', label: '操作日志', icon: ScrollText },
    ],
  },
]

/** 面包屑：分组名 + 页面名 */
const breadcrumb = computed(() => {
  for (const group of navGroups) {
    const hit = group.items.find((i) => i.path === route.path)
    if (hit) return { group: group.title, page: hit.label }
  }
  return { group: '', page: (route.meta.title as string) || '管理后台' }
})

/** 最新操作日志时间（顶栏「最近活动」轻提示，失败静默） */
const lastSync = ref('')

function refreshPage() {
  lastSync.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
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

/** 进入后台时校正一次管理员身份（令牌失效 / 权限被回收时会被拦截器送回登录页） */
onMounted(async () => {
  try {
    const me = await fetchMe()
    if (auth.token) auth.setSession(auth.token, me)
  } catch {
    // 拦截器已处理
  }
})
</script>

<template>
  <div class="admin-layout">
    <!-- 移动端遮罩 -->
    <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false" />

    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-brand">
        <span class="brand-mark" />
        <div class="brand-text">
          <strong>RoyalBot</strong>
          <span>{{ APP_VERSION }} 控制台</span>
        </div>
        <button class="icon-btn sidebar-close" @click="sidebarOpen = false" aria-label="关闭菜单">
          <X :size="18" />
        </button>
      </div>

      <nav class="sidebar-nav">
        <div v-for="group in navGroups" :key="group.title" class="nav-group">
          <div class="nav-group-title">{{ group.title }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
            @click="sidebarOpen = false"
          >
            <component :is="item.icon" :size="17" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="admin-who">
          <div class="who-avatar">{{ auth.admin?.username?.charAt(0).toUpperCase() || 'A' }}</div>
          <div class="who-info">
            <div class="who-name">{{ auth.admin?.username || '管理员' }}</div>
            <div class="who-role">超级管理员</div>
          </div>
          <button class="icon-btn" title="修改密码" @click="openPwdDialog">
            <KeyRound :size="15" />
          </button>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="admin-main">
      <header class="admin-topbar">
        <button class="icon-btn menu-btn" @click="sidebarOpen = true" aria-label="打开菜单">
          <Menu :size="20" />
        </button>

        <nav class="crumb" aria-label="面包屑">
          <span class="crumb-group">{{ breadcrumb.group }}</span>
          <ChevronRight :size="13" class="crumb-sep" />
          <span class="crumb-page">{{ breadcrumb.page }}</span>
        </nav>

        <span class="topbar-version">{{ APP_VERSION }}</span>

        <button class="icon-btn" title="刷新当前页" @click="refreshPage">
          <RefreshCw :size="16" />
        </button>

        <el-dropdown trigger="click" @command="onAdminCommand">
          <button class="admin-chip">
            <span class="chip-avatar">{{ auth.admin?.username?.charAt(0).toUpperCase() || 'A' }}</span>
            <span class="chip-name">{{ auth.admin?.username || '管理员' }}</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">
                <KeyRound :size="14" style="margin-right: 6px" />修改密码
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <LogOut :size="14" style="margin-right: 6px" />退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>

      <main class="admin-content">
        <RouterView />
      </main>
    </div>

    <el-dialog v-model="pwdVisible" title="修改密码" width="420px">
      <el-form label-width="88px" @submit.prevent>
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
.admin-layout {
  display: flex;
  min-height: 100vh;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
  border-color: var(--border-subtle);
}

/* ===== 侧边栏 ===== */
.sidebar {
  width: 236px;
  flex-shrink: 0;
  background: linear-gradient(180deg, rgba(13, 20, 32, 0.96), rgba(8, 12, 20, 0.96));
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 18px 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.brand-mark {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 10px;
  background: var(--gradient-brand);
  box-shadow: var(--shadow-glow);
}

.brand-text { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
.brand-text strong { font-size: 14px; letter-spacing: 0.02em; }
.brand-text span { font-size: 11px; color: var(--text-muted); }
.sidebar-close { display: none; margin-left: auto; }

.sidebar-nav {
  flex: 1;
  padding: 12px 10px 18px;
  overflow-y: auto;
}

.nav-group + .nav-group { margin-top: 14px; }

.nav-group-title {
  font-size: 11px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--text-muted);
  padding: 0 12px 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13.5px;
  margin-bottom: 2px;
  border: 1px solid transparent;
  transition: all var(--transition-fast);
}

.nav-item:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.nav-item.active {
  color: var(--primary);
  background: var(--primary-bg);
  border-color: var(--primary-border);
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border-subtle);
}

.admin-who { display: flex; align-items: center; gap: 10px; }

.who-avatar,
.chip-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: var(--primary-on);
  background: var(--gradient-brand);
}

.who-avatar { width: 32px; height: 32px; border-radius: 50%; font-size: 13px; flex-shrink: 0; }
.chip-avatar { width: 22px; height: 22px; border-radius: 50%; font-size: 11px; }

.who-info { flex: 1; min-width: 0; }
.who-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.who-role { font-size: 11px; color: var(--text-muted); }

/* ===== 顶栏 ===== */
.admin-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.admin-topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border-subtle);
  position: sticky;
  top: 0;
  background: rgba(7, 11, 18, 0.78);
  backdrop-filter: blur(12px);
  z-index: 10;
}

.crumb { display: flex; align-items: center; gap: 7px; font-size: 13.5px; min-width: 0; }
.crumb-group { color: var(--text-muted); }
.crumb-sep { color: var(--text-muted); flex-shrink: 0; }
.crumb-page { font-weight: 600; }

.topbar-version {
  margin-left: auto;
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
  padding: 3px 10px;
  border-radius: var(--radius-full);
}

.admin-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 5px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: var(--bg-glass);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.admin-chip:hover { border-color: var(--primary-border); background: var(--bg-glass-hover); }
.chip-name { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.admin-content {
  flex: 1;
  padding: 20px;
  max-width: 1440px;
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
    transition: transform var(--transition-base);
  }
  .sidebar.open { transform: translateX(0); }
  .sidebar-close { display: inline-flex; }
  .sidebar-mask {
    position: fixed;
    inset: 0;
    background: var(--bg-overlay);
    z-index: 40;
  }
  .menu-btn { display: inline-flex; }
  .crumb-group, .crumb-sep { display: none; }
  .chip-name { display: none; }
  .admin-content { padding: 14px; }
}
</style>
