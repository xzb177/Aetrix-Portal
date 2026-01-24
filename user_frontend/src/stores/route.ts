/**
 * 线路配置 Store
 *
 * 管理线路选择引擎的状态和配置
 *
 * @module routeStore
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { routesApi, type RouteInfo } from '@/api'
import {
  selectRoute,
  loadRoutesFromCache,
  saveRoutesToCache,
  clearRoutesCache,
  markRouteFailed,
  clearFailedRoutes,
  type RouteSelectorContext,
  type RouteSelectionResult,
} from '@/utils/routeSelector'
import { featureFlags } from '@/config/featureFlags'

export const useRouteStore = defineStore('route', () => {
  // ============================================================
  // 状态
  // ============================================================

  /** 所有可用线路 */
  const routes = ref<RouteInfo[]>([])

  /** 当前选中的线路 */
  const selectedRoute = ref<RouteInfo | null>(null)

  /** 线路选择结果详情 */
  const selectionResult = ref<RouteSelectionResult | null>(null)

  /** 加载状态 */
  const loading = ref(false)

  /** 错误信息 */
  const error = ref<string | null>(null)

  /** 功能是否启用 */
  const featureEnabled = computed(() => featureFlags.ROUTE_CONFIG ?? false)

  /** 是否使用默认线路（回退模式） */
  const isUsingDefault = computed(() => selectionResult.value?.isDefault ?? false)

  /** 是否有可用的线路 */
  const hasRoutes = computed(() => routes.value.length > 0)

  /** 当前线路 URL */
  const currentRouteUrl = computed(() => {
    if (!selectedRoute.value) return null
    const route = selectedRoute.value
    const protocol = route.tls ? 'https://' : 'http://'
    return `${protocol}${route.domain}${route.base_path}`
  })

  // ============================================================
  // 用户上下文获取
  // ============================================================

  /**
   * 获取用户上下文信息
   * 延迟导入 userStore 避免循环依赖
   */
  function getUserContext(): RouteSelectorContext {
    // 延迟获取 userStore
    const { useUserStore } = require('./user')
    const userStore = useUserStore()

    const context: RouteSelectorContext = {
      userId: userStore.user?.id,
      tgId: userStore.user?.telegram_id,
      // embyUserId 需要从 Emby 账号信息中获取
    }

    // 尝试从 localStorage 获取 Emby 账号信息
    try {
      const embyAccounts = localStorage.getItem('emby_accounts')
      if (embyAccounts) {
        const accounts = JSON.parse(embyAccounts)
        if (Array.isArray(accounts) && accounts.length > 0) {
          // 使用第一个 Emby 账号的 ID
          context.embyUserId = accounts[0].emby_user_id || accounts[0].id
        }
      }
    } catch {
      // 忽略解析错误
    }

    // 检测地区（通过时区或其他方式）
    const timezone = Intl?.DateTimeFormat()?.resolvedOptions()?.timeZone
    if (timezone) {
      // 简单的地区映射
      if (timezone.includes('Asia')) {
        context.region = 'ASIA'
      } else if (timezone.includes('Europe')) {
        context.region = 'EU'
      } else if (timezone.includes('America')) {
        context.region = 'US'
      }
    }

    return context
  }

  // ============================================================
  // 核心方法
  // ============================================================

  /**
   * 获取线路配置
   *
   * 优先级：
   * 1. Feature Flag 关闭 → 返回默认线路
   * 2. 本地缓存未过期 → 使用缓存
   * 3. API 调用成功 → 更新缓存
   * 4. API 调用失败 → 使用缓存或默认线路
   */
  async function fetchRoutes(forceRefresh = false): Promise<void> {
    // 检查功能开关
    if (!featureEnabled.value) {
      // 功能关闭时，使用默认行为
      routes.value = []
      selectedRoute.value = null
      selectionResult.value = null
      return
    }

    // 尝试从缓存加载
    if (!forceRefresh) {
      const cached = loadRoutesFromCache()
      if (cached && cached.length > 0) {
        routes.value = cached
        performRouteSelection()
        return
      }
    }

    loading.value = true
    error.value = null

    try {
      const data = await routesApi.getRoutes()

      if (Array.isArray(data) && data.length > 0) {
        routes.value = data
        // 保存到缓存
        saveRoutesToCache(data)
        performRouteSelection()
      } else {
        // API 返回空数据，使用缓存或默认
        const cached = loadRoutesFromCache()
        if (cached) {
          routes.value = cached
        } else {
          routes.value = []
        }
        performRouteSelection()
      }
    } catch (err) {
      console.error('Failed to fetch routes:', err)
      error.value = err instanceof Error ? err.message : '获取线路配置失败'

      // API 失败，尝试使用缓存
      const cached = loadRoutesFromCache()
      if (cached && cached.length > 0) {
        routes.value = cached
      } else {
        routes.value = []
      }
      performRouteSelection()
    } finally {
      loading.value = false
    }
  }

  /**
   * 执行线路选择
   */
  function performRouteSelection(): void {
    if (routes.value.length === 0) {
      selectedRoute.value = null
      selectionResult.value = null
      return
    }

    const context = getUserContext()
    const result = selectRoute(routes.value, context)

    selectionResult.value = result
    selectedRoute.value = result.route
  }

  /**
   * 刷新线路配置
   */
  async function refresh(): Promise<void> {
    await fetchRoutes(true)
  }

  /**
   * 标记当前线路失败，自动切换到下一条可用线路
   */
  function markCurrentFailed(reason?: string): void {
    if (!selectedRoute.value) return

    markRouteFailed(selectedRoute.value.id, reason)
    performRouteSelection()
  }

  /**
   * 重置失败记录
   */
  function resetFailedRecords(): void {
    clearFailedRoutes()
    performRouteSelection()
  }

  /**
   * 清除缓存并重新获取
   */
  async function clearCache(): Promise<void> {
    clearRoutesCache()
    await fetchRoutes(true)
  }

  /**
   * 获取调试信息
   */
  function getDebugInfo(): string {
    const { generateDebugInfo } = require('@/utils/routeSelector')
    const context = getUserContext()
    const result = selectionResult.value || {
      route: null,
      stickyKey: '',
      hashValue: 0,
      bucket: 0,
      isDefault: false,
    }

    return generateDebugInfo(
      routes.value,
      result,
      context,
      featureEnabled.value
    )
  }

  /**
   * 复制调试信息
   */
  async function copyDebugInfo(): Promise<boolean> {
    const { copyDebugInfo } = require('@/utils/routeSelector')
    const context = getUserContext()
    const result = selectionResult.value || {
      route: null,
      stickyKey: '',
      hashValue: 0,
      bucket: 0,
      isDefault: false,
    }

    return await copyDebugInfo(
      routes.value,
      result,
      context,
      featureEnabled.value
    )
  }

  // ============================================================
  // 初始化
  // ============================================================

  function init() {
    // 初始化时获取线路配置
    fetchRoutes()

    // 监听用户登录状态变化，重新选择线路
    const { useUserStore } = require('./user')
    const userStore = useUserStore()

    watch(
      () => userStore.isLoggedIn,
      () => {
        performRouteSelection()
      }
    )

    // 监听用户信息变化
    watch(
      () => userStore.user,
      () => {
        performRouteSelection()
      },
      { deep: true }
    )
  }

  // ============================================================
  // 导出
  // ============================================================

  return {
    // 状态
    routes,
    selectedRoute,
    selectionResult,
    loading,
    error,

    // 计算属性
    featureEnabled,
    isUsingDefault,
    hasRoutes,
    currentRouteUrl,

    // 方法
    fetchRoutes,
    refresh,
    markCurrentFailed,
    resetFailedRecords,
    clearCache,
    getDebugInfo,
    copyDebugInfo,
    init,
  }
})
