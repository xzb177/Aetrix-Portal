/**
 * 导航逻辑 composable
 * 统一处理 Tab 高亮、抽屉高亮、路由跳转等逻辑
 */

import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getTabByPath, getDefaultRouteForTab } from '@/routes/navigation'
import { ADMIN_TABS, type TabKey } from '@/config/tabs'

export function useNavigation() {
  const router = useRouter()
  const route = useRoute()

  // 当前激活的 Tab
  const activeTab = computed<TabKey>(() => {
    return getTabByPath(route.path)
  })

  // 当前激活的路由路径（用于抽屉高亮）
  const activePath = computed(() => {
    return route.path
  })

  // Tab 配置
  const tabs = computed(() => ADMIN_TABS)

  /**
   * 处理 Tab 点击
   * - 如果当前已在目标 Tab 的某个页面，不跳转
   * - 否则跳转到该 Tab 的默认页面
   */
  const handleTabClick = (tabKey: TabKey) => {
    const currentTab = getTabByPath(route.path)

    // 已在该 Tab，不做处理
    if (currentTab === tabKey) {
      return
    }

    // 跳转到目标 Tab 的默认页面
    const targetRoute = getDefaultRouteForTab(tabKey)
    router.push(targetRoute)
  }

  /**
   * 处理抽屉菜单项点击
   */
  const handleDrawerClick = (path: string) => {
    router.push(path)
  }

  return {
    activeTab,
    activePath,
    tabs,
    handleTabClick,
    handleDrawerClick
  }
}
