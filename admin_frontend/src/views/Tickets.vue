<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Ticket, Clock, CheckCircle, AlertCircle, XCircle, Filter } from 'lucide-vue-next'
import GlassCard from '@/components/glass/GlassCard.vue'
import StatCard from '@/components/glass/StatCard.vue'
import SectionHeader from '@/components/glass/SectionHeader.vue'
import ListRow from '@/components/glass/ListRow.vue'
import FilterDrawer, { type FilterItem } from '@/components/glass/FilterDrawer.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'

const router = useRouter()

interface Ticket {
  id: number
  title: string
  status: 'open' | 'pending' | 'resolved' | 'closed'
  priority: 'low' | 'medium' | 'high'
  created_at: string
  user_name: string
  description?: string
}

const tickets = ref<Ticket[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const showFilterDrawer = ref(false)

// 统计数据
const ticketStats = computed(() => {
  const total = tickets.value.length
  const open = tickets.value.filter(t => t.status === 'open').length
  const pending = tickets.value.filter(t => t.status === 'pending').length
  const resolved = tickets.value.filter(t => t.status === 'resolved').length
  const closed = tickets.value.filter(t => t.status === 'closed').length
  return { total, open, pending, resolved, closed }
})

// 筛选项
const filterItems: FilterItem[] = [
  {
    key: 'status',
    label: '状态',
    type: 'select',
    placeholder: '全部状态',
    options: [
      { label: '待处理', value: 'open' },
      { label: '处理中', value: 'pending' },
      { label: '已解决', value: 'resolved' },
      { label: '已关闭', value: 'closed' },
    ],
  },
  {
    key: 'priority',
    label: '优先级',
    type: 'select',
    placeholder: '全部优先级',
    options: [
      { label: '高', value: 'high' },
      { label: '中', value: 'medium' },
      { label: '低', value: 'low' },
    ],
  },
]

// 状态配置
const getStatusConfig = (status: string) => {
  const configs = {
    open: { label: '待处理', class: 'text-danger', icon: AlertCircle },
    pending: { label: '处理中', class: 'text-warning', icon: Clock },
    resolved: { label: '已解决', class: 'text-success', icon: CheckCircle },
    closed: { label: '已关闭', class: 'text-tertiary', icon: XCircle },
  }
  return configs[status as keyof typeof configs] || configs.open
}

// 优先级配置
const getPriorityConfig = (priority: string) => {
  const configs = {
    high: { label: '高', class: 'bg-danger-bg text-danger' },
    medium: { label: '中', class: 'bg-warning-bg text-warning' },
    low: { label: '低', class: 'bg-info-bg text-info' },
  }
  return configs[priority as keyof typeof configs] || configs.low
}

// 格式化时间
const formatTime = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000)

  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 604800) return `${Math.floor(diff / 86400)}天前`

  return date.toLocaleDateString('zh-CN')
}

// 加载工单列表
const loadTickets = async () => {
  loading.value = true
  error.value = null
  try {
    // TODO: 实际 API 调用
    // const response = await api.get('/api/admin/tickets')
    // tickets.value = response.data

    // 模拟数据
    await new Promise(resolve => setTimeout(resolve, 1000))
    tickets.value = []
  } catch (err: any) {
    console.error('加载工单失败:', err)
    error.value = '加载工单列表失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

// 工单点击
const handleTicketClick = (ticket: Ticket) => {
  router.push(`/tickets/${ticket.id}`)
}

// 筛选处理
const handleFilter = (data: Record<string, any>) => {
  console.log('筛选条件:', data)
  // TODO: 应用筛选
  loadTickets()
}

// 重置筛选
const handleResetFilter = () => {
  loadTickets()
}

onMounted(() => {
  loadTickets()
})
</script>

<template>
  <PageContainer class="tickets-page">
    <!-- 筛选按钮 -->
    <div class="filter-actions">
      <button class="btn-filter" @click="showFilterDrawer = true">
        <Filter :size="16" />
        <span>筛选</span>
      </button>
    </div>

    <!-- 加载状态 -->
    <LoadingState v-if="loading && !error" type="skeleton" :rows="5" />

    <!-- 错误状态 -->
    <ErrorState
      v-else-if="error"
      title="加载失败"
      :message="error"
      show-retry
      @retry="loadTickets"
    />

    <!-- 正常内容 -->
    <template v-else>
      <!-- 统计卡片 -->
      <div class="stats-grid">
        <StatCard
          :value="ticketStats.total"
          label="总工单"
          :icon="Ticket"
          icon-color="primary"
        />
        <StatCard
          :value="ticketStats.open"
          label="待处理"
          :icon="AlertCircle"
          icon-color="danger"
        />
        <StatCard
          :value="ticketStats.pending"
          label="处理中"
          :icon="Clock"
          icon-color="warning"
        />
        <StatCard
          :value="ticketStats.resolved"
          label="已解决"
          :icon="CheckCircle"
          icon-color="success"
        />
      </div>

      <!-- 工单列表 -->
      <GlassCard padding="none">
        <SectionHeader
          title="工单列表"
          :badge="ticketStats.total"
          badge-type="primary"
        />

        <!-- 空状态 -->
        <EmptyState
          v-if="tickets.length === 0"
          :icon="Ticket"
          title="暂无工单"
          description="当前没有需要处理的工单"
        />

        <!-- 列表 -->
        <div v-else class="ticket-list">
          <ListRow
            v-for="ticket in tickets"
            :key="ticket.id"
            :title="ticket.title"
            :subtitle="ticket.user_name + ' · ' + formatTime(ticket.created_at)"
            :icon="getStatusConfig(ticket.status).icon"
            :badge="getPriorityConfig(ticket.priority).label"
            :badge-type="ticket.priority === 'high' ? 'danger' : ticket.priority === 'medium' ? 'warning' : 'info'"
            @click="handleTicketClick(ticket)"
          >
            <template #right>
              <span :class="['status-badge', getStatusConfig(ticket.status).class]">
                {{ getStatusConfig(ticket.status).label }}
              </span>
            </template>
          </ListRow>
        </div>
      </GlassCard>
    </template>

    <!-- 筛选抽屉 -->
    <FilterDrawer
      v-model="showFilterDrawer"
      title="筛选工单"
      :items="filterItems"
      @filter="handleFilter"
      @reset="handleResetFilter"
    />
  </PageContainer>
</template>

<style scoped>
.tickets-page {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* 筛选操作区 */
.filter-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 0.75rem;
}

.btn-filter {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 150ms ease;
}

.btn-filter:active {
  background: var(--bg-card-hover);
  transform: scale(0.97);
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

@media (min-width: 640px) {
  .stats-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

/* 工单列表 */
.ticket-list {
  display: flex;
  flex-direction: column;
}

.status-badge {
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}
</style>
