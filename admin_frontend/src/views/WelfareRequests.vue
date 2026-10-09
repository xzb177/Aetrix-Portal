<script setup lang="ts">
/**
 * 公益服·求片审核：列表 / 通过 / 拒绝 / 标记已入库
 * 注：这是公益服求片中心（media_requests），与旧版求片管理（MediaSeek）是两套表。
 *
 * v2.55（暗房影院统一）：PageHeader + StatTile + SectionCard(flush)，
 * 逻辑与 PR #432 一致，仅模板迁移到共享组件。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, CircleCheck, Clock3, RefreshCw, X, XCircle } from 'lucide-vue-next'
import { PageHeader, SectionCard, StatTile } from '@/components/ui'
import {
  fetchWelfareRequests,
  approveWelfareRequest,
  rejectWelfareRequest,
  doneWelfareRequest,
  type WelfareRequestRow,
} from '@/api/welfare'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const list = ref<WelfareRequestRow[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref('')

const statusMap: Record<string, string> = {
  pending: '待审核', approved: '已通过', rejected: '已拒绝', done: '已入库',
}

const columns = computed<DataColumn[]>(() => [
  { key: 'title', label: '标题', minWidth: 200, mobile: 'title' },
  { key: 'media_type', label: '类型', width: 80 },
  { key: 'username', label: '申请人', width: 120 },
  { key: 'status', label: '状态', width: 100 },
  { key: 'created_at', label: '申请时间', width: 160 },
  { key: 'actions', label: '操作', width: 220, fixed: 'right', align: 'right' },
])

const statPending = computed(() => list.value.filter(r => r.status === 'pending').length)
const statApproved = computed(() => list.value.filter(r => r.status === 'approved').length)
const statRejected = computed(() => list.value.filter(r => r.status === 'rejected').length)
const statDone = computed(() => list.value.filter(r => r.status === 'done').length)

async function load() {
  loading.value = true
  try {
    const res = await fetchWelfareRequests({ page: page.value, page_size: pageSize.value, status: statusFilter.value || undefined })
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function doApprove(row: WelfareRequestRow) {
  await approveWelfareRequest(row.id, '')
  ElMessage.success('已通过')
  load()
}

async function doReject(row: WelfareRequestRow) {
  const { value } = await ElMessageBox.prompt('拒绝理由', '拒绝求片', { inputPlaceholder: '填写拒绝理由（可选）' }).catch(() => ({ value: null }))
  if (value === null) return
  await rejectWelfareRequest(row.id, value || '')
  ElMessage.success('已拒绝')
  load()
}

async function doDone(row: WelfareRequestRow) {
  await doneWelfareRequest(row.id)
  ElMessage.success('已标记入库')
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="公益服"
      title="求片审核"
      description="审核公益服求片中心的申请：通过、拒绝或标记已入库"
    >
      <template #actions>
        <el-select v-model="statusFilter" placeholder="状态筛选" clearable style="width: 140px" @change="load">
          <el-option label="待审核" value="pending" />
          <el-option label="已通过" value="approved" />
          <el-option label="已拒绝" value="rejected" />
          <el-option label="已入库" value="done" />
        </el-select>
        <el-button :icon="RefreshCw" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <div class="stat-row">
      <StatTile label="待审核" :value="statPending" :icon="Clock3" tone="warn" />
      <StatTile label="已通过" :value="statApproved" :icon="CircleCheck" tone="ok" />
      <StatTile label="已拒绝" :value="statRejected" :icon="XCircle" tone="danger" />
      <StatTile label="已入库" :value="statDone" :icon="Check" tone="info" />
    </div>

    <SectionCard title="求片列表" :meta="`共 ${total} 条`" flush>
      <DataTable :columns="columns" :rows="list" :loading="loading">
        <template #cell-media_type="{ row }">{{ row.media_type === 'tv' ? '剧集' : '电影' }}</template>
        <template #cell-status="{ row }">
          <el-tag :type="row.status === 'pending' ? 'warning' : row.status === 'approved' ? 'success' : row.status === 'done' ? 'info' : 'danger'">
            {{ statusMap[row.status] || row.status }}
          </el-tag>
        </template>
        <template #cell-created_at="{ row }">{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</template>
        <template #cell-actions="{ row }">
          <template v-if="row.status === 'pending'">
            <el-button link type="success" :icon="Check" @click="doApprove(row)">通过</el-button>
            <el-button link type="danger" :icon="X" @click="doReject(row)">拒绝</el-button>
          </template>
          <template v-else-if="row.status === 'approved'">
            <el-button link type="primary" @click="doDone(row)">标记入库</el-button>
          </template>
          <span v-else class="au-muted">—</span>
        </template>
      </DataTable>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" layout="total, prev, pager, next" @change="load"
        class="au-pagination" />
    </SectionCard>
  </div>
</template>

<style scoped>
.stat-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.stat-row > * { flex: 1 1 160px; }
.au-pagination {
  margin-top: 12px;
  justify-content: flex-end;
  padding: 0 16px 16px;
}
.au-muted { color: var(--au-text-2); }
</style>
