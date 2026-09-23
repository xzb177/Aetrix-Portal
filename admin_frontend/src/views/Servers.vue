<script setup lang="ts">
/**
 * 服务器 · Emby 总览 —— **Emby 相关功能的唯一入口页**
 *
 * 演进：以前「填一台 EA + 填一台已有 Emby」写在「Emby 服务入口」，「接了什么、有几台能用」
 * 在「服务器」，「这台 EA 碰不碰得到存储」在「存储挂载」，「库归谁扫」在「媒体库」——
 * 想知道「这台 EA 到底在不在服务这个服、库有没有分给它」要来回跳四个页面拼。
 *
 * v2.6.22 起这一页就是**唯一入口**：旧页「Emby 服务入口」已下线（旧地址跳到这里），
 * 页面本身由 `GET /api/admin/servers/overview` 驱动，按服给出每台入口的：
 *
 * 1. **连接体检**（面板视角的连通性与最近一次结论）；
 * 2. **节点认领**：`NODE_KEY` 有没有配上、EA 自己说它属于哪个服（`live` 时真去问）；
 * 3. **挂载体检**：这台 EA 视角下哪些存储碰不到（挂载是本机相对的，面板测通不代表它能播）；
 * 4. **库归属**：归它出流/扫描的媒体库数，以及同服里还没分配的库数；
 * 5. **告警**：两边不一致（EA 自称的服 ≠ 面板登记的服、NODE_KEY 对不上、挂载不可达、
 *    连接失败…）直接列出来，不用自己去比对。
 *
 * 增删改（添加 / 编辑 / 测试 / 设为当前 / 启停 / 删除）也都在这一页完成；
 * 内容自动化（MoviePilot / qB）与出流入口分开成两段，避免混在一起看不清谁在出流。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  AlertTriangle, CheckCircle2, CloudDownload, Download, HardDrive, Pencil, Plus,
  RefreshCw, Route as RealmIcon, Server, Trash2, Wifi,
} from 'lucide-vue-next'
import {
  activateServer,
  createServer,
  deleteServer,
  fetchServers,
  fetchServersOverview,
  refreshServerMounts,
  testServer,
  testServerConfig,
  toggleServer,
  updateServer,
} from '@/api/admin'
import type {
  RemoteServerRow, ServerKind, ServerKindMeta, ServerOverview, ServerOverviewRow,
  ServerProbeResult, ServerSummary,
} from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const realm = useRealmStore()

/** 出流入口（一个服一个）与内容自动化（可全服共用）——分两段展示，别混在一起 */
const ENTRY_KINDS: ServerKind[] = ['ea', 'emby']
const CONTENT_KINDS: ServerKind[] = ['moviepilot', 'qbittorrent']

const KIND_ICONS: Record<string, unknown> = {
  ea: Server,
  emby: HardDrive,
  moviepilot: CloudDownload,
  qbittorrent: Download,
}

// ==================== 状态 ====================

const servers = ref<RemoteServerRow[]>([])
const kinds = ref<ServerKindMeta[]>([])
const summary = ref<ServerSummary | null>(null)
/** Emby 总览（按服分组的入口画像）：页面主体数据 */
const overview = ref<ServerOverview | null>(null)
const loading = ref(false)
/** 「一键体检」在跑：真去问每台 EA 的节点身份 + 重拉挂载体检 */
const liveRunning = ref(false)
/** 范围：默认看**全部服**（总览的意义就在这），也可以只看当前服 */
const scopeAll = ref(true)
const kindFilter = ref<ServerKind | ''>('')
const busyId = ref<number | null>(null)

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

// ==================== 派生 ====================

const scopeParams = computed(() => (scopeAll.value ? { realm_id: 0 } : {}))
const isSharedKind = computed(() => form.kind === 'moviepilot' || form.kind === 'qbittorrent')
const currentKind = computed(() => kinds.value.find((k) => k.value === form.kind))
const kindCards = computed(() =>
  kinds.value.map((k) => ({ meta: k, stat: (overview.value?.summary ?? summary.value)?.kinds?.[k.value] }))
)
const totals = computed(() => overview.value?.totals ?? null)

/** 当前筛选下要看哪几类 */
const filterKinds = computed<ServerKind[]>(() =>
  kindFilter.value
    ? [kindFilter.value]
    : [...ENTRY_KINDS, ...CONTENT_KINDS]
)

