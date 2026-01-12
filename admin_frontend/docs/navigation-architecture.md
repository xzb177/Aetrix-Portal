# 管理后台导航重构设计

## 1. 导航信息架构

### 1.1 底部 TabBar（高频入口，5 项）

| Tab | 图标 | 默认页面 | 包含页面 |
|-----|------|----------|----------|
| **首页** | home | / (Dashboard) | 数据概览 |
| **用户** | users | /portal-users | 门户用户、订阅套餐、兑换码、邀请管理 |
| **Emby** | play | /emby-servers | Emby服务器、在线用户、转码监控 |
| **工单** | ticket | /tickets | 工单系统 |
| **设置** | settings | /settings | 系统配置、安全设置、管理员、角色权限、系统日志 |

### 1.2 侧边抽屉 DrawerNav（全量菜单）

```
├── 数据统计
│   ├── 数据概览         → Tab: 首页
│   ├── 播放热力图       → Tab: 首页
│   ├── 热门内容         → Tab: 首页
│   └── 用户行为         → Tab: 首页
│
├── 用户管理
│   ├── 门户用户         → Tab: 用户
│   ├── 订阅套餐         → Tab: 用户
│   ├── 兑换码管理       → Tab: 用户
│   └── 邀请管理         → Tab: 用户
│
├── Emby 管理
│   ├── Emby服务器       → Tab: Emby
│   ├── 在线用户         → Tab: Emby
│   └── 转码监控         → Tab: Emby
│
├── 内容管理
│   ├── 求片管理         → Tab: 工单
│   └── 公告管理         → Tab: 设置
│
├── 消息通知
│   ├── 站内消息         → Tab: 设置
│   └── 推送通知         → Tab: 设置
│
├── 工单系统
│   └── 工单列表         → Tab: 工单
│
├── 支付管理
│   ├── 支付配置         → Tab: 设置
│   └── 支付订单         → Tab: 设置
│
└── 系统管理
    ├── 系统配置         → Tab: 设置
    ├── 安全设置         → Tab: 设置
    ├── 管理员           → Tab: 设置
    ├── 角色权限         → Tab: 设置
    └── 系统日志         → Tab: 设置
```

## 2. 路由表与 Tab 映射

```typescript
// routes/navigation.ts

export interface NavRoute {
  path: string
  name: string
  tab: TabKey
  group: string
  icon: string
}

export type TabKey = 'home' | 'users' | 'emby' | 'tickets' | 'settings'

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
  { path: '/users/:id', name: '用户详情', tab: 'users', group: '用户管理', icon: 'user' },

  // Emby Tab
  { path: '/emby-servers', name: 'Emby服务器', tab: 'emby', group: 'Emby管理', icon: 'server' },
  { path: '/online-sessions', name: '在线用户', tab: 'emby', group: 'Emby管理', icon: 'online' },
  { path: '/transcoding', name: '转码监控', tab: 'emby', group: 'Emby管理', icon: 'transcode' },

  // 工单 Tab
  { path: '/tickets', name: '工单系统', tab: 'tickets', group: '工单系统', icon: 'ticket' },
  { path: '/tickets/:id', name: '工单详情', tab: 'tickets', group: '工单系统', icon: 'ticket-detail' },
  { path: '/media-requests', name: '求片管理', tab: 'tickets', group: '内容管理', icon: 'request' },

  // 设置 Tab
  { path: '/settings', name: '系统设置', tab: 'settings', group: '系统管理', icon: 'settings' },
  { path: '/system-config', name: '系统配置', tab: 'settings', group: '系统管理', icon: 'config' },
  { path: '/security', name: '安全设置', tab: 'settings', group: '系统管理', icon: 'shield' },
  { path: '/admins', name: '管理员', tab: 'settings', group: '系统管理', icon: 'admin' },
  { path: '/roles', name: '角色权限', tab: 'settings', group: '系统管理', icon: 'role' },
  { path: '/system-logs', name: '系统日志', tab: 'settings', group: '系统管理', icon: 'log' },
  { path: '/announcements', name: '公告管理', tab: 'settings', group: '消息通知', icon: 'announce' },
  { path: '/messages', name: '站内消息', tab: 'settings', group: '消息通知', icon: 'message' },
  { path: '/payment-config', name: '支付配置', tab: 'settings', group: '支付管理', icon: 'payment' },
  { path: '/payment-orders', name: '支付订单', tab: 'settings', group: '支付管理', icon: 'order' },
]
```

