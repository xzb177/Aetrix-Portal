<script setup lang="ts">
/** 求片管理：审核批准/拒绝/标记完成，联动用户通知 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, RefreshCw, X } from 'lucide-vue-next'
import { fetchMediaSeeks, updateMediaSeek } from '@/api/admin'
import type { MediaSeekRow } from '@/types'

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
      <el-table :data="list" v-loading="loading" style="width: 100%">
        <el-table-column label="片名" min-width="200">
          <template #default="{ row }">
            <span class="movie-name">《{{ row.movie_name }}》</span>
            <span v-if="row.year" class="movie-year">{{ row.year }}</span>
            <div v-if="row.note" class="movie-note">用户备注：{{ row.note }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">{{ row.type === 'movie' ? '电影' : row.type === 'tv' ? '剧集' : (row.type || '—') }}</template>
        </el-table-column>
        <el-table-column label="用户" width="110">
          <template #default="{ row }">{{ row.user_name }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span class="mini-badge" :class="statusBadge(row.status)">{{ statusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="管理备注" min-width="140">
          <template #default="{ row }">{{ row.admin_note || '—' }}</template>
        </el-table-column>
        <el-table-column label="提交时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" size="small" text type="success" @click="review(row, 'approved')">
              <Check :size="13" style="margin-right: 2px" />批准
            </el-button>
            <el-button v-if="row.status === 'pending'" size="small" text type="danger" @click="review(row, 'rejected')">
              <X :size="13" style="margin-right: 2px" />拒绝
            </el-button>
            <el-button v-if="row.status === 'approved'" size="small" text type="primary" @click="review(row, 'completed')">
              标记上架
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; }
.movie-name { font-weight: 600; }
.movie-year { font-size: 12px; color: var(--color-text-muted, #737373); margin-left: 6px; }
.movie-note { font-size: 12px; color: var(--color-text-muted, #737373); margin-top: 2px; }
.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; font-weight: 600; }
.mini-badge.ok { background: var(--success-bg); color: var(--success); }
.mini-badge.warn { background: rgba(234, 179, 8, 0.15); color: #eab308; }
.mini-badge.off { background: rgba(255, 255, 255, 0.08); color: var(--color-text-muted, #737373); }
</style>
