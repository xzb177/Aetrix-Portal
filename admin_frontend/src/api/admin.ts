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
  Pan115Account,
  Pan115DirEntry,
  Pan115Task,
  StorageMount,
  MountTypeMeta,
  MountDirEntry,
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

export const createLibrary = (data: {
  name: string
  collection_type: string
  paths: string[]
  /** 绑定的存储挂载（本机目录 / STRM / 115 / WebDAV / AList） */
  mount_ids?: number[]
  /** 刮削策略：missing_only（仅缺失时）/ 3m / 6m / 1y / all（全部重刮） */
  scrape_policy?: string
}) => post<{ success: boolean }>(`${E}/libraries`, data)

export const updateLibrary = (
  id: number,
  data: {
    name?: string
    collection_type?: string
    paths?: string[]
    /** 存储挂载绑定：传 [] 表示解绑全部，省略则不修改 */
    mount_ids?: number[]
    is_enabled?: boolean
    scrape_policy?: string
    /** 115 账号配置档：传 null 表示解绑（回退默认账号），省略则不修改 */
    account_115_id?: number | null
  }
) => put<{ success: boolean; rescan_required?: boolean }>(`${E}/libraries/${id}`, data)

/** 按发行平台自动生成虚拟媒体库（Netflix / Disney+ / Apple TV+ …） */
export const generateVirtualLibraries = (data: { platforms?: string[]; enabled?: boolean; prune?: boolean } = {}) =>
  post<{
    success: boolean
    created: { id: number; platform: string; name: string }[]
    updated: { id: number; platform: string; name: string }[]
    pruned: { id: number; platform: string; name: string }[]
    available_platforms: { platform: string; name: string }[]
  }>(`${E}/libraries/virtual`, data)

/** 待修复条目：数据库里有图片记录但取不到图（本地文件丢失 / 远程图失效） */
export const fetchRepairQueue = () =>
  get<{ total: number; items: { id: string; name: string; type: string; requested_at: string | null }[] }>(
    `${E}/libraries/repair/queue`
  )

export const runRepairQueue = () =>
  post<{ success: boolean; libraries: number[] }>(`${E}/libraries/repair/run`)

export const scanLibrary = (id: number) => post<{ success: boolean }>(`${E}/libraries/${id}/scan`)

export const deleteLibrary = (id: number) => del<{ success: boolean }>(`${E}/libraries/${id}`)

export const fetchSessions = () => get<{ sessions: EmbySessionRow[] }>(`${E}/sessions`)

export const stopSession = (sessionKey: string) => del<{ success: boolean }>(`${E}/sessions/${sessionKey}`)

export const stopAllTranscodes = () => post<{ stopped: number }>(`${E}/transcodes/stop-all`)

// ==================== 存储挂载（/api/admin/emby/mounts） ====================
// 挂载 = 媒体库的内容来源：local / strm 是本机目录，115 / webdav / alist 是远程来源。
// 远程挂载的条目在库里存 mount:// 路径，播放时由 EA 代理转发（凭据不下发）。

export const fetchMounts = () =>
  get<{ mounts: StorageMount[]; mount_types: MountTypeMeta[] }>(`${E}/mounts`)

export interface MountPayload {
  name?: string
  mount_type?: string
  path?: string
  /** 配置项；密钥类字段（password / token / cookie）留空表示不修改 */
  config?: Record<string, string>
  is_enabled?: boolean
  remark?: string
}

export const createMount = (data: MountPayload) =>
  post<{ success: boolean; mount: StorageMount }>(`${E}/mounts`, data)

export const updateMount = (id: number, data: MountPayload) =>
  put<{ success: boolean; mount: StorageMount; rescan_required?: boolean }>(`${E}/mounts/${id}`, data)

export const deleteMount = (id: number) =>
  del<{ success: boolean; unbound_libraries: number }>(`${E}/mounts/${id}`)

export const testSavedMount = (id: number) =>
  post<{ success: boolean; result: { ok: boolean; message: string }; mount: StorageMount }>(
    `${E}/mounts/${id}/test`
  )

export const testMountConfig = (data: { mount_type: string; path?: string; config?: Record<string, string> }) =>
  post<{ success: boolean; result: { ok: boolean; message: string } }>(`${E}/mounts/test`, data)

export const browseMount = (id: number, rel = '/') =>
  get<{ rel: string; entries: MountDirEntry[]; total: number }>(`${E}/mounts/${id}/browse`, { rel })

// ==================== 115 下载与转存（/api/admin/emby/115/*） ====================

export const fetchPan115Accounts = () =>
  get<{ accounts: Pan115Account[]; env_cookie_configured: boolean }>(`${E}/115/accounts`)

export const createPan115Account = (data: {
  name: string
  cookie: string
  is_default?: boolean
  is_enabled?: boolean
  remark?: string
}) => post<{ success: boolean; account: Pan115Account }>(`${E}/115/accounts`, data)

export const updatePan115Account = (
  id: number,
  data: { name?: string; cookie?: string; is_default?: boolean; is_enabled?: boolean; remark?: string }
) => put<{ success: boolean; account: Pan115Account }>(`${E}/115/accounts/${id}`, data)

export const deletePan115Account = (id: number) => del<{ success: boolean }>(`${E}/115/accounts/${id}`)

export const verifyPan115Account = (id: number) =>
  post<{ success: boolean; result: { ok: boolean; message?: string }; account: Pan115Account }>(
    `${E}/115/accounts/${id}/verify`
  )

export const verifyPan115Cookie = (cookie: string) =>
  post<{ success: boolean; result: { ok: boolean; message?: string } }>(`${E}/115/verify`, { cookie })

export const parsePan115Share = (shareUrl: string) =>
  post<{ success: boolean; parsed: { share_code: string; receive_code: string; url: string } }>(
    `${E}/115/parse`, { share_url: shareUrl }
  )

/** 浏览 115 目录（目标路径选择器）：表单 Cookie 优先，其次账号配置档，最后已保存 Cookie */
export const browsePan115 = (params: { cid?: string; account_id?: number; cookie?: string }) =>
  get<{ cid: string; cookie_source: string; entries: Pan115DirEntry[]; total: number }>(
    `${E}/115/browse`, params
  )

export const fetchPan115Tasks = (params: { status?: string; limit?: number } = {}) =>
  get<{
    tasks: Pan115Task[]
    active_count: number
    waiting_auth_count: number
    modes: { value: string; label: string }[]
    statuses: { value: string; label: string }[]
  }>(`${E}/115/tasks`, params)

export const createPan115Task = (data: {
  share_url: string
  target_cid?: string
  target_path?: string
  account_id?: number | null
  library_id?: number | null
  mode?: string
  cookie?: string
}) => post<{ success: boolean; task: Pan115Task }>(`${E}/115/tasks`, data)

export const retryPan115Task = (id: number) =>
  post<{ success: boolean; task: Pan115Task }>(`${E}/115/tasks/${id}/retry`)

export const cancelPan115Task = (id: number) =>
  post<{ success: boolean; task: Pan115Task }>(`${E}/115/tasks/${id}/cancel`)
