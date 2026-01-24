import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * Loading Store - 全局加载状态管理（带 watchdog 防护）
 *
 * 安全特性:
 * - 8 秒 watchdog 自动关闭超时的 loading 状态
 * - 记录 loading 来源（label、时间、堆栈）
 * - 计数器模式支持并发请求
 * - 强制停止方法用于兜底清理
 * - 完整的调试日志输出
 */

// 检查是否启用调试模式
const isDebugEnabled = () => {
  if (typeof window === 'undefined') return false
  const params = new URLSearchParams(window.location.search)
  return params.has('debug') && params.get('debug') !== '0'
}

interface LoadingSource {
  label: string
  timestamp: Date
  stack?: string
}

interface LoadingHistoryItem {
  action: 'start' | 'stop' | 'forceStop' | 'ensureStopped'
  label: string
  timestamp: Date
  activeRequests: number
  stack?: string
}

export const useLoadingStore = defineStore('loading', () => {
  // 当前 loading 状态
  const isLoading = ref(false)

  // 活跃请求计数器
  const activeRequests = ref(0)

  // Loading 来源追踪（最后一次触发）
  const currentSource = ref<LoadingSource | null>(null)

  // Loading 历史记录（最多保留 50 条）
  const history = ref<LoadingHistoryItem[]>([])

  // Watchdog 计时器
  let watchdogTimer: ReturnType<typeof setTimeout> | null = null
  const WATCHDOG_TIMEOUT = 8000 // 8 秒

  /**
   * 记录历史
   */
  const addToHistory = (action: LoadingHistoryItem['action'], label: string, stack?: string) => {
    const item: LoadingHistoryItem = {
      action,
      label,
      timestamp: new Date(),
      activeRequests: activeRequests.value,
      stack: isDebugEnabled() ? stack : undefined,
    }
    history.value.push(item)
    if (history.value.length > 50) {
      history.value.shift()
    }
  }

  /**
   * 获取调用堆栈
   */
  const getCallStack = () => {
    const stack = new Error().stack
    if (!stack) return undefined
    // 只取前 5 行有用的堆栈信息
    return stack.split('\n').slice(3, 8).join('\n')
  }

  /**
   * 开始 loading（带来源追踪）
   * 使用计数器模式，支持并发请求
   */
  const startLoading = (label = 'unknown') => {
    const stack = getCallStack()
    const debug = isDebugEnabled()

    activeRequests.value++
    isLoading.value = true

    // 更新来源（记录最后一次触发）
    currentSource.value = {
      label,
      timestamp: new Date(),
      stack: debug ? stack : undefined,
    }

    // 记录历史
    addToHistory('start', label, stack)

    // 输出调试日志
    if (debug) {
      console.log(`[LoadingStore] ▶ Started: ${label}`, {
        activeRequests: activeRequests.value,
        stack,
      })
    } else {
      console.log(`[LoadingStore] ▶ Started: ${label} (active: ${activeRequests.value})`)
    }

    // 清除之前的 watchdog
    if (watchdogTimer) {
      clearTimeout(watchdogTimer)
    }

    // 设置新的 watchdog
    watchdogTimer = setTimeout(() => {
      if (isLoading.value && activeRequests.value > 0) {
        const source = currentSource.value
        console.error(
          `[LoadingStore] ⚠ Watchdog triggered! Loading stuck for ${WATCHDOG_TIMEOUT}ms`,
          {
            source: source?.label || 'unknown',
            timestamp: source?.timestamp?.toISOString(),
            activeRequests: activeRequests.value,
            stack: source?.stack,
          }
        )
        // 强制停止（重置所有状态）
        forceStop('watchdog')
      }
    }, WATCHDOG_TIMEOUT)
  }

  /**
   * 停止 loading
   * 使用计数器模式，只有计数器归零时才真正停止
   */
  const stopLoading = (label = 'unknown') => {
    const stack = getCallStack()
    const debug = isDebugEnabled()

    if (activeRequests.value <= 0) {
      console.warn(
        `[LoadingStore] ⚠ Attempted to stop loading but no active requests: ${label}`,
        debug ? { stack } : undefined
      )
      return
    }

    activeRequests.value--

    // 记录历史
    addToHistory('stop', label, stack)

    if (debug) {
      console.log(`[LoadingStore] ◼ Stopped: ${label}`, {
        activeRequests: activeRequests.value,
        stack,
      })
    } else {
      console.log(`[LoadingStore] ◼ Stopped: ${label} (active: ${activeRequests.value})`)
    }

    // 只有当所有请求都完成时才停止 loading
    if (activeRequests.value === 0) {
      isLoading.value = false
      currentSource.value = null

      // 清除 watchdog
      if (watchdogTimer) {
        clearTimeout(watchdogTimer)
        watchdogTimer = null
      }

      // 输出完成日志
      console.log(`[LoadingStore] ✓ All requests completed`)
    }
  }

  /**
   * 强制停止 loading（用于兜底清理）
   * 重置所有状态，忽略计数器
   */
  const forceStop = (reason = 'force') => {
    if (!isLoading.value && activeRequests.value === 0) {
      return
    }

    const source = currentSource.value
    const stack = getCallStack()
    const debug = isDebugEnabled()

    // 记录历史
    addToHistory('forceStop', reason, stack)

    console.warn(
      `[LoadingStore] ⚠ Force stop (${reason}): ${source?.label || 'unknown'}`,
      {
        activeRequests: activeRequests.value,
        duration: source ? Date.now() - new Date(source.timestamp).getTime() : 0,
        ...(debug && { sourceStack: source?.stack, currentStack: stack }),
      }
    )

    isLoading.value = false
    activeRequests.value = 0
    currentSource.value = null

    if (watchdogTimer) {
      clearTimeout(watchdogTimer)
      watchdogTimer = null
    }
  }

  /**
   * 确保停止 loading（无论当前状态如何）
   */
  const ensureStopped = (context = 'ensure') => {
    if (isLoading.value || activeRequests.value > 0) {
      const stack = getCallStack()
      addToHistory('ensureStopped', context, stack)
      forceStop(context)
    }
  }

  /**
   * 获取当前状态摘要（用于调试）
   */
  const getStatusSummary = () => {
    return {
      isLoading: isLoading.value,
      activeRequests: activeRequests.value,
      currentSource: currentSource.value ? {
        label: currentSource.value.label,
        timestamp: currentSource.value.timestamp.toISOString(),
        duration: Date.now() - new Date(currentSource.value.timestamp).getTime(),
      } : null,
      historyCount: history.value.length,
      recentHistory: history.value.slice(-5).map(h => ({
        action: h.action,
        label: h.label,
        timestamp: h.timestamp.toISOString(),
        activeRequests: h.activeRequests,
      })),
    }
  }

  return {
    isLoading,
    activeRequests,
    currentSource,
    history,
    startLoading,
    stopLoading,
    forceStop,
    ensureStopped,
    getStatusSummary,
  }
})

