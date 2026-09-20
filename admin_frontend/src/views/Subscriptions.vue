<script setup lang="ts">
/**
 * 订阅管理
 *
 * v2.4.0 新增：此前订阅只能靠数据库查看——用户管理页只显示「生效中/未订阅」两态。
 * 本页提供订阅总览：生效中 / 即将到期 / 已过期，支持搜索、状态筛选、延长与授予。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CalendarClock, Crown, RefreshCw, Search, TimerOff, Users } from 'lucide-vue-next'
import { fetchPlans, type PlanRow } from '@/api/admin'
import {
  extendUserSubscription, fetchSubscriptions, grantUserSubscription,
} from '@/api/economy'
import type { SubscriptionOverviewRow } from '@/types'

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
    const res = await fetchSubscriptions(params)
    rows.value = res.subscriptions
    summary.value = res.summary
  } catch {
    // 错误提示由 HTTP 拦截器统一处理
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    plans.value = (await fetchPlans()).plans
  } catch {
    plans.value = []
  }
})

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
      await grantUserSubscription(row.user_id, { plan_id: dialog.planId, duration_days: dialog.days })
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
        <p class="admin-page-subtitle">共 {{ summary.total }} 条订阅记录 · {{ activeCount }} 位用户处于订阅中</p>
      </div>
      <div class="toolbar">
        <el-input
          v-model="search"
          placeholder="搜索用户名"
          clearable
          style="width: 180px"
          @keyup.enter="load"
          @clear="load"
        >
          <template #prefix><Search :size="14" /></template>
        </el-input>
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px" @change="load">
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
      <el-table :data="rows" v-loading="loading" style="width: 100%">
        <el-table-column label="用户" min-width="140">
          <template #default="{ row }">
            <span class="user-name">{{ row.username }}</span>
          </template>
        </el-table-column>
        <el-table-column label="套餐" min-width="140">
          <template #default="{ row }">{{ row.plan_name }}</template>
        </el-table-column>
        <el-table-column label="有效期" min-width="200">
          <template #default="{ row }">{{ fmtDay(row.start_date) }} → {{ fmtDay(row.end_date) }}</template>
        </el-table-column>
        <el-table-column label="剩余" width="110" sortable :sort-by="(r: SubscriptionOverviewRow) => r.days_left">
          <template #default="{ row }">
            <span :class="row.days_left <= 7 ? 'days-warn' : 'days-ok'">{{ row.days_left }} 天</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <span class="mini-badge" :class="daysTone(row)">{{ statusText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.days_left > 0"
              size="small"
              text
              type="primary"
              @click="openExtend(row)"
            >延长</el-button>
            <el-button v-else size="small" text type="primary" @click="openGrant(row)">续订</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!loading && rows.length === 0" class="empty-hint">没有符合条件的订阅记录</div>
    </div>

    <el-dialog
      v-model="dialog.visible"
      :title="dialog.mode === 'extend' ? '延长订阅' : '续订 / 授予订阅'"
      width="440px"
    >
      <el-form label-width="80px">
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
.mini-badge.off { background: var(--bg-hover); color: var(--text-muted); }

.empty-hint { font-size: 13px; color: var(--text-muted); padding: 16px 0; text-align: center; }
.dialog-user { font-weight: 600; }
.dialog-user em { font-style: normal; font-size: 12px; color: var(--text-muted); font-weight: 400; }
</style>
