/** v2.2.0 管理端 API（全部走 /api/admin/*，详见 backend/api/admin.py 与 emby_server/portal.py） */
import { get, getBlob, postBlob, post, put, patch, del, upload } from '@/utils/request'
import type {
  AdminInfo,
  AdminListResponse,
  AdminLogRow,
  AdminRole,
  AdminRow,
  Announcement,
  CdnConfig,
  CodeStats,
  DeviceRow,
  DeviceStats,
  LoginLogsResponse,
  EmbyLibrary,
  EmbyReachabilityReport,
  EmbyScanQueue,
  EmbyScanRun,
  EmbyScanTask,
  EmbySessionRow,
  LocalCacheConfig,
  LocalCacheEntryInfo,
  LocalCacheStats,
  Pan115Account,
  Pan115DirEntry,
  StorageMount,
  MountTypeMeta,
  MountDirEntry,
  PlaybackNode,
  PlaybackPolicy,
  PlaybackRuntime,
  PlayLinesSnapshot,
  EaMountHealth,
  RemoteServerRow,
  ServerKind,
  ServerKindMeta,
  ServerOverview,
  ServerOpsScanResult,
  ServerOpsSnapshot,
  ServerProbeResult,
  ServerSummary,
  LoginResponse,
  MediaSeekRow,
  RealmNodeSync,
  RealmOverview,
  RealmRow,
  RealmSubscriptionsResponse,
  RealmSummary,
  RealmsResponse,
  OverviewStats,
  PlaybackStats,
  RegistrationCode,
  RegistrationSettings,
  RcloneRemote,
  TicketMessageRow,
  TicketRow,
  TrendStats,
  UserDetail,
  UserGrants,
  UsersResponse,
} from '@/types'

// ==================== 认证 ====================

/** 管理员登录；站点开了「保护管理后台登录」时必须带人机验证令牌 */
export const login = (data: { username: string; password: string; captcha_token?: string }) =>
  post<LoginResponse>('/auth/login', data)

// ==================== 首次运行向导 ====================

/** 向导状态：初始化是否已完成（免鉴权，前端进 /admin/ 前先问一次） */
export const setupStatus = () => get<{ setup_completed: boolean }>('/setup/status')

/** 建第一个管理员；成功后向导入口永久关闭（再调直接 403） */
export const createFirstAdmin = (data: { username: string; password: string }) =>
  post<{ ok: boolean; username: string; setup_completed: boolean }>('/setup', data)

export const fetchMe = () => get<AdminInfo>('/auth/me')

export const changePassword = (data: { old_password: string; new_password: string }) =>
  post<{ success: boolean }>('/auth/change-password', data)

// ==================== 用户管理 ====================

export const fetchUsers = (params: { search?: string; active?: boolean; limit?: number; offset?: number }) =>
  get<UsersResponse>('/users', params)

/** 用户 360° 详情：资料 / 订阅 / 积分 / 订单 / 邀请 / 签到 / 观看 */
export const fetchUserDetail = (id: number) => get<UserDetail>(`/users/${id}`)

/** 用户授权资源卡片（Phase 4）：一个服一张，看他现在能用什么 */
export const fetchUserGrants = (id: number) => get<UserGrants>(`/user-grants/${id}`)

/** 趋势统计（近 N 天，按日补零） */
export const fetchStatsTrend = (days = 14) => get<TrendStats>('/stats/trend', { days })

export interface PlanRow {
  id: number
  name: string
  description: string | null
  price: number
  duration_days: number
  is_popular: boolean
  /** 套餐属于哪个服（一个服一个）：授予订阅时按它开会员 */
  realm_id?: number | null
  realm_name?: string
}

/** 套餐清单；`realm_id=0` = 全部服，不传 = 当前服 */
export const fetchPlans = (realm_id?: number) =>
  get<{ plans: PlanRow[]; realm_id: number | null; active_realm_id: number }>(
    '/plans',
    realm_id === undefined ? undefined : { realm_id }
  )

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
  /** 这批码开通哪个服的会员（留空 = 当前服） */
  realm_id?: number
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
  /** 这批码开通哪个服的会员（留空 = 当前服） */
  realm_id?: number
}) => post<{
  success: boolean
  message: string
  realm_id: number
  realm_name: string
  codes: { id: number; code: string; days_text: string; expires_at: string }[]
}>(
  '/registration-codes/generate', data)

/** 卡码清单（按服；`realm_id=0` = 全部服，不传 = 当前服） */
export const fetchCodeList = (params: {
  code_type?: number
  state?: string
  keyword?: string
  realm_id?: number
  limit?: number
  offset?: number
} = {}) => get<{
  total: number
  realm_id: number | null
  realm_name: string
  realms: { id: number; name: string }[]
  codes: RegistrationCode[]
}>('/registration-codes/list', params)

export const fetchCodeStats = (realm_id?: number) =>
  get<CodeStats>('/registration-codes/stats', realm_id === undefined ? undefined : { realm_id })

export const patchRegistrationCode = (id: number, data: { is_active?: boolean; note?: string; realm_id?: number }) =>
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

/** 求片清单；`realm_id=0` = 全部服，不传 = 当前服 */
export const fetchMediaSeeks = (params: { status_filter?: string; realm_id?: number } = {}) =>
  get<MediaSeekRow[]>('/media-seek', params)

export const updateMediaSeek = (id: number, data: { status: string; admin_note?: string }) =>
  put<{ success: boolean }>(`/media-seek/${id}`, data)

/**
 * 入库后标记已入库：后端会先确认片真的在媒体库里（按 tmdb_id / 片名匹配），
 * 匹配不到返回 409；`force=true` 是人工兜底（片改了名入库时用）。
 */
