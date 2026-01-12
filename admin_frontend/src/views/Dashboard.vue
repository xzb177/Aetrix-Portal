<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  UserPlus,
  CreditCard,
  Megaphone,
  Gift,
  Crown,
  DollarSign,
  MessageSquare,
  AlertCircle,
  Clock,
  Server,
  User,
  FileText,
  Settings as SettingsIcon,
} from 'lucide-vue-next'
import { getPortalUserStats, getTicketStats, getEmbyServers, getPaymentStats, getAdminLogs } from '@/api/portal'
import LoadingState from '@/components/feedback/LoadingState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import DashboardHeader from '@/components/dashboard/DashboardHeader.vue'
import MetricCard, { type MetricItem } from '@/components/dashboard/MetricCard.vue'
import QuickActionGrid, { type QuickActionItem } from '@/components/dashboard/QuickActionGrid.vue'
import TodoList, { type TodoItem, type RiskLevel } from '@/components/dashboard/TodoList.vue'
import ActivityTimeline, { type ActivityItem, type ActivityType } from '@/components/dashboard/ActivityTimeline.vue'

const router = useRouter()

// 数据状态
const portalStats = ref<any>(null)
const ticketStats = ref<any>(null)
const embyServers = ref<any[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const refreshing = ref(false)

// 收入统计
const revenueStats = ref({
  today: 0,
  month: 0,
})

// 日期范围
const dateRange = ref({
  start: new Date(),
  end: new Date(),
})

// 最后更新时间
const lastUpdate = ref(new Date())

// 关键指标数据
const metrics = computed<MetricItem[]>(() => {
  const vipTotal = portalStats.value?.vip_users || 0
  const totalUsers = portalStats.value?.total_users || 0
  const vipRate = totalUsers > 0 ? Math.round((vipTotal / totalUsers) * 100) : 0

  const serverOnline = embyServers.value?.filter((s) => s.is_active).length || 0
  const serverTotal = embyServers.value?.length || 0
  const serverOffline = serverTotal - serverOnline

  return [
    {
      id: 'vip',
      label: 'VIP 用户',
      value: vipTotal,
      icon: Crown,
      color: serverOffline > 0 ? 'primary' : 'success',
      route: '/portal-users?filter=vip',
      suffix: vipRate > 0 ? ` (${vipRate}%)` : '',
      trend: vipRate > 0 ? { value: `${vipRate}%`, up: true } : undefined,
    },
    {
      id: 'revenue',
      label: '今日收入',
      value: revenueStats.value.today.toLocaleString(),
      prefix: '¥',
      icon: DollarSign,
      color: 'success',
      route: '/payment-orders',
      subtitle: `本月 ¥${revenueStats.value.month.toLocaleString()}`,
    },
    {
      id: 'tickets',
      label: '待处理工单',
      value: ticketStats.value?.open || 0,
      icon: MessageSquare,
      color: (ticketStats.value?.open || 0) > 10 ? 'danger' : (ticketStats.value?.open || 0) > 0 ? 'warning' : 'info',
      route: '/tickets?status=open',
      subtitle: `共 ${ticketStats.value?.total || 0} 条`,
    },
    {
      id: 'server',
      label: 'Emby 服务器',
      value: `${serverOnline}/${serverTotal}`,
      icon: Server,
      color: serverOffline > 0 ? 'danger' : 'success',
      route: '/emby-servers',
      subtitle: serverOffline > 0 ? `${serverOffline} 台离线` : '全部正常',
    },
  ]
})

// 快捷操作
const quickActions: QuickActionItem[] = [
  { id: 'add-user', icon: UserPlus, label: '添加用户', color: 'primary', route: '/portal-users?action=add' },
  { id: 'announce', icon: Megaphone, label: '发布公告', color: 'warning', route: '/announcements?action=create' },
  { id: 'subscription', icon: CreditCard, label: '订阅管理', color: 'success', route: '/subscriptions' },
  { id: 'codes', icon: Gift, label: '兑换码', color: 'info', route: '/exchange-codes' },
]

// 待办事项
const todoItems = computed<TodoItem[]>(() => {
  const openTickets = ticketStats.value?.open || 0
  const serverOffline = (embyServers.value?.length || 0) - (embyServers.value?.filter((s) => s.is_active).length || 0)

  return [
    {
      id: 'tickets',
      title: '待处理工单',
      count: openTickets,
      icon: MessageSquare,
      riskLevel: openTickets > 10 ? ('critical' as RiskLevel) : openTickets > 0 ? ('high' as RiskLevel) : ('low' as RiskLevel),
      route: '/tickets?status=open',
      badgeText: openTickets > 0 ? `${openTickets} 条` : undefined,
    },
    {
      id: 'expiring',
      title: '即将过期用户',
      count: 0, // 需要从后端获取
      icon: Clock,
      riskLevel: 'medium' as RiskLevel,
      route: '/portal-users?filter=expiring',
      badgeText: '查看详情',
    },
    {
      id: 'server',
      title: '服务器告警',
      count: serverOffline,
      icon: AlertCircle,
      riskLevel: serverOffline > 0 ? ('critical' as RiskLevel) : ('low' as RiskLevel),
      route: '/emby-servers',
      badgeText: serverOffline > 0 ? `${serverOffline} 台离线` : undefined,
    },
    {
      id: 'pending',
      title: '待审核申请',
      count: 0, // 需要从后端获取
      icon: FileText,
      riskLevel: 'medium' as RiskLevel,
      route: '/portal-users?filter=pending',
    },
    {
      id: 'stock',
      title: '库存不足',
      count: 0, // 需要从后端获取
      icon: Gift,
      riskLevel: 'medium' as RiskLevel,
      route: '/exchange-codes?filter=low-stock',
    },
  ]
})

// 最近活动（从后端获取）
const activities = ref<ActivityItem[]>([])

// 加载数据
const loadStats = async (showRefreshLoading = false) => {
  if (showRefreshLoading) {
    refreshing.value = true
  } else {
    loading.value = true
  }
  error.value = null
  try {
    portalStats.value = await getPortalUserStats()
    ticketStats.value = await getTicketStats()
    embyServers.value = await getEmbyServers()

    // 获取收入数据
    try {
      const paymentStats = await getPaymentStats()
      revenueStats.value = {
        today: paymentStats.today_revenue || 0,
        month: paymentStats.month_revenue || 0,
      }
    } catch (err) {
      console.error('获取收入数据失败:', err)
    }

    // 获取管理员操作日志（最近活动）
    try {
      const logsRes = await getAdminLogs({ limit: 4 })
      if (logsRes.data) {
        activities.value = logsRes.data.map((log: any) => {
          // 根据 action 类型确定活动类型和图标
          let type: ActivityType = 'system'
          let icon = SettingsIcon
          let title = '系统操作'
          let description = log.action || ''
          let route: string | undefined

          // 根据操作类型映射
          switch (log.action) {
            case 'create_user':
            case 'user_created':
              type = 'user'
              icon = User
              title = '创建用户'
              description = log.details?.username || log.resource_id || ''
              break
            case 'update_user':
            case 'user_updated':
              type = 'user'
              icon = User
              title = '更新用户'
              description = log.details?.username || log.resource_id || ''
              break
            case 'delete_user':
            case 'user_deleted':
              type = 'user'
              icon = User
              title = '删除用户'
              description = log.resource_id || ''
              break
            case 'create_order':
            case 'order_created':
              type = 'order'
              icon = CreditCard
              title = '订单创建'
              description = `¥${log.details?.amount || log.resource_id || ''}`
              route = '/payment-orders'
              break
            case 'payment_success':
            case 'order_paid':
              type = 'order'
              icon = CreditCard
              title = '支付完成'
              description = `¥${log.details?.amount || ''}`
              route = '/payment-orders'
              break
            case 'create_ticket':
            case 'ticket_created':
            case 'new_ticket':
              type = 'ticket'
              icon = FileText
              title = '新工单'
              description = log.details?.subject || log.resource_id || '工单'
              route = '/tickets'
              break
            case 'reply_ticket':
            case 'ticket_replied':
              type = 'ticket'
              icon = FileText
              title = '回复工单'
              description = log.resource_id || ''
              route = '/tickets'
              break
            case 'close_ticket':
              type = 'ticket'
              icon = FileText
              title = '关闭工单'
              description = log.resource_id || ''
              route = '/tickets'
              break
            case 'create_announcement':
            case 'announcement_created':
              type = 'system'
              icon = Megaphone
              title = '发布公告'
              description = log.details?.title || log.resource_id || ''
              route = '/announcements'
              break
            case 'create_activity':
            case 'activity_created':
              type = 'system'
              icon = Gift
              title = '创建活动'
              description = log.details?.name || log.resource_id || ''
              route = '/activities'
              break
            case 'toggle_activity':
              type = 'system'
              icon = Gift
              title = '切换活动状态'
              description = log.details?.name || log.resource_id || ''
              route = '/activities'
              break
            case 'create_code':
            case 'code_created':
              type = 'order'
              icon = Gift
              title = '创建兑换码'
              description = log.details?.code || log.resource_id || ''
              route = '/exchange-codes'
              break
            case 'subscription_created':
            case 'create_subscription':
              type = 'order'
              icon = CreditCard
              title = '订阅开通'
              description = log.details?.plan || log.resource_id || ''
              break
            case 'emby_server_added':
              type = 'system'
              icon = Server
              title = '添加 Emby 服务器'
              description = log.details?.name || log.resource_id || ''
              route = '/emby-servers'
              break
            case 'emby_server_synced':
              type = 'system'
              icon = Server
              title = '同步服务器'
              description = log.details?.name || log.resource_id || ''
              route = '/emby-servers'
              break
            default:
              // 默认处理
              if (log.action.includes('user')) {
                type = 'user'
                icon = User
                title = '用户操作'
              } else if (log.action.includes('order') || log.action.includes('payment')) {
                type = 'order'
                icon = CreditCard
                title = '订单操作'
                route = '/payment-orders'
              } else if (log.action.includes('ticket')) {
                type = 'ticket'
                icon = FileText
                title = '工单操作'
                route = '/tickets'
              }
              description = `${log.admin_username} - ${log.action}`
          }

          return {
            id: String(log.id),
            type,
            title,
            description,
            timestamp: new Date(log.created_at),
            icon,
            route,
          } as ActivityItem
        })
      }
    } catch (err) {
      console.error('获取活动日志失败:', err)
      activities.value = []
    }

    lastUpdate.value = new Date()
  } catch (err: any) {
    console.error('加载统计数据失败:', err)
    error.value = '加载统计数据失败，请稍后重试'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

// 头卡刷新
const handleHeaderRefresh = () => {
  loadStats(true)
}

// 日期范围变化
const handleDateChange = (newRange: { start: Date; end: Date }) => {
  dateRange.value = newRange
  // 根据日期范围重新加载数据（需要后端支持）
  loadStats(true)
}

// 指标卡片点击
const handleMetricClick = (metric: MetricItem) => {
  if (metric.route) {
    router.push(metric.route)
  }
}

// 快捷操作点击
const handleQuickAction = (action: QuickActionItem) => {
  router.push(action.route)
}

// 待办事项点击
const handleTodoClick = (todo: TodoItem) => {
  router.push(todo.route)
}

// 活动点击
const handleActivityClick = (activity: ActivityItem) => {
  if (activity.route) {
    router.push(activity.route)
  }
}

// 查看全部活动
const handleViewAllActivities = () => {
  // 跳转到活动日志页面
  router.push('/activity-logs')
}

// 定时刷新
let refreshInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  loadStats()
  refreshInterval = setInterval(() => {
    loadStats(true)
  }, 60000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<template>
  <div class="dashboard-page">
    <!-- 加载状态 -->
    <LoadingState v-if="loading && !error" type="skeleton" :rows="5" />

    <!-- 错误状态 -->
    <ErrorState
      v-else-if="error"
      title="加载失败"
      :message="error"
      show-retry
      @retry="loadStats"
    />

    <!-- 正常内容 -->
    <template v-else>
      <!-- 第一段：头卡（日期 + 刷新 + 更新时间） -->
      <DashboardHeader
        :date-range="dateRange"
        :last-update="lastUpdate"
        :refreshing="refreshing"
        @refresh="handleHeaderRefresh"
        @date-change="handleDateChange"
      />

      <!-- 第二段：关键指标 2×2 -->
      <div class="metrics-grid">
        <MetricCard
          v-for="metric in metrics"
          :key="metric.id"
          :item="metric"
          @click="handleMetricClick"
        />
      </div>

      <!-- 第三段：快捷操作 2×2 -->
      <QuickActionGrid
        :actions="quickActions"
        :columns="2"
        @click="handleQuickAction"
      />

      <!-- 第四段：待办事项列表 -->
      <TodoList
        :items="todoItems"
        :max-items="5"
        @click="handleTodoClick"
      />

      <!-- 第五段：最近活动（可选） -->
      <ActivityTimeline
        :activities="activities"
        :max-items="4"
        @click="handleActivityClick"
        @view-all="handleViewAllActivities"
      />
    </template>
  </div>
</template>

<style scoped>
.dashboard-page {
  min-height: 100vh;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  background: var(--bg-primary);
}

/* 关键指标网格 2×2 */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}

/* 响应式 */
@media (max-width: 480px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }
}
</style>
