/**
 * 管理端 HTTP 客户端
 *
 * - baseURL: /api/admin（v2.2.0 后端统一前缀）
 * - 鉴权：Authorization: Bearer <access_token>（localStorage）
 * - 401：清除凭证并跳转登录页
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
      // 避免登录页自身的 401 循环跳转
      if (!window.location.pathname.endsWith('/login')) {
        window.location.href = '/admin/login'
      }
    }

    const message = detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(new Error(message))
  }
)

/** 所有 API 返回 any（由调用方按类型断言），保持调用层简洁 */
export function get<T = any>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request.get(url, { params }) as Promise<T>
}

export function post<T = any>(url: string, data?: unknown): Promise<T> {
  return request.post(url, data) as Promise<T>
}

export function put<T = any>(url: string, data?: unknown): Promise<T> {
  return request.put(url, data) as Promise<T>
}

export function del<T = any>(url: string): Promise<T> {
  return request.delete(url) as Promise<T>
}
