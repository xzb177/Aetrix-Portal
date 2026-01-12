import { http } from '@/utils/request'

// ==================== 类型定义 ====================

export interface PortalUser {
  id: number
  username: string
  email?: string
  telegram_id?: string
  is_active: boolean
  is_staff: boolean
  is_vip: boolean
  current_plan?: string
  vip_expires_at?: string
  emby_account_count?: number
  created_at: string
  last_login?: string
}

// ==================== 门户用户管理 ====================

// 获取门户用户列表
export const getPortalUsers = (params: {
  search?: string
  is_vip_only?: boolean
  is_active?: boolean
  skip?: number
  limit?: number
}) => {
  return http.get<PortalUser[]>('/portal/users', { params })
}

// 获取门户用户详情
export const getPortalUserDetail = (userId: number) => {
  return http.get(`/portal/users/${userId}`)
}

// 更新用户状态
export const updatePortalUserStatus = (userId: number, data: {
  is_active?: boolean
  is_staff?: boolean
}) => {
  return http.put(`/portal/users/${userId}/status`, data)
}

// 删除门户用户
export const deletePortalUser = (userId: number) => {
  return http.delete(`/portal/users/${userId}`)
}

// ==================== 订阅套餐管理 ====================

// 获取订阅套餐列表
export const getSubscriptionPlans = () => {
  return http.get('/subscriptions/plans')
}

// 创建订阅套餐
export const createSubscriptionPlan = (data: {
  name: string
  description: string
  price: number
  duration_days: number
  features: string[]
  is_active?: boolean
  is_popular?: boolean
  sort_order?: number
}) => {
  return http.post('/subscriptions/plans', data)
}

// 更新订阅套餐
export const updateSubscriptionPlan = (planId: number, data: {
  name?: string
  description?: string
  price?: number
  duration_days?: number
  features?: string[]
  is_active?: boolean
  is_popular?: boolean
  sort_order?: number
}) => {
  return http.put(`/subscriptions/plans/${planId}`, data)
}

// 删除订阅套餐
export const deleteSubscriptionPlan = (planId: number) => {
  return http.delete(`/subscriptions/plans/${planId}`)
}

// 获取订阅订单列表
export const getSubscriptionOrders = (params: {
  status_filter?: string
  skip?: number
  limit?: number
}) => {
  return http.get('/subscriptions/orders', { params })
}

// 获取用户订阅列表
export const getSubscriptions = (params: {
  status_filter?: string
  skip?: number
  limit?: number
}) => {
  return http.get('/subscriptions/list', { params })
}

// ==================== Emby 服务器管理 ====================

// 获取 Emby 服务器列表
export const getEmbyServers = () => {
  return http.get('/emby-servers/servers')
}

// 创建 Emby 服务器
export const createEmbyServer = (data: {
  name: string
  url: string
  api_key: string
  max_users?: number
  is_active?: boolean
}) => {
  return http.post('/emby-servers/servers', data)
}

// 更新 Emby 服务器
export const updateEmbyServer = (serverId: number, data: {
  name?: string
  url?: string
  api_key?: string
  max_users?: number
  is_active?: boolean
}) => {
  return http.put(`/emby-servers/servers/${serverId}`, data)
}

// 删除 Emby 服务器
export const deleteEmbyServer = (serverId: number) => {
  return http.delete(`/emby-servers/servers/${serverId}`)
}

// 同步 Emby 服务器用户数
export const syncEmbyServer = (serverId: number) => {
  return http.post(`/emby-servers/servers/${serverId}/sync`)
}

// 测试 Emby 服务器连接
export const testEmbyServer = (data: { url: string; api_key: string }) => {
  return http.post('/emby-servers/servers/test', data)
}

// 获取服务器用户列表
export const getEmbyServerUsers = (serverId: number) => {
  return http.get(`/emby-servers/servers/${serverId}/users`)
}

// 获取套餐关联的服务器
export const getPlanServers = (planId: number) => {
  return http.get(`/emby-servers/plans/${planId}/servers`)
}

