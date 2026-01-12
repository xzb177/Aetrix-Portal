import { http } from '@/utils/request'
import type { User, UserDetail, UserStats, PaginatedResponse } from '@/types/user'

// 获取用户列表
export const getUsers = (params: {
  page: number
  page_size: number
  keyword?: string
  is_vip?: boolean
  has_emby?: boolean
  sort_by?: string
  sort_order?: string
}) => {
  return http.get<PaginatedResponse<User>>('/users', { params })
}

// 获取用户详情
export const getUserDetail = (userId: number) => {
  return http.get<UserDetail>(`/users/${userId}`)
}

// 更新用户信息
export const updateUser = (userId: number, data: Partial<User>) => {
  return http.put(`/users/${userId}`, data)
}

// 切换 VIP 状态
export const toggleVIP = (userId: number) => {
  return http.post(`/users/${userId}/vip`)
}

// 获取用户统计
export const getUserStats = () => {
  return http.get<UserStats>('/users/stats/overview')
}

// 删除用户
export const deleteUser = (userId: number) => {
  return http.delete(`/users/${userId}`)
}