export const markMediaSeekInLibrary = (id: number, force = false) =>
  post<{ success: boolean; matched: boolean; emby_item_id?: string | null; message: string }>(
    `/media-seek/${id}/mark-in-library`,
    { force },
    // silent：409（库里没找到）要由视图弹确认框，不能先弹一条红色错误
    { silent: true },
  )

/**
 * 把求片交给外部服务：MoviePilot（提交订阅）或 qBittorrent（加种）。
 * qB 自己不会去找片子，所以选它时必须带链接（磁力或 .torrent 地址）。
 */
export const pushMediaSeek = (id: number, data: { target?: string; link?: string }) =>
  post<{ success: boolean; target: string; server?: string; message: string; status: string }>(
    `/media-seek/${id}/push`,
    data
  )

// ==================== 多服运营（/api/admin/realms） ====================

const R = '/realms'

/** 服清单（含每服的运营数据）+ 当前服 + 跨服汇总 */
export const fetchRealms = () => get<RealmsResponse>(R)

/** 只取各服的运营数据：给「数据概览」的服卡片用 */
export const fetchRealmOverview = () => get<RealmOverview>(`${R}/overview`)

export interface RealmPayload {
  name: string
  slug?: string
  url?: string
  description?: string
  is_active?: boolean
  /** paid（付费服，需要订阅）/ free（公益服，免费开放） */
  access_mode?: 'paid' | 'free'
  /** 公益服规则文案（用户端展示） */
  access_note?: string
  /** 下载策略：不传 = 跟随全局（公益服默认禁止下载） */
  allow_download?: boolean | null
}

export const createRealm = (data: RealmPayload) =>
  post<{ success: boolean; realm: RealmRow; summary: RealmSummary }>(R, data)

export interface RealmUpdateData {
  name?: string
  url?: string
  description?: string
  is_active?: boolean
  sort_order?: number
  access_mode?: 'paid' | 'free'
  access_note?: string
  /** 三态：follow = 跟随全局 / allow / deny */
  download_policy?: 'follow' | 'allow' | 'deny'
}

export const updateRealm = (id: number, data: RealmUpdateData) =>
  put<{ success: boolean; realm: RealmRow; summary: RealmSummary }>(`${R}/${id}`, data)

/** 切换面板当前操作的服：后台各页的作用域跟着切（服务端落库，多管理员一致） */
export const activateRealm = (id: number) =>
  post<{ success: boolean; active_realm_id: number; realm: RealmRow; summary: RealmSummary }>(
    `${R}/${id}/activate`
  )

/** 重新体检该服的所有播放节点（顺便带回节点自称的服与负责的库） */
export const syncRealmNodes = (id: number) =>
  post<{ success: boolean; nodes: RealmNodeSync[]; realm: RealmRow }>(`${R}/${id}/sync`)

/** 删除服；服里还有数据时必须传 move_to 指定数据移交给谁 */
export const deleteRealm = (id: number, moveTo?: number | null) =>
  del<{ success: boolean; deleted: number; moved_to: number | null; summary: RealmSummary }>(
    `${R}/${id}`,
    moveTo ? { move_to: moveTo } : undefined
  )

/** 某个服的订阅清单（`realmId=0` = 全部服）—— 订阅一个服一个，默认只看当前服 */
export const fetchRealmSubscriptions = (
  realmId: number,
  params: { status_filter?: string; search?: string; limit?: number; offset?: number } = {}
) =>
  get<RealmSubscriptionsResponse>(`${R}/${realmId}/subscriptions`, params)

// ==================== 服务器管理 ====================

const S = '/servers'

export const fetchServers = (params: { realm_id?: number } = {}) =>
  get<{
    servers: RemoteServerRow[]
    kinds: ServerKindMeta[]
    summary: ServerSummary
    realm_id: number | null
    active_realm_id: number
    realms: { id: number; name: string; slug: string }[]
  }>(S, params)

/**
 * Emby 总览：一行一台出流入口（EA / 已有 Emby），带归属服、连接、节点认领、
 * 挂载体检与媒体库归属。
 *
 * `live=true` 才会真的去问每台已启用的 EA「你是谁、属于哪个服」并重拉挂载体检；
 * 默认只读已落库的结论，不拖慢打开页面。
 */
export const fetchServersOverview = (params: { realm_id?: number; live?: boolean } = {}) =>
  get<ServerOverview>(`${S}/overview`, params)

export const fetchServersSummary = () => get<ServerSummary>(`${S}/summary`)

/**
 * 媒体运维快照（服务器维度）：整服扫描历史 + 扫描任务 + 刮削补全 / 修复 + 内容转交
 *
 * 按库的配置不在这里改，这里只回答「这台机器现在跑得怎么样」。
 * `include_unassigned=true` 把同服里还没分配节点的库也算进来（默认不算）。
 */
export const fetchServerOps = (serverId: number, params: {
  include_unassigned?: boolean
  runs_limit?: number
} = {}) => get<ServerOpsSnapshot>(`${S}/${serverId}/ops`, params)

/**
 * 一键把这台节点负责的库推入扫描队列（扫描 → 入库 → 刮削流水线）
 *
 * 与逐库「扫描」同一套机制：面板能扫的本地入队、归其它节点管的转发过去、
 * 已在队列的不重复推。
 */
export const runServerOpsScan = (serverId: number, params: { include_unassigned?: boolean } = {}) =>
  post<ServerOpsScanResult>(`${S}/${serverId}/ops/scan`, params)

