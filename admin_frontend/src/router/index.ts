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
      { path: 'codes', name: 'RegistrationCodes', component: () => import('@/views/RegistrationCodes.vue'), meta: { title: '注册码' } },
      { path: 'announcements', name: 'Announcements', component: () => import('@/views/Announcements.vue'), meta: { title: '公告管理' } },
      { path: 'tickets', name: 'Tickets', component: () => import('@/views/Tickets.vue'), meta: { title: '工单管理' } },
      { path: 'media-seek', name: 'MediaSeek', component: () => import('@/views/MediaSeek.vue'), meta: { title: '求片管理' } },
      { path: 'emby', name: 'EmbyAdmin', component: () => import('@/views/EmbyAdmin.vue'), meta: { title: '媒体库管理' } },
      { path: 'logs', name: 'Logs', component: () => import('@/views/Logs.vue'), meta: { title: '操作日志' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth !== false && !auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'Login' && auth.isAuthenticated) {
    return { path: '/' }
  }
  document.title = to.meta.title ? `${to.meta.title} · RoyalBot 管理后台` : 'RoyalBot 管理后台'
})

export default router
