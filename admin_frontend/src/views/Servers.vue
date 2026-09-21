<script setup lang="ts">
/**
 * 服务器：把「面板接了哪些外部服务」变成一份可增删改的清单
 *
 * 以前只能填一台后端服（EA）和一台已有 Emby 服，MoviePilot 与 qBittorrent 连入口都没有，
 * 所以求片批了之后没有办法真的把片子弄进来。这一页解决三件事：
 *
 * 1. **能加多台**：每类都可以加多台，EA / Emby 里挑一台作为「当前使用」；
 * 2. **告诉你有几台**：顶部四张统计卡（已添加 / 可用 / 当前使用），答「我到底接了什么」；
 *    （v2.6.21 起旧页「Emby 服务入口」已合并到这一页，旧地址保留为跳转）
 * 3. **接上求片**：MoviePilot 负责搜索下载，qBittorrent 负责下载，求片页直接就能转交；
 * 4. **归到某个服**（v2.6.20）：EA / Emby 是一个服一个的，加的时候就要选归属服；
 *    MoviePilot / qB 可以让多台服务器共用（归属留空 = 每个服都能用它求片）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CheckCircle2,
  CloudDownload,
  Download,
  HardDrive,
  Pencil,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  Wifi,
} from 'lucide-vue-next'
import {
  activateServer,
  createServer,
  deleteServer,
  fetchServers,
  refreshServerMounts,
  testServer,
  testServerConfig,
  toggleServer,
  updateServer,
} from '@/api/admin'
import type { RemoteServerRow, ServerKind, ServerKindMeta, ServerSummary, ServerProbeResult } from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const realm = useRealmStore()
/** 可选的归属服（面板当前服的选项一定在里面） */
const realmOptions = computed(() => realm.realms)
/** 内容自动化（MoviePilot / qB）可以「全服共用」，不需要归属某个服 */
const isSharedKind = computed(() => form.kind === 'moviepilot' || form.kind === 'qbittorrent')

const columns: DataColumn[] = [
  { key: 'name', label: '名称', minWidth: 160, mobile: 'title' },
  { key: 'kind_label', label: '类型', width: 130 },
  { key: 'realm_name', label: '归属服', width: 130 },
  { key: 'url', label: '地址', minWidth: 200 },
  { key: 'state', label: '状态', width: 190 },
  { key: 'actions', label: '操作', width: 250, fixed: 'right', align: 'right' },
]

const KIND_ICONS: Record<string, unknown> = {
  ea: Server,
  emby: HardDrive,
  moviepilot: CloudDownload,
  qbittorrent: Download,
}

const servers = ref<RemoteServerRow[]>([])
const kinds = ref<ServerKindMeta[]>([])
const summary = ref<ServerSummary | null>(null)
const loading = ref(false)
const busyId = ref<number | null>(null)
const kindFilter = ref<ServerKind | ''>('')

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const testingUnsaved = ref(false)
const unsavedResult = ref<ServerProbeResult | null>(null)
const form = reactive({
  name: '',
  kind: 'ea' as ServerKind,
  url: '',
  remark: '',
  is_enabled: true,
  config: {} as Record<string, string>,
  /** 归属服：EA / Emby 一个服一个；MoviePilot / qB 可留空（全服共用） */
  realm_id: null as number | null,
  shared: false,
})

const currentKind = computed(() => kinds.value.find((k) => k.value === form.kind))
const rows = computed(() =>
  kindFilter.value ? servers.value.filter((s) => s.kind === kindFilter.value) : servers.value
)
/** 顶部统计卡：顺序固定按后端下发，不要被数据里的出现顺序带跑 */
const kindCards = computed(() =>
  kinds.value.map((k) => ({ meta: k, stat: summary.value?.kinds?.[k.value] }))
)

function fmtDate(s: string | null): string {
  return s ? s.slice(0, 16).replace('T', ' ') : '未测试'
}

function stateBadge(s: RemoteServerRow): string {
  if (!s.is_enabled) return 'off'
  if (s.last_check_ok === true) return 'ok'
  if (s.last_check_ok === false) return 'danger'
  return 'warn'
}

function stateText(s: RemoteServerRow): string {
  if (!s.is_enabled) return '已停用'
  if (s.last_check_ok === true) return '连接正常'
  if (s.last_check_ok === false) return '连接失败'
  return '未测试'
}

async function load() {
  loading.value = true
  try {
    // 归属服下拉要用到服的清单（Layout 已加载过就不重复请求）
    if (!realm.loaded) realm.load().catch(() => undefined)
    const res = await fetchServers()
    servers.value = res.servers
    kinds.value = res.kinds
    summary.value = res.summary
  } finally {
    loading.value = false
  }
}

