<script setup lang="ts">
/** 操作日志：管理员操作审计流水 */
import { onMounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { fetchLogs } from '@/api/admin'
import type { AdminLogRow } from '@/types'

const logs = ref<AdminLogRow[]>([])
const loading = ref(false)
const actionFilter = ref('')
const limit = ref(100)

const ACTION_LABELS: Record<string, string> = {
  admin_change_password: '管理员改密',
  update_user: '更新用户',
  reset_user_password: '重置用户密码',
  send_user_message: '发送用户消息',
  broadcast_message: '全站广播',
  create_registration_codes: '生成注册码',
  update_registration_code: '更新注册码',
  set_registration_mode: '设置注册模式',
  create_announcement: '发布公告',
  update_announcement: '更新公告',
  delete_announcement: '删除公告',
  update_ticket: '更新工单',
  reply_ticket: '回复工单',
  update_media_seek: '审核求片',
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { limit: limit.value }
    if (actionFilter.value) params.action_filter = actionFilter.value
    logs.value = await fetchLogs(params)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmtDate(s: string): string {
  return s.slice(0, 19).replace('T', ' ')
}

function detailText(log: AdminLogRow): string {
  if (!log.details) return ''
  const parts: string[] = []
  for (const [k, v] of Object.entries(log.details)) {
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
  }
  return parts.join(' ')
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">操作日志</h1>
        <p class="admin-page-subtitle">全部管理操作均有审计记录（最近 {{ limit }} 条）</p>
      </div>
      <div class="toolbar">
        <el-select v-model="actionFilter" placeholder="操作类型" clearable filterable style="width: 170px" @change="load">
          <el-option v-for="(label, key) in ACTION_LABELS" :key="key" :label="label" :value="key" />
        </el-select>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="admin-card">
      <el-table :data="logs" v-loading="loading" style="width: 100%" :header-cell-style="{ background: 'transparent', color: '#a3a3a3' }">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作人" prop="admin_name" width="120" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <span class="action-chip">{{ ACTION_LABELS[row.action] || row.action }}</span>
          </template>
        </el-table-column>
        <el-table-column label="目标" width="120">
          <template #default="{ row }">
            <span v-if="row.target_type">{{ row.target_type }}#{{ row.target_id }}</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="详情" min-width="260">
          <template #default="{ row }">
            <span class="log-detail">{{ detailText(row) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="IP" prop="ip_address" width="130">
          <template #default="{ row }">{{ row.ip_address || '—' }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; }
.action-chip {
  font-size: 11px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border-radius: 6px;
  padding: 2px 8px;
}
.log-detail {
  font-size: 12px;
  font-family: ui-monospace, monospace;
  color: var(--color-text-secondary, #a3a3a3);
  word-break: break-all;
}
</style>
