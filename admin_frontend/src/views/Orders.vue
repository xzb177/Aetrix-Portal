<script setup lang="ts">
/**
 * 运营管理：经济总览 + 订单管理 + 人工补单
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, Search, CircleCheck, Wallet } from 'lucide-vue-next'
import {
  fetchEconomyStats,
  fetchEconomyOrders,
  markOrderPaid,
  type EconomyStats,
  type OrderRow,
} from '@/api/economy'

const loading = ref(false)
const stats = ref<EconomyStats | null>(null)
const orders = ref<OrderRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const statusFilter = ref('')
const kindFilter = ref('')
const search = ref('')

async function load() {
  loading.value = true
  try {
    const [s, o] = await Promise.all([
      fetchEconomyStats().catch(() => null),
      fetchEconomyOrders({
        status_filter: statusFilter.value || undefined,
        kind: kindFilter.value || undefined,
        search: search.value || undefined,
        limit: pageSize,
        offset: (page.value - 1) * pageSize,
      }),
    ])
    stats.value = s
    orders.value = o.orders
    total.value = o.total
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function handleMarkPaid(row: OrderRow) {
  await ElMessageBox.confirm(
    `确认将订单 ${row.order_id} 标记为已支付并履约？用于线下收款或回调丢失的补单。`,
    '人工补单',
    { confirmButtonText: '确认补单', cancelButtonText: '取消', type: 'warning' },
  )
  try {
    await markOrderPaid(row.order_id)
    ElMessage.success('补单成功，已发货')
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '补单失败')
  }
}

function fmtTime(iso?: string | null) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : '—'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-title">运营 · 订单</h2>
        <p class="page-sub">充值/订阅订单、营收统计与人工补单</p>
      </div>
      <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
    </header>

    <!-- 统计卡 -->
    <div v-if="stats" class="stat-cards">
      <div class="stat-card">
        <span class="stat-label">累计充值积分</span>
        <span class="stat-value">{{ stats.total_points.toLocaleString() }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">今日签到人次</span>
        <span class="stat-value">{{ stats.checkins_today }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">待支付订单</span>
        <span class="stat-value warn">{{ stats.orders.pending }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">累计营收 (¥)</span>
        <span class="stat-value">{{ stats.orders.revenue.toFixed(2) }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">兑换码已用 / 总数</span>
        <span class="stat-value">{{ stats.exchange_codes.used }} / {{ stats.exchange_codes.total }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">邀请总数</span>
        <span class="stat-value">{{ stats.invitations }}</span>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filters">
      <el-input
        v-model="search"
        placeholder="搜索订单号 / 用户名"
        clearable
        style="width: 220px"
        @keyup.enter="page = 1; load()"
      >
        <template #prefix><Search :size="14" /></template>
      </el-input>
      <el-select v-model="kindFilter" placeholder="类型" clearable style="width: 130px" @change="page = 1; load()">
        <el-option label="充值" value="recharge" />
        <el-option label="订阅" value="subscription" />
      </el-select>
      <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 130px" @change="page = 1; load()">
        <el-option label="待支付" value="pending" />
        <el-option label="已支付" value="paid" />
      </el-select>
      <el-button type="primary" @click="page = 1; load()">查询</el-button>
    </div>

    <!-- 订单表 -->
    <el-table :data="orders" v-loading="loading" stripe>
      <el-table-column prop="order_id" label="订单号" width="220" show-overflow-tooltip />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="row.kind === 'recharge' ? 'success' : 'primary'" size="small">
            {{ row.kind === 'recharge' ? '充值' : '订阅' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="item_name" label="商品" min-width="160" show-overflow-tooltip />
      <el-table-column prop="username" label="用户" width="120" />
      <el-table-column label="金额" width="100">
        <template #default="{ row }">¥ {{ Number(row.amount).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="payment_method" label="支付方式" width="100" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'paid' ? 'success' : 'warning'" size="small">
            {{ row.status === 'paid' ? '已支付' : '待支付' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="160">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status !== 'paid'"
            size="small"
            type="success"
            :icon="CircleCheck"
            @click="handleMarkPaid(row)"
          >补单</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无订单" :image-size="72">
          <template #image><Wallet :size="42" style="color: var(--el-text-color-placeholder)" /></template>
        </el-empty>
      </template>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next, total"
      class="pager"
      @current-change="load"
    />
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }

.page-head { display: flex; align-items: flex-start; justify-content: space-between; }
.page-title { margin: 0 0 4px; font-size: 20px; font-weight: 700; }
.page-sub { margin: 0; font-size: 13px; opacity: 0.6; }

.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  background: var(--el-fill-color-light);
  border-radius: 10px;
}
.stat-label { font-size: 12px; opacity: 0.6; }
.stat-value { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stat-value.warn { color: var(--el-color-warning); }

.filters { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }

.pager { margin-top: 4px; justify-content: flex-end; }
</style>
