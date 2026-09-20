<script setup lang="ts">
/**
 * 媒体库管理：库列表/创建/扫描/删除 + 刮削策略 + 平台虚拟媒体库 + 图片修复队列
 * + 在线会话监控/强制下线 + 停止全部转码
 *
 * v2.6.11：会话表改用 DataTable（手机卡片）；媒体库卡片的「挂载 / 刮削策略 / 115 账号」
 * 在窄屏改为「标签在上、控件在下」，不再把中文标签挤成竖排两行；页面里的硬编码灰度
 * 全部换成主题令牌。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, FolderPlus, RefreshCw, ScanSearch, Square, Wand2 } from 'lucide-vue-next'
import {
  createLibrary,
  deleteLibrary,
  fetchLibraries,
  fetchMounts,
  fetchPan115Accounts,
  fetchRepairQueue,
  fetchSessions,
  generateVirtualLibraries,
  runRepairQueue,
  scanLibrary,
  stopAllTranscodes,
  stopSession,
  updateLibrary,
} from '@/api/admin'
import type { EmbyLibrary, EmbySessionRow, Pan115Account, StorageMount } from '@/types'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const libraries = ref<EmbyLibrary[]>([])
const sessions = ref<EmbySessionRow[]>([])
const panAccounts = ref<Pan115Account[]>([])
const mounts = ref<StorageMount[]>([])
const loading = ref(false)
const repairCount = ref(0)
const virtualLoading = ref(false)

const sessionColumns: DataColumn[] = [
  { key: 'username', label: '用户', width: 130, mobile: 'title' },
  { key: 'item', label: '内容', minWidth: 190 },
  { key: 'device', label: '设备', minWidth: 150, mobile: 'hide' },
  { key: 'progress', label: '进度', width: 120 },
  { key: 'remote_addr', label: 'IP', width: 130, mobile: 'hide' },
  { key: 'started_at', label: '开始时间', width: 150 },
  { key: 'actions', label: '操作', width: 110, fixed: 'right', align: 'right' },
]

const createVisible = ref(false)
const form = ref({
  name: '',
  collection_type: 'movies',
  paths: '',
  mount_ids: [] as number[],
  scrape_policy: 'missing_only',
})

/** 刮削策略：只补缺 / 到期重刮 / 每次全量 */
const POLICIES = [
  { value: 'missing_only', label: '仅缺失时刮削' },
  { value: '3m', label: '3 个月重刮' },
  { value: '6m', label: '半年重刮' },
  { value: '1y', label: '一年重刮' },
  { value: 'all', label: '全部重刮' },
]

