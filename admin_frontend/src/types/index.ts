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
  created_at: string
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