onMounted(load)

function resetForm(kind: ServerKind = 'ea') {
  editingId.value = null
  unsavedResult.value = null
  form.name = ''
  form.kind = kind
  form.url = ''
  form.remark = ''
  form.is_enabled = true
  form.config = {}
  form.realm_id = realm.activeId
  form.shared = false
}

function openCreate(kind: ServerKind = 'ea') {
  resetForm(kind)
  dialogVisible.value = true
}

function openEdit(row: RemoteServerRow) {
  resetForm(row.kind)
  editingId.value = row.id
  form.name = row.name
  form.url = row.url
  form.remark = row.remark
  form.is_enabled = row.is_enabled
  form.realm_id = row.realm_id ?? realm.activeId
  form.shared = !!row.shared
  // 密钥不回明文：留空即「不改」，所以这里只回填非密钥字段
  const config: Record<string, string> = {}
  for (const [key, value] of Object.entries(row.config || {})) config[key] = value ?? ''
  form.config = config
  dialogVisible.value = true
}

/** 换类型时旧类型的字段不再适用，清掉避免把 A 类型的配置存进 B 类型 */
function onKindChange() {
  const keep = new Set((currentKind.value?.fields || []).map((f) => f.key))
  form.config = Object.fromEntries(Object.entries(form.config).filter(([k]) => keep.has(k)))
}

