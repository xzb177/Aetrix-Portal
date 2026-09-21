/** v2.2.0 管理后台类型定义（对齐后端 /api/admin/* 契约） */

export interface AdminInfo {
  id: number
  username: string
  is_staff: boolean
  created_at?: string | null
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: AdminInfo
}

export interface AdminUserRow {
  id: number
  username: string
  email: string | null
  is_active: boolean
  is_staff: boolean
  emby_username: string | null
  has_subscription: boolean
  subscription_id: number | null
  subscription_end: string | null
  last_login_at: string | null
  created_at: string
}

export interface UsersResponse {
  total: number
  users: AdminUserRow[]
}

export type CodeType = 1 | 2 | 3

/** 卡码状态：可用 / 已停用 / 已过期 / 已用尽 */
export type CodeState = 'active' | 'disabled' | 'expired' | 'used_up'

export interface RegistrationCode {
  id: number
  code: string
  code_type: CodeType
  code_type_name: string
  days: number
  days_text: string
  is_permanent: boolean
  is_decoy: boolean
  target_username: string
  source: string
  max_uses: number
  use_count: number
  is_active: boolean
  state: CodeState
  note: string | null
  expires_at: string | null
  used_by: { id: number; username: string }[]
  created_at: string
}

export interface CodeTypeStat {
  code_type: CodeType
  code_type_name: string
  total: number
  used: number
  available: number
}

export interface CodeStats {
  total: number
  active: number
  disabled: number
  expired: number
  used_up: number
  decoy: { total: number; triggered: number }
  days_granted: number
  by_type: CodeTypeStat[]
}

/** 播放设备（用户第三方客户端登录设备） */
export interface DeviceRow {
  device_id: string
  name: string | null
  client: string | null
  app_version: string | null
  ip: string | null
  is_blocked: boolean
  first_seen_at: string | null
  last_seen_at: string | null
  user_id: number
  username: string
  is_user_active: boolean
  is_online_recent: boolean
}

export interface DeviceStats {
  total: number
  active_30d: number
  blocked: number
  users: number
  limit_per_user: number
  auto_evict: boolean
  active_days: number
}

/** 登录 / 安全事件日志 */
export interface LoginLogRow {
  id: number
  user_id: number | null
  username: string | null
  ip: string | null
  user_agent: string | null
  success: boolean
  reason: string | null
  reason_label: string
  detail: string | null
  created_at: string | null
}

export interface LoginLogsResponse {
  total: number
  summary: { failed_24h: number; risk_24h: number }
  reasons: { value: string; label: string }[]
  logs: LoginLogRow[]
}

export interface RegistrationSettings {
  mode: 'open' | 'code' | 'closed'
  message: string
}

export interface Announcement {
  id: number
  title: string
  content: string
  type: string
  is_pinned: boolean
  is_active?: boolean
  created_at: string
  updated_at?: string | null
}

export interface TicketRow {
  id: number
  title: string
  category: string
  status: string
  priority: string
  user_name: string
  created_at: string
  updated_at: string
  latest_message: string
}

export interface TicketMessageRow {
  id: number
  message: string
  is_admin: boolean
  created_at: string
  admin_name: string | null
}

export interface MediaSeekRow {
  id: number
  movie_name: string
  year: string | null
  type: string | null
  note: string | null
  status: string
  admin_note: string | null
  user_name: string
  created_at: string
  /** 已转交的外部服务：moviepilot（已提交订阅）/ qbittorrent（已交给下载器） */
  push_target: string | null
  push_status: string | null
  push_message: string | null
  pushed_at: string | null
}

// ==================== 服务器清单 ====================

// ==================== 多服运营（server_realms） ====================

/** 一个服 = 一套可以独立运营的播放服务：自己的套餐/订阅/媒体库/播放节点 */
export interface RealmNode {
  id: number
  name: string
  url: string
  /** AE 用 NODE_KEY 认领这条记录；空串表示还没认领 */
  node_key: string
  is_enabled: boolean
  is_active: boolean
  online: boolean
  last_checked_at: string | null
  last_check_message: string
}

