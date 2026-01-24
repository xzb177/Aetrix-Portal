/**
 * 导航路由映射表
 * 定义每个路由对应的 Tab、分组、图标等信息
 */

import type { TabKey } from '@/config/tabs'

export interface NavRoute {
  path: string
  name: string
  tab: TabKey
  group: string
  icon: string
}

export const NAV_ROUTES: NavRoute[] = [
  // 首页 Tab
  { path: '/', name: '数据概览', tab: 'home', group: '数据统计', icon: 'chart' },
  { path: '/heatmap', name: '播放热力图', tab: 'home', group: '数据统计', icon: 'heatmap' },
  { path: '/popular-content', name: '热门内容', tab: 'home', group: '数据统计', icon: 'fire' },
  { path: '/user-behavior', name: '用户行为', tab: 'home', group: '数据统计', icon: 'trending' },

  // 用户 Tab
  { path: '/portal-users', name: '门户用户', tab: 'users', group: '用户管理', icon: 'users' },
  { path: '/subscriptions', name: '订阅套餐', tab: 'users', group: '用户管理', icon: 'crown' },
  { path: '/exchange-codes', name: '兑换码', tab: 'users', group: '用户管理', icon: 'ticket' },
  { path: '/invitations', name: '邀请管理', tab: 'users', group: '用户管理', icon: 'invite' },

  // Emby Tab
  { path: '/emby-servers', name: 'Emby服务器', tab: 'emby', group: 'Emby管理', icon: 'server' },
  { path: '/online-sessions', name: '在线用户', tab: 'emby', group: 'Emby管理', icon: 'online' },
  { path: '/transcoding', name: '转码监控', tab: 'emby', group: 'Emby管理', icon: 'transcode' },

  // 工单 Tab
  { path: '/tickets', name: '工单系统', tab: 'tickets', group: '工单系统', icon: 'ticket' },
  { path: '/media-requests', name: '求片管理', tab: 'tickets', group: '内容管理', icon: 'request' },

  // 设置 Tab - 系统管理
  { path: '/settings', name: '系统设置', tab: 'settings', group: '系统管理', icon: 'settings' },
  { path: '/system-config', name: '系统配置', tab: 'settings', group: '系统管理', icon: 'config' },
  { path: '/security', name: '安全设置', tab: 'settings', group: '系统管理', icon: 'shield' },
  { path: '/routes', name: '线路管理', tab: 'settings', group: '系统管理', icon: 'route' },
  { path: '/admins', name: '管理员', tab: 'settings', group: '系统管理', icon: 'admin' },
  { path: '/roles', name: '角色权限', tab: 'settings', group: '系统管理', icon: 'role' },
  { path: '/system-logs', name: '系统日志', tab: 'settings', group: '系统管理', icon: 'log' },

  // 设置 Tab - 消息通知
  { path: '/announcements', name: '公告管理', tab: 'settings', group: '消息通知', icon: 'announce' },
  { path: '/messages', name: '站内消息', tab: 'settings', group: '消息通知', icon: 'message' },

  // 设置 Tab - 支付管理
  { path: '/payment-config', name: '支付配置', tab: 'settings', group: '支付管理', icon: 'payment' },
  { path: '/payment-orders', name: '支付订单', tab: 'settings', group: '支付管理', icon: 'order' },
]

/**
 * 根据路径获取对应的 Tab
 */
export function getTabByPath(path: string): TabKey {
  // 精确匹配
  const exact = NAV_ROUTES.find(r => r.path === path)
  if (exact) return exact.tab

  // 前缀匹配（处理详情页等）
  const prefix = NAV_ROUTES.find(r => {
    if (r.path.includes(':id')) {
      const basePattern = r.path.split('/:')[0]
      return path.startsWith(basePattern + '/')
    }
    return false
  })
  if (prefix) return prefix.tab

  return 'home'
}

/**
 * 获取指定 Tab 的默认路由
 */
export function getDefaultRouteForTab(tab: TabKey): string {
  const routes = NAV_ROUTES.filter(r => r.tab === tab)
  return routes[0]?.path || '/'
}

/**
 * 获取抽屉菜单分组数据
 */
export interface DrawerGroup {
  name: string
  items: NavRoute[]
}

export function getDrawerGroups(): DrawerGroup[] {
  const groups: Record<string, NavRoute[]> = {}

  for (const route of NAV_ROUTES) {
    if (!groups[route.group]) {
      groups[route.group] = []
    }
    groups[route.group]!.push(route)
  }

  return Object.entries(groups).map(([name, items]) => ({ name, items }))
}
