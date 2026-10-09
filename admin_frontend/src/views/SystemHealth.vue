<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Activity, AlertTriangle, Database, Film, HardDrive, RefreshCw, Radio, Users } from 'lucide-vue-next'
import { EmptyState, PageHeader, SectionCard, StatTile } from '@/components/ui'
import { fetchEmbyOverview, fetchMounts, fetchPanelHealth, fetchSessions } from '@/api/admin'
import { fetchBackupConfig, saveBackupConfig, runBackupNow } from '@/api/admin'
import type { EmbySessionRow, StorageMount } from '@/types'
import type { PanelHealth } from '@/api/admin'
import type { BackupConfig } from '@/api/admin'

const health = ref<PanelHealth | null>(null)
const sessions = ref<EmbySessionRow[]>([])
const mounts = ref<StorageMount[]>([])
const overview = ref<{ total_items: number; total_libraries: number; active_sessions: number; total_users: number } | null>(null)
const loading = ref(false)
const lastChecked = ref('')
/** 面板健康接口失败（其余子查询各自兜底，不算失败） */
const loadError = ref('')

const backup = ref<BackupConfig | null>(null)
const backupSaving = ref(false)
const backupRunning = ref(false)

function fmtSize(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const panelOk = computed(() => health.value?.status === 'healthy' || health.value?.status === 'degraded')
const panelDetail = computed(() => {
  if (health.value?.status === 'healthy') return 'API 正常响应'
  if (health.value?.status === 'degraded') {
    const issues = health.value?.health_issues?.map((i) => i.message).join('；')
    return issues ? `有警告：${issues}` : '有警告，API 正常响应'
  }
  return '无法确认状态'
})

const checks = computed(() => [
  { label: 'EM 面板', detail: panelDetail.value, ok: panelOk.value, icon: Activity },
  { label: '共享数据库', detail: health.value?.database || '未返回数据库信息', ok: !!health.value, icon: Database },
  { label: '媒体网关', detail: overview.value ? `${overview.value.total_items} 个条目可用` : '等待媒体数据', ok: !!overview.value, icon: Film },
  { label: '存储来源', detail: `${mounts.value.filter((m) => m.is_enabled).length} 个挂载已启用`, ok: mounts.value.length === 0 || mounts.value.every((m) => m.last_check_ok !== false), icon: HardDrive },
])

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [h, o, s, m, b] = await Promise.all([
      fetchPanelHealth(),
      fetchEmbyOverview().catch(() => null),
      fetchSessions().catch(() => ({ sessions: [] as EmbySessionRow[] })),
      fetchMounts().catch(() => ({ mounts: [], mount_types: [] })),
      fetchBackupConfig().catch(() => null),
    ])
    health.value = h
    overview.value = o
    sessions.value = s.sessions
    mounts.value = m.mounts
    backup.value = b
    lastChecked.value = new Date().toLocaleTimeString()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '请求失败'
    ElMessage.error('健康检查失败，请确认 EM 服务仍在运行')
  } finally {
    loading.value = false
  }
}

async function saveBackup() {
  if (!backup.value) return
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(backup.value.time.trim())) {
    ElMessage.error('时间格式应为 HH:MM（24 小时制）')
    return
  }
  backupSaving.value = true
  try {
    backup.value = await saveBackupConfig(
      backup.value.enabled,
      backup.value.time.trim(),
      Math.max(1, Math.min(30, Math.round(backup.value.keep_days) || 7)),
    )
    ElMessage.success('备份配置已保存，立即生效')
  } catch {
    ElMessage.error('保存失败，请检查时间格式与保留天数')
  } finally {
    backupSaving.value = false
  }
}

async function manualBackup() {
  backupRunning.value = true
  try {
    const res = await runBackupNow()
    backup.value = res
    ElMessage.success(`备份完成：${res.backup.name}`)
  } catch {
    ElMessage.error('备份失败，请稍后重试')
  } finally {
    backupRunning.value = false
  }
}