export interface BackendServiceStatus {
  name: string; role: string; status: string
  last_heartbeat?: number | null; lag_seconds?: number | null
  pid?: number; started_at?: number; timestamp?: number
}
export const fetchBackendServices = () =>
  get<{ success: boolean; services: BackendServiceStatus[] }>(`/services/status`)

export interface QuotaBreakerStatus {
  tripped: boolean
  consecutive_403: number
  threshold: number
  tripped_at: number | null
  backoff_sec: number
}
export const fetchQuotaBreakerStatus = () =>
  get<{ success: boolean; breaker: QuotaBreakerStatus }>(`/quota-breaker/status`)
export const resetQuotaBreaker = () =>
  post<{ success: boolean; message: string }>(`/quota-breaker/reset`)

export interface ServerPayload {
  name: string
  kind: ServerKind
  url: string
  config?: Record<string, string>
  is_enabled?: boolean
  remark?: string
  /** 属于哪个服（留空 = 新增时归当前服，修改时不改归属） */
  realm_id?: number | null
}

export const createServer = (data: ServerPayload) =>
  post<{ success: boolean; server: RemoteServerRow; probe: ServerProbeResult }>(S, data)

export const updateServer = (id: number, data: ServerPayload) =>
  put<{ success: boolean; server: RemoteServerRow; probe: ServerProbeResult }>(`${S}/${id}`, data)

export const deleteServer = (id: number) =>
  del<{ success: boolean; summary: ServerSummary }>(`${S}/${id}`)

/** 测试「还没保存」的配置；编辑时带 server_id，密钥留空则沿用已保存的那份 */
export const testServerConfig = (data: {
  kind: ServerKind
  url: string
  config?: Record<string, string>
  server_id?: number
}) => post<ServerProbeResult>(`${S}/test`, data)

export const testServer = (id: number) => post<ServerProbeResult>(`${S}/${id}/test`)

/** 设为该类型的「当前使用」（EA / Emby）：服务端会先重新体检一次再切换 */
export const activateServer = (id: number) =>
  post<{
    success: boolean
    activated?: boolean
    mode?: string
    message?: string
    probe: ServerProbeResult
    server?: RemoteServerRow
    /** 激活 EA 时会顺带拉一次「EA 视角的挂载体检」，失败代表那台机器碰不到你的存储 */
    mounts_health?: { ok: boolean; error?: string; checked_at?: string | null; failed_count?: number } | null
  }>(`${S}/${id}/activate`)

export const toggleServer = (id: number) =>
  post<{ success: boolean; server: RemoteServerRow; summary: ServerSummary }>(`${S}/${id}/toggle`)

/** 重拉一次「EA 视角的挂载体检」（挂载页也有入口，这里给服务器页用） */
export const refreshServerMounts = () =>
  post<{ success: boolean; health: { ok: boolean; error?: string; checked_at?: string | null }; server: string }>(
    `${S}/mounts/health`
  )

// ==================== 日志与统计 ====================

export const fetchLogs = (params: { limit?: number; action_filter?: string } = {}) =>
  get<AdminLogRow[]>('/logs', params)

export const fetchOverview = () => get<OverviewStats>('/stats/overview')

export interface PanelHealth {
  status: string
  health_level?: string
  health_issues?: Array<{ level: string; key: string; message: string }>
  timestamp: string
  database: string
  online_users: number
  emby_server: string
}

/** EM 面板健康状态；不暴露密钥与连接串，仅返回可运营的信息。 */
export const fetchPanelHealth = () => get<PanelHealth>('/../health')

// 注：「Emby 服务入口」那两个格子的页面（及它的读写接口封装）已下线，
// EA / Emby 入口统一在「服务器」页维护（见 views/Servers.vue）。
// 后端 /api/admin/emby/servers 仍在（挂载体检与列表页要用），但前端不再直连。

export const fetchPlaybackStats = () => get<PlaybackStats>('/stats/playback')

// ==================== 自建 Emby 管理（/api/admin/emby/*） ====================

const E = '/emby'

export const fetchEmbyOverview = () => get<{ total_items: number; total_libraries: number; active_sessions: number; total_users: number }>(`${E}/overview`)

/** 封面自动生成的配置：样式 + 标题文字（都支持 {library}{type}{year} 变量） */
export interface LibraryCoverConfig {
  template: 'poster' | 'visual' | 'filmstrip'
  title: string
  subtitle: string
}

export const fetchLibraries = () => get<{ libraries: EmbyLibrary[] }>(`${E}/libraries`)

/** 拉取封面二进制；管理端图片请求也带 JWT，不把令牌拼进 URL。 */
export const fetchLibraryCover = (id: number) => getBlob(`${E}/libraries/${id}/cover`)

export const uploadLibraryCover = (id: number, file: File) => {
  const data = new FormData()
  data.append('file', file)
  return upload<{ success: boolean; cover_url: string; content_type: string }>(
    `${E}/libraries/${id}/cover`, data
  )
}

export const removeLibraryCover = (id: number) =>
  del<{ success: boolean }>(`${E}/libraries/${id}/cover`)

/** 封面自动生成：按当前配置渲染一张预览图（不落库，改一个字调一次） */
export const previewLibraryCover = (id: number, body: LibraryCoverConfig) =>
  postBlob(`${E}/libraries/${id}/cover/preview`, body)

/** 封面自动生成：渲染并落库落盘，返回新的封面 URL */
export const renderLibraryCover = (id: number, body: LibraryCoverConfig) =>
  post<{
    success: boolean
    cover_url: string
    content_type: string
    template: string
    library_name: string
    media_type: string
  }>(`${E}/libraries/${id}/cover/render`, body)

