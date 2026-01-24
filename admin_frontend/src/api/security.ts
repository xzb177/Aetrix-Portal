import { http } from '@/utils/request'

// 获取登录历史
export const getLoginHistory = (params?: { page?: number; page_size?: number }) => {
  return http.get('/auth/login-history', { params })
}

// 获取活跃会话
export const getActiveSessions = () => {
  return http.get('/auth/sessions')
}

// 撤销会话
export const revokeSession = (sessionId: string) => {
  return http.delete(`/auth/sessions/${sessionId}`)
}

// 撤销所有其他会话
export const revokeAllOtherSessions = () => {
  return http.post('/auth/sessions/revoke-others')
}

// 获取安全设置
export const getSecuritySettings = () => {
  return http.get('/auth/security-settings')
}

// 更新安全设置
export const updateSecuritySettings = (data: {
  enable_login_alert?: boolean
  enable_2fa?: boolean
  trusted_ips?: string[]
}) => {
  return http.put('/auth/security-settings', data)
}

// 获取安全统计
export const getSecurityStats = () => {
  return http.get('/auth/security-stats')
}

// 获取系统配置
export const getSystemConfig = () => {
  return http.get('/system/config')
}

// 更新系统配置
export const updateSystemConfig = (data: {
  site_name?: string
  allow_registration?: boolean
  default_vip_days?: number
}) => {
  return http.put('/system/config', data)
}

// 密码强度检查
export const checkPasswordStrength = (password: string) => {
  return http.post('/auth/check-password-strength', { password })
}

// 修改密码
export const changePassword = (data: {
  old_password: string
  new_password: string
  confirm_password: string
}) => {
  return http.post('/auth/change-password', data)
}