export interface RealmStats {
  libraries: number
  enabled_libraries: number
  items: number
  mounts: number
  plans: number
  active_subscriptions: number
  expiring_subscriptions: number
  subscribers: number
  nodes: number
  nodes_online: number
  pending_requests: number
}

export interface RealmRow {
  id: number
  name: string
  slug: string
  url: string
  description: string
  is_active: boolean
  sort_order: number
  /** 默认服：沿用历史配置键名，不能删除 */
  is_default: boolean
  /** 用户端该连的地址（服自己的地址 → 该服 Emby 入口 → 全局环境变量） */
  public_url: string
  nodes: RealmNode[]
  stats: RealmStats
  created_at: string | null
}

export interface RealmSummary {
  total_realms: number
  enabled_realms: number
  libraries: number
  items: number
  plans: number
  active_subscriptions: number
  subscribers: number
  nodes: number
  nodes_online: number
  pending_requests: number
}

export interface RealmsResponse {
  realms: RealmRow[]
  active_realm_id: number
  active_realm_name: string
  summary: RealmSummary
}

export interface RealmOverview {
  realms: {
    id: number
    name: string
    slug: string
    url: string
    is_active: boolean
    is_default: boolean
    public_url: string
    stats: RealmStats
  }[]
  active_realm_id: number
  summary: RealmSummary
}

/** 同步（体检）一个服的所有播放节点后的逐台结果 */
export interface RealmNodeSync {
  id: number
  name: string
  url: string
  ok: boolean
  message: string
  node_key_claimed: string
  realm_slug_reported: string
  libraries: number
  /** 节点自称的服与面板记录不一致：REALM / NODE_KEY 配错了 */
  realm_mismatch: boolean
}

/** 服务器类型：ea（后端服）/ emby（已有 Emby）/ moviepilot / qbittorrent */
export type ServerKind = 'ea' | 'emby' | 'moviepilot' | 'qbittorrent'

/** 类型声明的一个配置字段（由后端类型元数据下发，前端不再维护一份） */
export interface ServerFieldMeta {
  key: string
  label: string
  type?: 'text' | 'password' | 'number'
  secret?: boolean
  placeholder?: string
  help?: string
}

export interface ServerKindMeta {
  value: ServerKind
  label: string
  short: string
  desc: string
  group: string
  /** 只有 EA / Emby 有「当前使用」的概念 */
  activatable: boolean
  fields: ServerFieldMeta[]
}

export interface RemoteServerRow {
  id: number
  name: string
  kind: ServerKind
  kind_label: string
  kind_group: string
  url: string
  /** 属于哪个服（多服运营）：EA / Emby 一定属于某个服 */
  realm_id: number | null
  realm_name: string
  /** 内容自动化（MoviePilot / qB）声明了「全服共用」：不属于某个服，每个服都能用 */
  shared?: boolean
  /** EA 认领用的节点标识（面板在这里填，EA 用同名 NODE_KEY 启动） */
  node_key: string
  config: Record<string, string>
  /** 已配置密钥的字段名（密钥明文永不下发） */
  secret_keys: string[]
  is_enabled: boolean
  is_active: boolean
  remark: string
  last_checked_at: string | null
  last_check_ok: boolean | null
  last_check_message: string
  activatable: boolean
  can_push_media_seek: boolean
}

export interface ServerKindSummary {
  kind: ServerKind
  label: string
  short: string
  group: string
  activatable: boolean
  total: number
  enabled: number
  reachable: number
  active_id: number | null
  active_name: string
  active_url: string
}

export interface ServerSummary {
  kinds: Record<string, ServerKindSummary>
  total: number
  reachable: number
  unchecked: number
  /** 当前统计范围（服）；null = 全部服 */
  realm_id?: number | null
  /** 可以用来接收求片推送的类型（已启用且体检通过） */
  push_ready: ServerKind[]
}

export interface ServerProbeResult {
  ok: boolean
  message?: string
  status_code?: number | null
  server_name?: string
  version?: string
  can_query?: boolean
  can_subscribe?: boolean
  subscribe_count?: number | null
  torrent_count?: number | null
}

