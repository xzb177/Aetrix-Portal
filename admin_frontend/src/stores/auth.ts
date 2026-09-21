import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { AdminInfo } from '@/types/auth'

/**
 * 管理端认证状态。
 * 真实会话由后端 httpOnly Cookie 维护；sessionStorage 仅保存展示信息，
 * 不能单独作为认证依据。进入后台时必须由 /api/auth/me 校验会话。
 */
export const useAuthStore = defineStore('auth', () => {
  const adminInfo = ref<AdminInfo | null>(null)
  const csrfToken = ref<string | null>(null)
  const isAuthenticated = ref(false)

  const restoreState = () => {
    try {
      const savedInfo = sessionStorage.getItem('admin_info')
      const savedCsrf = sessionStorage.getItem('admin_csrf')
      adminInfo.value = savedInfo ? JSON.parse(savedInfo) as AdminInfo : null
      csrfToken.value = savedCsrf
      // 这里只恢复 UI 状态；路由/接口仍必须由后端确认 Cookie 会话。
      isAuthenticated.value = !!adminInfo.value
    } catch (error) {
      console.error('Failed to restore auth state:', error)
      adminInfo.value = null
      csrfToken.value = null
      isAuthenticated.value = false
      sessionStorage.removeItem('admin_info')
      sessionStorage.removeItem('admin_csrf')
    }
  }

  const setAdminInfo = (info: AdminInfo, csrf?: string) => {
    adminInfo.value = info
    isAuthenticated.value = true
    if (csrf) {
      csrfToken.value = csrf
      sessionStorage.setItem('admin_csrf', csrf)
    }
    sessionStorage.setItem('admin_info', JSON.stringify(info))
  }

  const logout = () => {
    adminInfo.value = null
    csrfToken.value = null
    isAuthenticated.value = false
    sessionStorage.removeItem('admin_info')
    sessionStorage.removeItem('admin_csrf')
  }

  const getCsrfToken = (): string => csrfToken.value || sessionStorage.getItem('admin_csrf') || ''

  const hasPermission = (permission: string): boolean => {
    if (!adminInfo.value) return false
    if (adminInfo.value.role === 'super_admin') return true
    return Array.isArray(adminInfo.value.permissions) && adminInfo.value.permissions.includes(permission)
  }

  const isSuperAdmin = (): boolean => adminInfo.value?.role === 'super_admin' || false

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