// 添加服务器到套餐
export const addServerToPlan = (planId: number, data: {
  server_id: number
  weight?: number
}) => {
  return http.post(`/emby-servers/plans/${planId}/servers`, data)
}

// 更新套餐服务器权重
export const updatePlanServer = (relationId: number, data: {
  weight?: number
}) => {
  return http.put(`/emby-servers/plans/servers/${relationId}`, data)
}

// 移除套餐服务器关联
export const removeServerFromPlan = (relationId: number) => {
  return http.delete(`/emby-servers/plans/servers/${relationId}`)
}

// ==================== 公告管理 ====================

// 获取公告列表
export const getAnnouncements = () => {
  return http.get('/announcements')
}

// 创建公告
export const createAnnouncement = (data: {
  title: string
  content: string
  type?: string
  is_active?: boolean
}) => {
  return http.post('/announcements', data)
}

// 更新公告
export const updateAnnouncement = (announcementId: number, data: {
  title?: string
  content?: string
  type?: string
  is_active?: boolean
}) => {
  return http.put(`/announcements/${announcementId}`, data)
}

// 删除公告
export const deleteAnnouncement = (announcementId: number) => {
  return http.delete(`/announcements/${announcementId}`)
}

// ==================== 工单管理 ====================

// 获取工单列表
export const getTickets = (params: {
  status_filter?: string
  category_filter?: string
  priority_filter?: string
  skip?: number
  limit?: number
}) => {
  return http.get('/tickets', { params })
}

// 获取工单详情
export const getTicketDetail = (ticketId: number) => {
  return http.get(`/tickets/${ticketId}`)
}

// 回复工单
export const replyTicket = (ticketId: number, data: {
  message: string
}) => {
  return http.post(`/tickets/${ticketId}/messages`, data)
}

// 更新工单状态
export const updateTicketStatus = (ticketId: number, data: {
  status: string
}) => {
  return http.put(`/tickets/${ticketId}/status`, data)
}

// ==================== 邀请管理 ====================

// 获取邀请码列表
export const getInvitationCodes = (params?: {
  skip?: number
  limit?: number
}) => {
  return http.get('/invitations/codes', { params })
}

// 获取邀请记录
export const getInvitationRecords = (params?: {
  skip?: number
  limit?: number
}) => {
  return http.get('/invitations/records', { params })
}

// 获取邀请配置
export const getInvitationConfig = () => {
  return http.get('/invitations/config')
}

// 更新邀请配置
export const updateInvitationConfig = (data: {
  invitation_enabled?: boolean
  invitation_reward_points?: number
  invitation_invitee_reward_points?: number
}) => {
  return http.put('/invitations/config', data)
}

// 获取邀请统计
export const getInvitationStats = () => {
  return http.get('/invitations/stats')
}

// ==================== 兑换码管理 ====================

// 获取兑换码列表
export const getExchangeCodes = (params?: {
  skip?: number
  limit?: number
  status?: number
  type?: number
  search?: string
}) => {
  return http.get('/exchange-codes', { params })
}

// 获取兑换码详情
export const getExchangeCodeDetail = (codeId: number) => {
  return http.get(`/exchange-codes/${codeId}`)
}

// 创建兑换码（单个）
export const createExchangeCode = (data: {
  code?: string
  type: number
  exchange_count: number
  note?: string
}) => {
  return http.post('/exchange-codes', data)
}

// 批量创建兑换码
export const batchCreateExchangeCodes = (data: {
  count: number
  type: number
  exchange_count: number
  note?: string
}) => {
  return http.post('/exchange-codes/batch', data)
}

// 更新兑换码状态
export const updateExchangeCodeStatus = (codeId: number, data: {
  status: number
}) => {
  return http.put(`/exchange-codes/${codeId}/status`, data)
}

// 删除兑换码
export const deleteExchangeCode = (codeId: number) => {
  return http.delete(`/exchange-codes/${codeId}`)
}

// 获取兑换码统计
export const getExchangeCodeStats = () => {
  return http.get('/exchange-codes/stats/overview')
}