export interface AdminLogRow {
  id: number
  action: string
  target_type: string | null
  target_id: number | null
  details: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
  admin_name: string
}

export interface OverviewStats {
  users: { total: number; active: number }
  tickets: { open: number }
  media_seeks: { pending: number }
  emby: { total_items: number; active_sessions: number }
}

export interface PlaybackStats {
  today: { plays: number; users: number }
  user_ranking: { username: string; plays: number }[]
  item_ranking: { name: string; type: string; plays: number }[]
}

// ==================== v2.4.0 运营管理补全 ====================

/** 用户 360° 详情（GET /api/admin/users/{id}） */
export interface UserDetailProfile {
  id: number
  username: string
  email: string | null
  is_active: boolean
  is_staff: boolean
  emby_username: string | null
  points: number
  last_login_at: string | null
  created_at: string | null
}

export interface UserSubscriptionRow {
  id: number
  plan_name: string
  start_date: string | null
  end_date: string | null
  days_left: number
  status: string
}

export interface UserDetail {
  profile: UserDetailProfile
  subscription: { active: UserSubscriptionRow | null; history: UserSubscriptionRow[] }
  points: {
    balance: number
    income: number
    expense: number
    recent: {
      id: number
      amount: number
      balance_after: number
      type: string
      description: string | null
      created_at: string | null
    }[]
  }
  orders: {
    paid_total: number
    recharge: { order_id: string; item_name: string; amount: number; points: number; status: string; created_at: string | null }[]
    subscription: { order_id: string; item_name: string; amount: number; status: string; created_at: string | null }[]
  }
  invitation: {
    count: number
    rebate_total: number
    invitees: { username: string; reward_points: number; created_at: string | null }[]
  }
  checkin: { total: number; last_date: string | null; streak: number }
  watch: { plays: number; watched_items: number }
}

/** 趋势统计（GET /api/admin/stats/trend） */
export interface TrendPoint {
  date: string
  new_users: number
  plays: number
  revenue: number
  checkins: number
}

export interface TrendStats {
  days: number
  series: TrendPoint[]
  totals: { new_users: number; plays: number; revenue: number; checkins: number }
}

/** 订阅总览（GET /api/admin/realms/{id}/subscriptions，`realm_id=0` = 全部服） */
export interface SubscriptionOverviewRow {
  id: number
  user_id: number
  username: string
  plan_name: string
  /** 会员属于哪个服：一个服一个，多服下必须分开看 */
  realm_id?: number | null
  realm_name?: string
  start_date: string | null
  end_date: string | null
  days_left: number
  status: string
}

export interface SubscriptionOverview {
  summary: { total: number; active: number; expiring_7d: number; expired: number }
  subscriptions: SubscriptionOverviewRow[]
}

/** 按服订阅清单（GET /api/admin/realms/{id}/subscriptions） */
export interface RealmSubscriptionsResponse extends SubscriptionOverview {
  total: number
  /** 本次统计范围：null = 全部服 */
  realm_id: number | null
  realm_name: string
  active_realm_id: number
}

export interface EconomyOverview {
  total_points: number
  checkins_today: number
  orders: { pending: number; revenue: number }
  exchange_codes: { total: number; used: number }
  invitations: number
}

export interface EmbyLibrary {
  id: number
  guid: string
  name: string
  collection_type: string
  /** 归属服与播放节点：多服 / 多机部署下“这个库归谁”一眼可见 */
  realm_id?: number | null
  realm_name?: string
  node_id?: number | null
  node_name?: string
  /** 归属节点最近一次体检是否通过；null = 未体检 */
  node_online?: boolean | null
  paths: string[]
  /** 绑定的存储挂载（storage_mounts.id）：本机目录 / STRM / 115 / WebDAV / AList */
  mount_ids: number[]
  is_enabled: boolean
  is_scanning: boolean
  last_scan_at: string | null
  item_count: number
  /** 刮削策略：missing_only / 3m / 6m / 1y / all */
  scrape_policy?: string
  /** 按发行平台自动生成的虚拟媒体库（无自己的目录） */
  is_virtual?: boolean
  platform?: string | null
  /** 绑定的 115 账号配置档（不同媒体库可用不同账号转存/下载） */
  account_115_id?: number | null
}

