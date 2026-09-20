<script setup lang="ts">
/**
 * 设备风控（v2.6.0）
 *
 * 用户第三方客户端（Infuse / Forward / SenPlayer 等）登录即登记设备。
 * 这里做跨用户审查：查设备、封禁（同时吊销令牌）与移除（踢下线）。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshCw, Ban, CircleCheck, LogOut, Search } from 'lucide-vue-next'
import { fetchDeviceStats, fetchDevices, removeDevice, setDeviceBlocked } from '@/api/admin'
import type { DeviceRow, DeviceStats } from '@/types'

const devices = ref<DeviceRow[]>([])
const stats = ref<DeviceStats | null>(null)
const loading = ref(false)
const total = ref(0)
const filters = ref({ keyword: '', only_blocked: false })

async function load() {
  loading.value = true
  try {
    const [list, stat] = await Promise.all([
      fetchDevices({
        keyword: filters.value.keyword || undefined,
        only_blocked: filters.value.only_blocked || undefined,
        limit: 300,
      }),
      fetchDeviceStats(),
    ])
    devices.value = list.devices
    total.value = list.total
    stats.value = stat
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function toggleBlock(row: DeviceRow) {
  const action = row.is_blocked ? '解封' : '封禁'
  await ElMessageBox.confirm(
    row.is_blocked
      ? `确认解封 ${row.username} 的设备「${row.name || row.device_id}」？`
      : `封禁后该设备已签发的令牌会被吊销，且无法再次登录。确认封禁 ${row.username} 的设备「${row.name || row.device_id}」？`,
    `${action}设备`,
    { type: 'warning' },
  )
  const res = await setDeviceBlocked(row.user_id, row.device_id, !row.is_blocked)
  ElMessage.success(res.message)
  load()
}

async function kick(row: DeviceRow) {
  await ElMessageBox.confirm(
    `移除后该设备令牌立即失效，客户端需重新登录。确认移除 ${row.username} 的设备？`,
    '移除设备',
    { type: 'warning' },
  )
  const res = await removeDevice(row.user_id, row.device_id)
  ElMessage.success(res.message)
  load()
}

function fmt(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

function ago(s: string | null): string {
  if (!s) return '—'
  const diff = Date.now() - new Date(s).getTime()
  if (diff < 0) return '刚刚'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">设备风控</h1>
        <p class="admin-page-subtitle">
          第三方客户端登录设备审查 —— 封禁会同时吊销令牌，移除等于踢下线
        </p>
      </div>
      <div class="toolbar">
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div v-if="stats" class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">设备总数</div>
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-hint">来自 {{ stats.users }} 位用户</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">近 {{ stats.active_days }} 天活跃</div>
        <div class="stat-value">{{ stats.active_30d }}</div>
        <div class="stat-hint">长期未活跃的设备不计入上限</div>
      </div>
      <div class="stat-card" :class="{ danger: stats.blocked > 0 }">
        <div class="stat-label">已封禁</div>
        <div class="stat-value">{{ stats.blocked }}</div>
        <div class="stat-hint">封禁设备无法再次登录</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">每用户上限</div>
        <div class="stat-value">{{ stats.limit_per_user || '不限' }}</div>
        <div class="stat-hint">
          {{ stats.auto_evict ? '超限自动踢最久未用' : '超限直接拒绝新设备' }}
        </div>
      </div>
    </div>

    <div class="admin-card filter-bar">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索用户名 / 设备 / 客户端 / IP"
        style="max-width: 280px"
        clearable
        @keyup.enter="load"
        @clear="load"
      >
        <template #prefix><Search :size="14" /></template>
      </el-input>
      <el-checkbox v-model="filters.only_blocked" @change="load">只看已封禁</el-checkbox>
      <el-button @click="load">查询</el-button>
      <span class="filter-count">共 {{ total }} 台</span>
    </div>

    <div class="admin-card">
      <el-table :data="devices" v-loading="loading" style="width: 100%">
        <el-table-column label="用户" width="150">
          <template #default="{ row }">
            {{ row.username }}
            <span v-if="!row.is_user_active" class="mini-badge danger">已禁用</span>
          </template>
        </el-table-column>
        <el-table-column label="设备" min-width="170">
          <template #default="{ row }">
            <div class="dev-name">{{ row.name || '未命名设备' }}</div>
            <div class="dev-id">{{ row.device_id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="客户端" width="150">
          <template #default="{ row }">
            <div>{{ row.client || '—' }}</div>
            <div class="dev-id">v{{ row.app_version || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="IP" width="130">
          <template #default="{ row }">{{ row.ip || '—' }}</template>
        </el-table-column>
        <el-table-column label="首次" width="150">
          <template #default="{ row }">{{ fmt(row.first_seen_at) }}</template>
        </el-table-column>
        <el-table-column label="最近活跃" width="130">
          <template #default="{ row }">
            <span :class="{ muted: !row.is_online_recent }">{{ ago(row.last_seen_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="mini-badge" :class="row.is_blocked ? 'danger' : 'ok'">
              {{ row.is_blocked ? '已封禁' : '正常' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              text
              :type="row.is_blocked ? 'success' : 'danger'"
              @click="toggleBlock(row)"
            >
              <component :is="row.is_blocked ? CircleCheck : Ban" :size="13" />
              {{ row.is_blocked ? '解封' : '封禁' }}
            </el-button>
            <el-button size="small" text type="warning" @click="kick(row)">
              <LogOut :size="13" />移除
            </el-button>
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
.stat-card.danger { border-color: rgba(239, 68, 68, 0.45); }
.stat-label { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }
.stat-value { font-size: 22px; font-weight: 600; margin: 4px 0 2px; }
.stat-hint { font-size: 11px; color: var(--color-text-muted, #737373); }

.filter-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.filter-count { font-size: 12px; color: var(--color-text-muted, #737373); margin-left: auto; }

.dev-name { font-size: 13px; }
.dev-id {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--color-text-muted, #737373);
  word-break: break-all;
}
.mini-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  background: var(--border-color, #262626);
  color: var(--color-text-secondary, #a3a3a3);
}
.mini-badge.ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.mini-badge.danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.muted { color: var(--color-text-muted, #737373); }
</style>
