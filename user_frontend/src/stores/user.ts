import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'

export interface User {
  id: number
  username: string
  email?: string
  is_vip: boolean
  emby_account?: string
  points?: number
  telegram_id?: number
  avatar_url?: string
}

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => !!token.value)
  const isVIP = computed(() => user.value?.is_vip ?? false)

  // 初始化 - 从 localStorage 恢复
  function init() {
    const savedToken = localStorage.getItem('access_token')
    const savedUser = localStorage.getItem('user')
    if (savedToken) {
      token.value = savedToken
    }
    if (savedUser) {
      try {
        user.value = JSON.parse(savedUser)
      } catch {
        localStorage.removeItem('user')
      }
    }
  }

  // 登录
  async function login(username: string, password: string) {
    loading.value = true
    try {
      const response = await authApi.login({ username, password }) as unknown as { access_token: string; user: User }
      token.value = response.access_token
      user.value = response.user

      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('user', JSON.stringify(response.user))
      return true
    } catch (error) {
      console.error('Login failed:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 注册
  async function register(username: string, password: string, email?: string, inviteCode?: string) {
    loading.value = true
    try {
      const response = await authApi.register({ username, password, email, invitation_code: inviteCode }) as unknown as { access_token: string; user: User }
      token.value = response.access_token
      user.value = response.user

      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('user', JSON.stringify(response.user))
      return true
    } catch (error) {
      console.error('Register failed:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // Telegram 登录回调
  async function telegramCallback(queryString: string) {
    loading.value = true
    try {
      const response = await authApi.telegramCallback({ query_string: queryString }) as unknown as { access_token: string; user: User }
      token.value = response.access_token
      user.value = response.user

      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('user', JSON.stringify(response.user))
      return true
    } catch (error) {
      console.error('Telegram login failed:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 获取用户信息
  async function fetchUser() {
    if (!token.value) return

    loading.value = true
    try {
      const response = await authApi.getCurrentUser()
      user.value = response.data
      localStorage.setItem('user', JSON.stringify(response.data))
    } catch (error) {
      console.error('Fetch user failed:', error)
      // 如果获取失败，清除登录状态
      logout()
    } finally {
      loading.value = false
    }
  }

  // 登出
  function logout() {
    user.value = null
    token.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
  }

  // 更新用户信息
  function updateUser(userData: Partial<User>) {
    if (user.value) {
      user.value = { ...user.value, ...userData }
      localStorage.setItem('user', JSON.stringify(user.value))
    }
  }

  return {
    user,
    token,
    loading,
    isLoggedIn,
    isVIP,
    init,
    login,
    register,
    telegramCallback,
    fetchUser,
    logout,
    updateUser,
  }
})
