<script setup lang="ts">
/** 工单管理：列表筛选/回复/关闭，回复联动站内通知 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshCw, Send } from 'lucide-vue-next'
import { closeTicket, fetchTicketMessages, fetchTickets, replyTicket, updateTicket } from '@/api/admin'
import type { TicketMessageRow, TicketRow } from '@/types'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const columns: DataColumn[] = [
  { key: 'title', label: '工单', minWidth: 240, mobile: 'title' },
  { key: 'user_name', label: '用户', width: 120 },
  { key: 'category', label: '分类', width: 90, mobile: 'hide' },
  { key: 'priority', label: '优先级', width: 90 },
  { key: 'status', label: '状态', width: 100 },
  { key: 'updated_at', label: '更新时间', width: 150 },
  { key: 'actions', label: '操作', width: 110, fixed: 'right', align: 'right' },
]

const list = ref<TicketRow[]>([])
const loading = ref(false)
const statusFilter = ref('')

const drawerVisible = ref(false)
const current = ref<TicketRow | null>(null)
const messages = ref<TicketMessageRow[]>([])
const replyText = ref('')
const sending = ref(false)
const metaSaving = ref(false)

async function load() {
  loading.value = true
  try {
    list.value = await fetchTickets(statusFilter.value ? { status_filter: statusFilter.value } : {})
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function openDetail(t: TicketRow) {
  current.value = t
  messages.value = await fetchTicketMessages(t.id)
  replyText.value = ''
  drawerVisible.value = true
}

async function send(closeAfter: boolean) {
  if (!current.value || !replyText.value.trim()) return
  sending.value = true
  try {
    await replyTicket(current.value.id, { message: replyText.value, close_ticket: closeAfter })
    ElMessage.success(closeAfter ? '已回复并关闭工单' : '回复成功')
    drawerVisible.value = false
    load()
  } finally {
    sending.value = false
  }
}

async function close(t: TicketRow) {
  await closeTicket(t.id)
  ElMessage.success('工单已关闭')
  if (current.value?.id === t.id) current.value.status = 'closed'
  load()
}

/** 抽屉内直接调整状态 / 优先级（后端 PUT /tickets/{id}） */
async function patchTicket(patch: { status?: string; priority?: string }) {
  if (!current.value) return
  metaSaving.value = true
  try {
    await updateTicket(current.value.id, patch)
    Object.assign(current.value, patch)
    ElMessage.success('工单已更新并通知用户')
    load()
  } catch {
    // 拦截器已提示
  } finally {
    metaSaving.value = false
  }
}

const PRIORITY_LABELS: Record<string, string> = { low: '低', medium: '中', high: '高', urgent: '紧急' }

function fmtDate(s: string): string {
  return s.slice(0, 16).replace('T', ' ')
}

function statusLabel(status: string): string {
  const map: Record<string, string> = { open: '进行中', pending: '待处理', closed: '已关闭' }
  return map[status] || status
}

