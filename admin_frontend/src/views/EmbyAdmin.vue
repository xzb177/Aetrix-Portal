<script setup lang="ts">
/**
 * 媒体库管理：库列表/创建/扫描/删除 + 刮削策略 + 平台虚拟媒体库 + 图片修复队列
 * + 在线会话监控/强制下线 + 停止全部转码
 *
 * v2.6.11：会话表改用 DataTable（手机卡片）；媒体库卡片的「挂载 / 刮削策略 / 115 账号」
 * 在窄屏改为「标签在上、控件在下」，不再把中文标签挤成竖排两行；页面里的硬编码灰度
 * 全部换成主题令牌。
 *
 * v2.6.20：多服 / 多机部署——每个库都能指定「归属服」与「归属播放节点」（未指定 = 所有服、
 * 所有节点可见，由面板扫描）；已分配的库只有那台 EA 向客户端展示、也只有它会扫描。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import {
  Delete, Film, FolderPlus, HardDrive, History, ImagePlus, RefreshCw, ScanSearch, Server,
  Settings2, Square, Wand2, X,
} from 'lucide-vue-next'
import {
  cancelQueuedScan,
  createLibrary,
  deleteLibrary,
  fetchLibraries,
  fetchLibraryCover,
  fetchLibraryScans,
  fetchMounts,
  fetchPan115Accounts,
  fetchReachability,
  fetchRepairQueue,
  fetchScanQueue,
  fetchServers,
  fetchSessions,
  fetchTmdbKeys,
  generateVirtualLibraries,
  removeLibraryCover,
  rescrapeItem,
  rescrapeLibrary,
  runRepairQueue,
  scanLibrary,
  saveTmdbKeys,
  testTmdbKeys,
  stopAllTranscodes,
  stopSession,
  updateLibrary,
  uploadLibraryCover,
} from '@/api/admin'
import type { TmdbKeysStatus, TmdbTestResult } from '@/api/admin'
import type {
  EmbyLibrary,
  EmbyPlaybackReachability,
  EmbyReachabilityReport,
  EmbyScanQueue,
  EmbyScanResult,
  EmbyScanRun,
  EmbyScanSource,
  EmbyScanStatus,
  EmbyScanTask,
  EmbySessionRow,
  Pan115Account,
  RemoteServerRow,
  StorageMount,
} from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import './EmbyAdmin.css'
import type { DataColumn } from '@/components/DataTable.vue'

const realm = useRealmStore()
const libraries = ref<EmbyLibrary[]>([])
const sessions = ref<EmbySessionRow[]>([])
const panAccounts = ref<Pan115Account[]>([])
const mounts = ref<StorageMount[]>([])
/** 可分配的播放节点（面板里 kind=ea 的服务器）：一个服可以有多台 */
const nodes = ref<RemoteServerRow[]>([])
const loading = ref(false)
const repairCount = ref(0)
const virtualLoading = ref(false)
const coverUrls = ref<Record<number, string>>({})
const coverUploading = ref<Record<number, boolean>>({})
let coverLoadVersion = 0

const settingsVisible = ref(false)
const settingsTarget = ref<EmbyLibrary | null>(null)

// 扫描流水（最近若干轮）：抽屉里看「是不是每轮都在失败」
const scanDrawer = ref(false)
const scanLoading = ref(false)
const scanTarget = ref<EmbyLibrary | null>(null)
const scanRuns = ref<EmbyScanRun[]>([])
const scanKeep = ref(0)

// 扫描队列（v2.27.0）：同一远程挂载同时只跑一个扫描，其它库排队。
// 只靠「每 1.5 秒刷一次媒体库列表」看不出排队原因（在等哪个挂载、排第几位），
// 所以队列单独轮询一份快照。
const scanQueue = ref<EmbyScanQueue | null>(null)
let queueTimer: number | undefined
let queueWasBusy = false

// 播放可达性（v2.28.0）：面板扫描正常 ≠ 出流的机器拿得到内容。
// 分离部署（EM 控制面 + EA 数据面 + 共享存储）下这是最该先看的一页：
// 本机路径 / local 挂载的库在 EA 出流时读不到，客户端只会看到条目的 404。
const reachability = ref<EmbyReachabilityReport | null>(null)

/** 归属服选项：默认服 + 已建的其他服 */
const realmOptions = computed(() => realm.realms)

function nodeLabel(n: RemoteServerRow): string {
  const state = n.last_check_ok === true ? '在线' : n.last_check_ok === false ? '未通过' : '未体检'
  return `${n.name}（${state}）`
}

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
  // 多服 / 多机：留空 = 当前服 / 未分配节点
  realm_id: null as number | null,
  node_id: null as number | null,
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
    // 归属服下拉要用服的清单（Layout 已加载过就不重复请求）
    if (!realm.loaded) realm.load().catch(() => undefined)
    const [l, s, r, a, m, srv, reach] = await Promise.all([
      fetchLibraries(),
      fetchSessions(),
      fetchRepairQueue().catch(() => ({ total: 0, items: [] })),
      fetchPan115Accounts().catch(() => ({ accounts: [], env_cookie_configured: false })),
      fetchMounts().catch(() => ({ mounts: [], mount_types: [] })),
      fetchServers().catch(() => null),
      fetchReachability().catch(() => null),
      loadTmdbStatus().catch(() => undefined),
    ])
    // mount_ids 兼容旧响应（老后端没有这个字段）
    libraries.value = l.libraries.map((lib) => ({ ...lib, mount_ids: lib.mount_ids || [] }))
    void loadCoverImages(libraries.value)
    sessions.value = s.sessions
    repairCount.value = r.total
    panAccounts.value = a.accounts
    mounts.value = m.mounts
    nodes.value = (srv?.servers || []).filter((x) => x.kind === 'ea')
    reachability.value = reach
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  pollQueue()
  // 队列与进度都是秒级的东西：页面开着就轮询（空闲时请求极小，且不刷整页列表）
  queueTimer = window.setInterval(pollQueue, 3000)
})

onUnmounted(() => {
  if (queueTimer) window.clearInterval(queueTimer)
  Object.values(coverUrls.value).forEach((url) => URL.revokeObjectURL(url))
})

async function loadCoverImages(rows: EmbyLibrary[]) {
  const version = ++coverLoadVersion
  Object.values(coverUrls.value).forEach((url) => URL.revokeObjectURL(url))
  coverUrls.value = {}
  await Promise.all(rows.filter((lib) => lib.cover_url).map(async (lib) => {
    try {
      const blob = await fetchLibraryCover(lib.id)
      if (version !== coverLoadVersion) {
        URL.revokeObjectURL(URL.createObjectURL(blob))
        return
      }
      coverUrls.value[lib.id] = URL.createObjectURL(blob)
    } catch {
      // 封面是可选增强；读取失败不影响媒体库卡片其余信息
    }
  }))
}

