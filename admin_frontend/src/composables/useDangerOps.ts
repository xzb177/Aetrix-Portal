import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cleanLocalCache,
  fetchBackupConfig,
  fetchLocalCacheConfig,
  fetchQuotaBreakerStatus,
  purgeLoginLogs,
  resetQuotaBreaker,
  runBackupNow,
  type BackupConfig,
  type QuotaBreakerStatus,
} from '@/api/admin'
import type { LocalCacheStats } from '@/types'

/**
 * 危险操作（Phase 5）：**不可撤销 / 跨对象**的那几项操作，收在一处实现
 *
 * 为什么要有这个 composable：这几项操作原先分散在三个页面里各写一遍——
 * 仪表盘的「手动恢复熔断器」、客户端策略的「清理本地缓存」、登录日志的「清理日志」。
 * 同一个删除动作有两份确认文案，就等于迟早有一份漏掉「会发生什么」这句话。
 * 现在逻辑只在这里一份：
 *
 * - 「系统设置 → 危险操作」页签用它（完整卡片 + 备份护栏 + 角色置灰）；
 * - 三个页面原来的按钮也调它（就地快捷方式，不再各自实现一遍）。
 *
 * **纯前端**：全部复用既有 `/api/admin/*` 写端点，没有新接口，也就没有新鉴权面。
 * 写权限仍由服务端 `get_current_admin` + `admin_roles` 把关（只读审计角色会被 403），
 * 前端的置灰只是提前告知。
 */
export type CacheCleanMode = 'ready' | 'failed' | 'all'

export function fmtBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

/**
 * 不可撤销的操作要手打一个词才算确认：点错一次不该丢数据
 * （返回 false = 用户取消或没打对，调用方直接返回，不要执行）
 */
async function confirmIrreversible(message: string, word: string, title: string): Promise<boolean> {
  try {
    const { value } = await ElMessageBox.prompt(message, title, {
      type: 'warning',
      confirmButtonText: `确认${word}`,
      cancelButtonText: '取消',
      inputPlaceholder: `输入「${word}」以确认`,
      inputValidator: (v: string) => (v.trim() === word ? true : `请输入「${word}」`),
    })
    return value.trim() === word
  } catch {
    return false
  }
}

export function useDangerOps() {
  const breaker = ref<QuotaBreakerStatus | null>(null)
  const cacheStats = ref<LocalCacheStats | null>(null)
  const backup = ref<BackupConfig | null>(null)
  const loading = ref(false)
  /** 当前正在执行的动作（'' = 无）：按钮据此显示 loading，避免重复点击 */
  const busy = ref('')

  async function loadState() {
    loading.value = true
    try {
      // 三个接口互不依赖，一起打；任何一个失败都只让**它自己**那一块显示为未知，
      // 不让「备份读不到」变成「缓存状态也读不到」
      const [cacheRes, backupRes] = await Promise.all([
        fetchLocalCacheConfig().catch(() => null),
        fetchBackupConfig().catch(() => null),
      ])
      cacheStats.value = cacheRes?.stats ?? null
      backup.value = backupRes ?? null
    } finally {
      await loadBreaker()
      loading.value = false
    }
  }

  /** 只拉熔断器状态：仪表盘只想显示那块小卡，不必把缓存与备份配置也拖回来 */
  async function loadBreaker() {
    const res = await fetchQuotaBreakerStatus().catch(() => null)
    breaker.value = res?.breaker ?? null
  }

  /** 立即备份一次（不是危险操作，但它是危险操作的前置动作，所以放在同一个地方） */
  async function backupNow(): Promise<boolean> {
    busy.value = 'backup'
    try {
      const res = await runBackupNow()
      backup.value = res
      ElMessage.success(`备份完成：${res.backup.name}`)
      return true
    } catch {
      return false   // 拦截器已提示
    } finally {
      busy.value = ''
    }
  }

  /** 手动恢复配额熔断器：状态读不到或本来就没触发时**不做**（不盲操作） */
  async function resetBreakerNow(): Promise<boolean> {
    if (!breaker.value?.tripped) return false
    try {
      await ElMessageBox.confirm(
        '恢复后 worker 会立刻重新请求上游。如果配额其实还没恢复，会马上再撞一次 403 并重新熔断。',
        '手动恢复配额熔断器',
        { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' },
      )
    } catch {
      return false
    }
    busy.value = 'breaker'
    try {
      await resetQuotaBreaker()
      ElMessage.success('熔断器已恢复，worker 重新开始工作')
      await loadState()
      return true
    } catch {
      return false
    } finally {
      busy.value = ''
    }
  }

  /** 清理 / 清空本地播放缓存。清空全部不可恢复，要求手打「清空」。 */
  async function cleanCache(mode: CacheCleanMode): Promise<boolean> {
    const used = fmtBytes(cacheStats.value?.bytes_used || 0)
    const what = mode === 'all'
      ? '清空**全部**缓存记录与本机副本（正在下载的那条会等下载完再清）'
      : mode === 'failed' ? '清理下载失败的记录（不动已缓存的副本）'
      : '清理已缓存的副本与对应记录，下次播放会重新回源拉取'
    if (mode === 'all') {
      const ok = await confirmIrreversible(
        `${what}。当前占用 ${used}，清完热门片要重新回源。`,
        '清空',
        '清空本地播放缓存',
      )
      if (!ok) return false
    } else {
      try {
        await ElMessageBox.confirm(`${what}。当前占用 ${used}。`, '清理本地播放缓存', {
          type: 'warning', confirmButtonText: '确认清理', cancelButtonText: '取消',
        })
      } catch {
        return false
      }
    }
    busy.value = `cache:${mode}`
    try {
      const res = await cleanLocalCache(mode)
      cacheStats.value = res.stats
      ElMessage.success(`已清理 ${res.cleaned.removed} 条，释放 ${fmtBytes(res.cleaned.freed_bytes)}`)
      return true
    } catch {
      return false
    } finally {
      busy.value = ''
    }
  }

  /** 清理登录与安全日志：days=0 表示清空全部。删掉就查不到了，手打「清理」确认。 */
  async function purgeLogs(days: number): Promise<boolean> {
    const d = Math.max(0, Math.round(Number(days) || 0))
    const label = d === 0 ? '**清空全部**登录与安全日志' : `删除 ${d} 天前的登录与安全日志`
    const ok = await confirmIrreversible(
      `${label}。删掉之后，风控与安全审计就查不到那段历史了（不可恢复）。`,
      '清理',
      '清理登录与安全日志',
    )
    if (!ok) return false
    busy.value = 'logs'
    try {
      const res = await purgeLoginLogs(d)
      ElMessage.success(res.message)
      return true
    } catch {
      return false
    } finally {
      busy.value = ''
    }
  }

  return {
    backup,
    breaker,
    busy,
    cacheStats,
    cleanCache,
    loadBreaker,
    loadState,
    loading,
    purgeLogs,
    backupNow,
    resetBreakerNow,
  }
}
