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
        <h1 class="admin-page-title">登录日志</h1>
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
      <div class="stat-tile">
        <div class="stat-label">日志总数</div>
        <div class="stat-value">{{ data?.total ?? 0 }}</div>
        <div class="stat-hint">按保留天数自动清理</div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': (data?.summary.failed_24h ?? 0) > 0 }">
        <div class="stat-label">24h 登录失败</div>
        <div class="stat-value">{{ data?.summary.failed_24h ?? 0 }}</div>
        <div class="stat-hint">含客户端与门户登录失败</div>
      </div>
      <div class="stat-tile" :class="{ 'is-danger': (data?.summary.risk_24h ?? 0) > 0 }">
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
      <DataTable
        :rows="data?.logs || []"
        :columns="columns"
        :loading="loading"
        empty="暂无登录日志"
      >
        <template #cell-username="{ row }">
          <span class="user-name">{{ row.username || '—' }}</span>
        </template>

        <template #cell-created_at="{ row }">{{ fmt(row.created_at) }}</template>

        <template #cell-reason_label="{ row }">{{ row.reason_label }}</template>

        <template #cell-success="{ row }">
          <span class="mini-badge" :class="row.success ? 'ok' : 'off'">
            {{ row.success ? '成功' : '失败' }}
          </span>
        </template>

        <template #cell-risk="{ row }">
          <span
            class="mini-badge"
            :class="riskLevel(row) === '高风险' ? 'danger' : riskLevel(row) === '注意' ? 'warn' : 'ok'"
          >
            {{ riskLevel(row) }}
          </span>
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
    </div>
  </div>
</template>

<style scoped>
/* 统计瓦片、工具条、徽标都走全局原语，页面只补两种状态描边 */
.stat-tile.is-warn { border-color: var(--warning-border); }
.stat-tile.is-danger { border-color: var(--danger-border); }

.user-name { font-weight: var(--font-weight-semibold); color: var(--text-primary); }

.region {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
}

.ua {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
