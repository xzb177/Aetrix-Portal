/**
 * RoyalBot Portal 用户端 — API 类型定义
 * 从后端 models.py + schemas/ 逆向生成
 */

// ==================== 通用 ====================

export interface ApiResponse<T = unknown> {
  code?: number
  message?: string
  data: T
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  skip: number
  limit: number
}

// ==================== 认证 ====================

export interface User {
  id: number
  username: string
  email?: string
  telegram_id?: number
  is_active: boolean
  is_staff: boolean
  points: number
  balance: number          // 充值余额（单位：分）
  completed_requests_count: number
  total_requests_count: number
  created_at: string
  updated_at: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
  email?: string
  invitation_code?: string
}

// ==================== 订阅 ====================

export interface SubscriptionPlan {
  id: number
  name: string
  description?: string
  price: number            // 价格（元）
  duration_days: number
  features?: string        // JSON
  is_active: boolean
  is_popular: boolean
  sort_order: number
}

export interface UserSubscription {
  id: number
  plan_id: number
  plan: SubscriptionPlan
  start_date: string
  end_date: string
  status: 'active' | 'expired' | 'cancelled'
  auto_renew: boolean
  created_at: string
}

export interface SubscriptionOrder {
  id: number
  order_id: string
  plan_id: number
  plan_name: string
  amount: number           // 金额（元）
  status: 'pending' | 'paid' | 'cancelled' | 'refunded'
  payment_method?: string
  created_at: string
  paid_at?: string
}

// ==================== Emby ====================

export interface EmbyAccount {
  id: number
  server_id: number
  server_name: string
  server_url: string
  username: string
  password: string
  is_active: boolean
  expires_at?: string
  created_at: string
}

export interface EmbyServer {
  id: number
  name: string
  url: string
  is_active: boolean
  current_users: number
  max_users: number
}

// ==================== 工单 ====================

export interface Ticket {
  id: number
  title: string
  category: 'technical' | 'billing' | 'feature' | 'other'
  priority: 'low' | 'medium' | 'high' | 'urgent'
  status: 'open' | 'replied' | 'resolved' | 'closed'
  created_at: string
  updated_at: string
}

export interface TicketMessage {
  id: number
  message: string
  attachments?: string[]
  is_admin: boolean
  created_at: string
}

export interface TicketDetail extends Ticket {
  messages: TicketMessage[]
}

export interface CreateTicketRequest {
  title: string
  category?: string
  priority?: string
  message: string
  attachments?: string[]
}

// ==================== 求片 ====================

export interface MovieRequest {
  id: number
  movie_name: string
  year?: string
  type: 'movie' | 'series' | 'anime' | 'documentary' | 'other'
  note?: string
  status: 'pending' | 'approved' | 'rejected' | 'completed'
  priority: number
  admin_note?: string
  tmdb_id?: number
  tmdb_poster?: string
  created_at: string
}

// ==================== 兑换码 ====================

export interface ExchangeCodeUse {
  code: string
}

export interface ExchangeCodeRecord {
  id: number
  code_type: number
  code_display: string
  effect?: Record<string, unknown>
  description?: string
  created_at: string
}

// ==================== 邀请 ====================

export interface InvitationCode {
  id: number
  code: string
  use_count: number
  created_at: string
}

export interface InvitationRecord {
  id: number
  inviter_id: number
  invitee_id: number
  code: string
  reward_points: number
  conversion_status: 'registered' | 'paid' | 'subscribed'
  created_at: string
}

// ==================== 消息 ====================

export interface Message {
  id: number
  title: string
  content: string
  message_type: 'system' | 'ticket' | 'announcement' | 'subscription' | 'media_seek' | 'exchange_code'
  related_id?: number
  is_read: boolean
  from_user?: string
  created_at: string
  read_at?: string
}

// ==================== 公告 ====================

export interface Announcement {
  id: number
  title: string
  content: string
  type: 'system' | 'activity' | 'urgent'
  priority_level: number  // P0=强制弹窗, P1=置顶, P2=普通
  is_active: boolean
  start_at?: string
  end_at?: string
  created_at: string
}

// ==================== 充值 ====================

export interface RechargePackage {
  id: number
  name: string
  amount: number           // 充值金额（分）
  price: number            // 支付价格（元）
  bonus?: number           // 赠送金额（分）
  is_active: boolean
}

export interface BalanceTransaction {
  id: number
  amount: number
  balance_before: number
  balance_after: number
  transaction_type: 'recharge' | 'exchange' | 'payment' | 'admin_adjust' | 'refund'
  source_type?: string
  description?: string
  created_at: string
}

// ==================== 线路 ====================

export interface Route {
  id: number
  name: string
  description?: string
  server_ids: number[]
  is_active: boolean
}

// ==================== 徽章 ====================

export interface Badge {
  id: number
  name: string
  description: string
  icon: string
  earned: boolean
  earned_at?: string
}
