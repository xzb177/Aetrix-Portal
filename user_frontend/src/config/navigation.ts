/**
 * 全站导航的唯一一份定义
 *
 * 用户端此前是三套并行导航：桌面顶栏写着一组文字链接，移动端底部坞又是另一组
 * 条目（名字、顺序都不同），顶栏还另有一个 ☰ 抽屉，合起来就是「一个像 App 的
 * 底部栏 + 一个像网页的顶栏」，看着像两个导航、两套产品。这里收敛成一份：
 *
 *   primaryNav    主导航（三个高频目的地）：全断点在顶栏渲染——
 *                 ≥900px 横排，≤900px 是第二行的横向滑动选项卡。
 *   menuSections  长尾入口（低频功能）：全断点统一收进顶栏头像菜单，
 *                 顶栏不再有第二个抽屉，也不再有底部导航坞。
 *
 * v2.10.0（方案 A）：收藏与观看记录原本是两个一级入口，占掉主导航 3/5 个位置，
 * 而它们本质是**媒体库的两种视图**（本站自己也保留了一份历史数据，但播放器
 * 同时承担着这些功能）。现在降级为媒体库页内的分段标签（`/media?tab=`），
 * 主导航只留 首页 / 媒体库 / 我的 三项，旧地址重定向过来，书签不失效。
 *
 * 改导航只改这里：顶栏、头像菜单两处同时生效，不会再出现
 * 「新页面只加进了一处」这种漏入口。
 */

import type { Component } from 'vue'
import {
  ArrowDownLeft, CalendarCheck, Clapperboard, Film, Gift,
  Inbox, MessageSquareDashed, Receipt, Search, Ticket, User, Wallet,
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

/** 主导航：全断点共用同一份（宽屏横排、窄屏滑动选项卡）
 *  三个就够：收藏与观看记录是媒体库内的分段（见下方注释与 /media?tab=） */
export const primaryNav: NavItem[] = [
  { name: '首页', path: '/', icon: Clapperboard },
  { name: '媒体库', path: '/media', icon: Film },
  { name: '我的', path: '/profile', icon: User },
]

/** 长尾入口：头像菜单里的分组，桌面与移动端一致 */
export const menuSections: NavGroup[] = [
  {
    title: '账号与经济',
    items: [
      { name: '我的钱包', path: '/wallet', icon: Wallet },
      // 订单与流水原来只能进钱包再点分页；直接深链到对应分页，少一步寻找
      { name: '我的订单', path: '/wallet?tab=orders', icon: Receipt },
      { name: '积分流水', path: '/wallet?tab=log', icon: ArrowDownLeft },
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