function statusBadge(status: string): string {
  const map: Record<string, string> = { open: 'ok', pending: 'warn', closed: 'off' }
  return map[status] || 'off'
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">工单管理</h1>
        <p class="admin-page-subtitle">回复会以站内消息通知用户</p>
      </div>
      <div class="toolbar">
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px" @change="load">
          <el-option label="进行中" value="open" />
          <el-option label="已关闭" value="closed" />
        </el-select>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="admin-card">
      <DataTable :rows="list" :columns="columns" :loading="loading" empty="暂无工单">
        <template #cell-title="{ row }">
          <button class="ticket-title" @click="openDetail(row)">{{ row.title }}</button>
          <div class="ticket-preview">{{ row.latest_message || '—' }}</div>
        </template>

        <template #cell-user_name="{ row }">{{ row.user_name }}</template>

        <template #cell-category="{ row }">{{ row.category }}</template>

        <template #cell-priority="{ row }">
          <span class="prio" :class="row.priority">{{ PRIORITY_LABELS[row.priority] || row.priority }}</span>
        </template>

        <template #cell-status="{ row }">
          <span class="mini-badge" :class="statusBadge(row.status)">{{ statusLabel(row.status) }}</span>
        </template>

        <template #cell-updated_at="{ row }">{{ fmtDate(row.updated_at) }}</template>

        <template #cell-actions="{ row }">
          <el-button v-if="row.status !== 'closed'" size="small" type="danger" plain @click="close(row)">
            关闭
          </el-button>
          <span v-else class="muted done-hint">已关闭</span>
        </template>
      </DataTable>
    </div>

    <el-drawer v-model="drawerVisible" :title="current?.title || '工单详情'" size="460px">
      <div v-if="current" class="ticket-meta">
        <div class="meta-line">
          <span class="meta-label">提交人</span>
          <span>{{ current.user_name }}</span>
          <span class="meta-label">分类</span>
          <span>{{ current.category }}</span>
          <span class="meta-label">创建</span>
          <span>{{ fmtDate(current.created_at) }}</span>
        </div>
        <div class="meta-controls">
          <span class="meta-label">状态</span>
          <el-select
            :model-value="current.status"
            size="small"
            style="width: 110px"
            :disabled="metaSaving"
            @change="(v: string) => patchTicket({ status: v })"
          >
            <el-option label="进行中" value="open" />
            <el-option label="待处理" value="pending" />
            <el-option label="已关闭" value="closed" />
          </el-select>
          <span class="meta-label">优先级</span>
          <el-select
            :model-value="current.priority"
            size="small"
            style="width: 110px"
            :disabled="metaSaving"
            @change="(v: string) => patchTicket({ priority: v })"
          >
            <el-option v-for="(label, key) in PRIORITY_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </div>
      </div>

      <div class="msg-list">
        <div v-for="m in messages" :key="m.id" class="msg" :class="{ admin: m.is_admin }">
          <div class="msg-meta">
            {{ m.is_admin ? (m.admin_name || '管理员') : current?.user_name }} · {{ fmtDate(m.created_at) }}
          </div>
          <div class="msg-body">{{ m.message }}</div>
        </div>
      </div>

      <div class="reply-box" v-if="current && current.status !== 'closed'">
        <el-input v-model="replyText" type="textarea" :rows="3" placeholder="输入回复内容…" />
        <div class="reply-actions">
          <el-button :disabled="sending || !replyText.trim()" @click="send(false)">
            <Send :size="14" style="margin-right: 4px" />回复
          </el-button>
          <el-button type="primary" :disabled="sending || !replyText.trim()" @click="send(true)">回复并关闭</el-button>
        </div>
      </div>
      <div v-else class="closed-hint">工单已关闭</div>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; }
.ticket-title { background: none; border: none; color: inherit; font-weight: 600; font-size: 14px; cursor: pointer; padding: 0; text-align: left; }
.ticket-title:hover { color: var(--primary); }
.ticket-preview {
  font-size: 12px;
  color: var(--color-text-muted, #737373);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}
.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; font-weight: 600; }
.mini-badge.ok { background: var(--success-bg); color: var(--success); }
.mini-badge.warn { background: rgba(234, 179, 8, 0.15); color: #eab308; }
.mini-badge.off { background: rgba(255, 255, 255, 0.08); color: var(--color-text-muted, #737373); }

.prio { font-size: 11px; color: var(--text-secondary); }
.prio.high, .prio.urgent { color: var(--danger); font-weight: 600; }
.prio.low { color: var(--text-muted); }

.ticket-meta {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  margin-bottom: 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--bg-glass);
}

.meta-line, .meta-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12.5px; }
.meta-label { color: var(--text-muted); }

.msg-list { display: flex; flex-direction: column; gap: 12px; }
.msg {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 12px;
  padding: 10px 12px;
}
.msg.admin { background: var(--primary-bg); border: 1px solid var(--primary-border); }
.msg-meta { font-size: 11px; color: var(--color-text-muted, #737373); margin-bottom: 4px; }
.msg-body { font-size: 13px; line-height: 1.6; white-space: pre-wrap; }

.reply-box { margin-top: 16px; }
.reply-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
.closed-hint { margin-top: 16px; text-align: center; color: var(--color-text-muted, #737373); font-size: 13px; }
</style>
