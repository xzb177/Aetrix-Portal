<script setup lang="ts">
/**
 * 登录 / 安全日志（v2.6.0）
 *
 * 记录门户与客户端登录、登录失败、设备超限被拒、诱饵码触发封禁等事件，
 * 供风控审查；支持按保留天数清理，避免表无限增长。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, Search, Trash2, ShieldAlert } from 'lucide-vue-next'
import { fetchLoginLogs, purgeLoginLogs } from '@/api/admin'
import type { LoginLogRow, LoginLogsResponse } from '@/types'

const data = ref<LoginLogsResponse | null>(null)
const loading = ref(false)
const filters = ref<{ username: string; ip: string; reason: string; success: string }>({
  username: '',
  ip: '',
  reason: '',
  success: '',
})

async function load() {
  loading.value = true
  try {
    data.value = await fetchLoginLogs({
      username: filters.value.username || undefined,
      ip: filters.value.ip || undefined,
      reason: filters.value.reason || undefined,
      success: filters.value.success === '' ? undefined : filters.value.success === 'true',
      limit: 300,
    })
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function purge(preset: number) {
  const label = preset === 0 ? '清空全部日志' : `清理 ${preset} 天前的日志`
  await ElMessageBox.confirm(`${label}？该操作不可撤销。`, '清理日志', { type: 'warning' })
  const res = await purgeLoginLogs(preset)
  ElMessage.success(res.message)
  load()
}

function fmt(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 19).replace('T', ' ')
}

function riskLevel(row: LoginLogRow): string {
  if (row.reason === 'decoy_code' || row.reason === 'device_limit') return '高风险'
  if (!row.success) return '注意'
  return '正常'
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">登录与安全日志</h1>
        <p class="admin-page-subtitle">登录成功/失败、设备超限、诱饵码触发等风控事件审查</p>
      </div>
      <div class="toolbar">
        <el-button @click="purge(data && data.total > 0 ? 90 : 0)">
          <Trash2 :size="14" style="margin-right: 4px" />清理日志
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">日志总数</div>
        <div class="stat-value">{{ data?.total ?? 0 }}</div>
        <div class="stat-hint">按保留天数自动清理</div>
      </div>
      <div class="stat-card" :class="{ warn: (data?.summary.failed_24h ?? 0) > 0 }">
        <div class="stat-label">24h 登录失败</div>
        <div class="stat-value">{{ data?.summary.failed_24h ?? 0 }}</div>
        <div class="stat-hint">含客户端与门户登录失败</div>
      </div>
      <div class="stat-card" :class="{ danger: (data?.summary.risk_24h ?? 0) > 0 }">
        <div class="stat-label">24h 风控拦截</div>
        <div class="stat-value">{{ data?.summary.risk_24h ?? 0 }}</div>
        <div class="stat-hint">
          <ShieldAlert :size="12" /> 设备超限 / 诱饵码触发
        </div>
      </div>
    </div>

    <div class="admin-card filter-bar">
      <el-input
        v-model="filters.username"
        placeholder="用户名"
        style="width: 160px"
        clearable
        @keyup.enter="load"
        @clear="load"
      />
      <el-input
        v-model="filters.ip"
        placeholder="IP"
        style="width: 150px"
        clearable
        @keyup.enter="load"
        @clear="load"
      />
      <el-select v-model="filters.reason" placeholder="全部事件" style="width: 170px" @change="load">
        <el-option value="" label="全部事件" />
        <el-option
          v-for="r in data?.reasons || []"
          :key="r.value"
          :value="r.value"
          :label="r.label"
        />
      </el-select>
      <el-select v-model="filters.success" placeholder="全部结果" style="width: 130px" @change="load">
        <el-option value="" label="全部结果" />
        <el-option value="true" label="成功" />
        <el-option value="false" label="失败" />
      </el-select>
      <el-button @click="load"><Search :size="14" /></el-button>
    </div>

    <div class="admin-card">
      <el-table :data="data?.logs || []" v-loading="loading" style="width: 100%">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="用户" width="140">
          <template #default="{ row }">{{ row.username || '—' }}</template>
        </el-table-column>
        <el-table-column label="事件" width="140">
          <template #default="{ row }">{{ row.reason_label }}</template>
        </el-table-column>
        <el-table-column label="结果" width="96">
          <template #default="{ row }">
            <span class="mini-badge" :class="row.success ? 'ok' : 'off'">
              {{ row.success ? '成功' : '失败' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="风险" width="90">
          <template #default="{ row }">
            <span
              class="mini-badge"
              :class="riskLevel(row) === '高风险' ? 'danger' : riskLevel(row) === '注意' ? 'warn' : 'ok'"
            >
              {{ riskLevel(row) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="IP" width="130">
          <template #default="{ row }">{{ row.ip || '—' }}</template>
        </el-table-column>
        <el-table-column label="详情" min-width="200">
          <template #default="{ row }">{{ row.detail || '—' }}</template>
        </el-table-column>
        <el-table-column label="客户端" min-width="180">
          <template #default="{ row }">
            <span class="ua">{{ row.user_agent || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.stat-card {
  background: var(--card-bg, #171717);
  border: 1px solid var(--border-color, #262626);
  border-radius: 12px;
  padding: 14px 16px;
}
.stat-card.warn { border-color: rgba(250, 204, 21, 0.4); }
.stat-card.danger { border-color: rgba(239, 68, 68, 0.45); }
.stat-label { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }
.stat-value { font-size: 22px; font-weight: 600; margin: 4px 0 2px; }
.stat-hint {
  font-size: 11px;
  color: var(--color-text-muted, #737373);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }

.mini-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  background: var(--border-color, #262626);
  color: var(--color-text-secondary, #a3a3a3);
}
.mini-badge.ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.mini-badge.warn { background: rgba(250, 204, 21, 0.15); color: #facc15; }
.mini-badge.danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.ua {
  font-size: 11px;
  color: var(--color-text-muted, #737373);
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
