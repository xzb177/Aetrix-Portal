import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import axios from 'axios'
import { ADMIN_KEY, TOKEN_KEY } from '@/utils/request'
import type { AdminInfo } from '@/types'

/** 用户端（门户）在同一源上保存的会话键——两端同源、同一套 JWT，可直接复用 */
const PORTAL_TOKEN_KEY = 'access_token'
const PORTAL_REFRESH_KEY = 'refresh_token'
/** 主动退出后台后的「不再免登」标记（仅本标签页有效，关掉页面即失效） */
const SKIP_SSO_KEY = 'admin_skip_sso'

interface ProbeResult {
  info: AdminInfo | null
  status: number
  token: string
}

/** 用给定 token 探测管理端身份；失败只回状态码，不抛异常 */
async function probeAdmin(token: string): Promise<ProbeResult> {
  try {
    const res = await axios.get<AdminInfo>('/api/admin/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 10000,
    })
    return { info: res.data, status: 200, token }
  } catch (e) {
    const status = axios.isAxiosError(e) ? e.response?.status ?? 0 : 0
    return { info: null, status, token }
  }
}

/**
 * 门户 access token 过期时用门户 refresh token 换一次新的
 *
 * 轮换后的新票据同时写回门户的存储键，用户端与本后台都不会掉线（JWT 无服务端撤销，
 * 以最后一次写入为准）。
 */
async function refreshPortalSession(): Promise<string | null> {
  const refresh = localStorage.getItem(PORTAL_REFRESH_KEY)
  if (!refresh) return null
  try {
    const res = await axios.post(
      '/api/user/auth/refresh',
      { refresh_token: refresh },
      { timeout: 10000 },
    )
    const access: string | undefined = res.data?.access_token
    if (!access) return null
    localStorage.setItem(PORTAL_TOKEN_KEY, access)
    if (res.data?.refresh_token) localStorage.setItem(PORTAL_REFRESH_KEY, res.data.refresh_token)
    return access
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const admin = ref<AdminInfo | null>(restoreAdmin())
  /** 免登探测只做一次（失败后不再反复打接口） */
  const ssoChecked = ref(false)
  /** 免登没成功的原因，用于登录页给出可操作提示 */
  const ssoNotice = ref('')

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
    // 主动退出后必须真的退出：本标签页内不再用门户会话自动免登（否则会被立刻「登回去」）
    sessionStorage.setItem(SKIP_SSO_KEY, '1')
  }

  /**
   * 门户免登：管理员在用户端登录后进管理后台，不再要求二次输入账号
   *
   * 管理后台与用户端同源，且共用同一套 JWT（`get_current_admin` 只认 `is_staff` 的 WebUser），
   * 所以门户的 access_token 本身就能通过 `/api/admin/auth/me`。这里静默探测一次：
   * - 通过 → 直接接管该会话（写入本后台的 token，后续请求照旧）
   * - 门户 token 已过期 → 用门户 refresh token 换新后再试
   * - 门户未登录 / 账号不是管理员 → 留在登录页并给出对应提示
   *
   * 探测走裸 axios：不能复用 utils/request，否则 401/403 会触发跳转与全局报错提示。
   */
  async function ssoFromPortal(): Promise<boolean> {
    if (ssoChecked.value) return isAuthenticated.value
    if (token.value) return true
    if (sessionStorage.getItem(SKIP_SSO_KEY)) {
      ssoChecked.value = true
      return false
    }
    const portalToken = localStorage.getItem(PORTAL_TOKEN_KEY)
    if (!portalToken) return false // 门户未登录：直接展示登录页，不发无谓请求
    ssoChecked.value = true

    let probe = await probeAdmin(portalToken)
    if (probe.status === 401) {
      const refreshed = await refreshPortalSession()
      if (refreshed) probe = await probeAdmin(refreshed)
    }

    if (probe.info) {
      setSession(probe.token, probe.info)
      ssoNotice.value = ''
      return true
    }

    ssoNotice.value =
      probe.status === 403
        ? '当前门户账号没有管理员权限，请使用管理员账号登录'
        : '门户登录状态已失效，请重新登录'
    return false
  }

  return {
    token,
    admin,
    ssoNotice,
    isAuthenticated,
    setSession,
    logout,
    ssoFromPortal,
  }
})
