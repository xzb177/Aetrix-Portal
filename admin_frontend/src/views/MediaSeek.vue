<script setup lang="ts">
/** 求片管理：审核批准/拒绝/标记完成，联动用户通知 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, CloudDownload, Download, RefreshCw, X } from 'lucide-vue-next'
import { fetchMediaSeeks, fetchServersSummary, pushMediaSeek, updateMediaSeek } from '@/api/admin'
import type { MediaSeekRow, ServerKind } from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const realm = useRealmStore()
/** 统计范围：当前服（默认）或全部服 */
const scope = ref<'realm' | 'all'>('realm')

/** 手机卡片只留片名 / 类型 / 用户 / 状态 / 时间，管理备注在桌面表格里看 */
const columns = computed<DataColumn[]>(() => [
  { key: 'movie_name', label: '片名', minWidth: 200, mobile: 'title' },
  { key: 'type', label: '类型', width: 80 },
  { key: 'user_name', label: '用户', width: 110 },
  // 求片是「给哪个服求的」：跨服汇总时才需要这一列
  ...(scope.value === 'all'
    ? [{ key: 'realm_name', label: '求给', minWidth: 110 } as DataColumn]
    : []),
  { key: 'status', label: '状态', width: 100 },
  { key: 'push', label: '转交外部服务', width: 170 },
  { key: 'admin_note', label: '管理备注', minWidth: 140, mobile: 'hide' },
  { key: 'created_at', label: '提交时间', width: 150 },
  // 批准 / 拒绝 / 转交 / 标记上架可能同时出现，给足宽度免得按钮被挤成两行
  { key: 'actions', label: '操作', width: 330, fixed: 'right', align: 'right' },
])

const list = ref<MediaSeekRow[]>([])
const loading = ref(false)
const statusFilter = ref('')
const busyId = ref<number | null>(null)
/** 哪几类外部服务已经接好（用于决定显示哪些推送按钮） */
const pushReady = ref<ServerKind[]>([])

const canMoviePilot = computed(() => pushReady.value.includes('moviepilot'))
const canQbittorrent = computed(() => pushReady.value.includes('qbittorrent'))
/** 一个能推的都没有：直接把入口指去「服务器」页，而不是发一个点了也不动的按钮 */
const noPushTarget = computed(() => !canMoviePilot.value && !canQbittorrent.value)

async function load() {
  loading.value = true
  try {
    const params: { status_filter?: string; realm_id?: number } = {}
    if (statusFilter.value) params.status_filter = statusFilter.value
    // 求片登记的是「给哪个服求」；realm_id=0 = 全部服（后端未标注的也算进来）
    params.realm_id = scope.value === 'all' ? 0 : (realm.activeId ?? 0)
    list.value = await fetchMediaSeeks(params)
    // 服务器没接好时按钮点了也只会失败，所以这里如实反映当前可用目标
    const summary = await fetchServersSummary()
    pushReady.value = summary.push_ready || []
  } finally {
    loading.value = false
  }
}

/** 推给 MoviePilot：它自己去搜索、下载、整理入库 */
async function pushToMoviePilot(r: MediaSeekRow) {
  busyId.value = r.id
  try {
    const res = await pushMediaSeek(r.id, { target: 'moviepilot' })
    res.success ? ElMessage.success(res.message || '已提交给 MoviePilot') : ElMessage.warning(res.message)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyId.value = null
  }
}

/** 交给 qBittorrent：qB 自己不会找片子，所以必须提供磁力 / 种子链接 */
async function pushToQbittorrent(r: MediaSeekRow) {
  const { value } = await ElMessageBox.prompt(
    `把《${r.movie_name}》的下载链接交给 qBittorrent`,
    '交给下载器',
    { inputPlaceholder: 'magnet:?xt=… 或 .torrent 的 http 地址', inputType: 'textarea' }
  )
  if (!value) return
  busyId.value = r.id
  try {
    const res = await pushMediaSeek(r.id, { target: 'qbittorrent', link: value })
    res.success ? ElMessage.success(res.message || '已交给下载器') : ElMessage.warning(res.message)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyId.value = null
  }
}

function pushLabel(target: string | null): string {
  if (target === 'moviepilot') return 'MoviePilot'
  if (target === 'qbittorrent') return 'qBittorrent'
  return target || '—'
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
        <el-radio-group v-model="scope" size="small" @change="load">
          <el-radio-button value="realm">当前服</el-radio-button>
          <el-radio-button value="all">全部服</el-radio-button>
        </el-radio-group>
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px" @change="load">
          <el-option label="待审核" value="pending" />
          <el-option label="已批准" value="approved" />
          <el-option label="已上架" value="completed" />
          <el-option label="已拒绝" value="rejected" />
        </el-select>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <!-- 没接好 MoviePilot / qB 时，求片批了也没法真的把片子弄进来：如实说明并给出入口 -->
    <el-alert v-if="noPushTarget" type="warning" :closable="false" show-icon class="push-guide">
      <template #default>
        还没有可以接收求片的服务：请在「服务器」页添加 <b>MoviePilot</b>（搜片下载与整理）或
        <b>qBittorrent</b>（下载器），测试连接通过后这里就会出现转交按钮。
      </template>
    </el-alert>

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

        <template #cell-realm_name="{ row }">
          <span class="mini-badge muted">{{ row.realm_name || '未标注' }}</span>
        </template>

        <template #cell-status="{ row }">
          <span class="mini-badge" :class="statusBadge(row.status)">{{ statusLabel(row.status) }}</span>
        </template>

        <template #cell-admin_note="{ row }">
          <span v-if="!row.admin_note" class="muted">—</span>
          <span v-else>{{ row.admin_note }}</span>
        </template>

        <template #cell-push="{ row }">
          <div v-if="!row.push_target" class="muted">未转交</div>
          <div v-else class="push-cell">
            <span class="mini-badge" :class="row.push_status === 'ok' ? 'ok' : 'danger'">
              {{ pushLabel(row.push_target) }}{{ row.push_status === 'ok' ? ' 已提交' : ' 失败' }}
            </span>
            <el-tooltip v-if="row.push_message" :content="row.push_message" placement="top">
              <span class="muted push-msg">{{ row.push_message }}</span>
            </el-tooltip>
          </div>
        </template>

        <template #cell-created_at="{ row }">{{ fmtDate(row.created_at) }}</template>

        <template #cell-actions="{ row }">
          <el-button v-if="row.status === 'pending'" size="small" type="success" plain @click="review(row, 'approved')">
            <Check :size="13" style="margin-right: 3px" />批准
          </el-button>
          <el-button v-if="row.status === 'pending'" size="small" type="danger" plain @click="review(row, 'rejected')">
            <X :size="13" style="margin-right: 3px" />拒绝
          </el-button>
          <el-button
            v-if="canMoviePilot && (row.status === 'pending' || row.status === 'approved')"
            size="small"
            type="primary"
            plain
            :loading="busyId === row.id"
            @click="pushToMoviePilot(row)"
          >
            <CloudDownload :size="13" style="margin-right: 3px" />交 MoviePilot
          </el-button>
          <el-button
            v-if="canQbittorrent && (row.status === 'pending' || row.status === 'approved')"
            size="small"
            plain
            :loading="busyId === row.id"
            @click="pushToQbittorrent(row)"
          >
            <Download :size="13" style="margin-right: 3px" />交给 qB
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
.push-guide { margin-bottom: 14px; line-height: 1.7; }
.push-cell { display: flex; flex-direction: column; gap: 3px; }
.push-cell .mini-badge { align-self: flex-start; }
.push-msg { display: block; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--font-size-xs); }
</style>