/** 存储挂载的类型元数据（后端下发，前端不自己维护一份） */
export interface MountTypeField {
  key: string
  label: string
  placeholder?: string
  secret?: boolean
  required?: boolean
  /** account115 = 渲染成 115 账号下拉；select 配合 options */
  type?: string
  options?: { label: string; value: string }[]
}

export interface MountTypeMeta {
  value: string
  label: string
  kind: 'local' | 'remote'
  /** 图标分组：local / cloud / gateway */
  group?: string
  hint: string
  needs_path: boolean
  /** 是否支持后台目录浏览 */
  browse?: boolean
  /** 「根目录标识」字段名，浏览时点目录会写回它 */
  root_key?: string
  /** 是否可以从远端拉取「已配置的 remote 列表」（rclone） */
  remotes?: boolean
  fields: MountTypeField[]
}

/** 存储挂载：媒体库的内容来源（local / strm / 115 / webdav / alist / s3 / aliyun / quark / onedrive） */
export interface StorageMount {
  id: number
  name: string
  /** 属于哪个服（storage_mounts.realm_id） */
  realm_id?: number | null
  mount_type: string
  mount_type_label: string
  kind: 'local' | 'remote'
  path: string
  /** 已脱敏的配置；secret_keys 里的键永远不出明文 */
  config: Record<string, string>
  secret_keys: string[]
  is_enabled: boolean
  remark: string
  last_checked_at: string | null
  last_check_ok: boolean | null
  last_check_message: string | null
  library_ids: number[]
  /** local / strm 的路径是否存在（远程类型为 null） */
  path_exists: boolean | null
  /** EM（面板进程）能不能用它：等于后台「测试连接」的结果 */
  em_reachable: boolean | null
  em_message: string
  em_checked_at: string | null
  /** EA（分离部署的播放节点）能不能用它；null 表示还没体检过 */
  ea_reachable: boolean | null
  ea_message: string
}

/** 当前真正出流的是谁：EA 分离部署 / 外部 Emby / 面板自己（一体化） */
export type PlaybackNode = 'ea' | 'external' | 'panel'

/** EA 视角挂载体检快照的汇总（逐条结果在 StorageMount 上） */
export interface EaMountHealth {
  ok: boolean
  checked_at: string | null
  error: string
}

export interface MountDirEntry {
  name: string
  rel: string
  is_dir: boolean
  size: number
  /** 提供者眼里的目录标识（115 的 cid）；浏览时可直接选为挂载根目录 */
  entry_id?: string
}

/** 115 账号配置档（Cookie 型，不回传明文） */
export interface Pan115Account {
  id: number
  name: string
  cookie_preview: string
  has_cookie: boolean
  is_default: boolean
  is_enabled: boolean
  remark: string
  last_verified_at: string | null
  last_verify_ok: boolean | null
  last_verify_message: string | null
  created_at: string | null
}

/** 115 转存 / 下载任务 */
export interface Pan115Task {
  id: number
  uid: string
  share_url: string
  share_code: string
  mode: string
  mode_label: string
  target_cid: string
  target_path: string
  account_id: number | null
  library_id: number | null
  status: string
  status_label: string
  total_files: number
  done_files: number
  failed_files: number
  progress: number
  error: string | null
  /** 分享快照条目与下载地址：后端保证永远是数组，绝不为 null */
  items: { fid: string; name: string; is_dir: boolean; size: number; pickcode: string }[]
  urls: string[]
  failed_keys: string[]
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
}

/** 115 目录项（目标路径选择器） */
export interface Pan115DirEntry {
  fid: string
  cid: string
  name: string
  is_dir: boolean
  size: number
  pickcode: string
}

export interface EmbySessionRow {
  session_key: string
  username: string
  item: string
  item_type: string
  device: string
  client: string
  remote_addr: string
  play_method: string
  position_ticks: number
  duration_ticks: number
  is_paused: boolean
  started_at: string | null
}
