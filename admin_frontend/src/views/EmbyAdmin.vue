<script setup lang="ts">
/** 媒体库管理：库列表/创建/扫描/删除 + 在线会话监控/强制下线 + 停止全部转码 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, FolderPlus, RefreshCw, ScanSearch, Square } from 'lucide-vue-next'
import {
  createLibrary,
  deleteLibrary,
  fetchLibraries,
  fetchSessions,
  scanLibrary,
  stopAllTranscodes,
  stopSession,
} from '@/api/admin'
import type { EmbyLibrary, EmbySessionRow } from '@/types'

const libraries = ref<EmbyLibrary[]>([])
const sessions = ref<EmbySessionRow[]>([])
const loading = ref(false)

const createVisible = ref(false)
const form = ref({ name: '', collection_type: 'movies', paths: '' })

async function load() {
  loading.value = true
  try {
    const [l, s] = await Promise.all([fetchLibraries(), fetchSessions()])
    libraries.value = l.libraries
    sessions.value = s.sessions
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function submitCreate() {
  if (!form.value.name.trim() || !form.value.paths.trim()) {
    ElMessage.warning('请填写库名称和路径')
    return
  }
  const paths = form.value.paths.split(/[,，\n]/).map((p) => p.trim()).filter(Boolean)
  await createLibrary({ name: form.value.name, collection_type: form.value.collection_type, paths })
  ElMessage.success('媒体库已创建')
  createVisible.value = false
  form.value = { name: '', collection_type: 'movies', paths: '' }
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
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">媒体库管理</h1>
        <p class="admin-page-subtitle">自建 Emby：媒体库、扫描与会话监控</p>
      </div>
      <div class="toolbar">
        <el-button @click="stopAll"><Square :size="13" style="margin-right: 4px" />停止全部转码</el-button>
        <el-button type="primary" @click="createVisible = true"><FolderPlus :size="14" style="margin-right: 4px" />新建媒体库</el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <!-- 媒体库列表 -->
    <div class="lib-grid">
      <div v-for="l in libraries" :key="l.id" class="admin-card lib-card">
        <div class="lib-head">
          <span class="lib-name">{{ l.name }}</span>
          <span class="mini-badge" :class="l.is_enabled ? 'ok' : 'off'">{{ l.is_enabled ? '启用' : '停用' }}</span>
          <span v-if="l.is_scanning" class="mini-badge scanning">扫描中…</span>
        </div>
        <div class="lib-meta">
          {{ { movies: '电影', tvshows: '剧集', music: '音乐', mixed: '混合' }[l.collection_type] || l.collection_type }}
          · {{ l.item_count }} 个条目
        </div>
        <div class="lib-paths">{{ l.paths.join(' | ') || '未配置路径' }}</div>
        <div class="lib-foot">
          <span class="lib-time">上次扫描 {{ fmtDate(l.last_scan_at) }}</span>
          <div class="lib-actions">
            <el-button size="small" text type="primary" @click="scan(l)">
              <ScanSearch :size="13" style="margin-right: 2px" />扫描
            </el-button>
            <el-button size="small" text type="danger" @click="removeLib(l)"><Delete :size="13" /></el-button>
          </div>
        </div>
      </div>
      <div v-if="libraries.length === 0 && !loading" class="admin-card empty-card">
        暂无媒体库，点击右上角「新建媒体库」开始
      </div>
    </div>

    <!-- 在线会话 -->
    <div class="admin-card" style="margin-top: 16px">
      <div class="sessions-head">
        <h2>在线会话（{{ sessions.length }}）</h2>
      </div>
      <el-table :data="sessions" style="width: 100%" :header-cell-style="{ background: 'transparent', color: '#a3a3a3' }">
        <el-table-column label="用户" prop="username" width="120" />
        <el-table-column label="内容" min-width="180">
          <template #default="{ row }">
            {{ row.item }}
            <span class="s-method">{{ row.play_method === 'Transcode' ? '转码' : '直连' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="设备" min-width="140">
          <template #default="{ row }">{{ [row.client, row.device].filter(Boolean).join(' · ') || '—' }}</template>
        </el-table-column>
        <el-table-column label="进度" width="110">
          <template #default="{ row }">
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: progress(row.position_ticks, row.duration_ticks) }" />
            </div>
            <span class="progress-num">{{ progress(row.position_ticks, row.duration_ticks) }}{{ row.is_paused ? ' · 已暂停' : '' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="IP" prop="remote_addr" width="130" />
        <el-table-column label="开始时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="danger" @click="kick(row)">下线</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建弹窗 -->
    <el-dialog v-model="createVisible" title="新建媒体库" width="440px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="如：电影库 / 剧集库" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.collection_type" style="width: 160px">
            <el-option label="电影" value="movies" />
            <el-option label="剧集" value="tvshows" />
            <el-option label="音乐" value="music" />
            <el-option label="混合" value="mixed" />
          </el-select>
        </el-form-item>
        <el-form-item label="路径">
          <el-input v-model="form.paths" type="textarea" :rows="3" placeholder="服务器上的媒体目录，多个用逗号或换行分隔&#10;如：/media/movies" />
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
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; }

.lib-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.lib-card { display: flex; flex-direction: column; gap: 6px; }
.lib-head { display: flex; align-items: center; gap: 8px; }
.lib-name { font-weight: 700; font-size: 15px; }
.lib-meta { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }
.lib-paths {
  font-size: 11px;
  font-family: ui-monospace, monospace;
  color: var(--color-text-muted, #737373);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lib-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
.lib-time { font-size: 11px; color: var(--color-text-muted, #737373); }
.lib-actions { display: flex; }
.empty-card { text-align: center; color: var(--color-text-muted, #737373); padding: 40px 0; }

.sessions-head h2 { font-size: 15px; margin: 0 0 12px; }
.s-method { font-size: 10px; background: rgba(255, 255, 255, 0.08); border-radius: 999px; padding: 1px 6px; margin-left: 6px; color: var(--color-text-secondary, #a3a3a3); }

.progress-track { height: 4px; border-radius: 2px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
.progress-fill { height: 100%; background: #10b981; border-radius: 2px; }
.progress-num { font-size: 11px; color: var(--color-text-muted, #737373); }

.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; font-weight: 600; }
.mini-badge.ok { background: rgba(16, 185, 129, 0.15); color: #10b981; }
.mini-badge.off { background: rgba(255, 255, 255, 0.08); color: var(--color-text-muted, #737373); }
.mini-badge.scanning { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
</style>
