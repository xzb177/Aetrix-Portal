<script setup lang="ts">
/**
 * 登录 / 安全日志（v2.6.0）
 *
 * 记录门户与客户端登录、登录失败、设备超限被拒、诱饵码触发封禁等事件，
 * 供风控审查；支持按保留天数清理，避免表无限增长。
 */
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, Search, Trash2, ShieldAlert, ScrollText, KeyRound, Database } from 'lucide-vue-next'
import { fetchLoginLogs } from '@/api/admin'
import { PageHeader, SectionCard, StatTile } from '@/components/ui'
import { useDangerOps } from '@/composables/useDangerOps'
import type { LoginLogRow, LoginLogsResponse } from '@/types'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

/** 手机卡片：用户为标题，事件/结果/风险/IP/详情/时间做键值行，客户端 UA 太长故隐藏 */
const columns: DataColumn[] = [
  { key: 'username', label: '用户', width: 140, mobile: 'title' },
  { key: 'created_at', label: '时间', width: 170 },
  { key: 'reason_label', label: '事件', width: 140 },
  { key: 'success', label: '结果', width: 96 },
  { key: 'risk', label: '风险', width: 90 },
  // IP 与归属地合并成一列：配置了「IP 与地理位置」能力后，风控审查不用再去查 IP 库
  { key: 'ip', label: 'IP / 归属地', width: 190 },
  { key: 'detail', label: '详情', minWidth: 200 },
  { key: 'user_agent', label: '客户端', minWidth: 180, mobile: 'hide' },
]

