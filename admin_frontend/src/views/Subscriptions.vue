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
import { BellRing, CalendarClock, Crown, RefreshCw, Search, TimerOff, Users } from 'lucide-vue-next'
import { fetchPlans, fetchRealmSubscriptions, type PlanRow } from '@/api/admin'
import {
  extendUserSubscription, grantUserSubscription,
  fetchReminderStatus, runReminders, updateReminderSettings,
  type ReminderStatus,
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
  await loadReminders()
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

// ==================== 到期续费提醒（v2.8.0） ====================
// 会员到期前按 7/3/1 天自动发站内信（1 小时检查一次，靠去重表保证不重复打扰）。
// 这里给出「到底有没有在跑」的口径：档位、待发条数、最近发送记录，并可手动跑一轮。
const reminders = ref<ReminderStatus | null>(null)
const reminderSaving = ref(false)
const reminderRunning = ref(false)
const reminderDays = ref('')

async function loadReminders() {
  try {
    reminders.value = await fetchReminderStatus()
    reminderDays.value = reminders.value.thresholds.join(',')
  } catch {
    // 错误提示由 HTTP 拦截器统一处理
  }
}

async function toggleReminders(enabled: boolean) {
  reminderSaving.value = true
  try {
    const res = await updateReminderSettings({ expiry_reminder_enabled: enabled })
    reminders.value = res.status
    ElMessage.success(enabled ? '到期提醒已开启' : '到期提醒已关闭')
  } catch {
    await loadReminders()
  } finally {
    reminderSaving.value = false
  }
}

async function saveReminderDays() {
  reminderSaving.value = true
  try {
    const res = await updateReminderSettings({ expiry_reminder_days: reminderDays.value })
    reminders.value = res.status
    reminderDays.value = res.status.thresholds.join(',')
    ElMessage.success(`提醒档位已保存：${res.status.thresholds.map((d) => `${d} 天`).join(' / ')}`)
  } catch {
    await loadReminders()
  } finally {
    reminderSaving.value = false
  }
}

/** dryRun=true 只看会发给谁，不打扰任何用户 */
async function runReminderPass(dryRun: boolean) {
  reminderRunning.value = true
  try {
    const res = await runReminders(dryRun)
    if (!res.enabled) {
      ElMessage.warning('到期提醒未开启，请先打开开关')
    } else if (dryRun) {
      ElMessage.info(res.due.length ? `待发 ${res.due.length} 条（未发送）` : '当前没有待发的提醒')
    } else if (res.reminded + res.expired_notified === 0) {
      ElMessage.info(res.skipped ? `无需重复提醒（跳过 ${res.skipped} 条）` : '当前没有待发的提醒')
    } else {
      ElMessage.success(`已发送：临期 ${res.reminded} 条 / 已到期 ${res.expired_notified} 条`)
    }
    await loadReminders()
  } catch {
    // 拦截器已提示
  } finally {
    reminderRunning.value = false
  }
}

/** 发送档位的中文说明（面板上不想让运营自己去猜 kind 的含义） */
function kindText(kind: string): string {
  return kind === 'expired' ? '已到期' : `剩 ${kind.replace('d', '')} 天`
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
        <h1 class="admin-page-title">订阅与权益</h1>
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

    <!-- 到期提醒：会员到期前自动触达，是续费率最直接的一环；面板要能看出它在跑 -->
    <div class="admin-card reminder-card">
      <div class="reminder-head">
        <div class="reminder-title">
          <BellRing :size="15" />
          到期续费提醒
          <span
            class="mini-badge"
            :class="reminders?.enabled ? 'ok' : 'muted'"
          >{{ reminders?.enabled ? '已开启' : '已关闭' }}</span>
        </div>
        <div class="reminder-actions">
          <el-switch
            :model-value="reminders?.enabled ?? false"
            :loading="reminderSaving"
            @change="(v: string | number | boolean) => toggleReminders(Boolean(v))"
          />
          <el-button
            size="small"
            :loading="reminderRunning"
            @click="runReminderPass(true)"
          >预览</el-button>
          <el-button
            size="small"
            type="primary"
            :loading="reminderRunning"
            :disabled="!reminders?.enabled"
            @click="runReminderPass(false)"
          >立即检查并发送</el-button>
        </div>
      </div>

      <div class="reminder-body">
        <div class="reminder-field">
          <label>提前提醒档位</label>
          <div class="reminder-input">
            <el-input v-model="reminderDays" size="small" placeholder="7,3,1" style="width: 140px" />
            <el-button size="small" :loading="reminderSaving" @click="saveReminderDays">保存</el-button>
          </div>
          <p class="reminder-hint">
            逗号分隔的天数，每个档位只提醒一次（当前：{{ reminders?.thresholds?.join(' / ') || '—' }} 天）
          </p>
        </div>
        <div class="reminder-stats">
          <div class="reminder-stat">
            <span class="rs-label">待发 · 临期</span>
            <span class="rs-value">{{ reminders?.pending_reminders ?? '—' }}</span>
          </div>
          <div class="reminder-stat">
            <span class="rs-label">待发 · 已到期</span>
            <span class="rs-value">{{ reminders?.pending_expired ?? '—' }}</span>
          </div>
          <div class="reminder-stat">
            <span class="rs-label">累计已发</span>
            <span class="rs-value">{{ reminders?.total_sent ?? '—' }}</span>
          </div>
          <div class="reminder-stat">
            <span class="rs-label">检查间隔</span>
            <span class="rs-value">
              {{ reminders ? Math.round(reminders.interval_seconds / 60) + ' 分钟' : '—' }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="reminders?.recent?.length" class="reminder-recent">
        <span class="rr-label">最近发送</span>
        <span v-for="r in reminders.recent.slice(0, 6)" :key="r.id" class="rr-item">
          {{ r.username }}
          <em>{{ kindText(r.kind) }}</em>
        </span>
      </div>
      <p v-else class="reminder-empty">
        还没有发送记录。已有会员临期时，这里会出现「谁 · 哪一档」的明细。
      </p>
    </div>

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

/* ==================== 到期提醒 ==================== */
.reminder-card { margin-bottom: 16px; }
.reminder-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.reminder-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
}
.reminder-actions { display: flex; align-items: center; gap: 8px; }
.reminder-body {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.reminder-field label { display: block; font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
.reminder-input { display: flex; align-items: center; gap: 8px; }
.reminder-hint { margin: 6px 0 0; font-size: 12px; color: var(--text-muted); }
.reminder-stats { display: flex; gap: 18px; flex-wrap: wrap; }
.reminder-stat { display: flex; flex-direction: column; gap: 2px; }
.rs-label { font-size: 12px; color: var(--text-muted); }
.rs-value { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.reminder-recent {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
  font-size: 12px;
}
.rr-label { color: var(--text-muted); }
.rr-item { padding: 1px 7px; border-radius: var(--radius-full); background: var(--bg-hover); }
.rr-item em { font-style: normal; color: var(--text-muted); margin-left: 4px; }
.reminder-empty { margin: 12px 0 0; font-size: 12px; color: var(--text-muted); }

.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: var(--radius-full); font-weight: 600; }
.mini-badge.ok { background: var(--success-bg); color: var(--success); }
.mini-badge.warn { background: var(--warning-bg); color: var(--warning); }
.mini-badge.off,
.mini-badge.muted { background: var(--bg-hover); color: var(--text-muted); }

.empty-hint { font-size: 13px; color: var(--text-muted); padding: 16px 0; text-align: center; }
.dialog-user { font-weight: 600; }
.dialog-user em { font-style: normal; font-size: 12px; color: var(--text-muted); font-weight: 400; }
</style>