/** 封面自动生成：按库里已保存的样式/标题重新生成（刮削补完新片后换封面） */
export const regenerateLibraryCover = (id: number) =>
  post<{ success: boolean; cover_url: string }>(`${E}/libraries/${id}/cover/regenerate`)

export const createLibrary = (data: {
  name: string
  collection_type: string
  paths: string[]
  /** 绑定的存储挂载（本机目录 / STRM / 115 / WebDAV / AList） */
  mount_ids?: number[]
  /** 刮削策略：missing_only（仅缺失时）/ 3m / 6m / 1y / all（全部重刮） */
  scrape_policy?: string
  /** 115 账号配置档：建库时就能绑，省得建完再进设置改一趟 */
  account_115_id?: number
  /** 归属服（留空 = 面板当前服）：内容隔离的边界 */
  realm_id?: number
  /** 归属播放节点（留空 = 未分配：所有节点可见、由面板扫描） */
  node_id?: number
  /** 封面自动生成：样式 + 标题文字；空 = 用直传封面 */
  cover_template?: 'poster' | 'visual' | 'filmstrip' | null
  cover_title?: string | null
  cover_subtitle?: string | null
}) => post<{ success: boolean; id: number; guid: string }>(`${E}/libraries`, data)

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
    /** 归属服：传 null 表示不标注（所有服可见），省略则不修改 */
    realm_id?: number | null
    /** 归属播放节点：传 null 表示不分配（所有节点可见），省略则不修改 */
    node_id?: number | null
    /** 封面自动生成：传 null/空串表示清除（回退直传封面），省略则不修改 */
    cover_template?: 'poster' | 'visual' | 'filmstrip' | null
    cover_title?: string | null
    cover_subtitle?: string | null
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
  post<{ success: boolean; libraries: number[]; already?: number[] }>(`${E}/libraries/repair/run`)

/**
 * 触发一个媒体库的扫描（v2.27.0 起是「入队」）
 *
 * - `started: true`：没被挡住，已经开扫；
 * - `started: false` + `task.position`：排在第几位（`task.waiting_for` 写明在等哪个挂载）；
 * - `already: true`：这个库已经在扫描 / 已在队列里（重复点击不报错），`message` 里有原因。
 */
export const scanLibrary = (id: number) =>
  post<{
    success: boolean
    queued?: boolean
    already?: boolean
    started?: boolean
    state?: string
    message?: string
    task?: EmbyScanTask
  }>(`${E}/libraries/${id}/scan`)

/** 扫描队列快照：正在跑 / 排队中 / 最近完成 + 远程 IO 计数（面板每几秒轮询一次） */
export const fetchScanQueue = () => get<EmbyScanQueue>(`${E}/scan-queue`)

// ==================== 元数据与刮削（EmbyAdmin.vue「元数据与刮削」分组） ====================

/** 密钥池里的一把 key（只给掩码与运行状态，**没有原文**） */
export interface TmdbKeyPoolRow {
  /** 展示序号（从 1 开始，与删除接口一致） */
  index: number
  masked: string
  /** 此刻正在用它发请求 */
  current: boolean
  /** 被限流 / 失效后进了冷却 */
  cooling: boolean
  cooldown_remaining: number
  reason: string
  hits: number
}

export interface TmdbKeysStatus {
  configured: boolean
  source: 'env' | 'db' | 'none'
  count: number
  masked: string[]
  env_present: boolean
  /** 实际在打请求/秒（自适应后） */
  rate?: number
  rate_ceiling?: number
  throttled?: number
  /** 逐把状态：哪把在用、哪把在冷却（还要 xx 秒） */
  pool?: TmdbKeyPoolRow[]
  keys_cooling?: number
  /** 当前生效的镜像地址（空配置 = 官方地址） */
  api_base?: string
  image_base?: string
  api_base_default?: string
  image_base_default?: string
  api_base_from_env?: boolean
  image_base_from_env?: boolean
}

/** TMDB Key 状态（只返回掩码与数量） */
export const fetchTmdbKeys = () => get<TmdbKeysStatus>(`${E}/scrape/tmdb-keys`)

/** 保存 TMDB API Keys（逗号/换行/空白分隔）：落库后立即热生效 */
export const saveTmdbKeys = (keys: string) =>
  put<{ success: boolean; saved: number; source: string; count: number }>(`${E}/scrape/tmdb-keys`, { keys })

/** 逐把增：往密钥池追加一把（去重；已存在返回 409） */
export const addTmdbKey = (key: string) =>
  post<{
    success: boolean
    count: number
    masked: string[]
    /** 环境变量里也有 key 时为 false（写入成功但暂不生效） */
    effective: boolean
    note: string
  }>(`${E}/scrape/tmdb-keys/add`, { key })

/** 逐把删：按展示序号（从 1 开始）删掉一把 */
export const deleteTmdbKey = (index: number) =>
  del<{ success: boolean; removed: string; count: number; masked: string[] }>(
    `${E}/scrape/tmdb-keys/${index}`)

/** 清除全部密钥的冷却（换完 key / 网络恢复后手动重来一次） */
export const resetTmdbKeyCooldown = () =>
  post<{ success: boolean; cleared: number; pool: TmdbKeyPoolRow[] }>(
    `${E}/scrape/tmdb-keys/cooldown/reset`)

export interface TmdbMirror {
  api_base: string
  image_base: string
  api_base_from_env?: boolean
  image_base_from_env?: boolean
  defaults: { api_base: string; image_base: string }
  cooldown_sec: number
  invalid_cooldown_sec: number
  /** 冷却时长对应的 SystemConfig 键（阈值不写死，可在配置里改） */
  cooldown_config_keys: string[]
}

