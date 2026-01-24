import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useLoadingStore } from '@/stores/loading'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/m/login',
    name: 'MobileLogin',
    component: () => import('@/views/MobileLogin.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/views/Layout.vue'),
    meta: { requiresAuth: true },
    children: [
      // ==================== 首页 ====================
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '数据概览', icon: 'Home', permission: 'stats.view' },
      },

      // ==================== Emby 数据统计 ====================
      {
        path: 'heatmap',
        name: 'Heatmap',
        component: () => import('@/views/Heatmap.vue'),
        meta: { title: '播放热力图', icon: 'Flame', permission: 'stats.view' },
      },
      {
        path: 'popular-content',
        name: 'PopularContent',
        component: () => import('@/views/PopularContent.vue'),
        meta: { title: '热门内容', icon: 'TrendingUp', permission: 'stats.view' },
      },
      {
        path: 'user-behavior',
        name: 'UserBehavior',
        component: () => import('@/views/UserBehavior.vue'),
        meta: { title: '用户行为', icon: 'BarChart', permission: 'stats.view' },
      },

      // ==================== 用户管理 ====================
      {
        path: 'portal-users',
        name: 'PortalUsers',
        component: () => import('@/views/PortalUsers.vue'),
        meta: { title: '门户用户', icon: 'Users', permission: 'users.view' },
      },
      {
        path: 'users/:id',
        name: 'UserDetail',
        component: () => import('@/views/UserDetail.vue'),
        meta: { title: '用户详情', hidden: true },
      },
      {
        path: 'subscriptions',
        name: 'Subscriptions',
        component: () => import('@/views/Subscriptions.vue'),
        meta: { title: '订阅套餐', icon: 'CreditCard', permission: 'subscriptions.view' },
      },
      {
        path: 'exchange-codes',
        name: 'ExchangeCodes',
        component: () => import('@/views/ExchangeCodes.vue'),
        meta: { title: '兑换码管理', icon: 'Ticket', permission: 'system.manage' },
      },

      // ==================== Emby 管理 ====================
      {
        path: 'emby-servers',
        name: 'EmbyServers',
        component: () => import('@/views/EmbyServers.vue'),
        meta: { title: 'Emby服务器', icon: 'Server', permission: 'emby.view' },
      },
      {
        path: 'online-sessions',
        name: 'OnlineSessions',
        component: () => import('@/views/OnlineSessions.vue'),
        meta: { title: '在线用户', icon: 'Users', permission: 'emby.view' },
      },
      {
        path: 'transcoding',
        name: 'Transcoding',
        component: () => import('@/views/TranscodingMonitor.vue'),
        meta: { title: '转码监控', icon: 'Zap', permission: 'emby.view' },
      },

      // ==================== 内容管理 ====================
      {
        path: 'media-requests',
        name: 'MediaRequests',
        component: () => import('@/views/MediaRequests.vue'),
        meta: { title: '求片管理', icon: 'Film', permission: 'content.view' },
      },

      // ==================== 通信与工单 ====================
      {
        path: 'tickets',
        name: 'Tickets',
        component: () => import('@/views/Tickets.vue'),
        meta: { title: '工单系统', icon: 'MessageSquare', permission: 'tickets.view' },
      },
      {
        path: 'tickets/:id',
        name: 'TicketDetail',
        component: () => import('@/views/TicketDetail.vue'),
        meta: { title: '工单详情', hidden: true },
      },
      {
        path: 'invitations',
        name: 'Invitations',
        component: () => import('@/views/Invitations.vue'),
        meta: { title: '邀请管理', icon: 'Users', permission: 'users.view' },
      },
      {
        path: 'messages',
        name: 'Messages',
        component: () => import('@/views/Messages.vue'),
        meta: { title: '站内消息', icon: 'MessageCircle', permission: 'system.view' },
      },
      {
        path: 'announcements',
        name: 'Announcements',
        component: () => import('@/views/Announcements.vue'),
        meta: { title: '公告管理', icon: 'Megaphone', permission: 'announcements.view' },
      },

      // ==================== 支付管理 ====================
      {
        path: 'payment-config',
        name: 'PaymentConfig',
        component: () => import('@/views/PaymentConfig.vue'),
        meta: { title: '支付配置', icon: 'CreditCard', permission: 'system.config' },
      },
      {
        path: 'payment-orders',
        name: 'PaymentOrders',
        component: () => import('@/views/PaymentOrders.vue'),
        meta: { title: '支付订单', icon: 'Receipt', permission: 'system.view' },
      },

      // ==================== 系统管理 ====================
      {
        path: 'routes',
        name: 'Routes',
        component: () => import('@/views/Routes.vue'),
        meta: { title: '线路管理', icon: 'Route', permission: 'routes.view' },
      },
      {
        path: 'admin-ops',
        name: 'AdminOps',
        component: () => import('@/views/AdminOps.vue'),
        meta: { title: '运营中控台', icon: 'Shield', permission: 'system.admin' },
      },
      {
        path: 'admins',
        name: 'Admins',
        component: () => import('@/views/Admins.vue'),
        meta: { title: '管理员', icon: 'Users', permission: 'system.admins' },
      },
      {
        path: 'roles',
        name: 'Roles',
        component: () => import('@/views/Roles.vue'),
        meta: { title: '角色权限', icon: 'Shield', permission: 'system.roles' },
      },
      {
        path: 'system-logs',
        name: 'SystemLogs',
        component: () => import('@/views/SystemLogs.vue'),
        meta: { title: '系统日志', icon: 'FileText', permission: 'system.logs' },
      },
      {
        path: 'security',
        name: 'Security',
        component: () => import('@/views/Security.vue'),
        meta: { title: '安全设置', icon: 'Shield', permission: 'system.config' },
      },
      {
        path: 'system-config',
        name: 'SystemConfig',
        component: () => import('@/views/SystemSettings.vue'),
        meta: { title: '系统配置', icon: 'Settings', permission: 'system.config' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/Settings.vue'),
        meta: { title: '系统设置', icon: 'Settings', permission: 'system.config' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes,
})

// ============================================================
// 自诊断模式 - 路由守卫增强日志
// ============================================================

// 调试日志辅助函数
const debugLog = (category: string, message: string, data?: any) => {
  const timestamp = new Date().toLocaleTimeString()
  const logMsg = `[${timestamp}] [${category}] ${message}`
  console.log(logMsg, data || '')

  // 写入全局调试日志（如果启用）
  if ((window as any).__addDebugLog) {
    ;(window as any).__addDebugLog(`${category}: ${message}`)
    if (data) {
      ;(window as any).__addDebugLog(`  -> ${JSON.stringify(data)}`)
    }
  }
}

// 检测 sessionStorage 可用性
const checkSessionStorage = () => {
  try {
    const testKey = '__session_storage_test__'
    sessionStorage.setItem(testKey, '1')
    sessionStorage.removeItem(testKey)
    return { available: true }
  } catch (e) {
    return { available: false, error: (e as Error).message }
  }
}

// 路由守卫
router.beforeEach((to, from, next) => {
  debugLog('Router', `=== 守卫检查 ===`)
  debugLog('Router', `from: ${from.fullPath} -> to: ${to.fullPath}`)

  // 检测 sessionStorage
  const storageCheck = checkSessionStorage()
  debugLog('Router', `sessionStorage 可用: ${storageCheck.available}`, storageCheck.error ? { error: storageCheck.error } : undefined)

  const authStore = useAuthStore()

  // 关键修复：每次守卫执行前，先从 sessionStorage 恢复状态
  // 解决 Pinia store 实例状态不一致问题（特别是 Safari）
  authStore.restoreState()
  debugLog('Router', `restoreState 已调用`)

  // 检查 localStorage 和 sessionStorage 的内容
  const localStorageKeys = Object.keys(localStorage)
  const sessionStorageKeys = Object.keys(sessionStorage)
  debugLog('Router', `存储状态`, {
    localStorage: localStorageKeys.filter(k => k.includes('admin') || k.includes('token')),
    sessionStorage: sessionStorageKeys.filter(k => k.includes('admin') || k.includes('token'))
  })

  // 设置页面标题
  document.title = `${to.meta.title || 'Aetrix 后台'} - 管理系统`

  // 详细的状态日志
  debugLog('Router', `认证状态检查`, {
    isAuthenticated: authStore.isAuthenticated,
    hasAdminInfo: !!authStore.adminInfo,
    adminUsername: authStore.adminInfo?.username || '(none)',
    requiresAuth: to.meta.requiresAuth,
    permission: to.meta.permission
  })

  // 分支判断日志
  const needsAuth = to.meta.requiresAuth !== false
  if (needsAuth && !authStore.isAuthenticated) {
    debugLog('Router', `>>> 分支: 未认证，重定向到 /login`)
    next('/login')
    return
  }

  if (to.meta.permission && !authStore.hasPermission(to.meta.permission as string)) {
    debugLog('Router', `>>> 分支: 权限不足，重定向到 /`)
    next('/')
    return
  }

  if ((to.path === '/login' || to.path === '/m/login') && authStore.isAuthenticated) {
    debugLog('Router', `>>> 分支: 已登录访问登录页，重定向到 /`)
    next('/')
    return
  }

  debugLog('Router', `>>> 分支: 通过检查，继续导航到 ${to.path}`)
  next()
})

// 路由导航后日志
router.afterEach((to, from) => {
  debugLog('Router', `导航完成: ${from.fullPath} -> ${to.fullPath}`)
  debugLog('Router', `当前 URL: ${window.location.href}`)

  // 兜底：确保每次路由切换后清除 loading 状态（DOM class）
  const appEl = document.getElementById('app')
  if (appEl && appEl.classList.contains('loading')) {
    appEl.classList.remove('loading')
    console.log('[Router] Loading cleared after navigation')
  }

  // 兜底：强制停止全局 loading store
  const loadingStore = useLoadingStore()
  loadingStore.ensureStopped('router.afterEach')
})

// 路由错误处理 - 确保 loading 不会卡住
router.onError((error) => {
  console.error('[Router] Navigation error:', error)

  // 强制停止所有 loading
  const loadingStore = useLoadingStore()
  loadingStore.ensureStopped('router.onError')

  // 清除 DOM loading class
  const appEl = document.getElementById('app')
  if (appEl && appEl.classList.contains('loading')) {
    appEl.classList.remove('loading')
    console.log('[Router] Loading cleared due to navigation error')
  }
})

export default router
