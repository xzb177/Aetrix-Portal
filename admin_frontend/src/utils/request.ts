/**
 * 管理端 HTTP 客户端
 *
 * - baseURL: /api/admin（v2.2.0 后端统一前缀）
 * - 鉴权：Authorization: Bearer <access_token>（localStorage）
 * - 401：清掉失效凭证后**原地重载**，由路由守卫用门户会话静默免登恢复；
 *   恢复不了才落回登录页（不再弹一句「凭证已过期」的报错）
 * - 响应：后端直接返回 JSON（无 code 包裹），失败时抛出 detail 信息
 */
import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

export const TOKEN_KEY = 'admin_access_token'
export const ADMIN_KEY = 'admin_info'

const request = axios.create({
  baseURL: '/api/admin',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

request.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => response.data,
  (error: AxiosError<{ detail?: string }>) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail

    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(ADMIN_KEY)
      // 避免登录页自身的 401（密码输错）循环重载
      if (!window.location.pathname.endsWith('/login')) {
        if (canAutoRecover()) {
          // 整页重载后路由守卫会拿门户会话静默接管：成功即原地恢复，失败才会去登录页
          markAutoRecover()
          window.location.reload()
        } else {
          // 刚恢复过又失效：不再循环，直接交给登录页
          window.location.href = '/admin/login'
        }
      }
      // 401 不做全局报错：这是一次可自愈的会话过期，提示交给登录页的说明文案
      return Promise.reject(new Error(detail || '登录状态已失效'))
    }

    const message = detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(new Error(message))
  }
)

/** 401 自愈节流：短时间内只自动重载一次，避免「重载 → 又 401 → 再重载」的死循环 */
const RECOVER_KEY = 'admin_401_recover_at'
const RECOVER_WINDOW = 15000

function canAutoRecover(): boolean {
  const last = Number(sessionStorage.getItem(RECOVER_KEY) || 0)
  return Date.now() - last > RECOVER_WINDOW
}

function markAutoRecover(): void {
  sessionStorage.setItem(RECOVER_KEY, String(Date.now()))
}

/** 所有 API 返回 any（由调用方按类型断言），保持调用层简洁 */
export function get<T = any>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request.get(url, { params }) as Promise<T>
}

export function post<T = any>(url: string, data?: unknown): Promise<T> {
  return request.post(url, data) as Promise<T>
}

/** multipart 直传；不要手动设置 boundary，交给浏览器 / Axios 生成。 */
export function upload<T = any>(url: string, data: FormData): Promise<T> {
  return request.post(url, data, { headers: { 'Content-Type': 'multipart/form-data' } }) as Promise<T>
}

export function getBlob(url: string): Promise<Blob> {
  return request.get(url, { responseType: 'blob' }) as Promise<Blob>
}

export function put<T = any>(
  url: string, data?: unknown, params?: Record<string, unknown>
): Promise<T> {
  return request.put(url, data, { params }) as Promise<T>
}

export function patch<T = any>(url: string, data?: unknown): Promise<T> {
  return request.patch(url, data) as Promise<T>
}

export function del<T = any>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request.delete(url, { params }) as Promise<T>
}