// ==================== 统计分析 ====================

// 获取门户用户统计
export const getPortalUserStats = () => {
  return http.get('/portal/users/stats')
}

// 获取工单统计
export const getTicketStats = () => {
  return http.get('/tickets/stats')
}

// 获取支付统计数据
export const getPaymentStats = () => {
  return http.get('/payment/stats')
}

// 获取系统统计数据
export const getSystemStats = () => {
  return http.get('/stats/system')
}

// 获取管理员操作日志（最近活动）
export const getAdminLogs = (params?: {
  limit?: number
}) => {
  return http.get('/stats/logs', { params })
}

// ==================== Emby 媒体 ====================

// 获取最近播放的媒体
export const getRecentPlays = (limit: number = 10) => {
  return http.get('/emby/recent-plays', { params: { limit } })
}

// 获取活动动态
export const getActivityFeed = (limit: number = 20) => {
  return http.get('/emby/activity-feed', { params: { limit } })
}

// ==================== 求片管理 ====================

// 获取求片列表
export const getMediaRequests = (params: {
  status_filter?: string
  type_filter?: string
  search?: string
  skip?: number
  limit?: number
}) => {
  return http.get('/media-requests', { params })
}

// 获取求片统计
export const getMediaRequestStats = () => {
  return http.get('/media-requests/stats')
}

// 获取求片详情
export const getMediaRequestDetail = (requestId: number) => {
  return http.get(`/media-requests/${requestId}`)
}

// 更新求片信息
export const updateMediaRequest = (requestId: number, data: {
  movie_name?: string
  year?: string
  type?: string
  note?: string
}) => {
  return http.put(`/media-requests/${requestId}`, data)
}

// 更新求片状态
export const updateMediaRequestStatus = (requestId: number, data: {
  status: string
  admin_note?: string
  status_remark?: string
  emby_item_id?: string
  poster_url?: string
  tmdb_id?: string
}) => {
  return http.put(`/media-requests/${requestId}/status`, data)
}

// 删除求片
export const deleteMediaRequest = (requestId: number) => {
  return http.delete(`/media-requests/${requestId}`)
}

// 获取求片订阅用户
export const getRequestSubscribers = (requestId: number) => {
  return http.get(`/media-requests/${requestId}/subscribers`)
}

// ==================== MoviePilot 下载管理 ====================

// 测试 MoviePilot 连接
export const testMoviePilotConnection = (data: {
  url: string
  api_token: string
}) => {
  return http.post('/downloads/test', data)
}

// 添加订阅
export const addSubscribe = (data: {
  moviepilot: {
    url: string
    api_token: string
  }
  name: string
  year?: string
  type?: string
  tmdb_id?: string
  season?: number
  note?: string
}) => {
  return http.post('/downloads/subscribe', data)
}

// 获取订阅列表
export const getSubscribes = (params?: {
  url?: string
  api_token?: string
}) => {
  return http.get('/downloads/subscribes', { params })
}

// 获取 MoviePilot 配置
export const getMoviePilotConfig = () => {
  return http.get('/downloads/config')
}

// ==================== 系统配置管理 ====================

// 获取配置列表
export const getSettings = (params?: { category?: string }) => {
  return http.get('/settings/', { params })
}

// 获取配置分类
export const getSettingCategories = () => {
  return http.get('/settings/categories')
}

// 更新单个配置
export const updateSetting = (key: string, value: string) => {
  return http.post('/settings/update', { key, value })
}

// 批量更新配置
export const batchUpdateSettings = (items: Array<{ key: string; value: string }>) => {
  return http.post('/settings/batch-update', items)
}

// 重置配置
export const resetSetting = (key: string) => {
  return http.post('/settings/reset', null, { params: { key } })
}

// 导出配置
export const exportSettings = () => {
  return http.get('/settings/export')
}

// 导入配置
export const importSettings = (items: Array<{ key: string; value: string; description?: string }>) => {
  return http.post('/settings/import', { items })
}
