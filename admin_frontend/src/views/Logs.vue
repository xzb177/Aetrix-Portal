<script setup lang="ts">
/** 操作日志：管理员操作审计流水 */
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, Search } from 'lucide-vue-next'
import { fetchLogs } from '@/api/admin'
import type { AdminLogRow } from '@/types'

const logs = ref<AdminLogRow[]>([])
const loading = ref(false)
const actionFilter = ref('')
const limit = ref(100)
const keyword = ref('')

/** 前端筛选：按操作人 / 目标 / 详情关键字（后端只提供 action 过滤） */
const visibleLogs = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return logs.value
  return logs.value.filter((l) => {
    const haystack = [l.admin_name, l.action, l.target_type, l.target_id, l.ip_address, JSON.stringify(l.details ?? '')]
      .join(' ')
      .toLowerCase()
    return haystack.includes(kw)
  })
})

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
  grant_subscription: '授予订阅',
  extend_subscription: '延长订阅',
  economy_create_plan: '新建套餐',
  economy_update_plan: '修改套餐',
  economy_delete_plan: '删除套餐',
  economy_create_package: '新建充值包',
  economy_update_package: '修改充值包',
  economy_delete_package: '删除充值包',
  economy_create_exchange_codes: '生成兑换码',
  economy_update_exchange_code: '修改兑换码',
  economy_mark_order_paid: '人工补单',
  economy_adjust_points: '调整积分',
  economy_update_settings: '修改经济设置',
}

/** 高频操作作为快捷筛选项，其余可在下拉中搜索 */
const QUICK_ACTIONS = [
  'economy_mark_order_paid',
  'economy_adjust_points',
  'grant_subscription',
  'update_user',
]

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
        <p class="admin-page-subtitle">
          全部管理操作均有审计记录（最近 {{ limit }} 条{{ keyword ? `，筛出 ${visibleLogs.length} 条` : '' }}）
        </p>
      </div>
      <div class="toolbar">
        <el-input v-model="keyword" placeholder="搜索操作人 / 目标 / 详情" clearable style="width: 220px">
          <template #prefix><Search :size="14" /></template>
        </el-input>
        <el-select v-model="actionFilter" placeholder="操作类型" clearable filterable style="width: 170px" @change="load">
          <el-option v-for="(label, key) in ACTION_LABELS" :key="key" :label="label" :value="key" />
        </el-select>
        <el-select v-model="limit" style="width: 110px" @change="load">
          <el-option :label="'最近 100 条'" :value="100" />
          <el-option :label="'最近 300 条'" :value="300" />
          <el-option :label="'最近 500 条'" :value="500" />
        </el-select>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="quick-filters">
      <button
        v-for="a in QUICK_ACTIONS"
        :key="a"
        class="quick-chip"
        :class="{ active: actionFilter === a }"
        @click="actionFilter = actionFilter === a ? '' : a; load()"
      >{{ ACTION_LABELS[a] }}</button>
    </div>

    <div class="admin-card">
      <el-table :data="visibleLogs" v-loading="loading" style="width: 100%">
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
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: 6px;
  padding: 2px 8px;
}
.log-detail {
  font-size: 12px;
  font-family: ui-monospace, monospace;
  color: var(--text-secondary);
  word-break: break-all;
}

.quick-filters { display: flex; gap: 8px; flex-wrap: wrap; }

.quick-chip {
  padding: 4px 12px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.quick-chip:hover { color: var(--text-primary); border-color: var(--border-strong); }
.quick-chip.active {
  color: var(--primary);
  border-color: var(--primary-border);
  background: var(--primary-bg);
}
</style>
