<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { CreditCard, RefreshCw, Search, Filter, DollarSign, Menu, Calendar, User, Package } from 'lucide-vue-next'
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
  pending_orders: number
  paid_orders: number
  total_revenue: number
  today_revenue: number
  month_revenue: number
}

const loading = ref(false)
const orders = ref<Order[]>([])
const stats = ref<Stats>({
  total_orders: 0,
  pending_orders: 0,
  paid_orders: 0,
  total_revenue: 0,
  today_revenue: 0,
  month_revenue: 0
})

const searchQuery = ref('')
const statusFilter = ref('all')
const refreshing = ref(false)
const showMoreMenu = ref(false)

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
    orders.value = ordersRes.orders
    stats.value = statsRes
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

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const formatDateShort = (dateStr: string) => {
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
  <div class="payment-orders-page page-container">
    <!-- 顶部栏 -->
    <div class="top-bar">
      <div class="top-bar-left">
        <button class="icon-btn menu-btn">
          <Menu :size="20" />
        </button>
        <CreditCard :size="22" class="top-icon" />
        <div class="top-titles">
          <h1 class="page-title">支付订单</h1>
          <p class="page-subtitle">查看和管理所有支付订单</p>
        </div>
      </div>
      <div class="top-bar-right">
        <button class="icon-btn" @click="refreshData" :class="{ spinning: refreshing }">
          <RefreshCw :size="18" />
        </button>
        <button class="icon-btn" @click="showMoreMenu = !showMoreMenu">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="1" />
            <circle cx="19" cy="12" r="1" />
            <circle cx="5" cy="12" r="1" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card mobile-card">
        <div class="stat-icon stat-blue">
          <CreditCard :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.total_orders }}</p>
          <p class="stat-label">总订单数</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-yellow">
          <CreditCard :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.pending_orders }}</p>
          <p class="stat-label">待支付</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-green">
          <CreditCard :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.paid_orders }}</p>
          <p class="stat-label">已支付</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-purple">
          <DollarSign :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">¥{{ stats.total_revenue.toFixed(2) }}</p>
          <p class="stat-label">总收入</p>
        </div>
      </div>
    </div>

    <!-- 收入统计 -->
    <div class="revenue-card mobile-card">
      <h3 class="section-title">收入统计</h3>
      <div class="revenue-items">
        <div class="revenue-item">
          <div class="revenue-info">
            <span class="revenue-label">今日收入</span>
            <span class="revenue-value revenue-today">¥{{ stats.today_revenue.toFixed(2) }}</span>
          </div>
          <div class="revenue-bar">
            <div class="revenue-fill revenue-today" :style="{ width: `${Math.min((stats.today_revenue / (stats.total_revenue || 1)) * 100, 100)}%` }"></div>
          </div>
        </div>
        <div class="revenue-item">
          <div class="revenue-info">
            <span class="revenue-label">本月收入</span>
            <span class="revenue-value revenue-month">¥{{ stats.month_revenue.toFixed(2) }}</span>
          </div>
          <div class="revenue-bar">
            <div class="revenue-fill revenue-month" :style="{ width: `${Math.min((stats.month_revenue / (stats.total_revenue || 1)) * 100, 100)}%` }"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-card mobile-card">
      <div class="search-box">
        <Search :size="18" class="search-icon" />
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
        <span class="result-count">共 {{ filteredOrders.length }} 条</span>
      </div>
    </div>

    <!-- 移动端卡片列表 -->
    <div class="order-cards mobile-only">
      <div
        v-for="order in filteredOrders"
        :key="order.id"
        class="order-card mobile-card"
      >
        <div class="order-card-header">
          <div class="order-id-wrapper">
            <CreditCard :size="16" class="order-icon" />
            <code class="order-id-short">{{ order.order_id.slice(-8) }}</code>
          </div>
          <span class="status-badge" :class="getStatusClass(order.status)">
            {{ getStatusText(order.status) }}
          </span>
        </div>

        <div class="order-card-body">
          <div class="order-info-row">
            <User :size="14" class="info-icon" />
            <span class="info-label">用户</span>
            <span class="info-value">{{ order.username }}</span>
          </div>
          <div class="order-info-row">
            <Package :size="14" class="info-icon" />
            <span class="info-label">套餐</span>
            <span class="info-value">{{ order.plan_name }}</span>
          </div>
          <div class="order-info-row">
            <Calendar :size="14" class="info-icon" />
            <span class="info-label">创建时间</span>
            <span class="info-value">{{ formatDateShort(order.created_at) }}</span>
          </div>
        </div>

        <div class="order-card-footer">
          <div class="order-amount">{{ formatAmount(order.amount) }}</div>
          <span class="payment-method">{{ order.payment_method }}</span>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!filteredOrders.length && !loading" class="empty-state">
        <CreditCard :size="48" />
        <p>暂无订单记录</p>
      </div>
    </div>

    <!-- 桌面端表格 -->
    <div class="table-wrapper desktop-only">
      <table class="orders-table">
        <thead>
          <tr>
            <th>订单号</th>
            <th>用户</th>
            <th>套餐</th>
            <th>金额</th>
            <th>支付方式</th>
            <th>状态</th>
            <th>支付时间</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!filteredOrders.length && !loading">
            <td colspan="8" class="empty-state">
              <CreditCard :size="48" />
              <p>暂无订单记录</p>
            </td>
          </tr>
          <tr v-for="order in filteredOrders" :key="order.id" class="order-row">
            <td class="order-id">
              <code>{{ order.order_id }}</code>
            </td>
            <td>{{ order.username }}</td>
            <td>{{ order.plan_name }}</td>
            <td class="amount">{{ formatAmount(order.amount) }}</td>
            <td>
              <span class="payment-method">{{ order.payment_method }}</span>
            </td>
            <td>
              <span class="status-badge" :class="getStatusClass(order.status)">
                {{ getStatusText(order.status) }}
              </span>
            </td>
            <td class="time">{{ formatDate(order.paid_at) }}</td>
            <td class="time">{{ formatDate(order.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.payment-orders-page {
  background: var(--bg-primary);
}

/* ===== 顶部栏 ===== */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
}

.top-bar-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.menu-btn {
  display: none;
}

@media (max-width: 1024px) {
  .menu-btn {
    display: flex;
  }
}

.top-icon {
  color: var(--primary);
}

.top-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
  line-height: var(--line-height-tight);
}

.page-subtitle {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin: 0;
}

.top-bar-right {
  display: flex;
  gap: var(--space-2);
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: var(--glass-gradient);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.icon-btn:active {
  transform: scale(0.95);
  background: var(--bg-card-hover);
}

.icon-btn.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ===== 统计卡片 ===== */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}

@media (min-width: 640px) {
  .stats-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.stat-blue {
  background: linear-gradient(135deg, #3B82F6, #2563EB);
}

.stat-yellow {
  background: linear-gradient(135deg, #F59E0B, #D97706);
}

.stat-green {
  background: linear-gradient(135deg, #22C55E, #16A34A);
}

.stat-purple {
  background: linear-gradient(135deg, #8B5CF6, #7C3AED);
}

.stat-content {
  flex: 1;
  min-width: 0;
}

.stat-value {
  font-size: var(--font-size-4xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  margin: 0;
  line-height: 1;
}

.stat-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin: var(--space-1) 0 0 0;
}

/* ===== 收入统计 ===== */
.revenue-card {
  padding: var(--space-4);
}

.section-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0 0 var(--space-3) 0;
}

.revenue-items {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.revenue-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.revenue-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.revenue-label {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.revenue-value {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
}

.revenue-today {
  color: var(--success);
}

.revenue-month {
  color: var(--primary);
}

.revenue-bar {
  height: 6px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
  overflow: hidden;
}

.revenue-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.revenue-fill.revenue-today {
  background: var(--success);
}

.revenue-fill.revenue-month {
  background: var(--primary);
}

/* ===== 筛选栏 ===== */
.filter-card {
  padding: var(--space-4);
}

.search-box {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
}

.search-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.filter-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  background: var(--bg-input);
  outline: none;
  cursor: pointer;
}

.result-count {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

/* ===== 移动端卡片列表 ===== */
.mobile-only {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.order-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.order-card {
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.order-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.order-id-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.order-icon {
  color: var(--primary);
}

.order-id-short {
  font-family: monospace;
  font-size: var(--font-size-sm);
  background: var(--primary-bg);
  color: var(--primary);
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
}

.order-card-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.order-info-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.info-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
  width: 16px;
}

.info-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  min-width: 60px;
}

.info-value {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.order-amount {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
}

.payment-method {
  font-size: var(--font-size-xs);
  padding: 2px var(--space-2);
  background: rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
}

/* ===== 桌面端表格 ===== */
.desktop-only {
  display: none;
}

.table-wrapper {
  background: var(--glass-gradient);
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

@media (min-width: 1025px) {
  .mobile-only {
    display: none;
  }

  .desktop-only {
    display: block;
  }
}

.orders-table {
  width: 100%;
  border-collapse: collapse;
}

.orders-table th {
  text-align: left;
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border-subtle);
  white-space: nowrap;
}

.orders-table td {
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.order-row:last-child td {
  border-bottom: none;
}

.order-row:hover {
  background: rgba(255, 255, 255, 0.02);
}

.order-id code {
  font-family: monospace;
  font-size: var(--font-size-xs);
  background: var(--primary-bg);
  padding: 2px var(--space-2);
  border-radius: 4px;
  color: var(--primary);
}

.amount {
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.time {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

/* ===== 状态标签 ===== */
.status-badge {
  display: inline-block;
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.status-paid {
  background: var(--success-bg);
  color: var(--success);
}

.status-pending {
  background: var(--warning-bg);
  color: var(--warning);
}

.status-failed {
  background: var(--danger-bg);
  color: var(--danger);
}

.status-cancelled {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-tertiary);
}

/* ===== 空状态 ===== */
.empty-state {
  text-align: center;
  padding: var(--space-6) var(--space-4);
  color: var(--text-tertiary);
}

.empty-state svg {
  margin-bottom: var(--space-3);
  opacity: 0.5;
}

.empty-state p {
  margin: 0;
}

/* ===== 响应式 ===== */
@media (max-width: 640px) {
  .filter-row {
    flex-wrap: wrap;
  }

  .filter-select {
    flex: 1;
    min-width: 120px;
  }

  .result-count {
    width: 100%;
    text-align: center;
  }

  .stats-grid {
    grid-template-columns: 1fr 1fr;
  }

  .stat-value {
    font-size: var(--font-size-3xl);
  }
}
</style>
