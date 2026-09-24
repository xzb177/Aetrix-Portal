<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Activity, Database, Film, HardDrive, RefreshCw, Radio, Users } from 'lucide-vue-next'
import { fetchEmbyOverview, fetchLibraries, fetchMounts, fetchPanelHealth, fetchSessions } from '@/api/admin'
import type { EmbyLibrary, EmbySessionRow, StorageMount } from '@/types'
import type { PanelHealth } from '@/api/admin'

const health = ref<PanelHealth | null>(null)
const libraries = ref<EmbyLibrary[]>([])
const sessions = ref<EmbySessionRow[]>([])
const mounts = ref<StorageMount[]>([])
const overview = ref<{ total_items: number; total_libraries: number; active_sessions: number; total_users: number } | null>(null)
const loading = ref(false)
const lastChecked = ref('')

const checks = computed(() => [
  { label: 'EM 面板', detail: health.value?.status === 'healthy' ? 'API 正常响应' : '无法确认状态', ok: health.value?.status === 'healthy', icon: Activity },
  { label: '共享数据库', detail: health.value?.database || '未返回数据库信息', ok: !!health.value, icon: Database },
  { label: '媒体网关', detail: overview.value ? `${overview.value.total_items} 个条目可用` : '等待媒体数据', ok: !!overview.value, icon: Film },
  { label: '存储来源', detail: `${mounts.value.filter((m) => m.is_enabled).length} 个挂载已启用`, ok: mounts.value.length === 0 || mounts.value.every((m) => m.last_check_ok !== false), icon: HardDrive },
])

async function load() {
  loading.value = true
  try {
    const [h, o, l, s, m] = await Promise.all([
      fetchPanelHealth(),
      fetchEmbyOverview().catch(() => null),
      fetchLibraries().catch(() => ({ libraries: [] as EmbyLibrary[] })),
      fetchSessions().catch(() => ({ sessions: [] as EmbySessionRow[] })),
      fetchMounts().catch(() => ({ mounts: [], mount_types: [] })),
    ])
    health.value = h
    overview.value = o
    libraries.value = l.libraries
    sessions.value = s.sessions
    mounts.value = m.mounts
    lastChecked.value = new Date().toLocaleTimeString()
  } catch {
    ElMessage.error('健康检查失败，请确认 EM 服务仍在运行')
  } finally {
    loading.value = false
  }
}

function fmtDate(value: string | null): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">服务健康</h1>
        <p class="admin-page-subtitle">从媒体服务运维角度查看 EM、媒体库、在线会话与存储来源，而不是只看业务统计。</p>
      </div>
      <el-button :loading="loading" type="primary" @click="load">
        <RefreshCw :size="14" style="margin-right: 5px" />重新检查
      </el-button>
    </div>

    <div class="health-grid">
      <div v-for="item in checks" :key="item.label" class="admin-card health-card">
        <div class="health-icon" :class="{ bad: item.ok === false }"><component :is="item.icon" :size="18" /></div>
        <div class="health-copy">
          <strong>{{ item.label }}</strong>
          <span>{{ item.detail }}</span>
        </div>
        <span class="health-dot" :class="{ bad: item.ok === false, idle: item.ok === undefined }" />
      </div>
    </div>

    <section class="admin-card">
      <div class="card-header"><h2><Radio :size="15" />运行态</h2><span class="muted">最近检查 {{ lastChecked || '—' }}</span></div>
      <div class="runtime-grid">
        <div><span>服务名称</span><strong>{{ health?.emby_server || 'Aetrix Media Server' }}</strong></div>
        <div><span>在线用户</span><strong>{{ health?.online_users ?? 0 }}</strong></div>
        <div><span>在线会话</span><strong>{{ overview?.active_sessions ?? sessions.length }}</strong></div>
        <div><span>媒体条目</span><strong>{{ overview?.total_items ?? 0 }}</strong></div>
        <div><span>媒体库</span><strong>{{ overview?.total_libraries ?? libraries.length }}</strong></div>
        <div><span>管理员看到的挂载</span><strong>{{ mounts.length }}</strong></div>
      </div>
    </section>

    <section class="ops-grid">
      <div class="admin-card">
        <div class="card-header"><h2><Film :size="15" />媒体库状态</h2></div>
        <div v-if="libraries.length" class="status-list">
          <div v-for="library in libraries" :key="library.id" class="status-row">
            <span>{{ library.name }}</span><span :class="library.is_scanning ? 'warn-text' : library.is_enabled ? 'ok-text' : 'muted'">{{ library.is_scanning ? '扫描中' : library.is_enabled ? `${library.item_count} 条目` : '已停用' }}</span>
          </div>
        </div>
        <div v-else class="empty-hint">暂无媒体库</div>
      </div>
      <div class="admin-card">
        <div class="card-header"><h2><Users :size="15" />实时会话</h2></div>
        <div v-if="sessions.length" class="status-list">
          <div v-for="session in sessions.slice(0, 8)" :key="session.session_key" class="status-row"><span>{{ session.username }} · {{ session.item }}</span><span class="muted">{{ fmtDate(session.started_at) }}</span></div>
        </div>
        <div v-else class="empty-hint">当前没有播放会话</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.health-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.health-card { display: flex; align-items: center; gap: 11px; min-width: 0; padding: 15px; }
.health-icon { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 36px; border-radius: 10px; color: var(--success); background: var(--success-bg); }
.health-icon.bad { color: var(--danger); background: var(--danger-bg); }
.health-copy { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.health-copy strong { font-size: 13px; color: var(--text-primary); }
.health-copy span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; color: var(--text-muted); }
.health-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: var(--success); box-shadow: 0 0 0 4px var(--success-bg); }
.health-dot.bad { background: var(--danger); box-shadow: 0 0 0 4px var(--danger-bg); }
.health-dot.idle { background: var(--text-faint); box-shadow: 0 0 0 4px var(--bg-hover); }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; }
.card-header h2 { display: flex; align-items: center; gap: 7px; margin: 0; font-size: 15px; }
.runtime-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.runtime-grid div { display: flex; flex-direction: column; gap: 5px; padding: 12px; border-radius: var(--radius-md); background: var(--bg-inset); }
.runtime-grid span { font-size: 11.5px; color: var(--text-muted); }
.runtime-grid strong { font-size: 18px; color: var(--text-primary); }
.ops-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.status-list { display: flex; flex-direction: column; }
.status-row { display: flex; justify-content: space-between; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); font-size: 13px; }
.status-row:last-child { border-bottom: 0; }
.status-row > span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted { color: var(--text-muted); font-size: 12px; }
.ok-text { color: var(--success); }
.warn-text { color: var(--warning); }
@media (max-width: 900px) { .health-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .runtime-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px) { .health-grid, .ops-grid { grid-template-columns: 1fr; } .runtime-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .health-card { padding: 13px; } }
</style>