export const fetchTmdbMirror = () => get<TmdbMirror>(`${E}/scrape/tmdb-mirror`)

/** 保存镜像地址（两个都传空 = 回到官方地址） */
export const saveTmdbMirror = (data: { api_base: string; image_base: string }) =>
  put<{ success: boolean; api_base: string; image_base: string; defaults: TmdbMirror['defaults'] }>(
    `${E}/scrape/tmdb-mirror`, data)

export interface TmdbTestResult {
  index: number
  masked: string
  ok: boolean
  message: string
}

/** 一键测试全部密钥：keys 为空则测当前生效的密钥池（测不通的会被放进冷却） */
export const testTmdbKeys = (keys?: string) =>
  post<{ results: TmdbTestResult[]; pool?: TmdbKeyPoolRow[] }>(
    `${E}/scrape/tmdb-test`, { keys: keys || '' })

// ==================== 多源元数据（Phase 6b） ====================

/** 某个源密钥池里的一把 key（同样只给掩码与运行状态） */
export interface MetaSourceKeyRow {
  index: number
  masked: string
  cooling: boolean
  cooldown_remaining: number
  reason: string
  hits: number
}

/** 一个数据源在配置里的样子（静态能力 + 运行状态都在这里） */
export interface MetaSourceRow {
  id: string
  label: string
  /** 一句话能力说明：它强在哪、缺什么（从后端的源注册表来，不在前端写死） */
  note: string
  /** 当前位次（从 1 开始，与拖动后的顺序一致） */
  position: number
  enabled: boolean
  requires_key: boolean
  /** 源天然给哪种语言：zh / en */
  lang: string
  /** 两次请求最小间隔秒数（0 = 不限速） */
  rate: number
  key_count: number
  keys: MetaSourceKeyRow[]
  cooling: number
  /** 这一轮为什么不参与（空 = 会参与）：已关闭 / 缺密钥 */
  skipped_reason: string
  /** key 去哪申请（后台直接给链接与说明，不用去搜索引擎里找） */
  apply_url?: string
  apply_hint?: string
  /** 密钥存在哪个配置键（告诉用户“去哪填”） */
  key_storage?: string
  /** true = 已废弃的旧键里还有残留（启动自愈会合并，界面提醒看一眼） */
  keys_legacy?: boolean
  /** 密钥在哪里填：inline = 本卡片行内输入；pool_card = 在下面的密钥池卡片里（TMDB） */
  key_entry?: 'inline' | 'pool_card'
}

export interface MetaSourcesConfig {
  enabled: boolean
  prefer_chinese: boolean
  order: string[]
  sources: MetaSourceRow[]
  default_order: string[]
  max_sources: number
  collect_timeout_sec: number
  active_count: number
}

export const fetchMetaSources = () => get<MetaSourcesConfig>(`${E}/scrape/meta-sources`)

/** 保存总开关 / 中文优先 / 顺序 / 逐源开关 / 逐源限速（**不动密钥池**） */
export const saveMetaSources = (data: {
  enabled: boolean
  prefer_chinese: boolean
  order: string[]
  toggles: Record<string, boolean>
  rates: Record<string, number>
}) => put<MetaSourcesConfig>(`${E}/scrape/meta-sources`, data)

/** 逐源逐把增：追加一把密钥（已存在返回 409） */
export const addMetaSourceKey = (sourceId: string, key: string) =>
  post<MetaSourcesConfig>(`${E}/scrape/meta-sources/${sourceId}/keys`, { key })

/** 逐源逐把删：按展示序号（从 1 开始）删一把 */
export const deleteMetaSourceKey = (sourceId: string, index: number) =>
  del<MetaSourcesConfig>(`${E}/scrape/meta-sources/${sourceId}/keys/${index}`)

/** 清除某个源全部密钥的冷却 */
export const resetMetaSourceCooldown = (sourceId: string) =>
  post<{ success: boolean; cleared: number; config: MetaSourcesConfig }>(
    `${E}/scrape/meta-sources/${sourceId}/keys/reset`)

/** 试采集的一行：命中了没有 / 为什么没问 / 失败原因 */
export interface MetaSourceOutcome {
  source: string
  label: string
  ok: boolean
  hit: boolean
  error: string
  elapsed_ms: number
  skipped: string
}

export interface MetaSourceProbe {
  fields: Record<string, unknown>
  external_ids: Record<string, string>
  outcomes: MetaSourceOutcome[]
  /** 哪个源赢了标题（空 = 都没命中） */
  primary: string
  prefer_chinese: boolean
}

/**
 * 试采集：用一个片名跑一遍，**不改任何数据**。
 * ``source`` 传了就只问那一个源（单独排查“是不是这个站在抽风”）。
 */
export const probeMetaSources = (data: {
  title: string
  year?: number | null
  kind: 'series' | 'movie'
  source?: string
}) => post<{
  success: boolean
  switch_on: boolean
  probe: MetaSourceProbe
  note: string
  sources: MetaSourceRow[]
}>(`${E}/scrape/meta-sources/test`, {
  title: data.title,
  year: data.year ?? null,
  kind: data.kind,
  source: data.source || '',
})

/** 逐把试某个源的密钥（测不通的直接进冷却） */
export const testMetaSourceKeys = (
  sourceId: string,
  data: { title: string; year?: number | null; kind: 'series' | 'movie' },
) => post<{
  results: Array<{
    index: number
    masked: string
    ok: boolean
    hit?: boolean
    message: string
    elapsed_ms?: number
  }>
  config: MetaSourcesConfig
}>(`${E}/scrape/meta-sources/${sourceId}/test`, {
  title: data.title,
  year: data.year ?? null,
  kind: data.kind,
})