function replaceCoverImage(id: number, blob: Blob) {
  const old = coverUrls.value[id]
  if (old) URL.revokeObjectURL(old)
  coverUrls.value[id] = URL.createObjectURL(blob)
}

async function uploadCover(l: EmbyLibrary, file: File) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    ElMessage.warning('封面仅支持 JPG、PNG 或 WebP 图片')
    return
  }
  if (file.size > 8 * 1024 * 1024) {
    ElMessage.warning('封面图片不能超过 8 MB')
    return
  }
  coverUploading.value[l.id] = true
  try {
    const result = await uploadLibraryCover(l.id, file)
    replaceCoverImage(l.id, await fetchLibraryCover(l.id))
    l.cover_url = result.cover_url
    ElMessage.success('媒体库封面已更新')
  } finally {
    coverUploading.value[l.id] = false
  }
}

function requestCoverUpload(l: EmbyLibrary, options: UploadRequestOptions) {
  return uploadCover(l, options.file)
}

async function removeCover(l: EmbyLibrary) {
  await removeLibraryCover(l.id)
  const old = coverUrls.value[l.id]
  if (old) URL.revokeObjectURL(old)
  delete coverUrls.value[l.id]
  l.cover_url = null
  ElMessage.success('媒体库封面已移除')
}

function openSettings(l: EmbyLibrary) {
  settingsTarget.value = l
  settingsVisible.value = true
}

async function savePolicy(l: EmbyLibrary) {
  await updateLibrary(l.id, { scrape_policy: l.scrape_policy })
  ElMessage.success(`「${l.name}」刮削策略已保存（下次扫描生效）`)
}

async function saveAccount115(l: EmbyLibrary) {
  // 传 null 表示解绑（回退默认账号）；undefined 会被 axios 丢掉，等于不改
  await updateLibrary(l.id, { account_115_id: l.account_115_id ?? null })
  ElMessage.success(`「${l.name}」115 账号绑定已更新`)
}

/** 绑定 / 解绑存储挂载（扫描时与「路径」一起遍历） */
async function saveMounts(l: EmbyLibrary) {
  await updateLibrary(l.id, { mount_ids: l.mount_ids ?? [] })
  ElMessage.success(`「${l.name}」挂载绑定已更新（重新扫描后生效）`)
}

/** 归属节点：决定了「谁向客户端展示这个库、谁来扫描它」 */
async function saveNode(l: EmbyLibrary) {
  await updateLibrary(l.id, { node_id: l.node_id ?? null })
  const node = nodes.value.find((n) => n.id === l.node_id)
  ElMessage.success(node
    ? `「${l.name}」改由「${node.name}」负责（那台机器看不到这个库的条目时检查它的存储）`
    : `「${l.name}」已改为未分配：所有节点可见、由面板扫描`)
  load()
}

/** 归属服：内容隔离的边界，跨服移动等于把内容交给另一个服 */
async function saveRealm(l: EmbyLibrary) {
  await updateLibrary(l.id, { realm_id: l.realm_id ?? null })
  ElMessage.success(`「${l.name}」归属服已更新`)
  load()
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
  const res = await runRepairQueue()
  const merged = res.already?.length || 0
  ElMessage.success(`已把 ${res.libraries.length} 个库加入扫描队列${merged ? `（另 ${merged} 个已在队列中，已合并）` : ''}`)
  await pollQueue()
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
    realm_id: form.value.realm_id ?? undefined,
    node_id: form.value.node_id ?? undefined,
  })
  ElMessage.success('媒体库已创建')
  createVisible.value = false
  form.value = {
    name: '', collection_type: 'movies', paths: '', mount_ids: [], scrape_policy: 'missing_only',
    realm_id: null, node_id: null,
  }
  load()
}

async function scan(l: EmbyLibrary) {
  const res = await scanLibrary(l.id)
  // 三件事要分清（v2.27.0）：已开扫 / 排在队列第几位（在等哪个挂载）/ 重复点击被合并
  if (res.already) ElMessage.info(`「${l.name}」${res.message || '已在扫描 / 已在队列中'}`)
  else if (res.started === false) ElMessage.warning(`「${l.name}」${res.message || '已加入扫描队列'}`)
  else ElMessage.success(`「${l.name}」扫描已启动`)
  await pollQueue()
  setTimeout(load, 1500)
}

// ==================== 元数据与刮削 ====================
const tmdbStatus = ref<TmdbKeysStatus | null>(null)
const tmdbKeysInput = ref('')
const tmdbSaving = ref(false)
const tmdbTesting = ref(false)
const tmdbTestResults = ref<TmdbTestResult[]>([])
const rescrapeItemId = ref('')
const rescrapeItemLoading = ref(false)
const rescrapeItemNotes = ref<string[]>([])
const rescrapeVisible = ref(false)
const rescrapeTarget = ref<EmbyLibrary | null>(null)
const rescrapePolicy = ref<'missing_only' | 'all'>('missing_only')
const rescrapeLoading = ref(false)

const tmdbStatusText = computed(() => {
  if (!tmdbStatus.value) return '加载中…'
  if (!tmdbStatus.value.configured) return '未配置'
  return `已配置 ${tmdbStatus.value.count} 个（${tmdbStatus.value.source === 'env' ? '环境变量' : '后台填写'}）`
})

async function loadTmdbStatus() {
  try {
    tmdbStatus.value = await fetchTmdbKeys()
  } catch {
    tmdbStatus.value = null // 出错不挡页面其它内容
  }
}

async function saveTmdbKeysAction() {
  if (!tmdbKeysInput.value.trim()) {
    ElMessage.warning('请先填写 Key')
    return
  }
  tmdbSaving.value = true
  try {
    const res = await saveTmdbKeys(tmdbKeysInput.value)
    tmdbKeysInput.value = ''
    tmdbTestResults.value = []
    ElMessage.success(`已保存 ${res.saved} 个 Key，${res.source === 'env' ? '当前生效的仍是环境变量' : '已立即生效'}`)
    await loadTmdbStatus()
  } finally {
    tmdbSaving.value = false
  }
}

async function testTmdbKeysAction() {
  tmdbTesting.value = true
  try {
    // 输入框有内容就测候选 key，否则测当前生效的 key
    const res = await testTmdbKeys(tmdbKeysInput.value.trim() || undefined)
    tmdbTestResults.value = res.results
    const ok = res.results.filter((r) => r.ok).length
    if (ok === res.results.length && res.results.length) ElMessage.success('全部 Key 有效')
    else if (!res.results.length) ElMessage.warning('没有可测试的 Key')
  } finally {
    tmdbTesting.value = false
  }
}

