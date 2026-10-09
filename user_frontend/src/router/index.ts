import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
// 标题里的站名来自「站点与品牌」能力（未配置时用默认值）
import { pageTitle } from '@/composables/useBranding'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { title: '首页' },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/profile',
      name: 'profile',
      component: () => import('@/views/ProfileView.vue'),
      meta: { title: '个人中心', requiresAuth: true },
    },
    {
      path: '/messages',
      name: 'messages',
      component: () => import('@/views/MessagesView.vue'),
      meta: { title: '消息中心', requiresAuth: true },
    },
    {
      path: '/tickets',
      name: 'tickets',
      component: () => import('@/views/TicketsView.vue'),
      meta: { title: '工单中心', requiresAuth: true },
    },
    {
      path: '/request',
      name: 'request',
      component: () => import('@/views/RequestView.vue'),
      meta: { title: '求片中心', requiresAuth: true },
    },
    // AI 助手（v2.19.0）：能力「AI 模型设置」的用户侧消费点；
    // 管理员没配置时页面会说明原因，不会出现「能点但报错」的入口
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('@/views/AssistantView.vue'),
      meta: { title: 'AI 助手', requiresAuth: true },
    },
    // ==================== 经济系统（v2.3.0） ====================
    {
      path: '/wallet',
      name: 'wallet',
      component: () => import('@/views/WalletView.vue'),
      meta: { title: '商店', requiresAuth: true },
    },
    {
      path: '/checkin',
      name: 'checkin',
      component: () => import('@/views/CheckinView.vue'),
      meta: { title: '每日签到', requiresAuth: true },
    },
    {
      path: '/invite',
      name: 'invite',
      component: () => import('@/views/InviteView.vue'),
      meta: { title: '邀请返利', requiresAuth: true },
    },
    {
      path: '/lottery',
      name: 'lottery',
      component: () => import('@/views/LotteryView.vue'),
      meta: { title: '幸运抽奖', requiresAuth: true },
    },
    // 追新日历：站内唯一一个「按时间看片」的页面（媒体浏览在第三方客户端，
    // 门户只保留“最近入库”这一个内容型入口）
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('@/views/CalendarView.vue'),
      meta: { title: '追新日历', requiresAuth: true },
    },
    // ==================== 媒体详情与播放（v2.42.5：媒体库/搜索浏览页已删） ====================
    // 老地址 /media、/library、/search、/favorites、/history 的书签与外部链接：
    // 媒体浏览统一走第三方客户端（Infuse 等），这些入口不再有对应页面，
    // 全部落到兜底 404 页（页面里会给「回首页」的出口）。
    {
      path: '/media/:id',
      name: 'media-detail',
      component: () => import('@/views/media/ItemDetailView.vue'),
      meta: { title: '详情', requiresAuth: true },
    },
    {
      path: '/watch/:id',
      name: 'watch',
      component: () => import('@/views/media/WatchView.vue'),
      meta: { title: '播放', requiresAuth: true },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: '页面未找到' },
    },
  ],
})

// 路由守卫
let initialized = false

router.beforeEach(async (to) => {
  const userStore = useUserStore()

  if (!initialized) {
    userStore.init()
    initialized = true
  }

  // 分段页标题由 LibraryHomeView 按 ?tab= 覆写（媒体库 / 收藏 / 观看记录）
  if (to.meta.title) {
    document.title = pageTitle(to.meta.title as string | undefined)
  }

  // 未登录访问受保护页面 → 跳转登录页并记录回跳地址
  if (to.meta.requiresAuth) {
    const hasToken = localStorage.getItem('access_token')
    if (!hasToken && !userStore.isLoggedIn) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    // 有 token 但没有用户信息（刷新页面），拉取一次
    if (!userStore.user) {
      try {
        await userStore.fetchUser()
      } catch {
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }
  }

  // 已登录访问登录页 → 回首页
  if (to.name === 'login' && userStore.isLoggedIn) {
    return { name: 'home' }
  }

  return true
})

export default router