function fmtDate(value: string | null): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <PageHeader
      eyebrow="系统与审计"
      title="服务健康"
      description="从媒体服务运维角度查看 EM、媒体库、在线会话与存储来源，而不是只看业务统计。"
    >
      <template #actions>
        <span class="checked-at">最近检查 {{ lastChecked || '—' }}</span>
        <el-button :loading="loading" type="primary" @click="load" :icon="RefreshCw">
          重新检查
        </el-button>
      </template>
    </PageHeader>

    <SectionCard v-if="loadError && !health" tone="accent">
      <EmptyState
        compact
        :icon="AlertTriangle"
        title="健康检查失败"
        :description="`请确认 EM 服务仍在运行（${loadError}）`"
      >
        <template #actions><el-button :loading="loading" @click="load">重试</el-button></template>
      </EmptyState>
    </SectionCard>

    <div class="health-grid" :aria-busy="loading">
      <StatTile
        v-for="item in checks"
        :key="item.label"
        layout="icon-left"
        :icon="item.icon"
        :label="item.label"
        :value="!health && loading ? '检查中' : item.ok ? '正常' : '异常'"
        :tone="!health && loading ? 'plain' : item.ok ? 'ok' : 'danger'"
        :hint="item.detail"
        :title="item.detail"
        class="health-tile"
      />
    </div>

    <SectionCard title="运行态" :icon="Radio" :meta="health?.emby_server || 'Aetrix Media Server'">
      <dl class="runtime-grid">
        <div><dt>在线用户</dt><dd>{{ health?.online_users ?? 0 }}</dd></div>
        <div><dt>在线会话</dt><dd>{{ overview?.active_sessions ?? sessions.length }}</dd></div>
        <div><dt>媒体条目</dt><dd>{{ overview?.total_items ?? 0 }}</dd></div>
        <div><dt>媒体库</dt><dd>{{ overview?.total_libraries ?? 0 }}</dd></div>
        <div><dt>管理员看到的挂载</dt><dd>{{ mounts.length }}</dd></div>
      </dl>
    </SectionCard>

    <div class="ops-grid">
      <SectionCard
        title="实时会话"
        :icon="Users"
        :meta="sessions.length > 8 ? `前 8 / 共 ${sessions.length}` : sessions.length ? `${sessions.length} 个` : ''"
      >
        <ul v-if="sessions.length" class="status-list">
          <li v-for="session in sessions.slice(0, 8)" :key="session.session_key" class="status-row">
            <span class="status-main">{{ session.username }} · {{ session.item }}</span>
            <span class="muted mono">{{ fmtDate(session.started_at) }}</span>
          </li>
        </ul>
        <EmptyState v-else compact :icon="Users" title="当前没有播放会话" />
      </SectionCard>

      <SectionCard title="数据库备份" :icon="Database" :meta="`上次执行 ${backup?.last_run || '—'}`">
        <div v-if="backup" class="backup-form">
          <div class="backup-row">
            <el-switch v-model="backup.enabled" active-text="定时备份" />
            <el-time-picker
              v-model="backup.time"
              format="HH:mm"
              value-format="HH:mm"
              placeholder="执行时间"
              class="w-time"
              :clearable="false"
            />
            <span class="keep">
              <span class="muted">保留</span>
              <el-input-number v-model="backup.keep_days" :min="1" :max="30" :controls="false" class="w-days" />
              <span class="muted">天</span>
            </span>
          </div>
          <div class="backup-row backup-actions">
            <el-button :loading="backupRunning" @click="manualBackup">立即备份</el-button>
            <el-button type="primary" :loading="backupSaving" @click="saveBackup">保存配置</el-button>
          </div>
          <ul v-if="backup.backups.length" class="status-list backup-list">
            <li v-for="f in backup.backups.slice(0, 7)" :key="f.name" class="status-row">
              <span class="status-main mono">{{ f.name }}</span>
              <span class="muted">{{ fmtSize(f.size) }} · {{ f.created_at }}</span>
            </li>
          </ul>
          <EmptyState v-else compact title="暂无备份文件" description="开启定时备份，或点「立即备份」生成第一份。" />
        </div>
        <div v-else-if="loading" class="backup-skeleton">
          <span class="au-skeleton" /><span class="au-skeleton" /><span class="au-skeleton is-short" />
        </div>
        <EmptyState v-else compact :icon="AlertTriangle" title="备份信息加载失败" description="不影响页面其他内容，可点「重新检查」再试。" />
      </SectionCard>
    </div>
  </div>
</template>

<style scoped>
.checked-at { font-size: 12px; color: var(--au-text-4); }

.health-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
/* 脚注只放一行（悬停看全文），四块高度对齐 */
.health-tile :deep(.au-stat__hint) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.health-tile :deep(.au-stat__value) { font-size: 1.25rem; }

.runtime-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}
.runtime-grid div {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  background: var(--au-surface-2);
}
.runtime-grid dt { font-size: 12px; color: var(--au-text-3); }
.runtime-grid dd {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--au-text);
}

.ops-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }

.status-list { display: flex; flex-direction: column; margin: 0; padding: 0; list-style: none; }
.status-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--au-border);
  font-size: 13px;
  color: var(--au-text-2);
}
.status-row:last-child { border-bottom: 0; }
.status-main { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-row .muted { flex-shrink: 0; }
.muted { color: var(--au-text-3); font-size: 12px; }

.backup-form { display: flex; flex-direction: column; gap: 12px; }
.backup-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.backup-actions { justify-content: flex-end; }
.keep { display: inline-flex; align-items: center; gap: 6px; }
.w-time { width: 130px; }
.w-days { width: 70px; }
.backup-list { max-height: 220px; overflow-y: auto; border-top: 1px solid var(--au-border); }
.backup-skeleton { display: flex; flex-direction: column; gap: 10px; }
.backup-skeleton .au-skeleton { display: block; height: 14px; border-radius: var(--au-r-sm); }
.backup-skeleton .is-short { width: 60%; }

@media (max-width: 1024px) {
  .health-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .runtime-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .ops-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .health-grid { grid-template-columns: 1fr; gap: 10px; }
  .runtime-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .status-row { flex-direction: column; gap: 2px; }
  .backup-actions { justify-content: stretch; }
  .backup-actions :deep(.el-button) { flex: 1; margin-left: 0; }
}
</style>