async function doRescrapeItem() {
  const id = Number(rescrapeItemId.value)
  if (!id) {
    ElMessage.warning('请填写条目 ID')
    return
  }
  rescrapeItemLoading.value = true
  try {
    const res = await rescrapeItem(id)
    const changed = Object.keys(res.summary.changed)
    rescrapeItemNotes.value = [
      `「${res.item.name}」：${res.summary.notes.join('；')}`,
      ...(changed.length ? [`变更字段：${changed.join('、')}`] : ['无字段变更']),
    ]
    ElMessage.success('已刷新')
  } finally {
    rescrapeItemLoading.value = false
  }
}

function openRescrape(l: EmbyLibrary) {
  rescrapeTarget.value = l
  rescrapePolicy.value = 'missing_only'
  rescrapeVisible.value = true
}

async function confirmRescrape() {
  if (!rescrapeTarget.value) return
  rescrapeLoading.value = true
  try {
    const res = await rescrapeLibrary(rescrapeTarget.value.id, rescrapePolicy.value)
    rescrapeVisible.value = false
    if (res.already) ElMessage.info(`「${rescrapeTarget.value.name}」${res.message}`)
    else ElMessage.success(`「${rescrapeTarget.value.name}」${res.message}`)
    await pollQueue()
  } finally {
    rescrapeLoading.value = false
  }
}

/** 取消一个还在排队的扫描（正在跑的取不了：停在中途会留下半个库的状态） */
async function cancelQueued(t: EmbyScanTask) {
  await cancelQueuedScan(t.library_id)
  ElMessage.success(`已取消「${t.name}」的排队`)
  await pollQueue()
}

async function removeLib(l: EmbyLibrary) {
  await ElMessageBox.confirm(
    `删除媒体库「${l.name}」将同时移除其索引条目（不删除磁盘文件），确定吗？`,
    '确认删除',
    { type: 'warning' }
  )
  await deleteLibrary(l.id)
  if (settingsTarget.value?.id === l.id) {
    settingsVisible.value = false
    settingsTarget.value = null
  }
  if (coverUrls.value[l.id]) {
    URL.revokeObjectURL(coverUrls.value[l.id])
    delete coverUrls.value[l.id]
  }
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

// ---- 最近一次扫描的结果（后端已落库，刷新页面也还在）----

/** 扫描结果徽标：没扫过返回 null（不占位） */
function scanBadge(l: EmbyLibrary): { text: string; cls: string } | null {
  const s: EmbyScanResult | null | undefined = l.last_scan
  if (!s) return null
  if (s.status === 'running') return { text: '上次扫描未完成', cls: 'scanning' }
  if (s.status === 'failed') return { text: '扫描失败', cls: 'danger' }
  if (s.status === 'partial') return { text: '来源不完整', cls: 'warn' }
  return { text: '扫描正常', cls: 'ok' }
}

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`
}

/** 部分失败 / 异常的原因（来源读不到时的 path + 原因） */
function scanError(l: EmbyLibrary): string {
  const s = l.last_scan
  if (!s || (s.status !== 'failed' && s.status !== 'partial')) return ''
  return s.error || (s.failed_roots || []).join('；')
}

const SCAN_STATUS_META: Record<EmbyScanStatus, { text: string; cls: string }> = {
  running: { text: '进行中', cls: 'scanning' },
  success: { text: '正常', cls: 'ok' },
  partial: { text: '来源不完整', cls: 'warn' },
  failed: { text: '失败', cls: 'danger' },
}

const SCAN_TRIGGER_LABELS: Record<string, string> = {
  manual: '面板',
  client: '客户端',
  node: '归属节点',
  repair: '修复队列',
}

function statusMeta(status: EmbyScanStatus): { text: string; cls: string } {
  return SCAN_STATUS_META[status] || { text: status, cls: 'muted' }
}

function triggerLabel(trigger: string | null): string {
  return trigger ? SCAN_TRIGGER_LABELS[trigger] || trigger : '—'
}

/** 流水里一轮的增量摘要（与卡片上的口径一致，失败时只显示原因） */
function runSummary(r: EmbyScanRun): string {
  return [`+${r.added}`, `~${r.updated}`, `-${r.removed}`].join(' / ')
}

// ---- 按来源拆分（哪条来源扫到了什么）----

/** 悬停明细：一条来源一行（读不到 / 0 个文件 / 文件数 + 增量） */
function sourcesDetail(list: EmbyScanSource[] | undefined): string {
  return (list || []).map((s) => {
    if (s.error) return `${s.label}：读取失败 —— ${s.error}`
    if (!s.files) return `${s.label}：0 个文件`
    const bits = [`${s.files} 个文件`, `新增 ${s.added}`, `更新 ${s.updated}`]
    if (s.probed) bits.push(`探测 ${s.probed}`)
    if (s.unchanged) bits.push(`未变 ${s.unchanged}`)
    return `${s.label}：${bits.join(' / ')}`
  }).join('\n')
}

/** 来源列：条数 + 有几条一条文件都没扫到 */
function sourcesLabel(list: EmbyScanSource[] | undefined): string {
  if (!list?.length) return '—'
  const empty = emptySourceCount(list)
  return empty ? `${list.length} 条 · ${empty} 空` : `${list.length} 条`
}

/** 有没有「别的来源有文件、这条一条都没有」的来源（全空是整库为空，另当别论） */
function emptySourceCount(list: EmbyScanSource[] | undefined): number {
  const sources = list || []
  if (!sources.some((s) => s.files > 0)) return 0
  return sources.filter((s) => !s.error && !s.files).length
}

// ---- 扫描队列（v2.27.0）：排队中的、在跑的、刚跑完的 ----

/** 轮询队列快照；从「忙」变「闲」时顺手把列表刷一遍（『最近一次结果』是落库数据，不会自己变） */
async function pollQueue() {
  try {
    const q = await fetchScanQueue()
    scanQueue.value = q
    const busy = q.running.length > 0 || q.waiting.length > 0
    if (queueWasBusy && !busy) load()
    queueWasBusy = busy
  } catch {
    // 轮询失败不打扰（比如正在重新登录）：下一次接着来
  }
}

const queueBusy = computed(() => {
  const q = scanQueue.value
  return !!q && (q.running.length > 0 || q.waiting.length > 0)
})

/** 队列里还没结束的扫描：库 id → 任务（卡片直接看这个，不用刷整页） */
const liveTasks = computed(() => {
  const map = new Map<number, EmbyScanTask>()
  for (const t of [...(scanQueue.value?.running || []), ...(scanQueue.value?.waiting || [])]) {
    map.set(t.library_id, t)
  }
  return map
})

const queueHistory = computed(() => (scanQueue.value?.history || []).slice(0, 5))
const queueHasContent = computed(() => !!scanQueue.value && (queueBusy.value || queueHistory.value.length > 0))

function liveFor(l: EmbyLibrary): EmbyScanTask | null {
  return liveTasks.value.get(l.id) || null
}

/** 挂载名字：面板写得出「在等谁」，不让管理员去存储来源页对 id */
function mountName(id: number): string {
  return scanQueue.value?.mount_names?.[String(id)] || `挂载 #${id}`
}