export interface RescrapeSummary {
  notes: string[]
  changed: Record<string, string>
  nfo_found: boolean
}

/** 条目级手动刮削（同步）：电影/剧集优先，季/集按 NFO 能力处理 */
export const rescrapeItem = (id: number) =>
  post<{ success: boolean; item: { id: number; name: string; item_type: string }; summary: RescrapeSummary }>(
    `${E}/scrape/items/${id}/rescrape`,
    {},
  )

/** 库级手动刮削：触发一次该库扫描，policy 只覆盖本轮快照（missing_only | all） */
export const rescrapeLibrary = (id: number, policy: 'missing_only' | 'all' = 'missing_only') =>
  post<{ success: boolean; started: boolean; already?: boolean; message: string }>(
    `${E}/scrape/libraries/${id}/rescrape`,
    { policy },
  )

export interface TmdbPreview {
  tmdb_id: string
  title: string
  year: number | null
  poster: string | null
  current_name: string
  current_tmdb_id: string | number | null
  matches_current: boolean
}

/** TMDB 预览：绑定前先看清「这到底是哪部片」，只读不写库 */
export const previewTmdb = (id: number, tmdbId: string) =>
  get<TmdbPreview>(`${E}/scrape/items/${id}/tmdb-preview`, { tmdb_id: tmdbId })

export interface TmdbBindResult {
  success: boolean
  unbound: boolean
  item: { id: number; name: string; item_type: string; tmdb_id?: string | number | null }
  notes: string[]
}

/** 手动绑定 TMDB ID（tmdbId 为空字符串 = 解绑）；绑定后自动补全缺失元数据 */
export const bindTmdb = (id: number, tmdbId: string, verify = true) =>
  post<TmdbBindResult>(`${E}/scrape/items/${id}/bind-tmdb`, { tmdb_id: tmdbId, verify })

/** 阶段统计（v2.42.9）：次数 + 累计耗时 + 平均耗时。avg_ms 只对「计过时」的那几次求平均 */
export interface EnrichStageStat {
  label: string
  count: number
  ms: number
  avg_ms: number
  last_at: string | null
}

/** 完成速率（v2.42.9）：近 window_sec 内每分钟的完成条数 + 距上一次成功的秒数 */
export interface EnrichThroughput {
  done_per_min: number
  retry_per_min: number
  failed_per_min: number
  window_sec: number
  samples: number
  done_total: number
  retry_total: number
  failed_total: number
  last_done_at: string | null
  idle_sec: number | null
}

export interface EnrichProgress {
  enrich: { pending: number; enriching: number; done: number; failed: number; retrying: number }
  probe: Record<string, number>
  workers: number
  enabled: boolean
  /** v2.42.9：阶段用时分解。键：remote_list / local_list / nfo_read / nfo_hit / tmdb_req /
   *  image_dl / enrich_item；进程内计数，进程重启归零 */
  stages?: Record<string, EnrichStageStat>
  throughput?: EnrichThroughput
  /** 远程目录列举的累计计数（真实请求 / 复用 / 在飞 / 峰值） */
  mount_io?: Record<string, number | string | null>
}

/** 补全 worker 进度：enrich 待处理/进行中/成功/失败/重试中 */
export const fetchEnrichProgress = () =>
  get<{ success: boolean } & EnrichProgress>(`${E}/scrape/enrich-progress`)

export interface AutoScanConfig {
  enabled: boolean
  /** 每天执行时间，"HH:MM"（服务器本地时间） */
  time: string
  /** 上次执行日期 "YYYY-MM-DD"，没跑过为空 */
  last_run: string
}

/** 定时扫描当前配置（开关 / 时间 / 上次执行） */
export const fetchAutoScan = () => get<{ success: boolean } & AutoScanConfig>(`${E}/scrape/auto-scan`)

/** 保存定时扫描配置：立即生效，无需重启；时间格式非法时后端 400 */
export interface ChaseNewConfig {
  enabled: boolean
  interval: number
  libraries: string
  last_check: string
  last_found: number
}
export const fetchChaseNew = () => get<{ success: boolean } & ChaseNewConfig>(`${E}/scrape/chase-new`)
export const saveChaseNew = (enabled: boolean, interval: number, libraries: string) =>
  put<{ success: boolean } & ChaseNewConfig>(`${E}/scrape/chase-new`, { enabled, interval, libraries })

// rclone remote 管理（类型统一在 @/types，与后端 _serialize_remote 对齐）
export type { RcloneRemote } from '@/types'
export const setProbeRemote = (id: number) => post<{ success: boolean }>(`${E}/rclone/remotes/${id}/probe`, {})
export const regenerateRcloneConf = () => post<{ success: boolean; path: string }>(`${E}/rclone/regenerate`, {})
export interface SaFile { id: number; filename: string; client_email: string; project_id: string; is_enabled: boolean }
export const fetchSaFiles = () => get<{ success: boolean; files: SaFile[] }>(`${E}/rclone/sa-files`)
export const saveAutoScan = (enabled: boolean, time: string) =>
  put<{ success: boolean } & AutoScanConfig>(`${E}/scrape/auto-scan`, { enabled, time })

export interface BackupFile { name: string; size: number; created_at: string }
export interface BackupConfig {
  enabled: boolean
  /** 每天执行时间，"HH:MM"（服务器本地时间） */
  time: string
  /** 保留最近 N 天 */
  keep_days: number
  /** 上次执行日期 "YYYY-MM-DD"，没跑过为空 */
  last_run: string
  backups: BackupFile[]
}

