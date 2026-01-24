<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { CreditCard, RefreshCw, Search, Calendar, User, Package } from 'lucide-vue-next'
import request from '@/utils/request'

interface Order {
  id: number
  order_id: string
  user_id: number
  username: string
  plan_name: string
  amount: number
  payment_method: string
  status: string
  paid_at: string | null
  created_at: string
  transaction_id: string | null
}

interface Stats {
  total_orders: number
  paid_orders: number
  total_revenue: number
}

const loading = ref(false)
const orders = ref<Order[]>([])
const stats = ref<Stats>({
  total_orders: 0,
  paid_orders: 0,
  total_revenue: 0
})

const searchQuery = ref('')
const statusFilter = ref('all')
const refreshing = ref(false)

const filteredOrders = computed(() => {
  let result = orders.value

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(o =>
      o.order_id.toLowerCase().includes(query) ||
      o.username.toLowerCase().includes(query) ||
      o.plan_name.toLowerCase().includes(query)
    )
  }

  if (statusFilter.value !== 'all') {
    result = result.filter(o => o.status === statusFilter.value)
  }

  return result
})

const loadData = async () => {
  loading.value = true
  try {
    const [ordersRes, statsRes] = await Promise.all([
      request.get<{ orders: Order[] }>('/payment/orders') as any,
      request.get<Stats>('/payment/stats') as any
    ])
    orders.value = ordersRes.orders || []
    stats.value = {
      total_orders: statsRes.total_orders || 0,
      paid_orders: statsRes.paid_orders || 0,
      total_revenue: statsRes.total_revenue || 0
    }
  } catch (err) {
    console.error('加载数据失败:', err)
  } finally {
    loading.value = false
  }
}

const refreshData = async () => {
  refreshing.value = true
  try {
    await loadData()
  } finally {
    refreshing.value = false
  }
}

const getStatusClass = (status: string) => {
  switch (status) {
    case 'paid': return 'status-paid'
    case 'pending': return 'status-pending'
    case 'failed': return 'status-failed'
    case 'cancelled': return 'status-cancelled'
    default: return ''
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'paid': return '已支付'
    case 'pending': return '待支付'
    case 'failed': return '支付失败'
    case 'cancelled': return '已取消'
    default: return status
  }
}

const formatAmount = (amount: number) => {
  return `¥${amount.toFixed(2)}`
}

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="payment-orders-page">
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon stat-blue">
          <CreditCard :size="18" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.total_orders }}</p>
          <p class="stat-label">总订单</p>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon stat-green">
          <CreditCard :size="18" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.paid_orders }}</p>
          <p class="stat-label">已支付</p>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon stat-purple">
          <CreditCard :size="18" />
        </div>
        <div class="stat-content">
          <p class="stat-value">¥{{ stats.total_revenue.toFixed(0) }}</p>
          <p class="stat-label">总收入</p>
        </div>
      </div>

      <button
        class="refresh-btn"
        :class="{ spinning: refreshing }"
        @click="refreshData"
      >
        <RefreshCw :size="18" />
      </button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-card">
      <div class="search-box">
        <Search :size="16" class="search-icon" />
        <input
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="搜索订单号、用户名、套餐..."
        />
      </div>

      <div class="filter-row">
        <select v-model="statusFilter" class="filter-select">
          <option value="all">全部状态</option>
          <option value="paid">已支付</option>
          <option value="pending">待支付</option>
          <option value="failed">支付失败</option>
          <option value="cancelled">已取消</option>
        </select>
        <span class="result-count">{{ filteredOrders.length }} 条</span>
      </div>
    </div>

    <!-- 订单列表 -->
    <div class="order-list">
      <div
        v-for="order in filteredOrders"
        :key="order.id"
        class="order-card"
      >
        <div class="order-header">
          <div class="order-id">
            <code>{{ order.order_id.slice(-8) }}</code>
          </div>
          <span class="status-badge" :class="getStatusClass(order.status)">
            {{ getStatusText(order.status) }}
          </span>
        </div>

        <div class="order-body">
          <div class="order-info">
            <User :size="14" />
            <span>{{ order.username }}</span>
          </div>
          <div class="order-info">
            <Package :size="14" />
            <span>{{ order.plan_name }}</span>
          </div>
          <div class="order-info">
            <Calendar :size="14" />
            <span>{{ formatDate(order.created_at) }}</span>
          </div>
        </div>

        <div class="order-footer">
          <span class="order-amount">{{ formatAmount(order.amount) }}</span>
          <span class="payment-method">{{ order.payment_method || '-' }}</span>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!filteredOrders.length && !loading" class="empty-state">
        <CreditCard :size="40" />
        <p>暂无订单</p>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <RefreshCw :size="24" class="spinning" />
        <p>加载中...</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.payment-orders-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr) auto;
  gap: 0.75rem;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  background: var(--bg-card, white);
  border-radius: 10px;
  border: 1px solid var(--border-subtle, #e8edf3);
}

