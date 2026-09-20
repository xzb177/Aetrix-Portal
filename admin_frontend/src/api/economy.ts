/** v2.3.0 经济系统管理 API（/api/admin/economy/*，详见 backend/api/admin.py） */
import { get, post, put, del } from '@/utils/request'
import type { SubscriptionOverview } from '@/types'

// ==================== 类型 ====================

export interface EconomyStats {
  total_points: number
  checkins_today: number
  orders: { pending: number; revenue: number }
  exchange_codes: { total: number; used: number }
  invitations: number
}

export interface PlanRowFull {
  id: number
  name: string
  description: string | null
  price: number
  duration_days: number
  features: string[] | null
  is_active: boolean
  is_popular: boolean
  sort_order: number
}

export interface PackageRow {
  id: number
  name: string
  amount: number
  price: number
  bonus: number
  is_active: boolean
  is_popular: boolean
  sort_order: number
}

export interface ExchangeCodeRow {
  id: number
  code: string
  type: 'points' | 'subscription'
  points_value: number
  plan_name: string | null
  duration_days: number
  max_uses: number
  use_count: number
  is_active: boolean
  note: string | null
  expires_at: string | null
  used_by: { id: number; username: string }[]
  created_at: string
}

export interface OrderRow {
  order_id: string
  kind: 'recharge' | 'subscription'
  item_name: string
  username: string
  user_id: number
  amount: number
  status: string
  payment_method: string | null
  created_at: string | null
  paid_at: string | null
}

export interface InvitationRow {
  id: number
  inviter: string
  invitee: string
  reward_points: number
  created_at: string | null
}

export interface PointsLogRow {
  id: number
  user_id: number
  username: string
  amount: number
  balance_after: number
  type: string
  description: string | null
  ref_id: string | null
  created_at: string | null
}

export interface EconomySettings {
  [key: string]: string
}

// ==================== 统计 ====================

export const fetchEconomyStats = () => get<EconomyStats>('/economy/stats')

// ==================== 订阅总览 ====================

export const fetchSubscriptions = (params: { status_filter?: string; search?: string; limit?: number } = {}) =>
  get<SubscriptionOverview>('/economy/subscriptions', params)

/** 按用户直接授予订阅（与用户管理页共享后端逻辑） */
export const grantUserSubscription = (userId: number, data: { plan_id: number; duration_days: number }) =>
  post<{ success: boolean }>(`/users/${userId}/subscriptions`, data)

export const extendUserSubscription = (subscriptionId: number, days: number) =>
  post<{ success: boolean }>(`/subscriptions/${subscriptionId}/extend`, { days })

// ==================== 订阅套餐 ====================

export const fetchEconomyPlans = () => get<{ plans: PlanRowFull[] }>('/economy/plans')

export const createEconomyPlan = (data: Omit<PlanRowFull, 'id'>) => post<{ success: boolean }>('/economy/plans', data)

export const updateEconomyPlan = (id: number, data: Omit<PlanRowFull, 'id'>) =>
  put<{ success: boolean }>(`/economy/plans/${id}`, data)

export const deleteEconomyPlan = (id: number) => del<{ success: boolean; message?: string }>(`/economy/plans/${id}`)

// ==================== 充值套餐 ====================

export const fetchEconomyPackages = () => get<{ packages: PackageRow[] }>('/economy/packages')

export const createEconomyPackage = (data: Omit<PackageRow, 'id'>) =>
  post<{ success: boolean }>('/economy/packages', data)

export const updateEconomyPackage = (id: number, data: Omit<PackageRow, 'id'>) =>
  put<{ success: boolean }>(`/economy/packages/${id}`, data)

export const deleteEconomyPackage = (id: number) =>
  del<{ success: boolean; message?: string }>(`/economy/packages/${id}`)

// ==================== 兑换码 ====================

export const fetchExchangeCodes = (params: { limit?: number } = {}) =>
  get<{ codes: ExchangeCodeRow[] }>('/economy/exchange-codes', params)

export const createExchangeCodes = (data: {
  count: number
  type: 'points' | 'subscription'
  points_value?: number
  plan_id?: number
  duration_days?: number
  max_uses?: number
  expires_days?: number
  note?: string
}) => post<{ success: boolean; codes: { id: number; code: string; type: string }[] }>('/economy/exchange-codes', data)

export const updateExchangeCode = (id: number, is_active: boolean) =>
  put<{ success: boolean }>(`/economy/exchange-codes/${id}`, { is_active })

// ==================== 订单 ====================

export const fetchEconomyOrders = (params: {
  status_filter?: string
  kind?: string
  search?: string
  limit?: number
  offset?: number
} = {}) => get<{ total: number; orders: OrderRow[] }>('/economy/orders', params)

export const markOrderPaid = (orderId: string) =>
  post<{ success: boolean }>(`/economy/orders/${orderId}/mark-paid`)

// ==================== 邀请与积分 ====================

export const fetchInvitations = (params: { limit?: number } = {}) =>
  get<{ records: InvitationRow[] }>('/economy/invitations', params)

export const fetchPointsLogs = (params: { user_id?: number; type_filter?: string; limit?: number; offset?: number } = {}) =>
  get<{ total: number; logs: PointsLogRow[] }>('/economy/points-logs', params)

export const adjustUserPoints = (userId: number, data: { amount: number; reason?: string }) =>
  post<{ success: boolean; balance: number }>(`/economy/users/${userId}/points`, data)

// ==================== 经济设置 ====================

export const fetchEconomySettings = () => get<{ settings: EconomySettings }>('/economy/settings')

export const updateEconomySettings = (settings: EconomySettings) =>
  put<{ success: boolean; changed: string[] }>('/economy/settings', { settings })