/** 数据库备份配置 + 备份文件列表 */
export const fetchBackupConfig = () =>
  get<{ success: boolean } & BackupConfig>(`/system/backup`)

/** 保存数据库备份配置：立即生效，无需重启；非法时后端 400 */
export const saveBackupConfig = (enabled: boolean, time: string, keep_days: number) =>
  put<{ success: boolean } & BackupConfig>(`/system/backup`, { enabled, time, keep_days })

/** 立即手动备份一次 */
export const runBackupNow = () =>
  post<{ success: boolean; backup: { name: string; size: number } } & BackupConfig>(`/system/backup/run`, {})

/**
 * 播放可达性报告（v2.28.0）：出流方式 + 逐库判定 + 用户端地址一致性
 *
 * 「面板扫描正常、播放节点找不到媒体」这类问题在这里提前暴露：本机路径 / local 挂载的库
 * 在 EA 出流时拿不到内容（warn = 无法确认，bad = 有证据），不用等客户端点播放才 404。
 */
export const fetchReachability = () => get<EmbyReachabilityReport>(`${E}/reachability`)

/** 取消一个**还在排队**的扫描（正在跑的不能取消：停在中途会留下半个库的状态） */
export const cancelQueuedScan = (id: number) =>
  del<{ success: boolean; library_id: number }>(`${E}/scan-queue/${id}`)

/** 某个媒体库最近的扫描流水（新的在前）；keep = 后端每库保留条数 */
export const fetchLibraryScans = (id: number, limit = 20) =>
  get<{ library_id: number; keep: number; runs: EmbyScanRun[] }>(`${E}/libraries/${id}/scans?limit=${limit}`)

export const deleteLibrary = (id: number) => del<{ success: boolean }>(`${E}/libraries/${id}`)

export const fetchSessions = () => get<{ sessions: EmbySessionRow[] }>(`${E}/sessions`)

export const stopSession = (sessionKey: string) => del<{ success: boolean }>(`${E}/sessions/${sessionKey}`)

export const stopAllTranscodes = () => post<{ stopped: number }>(`${E}/transcodes/stop-all`)

// ==================== 管理员与权限（v2.26.0，/api/admin/admins） ====================
// 角色定义在后端（backend/admin_roles.py）：super = 全部；operator = 日常运营；
// viewer = 只读。角色判定发生在服务端鉴权依赖里，这里的函数只是调用入口。

export const fetchAdmins = () => get<AdminListResponse>('/admins')

/** 把已注册的用户提为管理员（只标记账号 + 定角色，不新建账号） */
export const grantAdmin = (data: { username?: string; email?: string; role: AdminRole }) =>
  post<{ success: boolean; admin: AdminRow }>('/admins', data)

export const updateAdmin = (userId: number, data: { role?: AdminRole; is_active?: boolean }) =>
  patch<{ success: boolean; changed: Record<string, unknown>; admin: AdminRow }>(
    `/admins/${userId}`, data,
  )

export const revokeAdmin = (userId: number) =>
  del<{ success: boolean }>(`/admins/${userId}`)

// ==================== 播放与客户端策略（v2.26.0，/api/admin/playback） ====================
// 转码开关 / 并发上限 / 码率上限 / 客户端准入：改完对 EM 与 EA 同时生效（同一个库）。

export const fetchPlaybackPolicy = () =>
  get<{ policy: PlaybackPolicy; keys: Record<string, string>; runtime: PlaybackRuntime }>(
    '/playback/policy',
  )

// ==================== 播放线路可观测（Phase 3，/api/admin/playback/lines） ====================
// 四条线路各一张卡片：能不能用 / 是不是在降级 / 有多少人多少流量 / 效果如何。
// **只读**：线路配置在 CDN / 本地缓存两个卡片里改，这里不改。
// 灰度发布（0% 流量影子评估）本期不做，所以也没有对应的开关。

export const fetchPlayLines = () => get<PlayLinesSnapshot>('/playback/lines')

export const updatePlaybackPolicy = (policy: Partial<PlaybackPolicy>) =>
  put<{ success: boolean; applied: Record<string, string>; policy: PlaybackPolicy }>(
    '/playback/policy', { policy },
  )

// ==================== CDN 域名预留（播放三层第 2/3 层，/api/admin/playback/cdn） ====================
// 只做域名预留：启用后播放 URL 走该 CDN 域名（回源到现有服务），热门分片由边缘缓存。

export const fetchCdnConfig = () =>
  get<{ success: boolean; cdn: CdnConfig; play_lines: string[] }>('/playback/cdn')

export const updateCdnConfig = (payload: { domain: string; enabled: boolean }) =>
  put<{ success: boolean; cdn: CdnConfig }>('/playback/cdn', payload)

// ==================== VPS 本地缓存（播放线路「本地缓存」，/api/admin/playback/local-cache） ====================

/** 本地缓存：配置 + 占用/命中率统计 + 条目列表（只读） */
export const fetchLocalCacheConfig = () =>
  get<{
    success: boolean
    local_cache: LocalCacheConfig
    stats: LocalCacheStats
    entries: LocalCacheEntryInfo[]
    play_lines: string[]
  }>('/playback/local-cache')

/** 写回本地缓存配置（开关 / 目录 / 配额 / 热门规则 / 限速），参数非法由后端 400 拒绝 */
export const updateLocalCacheConfig = (payload: {
  enabled: boolean
  dir: string
  max_gb: number
  hot_days: number
  hot_plays: number
  rate_mbps: number
}) => put<{ success: boolean; local_cache: LocalCacheConfig; stats: LocalCacheStats }>(
  '/playback/local-cache', payload,
)

