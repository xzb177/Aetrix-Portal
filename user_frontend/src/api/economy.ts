/**
 * 经济系统与邀请返利 API（backend/api/economy.py + invitation.py）
 */
import api from './index'

// ==================== 类型 ====================

export interface CheckinStatus {
  enabled: boolean
  checked_today: boolean
  streak: number
  base_points: number
  streak_bonus: number
  streak_max_bonus: number
  points: number
}

export interface PointsLogEntry {
  id: number
  amount: number
  balance_after: number
  type: string
  description: string | null
  ref_id: string | null
  created_at: string | null
}

export interface PointsLogResponse {
  total: number
  balance: number
  logs: PointsLogEntry[]
}

export interface RechargePackage {
  id: number
  name: string
  amount: number
  bonus: number
  price: number
  is_popular: boolean
  total_points: number
}

export interface SubscriptionPlan {
  id: number
  name: string
  description: string | null
  price: number
  duration_days: number
  features: string[] | null
  is_popular: boolean
}

export interface PaymentMethod {
  id: string
  name: string
  enabled: boolean
}

export interface OrderRow {
  order_id: string
  kind: 'recharge' | 'subscription'
  item_name: string
  amount: number
  status: string
  created_at: string | null
  paid_at: string | null
}

export interface MyInviteInfo {
  code: string
  use_count: number
  max_uses: number
  invited_count: number
  config: {
    enabled: boolean
    reward_points: number
    invitee_reward_points: number
    rebate_percent: number
  }
}

export interface InvitationRecordRow {
  id: number
  invitee_username: string
  reward_points: number
  created_at: string | null
}

export interface RebateRow {
  id: number
  amount: number
  description: string | null
  ref_id: string | null
  created_at: string | null
}

// ==================== 签到 ====================

export const checkinApi = {
  status: () => api.get<never, CheckinStatus>('/api/user/economy/checkin/status'),
  doCheckin: () => api.post<never, { success: boolean; points_awarded: number; streak: number; balance: number; message: string }>('/api/user/economy/checkin'),
}

// ==================== 积分 ====================

export const pointsApi = {
  log: (params?: { limit?: number; offset?: number; type_filter?: string }) =>
    api.get<never, PointsLogResponse>('/api/user/economy/points/log', { params }),
}

// ==================== 兑换码 ====================

export const exchangeApi = {
  /** 兑换规则与开关（关闭时用户端隐藏核销入口，避免提交后报错） */
  config: () =>
    api.get<never, { enabled: boolean; invitee_note?: string }>('/api/user/economy/exchange/config'),
  redeem: (code: string) =>
    api.post<never, { success: boolean; reward_type?: string; points?: number; balance?: number; plan_name?: string; days?: number; message: string }>('/api/user/economy/exchange/redeem', { code }),
}

// ==================== 支付 ====================

export const paymentApi = {
  methods: () => api.get<never, PaymentMethod[]>('/api/user/economy/payment/methods'),
  packages: () => api.get<never, { enabled: boolean; packages: RechargePackage[] }>('/api/user/economy/payment/packages'),
  plans: () => api.get<never, { enabled: boolean; plans: SubscriptionPlan[] }>('/api/user/economy/payment/plans'),
  createOrder: (data: { kind: 'recharge' | 'subscription'; item_id: number; payment_method: string }) =>
    api.post<never, { success: boolean; order_id: string; amount: number; pay_url: string; message: string }>('/api/user/economy/payment/order', data),
  orders: (params?: { kind?: string; limit?: number }) =>
    api.get<never, { orders: OrderRow[] }>('/api/user/economy/payment/orders', { params }),
}

// ==================== 邀请返利 ====================

export const inviteApi = {
  config: () => api.get<never, MyInviteInfo['config']>('/api/user/invite/config'),
  myCode: () => api.get<never, MyInviteInfo>('/api/user/invite/my-code'),
  records: (params?: { limit?: number }) =>
    api.get<never, { total: number; records: InvitationRecordRow[] }>('/api/user/invite/records', { params }),
  rebates: (params?: { limit?: number }) =>
    api.get<never, { total_rebate: number; rebates: RebateRow[] }>('/api/user/invite/rebates', { params }),
}
