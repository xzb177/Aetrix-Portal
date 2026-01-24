import axios from 'axios'

// 使用空 baseURL，让请求自动适配当前域名
const api = axios.create({
  baseURL: '',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器 - 添加 token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 处理错误
api.interceptors.response.use(
  (response) => {
    const res = response.data
    // 后端返回格式: { code: 200, message: "success", data: ... }
    if (res.code === 200) {
      return res.data
    }
    // 直接返回数据（兼容没有 code 字段的接口）
    if (!res.code) {
      return res
    }
    return res
  },
  (error) => {
    if (error.response?.status === 401) {
      // Token 过期或无效，清除登录信息
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
      // 不再跳转到 /login 页面，而是由 AuthSheet 处理
      // 页面上的路由守卫会触发 AuthSheet
      window.location.replace('/')
    }

    // 获取错误信息并显示友好提示
    let errorMessage = '请求失败'
    if (error.response?.data) {
      const data = error.response.data as any
      if (typeof data === 'string') {
        errorMessage = data
      } else if (data.detail) {
        errorMessage = data.detail
      } else if (data.message) {
        errorMessage = data.message
      }
    }

    // 可以在这里添加 toast 提示
    console.error('API Error:', errorMessage)

    return Promise.reject(error)
  }
)

export default api

// API 接口
export const authApi = {
  // 账号密码登录
  login: (data: { username: string; password: string }) =>
    api.post('/api/user/auth/login', data),

  // 注册
  register: (data: { username: string; password: string; email?: string; invitation_code?: string }) =>
    api.post('/api/user/auth/register', data),

  // Telegram OAuth 回调
  telegramCallback: (data: { query_string: string }) =>
    api.post('/api/user/auth/telegram-callback', data),

  // 获取当前用户信息
  getCurrentUser: () => api.get('/api/user/auth/me'),

  // 登出
  logout: () => api.post('/api/user/auth/logout'),

  // 修改密码
  changePassword: (data: { old_password: string; new_password: string }) =>
    api.post('/api/user/auth/change-password', null, { params: data }),
}

export const subscriptionApi = {
  // 获取订阅套餐列表
  getPlans: () => api.get('/api/user/subscriptions/plans'),

  // 获取用户当前订阅
  getMySubscription: () => api.get('/api/user/subscriptions/my'),
}

// 支付相关 API
export const paymentApi = {
  // 获取支持的支付方式
  getMethods: () => api.get('/api/user/payment/methods'),

  // 创建支付订单
  createPayment: (data: { plan_id: number; payment_method: string }) =>
    api.post('/api/user/payment/create', data),

  // 余额支付订阅
  balancePay: (data: { plan_id: number }) =>
    api.post('/api/user/payment/balance-pay', data),

  // 查询订单状态
  getStatus: (order_id: string) =>
    api.get(`/api/user/payment/status/${order_id}`),

  // 获取我的订单列表
  getMyOrders: (params?: { skip?: number; limit?: number }) =>
    api.get('/api/user/payment/my-orders', { params }),
}

export const requestApi = {
  // 提交求片请求
  submit: (data: { movie_name: string; year?: string; type?: string; note?: string; tmdb_id?: string; poster_url?: string }) =>
    api.post('/api/user/requests', data),

  // 获取我的求片列表
  getMyRequests: () => api.get('/api/user/requests/my'),

  // 获取求片详情
  getDetail: (id: number) => api.get(`/api/user/requests/${id}`),

  // 获取海报墙求片列表（公共池）
  getGallery: (params?: {
    status_filter?: string
    type_filter?: string
    sort_by?: string
    page?: number
    limit?: number
  }) => api.get('/api/user/requests/gallery', { params }),

  // TMDB 搜索
  searchTmdb: (query: string, media_type?: string) =>
    api.get('/api/user/requests/tmdb-search', { params: { query, media_type } }),

  // 订阅/投票求片
  subscribe: (id: number) => api.post(`/api/user/requests/${id}/subscribe`),

  // 获取统计
  getStats: () => api.get('/api/user/requests/stats'),

  // 获取我的求片限制
  getMyLimit: () => api.get('/api/user/requests/my/limit'),
}

export const rechargeApi = {
  // 获取充值套餐
  getPackages: () => api.get('/api/user/recharge/packages'),

  // 创建充值订单
  createOrder: (data: { package_id?: number; amount?: number; payment_method: string }) =>
    api.post('/api/user/recharge/order', data),

  // 获取充值记录
  getHistory: () => api.get('/api/user/recharge/history'),
}

export const announcementApi = {
  // 获取公告列表
  getAnnouncements: (params?: { skip?: number; limit?: number }) =>
    api.get('/api/user/announcements', { params }),
}

// 邀请相关 API
export const inviteApi = {
  // 获取我的邀请码
  getMyCode: () => api.get('/api/user/invitation/my-code'),

  // 生成新邀请码
  generateCode: (data?: { code?: string }) =>
    api.post('/api/user/invitation/generate', data),

  // 获取邀请统计
  getStats: () => api.get('/api/user/invitation/stats'),

  // 获取邀请记录
  getRecords: (params?: { skip?: number; limit?: number }) =>
    api.get('/api/user/invitation/records', { params }),

  // 使用邀请码
  applyCode: (code: string) =>
    api.post('/api/user/invitation/apply', { code }),
}

// 兑换码相关 API
export const exchangeCodeApi = {
  // 兑换兑换码
  redeem: (code: string) =>
    api.post('/api/user/exchange-code/redeem', { code }),

  // 获取我的兑换记录
  getMyRecords: (params?: { skip?: number; limit?: number }) =>
    api.get('/api/user/exchange-code/my-records', { params }),
}

export const userApi = {
  // 获取用户信息（复用 authApi 的端点）
  getProfile: () => api.get('/api/user/auth/me'),

  // 绑定 Emby 账号
  bindEmby: (data: { emby_account: string }) =>
    api.post('/api/user/bind-emby', data),

  // 获取统计数据
  getStats: () => api.get('/api/user/stats'),
}

// Emby 相关 API
export const embyApi = {
  // 获取 Emby 服务器列表
  getServers: () => api.get('/api/user/emby/servers'),

  // 获取我的 Emby 账号列表
  getAccounts: () => api.get('/api/user/emby/accounts'),

  // 重置 Emby 账号密码
  resetPassword: (accountId: number) =>
    api.post(`/api/user/emby/reset/${accountId}`),

  // 刷新 Emby 账号信息
  refreshAccount: (accountId: number) =>
    api.post(`/api/user/emby/refresh/${accountId}`),
}

// 站内消息 API - 前后台联动核心
export const messageApi = {
  // 获取站内消息列表
  getMessages: (params?: { unread_only?: boolean; limit?: number }) =>
    api.get('/api/user/messages', { params }),

  // 获取未读消息数
  getUnreadCount: () => api.get('/api/user/messages/unread-count'),

  // 标记消息为已读
  markAsRead: (messageId: number) =>
    api.post(`/api/user/messages/${messageId}/read`),

  // 标记所有消息为已读
  markAllRead: () =>
    api.post('/api/user/messages/read-all'),

  // 删除消息
  delete: (messageId: number) =>
    api.delete(`/api/user/messages/${messageId}`),
}

// 工单 API - 与后台工单系统联动
export const ticketApi = {
  // 获取我的工单列表
  getMyTickets: (params?: { status_filter?: string }) =>
    api.get('/api/user/tickets', { params }),

  // 创建工单
  create: (data: { title: string; category?: string; message: string }) =>
    api.post('/api/user/tickets', data),

  // 获取工单详情
  getDetail: (ticketId: number) =>
    api.get(`/api/user/tickets/${ticketId}`),

  // 获取工单消息
  getMessages: (ticketId: number) =>
    api.get(`/api/user/tickets/${ticketId}/messages`),

  // 回复工单
  reply: (ticketId: number, data: { message: string }) =>
    api.post(`/api/user/tickets/${ticketId}/messages`, data),

  // 关闭工单
  close: (ticketId: number) =>
    api.post(`/api/user/tickets/${ticketId}/close`),
}

// 求片 API - 与后台求片管理联动
export const mediaSeekApi = {
  // 获取我的求片列表
  getMyRequests: () =>
    api.get('/api/user/media-seek'),

  // 创建求片请求
  create: (data: { movie_name: string; year?: string; type?: string; note?: string }) =>
    api.post('/api/user/media-seek', data),
}

// 活动记录 API
export const activityApi = {
  // 获取用户活动时间线
  getTimeline: () => api.get('/api/user/timeline'),
}

// 线路配置 API - 路由选择引擎
export interface RouteInfo {
  id: number
  name: string
  description?: string
  priority: number
  domain: string
  tls: boolean
  base_path: string
  tags: string[]
  region_scope: string[]
  worker_route?: string
  origin_type: string
}

export const routesApi = {
  // 获取可用线路列表
  getRoutes: (params?: { region?: string }) =>
    api.get('/api/routes/', { params }),

  // 获取当前激活线路
  getActiveRoute: (params?: { region?: string }) =>
    api.get('/api/routes/active', { params }),

  // 获取调试信息
  getDebugInfo: () =>
    api.get('/api/routes/debug'),
}

// 徽章系统 API（彩蛋功能）
export const badgesApi = {
  // 获取用户徽章列表
  getBadges: () => api.get('/api/user/badges'),

  // 获取身份卡数据
  getIdentityCard: () => api.get('/api/user/badges/identity-card'),

  // 检查徽章解锁（测试用）
  checkBadges: () => api.post('/api/user/badges/check'),
}
