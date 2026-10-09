<script setup lang="ts">
/** 公告管理：创建/编辑/置顶/删除，联动全站推送 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Megaphone, Plus, RefreshCw, Search } from 'lucide-vue-next'
import { PageHeader, SectionCard } from '@/components/ui'
import { createAnnouncement, deleteAnnouncement, fetchAnnouncements, updateAnnouncement } from '@/api/admin'
import type { Announcement } from '@/types'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const columns: DataColumn[] = [
  { key: 'title', label: '公告', minWidth: 260, mobile: 'title' },
  { key: 'type', label: '类型', width: 90 },
  { key: 'is_active', label: '状态', width: 90 },
  { key: 'created_at', label: '发布时间', width: 150 },
  // 置顶 / 停用 / 删除收进「管理」弹窗（编辑保留为独立按钮，它是最高频动作）
  { key: 'actions', label: '操作', width: 150, fixed: 'right', align: 'right' },
]

const list = ref<Announcement[]>([])
const loading = ref(false)
const loadError = ref('')
const activeOnly = ref(false)
const keyword = ref('')

/** 前端按启用状态 / 关键字过滤（后端已支持 active_only，这里用本地切换避免重复请求） */
const visibleList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return list.value.filter((a) => {
    if (activeOnly.value && a.is_active === false) return false
    return !kw || `${a.title} ${a.content}`.toLowerCase().includes(kw)
  })
})
const hasFilter = computed(() => activeOnly.value || Boolean(keyword.value.trim()))

const TYPE_LABELS: Record<string, string> = { system: '系统', maintenance: '维护', activity: '活动' }
function typeLabel(t: string): string {
  return TYPE_LABELS[t] || t
}

const dialogVisible = ref(false)
const editing = ref<Announcement | null>(null)
const form = ref({ title: '', content: '', type: 'system', is_pinned: false })
/** 提交 / 行内动作进行中（按钮 loading，防重复点击） */
const submitBusy = ref(false)
const rowBusyId = ref<number | null>(null)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    list.value = await fetchAnnouncements()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreate() {
  editing.value = null
  form.value = { title: '', content: '', type: 'system', is_pinned: false }
  dialogVisible.value = true
}

function openEdit(a: Announcement) {
  editing.value = a
  form.value = { title: a.title, content: a.content, type: a.type, is_pinned: a.is_pinned }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.title.trim() || !form.value.content.trim()) {
    ElMessage.warning('标题和内容不能为空')
    return
  }
  submitBusy.value = true
  try {
    if (editing.value) {
      await updateAnnouncement(editing.value.id, form.value)
      ElMessage.success('公告已更新并推送')
    } else {
      await createAnnouncement(form.value)
      ElMessage.success('公告已创建并推送给所有用户')
    }
    dialogVisible.value = false
    load()
  } finally {
    submitBusy.value = false
  }
}

// ==================== 公告管理弹窗（v2.29.0） ====================
// 表格里正文被截成两行、置顶/停用/删除三个按钮挤在行尾；现在行里只留「编辑 / 管理」，
// 弹窗里能读全文，置顶 / 停用 / 删除也各有说明（停用 = 用户端不再展示，删除不可恢复）。
const manage = ref({ visible: false, row: null as Announcement | null })

function openManage(a: Announcement) {
  manage.value = { visible: true, row: a }
}

/** 动作后刷新列表，并把弹窗里的公告换成最新快照 */
async function afterAction(a: Announcement) {
  await load()
  const fresh = list.value.find((x) => x.id === a.id)
  if (fresh) {
    manage.value.row = fresh
  } else {
    manage.value.visible = false
  }
}