async function testUnsaved() {
  if (!form.url) return ElMessage.warning('请先填写服务地址')
  testingUnsaved.value = true
  try {
    unsavedResult.value = await testServerConfig({
      kind: form.kind,
      url: form.url,
      config: form.config,
      server_id: editingId.value ?? undefined,
    })
    unsavedResult.value.ok
      ? ElMessage.success(unsavedResult.value.message || '连接成功')
      : ElMessage.warning(unsavedResult.value.message || '连接失败')
  } catch {
    /* 拦截器已提示 */
  } finally {
    testingUnsaved.value = false
  }
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写一个便于识别的名称')
  if (!form.url.trim()) return ElMessage.warning('请填写服务地址')
  saving.value = true
  const payload = {
    name: form.name.trim(),
    kind: form.kind,
    url: form.url.trim(),
    config: form.config,
    is_enabled: form.is_enabled,
    remark: form.remark,
    // 一个服一个：EA / Emby 必须选一个归属服；内容自动化可以选「全服共用」
    realm_id: form.shared ? null : form.realm_id,
    shared: isSharedKind.value && form.shared,
  }
  try {
    const res = editingId.value
      ? await updateServer(editingId.value, payload)
      : await createServer(payload)
    res.probe?.ok
      ? ElMessage.success('已保存，连接正常')
      : ElMessage.warning(res.probe?.message || '已保存，但连接失败：请检查地址与凭据')
    dialogVisible.value = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

async function runTest(row: RemoteServerRow) {
  busyId.value = row.id
  try {
    const res = await testServer(row.id)
    res.ok ? ElMessage.success(res.message || '连接成功') : ElMessage.warning(res.message || '连接失败')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyId.value = null
  }
}

async function runActivate(row: RemoteServerRow) {
  busyId.value = row.id
  try {
    const res = await activateServer(row.id)
    if (res.success) {
      ElMessage.success(res.message || '已设为当前使用')
      if (res.mounts_health && res.mounts_health.ok === false) {
        ElMessage.warning('这台 EA 上还有挂载不可达，去「存储挂载」页看逐条结论')
      }
    } else {
      ElMessage.warning(res.message || '连接没通过，已保持原来的入口')
    }
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyId.value = null
  }
}

async function runToggle(row: RemoteServerRow) {
  busyId.value = row.id
  try {
    const res = await toggleServer(row.id)
    ElMessage.success(res.server.is_enabled ? '已启用' : '已停用')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyId.value = null
  }
}

async function runRefreshMounts() {
  try {
    const res = await refreshServerMounts()
    res.success
      ? ElMessage.success(`已刷新 ${res.server} 上的挂载可达性`)
      : ElMessage.warning(res.health?.error || 'EA 体检未完成')
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(row: RemoteServerRow) {
  await ElMessageBox.confirm(
    `删除「${row.name}」？${row.is_active ? '它是当前的 Emby 服务入口，删除后会切回面板自己出流。' : ''}`,
    '删除服务器',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
  busyId.value = row.id
  try {
    await deleteServer(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">服务器</h1>
        <p class="admin-page-subtitle">
          面板一共接了哪些服务、有几台能用、当前用哪一台，都在这一页
        </p>
      </div>
      <div class="toolbar">
        <el-button @click="runRefreshMounts">
          <Wifi :size="14" style="margin-right: 4px" />EA 挂载体检
        </el-button>
        <el-button type="primary" @click="openCreate()">
          <Plus :size="14" style="margin-right: 4px" />添加服务器
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <!-- 统计卡：一眼看出「加了多少后端服 / 多少 Emby 服 / 下载器接没接」 -->
    <div class="kind-grid">
      <button
        v-for="card in kindCards"
        :key="card.meta.value"
        class="kind-card admin-card"
        :class="{ active: kindFilter === card.meta.value }"
        @click="kindFilter = kindFilter === card.meta.value ? '' : card.meta.value"
      >
        <div class="kind-top">
          <span class="kind-icon"><component :is="KIND_ICONS[card.meta.value]" :size="17" /></span>
          <span class="kind-label">{{ card.meta.short }}</span>
          <span class="kind-count">{{ card.stat?.total ?? 0 }}</span>
        </div>
        <div class="kind-line">
          <span class="mini-badge" :class="(card.stat?.reachable ?? 0) > 0 ? 'ok' : 'off'">
            可用 {{ card.stat?.reachable ?? 0 }}
          </span>
          <span v-if="card.meta.activatable" class="kind-current">
            {{ card.stat?.active_name ? `当前：${card.stat.active_name}` : '未设置当前使用' }}
          </span>
          <span v-else class="kind-current">用于求片</span>
        </div>
      </button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="guide">
      <template #title>每一类分别是干什么的</template>
      <template #default>
        <b>后端服（EA）</b>＝本项目自带的 Emby API，播放和媒体库都靠它；必须和面板用同一个数据库与
        SECRET_KEY。<b>已有 Emby 服</b>＝你自己那台 Emby / Jellyfin，接入后本项目的自建媒体库会停用。
        <b>MoviePilot</b>＝负责搜索下载与整理，求片批准后一键提交成它的订阅。
        <b>qBittorrent</b>＝下载器，拿到磁力 / 种子链接就能直接下载（它自己不会去找片子）。
        EA / Emby 可以加多台，但同一时间只有一台是「当前使用」；MoviePilot 与 qB 可以多台一起接。
        <b>入口只有一个</b>：以前那页「Emby 服务入口」已并入这里，加完点「设为当前」即可生效。
      </template>
    </el-alert>

    <div class="admin-card">
      <DataTable
        :rows="rows"
        :columns="columns"
        :loading="loading"
        empty="还没有添加任何服务器，点右上角「添加服务器」开始"
      >
        <template #cell-name="{ row }">
          <div class="name-cell">
            <span class="name">{{ row.name }}</span>
            <span v-if="row.is_active" class="mini-badge ok">当前使用</span>
            <span v-if="row.remark" class="muted remark">{{ row.remark }}</span>
          </div>
        </template>

        <template #cell-kind_label="{ row }">
          <span class="mini-badge" :class="row.kind_group === '播放' ? 'local' : 'remote'">
            {{ row.kind_label }}
          </span>
        </template>

        <template #cell-realm_name="{ row }">
          <span v-if="row.shared" class="mini-badge info">全服共用</span>
          <span v-else-if="row.realm_name" class="mini-badge muted">{{ row.realm_name }}</span>
          <span v-else class="mini-badge warn">未归服</span>
        </template>

        <template #cell-url="{ row }">
          <span class="url">{{ row.url }}</span>
        </template>

        <template #cell-state="{ row }">
          <div class="state-cell">
            <span class="mini-badge" :class="stateBadge(row)">{{ stateText(row) }}</span>
            <span class="muted state-time">{{ fmtDate(row.last_checked_at) }}</span>
            <el-tooltip v-if="row.last_check_message" :content="row.last_check_message" placement="top">
              <span class="muted state-msg">{{ row.last_check_message }}</span>
            </el-tooltip>
          </div>
        </template>

        <template #cell-actions="{ row }">
          <el-button size="small" :loading="busyId === row.id" @click="runTest(row)">测试</el-button>
          <el-button
            v-if="row.activatable && !row.is_active"
            size="small"
            type="primary"
            plain
            :loading="busyId === row.id"
            @click="runActivate(row)"
          >
            <CheckCircle2 :size="13" style="margin-right: 3px" />设为当前
          </el-button>
          <el-button size="small" @click="openEdit(row)"><Pencil :size="13" /></el-button>
          <el-button size="small" :loading="busyId === row.id" @click="runToggle(row)">
            {{ row.is_enabled ? '停用' : '启用' }}
          </el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">
            <Trash2 :size="13" />
          </el-button>
        </template>
      </DataTable>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑服务器' : '添加服务器'"
      width="560px"
      class="server-dialog"
    >
      <el-form label-position="top">
        <el-form-item label="类型">
          <el-select v-model="form.kind" style="width: 100%" :disabled="!!editingId" @change="onKindChange">
            <el-option v-for="k in kinds" :key="k.value" :label="k.label" :value="k.value" />
          </el-select>
          <p v-if="currentKind" class="field-help">{{ currentKind.desc }}</p>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" :placeholder="`例如 ${currentKind?.label || '服务器'} 主节点`" />
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.url" placeholder="必须以 http:// 或 https:// 开头" />
        </el-form-item>
        <el-form-item label="归属服">
          <el-select
            v-model="form.realm_id"
            :disabled="isSharedKind && form.shared"
            style="width: 100%"
            placeholder="选择这台服务器属于哪个服"
          >
            <el-option v-for="r in realmOptions" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
          <p class="field-help">
            EA / Emby 是「一个服一个」的入口：用户看到的地址、能播的内容都按归属服判定。
          </p>
          <template v-if="isSharedKind">
            <el-checkbox v-model="form.shared" label="全服共用（不属于某个服）" border style="margin-top: 8px" />
            <p class="field-help">
              MoviePilot / qBittorrent 属于内容自动化：勾上以后每个服都能用它求片，
              多服运营通常只需要接一套。
            </p>
          </template>
        </el-form-item>
        <el-form-item v-for="field in currentKind?.fields || []" :key="field.key" :label="field.label">
          <el-input
            v-model="form.config[field.key]"
            :type="field.type === 'password' ? 'password' : 'text'"
            :show-password="field.type === 'password'"
            :placeholder="
              editingId && field.secret && (servers.find((s) => s.id === editingId)?.secret_keys || []).includes(field.key)
                ? '已保存，留空表示不修改'
                : field.placeholder
            "
          />
          <p v-if="field.help" class="field-help">{{ field.help }}</p>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" placeholder="可选，例如「主力机」「备份」" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
        </el-form-item>
      </el-form>

      <div v-if="unsavedResult" class="probe" :class="unsavedResult.ok ? 'ok' : 'bad'">
        {{ unsavedResult.ok ? '✓' : '✗' }} {{ unsavedResult.message || (unsavedResult.ok ? '连接成功' : '连接失败') }}
      </div>

      <template #footer>
        <el-button :loading="testingUnsaved" @click="testUnsaved">
          <Wifi :size="14" style="margin-right: 4px" />测试连接
        </el-button>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kind-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.kind-card {
  text-align: left;
  cursor: pointer;
  padding: 14px 15px;
  border: 1px solid var(--border-default);
  background: var(--bg-surface);
  transition: border-color var(--transition-base), background var(--transition-base);
}
.kind-card:hover { border-color: var(--primary); }
.kind-card.active { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary-bg); }
.kind-top { display: flex; align-items: center; gap: 8px; }
.kind-icon {
  width: 30px; height: 30px; display: grid; place-items: center;
  border-radius: 9px; background: var(--primary-bg); color: var(--primary);
}
.kind-label { color: var(--text-secondary); font-size: var(--font-size-sm); }
.kind-count { margin-left: auto; font-size: 22px; font-weight: var(--font-weight-semibold); color: var(--text-primary); }
.kind-line { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.kind-current { color: var(--text-muted); font-size: var(--font-size-xs); }
.guide { margin-bottom: 14px; line-height: 1.75; }
.name-cell { display: flex; flex-direction: column; gap: 3px; }
.name-cell .name { color: var(--text-primary); font-weight: var(--font-weight-medium); }
.name-cell .mini-badge { align-self: flex-start; }
.remark { font-size: var(--font-size-xs); }
.url { color: var(--text-secondary); word-break: break-all; font-size: var(--font-size-sm); }
.state-cell { display: flex; flex-direction: column; gap: 3px; }
.state-time, .state-msg { font-size: var(--font-size-xs); }
.state-msg { display: block; max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.field-help { color: var(--text-muted); font-size: var(--font-size-xs); margin: 5px 0 0; line-height: 1.6; }
.probe { padding: 9px 11px; border-radius: var(--radius-md); font-size: var(--font-size-sm); margin-top: 4px; }
.probe.ok { color: var(--success); background: var(--success-bg); }
.probe.bad { color: var(--danger); background: var(--danger-bg); }
@media (max-width: 1100px) { .kind-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .kind-grid { grid-template-columns: 1fr; } }
</style>
