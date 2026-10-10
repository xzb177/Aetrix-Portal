/**
 * Telegram 绑定 API（backend/api/tg_bind.py）
 */
import api from './index'

export interface TgBindStatus {
  bound: boolean
  telegram_id: number | null
  required: boolean
  guide_enabled: boolean
  in_grace: boolean
  bot_username: string
}

export interface TgBindCodeResp {
  success: boolean
  code: string
  expires_in: number
  bot_username: string
}

export const tgApi = {
  status: () => api.get<never, TgBindStatus>('/api/user/telegram/status'),
  bindCode: () => api.post<never, TgBindCodeResp>('/api/user/telegram/bind-code'),
  verify: () => api.post<never, { success: boolean; telegram_id?: number; message?: string; code_expired?: boolean }>('/api/user/telegram/verify'),
  unbind: () => api.delete<never, { success: boolean }>('/api/user/telegram/unbind'),
}