/** 某台入口行是不是被当前筛选保留 */
function keepRow(row: ServerOverviewRow): boolean {
  return filterKinds.value.includes(row.kind)
}

/** 一段一段：每个服一张卡（按服分组才是「总览」，也避免同一台入口在页面上出现两次） */
const realmCards = computed(() => {
  const cards = overview.value?.realms ?? []
  const rows = (overview.value?.rows ?? []).filter(keepRow)
  return cards
    .map((card) => ({ card, rows: rows.filter((r) => r.realm_id === card.id) }))
    // 只筛某一类时，没有这一类的服不用占位置；看全部时保留空服，好让人一眼看出「这个服还空着」
    .filter(({ rows: list }) => list.length > 0 || kindFilter.value === '')
})

/** 内容自动化（MoviePilot / qB）：不属于某个服，多服共用 */
const contentRows = computed(() =>
  servers.value.filter((s) => filterKinds.value.includes(s.kind) && CONTENT_KINDS.includes(s.kind))
)

/** 当前筛选下要不要显示两段（出流入口 / 内容自动化） */
const showEntries = computed(() => !kindFilter.value || ENTRY_KINDS.includes(kindFilter.value))
const showContent = computed(() => !kindFilter.value || CONTENT_KINDS.includes(kindFilter.value))

const warnCount = computed(() => {
  const cards = (overview.value?.realms ?? []).reduce((sum, c) => sum + (c.warnings?.length || 0), 0)
  const rows = (overview.value?.rows ?? []).reduce((sum, r) => sum + (r.warnings?.length || 0), 0)
  return cards + rows
})

// ==================== 表格列 ====================

/** 入口表（EA / 已有 Emby）：一行的所有事实都在这几列里 */
const entryColumns: DataColumn[] = [
  { key: 'name', label: '名称', minWidth: 170, mobile: 'title' },
  { key: 'kind_label', label: '类型', width: 120 },
  { key: 'url', label: '地址', minWidth: 190 },
  { key: 'state', label: '连接', width: 170 },
  { key: 'node', label: '节点 / 归属', minWidth: 200 },
  { key: 'mounts', label: '挂载体检', minWidth: 190 },
  { key: 'libraries', label: '媒体库', width: 130 },
  // 测试 / 设为当前 / 编辑 / 停用启用 / 删除 收进「管理」弹窗：行里只留一个入口
  { key: 'actions', label: '操作', width: 100, fixed: 'right', align: 'right' },
]

const contentColumns: DataColumn[] = [
  { key: 'name', label: '名称', minWidth: 160, mobile: 'title' },
  { key: 'kind_label', label: '类型', width: 130 },
  { key: 'scope', label: '作用范围', width: 120 },
  { key: 'url', label: '地址', minWidth: 200 },
  { key: 'state', label: '状态', width: 190 },
  // 同上：一个「管理」入口，细节与动作都在弹窗里
  { key: 'actions', label: '操作', width: 100, fixed: 'right', align: 'right' },
]

// ==================== 加载 ====================

async function load() {
  loading.value = true
  try {
    if (!realm.loaded) realm.load().catch(() => undefined)
    const [list, ov] = await Promise.all([
      fetchServers(scopeParams.value),
      fetchServersOverview(scopeParams.value),
    ])
    servers.value = list.servers
    kinds.value = list.kinds
    summary.value = list.summary
    overview.value = ov
  } finally {
    loading.value = false
  }
}

/** 一键体检：真的去问每台 EA「你是谁、属于哪个服、负责哪些库」，并重拉当前出流 EA 的挂载体检 */
async function runLive() {
  liveRunning.value = true
  try {
    const ov = await fetchServersOverview({ ...scopeParams.value, live: true })
    overview.value = ov
    const list = await fetchServers(scopeParams.value)
    servers.value = list.servers
    summary.value = list.summary
    const bad = ov.totals?.warnings ?? 0
    bad
      ? ElMessage.warning(`体检完成，有 ${bad} 条需要注意（已标在下面各行）`)
      : ElMessage.success('体检完成，全部正常')
  } catch {
    /* 拦截器已提示 */
  } finally {
    liveRunning.value = false
  }
}