/** 手动清理：ready = 清本机副本，failed = 清失败记录，all = 全部（不含下载中的） */
export const cleanLocalCache = (mode: 'ready' | 'failed' | 'all') =>
  post<{ success: boolean; cleaned: { mode: string; removed: number; freed_bytes: number }; stats: LocalCacheStats }>(
    '/playback/local-cache/clean', { mode },
  )

// ==================== 存储挂载（/api/admin/emby/mounts） ====================
// 挂载 = 媒体库的内容来源：local / strm 是本机目录，115 / webdav / alist 是远程来源。
// 远程挂载的条目在库里存 mount:// 路径，播放时由 EA 代理转发（凭据不下发）。

/** 挂载清单；`realm_id=0` = 全部服，不传 = 当前服（挂载是一个服一个的） */
export const fetchMounts = (realm_id?: number) =>
  get<{
    mounts: StorageMount[]
    mount_types: MountTypeMeta[]
    /** 当前出流的节点：只有它是 ea 时，「EA 不可达」才是阻断性告警 */
    playback_node: PlaybackNode
    ea_health: EaMountHealth
    realm_id: number | null
    realm_names: Record<string, string>
  }>(`${E}/mounts`, realm_id === undefined ? undefined : { realm_id })

/** 本机（EM）体检：逐条跑一遍与「测试连接」相同的探测并落库 */
export const probeMountsHealth = () =>
  post<{ mounts: StorageMount[]; total: number; ok_count: number; failed_count: number }>(
    `${E}/mounts/health`
  )

/** EA 体检：让 EM 向 EA 拉一次「以 EA 视角」的挂载体检并落库 */
export const refreshEaMountHealth = () =>
  post<{
    success: boolean
    health: { ok: boolean; error?: string; checked_at?: string | null; failed_count?: number }
  }>('/emby/servers/mounts/refresh')

export interface MountPayload {
  name?: string
  mount_type?: string
  path?: string
  /** 配置项；密钥类字段（password / token / cookie）留空表示不修改 */
  config?: Record<string, string>
  is_enabled?: boolean
  remark?: string
  /** 归属服（留空 = 当前服）；换服时引用它的媒体库会跟着走 */
  realm_id?: number
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

/** 挂载路径选择器：只列子目录（媒体库表单「浏览」按钮用，走 /api/admin/mounts） */
export interface MountPickerDir {
  name: string
  path: string
}
export interface MountPickerCrumb {
  name: string
  path: string
}
export const browseMountDirs = (id: number, path?: string) =>
  get<{
    mount_id: number
    path: string
    parent: string | null
    crumbs: MountPickerCrumb[]
    dirs: MountPickerDir[]
    total: number
  }>(`/mounts/${id}/browse`, path ? { path } : undefined)

/** rclone：列出远端已配置的 remote（可用表单里尚未保存的 RC 地址 / 密码） */
export const fetchMountRcloneRemotes = (params: Record<string, string>) =>
  get<{ remotes: string[]; total: number }>(`${E}/mounts/rclone/remotes`, params)

// ==================== 115 账号与直挂（/api/admin/emby/115/*） ====================

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

/** 浏览 115 目录（账号可用性实测 / 直挂目录结构）：账号配置档优先，表单 Cookie 次之 */
export const browsePan115 = (params: { cid?: string; account_id?: number; cookie?: string }) =>
  get<{ cid: string; cookie_source: string; entries: Pan115DirEntry[]; total: number }>(
    `${E}/115/browse`, params
  )


// ==================== rclone remote 配置（/api/admin/emby/rclone/*） ====================

export const fetchRcloneRemotes = () =>
  get<{ remotes: RcloneRemote[] }>(`${E}/rclone/remotes`)

export const createRcloneRemote = (data: {
  name: string
  remote_type?: string
  drive_type?: string
  client_id?: string
  client_secret?: string
  team_drive_id?: string
  is_enabled?: boolean
  remark?: string
}) => post<{ success: boolean; remote: RcloneRemote }>(`${E}/rclone/remotes`, data)

export const updateRcloneRemote = (
  id: number,
  data: { name?: string; client_id?: string; client_secret?: string; team_drive_id?: string; is_enabled?: boolean; remark?: string }
) => put<{ success: boolean; remote: RcloneRemote }>(`${E}/rclone/remotes/${id}`, data)

export const deleteRcloneRemote = (id: number) =>
  del<{ success: boolean }>(`${E}/rclone/remotes/${id}`)

export const generateRcloneConf = () =>
  post<{ success: boolean; message: string; backup: string; reload: { success: boolean; message: string } }>(
    `${E}/rclone/remotes/generate-conf`, {})

export const previewRcloneConf = () =>
  get<{ preview: string }>(`${E}/rclone/remotes/conf-preview`)

export const setProbeRcloneRemote = (id: number) =>
  post<{ success: boolean; probe_remote: string }>(`${E}/rclone/remotes/${id}/set-probe`, {})

export const fetchProbeRcloneRemote = () =>
  get<{ probe_remote: string | null }>(`${E}/rclone/probe-remote`)

export const fetchRcloneOAuthUrl = (id: number) =>
  get<{ oauth_url: string; redirect_uri: string }>(`${E}/rclone/remotes/${id}/oauth-url`)

export const submitRcloneOAuthCode = (id: number, data: { code: string; redirect_uri: string }) =>
  post<{ success: boolean; has_token: boolean }>(`${E}/rclone/remotes/${id}/oauth-callback`, data)

export const uploadRcloneServiceAccount = (id: number, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return upload<{ success: boolean; filename: string; client_email: string; project_id: string }>(
    `${E}/rclone/remotes/${id}/upload-sa`, fd)
}
