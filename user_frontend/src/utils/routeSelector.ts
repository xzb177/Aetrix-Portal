/**
 * 线路选择引擎 (Route Selector)
 *
 * 实现稳定的用户分流和自动降级逻辑
 *
 * @module routeSelector
 */

import type { RouteInfo } from '@/api'

// ============================================================
// 常量定义
// ============================================================

const STORAGE_KEYS = {
  ANON_ID: 'route_anon_id',
  SELECTED_ROUTE: 'route_selected',
  FAILED_ROUTES: 'route_failed_cache',
  ROUTE_CONFIG_CACHE: 'route_config_cache',
  ROUTE_CONFIG_CACHE_TIME: 'route_config_cache_time',
} as const

const CACHE_TTL = 5 * 60 * 1000 // 5分钟缓存
const FAILED_ROUTE_TTL = 30 * 60 * 1000 // 30分钟失败记录

// ============================================================
// 类型定义
// ============================================================

export interface RouteSelectorContext {
  tgId?: number
  embyUserId?: number
  userId?: number
  region?: string
}

export interface RouteSelectionResult {
  route: RouteInfo | null
  stickyKey: string
  hashValue: number
  bucket: number
  fallbackReason?: string
  isDefault: boolean
}

export interface FailedRouteRecord {
  routeId: number
  timestamp: number
  reason?: string
}

// ============================================================
// FNV-1a 32bit Hash 实现
// ============================================================

/**
 * FNV-1a 32bit 哈希算法
 *
 * 生成确定性的哈希值，相同的输入总是产生相同的输出
 * 用于稳定的用户分流
 *
 * @param input - 要哈希的字符串
 * @returns 32位无符号整数哈希值
 */
export function fnv1aHash(input: string): number {
  if (typeof window === 'undefined') {
    // Node.js 环境
    const crypto = require('crypto')
    const hash = crypto.createHash('sha256').update(input).digest('hex')
    // 将十六进制哈希转为 32 位整数
    return parseInt(hash.substring(0, 8), 16)
  }

  // 浏览器环境使用 Web Crypto API
  // 为了保持确定性，使用简单的字符串哈希算法
  let hash = 0x811c9dc5 // FNV offset basis

  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) // FNV prime
  }

  // 确保是正整数（无符号 32 位）
  return hash >>> 0
}

// ============================================================
// Sticky Key 生成
// ============================================================

/**
 * 获取或生成匿名用户 ID
 *
 * 匿名 ID 只生成一次，持久化到 localStorage
 */
function getOrGenerateAnonId(): string {
  if (typeof window === 'undefined') {
    return 'unknown'
  }

  let anonId = localStorage.getItem(STORAGE_KEYS.ANON_ID)
  if (!anonId) {
    // 生成随机匿名 ID
    anonId = `anon_${Date.now()}_${Math.random().toString(36).substring(2, 10)}`
    localStorage.setItem(STORAGE_KEYS.ANON_ID, anonId)
  }
  return anonId
}

/**
 * 生成用户粘性标识 (Sticky Key)
 *
 * 优先级：tgId > embyUserId > userId > anonId
 *
 * @param context - 用户上下文信息
 * @returns 用户粘性标识
 */
export function generateStickyKey(context: RouteSelectorContext): string {
  // 优先级：Telegram ID
  if (context.tgId && context.tgId > 0) {
    return `tg_${context.tgId}`
  }

  // 其次：Emby 用户 ID
  if (context.embyUserId && context.embyUserId > 0) {
    return `emby_${context.embyUserId}`
  }

  // 其次：用户 ID
  if (context.userId && context.userId > 0) {
    return `user_${context.userId}`
  }

  // 最后：匿名 ID
  return getOrGenerateAnonId()
}

// ============================================================
// 失败线路记录
// ============================================================

/**
 * 获取失败线路记录
 */
function getFailedRoutes(): FailedRouteRecord[] {
  if (typeof window === 'undefined') {
    return []
  }

  try {
    const stored = localStorage.getItem(STORAGE_KEYS.FAILED_ROUTES)
    if (!stored) return []

    const records: FailedRouteRecord[] = JSON.parse(stored)
    const now = Date.now()

    // 清理过期的失败记录
    const valid = records.filter(r => now - r.timestamp < FAILED_ROUTE_TTL)

    if (valid.length !== records.length) {
      localStorage.setItem(STORAGE_KEYS.FAILED_ROUTES, JSON.stringify(valid))
    }

    return valid
  } catch {
    return []
  }
}

