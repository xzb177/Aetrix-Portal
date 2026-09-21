/**
 * 当前服（多服运营）
 *
 * 面板可以同时运营多个服，后台各页默认只看「当前服」：套餐、订阅、媒体库、
 * 存储挂载、播放节点、Emby 服务入口全部跟着它走。
 *
 * 服务端的 `SystemConfig['active_realm_id']` 是权威来源（保存后所有管理员看到一致），
 * 这里只做前端缓存 + 快速切换；切服失败时回退到服务端的值，不会让页面停在错误的作用域上。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { activateRealm, fetchRealms } from '@/api/admin'
import type { RealmRow, RealmSummary } from '@/types'

const LAST_REALM_KEY = 'admin_active_realm'

export const useRealmStore = defineStore('realm', () => {
  const realms = ref<RealmRow[]>([])
  const summary = ref<RealmSummary | null>(null)
  const activeId = ref<number | null>(null)
  const loading = ref(false)
  const loaded = ref(false)

  /** 当前服对象（列表还没加载时返回 null） */
  function activeRealm(): RealmRow | null {
    return realms.value.find((r) => r.id === activeId.value) || null
  }

  const activeName = () => activeRealm()?.name || ''

  /** 只取列表（不切服）：Layout 启动时调用 */
  async function load(): Promise<void> {
    loading.value = true
    try {
      const data = await fetchRealms()
      realms.value = data.realms
      summary.value = data.summary
      activeId.value = data.active_realm_id
      try {
        localStorage.setItem(LAST_REALM_KEY, String(data.active_realm_id))
      } catch {
        /* 隐私模式等场景忽略 */
      }
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  /**
   * 切换当前服：服务端落库后再刷新列表，避免多管理员各看各的。
   *
   * 注意「当前服」与「启用/停用」是两件事（`is_active` 指后者），切服不改任何服的启停状态，
   * 所以这里只更新 `activeId`，再拉一次列表让统计数字保持真实。
   */
  async function switchTo(realmId: number): Promise<void> {
    if (realmId === activeId.value) return
    const data = await activateRealm(realmId)
    activeId.value = data.active_realm_id
    summary.value = data.summary
    try {
      localStorage.setItem(LAST_REALM_KEY, String(data.active_realm_id))
    } catch {
      /* 忽略 */
    }
    await refresh().catch(() => {
      /* 列表刷新失败不影响已经切过去的服务端状态 */
    })
  }

  /** 重新拉取（服管理页改动后调用） */
  async function refresh(): Promise<void> {
    const data = await fetchRealms()
    realms.value = data.realms
    summary.value = data.summary
    activeId.value = data.active_realm_id
  }

  return { realms, summary, activeId, loading, loaded, activeRealm, activeName, load, switchTo, refresh }
})
