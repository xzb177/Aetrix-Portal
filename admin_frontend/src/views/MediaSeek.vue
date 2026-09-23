<script setup lang="ts">
/** 求片管理：审核批准/拒绝/标记完成，联动用户通知 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
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
  // 所有动作都收进「处理」弹窗：行里只留一个入口，不再挤成一排按钮
  { key: 'actions', label: '操作', width: 110, fixed: 'right', align: 'right' },
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

// ==================== 处理弹窗（v2.29.0） ====================
// 以前一行里摊着 5 个按钮（批准 / 拒绝 / 交 MoviePilot / 交给 qB / 标记上架），
// 拒绝与批准还要再弹一次输入框——既挤又看不全上下文（用户备注、转交结果都得切页找）。
// 现在行里只有一个「处理」按钮，弹窗里把求片详情 + 处理备注 + 全部动作放在一处。
const handle = ref({
  visible: false,
  row: null as MediaSeekRow | null,
  /** 处理备注（批准 / 拒绝时写库，拒绝会作为原因展示给用户） */
  note: '',
  /** qBittorrent 需要的磁力 / 种子地址（qB 自己不会找片子） */
  link: '',
})

/** 这一行还有没有可做的动作（已上架 / 已拒绝 / 已撤回只是查看） */
function isActionable(r: MediaSeekRow): boolean {
  return r.status === 'pending' || r.status === 'approved'
}

function openHandle(r: MediaSeekRow) {
  handle.value = { visible: true, row: r, note: r.admin_note || '', link: '' }
}

/** 动作做完刷新列表，并把弹窗里的行换成最新快照（转交结果、状态就地可见） */
async function afterAction(id: number) {
  await load()
  const fresh = list.value.find((x) => x.id === id)
  if (fresh) {
    handle.value.row = fresh
  } else {
    // 被当前状态筛选挡掉了（例如筛「待审核」时批准了）：如实说明，别把旧快照留在弹窗里
    handle.value.visible = false
    ElMessage.info('已处理，该求片不再符合当前筛选条件')
  }
}

/** 批准 / 拒绝 / 标记上架 */
async function reviewStatus(status: string) {
  const r = handle.value.row
  if (!r) return
  busyId.value = r.id
  try {
    await updateMediaSeek(r.id, {
      status,
      admin_note: handle.value.note.trim() || undefined,
    })
    ElMessage.success(
      { approved: '已批准', rejected: '已拒绝', completed: '已标记上架' }[status] || '已更新'
    )
    await afterAction(r.id)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyId.value = null
  }
}

