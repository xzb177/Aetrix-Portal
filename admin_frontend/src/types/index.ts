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
  /** 这张卡码开通哪个服的会员（一个服一个） */
  realm_id?: number | null
  realm_name?: string
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
  /** 统计范围：当前服的名称，或「全部服」 */
  realm_id?: number | null
  realm_name?: string
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
  /** IP 归属地（能力：IP 与地理位置）；未配置提供方时为空串 */
  region: string
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
  /** 这部片是给哪个服求的（用户提交时选/单服自动带出）；空 = 未标注 */
  realm_id?: number | null
  realm_name?: string
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
  /** 接入方式（v2.7.0）：paid = 付费服（需要订阅）/ free = 公益服（免费开放） */
  access_mode: 'paid' | 'free'
  /** 是不是公益服（= access_mode === 'free'，前后端同一口径） */
  is_free: boolean
  /** 公益服规则文案（用户端展示；付费服为空串） */
  access_note: string
  /** 下载策略：null = 跟随全局（公益服默认禁止）/ true = 允许 / false = 禁止 */
  allow_download: boolean | null
  /** 用户端该连的地址（服自己的地址 → 该服 Emby 入口 → 全局环境变量） */
  public_url: string
  nodes: RealmNode[]
  stats: RealmStats
  created_at: string | null
}

export interface RealmSummary {
  total_realms: number
  enabled_realms: number
  /** 公益服 / 付费服的服数（面板顶部与概览页展示） */
  free_realms: number
  paid_realms: number
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
    /** 接入方式（v2.7.0）：free = 公益服（免费开放） */
    access_mode: 'paid' | 'free'
    is_free: boolean
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

/** EA 自称的身份（`live` 模式下真去问那台 EA：你是谁、属于哪个服、负责哪些库） */
export interface ServerOverviewIdentity {
  ok: boolean
  error?: string
  claimed?: boolean
  node_key?: string
  node_name?: string
  realm_slug?: string
  realm_name?: string
  libraries?: number
  /** 这台进程是否真的在按服 / 节点过滤内容 */
  filtering?: boolean
}

/** EA 视角的挂载体检（按服保存）：挂载里的本机路径是主机相对的，只有那台机器说了算 */
export interface ServerOverviewMounts {
  ok: boolean
  checked_at: string | null
  error: string
  total: number
  failed_count: number
  unreachable: string[]
  /** 从没查过（不是错误，但面板要提示「还不知道」） */
  never_checked: boolean
}

/** Emby 总览的一行 = 一台出流入口（EA / 已有 Emby） */
export interface ServerOverviewRow extends RemoteServerRow {
  realm_slug: string
  realm_is_default: boolean
  is_entry: boolean
  is_current_entry: boolean
  identity: ServerOverviewIdentity
  mounts: ServerOverviewMounts | null
  /** 归这台节点扫描 / 出流的媒体库数 */
  libraries_assigned: number
  /** 同服里还没分配给任何节点的库数（未分配 = 所有节点可见、由面板扫描） */
  libraries_unassigned: number
  warnings: string[]
}

/** 总览里的一张服卡片：这个服到底用哪个入口出流、库归谁 */
export interface ServerOverviewRealm {
  id: number
  name: string
  slug: string
  url: string
  description: string
  is_active: boolean
  is_default: boolean
  public_url: string
  sort_order: number
  entry: {
    mode: string
    label: string
    url: string
    server_id: number | null
    server_name: string
  }
  libraries: { total: number; unassigned: number; by_node: Record<string, number> }
  mounts: ServerOverviewMounts
  warnings: string[]
}

/** Emby 总览（`/api/admin/servers/overview`）：一行一台入口，把散在各页的事实汇到一起 */
export interface ServerOverview {
  /** null / 0 = 全部服；数字 = 只看这个服 */
  realm_id: number | null
  active_realm_id: number
  live: boolean
  realms: ServerOverviewRealm[]
  rows: ServerOverviewRow[]
  totals: {
    entry: number
    online: number
    warnings: number
    libraries: number
    libraries_unassigned: number
  }
  summary: ServerSummary
  kinds: ServerKindMeta[]
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
  /** 最近一次扫描的结果（null = 从未扫描过）；见后端 scan_result_payload */
  last_scan?: EmbyScanResult | null
  item_count: number
  /** 刮削策略：missing_only / 3m / 6m / 1y / all */
  scrape_policy?: string
  /** 按发行平台自动生成的虚拟媒体库（无自己的目录） */
  is_virtual?: boolean
  platform?: string | null
  /** 绑定的 115 账号配置档（不填则回退默认账号 / 服务器级 PAN115_COOKIE） */
  account_115_id?: number | null
}

/**
 * 一条扫描来源的明细：这条来源扫到了多少文件、这批文件的处理结果
 *
 * 「挂载配好了、目录也在，但里面一条文件都没有」（挂载点被清空 / 账号范围变了 / 路径写错
 * 但目录恰好存在）只看总体统计是完全看不出来的——那是所有来源加在一起的结果。
 */
export interface EmbyScanSource {
  /** 来源标签：本机路径，或「挂载名（类型）」 */
  label: string
  /** unavailable = 这条来源读不到（同时也计进 failed_roots）；缺省 = 正常参与了这一轮 */
  kind?: string
  /** 这条来源自己的失败原因（读不到 / 遍历中途出错） */
  error?: string
  /** 这条来源里**发现**的媒体文件数（增量扫描跳过未变化的文件也算，不是写库条数） */
  files: number
  added: number
  updated: number
  probed: number
  scraped: number
  repaired: number
  unchanged: number
}

/** 一轮扫描的统计：最近一次与扫描流水共用同一份字段（后端 _scan_metrics） */
export interface EmbyScanMetrics {
  added: number
  updated: number
  removed: number
  probed: number
  scraped: number
  repaired: number
  /** 增量扫描跳过的未变化条目数 */
  unchanged: number
  /** 来源不完整，本轮跳过了「清理已删除条目」 */
  removal_skipped: boolean
  /** 读不到的来源（路径 / 挂载 + 原因） */
  failed_roots: string[]
  /** 按来源拆分的明细（顺序 = 媒体库里的配置顺序；虚拟库为空数组） */
  sources: EmbyScanSource[]
}

/** 扫描状态：running = 正在跑；success = 跑完且来源都正常；partial = 有来源读不到（已跳过清理）；failed = 异常中断 */
export type EmbyScanStatus = 'running' | 'success' | 'partial' | 'failed'

/** 媒体库最近一次扫描的结果：管理端刷新后仍然可查（不用去翻服务器日志） */
export interface EmbyScanResult extends EmbyScanMetrics {
  status: EmbyScanStatus
  finished_at: string | null
  duration_ms: number | null
  /** 失败原因摘要（仅 partial / failed 时有值） */
  error: string | null
}

/** 一条扫描流水（最近若干轮）：「这个库每轮都失败」和「只是最近一轮失败」是两件事 */
export interface EmbyScanRun extends EmbyScanMetrics {
  id: number
  status: EmbyScanStatus
  /** 谁触发的：manual（面板）/ client（客户端刷新）/ node（归属节点）/ repair（修复队列） */
  trigger: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  error: string | null
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
  /** 属于哪个服（storage_mounts.realm_id）；空 = 未标注（所有服都看得到） */
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
