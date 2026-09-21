<script setup lang="ts">
/**
 * 运营管理：经济总览 + 订单管理 + 人工补单
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, Search, CircleCheck, Wallet } from 'lucide-vue-next'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

/** 手机卡片：商品名为标题，金额/状态/用户/时间做键值行，订单号收进详情（太长会撑满一行） */
const columns: DataColumn[] = [
  { key: 'item_name', label: '商品', minWidth: 170, mobile: 'title' },
  { key: 'order_id', label: '订单号', width: 220, mobile: 'hide' },
  { key: 'kind', label: '类型', width: 90 },
  { key: 'amount', label: '金额', width: 110 },
  { key: 'username', label: '用户', width: 120 },
  { key: 'status', label: '状态', width: 96 },
  { key: 'payment_method', label: '支付方式', width: 110, mobile: 'hide' },
  { key: 'created_at', label: '创建时间', width: 160 },
  { key: 'actions', label: '操作', width: 110, fixed: 'right', align: 'right' },
]
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
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">订单管理</h1>
        <p class="admin-page-subtitle">充值 / 订阅订单、营收统计与人工补单</p>
      </div>
      <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- 统计卡 -->
    <div v-if="stats" class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label">累计充值积分</div>
        <div class="stat-value">{{ stats.total_points.toLocaleString() }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">今日签到人次</div>
        <div class="stat-value">{{ stats.checkins_today }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">待支付订单</div>
        <div class="stat-value" :class="{ 'stat-warn': stats.orders.pending > 0 }">{{ stats.orders.pending }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">累计营收 (¥)</div>
        <div class="stat-value stat-accent">{{ stats.orders.revenue.toFixed(2) }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">兑换码已用 / 总数</div>
        <div class="stat-value">{{ stats.exchange_codes.used }} / {{ stats.exchange_codes.total }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">邀请总数</div>
        <div class="stat-value">{{ stats.invitations }}</div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="toolbar">
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

    <!-- 订单表：桌面表格 / 手机卡片 -->
    <div class="admin-card">
      <DataTable
        :rows="orders"
        :columns="columns"
        :loading="loading"
        row-key="order_id"
        empty="暂无订单"
      >
        <template #cell-item_name="{ row }">{{ row.item_name }}</template>

        <template #cell-order_id="{ row }">
          <span class="mono">{{ row.order_id }}</span>
        </template>

        <template #cell-kind="{ row }">
          <el-tag :type="row.kind === 'recharge' ? 'success' : 'primary'" size="small">
            {{ row.kind === 'recharge' ? '充值' : '订阅' }}
          </el-tag>
        </template>

        <template #cell-amount="{ row }">
          <span class="amount">¥ {{ Number(row.amount).toFixed(2) }}</span>
        </template>

        <template #cell-username="{ row }">{{ row.username }}</template>

        <template #cell-status="{ row }">
          <el-tag :type="row.status === 'paid' ? 'success' : 'warning'" size="small">
            {{ row.status === 'paid' ? '已支付' : '待支付' }}
          </el-tag>
        </template>

        <template #cell-payment_method="{ row }">{{ row.payment_method || '—' }}</template>

        <template #cell-created_at="{ row }">{{ fmtTime(row.created_at) }}</template>

        <template #cell-actions="{ row }">
          <el-button
            v-if="row.status !== 'paid'"
            size="small"
            type="success"
            plain
            @click="handleMarkPaid(row)"
          >
            <CircleCheck :size="13" style="margin-right: 3px" />补单
          </el-button>
          <span v-else class="muted done-hint">已支付</span>
        </template>

        <template #empty>
          <el-empty description="暂无订单" :image-size="72">
            <template #image><Wallet :size="42" style="color: var(--text-faint)" /></template>
          </el-empty>
        </template>
      </DataTable>
    </div>

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
.stat-warn { color: var(--warning); }
.amount { font-weight: var(--font-weight-semibold); font-variant-numeric: tabular-nums; }
.done-hint { font-size: var(--font-size-xs); }
</style>