const data = ref<LoginLogsResponse | null>(null)
const loading = ref(false)
const loadError = ref('')
const filters = ref<{ username: string; ip: string; reason: string; success: string }>({
  username: '',
  ip: '',
  reason: '',
  success: '',
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    data.value = await fetchLoginLogs({
      username: filters.value.username || undefined,
      ip: filters.value.ip || undefined,
      reason: filters.value.reason || undefined,
      success: filters.value.success === '' ? undefined : filters.value.success === 'true',
      limit: 300,
    })
  } catch (e) {
    // 查询失败拦截器不弹提示，由表格错误态兜底（保留上一次的数据与统计）
    loadError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 清理动作进行中（按钮 loading，防重复点击） */
const purgeBusy = ref(false)
/** 危险操作共用实现（与「系统设置 → 危险操作」页签同一份） */
const dangerOps = useDangerOps()

/** 清理日志是危险操作：确认文案与执行都在 useDangerOps（与「系统设置 → 危险操作」同一份） */
async function purge(preset: number) {
  purgeBusy.value = true
  try {
    if (await dangerOps.purgeLogs(preset)) load()
  } finally {
    purgeBusy.value = false
  }
}

function fmt(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 19).replace('T', ' ')
}

const hasFilter = computed(() =>
  Boolean(filters.value.username || filters.value.ip || filters.value.reason || filters.value.success),
)

function resetFilters() {
  filters.value = { username: '', ip: '', reason: '', success: '' }
  load()
}

function riskBadge(row: LoginLogRow): string {
  const level = riskLevel(row)
  return level === '高风险' ? 'au-badge-rose' : level === '注意' ? 'au-badge-amber' : 'au-badge-green'
}

function riskLevel(row: LoginLogRow): string {
  if (row.reason === 'decoy_code' || row.reason === 'device_limit') return '高风险'
  if (!row.success) return '注意'
  return '正常'
}
</script>

<template>
  <div class="admin-page">
    <PageHeader
      eyebrow="用户与账号"
      title="登录日志"
      description="登录成功 / 失败、设备超限、诱饵码触发等风控事件；最多加载最近 300 条。"
    >
      <template #actions>
        <RouterLink class="danger-jump" :to="{ name: 'Settings', query: { tab: 'danger', op: 'logs' } }">
          危险操作中心 →
        </RouterLink>
        <el-button :loading="purgeBusy" @click="purge(data && data.total > 0 ? 90 : 0)" :icon="Trash2">
          清理日志
        </el-button>
        <el-button :loading="loading" @click="load" :icon="RefreshCw">刷新</el-button>
      </template>
    </PageHeader>

    <div class="stat-row">
      <StatTile label="日志总数" :value="data?.total ?? 0" :icon="Database" hint="按保留天数自动清理" />
      <StatTile
        label="24h 登录失败"
        :value="data?.summary.failed_24h ?? 0"
        :icon="KeyRound"
        :tone="(data?.summary.failed_24h ?? 0) > 0 ? 'warn' : 'plain'"
        hint="含客户端与门户登录失败"
      />
      <StatTile
        label="24h 风控拦截"
        :value="data?.summary.risk_24h ?? 0"
        :icon="ShieldAlert"
        :tone="(data?.summary.risk_24h ?? 0) > 0 ? 'danger' : 'plain'"
        hint="设备超限 / 诱饵码触发"
      />
    </div>

    <SectionCard title="登录事件" :icon="ScrollText" :meta="data ? `${data.logs.length} 条` : ''" flush>
      <div class="list-bar">
        <div class="filter-bar">
          <el-input v-model="filters.username" placeholder="用户名" clearable @keyup.enter="load" @clear="load" />
          <el-input v-model="filters.ip" placeholder="IP" clearable @keyup.enter="load" @clear="load" />
          <el-select v-model="filters.reason" placeholder="全部事件" @change="load">
            <el-option value="" label="全部事件" />
            <el-option v-for="r in data?.reasons || []" :key="r.value" :value="r.value" :label="r.label" />
          </el-select>
          <el-select v-model="filters.success" placeholder="全部结果" @change="load">
            <el-option value="" label="全部结果" />
            <el-option value="true" label="成功" />
            <el-option value="false" label="失败" />
          </el-select>
        </div>
        <div class="head-actions">
          <el-button v-if="hasFilter" text @click="resetFilters">清空筛选</el-button>
          <el-button type="primary" @click="load" :icon="Search">查询</el-button>
        </div>
      </div>

      <DataTable
        :rows="data?.logs || []"
        :columns="columns"
        :loading="loading"
        :error="loadError"
        :empty="hasFilter ? '没有匹配的登录记录' : '暂无登录日志'"
        :empty-description="hasFilter ? '换个用户名 / IP，或清空筛选再查。' : ''"
        @retry="load"
      >
        <template #cell-username="{ row }">
          <span class="user-name">{{ row.username || '—' }}</span>
        </template>

        <template #cell-created_at="{ row }"><span class="mono">{{ fmt(row.created_at) }}</span></template>

        <template #cell-reason_label="{ row }">{{ row.reason_label }}</template>

        <template #cell-success="{ row }">
          <span class="au-badge" :class="row.success ? 'au-badge-green' : 'au-badge-rose'">
            {{ row.success ? '成功' : '失败' }}
          </span>
        </template>

        <template #cell-risk="{ row }">
          <span class="au-badge" :class="riskBadge(row)">{{ riskLevel(row) }}</span>
        </template>

        <template #cell-ip="{ row }">
          <span class="mono">{{ row.ip || '—' }}</span>
          <span v-if="row.region" class="region">{{ row.region }}</span>
        </template>

        <template #cell-detail="{ row }">
          <span v-if="!row.detail" class="muted">—</span>
          <span v-else>{{ row.detail }}</span>
        </template>

        <template #cell-user_agent="{ row }">
          <span class="ua">{{ row.user_agent || '—' }}</span>
        </template>
      </DataTable>
    </SectionCard>
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.list-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px 12px;
  flex-wrap: wrap;
  padding: 4px 20px 12px;
}

.list-bar .filter-bar { flex: 1 1 auto; }
.list-bar .head-actions { justify-content: flex-end; }

/* 危险操作全部收在「系统设置 → 危险操作」：这里只留一个入口，不开第二个现场 */
.danger-jump {
  color: var(--au-text-3);
  text-decoration: none;
  font-size: 12px;
  padding: 0 4px;
}
.danger-jump:hover { color: var(--au-danger); text-decoration: underline; }
.danger-jump:focus-visible { outline: 2px solid var(--au-border-focus); outline-offset: 2px; border-radius: var(--au-r-sm); }

.user-name { font-weight: 600; color: var(--au-text); }
.muted { color: var(--au-text-4); }

.region {
  display: block;
  font-size: 12px;
  color: var(--au-text-3);
}

.ua {
  font-size: 12px;
  color: var(--au-text-3);
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 768px) {
  .list-bar { padding: 4px 16px 12px; }
}

@media (max-width: 640px) {
  .stat-row { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .ua { max-width: 100%; }
}
</style>
