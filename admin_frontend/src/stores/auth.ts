import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ADMIN_KEY, TOKEN_KEY } from '@/utils/request'
import type { AdminInfo } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const admin = ref<AdminInfo | null>(restoreAdmin())

  const isAuthenticated = computed(() => !!token.value)

  function restoreAdmin(): AdminInfo | null {
    try {
      const raw = localStorage.getItem(ADMIN_KEY)
      return raw ? (JSON.parse(raw) as AdminInfo) : null
    } catch {
      return null
    }
  }

  function setSession(newToken: string, info: AdminInfo) {
    token.value = newToken
    admin.value = info
    localStorage.setItem(TOKEN_KEY, newToken)
    localStorage.setItem(ADMIN_KEY, JSON.stringify(info))
  }

  function logout() {
    token.value = null
    admin.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(ADMIN_KEY)
  }

  return { token, admin, isAuthenticated, setSession, logout }
})
