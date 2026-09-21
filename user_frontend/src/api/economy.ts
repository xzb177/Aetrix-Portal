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
  /** 套餐属于哪个服（一个服一个）：买哪份就开哪个服的会员 */
  realm_id?: number | null
  realm_name?: string
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

// ==================== 会员卡码（注册码 / 续期码 / 白名单码） ====================

export interface CodePreview {
  valid: boolean
  kind: 'code' | 'invite' | 'exchange' | 'unknown'
  code_type?: number
  type_name?: string
  days?: number
  days_text?: string
  is_named?: boolean
  target_username?: string | null
  remaining_uses?: number
  message: string
}

export const membershipApi = {
  /** 预检卡码：仅识别类型与天数，不核销（POST 以免卡码进访问日志） */
  preview: (code: string) =>
    api.post<never, CodePreview>('/api/user/membership/redeem/preview', { code }),
  /** 核销卡码：成功后直接开通或叠加会员 */
  redeem: (code: string) =>
    api.post<never, { success: boolean; message: string; code_type?: number; days?: number; end_date?: string }>(
      '/api/user/membership/redeem', { code }),
}

// ==================== 我的设备（第三方播放器登录设备） ====================

export interface MyDevice {
  device_id: string
  name: string | null
  client: string | null
  app_version: string | null
  ip: string | null
  is_blocked: boolean
  first_seen_at: string | null
  last_seen_at: string | null
  is_online_recent: boolean
}

export interface MyDevicesResponse {
  limit: number
  count: number
  active_count: number
  remaining: number | null
  auto_evict: boolean
  active_days: number
  devices: MyDevice[]
}

export const deviceApi = {
  mine: () => api.get<never, MyDevicesResponse>('/api/user/emby/devices'),
  remove: (deviceId: string) =>
    api.delete<never, { success: boolean; message: string }>(
      `/api/user/emby/devices/${encodeURIComponent(deviceId)}`),
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
