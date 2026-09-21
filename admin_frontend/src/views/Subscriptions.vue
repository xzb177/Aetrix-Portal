<script setup lang="ts">
/**
 * 订阅管理
 *
 * v2.4.0 新增：此前订阅只能靠数据库查看——用户管理页只显示「生效中/未订阅」两态。
 * 本页提供订阅总览：生效中 / 即将到期 / 已过期，支持搜索、状态筛选、延长与授予。
 *
 * v2.6.20：订阅是**一个服一个**的。默认只看面板当前服（会员开在哪个服、能在哪台 EA 上播
 * 都由它决定），顶部可以切到「全部服」做跨服汇总——这时列表会多一列归属服。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CalendarClock, Crown, RefreshCw, Search, TimerOff, Users } from 'lucide-vue-next'
import { fetchPlans, fetchRealmSubscriptions, type PlanRow } from '@/api/admin'
import {
  extendUserSubscription, grantUserSubscription,
} from '@/api/economy'
import type { SubscriptionOverviewRow } from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const realm = useRealmStore()
/** 统计范围：当前服（默认）或全部服 */
const scope = ref<'realm' | 'all'>('realm')
const scopeRealmName = ref('')

/** 订阅列表：手机端用户名做标题，「剩余」保留桌面端排序 */
const columns = computed<DataColumn[]>(() => [
  { key: 'username', label: '用户', minWidth: 140, mobile: 'title' },
  { key: 'plan_name', label: '套餐', minWidth: 140 },
  // 只有跨服汇总时才需要归属服这一列
  ...(scope.value === 'all'
    ? [{ key: 'realm_name', label: '归属服', minWidth: 130 } as DataColumn]
    : []),
  { key: 'period', label: '有效期', minWidth: 200 },
  { key: 'days_left', label: '剩余', width: 110, sortable: true },
  { key: 'status', label: '状态', width: 110 },
  { key: 'actions', label: '操作', width: 170, fixed: 'right', align: 'right' },
])

const loading = ref(false)
const rows = ref<SubscriptionOverviewRow[]>([])
const summary = ref({ total: 0, active: 0, expiring_7d: 0, expired: 0 })
const statusFilter = ref<string>('')
const search = ref('')
const plans = ref<PlanRow[]>([])

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { limit: 200 }
    if (statusFilter.value) params.status_filter = statusFilter.value
    if (search.value.trim()) params.search = search.value.trim()
    // realm_id=0 → 全部服；其余按服过滤（后端 `active_realm_id` 作为兜底）
    const res = await fetchRealmSubscriptions(scope.value === 'all' ? 0 : realm.activeId ?? 0, params)
    rows.value = res.subscriptions
    summary.value = res.summary
    scopeRealmName.value = res.realm_name
  } catch {
    // 错误提示由 HTTP 拦截器统一处理
  } finally {
    loading.value = false
  }
}

/** 可授予的套餐：跨服汇总时列出全部服的套餐（授予时按套餐所属的服开会员） */
async function loadPlans() {
  try {
    plans.value = (await fetchPlans(scope.value === 'all' ? 0 : undefined)).plans
  } catch {
    plans.value = []
  }
}

onMounted(async () => {
  await load()
  await loadPlans()
})

function onScopeChange() {
  load()
  loadPlans()
}

const activeCount = computed(() => summary.value.active)

function daysTone(row: SubscriptionOverviewRow): string {
  if (row.days_left <= 0) return 'off'
  if (row.days_left <= 7) return 'warn'
  return 'ok'
}

function statusText(row: SubscriptionOverviewRow): string {
  if (row.days_left <= 0) return '已过期'
  if (row.days_left <= 7) return '即将到期'
  return '生效中'
}

function fmtDay(s: string | null): string {
  return s ? s.slice(0, 10) : '—'
}

// ==================== 延长 / 授予 ====================

const dialog = reactive({
  visible: false,
  mode: 'extend' as 'extend' | 'grant',
  row: null as SubscriptionOverviewRow | null,
  planId: undefined as number | undefined,
  days: 30,
})
const saving = ref(false)

function openExtend(row: SubscriptionOverviewRow) {
  dialog.mode = 'extend'
  dialog.row = row
  dialog.days = row.days_left > 0 ? 30 : 30
  dialog.visible = true
}

function openGrant(row: SubscriptionOverviewRow) {
  dialog.mode = 'grant'
  dialog.row = row
  dialog.planId = plans.value[0]?.id
  dialog.days = plans.value[0]?.duration_days ?? 30
  dialog.visible = true
}

function onPlanChange(id: number | undefined) {
  const plan = plans.value.find((p) => p.id === id)
  if (plan) dialog.days = plan.duration_days
}