async function load() {
  loading.value = true
  try {
    const [l, s, r, a, m] = await Promise.all([
      fetchLibraries(),
      fetchSessions(),
      fetchRepairQueue().catch(() => ({ total: 0, items: [] })),
      fetchPan115Accounts().catch(() => ({ accounts: [], env_cookie_configured: false })),
      fetchMounts().catch(() => ({ mounts: [], mount_types: [] })),
    ])
    // mount_ids 兼容旧响应（老后端没有这个字段）
    libraries.value = l.libraries.map((lib) => ({ ...lib, mount_ids: lib.mount_ids || [] }))
    sessions.value = s.sessions
    repairCount.value = r.total
    panAccounts.value = a.accounts
    mounts.value = m.mounts
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function savePolicy(l: EmbyLibrary) {
  await updateLibrary(l.id, { scrape_policy: l.scrape_policy })
  ElMessage.success(`「${l.name}」刮削策略已保存（下次扫描生效）`)
}

async function saveAccount115(l: EmbyLibrary) {
  // 传 null 表示解绑（回退默认账号）；undefined 会被 axios 丢掉，等于不改
  await updateLibrary(l.id, { account_115_id: l.account_115_id ?? null })
  ElMessage.success(`「${l.name}」115 账号绑定已更新`)
}

function mountNames(ids: number[]): string {
  return (ids || [])
    .map((id) => mounts.value.find((m) => m.id === id)?.name || `#${id}`)
    .join(' | ')
}

/** 绑定 / 解绑存储挂载（扫描时与「路径」一起遍历） */
async function saveMounts(l: EmbyLibrary) {
  await updateLibrary(l.id, { mount_ids: l.mount_ids ?? [] })
  ElMessage.success(`「${l.name}」挂载绑定已更新（重新扫描后生效）`)
}

async function generateVirtual() {
  virtualLoading.value = true
  try {
    const res = await generateVirtualLibraries({ enabled: true })
    ElMessage.success(`虚拟媒体库：新建 ${res.created.length}、更新 ${res.updated.length}`)
    if (res.created.length === 0 && res.updated.length === 0) {
      ElMessage.info('当前库里还没有识别到发行平台标签（NF / DSNP / ATVP …）')
    }
    load()
  } finally {
    virtualLoading.value = false
  }
}

async function repairNow() {
  await runRepairQueue()
  ElMessage.success('已开始修复缺图条目')
  setTimeout(load, 2000)
}

async function submitCreate() {
  const paths = form.value.paths.split(/[,，\n]/).map((p) => p.trim()).filter(Boolean)
  if (!form.value.name.trim() || (!paths.length && !form.value.mount_ids.length)) {
    ElMessage.warning('请填写库名称，并至少配置一个路径或一个存储挂载')
    return
  }
  await createLibrary({
    name: form.value.name,
    collection_type: form.value.collection_type,
    paths,
    mount_ids: form.value.mount_ids,
    scrape_policy: form.value.scrape_policy,
  })
  ElMessage.success('媒体库已创建')
  createVisible.value = false
  form.value = {
    name: '', collection_type: 'movies', paths: '', mount_ids: [], scrape_policy: 'missing_only',
  }
  load()
}

async function scan(l: EmbyLibrary) {
  await scanLibrary(l.id)
  ElMessage.success(`「${l.name}」扫描已启动`)
  setTimeout(load, 1500)
}

async function removeLib(l: EmbyLibrary) {
  await ElMessageBox.confirm(
    `删除媒体库「${l.name}」将同时移除其索引条目（不删除磁盘文件），确定吗？`,
    '确认删除',
    { type: 'warning' }
  )
  await deleteLibrary(l.id)
  ElMessage.success('已删除')
  load()
}

async function kick(s: EmbySessionRow) {
  await ElMessageBox.confirm(`强制下线「${s.username}」正在播放的会话？`, '确认', { type: 'warning' })
  await stopSession(s.session_key)
  ElMessage.success('已停止该会话')
  load()
}

async function stopAll() {
  const res = await stopAllTranscodes()
  ElMessage.success(`已停止 ${res.stopped} 路转码`)
}

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

function progress(pos: number, dur: number): string {
  if (!dur) return '0%'
  return Math.min(100, Math.round((pos / dur) * 100)) + '%'
}

function typeLabel(t: string): string {
  return { movies: '电影', tvshows: '剧集', music: '音乐', mixed: '混合' }[t] || t
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">媒体库管理</h1>
        <p class="admin-page-subtitle">自建 Emby：媒体库、扫描与在线会话</p>
      </div>
      <div class="admin-page-actions">
        <el-button v-if="repairCount > 0" @click="repairNow">
          修复缺图（{{ repairCount }}）
        </el-button>
        <el-button :loading="virtualLoading" @click="generateVirtual">
          <Wand2 :size="14" style="margin-right: 4px" />生成平台虚拟库
        </el-button>
        <el-button @click="stopAll">
          <Square :size="13" style="margin-right: 4px" />停止全部转码
        </el-button>
        <el-button type="primary" @click="createVisible = true">
          <FolderPlus :size="15" style="margin-right: 4px" />新建媒体库
        </el-button>
        <el-button :loading="loading" aria-label="刷新" @click="load">
          <RefreshCw :size="15" />
        </el-button>
      </div>
    </div>

    <!-- 媒体库列表 -->
    <div class="lib-grid">
      <div v-for="l in libraries" :key="l.id" class="admin-card lib-card">
        <div class="lib-head">
          <span class="lib-name">{{ l.name }}</span>
          <span v-if="l.is_virtual" class="mini-badge pin">虚拟库</span>
          <span class="mini-badge" :class="l.is_enabled ? 'ok' : 'off'">
            {{ l.is_enabled ? '启用' : '停用' }}
          </span>
          <span v-if="l.is_scanning" class="mini-badge scanning">扫描中…</span>
        </div>

        <div class="lib-meta">{{ typeLabel(l.collection_type) }} · {{ l.item_count }} 个条目</div>

        <div class="lib-paths">
          <template v-if="l.is_virtual">
            按发行平台「{{ l.platform || '—' }}」聚合，条目仍归属原媒体库
          </template>
          <template v-else>
            {{ [...l.paths, mountNames(l.mount_ids)].filter(Boolean).join(' | ') || '未配置来源' }}
          </template>
        </div>

        <div v-if="!l.is_virtual" class="lib-policy">
          <span class="policy-label">存储挂载</span>
          <el-select
            v-model="l.mount_ids"
            size="small"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="未绑定"
            @change="saveMounts(l)"
          >
            <el-option v-for="m in mounts" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </div>

        <div v-if="!l.is_virtual" class="lib-policy">
          <span class="policy-label">刮削策略</span>
          <el-select v-model="l.scrape_policy" size="small" @change="savePolicy(l)">
            <el-option v-for="p in POLICIES" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </div>

        <div v-if="!l.is_virtual" class="lib-policy">
          <span class="policy-label">115 账号</span>
          <el-select
            v-model="l.account_115_id"
            size="small"
            clearable
            placeholder="默认账号"
            @change="saveAccount115(l)"
          >
            <el-option v-for="a in panAccounts" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
        </div>

        <div class="lib-foot">
          <span class="lib-time">上次扫描 {{ fmtDate(l.last_scan_at) }}</span>
          <div class="lib-actions">
            <el-button size="small" type="primary" plain @click="scan(l)">
              <ScanSearch :size="13" style="margin-right: 3px" />扫描
            </el-button>
            <el-button size="small" type="danger" plain @click="removeLib(l)">
              <Delete :size="13" style="margin-right: 3px" />删除
            </el-button>
          </div>
        </div>
      </div>

      <div v-if="libraries.length === 0 && !loading" class="admin-card empty-card">
        暂无媒体库，点击右上角「新建媒体库」开始
      </div>
    </div>

    <!-- 在线会话 -->
    <div class="admin-card">
      <div class="card-header">
        <h2>在线会话（{{ sessions.length }}）</h2>
      </div>
      <DataTable
        :rows="sessions"
        :columns="sessionColumns"
        :loading="loading"
        empty="当前没有正在播放的会话"
        row-key="session_key"
      >
        <template #cell-username="{ row }">
          <span class="user-name">{{ row.username }}</span>
        </template>

        <template #cell-item="{ row }">
          {{ row.item }}
          <span class="s-method">{{ row.play_method === 'Transcode' ? '转码' : '直连' }}</span>
        </template>

        <template #cell-device="{ row }">
          {{ [row.client, row.device].filter(Boolean).join(' · ') || '—' }}
        </template>

        <template #cell-progress="{ row }">
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: progress(row.position_ticks, row.duration_ticks) }" />
          </div>
          <span class="progress-num">
            {{ progress(row.position_ticks, row.duration_ticks) }}{{ row.is_paused ? ' · 已暂停' : '' }}
          </span>
        </template>

        <template #cell-remote_addr="{ row }">
          <span class="mono">{{ row.remote_addr || '—' }}</span>
        </template>

        <template #cell-started_at="{ row }">{{ fmtDate(row.started_at) }}</template>

        <template #cell-actions="{ row }">
          <el-button size="small" type="danger" plain @click="kick(row)">下线</el-button>
        </template>
      </DataTable>
    </div>

    <!-- 新建弹窗 -->
    <el-dialog v-model="createVisible" title="新建媒体库" width="480px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：电影库 / 剧集库" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.collection_type" style="width: 100%">
            <el-option label="电影" value="movies" />
            <el-option label="剧集" value="tvshows" />
            <el-option label="音乐" value="music" />
            <el-option label="混合" value="mixed" />
          </el-select>
        </el-form-item>
        <el-form-item label="刮削策略">
          <el-select v-model="form.scrape_policy" style="width: 100%">
            <el-option v-for="p in POLICIES" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="路径">
          <el-input
            v-model="form.paths"
            type="textarea"
            :rows="3"
            placeholder="服务器上的媒体目录，多个用逗号或换行分隔&#10;如：/media/movies"
          />
          <div class="form-hint">本机目录。也可以用下面的「存储挂载」接入 115 / WebDAV / AList 等来源。</div>
        </el-form-item>
        <el-form-item label="存储挂载">
          <el-select
            v-model="form.mount_ids"
            multiple
            collapse-tags
            placeholder="不绑定（只用上面的路径）"
            style="width: 100%"
          >
            <el-option v-for="m in mounts" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
          <div class="form-hint">路径与挂载可以同时用；挂载在「存储挂载」页里创建与测试。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-page { gap: 16px; }

.lib-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}

.lib-card { display: flex; flex-direction: column; gap: 8px; }
.lib-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.lib-name { font-weight: var(--font-weight-bold); font-size: var(--font-size-lg); color: var(--text-primary); }
.lib-meta { font-size: var(--font-size-xs); color: var(--text-tertiary); }

.lib-paths {
  font-size: var(--font-size-xs);
  font-family: var(--font-mono);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lib-policy { display: flex; align-items: center; gap: 10px; }
.policy-label { font-size: var(--font-size-xs); color: var(--text-tertiary); width: 62px; flex-shrink: 0; }
.lib-policy :deep(.el-select) { flex: 1; min-width: 0; }

.lib-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.lib-time { font-size: var(--font-size-xs); color: var(--text-muted); }
.lib-actions { display: flex; gap: 8px; }
.lib-actions :deep(.el-button) { margin-left: 0; }

.empty-card { text-align: center; color: var(--text-muted); padding: 40px 16px; font-size: var(--font-size-sm); }

.card-header h2 {
  margin: 0;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.user-name { font-weight: 600; color: var(--text-primary); }

.s-method {
  font-size: 11px;
  background: rgba(255, 255, 255, 0.07);
  border-radius: var(--radius-full);
  padding: 2px 7px;
  margin-left: 7px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.progress-track {
  height: 5px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.09);
  overflow: hidden;
  max-width: 110px;
}

.progress-fill { height: 100%; background: var(--gradient-brand); border-radius: 3px; }
.progress-num { font-size: var(--font-size-xs); color: var(--text-muted); }

/* 手机：卡片内标签与控件竖排，路径允许换行 */
@media (max-width: 640px) {
  .lib-grid { grid-template-columns: minmax(0, 1fr); }
  .lib-policy { flex-direction: column; align-items: stretch; gap: 6px; }
  .policy-label { width: auto; }
  .lib-paths { white-space: normal; word-break: break-all; }
  .lib-actions { width: 100%; }
  .lib-actions :deep(.el-button) { flex: 1; }
  .admin-page-actions :deep(.el-button.is-primary) { flex: 1 1 100%; }
}
</style>
