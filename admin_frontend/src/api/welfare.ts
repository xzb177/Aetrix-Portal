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

// ==================== 群抽奖活动（G2） ====================
export type LotteryRoundStatus = 'open' | 'drawing' | 'done' | 'cancelled'

export interface LotteryRoundRow {
  id: number
  title: string
  chat_id: string
  status: LotteryRoundStatus
  participant_count: number
  prize_count: number
  draw_at: string | null
  created_at: string | null
}

export interface LotteryRoundPrizeRow {
  id: number
  round_id: number
  name: string
  type: 'days' | 'points' | 'whitelist'
  value: number
  quantity: number
  sort: number
}

export interface LotteryRoundEntryRow {
  id: number
  user_id: number | null
  telegram_id: string | null
  joined_at: string | null
}

export interface LotteryRoundWinnerRow {
  id: number
  prize_id: number
  prize_name: string
  user_id: number | null
  telegram_id: string | null
  distributed: boolean
  distributed_at: string | null
}

export interface LotteryRoundDetail {
  round: Record<string, unknown>
  prizes: LotteryRoundPrizeRow[]
  entries: LotteryRoundEntryRow[]
  winners: LotteryRoundWinnerRow[]
  verify: Record<string, unknown> | null
}

export interface CreateRoundPayload {
  title: string
  chat_id: number
  prizes: Array<{
    name: string
    type: 'days' | 'points' | 'whitelist'
    value: number
    quantity: number
  }>
  draw_at?: string | null
  max_participants?: number | null
}

export const fetchLotteryRounds = (params: { page?: number; page_size?: number; status?: LotteryRoundStatus } = {}) =>
  get<{ total: number; items: LotteryRoundRow[] }>(`${E}/lottery/rounds`, params)

export const createLotteryRound = (data: CreateRoundPayload) =>
  post<Record<string, unknown>>(`${E}/lottery/rounds`, data)

export const fetchLotteryRound = (id: number) =>
  get<LotteryRoundDetail>(`${E}/lottery/rounds/${id}`)

export const drawLotteryRound = (id: number) =>
  post<{ success: boolean; winners: unknown[]; distribute: unknown }>(`${E}/lottery/rounds/${id}/draw`, {})

export const cancelLotteryRound = (id: number) =>
  post<{ success: boolean }>(`${E}/lottery/rounds/${id}/cancel`, {})
