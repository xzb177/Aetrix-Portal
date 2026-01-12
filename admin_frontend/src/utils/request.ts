import axios, { type AxiosError, type AxiosRequestConfig, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

// API 基础地址
// 开发环境使用 Vite 代理，生产环境使用完整 URL
const isDev = import.meta.env.DEV
// 生产环境使用相对路径 /api，由 Nginx 代理到后端
const BASE_URL = '/api'

// ============ 简单的内存缓存 ============
interface CacheItem {
  data: any
  timestamp: number
}

const requestCache = new Map<string, CacheItem>()
const DEFAULT_CACHE_TTL = 5 * 60 * 1000 // 5分钟

// 生成缓存键
const getCacheKey = (config: InternalAxiosRequestConfig): string => {
  return `${config.method}:${config.url}:${JSON.stringify(config.params)}:${JSON.stringify(config.data)}`
}

// 检查缓存
const checkCache = (config: InternalAxiosRequestConfig) => {
  if (config.method !== 'get' && config.method !== 'GET') return null
  if (!config.headers?.['Cache-Enabled']) return null

  const key = getCacheKey(config)
  const cached = requestCache.get(key)
  if (cached && Date.now() - cached.timestamp < (config.headers['Cache-TTL'] ? Number(config.headers['Cache-TTL']) : DEFAULT_CACHE_TTL)) {
    return cached.data
  }
  return null
}

// 设置缓存
const setCache = (config: InternalAxiosRequestConfig, data: any) => {
  if (config.method !== 'get' && config.method !== 'GET') return
  if (!config.headers?.['Cache-Enabled']) return

  const key = getCacheKey(config)
  requestCache.set(key, {
    data,
    timestamp: Date.now(),
  })
}

// ============ 请求重试配置 ============
interface AxiosRequestConfigExtended extends AxiosRequestConfig {
  __retryCount?: number
  __shouldRetry?: boolean
}

const MAX_RETRY = 2
const RETRY_DELAY = 1000

// ============ 创建 axios 实例 ============
const request = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 检查缓存
    const cached = checkCache(config)
    if (cached) {
      // 返回一个特殊标记，在响应拦截器中处理
      config.headers = config.headers || {}
      config.headers['__fromCache'] = 'true'
      config.adapter = () => Promise.resolve({
        data: cached,
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      } as AxiosResponse)
    }

    const authStore = useAuthStore()

    // 安全改进: 使用 httpOnly Cookie 存储 Token，不再手动添加 Authorization header
    // Cookie 中的访问令牌由浏览器自动发送，无需手动添加
    // 只需要添加 CSRF token 以防止跨站请求伪造 (CSRF) 攻击
    let csrfToken = authStore.getCsrfToken()

    // 如果 sessionStorage 中没有，尝试从 cookie 读取
    if (!csrfToken) {
      const match = document.cookie.match(/(^|;)\\s*admin_csrf_token=([^;]*)/)
      if (match && match[2]) {
        csrfToken = match[2]
      }
    }

    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken
    }

    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    // 设置缓存
    const config = response.config as InternalAxiosRequestConfig
    if (!config.headers?.['__fromCache']) {
      setCache(config, response.data)
    }

    const res = response.data
    // 后端返回格式: { code: 200, message: "success", data: ... }
    if (res.code === 200 || res.code === '200') {
      return res.data
    }
    // 有些端点直接返回数据（如 /emby/stats 等），没有 code 字段
    if (!res.code && (res.items || Array.isArray(res) || typeof res !== 'object' || res.total_users !== undefined)) {
      return res
    }
    // 错误响应
    if (res.code && res.code !== 200) {
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message || '请求失败'))
    }
    return res
  },
  async (error: AxiosError) => {
    const config = error.config as AxiosRequestConfigExtended

    // 网络错误或服务器错误时重试
    if (config && config.__shouldRetry !== false) {
      config.__retryCount = config.__retryCount || 0

      // 判断是否应该重试
      const shouldRetry = config.__retryCount < MAX_RETRY && (
        !error.response || // 网络错误
        error.response.status >= 500 || // 服务器错误
        error.response.status === 429 // 限流
      )

      if (shouldRetry) {
        config.__retryCount = (config.__retryCount || 0) + 1
        // 延迟重试
        const retryCount = config.__retryCount
        await new Promise(resolve => setTimeout(resolve, RETRY_DELAY * retryCount))
        return request(config)
      }
    }

    const authStore = useAuthStore()

    if (error.response) {
      const status = error.response.status
      // 优先显示后端返回的 detail 信息
      const responseData = error.response.data as any
      let message = '请求失败'

      // 尝试获取后端返回的错误信息
      if (responseData) {
        if (typeof responseData === 'string') {
          message = responseData
        } else if (responseData.detail) {
          message = responseData.detail
        } else if (responseData.message) {
          message = responseData.message
        }
      }

      switch (status) {
        case 401:
          ElMessage.error('登录已过期，请重新登录')
          authStore.logout()
          // 使用 router 跳转而不是 window.location.href
          window.location.href = window.location.pathname.startsWith('/admin') ? '/admin/login' : '/login'
          break
        case 403:
          ElMessage.error(message || '权限不足')
          break
        case 404:
          ElMessage.error(message || '请求的资源不存在')
          break
        case 429:
          ElMessage.error(message || '请求过于频繁，请稍后再试')
          break
        case 500:
          ElMessage.error(message || '服务器内部错误，请稍后重试')
          break
        case 502:
        case 503:
        case 504:
          ElMessage.error(message || '服务暂时不可用，请稍后重试')
          break
        default:
          ElMessage.error(message)
      }
    } else if (error.request) {
      ElMessage.error('网络错误，请检查网络连接')
    } else {
      ElMessage.error('请求失败：' + (error.message || '未知错误'))
    }

    return Promise.reject(error)
  }
)

export default request

// 通用请求方法
export const http = {
  get: <T = any>(url: string, config?: AxiosRequestConfig): Promise<T> => {
    return request.get(url, config)
  },
  post: <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> => {
    return request.post(url, data, config)
  },
  put: <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> => {
    return request.put(url, data, config)
  },
  delete: <T = any>(url: string, config?: AxiosRequestConfig): Promise<T> => {
    return request.delete(url, config)
  },
}

// 清除所有缓存
export const clearCache = () => {
  requestCache.clear()
}

// 带缓存的 GET 请求
export const cachedGet = <T = any>(url: string, config?: AxiosRequestConfig): Promise<T> => {
  return request.get(url, {
    ...config,
    headers: {
      ...config?.headers,
      'Cache-Enabled': 'true',
    },
  })
}
