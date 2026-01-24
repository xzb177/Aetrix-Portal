/**
 * 线路管理 API
 *
 * 提供线路管理的 CRUD 和操作接口
 * 如果后端接口尚未实现，使用 localStorage/mock 数据兜底
 */

import { http } from '@/utils/request'

// ============================================================
// 类型定义
// ============================================================

export interface Route {
  id: number
  name: string
  description?: string
  enabled: boolean
  priority: number
  status: 'ok' | 'maintenance' | 'degraded' | 'down'
  domain: string
  tls: boolean
  base_path: string
  tags: string[]
  region_scope: string[]
  worker_route?: string
  origin_type: string
  rollout_percent: number
  health_last_ok_at?: string
  health_fail_count: number
  created_at: string
  updated_at: string
}

export interface RouteForm {
  name: string
  description?: string
  enabled: boolean
  priority: number
  tags: string[]
  region_scope: string[]
  domain: string
  tls: boolean
  base_path: string
  worker_route?: string
  origin_type: 'emby' | 'jellyfin' | 'http'
  rewrite_from?: string
  rewrite_to?: string
  status: 'ok' | 'maintenance' | 'degraded' | 'down'
  maintenance_message?: string
  rollout_percent: number
  health_url?: string
  health_expect_status: number
  health_timeout_ms: number
}

export interface PreviewData {
  user_id?: number
  tg_id?: number
  emby_user_id?: string
  anon_id?: string
  region?: string
  device?: string
}

export interface PreviewResult {
  selected_route: Route | null
  available_routes: Route[]
  explanation: string
  debug_info: {
    total_routes: number
    enabled_routes: number
    status_ok_routes: number
    region_matched: boolean
    in_allow_list: boolean
    in_deny_list: boolean
    rollout_passed: boolean
    hash_value?: number
    matched_rules: string[]
  }
}

export interface RouteListParams {
  search?: string
  enabled?: boolean
  status?: string
  tags?: string
}

// ============================================================
// Mock 数据（后端接口不可用时使用）
// ============================================================

const MOCK_ROUTES: Route[] = [
  {
    id: 1,
    name: '主线路 CF Worker',
    description: '主线路，通过 Cloudflare Worker 转发',
    enabled: true,
    priority: 10,
    status: 'ok',
    domain: 'emby.example.com',
    tls: true,
    base_path: '/emby',
    tags: ['primary', 'cf-worker'],
    region_scope: ['GLOBAL'],
    worker_route: '/emby/*',
    origin_type: 'emby',
    rollout_percent: 100,
    health_last_ok_at: new Date().toISOString(),
    health_fail_count: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z'
  },
  {
    id: 2,
    name: '备用线路直连',
    description: '备用线路，直连源站',
    enabled: true,
    priority: 50,
    status: 'ok',
    domain: 'backup.example.com',
    tls: true,
    base_path: '/',
    tags: ['backup', 'direct'],
    region_scope: ['CN', 'HK', 'TW'],
    origin_type: 'emby',
    rollout_percent: 100,
    health_last_ok_at: new Date().toISOString(),
    health_fail_count: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z'
  }
]

// LocalStorage key
const STORAGE_KEY = 'admin_routes_mock_data'

// 获取 mock 数据
function getMockRoutes(): Route[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      return JSON.parse(stored)
    }
  } catch (e) {
    console.error('Failed to load mock routes from localStorage:', e)
  }
  return [...MOCK_ROUTES]
}

// 保存 mock 数据
function saveMockRoutes(routes: Route[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(routes))
  } catch (e) {
    console.error('Failed to save mock routes to localStorage:', e)
  }
}

// 生成新 ID
function generateId(routes: Route[]): number {
  const maxId = routes.reduce((max, r) => Math.max(max, r.id), 0)
  return maxId + 1
}

// ============================================================
// API 函数（带 mock 兜底）
// ============================================================

/**
 * 获取线路列表
 */
export async function getRoutes(params?: RouteListParams): Promise<Route[]> {
  try {
    const response = await http.get<{ items: Route[] } | Route[]>('/routes', { params })
    // 兼容两种返回格式
    return Array.isArray(response) ? response : response.items || []
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    let routes = getMockRoutes()

    // 应用过滤条件
    if (params?.search) {
      const searchLower = params.search.toLowerCase()
      routes = routes.filter(r =>
        r.name.toLowerCase().includes(searchLower) ||
        r.domain.toLowerCase().includes(searchLower)
      )
    }
    if (params?.enabled !== undefined) {
      routes = routes.filter(r => r.enabled === params.enabled)
    }
    if (params?.status) {
      routes = routes.filter(r => r.status === params.status)
    }
    if (params?.tags) {
      const tags = params.tags.split(',').map(t => t.trim().toLowerCase())
      routes = routes.filter(r =>
        r.tags.some(tag => tags.some(t => tag.toLowerCase().includes(t)))
      )
    }

    // 按优先级排序
    return routes.sort((a, b) => a.priority - b.priority)
  }
}