/** 一条任务的状态徽标（排队中带位置，扫描中带阶段） */
function taskBadge(t: EmbyScanTask): { text: string; cls: string } {
  if (t.state === 'queued') return { text: `排队中（第 ${t.position ?? '-'} 位）`, cls: 'muted' }
  if (t.state === 'running') return { text: `扫描中 · ${t.progress?.phase_label || '准备中'}`, cls: 'scanning' }
  if (t.state === 'canceled') return { text: '已取消', cls: 'muted' }
  if (t.state === 'failed' || t.result === 'failed') return { text: '失败', cls: 'danger' }
  if (t.result === 'partial') return { text: '完成（来源不完整）', cls: 'warn' }
  return { text: '完成', cls: 'ok' }
}

/** 为什么在等：同一远程挂载被别的库占着就写明是哪个 */
function waitingText(t: EmbyScanTask): string {
  const mounts = (t.waiting_for || []).map(mountName)
  if (mounts.length) return `在等挂载：${mounts.join('、')}`
  return (t.position ?? 1) > 1 ? '前面还有扫描在跑' : '等待调度'
}

/** 进度一行：已处理 / 已发现 / 耗时（扫到哪了一眼可见，不用看容器 CPU） */
function progressLine(t: EmbyScanTask): string {
  const p = t.progress
  if (!p) return ''
  const parts = [`已处理 ${p.processed}`]
  if (p.enumerated) parts.push(`已发现 ${p.enumerated}`)
  if (p.elapsed_ms) parts.push(fmtDuration(p.elapsed_ms))
  if (p.remote_lists) parts.push(`远程请求 ${p.remote_lists}`)
  return parts.join(' · ')
}

/** 卡片徽标：队列优先（排队中 / 扫描中 + 阶段）→ 归属节点在扫 → 上一次的结果 */
function cardBadge(l: EmbyLibrary): { text: string; cls: string } | null {
  const task = liveFor(l)
  if (task) return taskBadge(task)
  if (l.scan_live?.state === 'running') return { text: '扫描中（归属节点）', cls: 'scanning' }
  if (l.is_scanning) return { text: '扫描中…', cls: 'scanning' }
  return scanBadge(l)
}

/** 卡片的实时一行：排队原因，或「已处理 N · 当前目录」 */
function cardLiveHint(l: EmbyLibrary): string {
  const task = liveFor(l)
  if (!task) return l.scan_live?.state === 'running' ? (l.scan_live.message || '') : ''
  if (task.state === 'queued') return waitingText(task)
  return [progressLine(task), task.progress?.current].filter(Boolean).join(' · ')
}

function queuedSince(t: EmbyScanTask): string {
  return t.queued_ms ? `等了 ${fmtDuration(t.queued_ms)}` : ''
}

// ---- 播放可达性（v2.28.0）：面板扫描正常 ≠ 出流的那台机器拿得到内容 ----

/** 一条库的可达性提示（ok 不占地方，只提示 warn / bad） */
function libReach(l: EmbyLibrary): EmbyPlaybackReachability | null {
  const verdict = l.playback
  return verdict && verdict.level !== 'ok' ? verdict : null
}

const reachProblems = computed(() => (reachability.value?.libraries || []).filter((i) => i.level !== 'ok'))
/** 顶部横幅：只有真的有问题（或有待确认项）才占版面 */
const reachHasContent = computed(() => {
  const r = reachability.value
  return !!r && (r.level !== 'ok' || reachProblems.value.length > 0)
})

function reachCls(level: string): string {
  return level === 'bad' ? 'danger' : level === 'warn' ? 'warn' : 'ok'
}

function reachText(level: string): string {
  return { bad: '读不到', warn: '待确认', ok: '可达' }[level] || level
}

/** 卡片提示的悬停文案：原因 + 改法（卡片上只放一句，详情靠悬停） */
function reachTitle(l: EmbyLibrary): string {
  const verdict = libReach(l)
  return [verdict?.message, verdict?.fix].filter(Boolean).join(' ｜ ')
}

/** 横幅第一行的事实：谁在出流、面板协议面开着吗、用户该连哪个地址、EA 体检什么时候拉的 */
function reachFacts(): string[] {
  const r = reachability.value
  if (!r) return []
  const facts = [r.playback.label]
  facts.push(r.playback.gateway_enabled ? '面板协议面：开' : '面板协议面：关（分离部署）')
  facts.push(clientUrlFact(r))
  facts.push(r.ea_health_at ? `EA 体检：${fmtDate(r.ea_health_at)}` : 'EA 体检：还没拉过')
  return facts
}

/**
 * 用户该连哪个地址（v2.32.0）
 *
 * 还没配任何入口地址时（client_url_source = none）后端给的是空串：这时候用户该连的就是
 * **管理员此刻访问面板的这个地址**（面板与接口同源），所以直接报浏览器自己的 origin，
 * 而不是把写死的 localhost 摆在用户端地址上、再报一条红。
 * 配过地址（服地址 / 服务入口 / 环境变量）就照配置显示。
 */
function clientUrlFact(r: EmbyReachabilityReport): string {
  if (r.playback.client_url) return `用户端地址：${r.playback.client_url}`
  return `用户端地址：${window.location.origin}（按当前访问地址）`
}



// ---- 卡片facts：这个库由谁扫、内容从哪来、有多少条目（不用进库再点一层）----

/** 服务：归属节点（EA）在扫；没指定就是面板自己扫 */
function serviceFact(l: EmbyLibrary): { text: string; warn: boolean } {
  if (l.node_name) {
    const label = l.realm_name ? `${l.node_name}（${l.realm_name}）` : l.node_name
    return { text: label, warn: l.node_online === false }
  }
  if (l.realm_name) return { text: `面板 · ${l.realm_name}`, warn: false }
  return { text: '面板扫描', warn: false }
}

