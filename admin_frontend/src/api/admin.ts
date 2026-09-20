/** v2.2.0 管理端 API（全部走 /api/admin/*，详见 backend/api/admin.py 与 emby_server/portal.py） */
import { get, post, put, patch, del } from '@/utils/request'
import type {
  AdminInfo,
  AdminLogRow,
  Announcement,
  CodeStats,
  DeviceRow,
  DeviceStats,
  LoginLogsResponse,
  EmbyLibrary,
  EmbySessionRow,
  LoginResponse,
  MediaSeekRow,
  OverviewStats,
  PlaybackStats,
  RegistrationCode,
  RegistrationSettings,
  TicketMessageRow,
  TicketRow,
  TrendStats,
  UserDetail,
  UsersResponse,
} from '@/types'

// ==================== 认证 ====================

export const login = (data: { username: string; password: string }) =>
  post<LoginResponse>('/auth/login', data)

export const fetchMe = () => get<AdminInfo>('/auth/me')

export const changePassword = (data: { old_password: string; new_password: string }) =>
  post<{ success: boolean }>('/auth/change-password', data)

// ==================== 用户管理 ====================

export const fetchUsers = (params: { search?: string; active?: boolean; limit?: number; offset?: number }) =>
  get<UsersResponse>('/users', params)

/** 用户 360° 详情：资料 / 订阅 / 积分 / 订单 / 邀请 / 签到 / 观看 */
export const fetchUserDetail = (id: number) => get<UserDetail>(`/users/${id}`)

/** 趋势统计（近 N 天，按日补零） */
export const fetchStatsTrend = (days = 14) => get<TrendStats>('/stats/trend', { days })

export interface PlanRow {
  id: number
  name: string
  description: string | null
  price: number
  duration_days: number
  is_popular: boolean
}

export const fetchPlans = () => get<{ plans: PlanRow[] }>('/plans')

export const grantSubscription = (userId: number, data: { plan_id: number; duration_days: number }) =>
  post<{ success: boolean }>(`/users/${userId}/subscriptions`, data)

export const extendSubscription = (subscriptionId: number, days: number) =>
  post<{ success: boolean }>(`/subscriptions/${subscriptionId}/extend`, { days })

export const updateUser = (id: number, data: { is_active?: boolean; is_staff?: boolean }) =>
  put<{ success: boolean }>(`/users/${id}`, data)

export const resetUserPassword = (id: number, new_password: string) =>
  post<{ success: boolean }>(`/users/${id}/reset-password`, { new_password })

export const sendUserMessage = (id: number, data: { title: string; content: string }) =>
  post<{ success: boolean }>(`/users/${id}/messages`, data)

export const broadcastMessage = (data: { title: string; content: string }) =>
  post<{ success: boolean }>('/messages/broadcast', data)

// ==================== 卡码体系 ====================

export const fetchRegistrationCodes = () =>
  get<{ codes: RegistrationCode[] }>('/registration-codes')

export const createRegistrationCodes = (data: {
  count: number
  max_uses: number
  expires_days: number
  note?: string
}) => post<{ codes: { code: string }[] }>('/registration-codes', data)

export const updateRegistrationCode = (id: number, is_active: boolean) =>
  put<{ success: boolean }>(`/registration-codes/${id}`, { is_active })

export const fetchRegistrationSettings = () => get<RegistrationSettings>('/settings/registration')

export const updateRegistrationSettings = (data: { mode: string; message?: string }) =>
  put<{ success: boolean }>('/settings/registration', data)

/** 类型化卡码生成（注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码） */
export const generateCodes = (data: {
  code_type: number
  count: number
  days?: number | null
  max_uses: number
  expires_days: number
  algorithm?: string
  is_decoy?: boolean
  target_username?: string
  note?: string
}) => post<{ success: boolean; message: string; codes: { id: number; code: string; days_text: string; expires_at: string }[] }>(
  '/registration-codes/generate', data)

export const fetchCodeList = (params: {
  code_type?: number
  state?: string
  keyword?: string
  limit?: number
  offset?: number
} = {}) => get<{ total: number; codes: RegistrationCode[] }>('/registration-codes/list', params)

export const fetchCodeStats = () => get<CodeStats>('/registration-codes/stats')

export const patchRegistrationCode = (id: number, data: { is_active?: boolean; note?: string }) =>
  patch<{ success: boolean; code: RegistrationCode }>(`/registration-codes/${id}`, data)

