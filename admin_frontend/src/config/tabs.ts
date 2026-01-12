/**
 * 管理后台 Tab 配置
 * 底部 Tab 导航的 5 个高频入口
 */

import type { Tab } from '@/components/navigation/TabBar.vue'

export const ADMIN_TABS: Tab[] = [
  {
    key: 'home',
    label: '首页',
    icon: '/admin/icons/tab-home.svg',
    iconActive: '/admin/icons/tab-home-active.svg',
    defaultRoute: '/'
  },
  {
    key: 'users',
    label: '用户',
    icon: '/admin/icons/tab-users.svg',
    iconActive: '/admin/icons/tab-users-active.svg',
    defaultRoute: '/portal-users'
  },
  {
    key: 'emby',
    label: 'Emby',
    icon: '/admin/icons/tab-emby.svg',
    iconActive: '/admin/icons/tab-emby-active.svg',
    defaultRoute: '/emby-servers'
  },
  {
    key: 'tickets',
    label: '工单',
    icon: '/admin/icons/tab-tickets.svg',
    iconActive: '/admin/icons/tab-tickets-active.svg',
    defaultRoute: '/tickets'
  },
  {
    key: 'settings',
    label: '设置',
    icon: '/admin/icons/tab-settings.svg',
    iconActive: '/admin/icons/tab-settings-active.svg',
    defaultRoute: '/settings'
  }
]

export type TabKey = 'home' | 'users' | 'emby' | 'tickets' | 'settings'
