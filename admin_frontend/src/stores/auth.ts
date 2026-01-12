import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { AdminInfo } from '@/types/auth'

/**
 * 认证 Store - 使用 httpOnly Cookie 安全存储 Token
 *
 * 安全改进:
 * - Token 存储在 httpOnly cookie 中 (后端设置，前端无法访问)
 * - 只有 CSRF token 存储在 sessionStorage 中 (仅用于读取)
 * - 管理员信息存储在 sessionStorage 中 (页面刷新时恢复)
 */
export const useAuthStore = defineStore('auth', () => {
  // 状态 - 不再存储敏感的 access_token
  const adminInfo = ref<AdminInfo | null>(null)
  const csrfToken = ref<string | null>(null)
  const isAuthenticated = ref<boolean>(false)

  // 初始化时从 sessionStorage 恢复状态
  const restoreState = () => {
    try {
      const savedInfo = sessionStorage.getItem('admin_info')
      const savedCsrf = sessionStorage.getItem('admin_csrf')

      if (savedInfo) {
        adminInfo.value = JSON.parse(savedInfo)
        isAuthenticated.value = true
      }
      if (savedCsrf) {
        csrfToken.value = savedCsrf
      }
    } catch (e) {
      console.error('Failed to restore auth state:', e)
      // 清除损坏的数据
      sessionStorage.removeItem('admin_info')
      sessionStorage.removeItem('admin_csrf')
    }
  }

  // 设置管理员信息和 CSRF token (登录成功后调用)
  const setAdminInfo = (info: AdminInfo, csrf?: string) => {
    adminInfo.value = info
    isAuthenticated.value = true

    // 将 CSRF token 存储到 sessionStorage (仅用于请求时读取)
    if (csrf) {
      csrfToken.value = csrf
      sessionStorage.setItem('admin_csrf', csrf)
    }

    // 将 adminInfo 存储到 sessionStorage (页面刷新时恢复)
    sessionStorage.setItem('admin_info', JSON.stringify(info))
  }

  // 登出
  const logout = () => {
    adminInfo.value = null
    csrfToken.value = null
    isAuthenticated.value = false

    // 清除 sessionStorage
    sessionStorage.removeItem('admin_info')
    sessionStorage.removeItem('admin_csrf')
  }

  // 获取 CSRF token (用于请求 header)
  const getCsrfToken = (): string => {
    return csrfToken.value || sessionStorage.getItem('admin_csrf') || ''
  }

  // 检查权限
  const hasPermission = (permission: string): boolean => {
    // 如果没有管理员信息，默认允许
    if (!adminInfo.value) return true
    // 如果是超级管理员，允许所有权限
    if (adminInfo.value.role === 'super_admin') return true
    // 如果权限列表为空，默认允许
    if (!adminInfo.value.permissions || adminInfo.value.permissions.length === 0) return true
    // 检查是否有指定权限
    return adminInfo.value.permissions.includes(permission)
  }

  // 检查是否是超级管理员
  const isSuperAdmin = (): boolean => {
    return adminInfo.value?.role === 'super_admin' || false
  }

  // 初始化时恢复状态
  restoreState()

  return {
    adminInfo,
    csrfToken,
    isAuthenticated,
    setAdminInfo,
    restoreState,
    logout,
    hasPermission,
    isSuperAdmin,
    getCsrfToken,
  }
})