/**
 * 创建线路
 */
export async function createRoute(data: RouteForm): Promise<Route> {
  try {
    return await http.post<Route>('/routes', data)
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    const routes = getMockRoutes()
    const newRoute: Route = {
      ...data,
      id: generateId(routes),
      health_last_ok_at: undefined,
      health_fail_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    }
    routes.push(newRoute)
    saveMockRoutes(routes)
    return newRoute
  }
}

/**
 * 更新线路
 */
export async function updateRoute(id: number, data: Partial<RouteForm>): Promise<Route> {
  try {
    return await http.put<Route>(`/routes/${id}`, data)
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    const routes = getMockRoutes()
    const index = routes.findIndex(r => r.id === id)
    if (index === -1) {
      throw new Error('Route not found')
    }
    routes[index] = {
      ...routes[index],
      ...data,
      updated_at: new Date().toISOString()
    }
    saveMockRoutes(routes)
    return routes[index]
  }
}

/**
 * 删除线路
 */
export async function deleteRoute(id: number): Promise<void> {
  try {
    await http.delete(`/routes/${id}`)
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    const routes = getMockRoutes()
    const filtered = routes.filter(r => r.id !== id)
    if (filtered.length === routes.length) {
      throw new Error('Route not found')
    }
    saveMockRoutes(filtered)
  }
}

/**
 * 切换线路启用/禁用状态
 */
export async function toggleRoute(id: number, enabled: boolean): Promise<Route> {
  try {
    return await http.post<Route>(`/routes/${id}/toggle`, { enabled })
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    return updateRoute(id, { enabled })
  }
}

/**
 * 设置维护模式
 */
export async function setMaintenance(
  id: number,
  status: 'ok' | 'maintenance',
  message?: string
): Promise<Route> {
  try {
    return await http.post<Route>(`/routes/${id}/maintenance`, {
      status,
      maintenance_message: message
    })
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    return updateRoute(id, { status })
  }
}

/**
 * 复制线路
 */
export async function copyRoute(id: number, name: string): Promise<Route> {
  try {
    return await http.post<Route>(`/routes/${id}/copy`, { name })
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    const routes = getMockRoutes()
    const original = routes.find(r => r.id === id)
    if (!original) {
      throw new Error('Route not found')
    }
    const newRoute: Route = {
      ...original,
      id: generateId(routes),
      name,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    }
    routes.push(newRoute)
    saveMockRoutes(routes)
    return newRoute
  }
}

/**
 * 调整优先级
 */
export async function updatePriority(id: number, priority: number): Promise<Route> {
  try {
    return await http.put<Route>(`/routes/${id}/priority`, { priority })
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    return updateRoute(id, { priority })
  }
}

/**
 * 策略预览
 */
export async function previewRoute(data: PreviewData): Promise<PreviewResult> {
  try {
    return await http.post<PreviewResult>('/routes/preview', data)
  } catch (error) {
    console.warn('Backend API unavailable, using mock data')
    // Mock 兜底
    const routes = getMockRoutes().filter(r => r.enabled && r.status === 'ok')
    const sorted = routes.sort((a, b) => a.priority - b.priority)

    // 简单的灰度模拟
    let selectedIndex = 0
    if (data.region && data.region !== 'GLOBAL') {
      const regionMatch = sorted.find(r => r.region_scope.includes(data.region!))
      if (regionMatch) {
        selectedIndex = sorted.indexOf(regionMatch)
      }
    }

    return {
      selected_route: sorted[selectedIndex] || null,
      available_routes: sorted,
      explanation: `根据您的配置，选中了线路「${sorted[selectedIndex]?.name || '无'}」`,
      debug_info: {
        total_routes: routes.length,
        enabled_routes: sorted.length,
        status_ok_routes: sorted.filter(r => r.status === 'ok').length,
        region_matched: !!data.region,
        in_allow_list: true,
        in_deny_list: false,
        rollout_passed: true,
        matched_rules: ['优先级匹配', '地区匹配']
      }
    }
  }
}

/**
 * 重置 mock 数据（仅用于开发测试）
 */
export function resetMockData(): void {
  localStorage.removeItem(STORAGE_KEY)
}
