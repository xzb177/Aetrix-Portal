import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '管理员登录', requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/views/Layout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'Dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '数据概览' } },
      { path: 'users', name: 'Users', component: () => import('@/views/Users.vue'), meta: { title: '用户管理' } },
      { path: 'subscriptions', name: 'Subscriptions', component: () => import('@/views/Subscriptions.vue'), meta: { title: '订阅管理' } },
      { path: 'goods', name: 'Goods', component: () => import('@/views/Goods.vue'), meta: { title: '商品管理' } },
      { path: 'orders', name: 'Orders', component: () => import('@/views/Orders.vue'), meta: { title: '运营·订单' } },
      { path: 'exchange-codes', name: 'ExchangeCodes', component: () => import('@/views/ExchangeCodes.vue'), meta: { title: '运营·兑换码' } },
      { path: 'invitations', name: 'Invitations', component: () => import('@/views/Invitations.vue'), meta: { title: '运营·邀请与积分' } },
      { path: 'codes', name: 'RegistrationCodes', component: () => import('@/views/RegistrationCodes.vue'), meta: { title: '卡码管理' } },
      { path: 'devices', name: 'Devices', component: () => import('@/views/Devices.vue'), meta: { title: '设备风控' } },
      { path: 'login-logs', name: 'LoginLogs', component: () => import('@/views/LoginLogs.vue'), meta: { title: '登录与安全日志' } },
      { path: 'announcements', name: 'Announcements', component: () => import('@/views/Announcements.vue'), meta: { title: '公告管理' } },
      { path: 'tickets', name: 'Tickets', component: () => import('@/views/Tickets.vue'), meta: { title: '工单管理' } },
      { path: 'media-seek', name: 'MediaSeek', component: () => import('@/views/MediaSeek.vue'), meta: { title: '求片管理' } },
      { path: 'emby', name: 'EmbyAdmin', component: () => import('@/views/EmbyAdmin.vue'), meta: { title: '媒体库管理' } },
      { path: 'mounts', name: 'StorageMounts', component: () => import('@/views/StorageMounts.vue'), meta: { title: '存储挂载' } },
      { path: 'transfer-115', name: 'Transfer115', component: () => import('@/views/Transfer115.vue'), meta: { title: '115 转存' } },
      { path: 'settings', name: 'Settings', component: () => import('@/views/Settings.vue'), meta: { title: '系统设置' } },
      { path: 'logs', name: 'Logs', component: () => import('@/views/Logs.vue'), meta: { title: '操作日志' } },
      { path: 'health', name: 'SystemHealth', component: () => import('@/views/SystemHealth.vue'), meta: { title: '服务健康' } },
      { path: 'emby-servers', name: 'EmbyServers', component: () => import('@/views/EmbyServers.vue'), meta: { title: 'Emby 服务入口' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 门户免登：管理员在用户端已登录时，进后台直接接管该会话，不再要求二次登录。
  // 只在没有后台会话时探测一次（ssoFromPortal 内部做了幂等与失败短路）。
  if (!auth.isAuthenticated) {
    await auth.ssoFromPortal()
  }

  if (to.meta.requiresAuth !== false && !auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'Login' && auth.isAuthenticated) {
    return { path: '/' }
  }
  document.title = to.meta.title ? `${to.meta.title} · RoyalBot 管理后台` : 'RoyalBot 管理后台'
})

export default router