// 在浏览器环境暴露给调试使用
if (typeof window !== 'undefined') {
  ;(window as any).__loadingStore = {
    getStatus: () => {
      const store = useLoadingStore()
      return store.getStatusSummary()
    },
    getHistory: () => {
      const store = useLoadingStore()
      return store.history
    },
    forceStop: () => {
      const store = useLoadingStore()
      store.forceStop('manual')
    },
    enableDebug: () => {
      console.log('[LoadingStore] Debug mode enabled. Add ?debug=1 to URL.')
    },
  }

  // 页面失去焦点时检查是否有卡住的 loading
  window.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      const store = useLoadingStore()
      if (store.isLoading || store.activeRequests > 0) {
        console.warn('[LoadingStore] Page hidden while loading active:', store.getStatusSummary())
      }
    }
  })

  // 页面卸载时检查
  window.addEventListener('beforeunload', () => {
    const store = useLoadingStore()
    if (store.isLoading || store.activeRequests > 0) {
      console.warn('[LoadingStore] Page unloading while loading active:', store.getStatusSummary())
    }
  })

  console.log(
    '[LoadingStore] Debug API exposed:\n' +
    '  - window.__loadingStore.getStatus() - 获取当前状态\n' +
    '  - window.__loadingStore.getHistory() - 获取历史记录\n' +
    '  - window.__loadingStore.forceStop() - 强制停止\n' +
    '  添加 ?debug=1 到 URL 可启用完整调试日志'
  )
}
