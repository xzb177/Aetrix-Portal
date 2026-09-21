<script setup lang="ts">
/** 求片管理：审核批准/拒绝/标记完成，联动用户通知 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, RefreshCw, X } from 'lucide-vue-next'
import { fetchMediaSeeks, updateMediaSeek } from '@/api/admin'
import type { MediaSeekRow } from '@/types'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

/** 手机卡片只留片名 / 类型 / 用户 / 状态 / 时间，管理备注在桌面表格里看 */
const columns: DataColumn[] = [
  { key: 'movie_name', label: '片名', minWidth: 200, mobile: 'title' },
  { key: 'type', label: '类型', width: 80 },
  { key: 'user_name', label: '用户', width: 110 },
  { key: 'status', label: '状态', width: 100 },
  { key: 'admin_note', label: '管理备注', minWidth: 140, mobile: 'hide' },
  { key: 'created_at', label: '提交时间', width: 150 },
  { key: 'actions', label: '操作', width: 200, fixed: 'right', align: 'right' },
]

const list = ref<MediaSeekRow[]>([])
const loading = ref(false)
const statusFilter = ref('')

async function load() {
  loading.value = true
  try {
    list.value = await fetchMediaSeeks(statusFilter.value ? { status_filter: statusFilter.value } : {})
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function review(r: MediaSeekRow, status: string) {
  let adminNote = ''
  if (status === 'rejected') {
    const { value } = await ElMessageBox.prompt('拒绝原因（可选）', `拒绝《${r.movie_name}》`, {
      inputPlaceholder: '如：已有同类型资源 / 片源不可得…',
    })
    adminNote = value || ''
  } else if (status === 'approved') {
    const { value } = await ElMessageBox.prompt('处理备注（可选）', `批准《${r.movie_name}》`, {
      inputPlaceholder: '如：预计本周内上架…',
    })
    adminNote = value || ''
  }

  await updateMediaSeek(r.id, { status, admin_note: adminNote || undefined })
  ElMessage.success({ approved: '已批准', rejected: '已拒绝', completed: '已标记完成' }[status] || '已更新')
  load()
}

function fmtDate(s: string): string {
  return s.slice(0, 16).replace('T', ' ')
}

function statusBadge(status: string): string {
  const map: Record<string, string> = { pending: 'warn', approved: 'ok', completed: 'ok', rejected: 'off' }
  return map[status] || 'off'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = { pending: '待审核', approved: '已批准', completed: '已上架', rejected: '已拒绝' }
  return map[status] || status
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">求片管理</h1>
        <p class="admin-page-subtitle">审核结果会通知提交用户</p>
      </div>
      <div class="toolbar">
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px" @change="load">
          <el-option label="待审核" value="pending" />
          <el-option label="已批准" value="approved" />
          <el-option label="已上架" value="completed" />
          <el-option label="已拒绝" value="rejected" />
        </el-select>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="admin-card">
      <DataTable :rows="list" :columns="columns" :loading="loading" empty="暂无求片记录">
        <template #cell-movie_name="{ row }">
          <span class="movie-name">《{{ row.movie_name }}》</span>
          <span v-if="row.year" class="movie-year">{{ row.year }}</span>
          <div v-if="row.note" class="movie-note">用户备注：{{ row.note }}</div>
        </template>

        <template #cell-type="{ row }">
          {{ row.type === 'movie' ? '电影' : row.type === 'tv' ? '剧集' : (row.type || '—') }}
        </template>

        <template #cell-user_name="{ row }">{{ row.user_name }}</template>

        <template #cell-status="{ row }">
          <span class="mini-badge" :class="statusBadge(row.status)">{{ statusLabel(row.status) }}</span>
        </template>

        <template #cell-admin_note="{ row }">
          <span v-if="!row.admin_note" class="muted">—</span>
          <span v-else>{{ row.admin_note }}</span>
        </template>

        <template #cell-created_at="{ row }">{{ fmtDate(row.created_at) }}</template>

        <template #cell-actions="{ row }">
          <el-button v-if="row.status === 'pending'" size="small" type="success" plain @click="review(row, 'approved')">
            <Check :size="13" style="margin-right: 3px" />批准
          </el-button>
          <el-button v-if="row.status === 'pending'" size="small" type="danger" plain @click="review(row, 'rejected')">
            <X :size="13" style="margin-right: 3px" />拒绝
          </el-button>
          <el-button v-if="row.status === 'approved'" size="small" type="primary" plain @click="review(row, 'completed')">
            标记上架
          </el-button>
          <span v-if="row.status === 'completed' || row.status === 'rejected'" class="muted done-hint">
            已处理
          </span>
        </template>
      </DataTable>
    </div>
  </div>
</template>

<style scoped>
/* 工具条、徽标、muted 等技术样式已收到全局原语（styles/index.css），页面只留专有样式 */
.movie-name { font-weight: var(--font-weight-semibold); color: var(--text-primary); }
.movie-year { font-size: var(--font-size-xs); color: var(--text-muted); margin-left: 6px; }
.movie-note { font-size: var(--font-size-xs); color: var(--text-muted); margin-top: 3px; }
.done-hint { font-size: var(--font-size-xs); }
</style>
