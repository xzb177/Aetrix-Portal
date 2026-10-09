/** 公益服管理后台 API（全部走 /api/admin/welfare/*） */
import { get, post, put, del } from '@/utils/request'

const E = '/welfare'

// ==================== 公益用户操作（v2.55 用户列表已并入用户管理，列表接口停用） ====================

export const grantWelfare = (data: { user_id: number; days: number; channel?: string }) =>
  post<{ success: boolean; expires_at: string | null }>(`${E}/grant`, data)

export const revokeWelfare = (user_id: number) =>
  post<{ success: boolean }>(`${E}/revoke`, { user_id })

export const bulkExtendWelfare = (data: { min_expired_days: number; max_expired_days: number; add_days: number }) =>
  post<{ success: boolean; affected: number }>(`${E}/bulk-extend`, data)

// ==================== 抽奖 ====================
// 注：求片审核已并入「求片管理」（MediaSeek.vue），welfare.ts 不再保留求片 API。

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