.stat-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.stat-blue { background: linear-gradient(135deg, #3B82F6, #2563EB); }
.stat-green { background: linear-gradient(135deg, #22C55E, #16A34A); }
.stat-purple { background: linear-gradient(135deg, #8B5CF6, #7C3AED); }

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
  margin: 0;
  line-height: 1;
}

.stat-label {
  font-size: 0.75rem;
  color: var(--text-tertiary, #94a3b8);
  margin: 0.25rem 0 0 0;
}

.refresh-btn {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-card, white);
  border: 1px solid var(--border-subtle, #e8edf3);
  border-radius: 10px;
  color: var(--text-secondary, #64748b);
  cursor: pointer;
  transition: all 0.2s;
}

.refresh-btn:hover {
  color: var(--primary, #673AB7);
  border-color: var(--primary, #673AB7);
}

.refresh-btn.spinning svg {
  animation: spin 1s linear infinite;
}

/* 筛选栏 */
.filter-card {
  background: var(--bg-card, white);
  border-radius: 10px;
  padding: 1rem;
  border: 1px solid var(--border-subtle, #e8edf3);
}

.search-box {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-input, #f8fafc);
  border: 1px solid var(--border-subtle, #e2e8f0);
  border-radius: 8px;
  margin-bottom: 0.75rem;
}

.search-icon {
  color: var(--text-tertiary, #94a3b8);
}

.search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 0.875rem;
  color: var(--text-primary, #1a1a2e);
}

.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.filter-select {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-subtle, #e2e8f0);
  border-radius: 8px;
  font-size: 0.875rem;
  color: var(--text-primary, #1a1a2e);
  background: var(--bg-input, #f8fafc);
  outline: none;
}

.result-count {
  font-size: 0.75rem;
  color: var(--text-tertiary, #94a3b8);
}

/* 订单列表 */
.order-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.order-card {
  background: var(--bg-card, white);
  border-radius: 10px;
  padding: 1rem;
  border: 1px solid var(--border-subtle, #e8edf3);
}

.order-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.order-id code {
  font-family: monospace;
  font-size: 0.75rem;
  background: var(--primary-bg, rgba(103, 58, 183, 0.1));
  color: var(--primary, #673AB7);
  padding: 2px 6px;
  border-radius: 4px;
}

.order-body {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.order-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: var(--text-secondary, #64748b);
}

.order-info svg {
  flex-shrink: 0;
}

.order-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-subtle, #f1f5f9);
}

.order-amount {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
}

.payment-method {
  font-size: 0.75rem;
  padding: 2px 6px;
  background: var(--bg-secondary, #f8fafc);
  border-radius: 4px;
  color: var(--text-tertiary, #94a3b8);
}

/* 状态标签 */
.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-paid {
  background: rgba(34, 197, 94, 0.1);
  color: #22C55E;
}

.status-pending {
  background: rgba(245, 158, 11, 0.1);
  color: #F59E0B;
}

.status-failed {
  background: rgba(239, 68, 68, 0.1);
  color: #EF4444;
}

.status-cancelled {
  background: rgba(148, 163, 184, 0.1);
  color: #94A3B8;
}

/* 空状态和加载状态 */
.empty-state, .loading-state {
  text-align: center;
  padding: 2rem;
  color: var(--text-tertiary, #94a3b8);
}

.empty-state svg, .loading-state svg {
  margin-bottom: 0.5rem;
  opacity: 0.5;
}

.empty-state p, .loading-state p {
  margin: 0;
  font-size: 0.875rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 移动端适配 */
@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .refresh-btn {
    grid-column: span 2;
    width: 100%;
    height: 36px;
  }
}
</style>
