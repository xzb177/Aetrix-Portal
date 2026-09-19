import axios from 'axios'

// 使用空 baseURL，让请求自动适配当前域名（前后端同源部署）
const api = axios.create({
  baseURL: '',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ==================== Token 存取 ====================

export const tokenStore = {
  get access() {
    return localStorage.getItem('access_token')
  },
  get refresh() {
    return localStorage.getItem('refresh_token')
  },
  set(access: string, refresh?: string) {
    localStorage.setItem('access_token', access)
    if (refresh) localStorage.setItem('refresh_token', refresh)
  },
  clear() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
  },
}

// ==================== 请求拦截器 ====================

api.interceptors.request.use(
  (config) => {
    const token = tokenStore.access
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// ==================== 401 自动刷新（refresh token 轮换） ====================

let isRefreshing = false
let refreshSubscribers: Array<(token: string) => void> = []

function subscribeTokenRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb)
}

function onRefreshed(newToken: string) {
  refreshSubscribers.forEach((cb) => cb(newToken))
  refreshSubscribers = []
}

function forceLogout() {
  tokenStore.clear()
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}

api.interceptors.response.use(
  (response) => {
    const res = response.data
    // 后端统一返回 JSON；兼容 { code: 200, data } 包装与裸数据
    if (res && typeof res === 'object' && 'code' in res && res.code === 200 && 'data' in res) {
      return res.data
    }
    return res
  },
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      const isAuthRequest =
        originalRequest?.url?.includes('/api/user/auth/login') ||
        originalRequest?.url?.includes('/api/user/auth/register') ||
        originalRequest?.url?.includes('/api/user/auth/refresh')

      if (isAuthRequest) {
        return Promise.reject(error)
      }

      const refreshToken = tokenStore.refresh
      if (!refreshToken) {
        forceLogout()
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve) => {
          subscribeTokenRefresh((newToken: string) => {
            originalRequest.headers.Authorization = `Bearer ${newToken}`
            resolve(api(originalRequest))
          })
        })
      }

      isRefreshing = true
      originalRequest._retry = true

      try {
        const res = await axios.post('/api/user/auth/refresh', { refresh_token: refreshToken })
        const data = res.data
        tokenStore.set(data.access_token, data.refresh_token)
        onRefreshed(data.access_token)
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`
        return api(originalRequest)
      } catch (refreshError) {
        forceLogout()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

export default api

// ==================== 认证 API（backend/api/emby_portal.py） ====================

export interface AuthUser {
  id: number
  username: string
  email?: string | null
  emby_username?: string | null
  is_vip: boolean
  is_active: boolean
  created_at?: string | null
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

export const authApi = {
  login: (data: { username: string; password: string }) =>
    api.post<never, AuthResponse>('/api/user/auth/login', data),

  register: (data: { username: string; password: string; email?: string }) =>
    api.post<never, AuthResponse>('/api/user/auth/register', data),

  getCurrentUser: () => api.get<never, AuthUser>('/api/user/auth/me'),

  logout: () => api.post('/api/user/auth/logout'),

  changePassword: (data: { old_password: string; new_password: string }) =>
    api.post('/api/user/auth/change-password', data),
}

// ==================== 自建 Emby 门户 API（backend/emby_server/portal.py） ====================

export interface AccountCard {
  server_id: string
  server_name: string
  base_url: string
  emby_username: string
  emby_password: null
  has_password: boolean
  import_schemes: Record<string, string>
}

export interface PortalMediaItem {
  id: string
  name: string
  type: string
  year?: number | null
  rating?: number | null
  position_ticks?: number
  duration_ticks?: number
  progress?: number
  poster_url?: string | null
}

export const embyApi = {
  // 账号卡（服务器地址 / Emby 用户名 / 播放器一键导入 scheme）
  getAccountCard: () => api.get<never, AccountCard>('/api/user/emby/server'),

  // 设置/修改 Emby 播放密码
  setPassword: (password: string) => api.post('/api/user/emby/password', { password }),

  // 续看列表
  getResume: (limit = 12) => api.get<never, { items: PortalMediaItem[] }>('/api/user/emby/resume', { params: { limit } }),

  // 收藏列表
  getFavorites: () => api.get<never, { items: PortalMediaItem[] }>('/api/user/emby/favorites'),

  // 收藏/取消收藏
  toggleFavorite: (itemId: string) => api.post<never, { is_favorite: boolean }>(`/api/user/emby/favorites/${itemId}`),

  // 观看统计
  getStats: () => api.get<never, {
    total_plays: number
    watched_items: number
    total_seconds: number
    recent: Array<{ item: string; type: string; device?: string; client?: string; at?: string | null }>
  }>('/api/user/emby/stats'),
}

// ==================== 站内消息 API（backend/api/user.py + admin 联动） ====================

export interface StationMessage {
  id: number
  title: string
  content: string
  message_type: string
  related_id?: number | null
  is_read: boolean
  created_at: string
  from_user?: string | null
}

export const messageApi = {
  getMessages: (params?: { unread_only?: boolean; limit?: number }) =>
    api.get<never, StationMessage[]>('/api/user/messages', { params }),

  getUnreadCount: () => api.get<never, { unread_count: number }>('/api/user/messages/unread-count'),

  markAsRead: (messageId: number) => api.post(`/api/user/messages/${messageId}/read`),

  markAllRead: () => api.post('/api/user/messages/read-all'),
}

// ==================== 公告 API ====================

export interface Announcement {
  id: number
  title: string
  content: string
  type: string
  is_pinned: boolean
  created_at: string
}

export const announcementApi = {
  getAnnouncements: () => api.get<never, Announcement[]>('/api/user/announcements'),
}

// ==================== 工单 API ====================

export interface Ticket {
  id: number
  title: string
  category: string
  status: string
  priority: string
  created_at: string
  updated_at: string
}

export interface TicketMessage {
  id: number
  message: string
  is_admin: boolean
  created_at: string
  admin_name?: string | null
}

export const ticketApi = {
  getMyTickets: (params?: { status_filter?: string }) =>
    api.get<never, Ticket[]>('/api/user/tickets', { params }),

  create: (data: { title: string; category?: string; message: string }) =>
    api.post<never, { success: boolean; ticket_id: number; message: string }>('/api/user/tickets', data),

  getMessages: (ticketId: number) => api.get<never, TicketMessage[]>(`/api/user/tickets/${ticketId}/messages`),

  reply: (ticketId: number, message: string) =>
    api.post(`/api/user/tickets/${ticketId}/messages`, { title: 'reply', message, category: 'other' }),

  close: (ticketId: number) => api.post(`/api/user/tickets/${ticketId}/close`),
}

// ==================== 求片 API ====================

export interface MediaSeekRequest {
  id: number
  movie_name: string
  year?: string | null
  type?: string | null
  note?: string | null
  status: string
  admin_note?: string | null
  created_at: string
}

export const mediaSeekApi = {
  getMyRequests: () => api.get<never, MediaSeekRequest[]>('/api/user/media-seek'),

  create: (data: { movie_name: string; year?: string; type?: string; note?: string }) =>
    api.post('/api/user/media-seek', data),
}
