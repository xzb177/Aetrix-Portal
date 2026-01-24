import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useAuthSheet } from '@/composables/useAuthSheet'

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
      path: '/m/login',
      name: 'mobile-login',
      component: () => import('@/views/MobileLoginView.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/m/register',
      name: 'register',
      component: () => import('@/views/MobileRegisterView.vue'),
      meta: { title: '注册' },
    },
    {
      path: '/auth/telegram/callback',
      name: 'telegram-callback',
      component: () => import('@/views/TelegramCallback.vue'),
      meta: { title: 'Telegram 登录' },
    },
    {
      path: '/telegram-auth-success',
      name: 'telegram-auth-success',
      component: () => import('@/views/TelegramAuthSuccess.vue'),
      meta: { title: '登录成功' },
    },
    {
      path: '/subscription',
      name: 'subscription',
      component: () => import('@/views/SubscriptionView.vue'),
      meta: { title: '订阅套餐', requiresAuth: true },
    },
    {
      path: '/request',
      name: 'request',
      component: () => import('@/views/RequestView.vue'),
      meta: { title: '求片中心', requiresAuth: true },
    },
    {
      path: '/recharge',
      name: 'recharge',
      component: () => import('@/views/RechargeView.vue'),
      meta: { title: '充值中心', requiresAuth: true },
    },
    {
      path: '/recharge/success',
      name: 'recharge-success',
      component: () => import('@/views/RechargeSuccessView.vue'),
      meta: { title: '充值成功', requiresAuth: true },
    },
    {
      path: '/recharge/fail',
      name: 'recharge-fail',
      component: () => import('@/views/RechargeFailView.vue'),
      meta: { title: '充值失败', requiresAuth: true },
    },
    {
      path: '/payment/return',
      name: 'payment-return',
      component: () => import('@/views/PaymentReturnView.vue'),
      meta: { title: '支付返回' },
    },
    {
      path: '/profile',
      name: 'profile',
      component: () => import('@/views/ProfileView.vue'),
      meta: { title: '个人中心', requiresAuth: true },
    },
    {
      path: '/checkin',
      name: 'checkin',
      component: () => import('@/views/CheckInView.vue'),
      meta: { title: '每日签到', requiresAuth: true },
    },
    {
      path: '/invite',
      name: 'invite',
      component: () => import('@/views/InviteView.vue'),
      meta: { title: '邀请好友', requiresAuth: true },
    },
    {
      path: '/exchange-code',
      name: 'exchange-code',
      component: () => import('@/views/ExchangeCodeView.vue'),
      meta: { title: '兑换码', requiresAuth: true },
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
      path: '/order/:id',
      name: 'order-detail',
      component: () => import('@/views/OrderDetailView.vue'),
      meta: { title: '订单详情', requiresAuth: true },
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

router.beforeEach((to, from, next) => {
  const userStore = useUserStore()
  const { openAuthSheet } = useAuthSheet()

  // 只在首次访问时初始化用户状态
  if (!initialized) {
    userStore.init()
    initialized = true
  }

  // 设置页面标题
  if (to.meta.title) {
    document.title = `${to.meta.title} - Aetrix`
  }

  // 需要登录的页面
  if (to.meta.requiresAuth) {
    if (!userStore.isLoggedIn) {
      // 未登录，重定向到首页并弹出登录窗口
      next({ name: 'home', query: { auth: 'required', redirect: to.fullPath } })
      setTimeout(() => openAuthSheet(), 0)
      return
    }

    // 有 token 但没有用户信息，尝试获取用户信息
    if (!userStore.user) {
      userStore.fetchUser().then(() => {
        next()
      }).catch(() => {
        // 获取用户信息失败，清除状态并重定向到首页
        userStore.logout()
        next({ name: 'home', query: { auth: 'required', redirect: to.fullPath } })
        setTimeout(() => openAuthSheet(), 0)
      })
      return
    }
  }

  next()
})

export default router
