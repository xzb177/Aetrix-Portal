/**
 * 全站导航的唯一一份定义
 *
 * 用户端此前是两套并行导航：桌面顶栏写着一组文字链接，移动端底部坞又是另一组
 * 条目（名字、顺序都不同），合起来就是「一个像 App 的底部栏 + 一个像网页的
 * 顶栏」，看着像两个导航、两套产品。这里收敛成一份：
 *
 *   primaryNav    主导航（5 个高频目的地）：桌面渲染在顶栏，移动端渲染在底部坞，
 *                 条目 / 顺序 / 图标完全一致 —— 同一个导航，只是摆放位置不同。
 *   menuSections  长尾入口（低频功能）：全断点统一收进顶栏头像菜单，
 *                 顶栏在移动端不再有第二个抽屉，避免「同一批链接出现两遍」。
 *
 * 改导航只改这里：顶栏、底部坞、头像菜单三处同时生效，不会再出现
 * 「新页面只加进了一处」这种漏入口。
 */

import type { Component } from 'vue'
import {
  CalendarCheck, Clapperboard, Film, Gift, Heart, History,
  Inbox, MessageSquareDashed, Search, Ticket, User, Wallet,
} from 'lucide-vue-next'

export interface NavItem {
  /** 显示名（顶栏与底部坞共用） */
  name: string
  /** 路由内路径，必须已在 src/router/index.ts 声明 */
  path: string
  icon: Component
}

export interface NavGroup {
  title: string
  items: NavItem[]
}

/** 主导航：顶栏（≥900px）与底部导航坞（≤900px）共用同一份 */
export const primaryNav: NavItem[] = [
  { name: '首页', path: '/', icon: Clapperboard },
  { name: '媒体库', path: '/media', icon: Film },
  { name: '收藏', path: '/favorites', icon: Heart },
  { name: '观看记录', path: '/history', icon: History },
  { name: '我的', path: '/profile', icon: User },
]

/** 长尾入口：头像菜单里的分组，桌面与移动端一致 */
export const menuSections: NavGroup[] = [
  {
    title: '账号与经济',
    items: [
      { name: '我的钱包', path: '/wallet', icon: Wallet },
      { name: '每日签到', path: '/checkin', icon: CalendarCheck },
      { name: '邀请返利', path: '/invite', icon: Gift },
    ],
  },
  {
    title: '互动与支持',
    items: [
      { name: '搜索片名', path: '/search', icon: Search },
      { name: '求片中心', path: '/request', icon: MessageSquareDashed },
      { name: '工单支持', path: '/tickets', icon: Ticket },
      { name: '消息中心', path: '/messages', icon: Inbox },
    ],
  },
]