onMounted(load)

// ==================== 展示辅助 ====================

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

/** 节点列：面板登记了什么 + EA 自己说了什么（live 才有） */
function nodeText(row: ServerOverviewRow): string {
  const parts: string[] = []
  if (row.node_key) parts.push(`认领：${row.node_key}`)
  else parts.push(row.kind === 'ea' ? '未认领（未配 NODE_KEY）' : '不适用')
  const identity = row.identity || ({} as ServerOverviewRow['identity'])
  if (identity.ok) {
    if (identity.realm_slug) parts.push(`EA 自称：${identity.realm_name || identity.realm_slug}`)
    if (identity.claimed && identity.node_name) parts.push(`节点：${identity.node_name}`)
    if (typeof identity.libraries === 'number') parts.push(`EA 可见库：${identity.libraries}`)
  }
  return parts.join(' · ')
}

function mountBadge(mounts: ServerOverviewRow['mounts']): string {
  if (!mounts) return 'off'
  if (mounts.never_checked) return 'warn'
  if (!mounts.ok) return 'danger'
  return mounts.failed_count ? 'danger' : 'ok'
}

function mountText(mounts: ServerOverviewRow['mounts']): string {
  if (!mounts) return '仅 EA 有此体检'
  if (mounts.never_checked) return '还没做过（点「一键体检」）'
  if (mounts.error) return `体检失败：${mounts.error}`
  if (mounts.failed_count) return `${mounts.failed_count} / ${mounts.total} 条不可达`
  return `${mounts.total} 条全部可达`
}

// ==================== 对话框 ====================

/**
 * 切换当前服：与顶栏那个切换器同一份状态（stores/realm），切完就地刷新本页
 *
 * 「多服」在导航里不再是一个模块，所以作用域的选择就放在这一页——
 * 先选服，再看这台的服务器与线路。
 */
