import axios, { type AxiosError, type AxiosRequestConfig, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useLoadingStore } from '@/stores/loading'

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

// ============ 扩展配置接口 ============
interface AxiosRequestConfigExtended extends AxiosRequestConfig {
  // 重试配置
  __retryCount?: number
  __shouldRetry?: boolean
  // Loading 配置
  __skipLoading?: boolean
  __loadingLabel?: string
  // 请求 ID（用于追踪）
  __requestId?: string
}

// ============ 请求重试配置 ============
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

// ============ Loading 管理辅助函数 ============
// 生成简单的请求 ID
let requestIdCounter = 0
const generateRequestId = () => `req_${++requestIdCounter}_${Date.now()}`

// 存储每个请求的 loading label
const requestLabels = new Map<string, string>()

/**
 * 开始请求 loading
 * 注意：默认跳过全局 loading，避免每个请求都触发
 * 只有显式设置 __skipLoading = false 的请求才显示 loading
 */
const handleRequestStart = (config: InternalAxiosRequestConfig): string => {
  const extendedConfig = config as AxiosRequestConfigExtended
  // 默认跳过全局 loading，避免每个请求都触发
  // 只有显式设置 __skipLoading = false 的请求才显示 loading
  if (extendedConfig.__skipLoading === false) {
    const loadingStore = useLoadingStore()
    const requestId = extendedConfig.__requestId || generateRequestId()
    extendedConfig.__requestId = requestId
    const label = extendedConfig.__loadingLabel || `${config.method?.toUpperCase()} ${config.url}`
    requestLabels.set(requestId, label)
    loadingStore.startLoading(label)
    return requestId
  }
  return ''
}

/**
 * 结束请求 loading
 */
const handleRequestEnd = (requestId: string) => {
  if (requestId) {
    const loadingStore = useLoadingStore()
    const label = requestLabels.get(requestId) || 'request.end'
    requestLabels.delete(requestId)
    loadingStore.stopLoading(label)
  }
}

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 开始 loading（返回请求 ID）
    const requestId = handleRequestStart(config)
    // 存储请求 ID 到 config 中，供响应拦截器使用
    ;(config as AxiosRequestConfigExtended).__requestId = requestId

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
    // 请求错误也要停止 loading
    const requestId = (error.config as AxiosRequestConfigExtended).__requestId || ''
    handleRequestEnd(requestId)
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    // 停止 loading（成功路径）
    const requestId = (response.config as AxiosRequestConfigExtended).__requestId || ''
    handleRequestEnd(requestId)

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
  async (error) => {
    // 获取请求 ID，确保 finally 中能停止 loading
    const requestId = (error.config as AxiosRequestConfigExtended)?.__requestId || ''

    try {
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
            // 如果已经在登录页面，不显示"登录已过期"，只显示具体错误信息
            const isLoginPage = window.location.pathname.includes('/login')
            ElMessage.error(isLoginPage ? message : '登录已过期，请重新登录')
            // 只有非登录页面才执行登出和重定向
            if (!isLoginPage) {
              authStore.logout()
              window.location.href = window.location.pathname.startsWith('/admin') ? '/admin/login' : '/login'
            }
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
    } finally {
      // 兜底：确保无论如何都停止 loading
      handleRequestEnd(requestId)
    }
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