async function submit() {
  const row = dialog.row
  if (!row) return
  saving.value = true
  try {
    if (dialog.mode === 'extend') {
      await extendUserSubscription(row.id, dialog.days)
      ElMessage.success('订阅已延长并通知用户')
    } else {
      if (!dialog.planId) {
        ElMessage.warning('请选择套餐')
        return
      }
      const plan = plans.value.find((p) => p.id === dialog.planId)
      await grantUserSubscription(row.user_id, {
        plan_id: dialog.planId,
        duration_days: dialog.days,
        // 会员开在哪个服：优先跟随所选套餐，避免在多服面板里开错服
        ...(plan?.realm_id ? { realm_id: plan.realm_id } : {}),
      })
      ElMessage.success('订阅已授予并通知用户')
    }
    dialog.visible = false
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">订阅管理</h1>
        <p class="admin-page-subtitle">
          共 {{ summary.total }} 条订阅记录 · {{ activeCount }} 位用户处于订阅中
          <template v-if="scopeRealmName">· 范围：{{ scopeRealmName }}</template>
        </p>
      </div>
      <div class="toolbar">
        <el-radio-group v-model="scope" size="small" @change="onScopeChange">
          <el-radio-button value="realm">当前服</el-radio-button>
          <el-radio-button value="all">全部服</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="search"
          placeholder="搜索用户名"
          clearable
          @keyup.enter="load"
          @clear="load"
        >
          <template #prefix><Search :size="14" /></template>
        </el-input>
        <el-select v-model="statusFilter" placeholder="全部状态" clearable @change="load">
          <el-option label="生效中" value="active" />
          <el-option label="7 天内到期" value="expiring" />
          <el-option label="已过期" value="expired" />
        </el-select>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <section class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label"><Crown :size="13" /> 生效中</div>
        <div class="stat-value stat-accent">{{ summary.active }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label"><CalendarClock :size="13" /> 7 天内到期</div>
        <div class="stat-value" :class="{ 'stat-warn': summary.expiring_7d > 0 }">{{ summary.expiring_7d }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label"><TimerOff :size="13" /> 已过期</div>
        <div class="stat-value">{{ summary.expired }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label"><Users :size="13" /> 记录总数</div>
        <div class="stat-value">{{ summary.total }}</div>
      </div>
    </section>

    <div class="admin-card">
      <DataTable :rows="rows" :columns="columns" :loading="loading" empty="没有符合条件的订阅记录">
        <template #cell-username="{ row }">
          <span class="user-name">{{ row.username }}</span>
        </template>

        <template #cell-plan_name="{ row }">{{ row.plan_name }}</template>

        <template #cell-realm_name="{ row }">
          <span class="mini-badge muted">{{ row.realm_name || '未标注' }}</span>
        </template>

        <template #cell-period="{ row }">{{ fmtDay(row.start_date) }} → {{ fmtDay(row.end_date) }}</template>

        <template #cell-days_left="{ row }">
          <span :class="row.days_left <= 7 ? 'days-warn' : 'days-ok'">{{ row.days_left }} 天</span>
        </template>

        <template #cell-status="{ row }">
          <span class="mini-badge" :class="daysTone(row)">{{ statusText(row) }}</span>
        </template>

        <template #cell-actions="{ row }">
          <el-button
            v-if="row.days_left > 0"
            size="small"
            text
            type="primary"
            @click="openExtend(row)"
          >延长</el-button>
          <el-button v-else size="small" text type="primary" @click="openGrant(row)">续订</el-button>
        </template>
      </DataTable>
    </div>

    <el-dialog
      v-model="dialog.visible"
      :title="dialog.mode === 'extend' ? '延长订阅' : '续订 / 授予订阅'"
      width="440px"
    >
      <el-form label-position="top">
        <el-form-item label="用户">
          <span class="dialog-user">{{ dialog.row?.username }}</span>
        </el-form-item>
        <el-form-item v-if="dialog.mode === 'extend'" label="当前到期">
          <span class="dialog-user">
            {{ fmtDay(dialog.row?.end_date ?? null) }}
            <em class="muted">（剩余 {{ dialog.row?.days_left }} 天）</em>
          </span>
        </el-form-item>
        <el-form-item v-else label="套餐">
          <el-select v-model="dialog.planId" style="width: 100%" @change="onPlanChange">
            <el-option
              v-for="p in plans"
              :key="p.id"
              :label="`${p.name}（${p.duration_days} 天 / ¥${p.price}）`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="天数">
          <el-input-number v-model="dialog.days" :min="1" :max="3650" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.user-name { font-weight: 600; }
.stat-warn { color: var(--warning); }

.days-ok { color: var(--success); font-weight: 600; }
.days-warn { color: var(--warning); font-weight: 600; }

.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: var(--radius-full); font-weight: 600; }
.mini-badge.ok { background: var(--success-bg); color: var(--success); }
.mini-badge.warn { background: var(--warning-bg); color: var(--warning); }
.mini-badge.off,
.mini-badge.muted { background: var(--bg-hover); color: var(--text-muted); }

.empty-hint { font-size: 13px; color: var(--text-muted); padding: 16px 0; text-align: center; }
.dialog-user { font-weight: 600; }
.dialog-user em { font-style: normal; font-size: 12px; color: var(--text-muted); font-weight: 400; }
</style>