export const deleteRegistrationCode = (id: number) =>
  del<{ success: boolean; message: string }>(`/registration-codes/${id}`)

// ==================== 设备风控 ====================

export const fetchDevices = (params: {
  user_id?: number
  keyword?: string
  only_blocked?: boolean
  limit?: number
  offset?: number
} = {}) => get<{ total: number; devices: DeviceRow[] }>('/devices', params)

export const fetchDeviceStats = () => get<DeviceStats>('/devices/stats')

export const setDeviceBlocked = (userId: number, deviceId: string, isBlocked: boolean) =>
  put<{ success: boolean; message: string }>(
    `/devices/${encodeURIComponent(deviceId)}`, { is_blocked: isBlocked }, { user_id: userId })

export const removeDevice = (userId: number, deviceId: string) =>
  del<{ success: boolean; message: string }>(
    `/devices/${encodeURIComponent(deviceId)}`, { user_id: userId })

// ==================== 登录 / 安全日志 ====================

export const fetchLoginLogs = (params: {
  username?: string
  ip?: string
  reason?: string
  success?: boolean
  limit?: number
  offset?: number
} = {}) => get<LoginLogsResponse>('/login-logs', params)

export const purgeLoginLogs = (days: number) =>
  post<{ success: boolean; message: string; deleted: number }>('/login-logs/purge', { days })

// ==================== 公告 ====================

export const fetchAnnouncements = (params: { active_only?: boolean } = {}) =>
  get<Announcement[]>('/announcements', params)

export const createAnnouncement = (data: { title: string; content: string; type?: string; is_pinned?: boolean }) =>
  post<{ success: boolean }>('/announcements', data)

export const updateAnnouncement = (id: number, data: Partial<{ title: string; content: string; type: string; is_pinned: boolean; is_active: boolean }>) =>
  put<{ success: boolean }>(`/announcements/${id}`, data)

export const deleteAnnouncement = (id: number) => del<{ success: boolean }>(`/announcements/${id}`)

// ==================== 工单 ====================

export const fetchTickets = (params: { status_filter?: string } = {}) =>
  get<TicketRow[]>('/tickets', params)

/** 工单状态 / 优先级调整 */
export const updateTicket = (id: number, data: { status?: string; priority?: string; category?: string }) =>
  put<{ success: boolean }>(`/tickets/${id}`, data)

export const fetchTicketMessages = (id: number) => get<TicketMessageRow[]>(`/tickets/${id}/messages`)

export const replyTicket = (id: number, data: { message: string; close_ticket?: boolean }) =>
  post<{ success: boolean }>(`/tickets/${id}/reply`, data)

export const closeTicket = (id: number) => post<{ success: boolean }>(`/tickets/${id}/close`)

// ==================== 求片 ====================

export const fetchMediaSeeks = (params: { status_filter?: string } = {}) =>
  get<MediaSeekRow[]>('/media-seek', params)

export const updateMediaSeek = (id: number, data: { status: string; admin_note?: string }) =>
  put<{ success: boolean }>(`/media-seek/${id}`, data)

// ==================== 日志与统计 ====================

export const fetchLogs = (params: { limit?: number; action_filter?: string } = {}) =>
  get<AdminLogRow[]>('/logs', params)

export const fetchOverview = () => get<OverviewStats>('/stats/overview')

export const fetchPlaybackStats = () => get<PlaybackStats>('/stats/playback')

// ==================== 自建 Emby 管理（/api/admin/emby/*） ====================

const E = '/emby'

export const fetchEmbyOverview = () => get<{ total_items: number; total_libraries: number; active_sessions: number; total_users: number }>(`${E}/overview`)

export const fetchLibraries = () => get<{ libraries: EmbyLibrary[] }>(`${E}/libraries`)

export const createLibrary = (data: { name: string; collection_type: string; paths: string[] }) =>
  post<{ success: boolean }>(`${E}/libraries`, data)

export const scanLibrary = (id: number) => post<{ success: boolean }>(`${E}/libraries/${id}/scan`)

export const deleteLibrary = (id: number) => del<{ success: boolean }>(`${E}/libraries/${id}`)

export const fetchSessions = () => get<{ sessions: EmbySessionRow[] }>(`${E}/sessions`)

export const stopSession = (sessionKey: string) => del<{ success: boolean }>(`${E}/sessions/${sessionKey}`)

export const stopAllTranscodes = () => post<{ stopped: number }>(`${E}/transcodes/stop-all`)
