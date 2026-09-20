import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, tokenStore, type AuthUser } from '@/api'

export type { AuthUser as User }

export const useUserStore = defineStore('user', () => {
  const user = ref<AuthUser | null>(null)
  const token = ref<string | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => !!token.value)
  const isVIP = computed(() => !!user.value?.is_vip)
  /** 付费墙是否开启（后端配置），开启且非会员时播放会被拦截 */
  const subscriptionRequired = computed(() => !!user.value?.subscription_required)
  /** 需要被拦截：付费墙开启且当前账号不是会员 */
  const needsSubscription = computed(() => subscriptionRequired.value && !isVIP.value)

  // 从 localStorage 恢复登录态
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

  function _persist(response: { access_token: string; refresh_token: string; user: AuthUser }) {
    token.value = response.access_token
    user.value = response.user
    tokenStore.set(response.access_token, response.refresh_token)
    localStorage.setItem('user', JSON.stringify(response.user))
  }

  async function login(username: string, password: string) {
    loading.value = true
    try {
      const response = await authApi.login({ username, password })
      _persist(response)
      return true
    } finally {
      loading.value = false
    }
  }

  async function register(
    username: string,
    password: string,
    email?: string,
    invitationCode?: string,
    registrationCode?: string,
  ) {
    loading.value = true
    try {
      const response = await authApi.register({
        username,
        password,
        email,
        invitation_code: invitationCode || undefined,
        registration_code: registrationCode || undefined,
      })
      _persist(response)
      return true
    } finally {
      loading.value = false
    }
  }

  async function fetchUser() {
    if (!token.value) return
    loading.value = true
    try {
      const response = await authApi.getCurrentUser()
      user.value = response
      localStorage.setItem('user', JSON.stringify(response))
    } catch (error) {
      // 获取失败（含刷新失败）时清除登录态；拦截器已处理跳转
      console.error('Fetch user failed:', error)
      logout()
      throw error
    } finally {
      loading.value = false
    }
  }

  function logout() {
    user.value = null
    token.value = null
    tokenStore.clear()
  }

  function updateUser(userData: Partial<AuthUser>) {
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
    subscriptionRequired,
    needsSubscription,
    init,
    login,
    register,
    fetchUser,
    logout,
    updateUser,
  }
})