/** 来源：几条路径 + 几个挂载，后面直接跟「读不到 / 为空」 */
function sourceFact(l: EmbyLibrary): { text: string; warn: boolean } {
  const total = (l.paths?.length || 0) + (l.mount_ids?.length || 0)
  if (!total) return { text: l.is_virtual ? '虚拟库（无来源）' : '未配来源', warn: !l.is_virtual }
  const sources = l.last_scan?.sources || []
  const unavailable = sources.filter((s) => s.kind === 'unavailable').length
  const empty = emptySourceCount(sources)
  const parts = [`来源 ${total}`]
  if (unavailable) parts.push(`${unavailable} 条读不到`)
  else if (empty) parts.push(`${empty} 条为空`)
  return { text: parts.join(' · '), warn: unavailable > 0 || empty > 0 }
}

const scanColumns: DataColumn[] = [
  { key: 'started_at', label: '开始', width: 140, mobile: 'title' },
  { key: 'status', label: '结果', width: 110 },
  { key: 'trigger', label: '触发', width: 90 },
  { key: 'summary', label: '新增/更新/删除', width: 150 },
  { key: 'sources', label: '来源', width: 110 },
  { key: 'duration', label: '耗时', width: 90 },
  { key: 'error', label: '原因', minWidth: 160 },
]

