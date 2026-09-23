<script setup lang="ts">
/**
 * 运营管理：经济总览 + 订单管理 + 人工补单
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, Search, CircleCheck, Wallet, Ban, Undo2, ReceiptText } from 'lucide-vue-next'
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
  // 补单 / 关单 / 退款收进订单详情弹窗：行里只留一个入口（状态不同则可用动作不同）
  { key: 'actions', label: '操作', width: 100, fixed: 'right', align: 'right' },
]
import {
  fetchEconomyStats,
  fetchEconomyOrders,
  markOrderPaid,
  closeOrder,
  refundOrder,
  fetchRefundRecords,
  type EconomyStats,
  type OrderRow,
  type RefundRecord,
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

// ==================== 关单 / 退款（v2.9.0） ====================
// 以前订单只能「标记已支付」：线下多转一笔、点错套餐都没法处理，只能去改数据库。
// 现在：待支付 → 关闭（作废）；已支付 → 退款（默认按账本回滚积分/会员天数）。

/** 状态标签：四种状态的颜色与文案集中一处，表格与筛选共用 */
const STATUS_META: Record<string, { text: string; type: 'success' | 'warning' | 'info' | 'danger' }> = {
  paid: { text: '已支付', type: 'success' },
  pending: { text: '待支付', type: 'warning' },
  refunded: { text: '已退款', type: 'danger' },
  closed: { text: '已关闭', type: 'info' },
}

function statusText(status: string): string {
  return STATUS_META[status]?.text || status
}

function statusType(status: string) {
  return STATUS_META[status]?.type || 'info'
}

const records = ref<RefundRecord[]>([])

async function loadRecords() {
  try {
    records.value = (await fetchRefundRecords(8)).records
  } catch {
    // 记录区加载失败不该影响订单主表
  }
}

// ==================== 订单详情弹窗（v2.29.0） ====================
// 以前行尾直接摆着「补单 / 关闭」两个按钮，点下去只有一句确认框；现在一个「详情」入口，
// 弹窗里先看全订单（订单号 / 用户 / 金额 / 支付方式 / 创建与支付时间），再决定怎么处理。
const detail = ref({ visible: false, row: null as OrderRow | null })

function openDetail(row: OrderRow) {
  detail.value = { visible: true, row }
}

/** 动作后刷新订单与退款记录，并把弹窗里的订单换成最新快照 */
async function afterAction(orderId: string) {
  await Promise.all([load(), loadRecords()])
  const fresh = orders.value.find((o) => o.order_id === orderId)
  if (fresh) {
    detail.value.row = fresh
  } else {
    // 当前筛选下已不包含它（例如只看待支付时补了单）：关掉并说明
    detail.value.visible = false
    ElMessage.info('已完成，该订单不再符合当前筛选条件')
  }
}

