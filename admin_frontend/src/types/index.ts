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

export interface RegistrationCode {
  id: number
  code: string
  max_uses: number
  use_count: number
  is_active: boolean
  note: string | null
  expires_at: string | null
  used_by: { id: number; username: string }[]
  created_at: string
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

/** 订阅总览（GET /api/admin/economy/subscriptions） */
export interface SubscriptionOverviewRow {
  id: number
  user_id: number
  username: string
  plan_name: string
  start_date: string | null
  end_date: string | null
  days_left: number
  status: string
}

export interface SubscriptionOverview {
  summary: { total: number; active: number; expiring_7d: number; expired: number }
  subscriptions: SubscriptionOverviewRow[]
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
  paths: string[]
  is_enabled: boolean
  is_scanning: boolean
  last_scan_at: string | null
  item_count: number
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