async function switchRealm(id: number) {
  if (!id || id === realm.activeId) return
  try {
    await realm.switchTo(id)
    ElMessage.success(`已切换到「${realm.activeName() || id}」`)
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

function resetForm(kind: ServerKind = 'ea', realmId: number | null = null) {
  editingId.value = null
  unsavedResult.value = null
  form.name = ''
  form.kind = kind
  form.url = ''
  form.remark = ''
  form.is_enabled = true
  form.config = {}
  form.realm_id = realmId ?? realm.activeId
  form.shared = false
}

/** 从某个服的卡片上添加：直接预填那个服，不用再选一次 */
function openCreate(kind: ServerKind = 'ea', realmId: number | null = null) {
  resetForm(kind, realmId)
  dialogVisible.value = true
}

function openEdit(row: RemoteServerRow) {
  resetForm(row.kind, row.realm_id)
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

// ==================== 行操作 ====================

// ==================== 服务器管理弹窗（v2.29.0） ====================
// 入口行原本摆着 5 个按钮（测试 / 设为当前 / 编辑 / 停用启用 / 删除），而连接结论、节点认领、
// 挂载体检、媒体库归属全挤在带 tooltip 的单元格里；现在一个入口，弹窗里把一台机器的事实
// 与能做的动作放在同一处。
const manage = ref({ visible: false, row: null as ServerOverviewRow | RemoteServerRow | null })

function isEntryRow(r: RemoteServerRow | ServerOverviewRow): r is ServerOverviewRow {
  return 'is_current_entry' in r
}

function openManage(row: ServerOverviewRow | RemoteServerRow) {
  manage.value = { visible: true, row }
}

/** 动作后刷新两段表，并把弹窗里的那台机器换成最新快照 */
async function refreshManage(id: number) {
  await load()
  const fresh =
    (overview.value?.rows ?? []).find((r) => r.id === id) || servers.value.find((s) => s.id === id)
  if (fresh) {
    manage.value.row = fresh
  } else {
    manage.value.visible = false
  }
}

/** 从弹窗进编辑：先关掉这一层，避免两个弹窗叠着 */
function editFromManage(row: RemoteServerRow) {
  manage.value.visible = false
  openEdit(row)
}

/** 作用范围：内容自动化（MoviePilot / qB）可以是「全服共用」 */
function scopeText(row: RemoteServerRow): string {
  if (row.shared) return '全服共用'
  return row.realm_name || '未标注'
}

async function runTest(row: RemoteServerRow) {
  busyId.value = row.id
  try {
    const res = await testServer(row.id)
    res.ok ? ElMessage.success(res.message || '连接成功') : ElMessage.warning(res.message || '连接失败')
    await refreshManage(row.id)
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
        ElMessage.warning('这台 EA 上还有挂载不可达，看本页「挂载体检」列')
      }
    } else {
      ElMessage.warning(res.message || '连接没通过，已保持原来的入口')
    }
    await refreshManage(row.id)
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
    await refreshManage(row.id)
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
    await load()
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(row: RemoteServerRow) {
  try {
    await ElMessageBox.confirm(
      `删除「${row.name}」？${row.is_active ? '它是当前的 Emby 服务入口，删除后会切回面板自己出流。' : ''}`,
      '删除服务器',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  busyId.value = row.id
  try {
    await deleteServer(row.id)
    ElMessage.success('已删除')
    await refreshManage(row.id)
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
        <h1 class="admin-page-title">服务器与线路</h1>
        <p class="admin-page-subtitle">
          接了几台后端服、几台已有 Emby、当前用哪台出流、库归谁、这台机器碰不碰得到存储 ——
          都在这一页（范围在右上角切，不用先理解「多服」是个什么模块）
        </p>
      </div>
      <div class="toolbar">
        <RouterLink to="/realms" class="toolbar-link">
          <RealmIcon :size="14" />服管理
        </RouterLink>
        <RouterLink to="/mounts" class="toolbar-link">存储来源</RouterLink>
        <RouterLink to="/emby" class="toolbar-link">媒体库</RouterLink>
        <el-button :loading="liveRunning" @click="runLive">
          <Wifi :size="14" style="margin-right: 4px" />一键体检
        </el-button>
        <el-button @click="runRefreshMounts">EA 挂载体检</el-button>
        <el-button type="primary" @click="openCreate()">
          <Plus :size="14" style="margin-right: 4px" />添加服务器
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <!-- 汇总：一眼看出「接了多少、多少可用、多少要处理」 -->
    <div class="ov-totals admin-card">
      <span class="ov-item">
        <b>{{ totals?.entry ?? 0 }}</b>
        <em>Emby 出流入口</em>
      </span>
      <span class="ov-item">
        <b class="ok">{{ totals?.online ?? 0 }}</b>
        <em>连接正常</em>
      </span>
      <span class="ov-item">
        <b>{{ totals?.libraries ?? 0 }}</b>
        <em>媒体库</em>
      </span>
      <span class="ov-item">
        <b :class="{ warn: (totals?.libraries_unassigned ?? 0) > 0 }">{{ totals?.libraries_unassigned ?? 0 }}</b>
        <em>未分配节点</em>
      </span>
      <span class="ov-item">
        <b :class="{ danger: warnCount > 0, ok: warnCount === 0 }">{{ warnCount }}</b>
        <em>需要处理</em>
      </span>
      <span class="ov-scope">
        <!-- 当前服与范围都在这一页选：多服不是一个要单独学的模块，只是这里的一个筛选条件 -->
        <span class="ov-scope-label">当前服</span>
        <el-select
          :model-value="realm.activeId ?? undefined"
          size="small"
          placeholder="当前服"
          class="scope-realm"
          @change="switchRealm"
        >
          <el-option v-for="r in realm.realms" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
        <span class="ov-scope-label">范围</span>
        <el-radio-group v-model="scopeAll" size="small" @change="load">
          <el-radio-button :value="true">全部服</el-radio-button>
          <el-radio-button :value="false">仅当前服</el-radio-button>
        </el-radio-group>
      </span>
    </div>

    <!-- 统计卡：点一下只看那一类（内容自动化与出流入口分开看） -->
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
        SECRET_KEY。<b>已有 Emby 服</b>＝你已经在跑的那台 Emby / Jellyfin，接入后本项目的自建媒体库会停用。
        <b>MoviePilot</b>＝负责搜索下载与整理，求片批准后一键提交成它的订阅。
        <b>qBittorrent</b>＝下载器，拿到磁力 / 种子链接就能直接下载（它自己不会去找片子）。
        EA / Emby 可以加多台，但**同一个服同一时间只有一台是「当前使用」**；MoviePilot 与 qB 可以多台一起接。
        <b>入口只有一个</b>：以前那页「Emby 服务入口」已并入这里，加完点「设为当前」即可生效。
      </template>
    </el-alert>

    <!-- ==================== Emby 总览（按服） ==================== -->
    <template v-if="showEntries">
      <div v-loading="loading" class="realm-stack">
        <section
          v-for="{ card, rows: entryRows } in realmCards"
          :key="card.id"
          class="realm-card admin-card"
        >
          <header class="realm-head">
            <span class="realm-icon"><RealmIcon :size="16" /></span>
            <span class="realm-name">
              {{ card.name }}
              <span v-if="card.is_default" class="mini-badge muted">默认服</span>
              <span v-if="!card.is_active" class="mini-badge warn">已停用</span>
              <em class="realm-slug">{{ card.slug }}</em>
            </span>
            <span class="realm-entry">
              <span class="mini-badge" :class="card.entry.mode === 'panel' ? 'warn' : 'ok'">
                当前入口：{{ card.entry.label }}
              </span>
              <span v-if="card.entry.url" class="muted realm-url">{{ card.entry.url }}</span>
              <span class="muted">
                媒体库 {{ card.libraries.total }} 个<template v-if="card.libraries.unassigned">
                  （未分配节点 {{ card.libraries.unassigned }}）</template>
              </span>
            </span>
            <span class="realm-actions">
              <RouterLink :to="`/realms`" class="muted link">服管理</RouterLink>
              <RouterLink :to="`/emby`" class="muted link">媒体库</RouterLink>
              <el-button size="small" @click="openCreate('ea', card.id)">
                <Plus :size="13" style="margin-right: 3px" />加 EA
              </el-button>
              <el-button size="small" @click="openCreate('emby', card.id)">
                <Plus :size="13" style="margin-right: 3px" />加 Emby
              </el-button>
            </span>
          </header>

          <div v-if="card.warnings?.length" class="warn-box">
            <span v-for="w in card.warnings" :key="w" class="warn-line">
              <AlertTriangle :size="13" />{{ w }}
            </span>
          </div>

          <DataTable
            :rows="entryRows"
            :columns="entryColumns"
            empty="这个服还没有 Emby 出流入口：点右上角「加 EA」或「加 Emby」"
          >
            <template #cell-name="{ row }">
              <div class="name-cell">
                <span class="name">{{ row.name }}</span>
                <span class="badges">
                  <span v-if="row.is_current_entry" class="mini-badge ok">当前使用</span>
                  <span v-if="!row.is_enabled" class="mini-badge off">已停用</span>
                  <span v-if="row.realm_name && !scopeAll" class="mini-badge muted">{{ row.realm_name }}</span>
                </span>
                <span v-if="row.remark" class="muted remark">{{ row.remark }}</span>
              </div>
            </template>

            <template #cell-kind_label="{ row }">
              <span class="mini-badge local">{{ row.kind_label }}</span>
            </template>

            <template #cell-url="{ row }">
              <span class="url">{{ row.url }}</span>
            </template>

            <template #cell-state="{ row }">
              <div class="state-cell">
                <span class="mini-badge" :class="stateBadge(row)">{{ stateText(row) }}</span>
                <span class="muted sub">{{ fmtDate(row.last_checked_at) }}</span>
                <el-tooltip v-if="row.last_check_message" :content="row.last_check_message" placement="top">
                  <span class="muted sub ellipsis">{{ row.last_check_message }}</span>
                </el-tooltip>
              </div>
            </template>

            <template #cell-node="{ row }">
              <el-tooltip :content="nodeText(row)" placement="top">
              <div class="state-cell">
                <span class="mini-badge" :class="row.node_key ? 'info' : 'muted'">
                  {{ row.node_key ? `认领 ${row.node_key}` : (row.kind === 'ea' ? '未认领' : '不适用') }}
                </span>
                <span v-if="row.identity?.ok && row.identity.realm_slug" class="muted sub">
                  EA 自称：{{ row.identity.realm_name || row.identity.realm_slug }}
                </span>
                <el-tooltip v-if="row.identity?.ok === false" :content="row.identity.error || ''" placement="top">
                  <span class="muted sub ellipsis">身份探测失败</span>
                </el-tooltip>
                <span v-else-if="typeof row.identity?.libraries === 'number'" class="muted sub">
                  EA 可见库：{{ row.identity.libraries }}
                </span>
              </div>
              </el-tooltip>
            </template>

            <template #cell-mounts="{ row }">
              <el-tooltip v-if="row.mounts" :content="mountText(row.mounts)" placement="top">
                <div class="state-cell">
                  <span class="mini-badge" :class="mountBadge(row.mounts)">{{ mountText(row.mounts) }}</span>
                  <span v-if="row.mounts.unreachable?.length" class="muted sub ellipsis">
                    不可达：{{ row.mounts.unreachable.join('、') }}
                  </span>
                </div>
              </el-tooltip>
              <span v-else class="muted">—</span>
            </template>

            <template #cell-libraries="{ row }">
              <div class="state-cell">
                <span class="muted sub">归它 {{ row.libraries_assigned }} 个</span>
                <span v-if="row.kind === 'ea'" class="muted sub">未分配 {{ row.libraries_unassigned }} 个</span>
              </div>
            </template>

            <template #cell-actions="{ row }">
              <!-- 一个入口：测试 / 设为当前 / 编辑 / 停用启用 / 删除 都在弹窗里（原来这行有 5 个按钮） -->
              <el-button size="small" plain @click="openManage(row)">管理</el-button>
            </template>

          </DataTable>

          <!-- 逐行的告警（挂载不可达 / 服不一致 / 连接失败…）：手机端在卡片下方，桌面端也能看全 -->
          <div v-if="entryRows.some((r) => r.warnings?.length)" class="row-warnings">
            <span v-for="r in entryRows.filter((x) => x.warnings?.length)" :key="r.id" class="warn-line">
              <AlertTriangle :size="13" /><b>{{ r.name }}：</b>{{ r.warnings.join('；') }}
            </span>
          </div>
        </section>
      </div>
    </template>

    <!-- ==================== 内容自动化（求片用） ==================== -->
    <template v-if="showContent">
      <div class="section-label">
        <span class="section-title">内容自动化（求片用）</span>
        <span class="muted">MoviePilot 负责找片、qB 负责下载；可以声明「全服共用」，多服接一套就够</span>
      </div>
      <div class="admin-card">
        <DataTable
          :rows="contentRows"
          :columns="contentColumns"
          :loading="loading"
          empty="还没有接 MoviePilot / qBittorrent：求片批准后就没办法把片子弄进来"
        >
          <template #cell-name="{ row }">
            <div class="name-cell">
              <span class="name">{{ row.name }}</span>
              <span v-if="row.remark" class="muted remark">{{ row.remark }}</span>
            </div>
          </template>
          <template #cell-kind_label="{ row }">
            <span class="mini-badge remote">{{ row.kind_label }}</span>
          </template>
          <template #cell-scope="{ row }">
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
              <span class="muted sub">{{ fmtDate(row.last_checked_at) }}</span>
            </div>
          </template>
          <template #cell-actions="{ row }">
            <!-- 一个入口：测试 / 编辑 / 停用启用 / 删除 都在弹窗里 -->
            <el-button size="small" plain @click="openManage(row)">管理</el-button>
          </template>
        </DataTable>
      </div>
    </template>

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
            <el-option v-for="r in realm.realms" :key="r.id" :label="r.name" :value="r.id" />
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

    <!--
      服务器管理（弹窗）：一台机器的全部事实（连接、节点认领、挂载体检、媒体库归属、告警）
      与全部动作放在一处。以前这些分散在带 tooltip 的列里，左边是 5 个按钮。
      动作做完弹窗不关，弹窗里的快照就地刷新。
    -->
    <el-dialog v-model="manage.visible" :title="`管理服务器「${manage.row?.name || ''}」`" width="580px">
      <div v-if="manage.row" class="mg-body">
        <div class="kv-list">
          <div class="kv-row"><span class="kv-key">名称</span>
            <span class="kv-value">
              {{ manage.row.name }}
              <span v-if="isEntryRow(manage.row) && manage.row.is_current_entry" class="mini-badge ok mg-gap">当前使用</span>
              <span v-if="!manage.row.is_enabled" class="mini-badge off mg-gap">已停用</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">类型 / 归属</span>
            <span class="kv-value">{{ manage.row.kind_label }} · {{ scopeText(manage.row) }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">地址</span>
            <span class="kv-value mono">{{ manage.row.url || '未填写' }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">连接</span>
            <span class="kv-value">
              <span class="mini-badge" :class="stateBadge(manage.row)">{{ stateText(manage.row) }}</span>
              <span class="mg-msg">
                {{ fmtDate(manage.row.last_checked_at) }}
                <template v-if="manage.row.last_check_message">· {{ manage.row.last_check_message }}</template>
              </span>
            </span>
          </div>
          <div v-if="isEntryRow(manage.row)" class="kv-row"><span class="kv-key">节点认领</span>
            <span class="kv-value">{{ nodeText(manage.row) }}</span>
          </div>
          <div v-if="isEntryRow(manage.row)" class="kv-row"><span class="kv-key">挂载体检（EA 视角）</span>
            <span class="kv-value">
              <span class="mini-badge" :class="mountBadge(manage.row.mounts)">{{ mountText(manage.row.mounts) }}</span>
              <span v-if="manage.row.mounts?.unreachable?.length" class="mg-msg">
                不可达：{{ manage.row.mounts.unreachable.join('、') }}
              </span>
            </span>
          </div>
          <div v-if="isEntryRow(manage.row)" class="kv-row"><span class="kv-key">媒体库归属</span>
            <span class="kv-value">
              归它 {{ manage.row.libraries_assigned }} 个
              <template v-if="manage.row.kind === 'ea'">· 未分配 {{ manage.row.libraries_unassigned }} 个</template>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">备注</span><span class="kv-value">{{ manage.row.remark || '—' }}</span></div>
        </div>

        <el-alert
          v-if="isEntryRow(manage.row) && manage.row.warnings?.length"
          type="warning"
          :closable="false"
          show-icon
        >
          <template #title>这台机器有需要处理的事项</template>
          <template #default>
            <ul class="mg-warn">
              <li v-for="w in manage.row.warnings" :key="w">{{ w }}</li>
            </ul>
          </template>
        </el-alert>

        <p class="mg-hint">
          <template v-if="isEntryRow(manage.row) && manage.row.is_entry">
            「设为当前」会让这个服的客户端改连这台（连接不通过时保持原入口）；
          </template>
          「停用」只是不再使用它，配置与凭证都保留；删除不可恢复。改地址与密钥进「编辑」。
        </p>
      </div>

      <template #footer>
        <div class="mg-footer">
          <el-button type="danger" plain :disabled="!manage.row" @click="manage.row && remove(manage.row)">
            <Trash2 :size="13" style="margin-right: 3px" />删除
          </el-button>
          <div class="mg-footer-right">
            <el-button @click="manage.visible = false">关闭</el-button>
            <template v-if="manage.row">
              <el-button :loading="busyId === manage.row.id" @click="runTest(manage.row)">
                <Wifi :size="13" style="margin-right: 3px" />测试连接
              </el-button>
              <!-- 「设为当前」只给出流入口（EA / 已有 Emby）：内容自动化那两段原先也没有这个动作 -->
              <el-button
                v-if="isEntryRow(manage.row) && manage.row.is_entry && manage.row.activatable && !manage.row.is_current_entry"
                type="primary"
                plain
                :loading="busyId === manage.row.id"
                @click="runActivate(manage.row)"
              >
                <CheckCircle2 :size="13" style="margin-right: 3px" />设为当前
              </el-button>
              <el-button :loading="busyId === manage.row.id" @click="runToggle(manage.row)">
                {{ manage.row.is_enabled ? '停用' : '启用' }}
              </el-button>
              <el-button type="primary" @click="editFromManage(manage.row)">
                <Pencil :size="13" style="margin-right: 3px" />编辑
              </el-button>
            </template>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 管理弹窗：详情用全局 .kv-list，只补告警列表与页脚布局 */
.mg-body { display: flex; flex-direction: column; gap: 12px; }
.mg-body .kv-row .kv-value { text-align: left; }
.mg-gap { margin-left: 6px; }
.mg-msg { display: block; margin-top: 3px; font-size: var(--font-size-xs); color: var(--text-muted); }
.mg-warn { margin: 0; padding-left: 18px; font-size: var(--font-size-xs); line-height: 1.8; }
.mg-hint {
  margin: 0;
  font-size: var(--font-size-xs);
  line-height: 1.8;
  color: var(--text-muted);
  background: var(--bg-inset);
  border-radius: var(--radius-md);
  padding: 10px 12px;
}
.mg-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.mg-footer-right { display: flex; gap: 8px; flex-wrap: wrap; }

/* ==================== 汇总条 ==================== */
.ov-totals {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 22px;
  padding: 12px 16px;
  margin-bottom: 14px;
}
.ov-item { display: flex; flex-direction: column; gap: 1px; }
.ov-item b { font-size: 20px; font-weight: var(--font-weight-semibold); color: var(--text-primary); font-variant-numeric: tabular-nums; }
.ov-item b.ok { color: var(--success); }
.ov-item b.warn { color: var(--warning); }
.ov-item b.danger { color: var(--danger); }
.ov-item em { font-style: normal; font-size: var(--font-size-xs); color: var(--text-muted); }
.ov-scope { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; }
.ov-scope-label { font-size: var(--font-size-xs); color: var(--text-muted); }
.scope-realm { width: 150px; }

/* 顶部相邻页入口：交付链上的下一站直接点过去，不用回侧边栏找 */
.toolbar-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  color: var(--text-tertiary);
  font-size: var(--font-size-xs);
  text-decoration: none;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}
.toolbar-link:hover { border-color: var(--primary-border); color: var(--text-primary); }

/* ==================== 类型卡片 ==================== */
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

/* ==================== 按服的入口卡片 ==================== */
.realm-stack { display: flex; flex-direction: column; gap: 14px; }
.realm-card { padding: 14px 16px 16px; }
.realm-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}
.realm-icon {
  width: 30px; height: 30px; display: grid; place-items: center; flex-shrink: 0;
  border-radius: 9px; background: var(--primary-bg); color: var(--primary);
}
.realm-name {
  display: flex; align-items: center; gap: 6px;
  color: var(--text-primary); font-weight: var(--font-weight-semibold);
}
.realm-slug { font-style: normal; font-size: var(--font-size-xs); color: var(--text-muted); }
.realm-entry { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.realm-url { font-size: var(--font-size-xs); word-break: break-all; }
.realm-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.link { font-size: var(--font-size-xs); text-decoration: none; }
.link:hover { color: var(--primary); }

/* ==================== 告警 ==================== */
.warn-box, .row-warnings {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}
.row-warnings { margin: 10px 0 0; }
.warn-line {
  display: flex; align-items: flex-start; gap: 6px;
  padding: 7px 10px;
  border-radius: var(--radius-md);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: var(--font-size-xs);
  line-height: 1.6;
}
.warn-line svg { flex-shrink: 0; margin-top: 2px; }

/* ==================== 单元格 ==================== */
.name-cell { display: flex; flex-direction: column; gap: 3px; }
.name-cell .name { color: var(--text-primary); font-weight: var(--font-weight-medium); }
.badges { display: flex; flex-wrap: wrap; gap: 4px; }
.remark { font-size: var(--font-size-xs); }
.url { color: var(--text-secondary); word-break: break-all; font-size: var(--font-size-sm); }
.state-cell { display: flex; flex-direction: column; gap: 3px; }
.sub { font-size: var(--font-size-xs); }
.ellipsis { display: block; max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section-label {
  display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
  margin: 20px 0 10px;
}
.section-title { color: var(--text-primary); font-weight: var(--font-weight-semibold); }
.section-label .muted { font-size: var(--font-size-xs); }
.field-help { color: var(--text-muted); font-size: var(--font-size-xs); margin: 5px 0 0; line-height: 1.6; }
.probe { padding: 9px 11px; border-radius: var(--radius-md); font-size: var(--font-size-sm); margin-top: 4px; }
.probe.ok { color: var(--success); background: var(--success-bg); }
.probe.bad { color: var(--danger); background: var(--danger-bg); }

@media (max-width: 1100px) { .kind-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) {
  .kind-grid { grid-template-columns: 1fr; }
  .realm-actions { margin-left: 0; width: 100%; }
  .ov-scope { margin-left: 0; }
}
</style>
