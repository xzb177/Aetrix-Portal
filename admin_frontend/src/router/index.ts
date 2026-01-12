import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

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

// 路由守卫
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()

  // 设置页面标题
  document.title = `${to.meta.title || 'Aetrix 后台'} - 管理系统`

  // 检查是否需要登录
  if (to.meta.requiresAuth !== false && !authStore.isAuthenticated) {
    next('/login')
    return
  }

  // 检查权限
  if (to.meta.permission && !authStore.hasPermission(to.meta.permission as string)) {
    next('/')
    return
  }

  // 已登录用户访问登录页，跳转到首页
  if ((to.path === '/login' || to.path === '/m/login') && authStore.isAuthenticated) {
    next('/')
    return
  }

  next()
})

export default router