async function openScans(l: EmbyLibrary) {
  scanTarget.value = l
  scanDrawer.value = true
  scanLoading.value = true
  scanRuns.value = []
  try {
    const res = await fetchLibraryScans(l.id)
    scanRuns.value = res.runs
    scanKeep.value = res.keep
  } catch {
    ElMessage.error('读取扫描记录失败')
  } finally {
    scanLoading.value = false
  }
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
        <h1 class="admin-page-title">媒体库</h1>
        <p class="admin-page-subtitle">上传封面，快速识别媒体库；来源与节点设置集中到「设置」中维护</p>
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

    <!--
      播放可达性（v2.28.0）：面板扫描没问题 ≠ 出流的机器拿得到内容。
      分离部署（EM 控制面 + EA 数据面 + 共享 WebDAV/rclone）下，内容只存在于面板那台机器
      上时（本机目录 / local 挂载），客户端会看得到条目却播不了；这里提前说清楚。
    -->
    <div v-if="reachHasContent && reachability" class="admin-card reach-card">
      <div class="card-header">
        <h2>
          播放可达性
          <span class="mini-badge" :class="reachCls(reachability.level)">
            {{ reachText(reachability.level) }}
          </span>
        </h2>
        <div class="queue-facts">
          <span v-for="f in reachFacts()" :key="f" class="fact">{{ f }}</span>
        </div>
      </div>

      <!-- 用户端该连哪个地址（分离部署最容易配错的一处） -->
      <div v-if="reachability.client_endpoint.level !== 'ok'" class="reach-row">
        <span class="mini-badge" :class="reachCls(reachability.client_endpoint.level)">
          {{ reachText(reachability.client_endpoint.level) }}
        </span>
        <div class="reach-row-body">
          <div class="reach-row-title">用户端地址</div>
          <div class="queue-row-sub" :class="{ danger: reachability.client_endpoint.level === 'bad', warn: reachability.client_endpoint.level === 'warn' }">
            {{ reachability.client_endpoint.message }}
          </div>
          <div v-if="reachability.client_endpoint.fix" class="reach-row-fix">
            {{ reachability.client_endpoint.fix }}
          </div>
        </div>
      </div>

      <!-- 逐库：哪个库在出流的那台机器上拿不到内容、怎么改 -->
      <div v-for="p in reachProblems" :key="'reach-' + p.library_id" class="reach-row">
        <span class="mini-badge" :class="reachCls(p.level)">{{ reachText(p.level) }}</span>
        <div class="reach-row-body">
          <div class="reach-row-title">
            <span class="reach-name">{{ p.library_name }}</span>
            <span class="reach-node">{{ p.targets.length ? p.targets.join('、') : p.playback_label }}</span>
          </div>
          <div class="queue-row-sub" :class="{ danger: p.level === 'bad', warn: p.level === 'warn' }">
            {{ p.message }}
          </div>
          <div v-if="p.fix" class="reach-row-fix">{{ p.fix }}</div>
        </div>
      </div>
    </div>

    <!-- 扫描队列：同一远程挂载同时只跑一个扫描，其它库在这里排队（不再让管理员自己控并发） -->
    <div v-if="queueHasContent" class="admin-card queue-card">
      <div class="card-header">
        <h2>扫描队列</h2>
        <div class="queue-facts">
          <span class="fact">并发上限 {{ scanQueue?.max_parallel }}</span>
          <span class="fact">{{ scanQueue?.mount_serial ? '同一远程挂载串行' : '挂载串行已关闭' }}</span>
          <span class="fact" title="本轮真实远程请求 / 内存复用 / 在飞请求">
            远程请求 {{ scanQueue?.remote.lists }} · 复用 {{ scanQueue?.remote.reused }}
            · 在飞 {{ scanQueue?.remote.inflight }}
          </span>
        </div>
      </div>

      <div class="queue-grid">
        <div class="queue-col">
          <div class="queue-col-title">正在扫描（{{ scanQueue?.running.length || 0 }}）</div>
          <div v-for="t in scanQueue?.running" :key="'run-' + t.library_id" class="queue-row">
            <div class="queue-row-head">
              <span class="queue-name">{{ t.name }}</span>
              <span class="mini-badge scanning">{{ t.progress?.phase_label || '准备中' }}</span>
            </div>
            <div class="queue-row-sub mono">{{ progressLine(t) || '刚刚开始' }}</div>
            <div v-if="t.progress?.current" class="queue-row-sub mono" :title="t.progress.current">
              {{ t.progress.current }}
            </div>
          </div>
          <div v-if="!scanQueue?.running.length" class="queue-empty">没有正在跑的扫描</div>
        </div>

        <div class="queue-col">
          <div class="queue-col-title">排队中（{{ scanQueue?.waiting.length || 0 }}）</div>
          <div v-for="t in scanQueue?.waiting" :key="'wait-' + t.library_id" class="queue-row">
            <div class="queue-row-head">
              <span class="queue-name">{{ t.name }}</span>
              <span class="mini-badge muted">第 {{ t.position ?? '-' }} 位</span>
              <el-button
                size="small"
                text
                :icon="X"
                @click="cancelQueued(t)"
              >取消</el-button>
            </div>
            <div class="queue-row-sub warn">{{ waitingText(t) }}</div>
            <div class="queue-row-sub mono">
              {{ [queuedSince(t), triggerLabel(t.trigger)].filter(Boolean).join(' · ') }}
            </div>
          </div>
          <div v-if="!scanQueue?.waiting.length" class="queue-empty">没有排队的扫描</div>
        </div>

        <div class="queue-col">
          <div class="queue-col-title">最近完成</div>
          <div v-for="t in queueHistory" :key="'done-' + t.library_id + t.requested_at" class="queue-row">
            <div class="queue-row-head">
              <span class="queue-name">{{ t.name }}</span>
              <span class="mini-badge" :class="taskBadge(t).cls">{{ taskBadge(t).text }}</span>
            </div>
            <div class="queue-row-sub mono">
              {{ [t.duration_ms != null ? `耗时 ${fmtDuration(t.duration_ms)}` : '',
                 queuedSince(t), triggerLabel(t.trigger),
                 t.request_count > 1 ? `被点 ${t.request_count} 次` : ''].filter(Boolean).join(' · ') }}
            </div>
            <div v-if="t.error" class="queue-row-sub danger" :title="t.error">{{ t.error }}</div>
          </div>
          <div v-if="!queueHistory.length" class="queue-empty">还没有跑完的扫描</div>
        </div>
      </div>
    </div>

    <!-- 元数据与刮削：TMDB Key 填写与手动刮削收拢在这里（不放在通用系统设置页） -->
    <div class="admin-card scrape-card">
      <div class="card-header">
        <h2>元数据与刮削</h2>
        <div class="queue-facts">
          <span class="fact" :class="{ warn: tmdbStatus !== null && !tmdbStatus.configured }">
            TMDB：{{ tmdbStatusText }}
          </span>
        </div>
      </div>
      <div class="scrape-grid">
        <div class="scrape-block">
          <h3>TMDB API Keys</h3>
          <p class="drawer-hint">
            每行一个，也可用逗号分隔；多个 key 在 401 / 429 时自动轮询。
            保存后立即生效，无需重启。<span
              v-if="tmdbStatus?.env_present"
              class="text-danger"
            >环境变量里已配置 TMDB Key，后台填写暂不生效（环境变量优先）。</span>
          </p>
          <el-input
            v-model="tmdbKeysInput"
            type="textarea"
            :rows="3"
            placeholder="粘贴 TMDB API Key，每行一个或用逗号分隔"
          />
          <div class="scrape-actions">
            <el-button type="primary" size="small" :loading="tmdbSaving" @click="saveTmdbKeysAction">
              保存
            </el-button>
            <el-button size="small" :loading="tmdbTesting" @click="testTmdbKeysAction">
              测试连接
            </el-button>
            <span v-if="tmdbStatus && tmdbStatus.masked.length" class="mono scrape-masked">
              已配置 {{ tmdbStatus.count }} 个（{{ tmdbStatus.masked.join(' · ') }}）
            </span>
          </div>
          <div v-if="tmdbTestResults.length" class="scrape-results">
            <div v-for="r in tmdbTestResults" :key="r.index" class="scrape-result">
              <span class="mini-badge" :class="r.ok ? 'ok' : 'danger'">{{ r.ok ? '有效' : '失败' }}</span>
              <span class="mono">{{ r.masked }}</span>
              <span>{{ r.message }}</span>
            </div>
          </div>
        </div>
        <div class="scrape-block">
          <h3>条目元数据刷新</h3>
          <p class="drawer-hint">
            按条目 ID 立即重刮一条：有 NFO 就重读 NFO（文字以 NFO 为准），
            再用 TMDB 补缺失的图片 / IMDb / 别名。电影 / 剧集优先，季 / 集按 NFO 能力处理。
          </p>
          <div class="scrape-actions">
            <el-input v-model="rescrapeItemId" placeholder="条目 ID" style="width: 160px" clearable />
            <el-button size="small" :loading="rescrapeItemLoading" @click="doRescrapeItem">
              刷新元数据
            </el-button>
          </div>
          <div v-if="rescrapeItemNotes.length" class="scrape-results">
            <div v-for="(n, i) in rescrapeItemNotes" :key="i" class="scrape-result">{{ n }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 媒体库列表：卡片只保留识别信息、关键状态和高频操作，其余设置收进抽屉 -->
    <div class="lib-grid">
      <article v-for="l in libraries" :key="l.id" class="admin-card lib-card">
        <div class="lib-cover">
          <img v-if="coverUrls[l.id]" :src="coverUrls[l.id]" :alt="`${l.name} 封面`" />
          <div v-else class="lib-cover-empty">
            <Film :size="32" />
            <span>{{ typeLabel(l.collection_type) }}库</span>
          </div>
          <div class="lib-cover-shade" />
          <div class="lib-cover-badges">
            <span v-if="l.is_virtual" class="mini-badge pin">虚拟库</span>
            <span class="mini-badge" :class="l.is_enabled ? 'ok' : 'off'">
              {{ l.is_enabled ? '启用' : '停用' }}
            </span>
            <span v-if="cardBadge(l)" class="mini-badge" :class="cardBadge(l)?.cls">
              {{ cardBadge(l)?.text }}
            </span>
          </div>
          <div class="lib-cover-actions">
            <el-upload
              :accept="'image/jpeg,image/png,image/webp'"
              :show-file-list="false"
              :disabled="coverUploading[l.id]"
              :http-request="(options: UploadRequestOptions) => requestCoverUpload(l, options)"
            >
              <el-button
                class="cover-button"
                circle
                text
                :loading="coverUploading[l.id]"
                :title="l.cover_url ? '更换封面' : '上传封面'"
                aria-label="上传媒体库封面"
              >
                <ImagePlus :size="18" />
              </el-button>
            </el-upload>
            <el-button
              v-if="l.cover_url"
              class="cover-button"
              circle
              text
              title="移除封面"
              aria-label="移除媒体库封面"
              @click="removeCover(l)"
            >
              <X :size="17" />
            </el-button>
          </div>
        </div>

        <div class="lib-body">
          <div class="lib-head">
            <span class="lib-name">{{ l.name }}</span>
            <span class="lib-meta">{{ typeLabel(l.collection_type) }}库</span>
          </div>

          <div class="lib-facts">
            <span class="fact" :class="{ warn: serviceFact(l).warn }" :title="'服务：' + serviceFact(l).text">
              <Server :size="12" />{{ serviceFact(l).text }}
            </span>
            <span class="fact" :class="{ warn: sourceFact(l).warn }" :title="'来源：' + sourceFact(l).text">
              <HardDrive :size="12" />{{ sourceFact(l).text }}
            </span>
            <span class="fact"><Film :size="12" />{{ l.item_count }} 个条目</span>
          </div>

          <div class="lib-state">
            <span v-if="cardLiveHint(l)" class="lib-live" :title="cardLiveHint(l)">
              <span class="scan-dot" :class="liveFor(l)?.state === 'queued' ? 'is-queued' : 'is-running'" />
              {{ cardLiveHint(l) }}
            </span>
            <span v-else class="lib-time">
              {{ l.last_scan_at ? `上次扫描 ${fmtDate(l.last_scan_at)}` : '尚未扫描' }}
            </span>
          </div>

          <div v-if="scanError(l)" class="scan-error" :title="scanError(l)">{{ scanError(l) }}</div>
          <div v-else-if="libReach(l)?.level === 'bad'" class="scan-error" :title="reachTitle(l)">
            播放风险：{{ libReach(l)?.message }}
          </div>
        </div>

        <div class="lib-foot">
          <el-button size="small" type="primary" plain @click="scan(l)">
            <ScanSearch :size="13" />扫描
          </el-button>
          <el-button size="small" plain title="重新刮削元数据" @click="openRescrape(l)">
            <RefreshCw :size="13" />重新刮削
          </el-button>
          <el-button size="small" plain @click="openSettings(l)">
            <Settings2 :size="13" />设置
          </el-button>
          <el-button size="small" plain title="扫描记录" @click="openScans(l)">
            <History :size="13" />
          </el-button>
          <el-button size="small" type="danger" plain title="删除媒体库" @click="removeLib(l)">
            <Delete :size="13" />
          </el-button>
        </div>
      </article>

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
            placeholder="服务器上的媒体目录，多个用逗号或换行分隔&#10;如：/media/movies&#10;挂载子目录：mount://挂载ID/子目录（如 mount://2/video/剧集/动漫剧）"
          />
          <div class="form-hint">本机目录；也可以写 <code>mount://挂载ID/子目录</code> 只扫描挂载下的某个子目录（如 <code>mount://2/video/剧集/动漫剧</code>）。想扫整个挂载用下面的「存储挂载」。</div>
        </el-form-item>
        <el-form-item label="归属服">
          <el-select v-model="form.realm_id" placeholder="留空 = 面板当前服" style="width: 100%">
            <el-option v-for="r in realmOptions" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
          <p class="field-help">一个服一个：只有这个服的 EA 会向客户端提供这个库。</p>
        </el-form-item>
        <el-form-item label="归属播放节点">
          <el-select
            v-model="form.node_id"
            clearable
            placeholder="留空 = 未分配（所有节点可见、由面板扫描）"
            style="width: 100%"
          >
            <el-option v-for="n in nodes" :key="n.id" :label="nodeLabel(n)" :value="n.id" />
          </el-select>
          <p class="field-help">
            如果这个库的内容只在那台机器上（本机目录 / 只在那里配了的 rclone），就把库分配给那台节点。
          </p>
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

    <!-- 媒体库设置：从卡片移出低频配置，保持卡片可快速扫读 -->
    <el-drawer v-model="settingsVisible" :title="`媒体库设置 · ${settingsTarget?.name || ''}`" size="430px">
      <div v-if="settingsTarget" class="library-settings">
        <div class="settings-section">
          <div class="settings-section-title">归属与来源</div>
          <div class="lib-policy">
            <span class="policy-label">归属服</span>
            <el-select
              v-model="settingsTarget.realm_id"
              clearable
              placeholder="未标注（所有服可见）"
              @change="saveRealm(settingsTarget)"
            >
              <el-option v-for="r in realmOptions" :key="r.id" :label="r.name" :value="r.id" />
            </el-select>
          </div>
          <div v-if="!settingsTarget.is_virtual" class="lib-policy">
            <span class="policy-label">归属节点</span>
            <el-select
              v-model="settingsTarget.node_id"
              clearable
              placeholder="未分配（所有节点可见）"
              @change="saveNode(settingsTarget)"
            >
              <el-option v-for="n in nodes" :key="n.id" :label="nodeLabel(n)" :value="n.id" />
            </el-select>
          </div>
          <div v-if="!settingsTarget.is_virtual" class="lib-policy">
            <span class="policy-label">存储来源</span>
            <el-select
              v-model="settingsTarget.mount_ids"
              multiple
              collapse-tags
              collapse-tags-tooltip
              placeholder="未绑定"
              @change="saveMounts(settingsTarget)"
            >
              <el-option v-for="m in mounts" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>
          </div>
          <div class="settings-paths">
            <span>当前路径</span>
            <p v-if="settingsTarget.is_virtual">
              按发行平台「{{ settingsTarget.platform || '—' }}」聚合，条目仍归属原媒体库
            </p>
            <p v-else>{{ settingsTarget.paths.join(' · ') || '未配置本机路径' }}</p>
          </div>
        </div>

        <div v-if="!settingsTarget.is_virtual" class="settings-section">
          <div class="settings-section-title">扫描与账号</div>
          <div class="lib-policy">
            <span class="policy-label">刮削策略</span>
            <el-select v-model="settingsTarget.scrape_policy" @change="savePolicy(settingsTarget)">
              <el-option v-for="p in POLICIES" :key="p.value" :label="p.label" :value="p.value" />
            </el-select>
          </div>
          <div class="lib-policy">
            <span class="policy-label">115 账号</span>
            <el-select
              v-model="settingsTarget.account_115_id"
              clearable
              placeholder="默认账号"
              @change="saveAccount115(settingsTarget)"
            >
              <el-option v-for="a in panAccounts" :key="a.id" :label="a.name" :value="a.id" />
            </el-select>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 重新刮削：选策略；all 二次确认并提示配额消耗 -->
    <el-dialog v-model="rescrapeVisible" title="重新刮削" width="420px">
      <p class="drawer-hint">
        对「{{ rescrapeTarget?.name }}」触发一次重新刮削扫描，策略只覆盖本轮，不改库配置。
      </p>
      <el-radio-group v-model="rescrapePolicy">
        <el-radio-button value="missing_only">仅补缺失</el-radio-button>
        <el-radio-button value="all">全量重刮</el-radio-button>
      </el-radio-group>
      <p v-if="rescrapePolicy === 'all'" class="drawer-hint text-danger" style="margin-top: 8px">
        全量重刮会对该库所有条目重新请求 TMDB，会消耗大量配额，确定要继续吗？
      </p>
      <template #footer>
        <el-button @click="rescrapeVisible = false">取消</el-button>
        <el-button type="primary" :loading="rescrapeLoading" @click="confirmRescrape">开始</el-button>
      </template>
    </el-dialog>

    <!-- 扫描记录：最近若干轮（每轮的状态 / 触发方 / 增量 / 耗时 / 原因） -->
    <el-drawer v-model="scanDrawer" :title="`扫描记录 · ${scanTarget?.name || ''}`" size="620px">
      <p class="drawer-hint">
        每轮扫描一行，最近的在最上面（每库最多保留 {{ scanKeep }} 条）。
        「每轮都失败」和「只是最近一轮失败」是两件事，这里能直接看出来。
        「来源」列把这一轮拆到每条路径 / 挂载上：悬停看每条扫到多少文件、哪条是空的。
      </p>
      <DataTable
        :rows="scanRuns"
        :columns="scanColumns"
        :loading="scanLoading"
        empty="还没有扫描记录"
        row-key="id"
      >
        <template #cell-started_at="{ row }">{{ fmtDate(row.started_at) }}</template>

        <template #cell-status="{ row }">
          <span class="mini-badge" :class="statusMeta(row.status).cls">{{ statusMeta(row.status).text }}</span>
        </template>

        <template #cell-trigger="{ row }">{{ triggerLabel(row.trigger) }}</template>

        <template #cell-summary="{ row }">
          <span class="mono">{{ runSummary(row) }}</span>
        </template>

        <template #cell-sources="{ row }">
          <span
            :class="{ 'scan-hint': emptySourceCount(row.sources) }"
            :title="sourcesDetail(row.sources)"
          >{{ sourcesLabel(row.sources) }}</span>
        </template>

        <template #cell-duration="{ row }">
          {{ row.duration_ms != null ? fmtDuration(row.duration_ms) : '—' }}
        </template>

        <template #cell-error="{ row }">
          <span v-if="row.error" class="scan-error" :title="row.error">{{ row.error }}</span>
          <span v-else-if="row.failed_roots.length" class="scan-error" :title="row.failed_roots.join('；')">
            {{ row.failed_roots.join('；') }}
          </span>
          <span v-else>—</span>
        </template>
      </DataTable>
    </el-drawer>
  </div>
</template>

<style scoped>
.admin-page { gap: 16px; }

.lib-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 16px;
}

.lib-card { display: flex; flex-direction: column; gap: 0; overflow: hidden; min-width: 0; }
.lib-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: nowrap; }
.lib-name {
  font-weight: var(--font-weight-bold); font-size: var(--font-size-lg); color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.lib-meta { flex-shrink: 0; font-size: var(--font-size-xs); color: var(--text-tertiary); }
lib-state { min-height: 18px; }

.lib-cover { position: relative; aspect-ratio: 16 / 8.5; overflow: hidden; background: var(--bg-inset); }
lib-cover > img { width: 100%; height: 100%; object-fit: cover; display: block; }
lib-cover-empty {
  width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 8px; color: var(--text-muted); font-size: var(--font-size-xs);
}
lib-cover-shade {
  position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(to bottom, rgb(0 0 0 / 0.32), transparent 45%, rgb(0 0 0 / 0.18));
}
lib-cover-badges { position: absolute; top: 10px; left: 10px; right: 58px; display: flex; gap: 6px; flex-wrap: wrap; }
lib-cover-actions { position: absolute; top: 8px; right: 8px; display: flex; gap: 4px; }
cover-button {
  color: #fff !important; background: rgb(0 0 0 / 0.48) !important;
  border: 1px solid rgb(255 255 255 / 0.22) !important;
}
cover-button:hover { background: rgb(0 0 0 / 0.72) !important; }
lib-body { display: flex; flex-direction: column; gap: 10px; padding: 14px 14px 12px; flex: 1; }
lib-facts { display: flex; flex-wrap: wrap; gap: 6px 12px; }
.fact {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fact.warn { color: var(--warning); }

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

.drawer-hint { margin: 0 0 12px; font-size: var(--font-size-xs); color: var(--text-tertiary); }

.text-danger { color: var(--danger); }
.scrape-card { margin-bottom: 16px; }
.scrape-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.scrape-block h3 { margin: 0 0 8px; font-size: var(--font-size-sm); font-weight: 600; }
.scrape-actions { display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.scrape-masked { font-size: var(--font-size-xs); color: var(--text-tertiary); }
.scrape-results { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.scrape-result { display: flex; align-items: center; gap: 8px; font-size: var(--font-size-xs); }
@media (max-width: 900px) { .scrape-grid { grid-template-columns: 1fr; } }

/* 最近一次扫描结果：摘要一行 +（失败时）原因一行 */
.lib-scan { display: flex; flex-direction: column; gap: 3px; }
.scan-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}
.scan-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); flex-shrink: 0; }
.scan-dot.is-success { background: var(--success); }
.scan-dot.is-partial { background: var(--warning); }
.scan-dot.is-failed { background: var(--danger); }
.scan-dot.is-running { background: var(--info); }
.scan-error {
  font-size: var(--font-size-xs);
  color: var(--warning);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scan-hint {
  font-size: var(--font-size-xs);
  color: var(--warning);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 实时状态一行（排队原因 / 扫描进度）：与「最近一次结果」分层，后者是落库的历史 */
.lib-live {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--info);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.scan-dot.is-queued { background: var(--text-tertiary); }

/* 扫描队列：正在跑 / 排队中 / 最近完成 三列（同一远程挂载串行化的可见面） */
.reach-card { display: flex; flex-direction: column; gap: 10px; }
.reach-card .card-header h2 { display: flex; align-items: center; gap: 8px; }
.reach-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
}
.reach-row-body { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.reach-row-title { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.reach-name { font-weight: var(--font-weight-bold); color: var(--text-primary); }
.reach-node { font-size: var(--font-size-xs); color: var(--text-tertiary); }
.reach-row-fix { font-size: var(--font-size-xs); color: var(--text-secondary); }

.queue-card { display: flex; flex-direction: column; gap: 12px; }
.queue-card .card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.queue-facts { display: flex; flex-wrap: wrap; gap: 6px 14px; }
.queue-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.queue-col { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.queue-col-title { font-size: var(--font-size-xs); color: var(--text-tertiary); }
.queue-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-inset);
  min-width: 0;
}
.queue-row-head { display: flex; align-items: center; gap: 8px; min-width: 0; }
.queue-name {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-row-head :deep(.el-button) { margin-left: auto; padding: 0 4px; }
.queue-row-sub {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-row-sub.warn { color: var(--warning); }
.queue-row-sub.danger { color: var(--danger); }
.queue-empty { font-size: var(--font-size-xs); color: var(--text-muted); }

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