async function handleClose(row: OrderRow) {
  try {
    await ElMessageBox.confirm(
      `确认关闭订单 ${row.order_id}？未支付的订单将被作废，用户不会收到通知（他并没有付款）。`,
      '关闭订单',
      { confirmButtonText: '确认关闭', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await closeOrder(row.order_id)
    ElMessage.success('订单已关闭')
    await afterAction(row.order_id)
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '关单失败')
  }
}

// 退款对话框：原因 + 两个开关。默认回滚权益（退款不退权益=白送），
// 余额不够时后端会拒绝并回报余额，管理员可以显式勾选「允许余额为负」再退。
const refundDialog = ref({
  visible: false,
  row: null as OrderRow | null,
  reason: '',
  revoke: true,
  allowNegative: false,
  reverseRebate: true,
})
const refundSaving = ref(false)

function openRefund(row: OrderRow) {
  refundDialog.value = {
    visible: true, row, reason: '', revoke: true, allowNegative: false, reverseRebate: true,
  }
}

/** 从详情弹窗进退款：先关详情，避免两个弹窗叠在一起 */
function refundFromDetail(row: OrderRow) {
  detail.value.visible = false
  openRefund(row)
}

async function submitRefund() {
  const row = refundDialog.value.row
  if (!row) return
  const d = refundDialog.value
  if (!d.reason.trim()) {
    ElMessage.warning('请填写退款原因（对账与客服复盘都要用）')
    return
  }
  refundSaving.value = true
  try {
    const res = await refundOrder(row.order_id, {
      reason: d.reason.trim(),
      revoke_entitlement: d.revoke,
      allow_negative: d.allowNegative,
      reverse_rebate: d.reverseRebate,
    })
    const bits: string[] = []
    if (res.revoked_points) bits.push(`扣回 ${res.revoked_points} 积分`)
    if (res.rebate_reversed) bits.push(`撤回返利 ${res.rebate_reversed} 积分`)
    if (res.revoked_days) bits.push(`回滚 ${res.revoked_days} 天`)
    if (res.cancelled) bits.push('该订阅已撤销')
    ElMessage.success(`退款完成${bits.length ? '：' + bits.join('、') : ''}`)
    refundDialog.value.visible = false
    await afterAction(row.order_id)
  } catch (e: unknown) {
    // 余额不足时后端给出可读原因，原样展示（引导勾选「允许余额为负」）
    ElMessage.error((e as Error)?.message || '退款失败')
  } finally {
    refundSaving.value = false
  }
}

async function handleMarkPaid(row: OrderRow) {
  try {
    await ElMessageBox.confirm(
      `确认将订单 ${row.order_id} 标记为已支付并履约？用于线下收款或回调丢失的补单。`,
      '人工补单',
      { confirmButtonText: '确认补单', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await markOrderPaid(row.order_id)
    ElMessage.success('补单成功，已发货')
    await afterAction(row.order_id)
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '补单失败')
  }
}

function fmtTime(iso?: string | null) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : '—'
}

onMounted(() => {
  load()
  loadRecords()
})
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">订单</h1>
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
        <el-option label="已退款" value="refunded" />
        <el-option label="已关闭" value="closed" />
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
          <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
        </template>

        <template #cell-payment_method="{ row }">{{ row.payment_method || '—' }}</template>

        <template #cell-created_at="{ row }">{{ fmtTime(row.created_at) }}</template>

        <template #cell-actions="{ row }">
          <!-- 一个入口：补单 / 关单 / 退款 都在详情弹窗里（原来这行是两个动作按钮） -->
          <el-button size="small" :type="row.status === 'pending' ? 'primary' : 'default'" plain @click="openDetail(row)">
            {{ row.status === 'pending' ? '处理' : '详情' }}
          </el-button>
        </template>

        <template #empty>
          <el-empty description="暂无订单" :image-size="72">
            <template #image><Wallet :size="42" style="color: var(--text-faint)" /></template>
          </el-empty>
        </template>
      </DataTable>
    </div>

    <!-- 退款 / 关单记录：订单表只有状态标签，说不清「为什么退的」 -->
    <div v-if="records.length" class="admin-card records-card">
      <div class="records-head">
        <ReceiptText :size="14" />
        最近的退款 / 关单
        <span class="muted records-hint">原因会同时写进操作审计</span>
      </div>
      <ul class="records">
        <li v-for="r in records" :key="r.order_id + r.status" class="record">
          <span class="mono">{{ r.order_id }}</span>
          <span class="mini-badge" :class="r.status === 'refunded' ? 'danger' : 'muted'">
            {{ r.status === 'refunded' ? '已退款' : '已关闭' }}
          </span>
          <span class="record-user">{{ r.username }}</span>
          <span class="record-reason">{{ r.reason || '（未填原因）' }}</span>
          <span class="muted record-time">{{ fmtTime(r.at) }}</span>
        </li>
      </ul>
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

    <!-- 退款：默认回滚权益，余额不够时可显式允许扣成负数 -->
    <el-dialog v-model="refundDialog.visible" title="订单退款" width="480px">
      <el-form label-position="top">
        <el-form-item label="订单">
          <span class="dialog-order">
            <span class="mono">{{ refundDialog.row?.order_id }}</span>
            <em class="muted">（{{ refundDialog.row?.item_name }} · ¥{{ Number(refundDialog.row?.amount ?? 0).toFixed(2) }}）</em>
          </span>
        </el-form-item>
        <el-form-item label="退款原因（必填，写入审计）">
          <el-input v-model="refundDialog.reason" placeholder="例如：线下重复付款 / 用户申请退款" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="refundDialog.revoke">
            回滚权益（充值扣回积分 / 订阅回滚天数）
          </el-checkbox>
          <p class="opt-hint">
            取消勾选则只记账、不动权益——用于客服补偿这类“钱退了但东西留着”的场景。
          </p>
        </el-form-item>
        <el-form-item v-if="refundDialog.revoke && refundDialog.row?.kind === 'recharge'">
          <el-checkbox v-model="refundDialog.reverseRebate">同时撤回邀请人返利</el-checkbox>
          <p class="opt-hint">
            返利是这笔订单产生的；只退买家不退返利，等于站点为一次退款付两遍钱。
          </p>
        </el-form-item>
        <el-form-item v-if="refundDialog.revoke && refundDialog.row?.kind === 'recharge'">
          <el-checkbox v-model="refundDialog.allowNegative">用户余额不足时允许扣成负数</el-checkbox>
          <p class="opt-hint">
            不勾选时余额不够会被拒绝（并回报当前余额），避免悄悄把账户扣成负数。
          </p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="refundDialog.visible = false">取消</el-button>
        <el-button type="danger" :loading="refundSaving" @click="submitRefund">确认退款</el-button>
      </template>
    </el-dialog>

    <!--
      订单详情（弹窗）：订单号 / 用户 / 金额 / 支付方式 / 创建与支付时间全在这里，
      可用的处理动作随状态变化（待支付：补单或关单；已支付：退款），退款仍走专门的退款弹窗
      （勾选项多，放在同一层会看不清）。
    -->
    <el-dialog v-model="detail.visible" title="订单详情" width="520px">
      <div v-if="detail.row" class="od-body">
        <div class="od-head">
          <el-tag :type="statusType(detail.row.status)" size="small">
            {{ statusText(detail.row.status) }}
          </el-tag>
          <span class="od-amount">¥ {{ Number(detail.row.amount).toFixed(2) }}</span>
        </div>

        <div class="kv-list">
          <div class="kv-row"><span class="kv-key">订单号</span><span class="kv-value mono">{{ detail.row.order_id }}</span></div>
          <div class="kv-row"><span class="kv-key">商品</span><span class="kv-value">{{ detail.row.item_name }}</span></div>
          <div class="kv-row"><span class="kv-key">类型</span>
            <span class="kv-value">{{ detail.row.kind === 'recharge' ? '充值' : '订阅' }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">用户</span><span class="kv-value">{{ detail.row.username }}</span></div>
          <div class="kv-row"><span class="kv-key">支付方式</span>
            <span class="kv-value">{{ detail.row.payment_method || '—' }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">创建时间</span><span class="kv-value">{{ fmtTime(detail.row.created_at) }}</span></div>
          <div class="kv-row"><span class="kv-key">支付时间</span>
            <span class="kv-value">{{ detail.row.paid_at ? fmtTime(detail.row.paid_at) : '未支付' }}</span>
          </div>
        </div>

        <p class="od-hint">
          <template v-if="detail.row.status === 'pending'">
            补单用于线下收款或支付回调丢失（会按订单内容直接履约）；关闭则作废订单，用户不会收到通知。
          </template>
          <template v-else-if="detail.row.status === 'paid'">
            退款会按账本回滚权益（可逐项勾选），原因会写进操作审计与下面的退款记录。
          </template>
          <template v-else>该订单已{{ statusText(detail.row.status) }}，无可执行的动作。</template>
        </p>
      </div>

      <template #footer>
        <el-button @click="detail.visible = false">关闭</el-button>
        <template v-if="detail.row?.status === 'pending'">
          <el-button @click="detail.row && handleClose(detail.row)">
            <Ban :size="13" style="margin-right: 4px" />关闭订单
          </el-button>
          <el-button type="success" plain @click="detail.row && handleMarkPaid(detail.row)">
            <CircleCheck :size="13" style="margin-right: 4px" />人工补单
          </el-button>
        </template>
        <el-button
          v-else-if="detail.row?.status === 'paid'"
          type="danger"
          plain
          @click="detail.row && refundFromDetail(detail.row)"
        >
          <Undo2 :size="13" style="margin-right: 4px" />退款
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stat-warn { color: var(--warning); }
.amount { font-weight: var(--font-weight-semibold); font-variant-numeric: tabular-nums; }
.done-hint { font-size: var(--font-size-xs); }
.dialog-order { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.dialog-order em { font-style: normal; font-size: var(--font-size-xs); }
.opt-hint { margin: 2px 0 0; font-size: var(--font-size-xs); color: var(--text-muted); line-height: 1.5; }

/* 订单详情弹窗：详情用全局 .kv-list，只补金额行与说明 */
.od-body { display: flex; flex-direction: column; gap: 12px; }
.od-body .kv-row .kv-value { text-align: left; }
.od-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.od-amount { font-size: var(--font-size-lg, 18px); font-weight: 600; font-variant-numeric: tabular-nums; }
.od-hint {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  line-height: 1.7;
  background: var(--bg-inset, rgba(255, 255, 255, 0.03));
  border-radius: var(--radius-md, 10px);
  padding: 10px 12px;
}

.records-card { margin-top: 16px; }
.records-head { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; }
.records-hint { font-weight: 400; }
.records { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.record { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12px; }
.record-user { color: var(--text-muted); }
.record-reason { flex: 1 1 160px; min-width: 120px; }
.record-time { font-variant-numeric: tabular-nums; }
.mono { font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: var(--radius-full); font-weight: 600; }
.mini-badge.danger { background: var(--danger-bg); color: var(--danger); }
.mini-badge.muted { background: var(--bg-hover); color: var(--text-muted); }
</style>
