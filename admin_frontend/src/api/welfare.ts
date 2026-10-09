/** 公益服管理后台 API（全部走 /api/admin/welfare/*） */
import { get, post, put, del } from '@/utils/request'

const E = '/welfare'

// ==================== 公益用户 ====================

export interface WelfareUserRow {
  id: number
  username: string
  is_welfare: boolean
  welfare_expires_at: string | null
  days_left: number | null
  welfare_grant_channel: string | null
}

export const fetchWelfareUsers = (params: { page?: number; page_size?: number; keyword?: string; only_welfare?: boolean } = {}) =>
  get<{ total: number; items: WelfareUserRow[] }>(`${E}/users`, params)

export const grantWelfare = (data: { user_id: number; days: number; channel?: string }) =>
  post<{ success: boolean; expires_at: string | null }>(`${E}/grant`, data)

export const revokeWelfare = (user_id: number) =>
  post<{ success: boolean }>(`${E}/revoke`, { user_id })

export const bulkExtendWelfare = (data: { min_expired_days: number; max_expired_days: number; add_days: number }) =>
  post<{ success: boolean; affected: number }>(`${E}/bulk-extend`, data)

// ==================== 求片审核 ====================

export interface WelfareRequestRow {
  id: number
  title: string
  media_type: string
  tmdb_id: string
  username: string
  status: string
  admin_note: string
  created_at: string
}

export const fetchWelfareRequests = (params: { page?: number; page_size?: number; status?: string } = {}) =>
  get<{ total: number; items: WelfareRequestRow[] }>(`${E}/requests`, params)

export const approveWelfareRequest = (id: number, admin_note: string) =>
  post(`${E}/requests/${id}/approve`, { admin_note })

export const rejectWelfareRequest = (id: number, admin_note: string) =>
  post(`${E}/requests/${id}/reject`, { admin_note })

export const doneWelfareRequest = (id: number) =>
  post(`${E}/requests/${id}/done`, {})

// ==================== 抽奖 ====================

export interface LotteryPrizeRow {
  id: number
  name: string
  type: string
  value: number
  probability: number
  enabled: boolean
}

export interface LotteryLogRow {
  id: number
  username: string
  prize_name: string
  created_at: string
}

export const fetchLotteryPrizes = () =>
  get<LotteryPrizeRow[]>(`${E}/lottery/prizes`)

export const createLotteryPrize = (data: { name: string; type: string; value: number; probability: number; enabled: boolean }) =>
  post<LotteryPrizeRow>(`${E}/lottery/prizes`, data)

export const updateLotteryPrize = (id: number, data: Partial<{ name: string; type: string; value: number; probability: number; enabled: boolean }>) =>
  put<LotteryPrizeRow>(`${E}/lottery/prizes/${id}`, data)

export const deleteLotteryPrize = (id: number) =>
  del<{ success: boolean }>(`${E}/lottery/prizes/${id}`)

export const fetchLotteryLogs = (params: { page?: number; page_size?: number } = {}) =>
  get<{ total: number; items: LotteryLogRow[] }>(`${E}/lottery/logs`, params)

// ==================== 配置 ====================

export const fetchWelfareConfig = () =>
  get<Record<string, string>>(`${E}/config`)

export const saveWelfareConfig = (data: Record<string, string>) =>
  put<{ success: boolean; updated: string[] }>(`${E}/config`, data)
