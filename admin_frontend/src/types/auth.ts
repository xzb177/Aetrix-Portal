// 认证相关类型
export interface AdminInfo {
  id: number
  username: string
  role: string
  role_display: string
  permissions: string[]
  is_active: boolean
  last_login: string | null
}

export interface LoginForm {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  admin_info: AdminInfo
}
