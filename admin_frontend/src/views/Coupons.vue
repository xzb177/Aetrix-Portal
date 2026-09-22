<script setup lang="ts">
/**
 * 优惠券（v2.10.0）
 *
 * 与兑换码的区别要一眼看得出：兑换码是「不花钱直接拿东西」，优惠券是「付费时打折」，
 * 钱照旧走支付网关，只是单价变了。所以这张表讲的全是「折扣与额度」。
 *
 * 额度是**预订制**的：下单就占（reserved），付款转已用（consumed），关单/退款释放（released）。
 * 面板上必须能看见「占用中」这一档——它可能随时变成已用，也可能超时被自动清理，
 * 只看 `use_count` 会说不清「这张券到底还能不能发」。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshCw, Settings2, TicketPercent } from 'lucide-vue-next'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'
import { useRealmStore } from '@/stores/realm'
import {
  createCoupons,
  deleteCoupon,
  fetchCouponSettings,
  fetchCouponUsages,
  fetchCoupons,
  updateCoupon,
  updateCouponSettings,
  type CouponCreatePayload,
  type CouponRow,
  type CouponUsageRow,
} from '@/api/economy'

const realm = useRealmStore()
const realms = computed(() => realm.realms)

const loading = ref(false)
const coupons = ref<CouponRow[]>([])
const enabled = ref(true)
const reserveHours = ref(24)
const activeUsage = ref(0)
const settingsSaving = ref(false)

// 筛选
const filters = ref({ kind: '', active: '', search: '' })

const columns: DataColumn[] = [
  { key: 'code', label: '优惠码', width: 150, mobile: 'title' },
  { key: 'discount', label: '优惠', width: 150 },
  { key: 'limits', label: '额度', width: 130 },
  { key: 'scope', label: '适用范围', width: 150 },
  { key: 'valid', label: '有效期', width: 150 },
  { key: 'note', label: '备注', minWidth: 130, mobile: 'hide' },
  { key: 'is_active', label: '状态', width: 90 },
  { key: 'actions', label: '操作', width: 190, fixed: 'right', align: 'right' },
]

async function load() {
  loading.value = true
  try {
    const [list, settings] = await Promise.all([
      fetchCoupons({
        kind: filters.value.kind || undefined,
        active: filters.value.active || undefined,
        search: filters.value.search || undefined,
        limit: 300,
      }),
      fetchCouponSettings().catch(() => null),
    ])
    coupons.value = list.coupons
    enabled.value = list.enabled
    if (settings) {
      enabled.value = settings.enabled
      reserveHours.value = settings.reserve_hours
      activeUsage.value = settings.active_usage
    }
  } finally {
    loading.value = false
  }
}

// ==================== 文案 ====================
function discountText(row: CouponRow): string {
  return row.discount_type === 'percent'
    ? `${(row.value / 10).toFixed(1).replace(/\.0$/, '')} 折（实付 ${row.value}%）`
    : `立减 ¥${row.value.toFixed(2)}`
}

function scopeText(row: CouponRow): string {
  const kind = row.kind === 'all' ? '全部商品' : row.kind === 'subscription' ? '仅会员' : '仅充值'
  return row.realm_name ? `${kind} · ${row.realm_name}` : kind
}

function validText(row: CouponRow): string {
  if (!row.valid_from && !row.valid_until) return '长期有效'
  const from = row.valid_from ? row.valid_from.slice(0, 10) : '即日'
  const until = row.valid_until ? row.valid_until.slice(0, 10) : '不限'
  return `${from} → ${until}`
}

function usageText(row: CouponRow): string {
  const total = row.max_uses ? `${row.max_uses} 次` : '不限'
  return `${row.use_count} / ${total}`
}

const summary = computed(() => {
  const usable = coupons.value.filter((c) => c.usable).length
  const reserved = coupons.value.reduce((acc, c) => acc + (c.stats?.reserved || 0), 0)
  const consumed = coupons.value.reduce((acc, c) => acc + (c.stats?.consumed || 0), 0)
  return { total: coupons.value.length, usable, reserved, consumed }
})

// ==================== 新建 ====================
const createVisible = ref(false)
const creating = ref(false)
const createResult = ref<string[]>([])
const resultVisible = ref(false)
const createForm = ref<CouponCreatePayload & { validMode: 'days' | 'until'; valid_until_text: string }>({
  count: 1,
  code: '',
  kind: 'all',
  discount_type: 'percent',
  value: 90,
  min_amount: 0,
  max_discount: 0,
  realm_id: null,
  max_uses: 0,
  per_user_limit: 1,
  validMode: 'days',
  valid_days: 30,
  valid_until_text: '',
  note: '',
})

function resetCreateForm() {
  createForm.value = {
    count: 1, code: '', kind: 'all', discount_type: 'percent', value: 90,
    min_amount: 0, max_discount: 0, realm_id: null, max_uses: 0, per_user_limit: 1,
    validMode: 'days', valid_days: 30, valid_until_text: '', note: '',
  }
}

async function handleCreate() {
  creating.value = true
  try {
    const f = createForm.value
    const payload: CouponCreatePayload = {
      count: f.code ? 1 : Number(f.count || 1),
      code: f.code ? f.code.trim().toUpperCase() : undefined,
      kind: f.kind,
      discount_type: f.discount_type,
      value: Number(f.value),
      min_amount: Number(f.min_amount || 0),
      max_discount: Number(f.max_discount || 0),
      realm_id: f.realm_id || null,
      max_uses: Number(f.max_uses || 0),
      per_user_limit: Number(f.per_user_limit || 0),
      note: f.note || undefined,
    }
    if (f.validMode === 'days') {
      if (Number(f.valid_days || 0) > 0) payload.valid_days = Number(f.valid_days)
    } else if (f.valid_until_text) {
      payload.valid_until = f.valid_until_text
    }

    const res = await createCoupons(payload)
    createResult.value = res.coupons.map((c) => c.code)
    resultVisible.value = true
    createVisible.value = false
    ElMessage.success(`已生成 ${res.count} 张优惠券`)
    resetCreateForm()
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '创建失败')
  } finally {
    creating.value = false
  }
}

function copyCodes() {
  navigator.clipboard.writeText(createResult.value.join('\n'))
  ElMessage.success('已复制全部')
}

// ==================== 编辑 ====================
const editVisible = ref(false)
const editing = ref(false)
const editTarget = ref<CouponRow | null>(null)
const editForm = ref({
  kind: 'all' as CouponRow['kind'],
  discount_type: 'percent' as CouponRow['discount_type'],
  value: 90,
  min_amount: 0,
  max_discount: 0,
  realm_id: null as number | null,
  max_uses: 0,
  per_user_limit: 1,
  valid_until_text: '',
  is_active: true,
  note: '',
})

function openEdit(row: CouponRow) {
  editTarget.value = row
  editForm.value = {
    kind: row.kind,
    discount_type: row.discount_type,
    value: row.value,
    min_amount: row.min_amount,
    max_discount: row.max_discount,
    realm_id: row.realm_id,
    max_uses: row.max_uses,
    per_user_limit: row.per_user_limit,
    valid_until_text: row.valid_until ? row.valid_until.slice(0, 16).replace('T', ' ') : '',
    is_active: row.is_active,
    note: row.note || '',
  }
  editVisible.value = true
}

async function handleUpdate() {
  if (!editTarget.value) return
  editing.value = true
  try {
    const f = editForm.value
    await updateCoupon(editTarget.value.id, {
      kind: f.kind,
      discount_type: f.discount_type,
      value: Number(f.value),
      min_amount: Number(f.min_amount || 0),
      max_discount: Number(f.max_discount || 0),
      realm_id: f.realm_id || null,
      max_uses: Number(f.max_uses || 0),
      per_user_limit: Number(f.per_user_limit || 0),
      valid_until: f.valid_until_text || undefined,
      is_active: f.is_active,
      note: f.note,
    })
    ElMessage.success('已保存（只影响之后的订单，已下单的金额不变）')
    editVisible.value = false
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '保存失败')
  } finally {
    editing.value = false
  }
}

async function toggleCoupon(row: CouponRow) {
  try {
    await updateCoupon(row.id, { is_active: !row.is_active })
    row.is_active = !row.is_active
    ElMessage.success(row.is_active ? '已启用' : '已停用')
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '操作失败')
  }
}

async function handleDelete(row: CouponRow) {
  try {
    await ElMessageBox.confirm(
      `删除优惠券 ${row.code}？只有从没用过的券可以删除，有核销记录的请改用停用。`,
      '删除优惠券',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await deleteCoupon(row.id)
    ElMessage.success(res.message || '已删除')
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '删除失败')
  }
}

// ==================== 核销记录 ====================
const usagesVisible = ref(false)
const usagesLoading = ref(false)
const usages = ref<CouponUsageRow[]>([])
const usagesFilter = ref<CouponRow | null>(null)

async function openUsages(row?: CouponRow) {
  usagesFilter.value = row || null
  usagesVisible.value = true
  usagesLoading.value = true
  try {
    const res = await fetchCouponUsages({ limit: 100, coupon_id: row?.id })
    usages.value = res.records
  } finally {
    usagesLoading.value = false
  }
}

const STATUS_META: Record<string, { label: string; type: 'success' | 'warning' | 'info' }> = {
  reserved: { label: '预订（未付款）', type: 'warning' },
  consumed: { label: '已使用', type: 'success' },
  released: { label: '已释放', type: 'info' },
}

const statusMeta = (s: string) => STATUS_META[s] || { label: s, type: 'info' as const }

// ==================== 设置 ====================
async function saveSettings() {
  settingsSaving.value = true
  try {
    const res = await updateCouponSettings({
      enabled: enabled.value,
      reserve_hours: Number(reserveHours.value || 0),
    })
    ElMessage.success(enabled.value ? '优惠券已开启' : '优惠券已关闭（用户端不再显示优惠码入口）')
    reserveHours.value = res.reserve_hours
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '保存失败')
  } finally {
    settingsSaving.value = false
  }
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}

onMounted(() => {
  if (!realm.realms.length) realm.load().catch(() => {})
  load()
})
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">优惠券</h1>
        <p class="admin-page-subtitle">
          付费时抵扣：共 {{ summary.total }} 张（可用 {{ summary.usable }}）·
          占用中 {{ summary.reserved }} · 已核销 {{ summary.consumed }}
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
        <el-button :icon="TicketPercent" @click="openUsages()">核销记录</el-button>
        <el-button type="primary" :icon="Plus" @click="createVisible = true">新建优惠券</el-button>
      </div>
    </div>

    <!-- 开关与预订清理：额度不能被「点了下单没付款」的订单永远占着 -->
    <div class="admin-card settings-bar">
      <div class="setting">
        <span class="setting-label">
          <Settings2 :size="14" />
          优惠券功能
        </span>
        <el-switch v-model="enabled" active-text="开启" inactive-text="关闭" />
        <span class="setting-hint">关闭后用户端不再显示优惠码入口，已下的单不受影响</span>
      </div>
      <div class="setting">
        <span class="setting-label">超时未支付自动收尾</span>
        <el-input-number v-model="reserveHours" :min="0" :max="720" :step="6" size="small" />
        <span class="setting-hint">
          小时（0 = 不自动清理）：到点后自动关单并退回优惠额度，当前占用中 {{ activeUsage }} 笔
        </span>
      </div>
      <el-button type="primary" plain :loading="settingsSaving" @click="saveSettings">保存设置</el-button>
    </div>

    <div class="admin-card">
      <div class="filters">
        <el-select v-model="filters.kind" placeholder="适用范围" clearable style="width: 140px" @change="load">
          <el-option label="全部商品" value="all" />
          <el-option label="仅会员" value="subscription" />
          <el-option label="仅充值" value="recharge" />
        </el-select>
        <el-select v-model="filters.active" placeholder="状态" clearable style="width: 120px" @change="load">
          <el-option label="启用" value="true" />
          <el-option label="停用" value="false" />
        </el-select>
        <el-input
          v-model="filters.search"
          placeholder="搜索优惠码"
          clearable
          style="width: 200px"
          @keyup.enter="load"
          @clear="load"
        />
        <el-button @click="load">查询</el-button>
      </div>

      <DataTable :rows="coupons" :columns="columns" :loading="loading" empty="还没有优惠券">
        <template #cell-code="{ row }">
          <span class="mono code">{{ row.code }}</span>
        </template>

        <template #cell-discount="{ row }">
          <span class="discount">{{ discountText(row) }}</span>
          <div v-if="row.min_amount > 0 || row.max_discount > 0" class="muted">
            <span v-if="row.min_amount > 0">满 ¥{{ row.min_amount.toFixed(2) }} 可用</span>
            <span v-if="row.max_discount > 0">· 最多省 ¥{{ row.max_discount.toFixed(2) }}</span>
          </div>
        </template>

        <template #cell-limits="{ row }">
          <span>{{ usageText(row) }}</span>
          <div class="muted">
            每人 {{ row.per_user_limit ? row.per_user_limit + ' 次' : '不限' }}
            <span v-if="row.stats?.reserved">· 占用中 {{ row.stats.reserved }}</span>
          </div>
        </template>

        <template #cell-scope="{ row }">{{ scopeText(row) }}</template>

        <template #cell-valid="{ row }">
          <span :class="{ muted: !row.valid_until }">{{ validText(row) }}</span>
        </template>

        <template #cell-note="{ row }">
          <span v-if="!row.note" class="muted">—</span>
          <span v-else>{{ row.note }}</span>
        </template>

        <template #cell-is_active="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>

        <template #cell-actions="{ row }">
          <el-button size="small" link @click="openUsages(row)">记录</el-button>
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
          <el-button size="small" link :type="row.is_active ? 'warning' : 'success'" @click="toggleCoupon(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button size="small" link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </DataTable>
    </div>

    <!-- 新建 -->
    <el-dialog v-model="createVisible" title="新建优惠券" width="560px">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="适用范围">
            <el-select v-model="createForm.kind" style="width: 100%">
              <el-option label="全部商品（充值 + 会员）" value="all" />
              <el-option label="仅会员" value="subscription" />
              <el-option label="仅充值" value="recharge" />
            </el-select>
          </el-form-item>
          <el-form-item label="限定服（可选）">
            <el-select v-model="createForm.realm_id" clearable placeholder="不限定" style="width: 100%">
              <el-option v-for="r in realms" :key="r.id" :label="r.name" :value="r.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="折扣方式">
            <el-radio-group v-model="createForm.discount_type">
              <el-radio-button value="percent">按比例打折</el-radio-button>
              <el-radio-button value="fixed">固定减免</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item :label="createForm.discount_type === 'percent' ? '实付百分比（90 = 九折）' : '减免金额（元）'">
            <el-input-number
              v-model="createForm.value"
              :min="createForm.discount_type === 'percent' ? 1 : 0.01"
              :max="createForm.discount_type === 'percent' ? 100 : 100000"
              :precision="createForm.discount_type === 'percent' ? 0 : 2"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="门槛（满多少可用，0 = 不限）">
            <el-input-number v-model="createForm.min_amount" :min="0" :precision="2" style="width: 100%" />
          </el-form-item>
          <el-form-item label="封顶减免（0 = 不封顶）">
            <el-input-number v-model="createForm.max_discount" :min="0" :precision="2" style="width: 100%" />
          </el-form-item>
          <el-form-item label="总次数上限（0 = 不限）">
            <el-input-number v-model="createForm.max_uses" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item label="每人限用（0 = 不限）">
            <el-input-number v-model="createForm.per_user_limit" :min="0" style="width: 100%" />
          </el-form-item>
        </div>

        <el-divider content-position="left">生成方式</el-divider>
        <div class="form-grid">
          <el-form-item label="指定优惠码（留空 = 随机生成）">
            <el-input v-model="createForm.code" placeholder="如 SAVE10" maxlength="32" />
          </el-form-item>
          <el-form-item label="数量（随机码时有效，最多 200）">
            <el-input-number v-model="createForm.count" :min="1" :max="200" :disabled="!!createForm.code" style="width: 100%" />
          </el-form-item>
          <el-form-item label="有效期">
            <el-radio-group v-model="createForm.validMode">
              <el-radio-button value="days">按天数</el-radio-button>
              <el-radio-button value="until">指定时间</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="createForm.validMode === 'days'" label="有效天数（0 = 长期）">
            <el-input-number v-model="createForm.valid_days" :min="0" :max="3650" style="width: 100%" />
          </el-form-item>
          <el-form-item v-else label="截止时间">
            <el-input v-model="createForm.valid_until_text" placeholder="2026-10-01 12:00" />
          </el-form-item>
        </div>

        <el-form-item label="备注">
          <el-input v-model="createForm.note" placeholder="活动名称等（选填）" maxlength="60" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">生成</el-button>
      </template>
    </el-dialog>

    <!-- 生成结果 -->
    <el-dialog v-model="resultVisible" title="生成结果（请保存）" width="420px">
      <el-input :model-value="createResult.join('\n')" type="textarea" :rows="10" readonly class="mono" />
      <template #footer>
        <el-button type="primary" @click="copyCodes">复制全部</el-button>
      </template>
    </el-dialog>

    <!-- 编辑 -->
    <el-dialog v-model="editVisible" :title="`编辑优惠券 ${editTarget?.code || ''}`" width="560px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="改动只影响之后的订单"
        description="已下单的订单保留当时的优惠快照，金额与记录都不会跟着变。"
        style="margin-bottom: 12px"
      />
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="适用范围">
            <el-select v-model="editForm.kind" style="width: 100%">
              <el-option label="全部商品" value="all" />
              <el-option label="仅会员" value="subscription" />
              <el-option label="仅充值" value="recharge" />
            </el-select>
          </el-form-item>
          <el-form-item label="限定服">
            <el-select v-model="editForm.realm_id" clearable placeholder="不限定" style="width: 100%">
              <el-option v-for="r in realms" :key="r.id" :label="r.name" :value="r.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="折扣方式">
            <el-radio-group v-model="editForm.discount_type">
              <el-radio-button value="percent">比例</el-radio-button>
              <el-radio-button value="fixed">固定减免</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item :label="editForm.discount_type === 'percent' ? '实付百分比（90 = 九折）' : '减免金额（元）'">
            <el-input-number
              v-model="editForm.value"
              :min="editForm.discount_type === 'percent' ? 1 : 0.01"
              :max="editForm.discount_type === 'percent' ? 100 : 100000"
              :precision="editForm.discount_type === 'percent' ? 0 : 2"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="门槛">
            <el-input-number v-model="editForm.min_amount" :min="0" :precision="2" style="width: 100%" />
          </el-form-item>
          <el-form-item label="封顶减免">
            <el-input-number v-model="editForm.max_discount" :min="0" :precision="2" style="width: 100%" />
          </el-form-item>
          <el-form-item label="总次数上限（不能低于已占用）">
            <el-input-number v-model="editForm.max_uses" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item label="每人限用">
            <el-input-number v-model="editForm.per_user_limit" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item label="截止时间（留空 = 不限）">
            <el-input v-model="editForm.valid_until_text" placeholder="2026-10-01 12:00" />
          </el-form-item>
          <el-form-item label="状态">
            <el-switch v-model="editForm.is_active" active-text="启用" inactive-text="停用" />
          </el-form-item>
        </div>
        <el-form-item label="备注">
          <el-input v-model="editForm.note" maxlength="60" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="handleUpdate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 核销记录 -->
    <el-dialog
      v-model="usagesVisible"
      :title="usagesFilter ? `核销记录 · ${usagesFilter.code}` : '最近的核销记录'"
      width="760px"
    >
      <el-table :data="usages" v-loading="usagesLoading" size="small" empty-text="还没有核销记录">
        <el-table-column prop="code" label="优惠码" width="130">
          <template #default="{ row }"><span class="mono">{{ row.code }}</span></template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="120" />
        <el-table-column prop="order_id" label="订单" min-width="180">
          <template #default="{ row }"><span class="mono">{{ row.order_id }}</span></template>
        </el-table-column>
        <el-table-column label="金额" width="170">
          <template #default="{ row }">
            ¥{{ row.paid_amount.toFixed(2) }}
            <span class="muted">（原价 ¥{{ row.list_price.toFixed(2) }}，省 ¥{{ row.discount_amount.toFixed(2) }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" size="small">{{ statusMeta(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="140">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions { display: flex; gap: 8px; }

.settings-bar {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  padding: 14px 16px;
}

.setting { display: flex; align-items: center; gap: 8px; }
.setting-label { display: inline-flex; align-items: center; gap: 5px; font-size: 13px; font-weight: 600; }
.setting-hint { font-size: 12px; color: var(--text-muted); }

.filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }

.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }

.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.code { letter-spacing: 0.06em; font-weight: 600; color: var(--primary); }
.discount { font-weight: 600; }
.muted { color: var(--text-muted); font-size: 12px; }
</style>