/**
 * 记录线路失败
 */
export function markRouteFailed(routeId: number, reason?: string): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    const records = getFailedRoutes()
    const now = Date.now()

    // 更新或添加记录
    const existing = records.findIndex(r => r.routeId === routeId)
    if (existing >= 0) {
      records[existing].timestamp = now
      records[existing].reason = reason
    } else {
      records.push({ routeId, timestamp: now, reason })
    }

    localStorage.setItem(STORAGE_KEYS.FAILED_ROUTES, JSON.stringify(records))
  } catch {
    // 忽略存储错误
  }
}

/**
 * 清理失败线路记录
 */
export function clearFailedRoutes(): void {
  if (typeof window === 'undefined') {
    return
  }

  localStorage.removeItem(STORAGE_KEYS.FAILED_ROUTES)
}

/**
 * 检查线路是否在失败列表中
 */
function isRouteFailed(routeId: number): boolean {
  const records = getFailedRoutes()
  return records.some(r => r.routeId === routeId)
}

// ============================================================
// 线路选择算法
// ============================================================

/**
 * 计算用户的哈希桶值
 *
 * @param stickyKey - 用户粘性标识
 * @param routeId - 线路 ID
 * @returns 0-100 的桶值
 */
export function calculateBucket(stickyKey: string, routeId: number): number {
  const combined = `${stickyKey}-${routeId}`
  const hash = fnv1aHash(combined)
  return hash % 101 // 0-100
}

/**
 * 从可用线路中选择最优线路
 *
 * 规则优先级：
 * 1. allowUserIds 命中 -> 直接可用
 * 2. denyUserIds 命中 -> 排除
 * 3. enabled=false 或 status in (maintenance,down) -> 排除
 * 4. regionScope 不符合 -> 排除
 * 5. rolloutPercent：bucket < percent -> 命中
 * 6. 按 priority 升序排序，选最优
 *
 * @param routes - 可用线路列表
 * @param context - 用户上下文
 * @param options - 额外选项
 * @returns 选中的线路信息
 */
export function selectRoute(
  routes: RouteInfo[],
  context: RouteSelectorContext,
  options: {
    allowUserIds?: number[]
    denyUserIds?: number[]
    rolloutPercents?: Map<number, number>
    enabled?: boolean
    status?: 'ok' | 'maintenance' | 'down'
  } = {}
): RouteSelectionResult {
  const stickyKey = generateStickyKey(context)

  // 过滤掉失败的线路
  let availableRoutes = routes.filter(r => !isRouteFailed(r.id))

  // 如果所有线路都失败了，重置失败记录并重试
  if (availableRoutes.length === 0 && routes.length > 0) {
    clearFailedRoutes()
    availableRoutes = routes
  }

  // 如果没有可用线路，返回空结果
  if (availableRoutes.length === 0) {
    return {
      route: null,
      stickyKey,
      hashValue: 0,
      bucket: 0,
      fallbackReason: 'No available routes',
      isDefault: false,
    }
  }

  // 地区匹配
  if (context.region) {
    const regionMatches = availableRoutes.filter(r =>
      r.region_scope.includes(context.region!) ||
      r.region_scope.includes('GLOBAL')
    )

    if (regionMatches.length > 0) {
      availableRoutes = regionMatches
    } else {
      // 降级到 GLOBAL 线路
      availableRoutes = availableRoutes.filter(r =>
        r.region_scope.includes('GLOBAL')
      )
    }
  }

  if (availableRoutes.length === 0) {
    return {
      route: null,
      stickyKey,
      hashValue: 0,
      bucket: 0,
      fallbackReason: `No routes available for region: ${context.region}`,
      isDefault: false,
    }
  }

  // 按 priority 升序排序（越小越优先）
  availableRoutes.sort((a, b) => a.priority - b.priority)

  // 选择最优线路
  const selected = availableRoutes[0]
  const hashValue = fnv1aHash(`${stickyKey}`)
  const bucket = hashValue % 101

  return {
    route: selected,
    stickyKey,
    hashValue,
    bucket,
    isDefault: selected.tags.includes('default'),
  }
}