## 3. TabBar 配置

```typescript
// config/tabs.ts

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
```

## 4. 路由高亮规则

```typescript
// composables/useNavigation.ts

import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NAV_ROUTES, type TabKey } from '@/routes/navigation'

export function useNavigation() {
  const route = useRoute()

  // 获取当前路由对应的 Tab
  const activeTab = computed<TabKey>(() => {
    const matched = NAV_ROUTES.find(r =>
      route.path === r.path || route.path.startsWith(r.path.replace(':id', ''))
    )
    return matched?.tab || 'home'
  })

  // 获取当前路由在抽屉中的高亮 key
  const activeDrawerKey = computed(() => {
    return route.path
  })

  // Tab 点击处理：跳转到该 Tab 的默认页面
  const handleTabClick = (tab: TabKey) => {
    const tabRoutes = NAV_ROUTES.filter(r => r.tab === tab)
    // 优先跳转到当前 tab 下的当前页面（如果存在），否则跳转默认页面
    const currentInTab = tabRoutes.find(r => r.path === route.path)
    if (currentInTab) {
      return // 已在该页面，不跳转
    }
    const defaultRoute = ADMIN_TABS.find(t => t.key === tab)?.defaultRoute
    return defaultRoute || '/'
  }

  return {
    activeTab,
    activeDrawerKey,
    handleTabClick
  }
}
```

## 5. AppBar 右侧操作规则

```
┌─────────────────────────────────────────────────────┐
│ [≡]  数据概览                    [页面主操作] [⋯]    │
└─────────────────────────────────────────────────────┘

规则：
1. 只显示当前页面最重要的操作（1个按钮）
2. 次要操作折叠到"更多"菜单 [⋯]
3. 更多菜单内容：
   - 导航相关：刷新、搜索
   - 页面相关：导出、批量操作等
   - 系统相关：通知、个人设置

示例：
- 数据概览：[导出] [⋯更多（刷新、时间筛选）]
- 门户用户：[添加用户] [⋯更多（导入、导出）]
- 工单详情：[回复] [⋯更多（分配、关闭、转交）]
```

## 6. 组件拆分建议

### 6.1 新增组件

```
admin_frontend/src/components/navigation/
├── TabBar.vue              # 底部 Tab 导航（新增）
├── AppBarMoreMenu.vue      # AppBar 更多菜单（新增）
└── DrawerNav.vue           # 侧边抽屉（改造）
```

### 6.2 修改组件

```
admin_frontend/src/components/navigation/
└── AppBar.vue              # 精简右侧操作
```

### 6.3 新增配置文件

```
admin_frontend/src/
├── config/
│   └── tabs.ts             # Tab 配置
├── routes/
│   └── navigation.ts       # 导航路由映射
└── composables/
    └── useNavigation.ts    # 导航逻辑 hook
```

## 7. 高亮统一规则

| 路由 | Tab 高亮 | 抽屉高亮 |
|------|----------|----------|
| / | 首页 | 数据概览 |
| /heatmap | 首页 | 播放热力图 |
| /portal-users | 用户 | 门户用户 |
| /users/123 | 用户 | 用户详情 |
| /tickets | 工单 | 工单系统 |
| /settings | 设置 | 系统设置 |

**原则**：
1. 同一时刻只有一个高亮项
2. Tab 根据路由所属分类自动高亮
3. 抽屉根据精确路径高亮
4. 点击 Tab 跳转到该 Tab 的默认页面（不在当前页面时）
