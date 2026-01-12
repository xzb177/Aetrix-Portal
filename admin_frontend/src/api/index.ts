import { http } from '@/utils/request'

// 登录
export const login = (data: { username: string; password: string }) => {
  return http.post('/auth/login', data)
}

// 获取当前管理员信息
export const getCurrentAdmin = () => {
  return http.get('/auth/me')
}

// 修改密码
export const changePassword = (data: { old_password: string; new_password: string }) => {
  return http.post('/auth/change-password', data)
}

// 登出
export const logout = () => {
  return http.post('/auth/logout')
}