async function remove(a: Announcement) {
  try {
    await ElMessageBox.confirm(`确定删除公告「${a.title}」吗？删除后不可恢复。`, '确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  rowBusyId.value = a.id
  try {
    await deleteAnnouncement(a.id)
    ElMessage.success('已删除')
    await afterAction(a)
  } finally {
    rowBusyId.value = null
  }
}

async function togglePin(a: Announcement) {
  rowBusyId.value = a.id
  try {
    await updateAnnouncement(a.id, { is_pinned: !a.is_pinned })
    ElMessage.success(a.is_pinned ? '已取消置顶' : '已置顶（用户端消息中心排在最前）')
    await afterAction(a)
  } finally {
    rowBusyId.value = null
  }
}

async function toggleActive(a: Announcement) {
  const next = a.is_active === false
  rowBusyId.value = a.id
  try {
    await updateAnnouncement(a.id, { is_active: next })
    ElMessage.success(next ? '公告已启用' : '公告已停用（用户端不再展示）')
    await afterAction(a)
  } finally {
    rowBusyId.value = null
  }
}

function fmtDate(s: string): string {
  return s.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <div class="admin-page">
    <PageHeader eyebrow="内容与服务" title="公告管理" description="发布或修改公告会实时推送给所有在线用户；置顶、停用与删除在「管理」里。">
      <template #actions>
        <el-button :loading="loading" :icon="RefreshCw" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">发布公告</el-button>
      </template>
    </PageHeader>

    <SectionCard
      title="全部公告"
      :icon="Megaphone"
      :meta="hasFilter ? `筛出 ${visibleList.length} / ${list.length}` : loading ? '' : `${list.length} 条`"
      flush
    >
      <div class="list-bar">
        <div class="toolbar">
          <el-input v-model="keyword" placeholder="搜索标题 / 正文" clearable>
            <template #prefix><Search :size="14" /></template>
          </el-input>
          <el-radio-group v-model="activeOnly" aria-label="按状态筛选">
            <el-radio-button :value="false">全部</el-radio-button>
            <el-radio-button :value="true">展示中</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <DataTable
        :rows="visibleList"
        :columns="columns"
        :loading="loading"
        :error="loadError"
        :empty="hasFilter ? '没有匹配的公告' : '还没有公告'"
        :empty-description="hasFilter ? '换个关键字，或切回「全部」。' : '点右上角「发布公告」，所有在线用户会立即收到。'"
        @retry="load"
      >
        <template #cell-title="{ row }">
          <div class="ann-title">
            <span v-if="row.is_pinned" class="au-badge au-badge-amber">置顶</span>
            <span class="ann-name">{{ row.title }}</span>
          </div>
          <div class="ann-content">{{ row.content }}</div>
        </template>

        <template #cell-type="{ row }">
          <span class="au-badge au-badge-muted">{{ typeLabel(row.type) }}</span>
        </template>

        <template #cell-is_active="{ row }">
          <span class="au-badge" :class="row.is_active === false ? 'au-badge-muted' : 'au-badge-green'">
            {{ row.is_active === false ? '已停用' : '展示中' }}
          </span>
        </template>

        <template #cell-created_at="{ row }"><span class="mono">{{ fmtDate(row.created_at) }}</span></template>

        <template #cell-actions="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <!-- 置顶 / 停用 / 删除 都在弹窗里（原来这行有 4 个按钮，最宽松的那个还是不可恢复的删除） -->
          <el-button size="small" @click="openManage(row)">管理</el-button>
        </template>
      </DataTable>
    </SectionCard>

    <!-- 公告管理（弹窗）：全文 + 置顶 / 停用 / 删除，每个动作都写清楚影响 -->
    <el-dialog v-model="manage.visible" title="管理公告" width="560px">
      <div v-if="manage.row" class="manage-body">
        <div class="kv-list">
          <div class="kv-row"><span class="kv-key">标题</span><span class="kv-value">{{ manage.row.title }}</span></div>
          <div class="kv-row"><span class="kv-key">类型</span>
            <span class="kv-value">{{ typeLabel(manage.row.type) }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">状态</span>
            <span class="kv-value">
              <span class="au-badge" :class="manage.row.is_active === false ? 'au-badge-muted' : 'au-badge-green'">
                {{ manage.row.is_active === false ? '已停用' : '展示中' }}
              </span>
              <span v-if="manage.row.is_pinned" class="au-badge au-badge-amber mg-gap">置顶</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">发布时间</span><span class="kv-value">{{ fmtDate(manage.row.created_at) }}</span></div>
        </div>

        <div class="mg-content">
          <div class="mg-content-label">公告正文</div>
          <div class="mg-content-body">{{ manage.row.content }}</div>
        </div>

        <ul class="mg-hints">
          <li>置顶：用户端消息中心的排序与预览里排在最前，不改变发布状态。</li>
          <li>停用：立即从用户端消失（历史推送不回滚），随时可以再启用。</li>
          <li>删除：发布记录一并移除，不可恢复；只想下架用「停用」。</li>
        </ul>
      </div>

      <template #footer>
        <div class="mg-footer">
          <el-button v-if="manage.row" type="danger" :loading="rowBusyId === manage.row.id" @click="remove(manage.row)">删除</el-button>
          <div class="mg-footer-right">
            <el-button @click="manage.visible = false">关闭</el-button>
            <el-button v-if="manage.row" :loading="rowBusyId === manage.row.id" @click="togglePin(manage.row)">
              {{ manage.row.is_pinned ? '取消置顶' : '置顶' }}
            </el-button>
            <el-button v-if="manage.row" :type="manage.row.is_active === false ? 'success' : 'warning'" :loading="rowBusyId === manage.row.id" @click="toggleActive(manage.row)">
              {{ manage.row.is_active === false ? '启用' : '停用' }}
            </el-button>
            <el-button v-if="manage.row" type="primary" @click="manage.visible = false; openEdit(manage.row)">
              编辑内容
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑公告' : '发布公告'" width="480px">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="form.title" placeholder="公告标题" /></el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="6" placeholder="公告内容（支持换行）" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" class="w-type">
            <el-option label="系统" value="system" />
            <el-option label="维护" value="maintenance" />
            <el-option label="活动" value="activity" />
          </el-select>
        </el-form-item>
        <el-form-item label="置顶"><el-switch v-model="form.is_pinned" active-text="在用户端消息中心排在最前" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitBusy" @click="submit">{{ editing ? '保存' : '发布' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.list-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px 12px;
  flex-wrap: wrap;
  padding: 4px 20px 12px;
}

.ann-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ann-name { font-weight: 600; color: var(--au-text); }

.ann-content {
  font-size: 12px;
  color: var(--au-text-3);
  margin-top: 4px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 管理弹窗：详情用全局 .kv-list，正文单独一块便于阅读 */
.manage-body { display: flex; flex-direction: column; gap: 12px; }
.manage-body .kv-row .kv-value { text-align: left; }
.mg-gap { margin-left: 6px; }
.mg-content-label { font-size: 12px; color: var(--au-text-3); margin-bottom: 6px; }
.mg-content-body {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  color: var(--au-text);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  padding: 10px 12px;
  max-height: 220px;
  overflow-y: auto;
}
.mg-hints {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--au-text-3);
  line-height: 1.8;
}
.mg-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.mg-footer-right { display: flex; gap: 8px; flex-wrap: wrap; }
.w-type { width: 160px; }

@media (max-width: 768px) {
  .list-bar { padding: 4px 16px 12px; }
}

@media (max-width: 640px) {
  .mg-footer { flex-direction: column-reverse; align-items: stretch; }
  .mg-footer-right :deep(.el-button) { flex: 1 1 40%; margin-left: 0; }
}
</style>