// ============================================================
// 缓存管理
// ============================================================

/**
 * 从缓存加载线路配置
 */
export function loadRoutesFromCache(): RouteInfo[] | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    const cached = localStorage.getItem(STORAGE_KEYS.ROUTE_CONFIG_CACHE)
    const cacheTime = localStorage.getItem(STORAGE_KEYS.ROUTE_CONFIG_CACHE_TIME)

    if (!cached || !cacheTime) {
      return null
    }

    const age = Date.now() - parseInt(cacheTime, 10)
    if (age > CACHE_TTL) {
      // 缓存过期
      return null
    }

    return JSON.parse(cached)
  } catch {
    return null
  }
}

/**
 * 保存线路配置到缓存
 */
export function saveRoutesToCache(routes: RouteInfo[]): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    localStorage.setItem(STORAGE_KEYS.ROUTE_CONFIG_CACHE, JSON.stringify(routes))
    localStorage.setItem(STORAGE_KEYS.ROUTE_CONFIG_CACHE_TIME, Date.now().toString())
  } catch {
    // 忽略存储错误
  }
}

/**
 * 清除线路配置缓存
 */
export function clearRoutesCache(): void {
  if (typeof window === 'undefined') {
    return
  }

  localStorage.removeItem(STORAGE_KEYS.ROUTE_CONFIG_CACHE)
  localStorage.removeItem(STORAGE_KEYS.ROUTE_CONFIG_CACHE_TIME)
}

// ============================================================
// 调试信息
// ============================================================

/**
 * 生成线路选择调试信息
 */
export function generateDebugInfo(
  routes: RouteInfo[],
  selection: RouteSelectionResult,
  context: RouteSelectorContext,
  featureEnabled: boolean
): string {
  const lines: string[] = []

  lines.push('=== 线路选择调试信息 ===')
  lines.push(`功能开关: ${featureEnabled ? '✅ 启用' : '❌ 禁用'}`)
  lines.push(`用户上下文:`)
  lines.push(`  - userId: ${context.userId ?? 'N/A'}`)
  lines.push(`  - tgId: ${context.tgId ?? 'N/A'}`)
  lines.push(`  - embyUserId: ${context.embyUserId ?? 'N/A'}`)
  lines.push(`  - region: ${context.region ?? 'N/A'}`)
  lines.push(``)
  lines.push(`选择结果:`)
  lines.push(`  - stickyKey: ${selection.stickyKey}`)
  lines.push(`  - hashValue: ${selection.hashValue}`)
  lines.push(`  - bucket: ${selection.bucket}`)
  lines.push(`  - 线路ID: ${selection.route?.id ?? 'N/A'}`)
  lines.push(`  - 线路名: ${selection.route?.name ?? 'N/A'}`)
  lines.push(`  - 域名: ${selection.route?.domain ?? 'N/A'}`)
  lines.push(`  - 是默认线路: ${selection.isDefault ? '是' : '否'}`)

  if (selection.fallbackReason) {
    lines.push(`  - 回退原因: ${selection.fallbackReason}`)
  }

  lines.push(``)
  lines.push(`可用线路 (${routes.length} 条):`)
  routes.forEach((r, i) => {
    lines.push(`  ${i + 1}. [${r.id}] ${r.name} (${r.domain}) - priority: ${r.priority}`)
  })

  lines.push(`========================`)

  return lines.join('\n')
}

/**
 * 复制调试信息到剪贴板
 */
export async function copyDebugInfo(
  routes: RouteInfo[],
  selection: RouteSelectionResult,
  context: RouteSelectorContext,
  featureEnabled: boolean
): Promise<boolean> {
  const debugInfo = generateDebugInfo(routes, selection, context, featureEnabled)

  if (typeof navigator !== 'undefined' && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(debugInfo)
      return true
    } catch {
      return false
    }
  }

  // 降级方案
  try {
    const textarea = document.createElement('textarea')
    textarea.value = debugInfo
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    return true
  } catch {
    return false
  }
}