/** 转交外部服务：MoviePilot（提交订阅）或 qBittorrent（加种，必须带链接） */
async function pushTo(target: 'moviepilot' | 'qbittorrent') {
  const r = handle.value.row
  if (!r) return
  const link = handle.value.link.trim()
  if (target === 'qbittorrent' && !link) {
    ElMessage.warning('交给 qBittorrent 需要先填磁力 / 种子地址')
    return
  }
  busyId.value = r.id
  try {
    const res = await pushMediaSeek(r.id, target === 'qbittorrent' ? { target, link } : { target })
    res.success
      ? ElMessage.success(res.message || `已提交给 ${pushLabel(target)}`)
      : ElMessage.warning(res.message)
    handle.value.link = ''
    await afterAction(r.id)
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

function fmtDate(s: string): string {
  return s.slice(0, 16).replace('T', ' ')
}

function statusBadge(status: string): string {
  const map: Record<string, string> = {
    pending: 'warn', approved: 'ok', completed: 'ok', rejected: 'off', withdrawn: 'off',
  }
  return map[status] || 'off'
}

function typeLabel(type: string | null): string {
  if (type === 'movie') return '电影'
  if (type === 'tv') return '剧集'
  return type || '—'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待审核', approved: '已批准', completed: '已上架', rejected: '已拒绝',
    // 用户自己撤掉的：默认不进待办清单，只能靠状态筛选查（下面有这一项）
    withdrawn: '已撤回',
  }
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
          <!-- 用户自己撤掉的默认不在待办里（额度仍按提交数算），需要审计时从这里查 -->
          <el-option label="已撤回" value="withdrawn" />
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

        <template #cell-type="{ row }">{{ typeLabel(row.type) }}</template>

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
          <!-- 一个入口：详情 + 批准 / 拒绝 / 转交 / 标记上架 都在弹窗里（原来这行有 5 个按钮） -->
          <el-button
            size="small"
            :type="isActionable(row) ? 'primary' : 'default'"
            :plain="isActionable(row)"
            @click="openHandle(row)"
          >
            {{ isActionable(row) ? '处理' : '查看' }}
          </el-button>
        </template>
      </DataTable>
    </div>

    <!--
      处理弹窗（v2.29.0）：求片详情 + 处理备注 + 全部动作都在这一处。
      动作做完弹窗不关——就地换成最新快照，转交结果 / 新状态直接可见，
      而且换行的动作（批准 → 标记上架）不用再重新找到那一行。
    -->
    <el-dialog
      v-model="handle.visible"
      :title="handle.row ? `处理求片《${handle.row.movie_name}》` : '处理求片'"
      width="560px"
    >
      <div v-if="handle.row" class="handle-body">
        <div class="kv-list">
          <div class="kv-row"><span class="kv-key">片名</span><span class="kv-value">《{{ handle.row.movie_name }}》</span></div>
          <div class="kv-row"><span class="kv-key">年份 / 类型</span>
            <span class="kv-value">{{ handle.row.year || '—' }} · {{ typeLabel(handle.row.type) }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">提交用户</span><span class="kv-value">{{ handle.row.user_name }}</span></div>
          <div class="kv-row"><span class="kv-key">求给</span>
            <span class="kv-value">{{ handle.row.realm_name || '未标注' }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">提交时间</span><span class="kv-value">{{ fmtDate(handle.row.created_at) }}</span></div>
          <div class="kv-row"><span class="kv-key">当前状态</span>
            <span class="kv-value">
              <span class="mini-badge" :class="statusBadge(handle.row.status)">{{ statusLabel(handle.row.status) }}</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">用户备注</span>
            <span class="kv-value">{{ handle.row.note || '—' }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">转交外部服务</span>
            <span class="kv-value">
              <template v-if="!handle.row.push_target">未转交</template>
              <template v-else>
                {{ pushLabel(handle.row.push_target) }}{{ handle.row.push_status === 'ok' ? ' 已提交' : ' 失败' }}
                <span v-if="handle.row.push_message" class="push-msg-line">{{ handle.row.push_message }}</span>
              </template>
            </span>
          </div>
        </div>

        <el-form label-position="top" class="handle-form">
          <el-form-item label="处理备注">
            <el-input
              v-model="handle.note"
              type="textarea"
              :rows="2"
              placeholder="如：预计本周内上架 / 已有同类型资源…"
            />
            <p class="form-hint">拒绝时会作为原因展示给提交用户；批准时作为进度说明（可不填）。</p>
          </el-form-item>

          <!-- qBittorrent 自己不会找片子：要交给它就必须在这里把链接填上（原来是一个二次弹窗） -->
          <el-form-item v-if="canQbittorrent && isActionable(handle.row)" label="qBittorrent 下载地址">
            <el-input
              v-model="handle.link"
              type="textarea"
              :rows="2"
              placeholder="magnet:?xt=… 或 .torrent 的 http 地址（只在这条求片交给 qB 时使用）"
            />
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <div class="handle-footer">
          <el-button @click="handle.visible = false">关闭</el-button>
          <div class="handle-actions">
            <el-button
              v-if="handle.row?.status === 'pending'"
              size="small"
              type="danger"
              plain
              :loading="busyId === handle.row.id"
              @click="reviewStatus('rejected')"
            >
              <X :size="13" style="margin-right: 3px" />拒绝
            </el-button>
            <el-button
              v-if="handle.row?.status === 'pending'"
              size="small"
              type="success"
              plain
              :loading="busyId === handle.row.id"
              @click="reviewStatus('approved')"
            >
              <Check :size="13" style="margin-right: 3px" />批准
            </el-button>
            <el-button
              v-if="handle.row?.status === 'approved'"
              size="small"
              type="primary"
              plain
              :loading="busyId === handle.row.id"
              @click="reviewStatus('completed')"
            >
              标记上架
            </el-button>
            <el-button
              v-if="canMoviePilot && handle.row && isActionable(handle.row)"
              size="small"
              type="primary"
              plain
              :loading="busyId === handle.row.id"
              @click="pushTo('moviepilot')"
            >
              <CloudDownload :size="13" style="margin-right: 3px" />交 MoviePilot
            </el-button>
            <el-button
              v-if="canQbittorrent && handle.row && isActionable(handle.row)"
              size="small"
              plain
              :loading="busyId === handle.row.id"
              @click="pushTo('qbittorrent')"
            >
              <Download :size="13" style="margin-right: 3px" />交给 qB
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>
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

/* 处理弹窗：详情用全局 .kv-list 原语，只补两处专有间距 */
.handle-body { display: flex; flex-direction: column; gap: 14px; }
/* 弹窗里的键值行靠左：值是片名 / 备注 / 报错这类长文本，右对齐读不动 */
.handle-body .kv-row .kv-value { text-align: left; }
.handle-form { margin-top: 2px; }
.handle-form :deep(.el-form-item) { margin-bottom: 12px; }
.push-msg-line { display: block; font-size: var(--font-size-xs); color: var(--text-muted); margin-top: 2px; }
.handle-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.handle-actions { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
