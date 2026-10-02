<script setup lang="ts">
/**
 * 媒体库管理：库列表/创建/扫描/删除 + 刮削策略 + 平台虚拟媒体库 + 图片修复队列
 * + 停止全部转码
 *
 * v2.6.11：会话表改用 DataTable（手机卡片）；媒体库卡片的「挂载 / 刮削策略 / 115 账号」
 * 在窄屏改为「标签在上、控件在下」，不再把中文标签挤成竖排两行；页面里的硬编码灰度
 * 全部换成主题令牌。
 *
 * v2.6.20：多服 / 多机部署——每个库都能指定「归属服」与「归属播放节点」（未指定 = 所有服、
 * 所有节点可见，由面板扫描）；已分配的库只有那台 EA 向客户端展示、也只有它会扫描。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
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
  fetchAutoScan,
  fetchChaseNew,
  fetchTmdbKeys,
  generateVirtualLibraries,
  previewLibraryCover,
  previewTmdb,
  regenerateLibraryCover,
  removeLibraryCover,
  renderLibraryCover,
  rescrapeItem,
  rescrapeLibrary,
  runRepairQueue,
  scanLibrary,
  saveAutoScan,
  saveChaseNew,
  saveTmdbKeys,
  testTmdbKeys,
  stopAllTranscodes,
  updateLibrary,
  uploadLibraryCover,
} from '@/api/admin'
import type { AutoScanConfig, ChaseNewConfig, TmdbKeysStatus, TmdbTestResult } from '@/api/admin'
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
  Pan115Account,
  RemoteServerRow,
  StorageMount,
} from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import MountPathPicker from '@/components/MountPathPicker.vue'
import './EmbyAdmin.css'
import type { DataColumn } from '@/components/DataTable.vue'

const realm = useRealmStore()
const libraries = ref<EmbyLibrary[]>([])
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

// 媒体库配置表单的可见性与状态统一在下面的「单页分组表单」一节里（新建 / 编辑共用）

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

// ==================== 媒体库配置：新建与编辑共用一张分组表单 ====================
// 借鉴 Emby Manager：一个媒体库的全部配置在一张单页表单里改完（分组 + 每项一句人话
// 说明 + 推荐项标注），而不是「新建一个弹窗 + 设置一个抽屉」两处各改一半：以前
// 路径在设置里只能看不能改、启用状态和追新监听根本没入口。
// 表单状态只有这一份，所以「浏览」的追加 / 去重口径两边完全一致。

interface LibFormState {
  /** null = 新建 */
  id: number | null
  name: string
  collection_type: string
  is_enabled: boolean
  realm_id: number | null
  node_id: number | null
  mount_ids: number[]
  scrape_policy: string
  account_115_id: number | null
  /** 媒体路径：一行一个（也容忍逗号分隔，与后端同一套拆分口径） */
  paths: string
  /** 是否纳入「追新」轮询监听（仅编辑可用；追新本身是全局开关） */
  chase: boolean
}

function emptyLibForm(): LibFormState {
  return {
    id: null,
    name: '',
    collection_type: 'movies',
    is_enabled: true,
    realm_id: null,
    node_id: null,
    mount_ids: [],
    scrape_policy: 'missing_only',
    account_115_id: null,
    paths: '',
    chase: false,
  }
}

const libForm = reactive<LibFormState>(emptyLibForm())
const libFormVisible = ref(false)
const libFormSaving = ref(false)
/** 追新监听是即时保存的（另一个接口），单独一个 loading，不跟表单保存共用 */
const chaseLibSaving = ref(false)
/** 编辑中的库对象（封面操作要用）；新建时为 null */
const libFormTarget = ref<EmbyLibrary | null>(null)
/** 打开时的表单指纹：算「有没有改动」+ 还原用（存指纹而不是对象引用） */
const libFormFingerprintAtOpen = ref('')

// ---- 封面自动生成（样式 + 标题变量） ----

/** 样式选项：每项写清「长什么样」，别让管理员对着预览猜 */
const COVER_TEMPLATES: LibOption[] = [
  { value: 'poster', label: '海报拼贴', hint: '最新入库的多张海报排在一起，下面压标题。适合剧集库，一眼看出最近更新了什么' },
  { value: 'visual', label: '主视觉', hint: '单张海报铺满整幅，底部渐变压标题。适合电影库，干净大气' },
  { value: 'filmstrip', label: '胶片带', hint: '三张海报横排成带状，标题压在下方。适合片库少的分类' },
]

const coverTemplate = ref<'' | 'poster' | 'visual' | 'filmstrip'>('')
const coverTitle = ref('')
const coverSubtitle = ref('')
const coverPreviewUrl = ref('')
const coverPreviewLoading = ref(false)
const coverPreviewError = ref('')
const coverSaving = ref(false)
const coverRegenerating = ref(false)

/** 预览的 blob URL，用完必须 revoke，否则每点一次泄漏一份 */
let coverPreviewObjectUrl = ''

function releaseCoverPreview() {
  if (coverPreviewObjectUrl) {
    URL.revokeObjectURL(coverPreviewObjectUrl)
    coverPreviewObjectUrl = ''
  }
}

/** 预览需要已保存的库 id：渲染要从库里挑海报，新建库还没入库没有海报可选 */
function canPreviewCover(): boolean {
  return libFormTarget.value !== null
}

async function loadCoverPreview() {
  const lib = libFormTarget.value
  if (!lib || !coverTemplate.value) {
    coverPreviewUrl.value = ''
    coverPreviewError.value = coverTemplate.value ? '新建的库还没有条目，保存后再生成封面' : ''
    return
  }
  coverPreviewLoading.value = true
  coverPreviewError.value = ''
  try {
    const blob = await previewLibraryCover(lib.id, {
      template: coverTemplate.value,
      title: coverTitle.value,
      subtitle: coverSubtitle.value,
    })
    releaseCoverPreview()
    coverPreviewObjectUrl = URL.createObjectURL(blob)
    coverPreviewUrl.value = coverPreviewObjectUrl
    coverPreviewError.value = ''
  } catch (e) {
    // 生成不出来是常态（库还没刮削出图），给一句话说明而不是弹错
    coverPreviewUrl.value = ''
    coverPreviewError.value = e instanceof Error ? e.message : '预览失败'
  } finally {
    coverPreviewLoading.value = false
  }
}

async function saveCoverConfig() {
  const lib = libFormTarget.value
  if (!lib || !coverTemplate.value) return
  coverSaving.value = true
  try {
    await renderLibraryCover(lib.id, {
      template: coverTemplate.value,
      title: coverTitle.value,
      subtitle: coverSubtitle.value,
    })
    ElMessage.success('封面已重新生成并保存')
    await loadLibraries()
    await loadCoverPreview()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '封面生成失败')
  } finally {
    coverSaving.value = false
  }
}

async function regenerateCover() {
  const lib = libFormTarget.value
  if (!lib) return
  coverRegenerating.value = true
  try {
    await regenerateLibraryCover(lib.id)
    ElMessage.success('已按最新入库的海报重新生成')
    await loadLibraries()
    await loadCoverPreview()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '重新生成失败')
  } finally {
    coverRegenerating.value = false
  }
}

/** 关表单时顺手回收 blob URL */
watch(coverTemplate, () => { if (coverTemplate.value) loadCoverPreview() })

interface LibOption { value: string; label: string; hint: string; recommended?: boolean }

/** 内容类型：每一项都写清「选了会发生什么」 */
const COLLECTION_TYPES: LibOption[] = [
  { value: 'movies', label: '电影', hint: '一个文件一部片：客户端只给「播放」，没有季 / 集' },
  { value: 'tvshows', label: '剧集', hint: '按「剧名/季/集」目录组织：客户端能选季选集，刮削按剧集算' },
  { value: 'music', label: '音乐', hint: '按「歌手/专辑」组织，刮削走音乐元数据（TMDB 音乐条目少）' },
  { value: 'mixed', label: '混合', hint: '电影剧集放一起：能扫进来，但客户端分不出季集，只适合临时合并' },
]

/** 刮削策略：决定一轮扫描要不要回头重刮「已经刮过」的条目（直接影响 TMDB 配额） */
const POLICIES: LibOption[] = [
  { value: 'missing_only', label: '仅缺失时刮削', hint: '只补缺图 / 缺简介的条目，刮过的不再请求 TMDB —— 最省配额', recommended: true },
  { value: '3m', label: '3 个月重刮', hint: '顺手修正三个月前刮错的信息（换主图、补 IMDb / 别名）' },
  { value: '6m', label: '半年重刮', hint: '半年回头重刮一次；条目多时配额开销明显' },
  { value: '1y', label: '一年重刮', hint: '一年一次大修：适合整站换源 / 换刮削源之后' },
  { value: 'all', label: '全部重刮', hint: '每轮扫描把所有条目重刮一遍，最干净也最耗配额，别常开' },
]

function optionOf(list: LibOption[], value: string | null | undefined): LibOption | undefined {
  return list.find((o) => o.value === value)
}

/** 下拉收起时也能看见「（推荐）」，不然推荐项藏在面板里没人知道 */
function optionLabel(list: LibOption[], value: string | null | undefined): string {
  const hit = optionOf(list, value)
  return hit ? (hit.recommended ? `${hit.label}（推荐）` : hit.label) : ''
}

// ---- 媒体路径：一行一个，浏览按钮的单选 / 多选都追加到同一个框 ----

// 挂载路径选择器
const pathPicker = ref<{ open: () => void } | null>(null)

/** 路径框 → 路径数组：一行一个（兼容逗号 / 中文逗号），去重且去空 */
function parsePaths(text: string): string[] {
  const out: string[] = []
  for (const raw of (text || '').split(/[,，\n]/)) {
    const p = raw.trim()
    if (p && !out.includes(p)) out.push(p)
  }
  return out
}

/**
 * 追加一批路径：与框里已有的逐个比对，已存在就跳过；批次内部同样去重
 * （跨层级重复勾选时只写一次）。跳过的数量要报出来——「我勾了 5 个，怎么只加了 2 个」
 * 是这里最容易让人以为坏了的地方。
 */
function appendPaths(list: string[]) {
  const existing = parsePaths(libForm.paths)
  const seen = new Set(existing)
  const added: string[] = []
  let skipped = 0
  for (const raw of list) {
    const p = (raw || '').trim()
    if (!p) continue
    if (seen.has(p)) {
      skipped += 1
      continue
    }
    seen.add(p)
    added.push(p)
  }
  if (!added.length) {
    ElMessage.info(`所选 ${list.length} 个目录都已在路径框里，没有新增`)
    return
  }
  libForm.paths = [...existing, ...added].join('\n')
  ElMessage.success(skipped > 0
    ? `已追加 ${added.length} 个目录（跳过 ${skipped} 个已存在）`
    : `已追加 ${added.length} 个目录`)
}

/** 单选：追加一个目录（与多选同口径，同样去重） */
function onPickMountPath(mountPath: string) {
  appendPaths([mountPath])
}

/** 多选：一批目录一次性写入路径框 */
function onPickMountPaths(mountPaths: string[]) {
  appendPaths(mountPaths)
}

// ---- 打开 / 还原 / 保存 ----

/** 表单指纹：只认「规范化后」的差异（路径去空去重、挂载排序），空改空格不算改动 */
function formFingerprint(): string {
  return JSON.stringify({
    name: libForm.name.trim(),
    collection_type: libForm.collection_type,
    is_enabled: libForm.is_enabled,
    realm_id: libForm.realm_id,
    node_id: libForm.node_id,
    mount_ids: [...libForm.mount_ids].sort((a, b) => a - b),
    scrape_policy: libForm.scrape_policy,
    account_115_id: libForm.account_115_id,
    paths: parsePaths(libForm.paths),
    chase: libForm.chase,
  })
}

const libFormDirty = computed(
  () => libFormVisible.value && formFingerprint() !== libFormFingerprintAtOpen.value,
)

/** 路径改没改：改了就必须重新扫描一次才生效（扫描任务用配置快照，见 update_library） */
const libFormPathsChanged = computed(() => {
  if (!libFormDirty.value) return false
  const before = JSON.parse(libFormFingerprintAtOpen.value || '{}')
  return JSON.stringify(before.paths) !== JSON.stringify(parsePaths(libForm.paths))
})

function openCreate() {
  libFormTarget.value = null
  Object.assign(libForm, emptyLibForm())
  libFormVisible.value = true
  libFormFingerprintAtOpen.value = formFingerprint()
}

function openSettings(l: EmbyLibrary) {
  libFormTarget.value = l
  // 封面：先回填已存配置，再拉一张预览（走 blob，不占 cover_path）
  coverTemplate.value = (l.cover_template || '') as typeof coverTemplate.value
  coverTitle.value = l.cover_title || ''
  coverSubtitle.value = l.cover_subtitle || ''
  if (coverTemplate.value) void loadCoverPreview()
  else { coverPreviewUrl.value = ''; coverPreviewError.value = '' }
  Object.assign(libForm, {
    id: l.id,
    name: l.name,
    collection_type: l.collection_type || 'movies',
    is_enabled: l.is_enabled !== false,
    realm_id: l.realm_id ?? null,
    node_id: l.node_id ?? null,
    mount_ids: [...(l.mount_ids || [])],
    scrape_policy: l.scrape_policy || 'missing_only',
    account_115_id: l.account_115_id ?? null,
    paths: (l.paths || []).join('\n'),
    chase: chaseLibraryIds().includes(l.id),
  })
  libFormVisible.value = true
  libFormFingerprintAtOpen.value = formFingerprint()
}

/** 还原：回到打开时的样子（追新监听是即时保存的，不在这份还原范围内） */
function revertForm() {
  if (libFormTarget.value) openSettings(libFormTarget.value)
  else openCreate()
  ElMessage.info('已还原为打开时的配置')
}

/** 抽屉里还有没保存的改动时拦一下：关抽屉不等于想丢掉刚才填的 */
function beforeCloseForm(done: () => void) {
  if (!libFormDirty.value) {
    done()
    return
  }
  ElMessageBox.confirm('表单里有还没保存的改动，放弃吗？', '放弃改动', {
    type: 'warning',
    confirmButtonText: '放弃改动',
    cancelButtonText: '继续编辑',
  }).then(() => done()).catch(() => undefined)
}

/** 「取消」按钮走同一条拦截（直接改 v-model 不会触发 before-close） */
function cancelForm() {
  beforeCloseForm(() => {
    libFormVisible.value = false
    libFormTarget.value = null
  })
}

/** 追新开关：即时代理到全局清单，失败弹回原状态（toggleChase 里处理） */
function onChaseSwitch(v: unknown) {
  toggleChase(!!v)
}

/**
 * 保存：新建走 POST、编辑走 PUT（同一个鉴权接口，一次提交全部字段）。
 * 路径类改动后端会回 rescan_required —— 扫描任务用的是配置快照，不重扫就还是老路径。
 */
async function saveForm(thenScan = false) {
  const editingId = libForm.id
  const name = libForm.name.trim()
  const paths = parsePaths(libForm.paths)
  const virtual = !!libFormTarget.value?.is_virtual
  if (!name) {
    ElMessage.warning('请填写媒体库名称')
    return
  }
  if (!virtual && !paths.length && !libForm.mount_ids.length) {
    ElMessage.warning('请至少配置一个媒体路径或一个存储挂载，否则扫不到任何内容')
    return
  }
  libFormSaving.value = true
  try {
    let savedId: number | null = null
    if (editingId == null) {
      const res = await createLibrary({
        name,
        collection_type: libForm.collection_type,
        paths,
        mount_ids: libForm.mount_ids,
        scrape_policy: libForm.scrape_policy,
        account_115_id: libForm.account_115_id ?? undefined,
        realm_id: libForm.realm_id ?? undefined,
        node_id: libForm.node_id ?? undefined,
      })
      savedId = res.id
      const hasSource = paths.length > 0 || libForm.mount_ids.length > 0
      ElMessage.success(`媒体库「${name}」已创建${hasSource ? '，可以扫一次了' : ''}`)
    } else {
      // 虚拟库没有自己的目录与挂载（也不归属某台节点），这几个字段干脆不传：
      // 传空数组等于「清空来源」，没必要为看不出来的库担这个风险
      const res = await updateLibrary(editingId, {
        name,
        collection_type: libForm.collection_type,
        is_enabled: libForm.is_enabled,
        scrape_policy: libForm.scrape_policy,
        // 传 null 表示解绑（回退默认账号）；省略会被 axios 丢掉，等于不改
        account_115_id: libForm.account_115_id ?? null,
        realm_id: libForm.realm_id ?? null,
        ...(virtual
          ? {}
          : { paths, mount_ids: libForm.mount_ids, node_id: libForm.node_id ?? null }),
      })
      savedId = editingId
      ElMessage.success(res?.rescan_required
        ? `「${name}」配置已保存（路径 / 归属类改动要重新扫描后才对扫描生效）`
        : `「${name}」配置已保存`)
    }
    libFormVisible.value = false
    libFormTarget.value = null
    await load()
    if (thenScan && savedId != null) {
      const target = libraries.value.find((x) => x.id === savedId)
      if (target) await scan(target)
    }
  } catch {
    // 失败提示由全局拦截器给出（带着后端的 detail，如「目录不存在或不可读」）；
    // 这里不重复弹，表单内容原样留着让管理员改完再存
  } finally {
    libFormSaving.value = false
  }
}

// ---- 目录变更监听（追新）：全局开关 + 每库一个「纳不纳入」 ----

/** 追新监听的库 id 列表。空串 = 全部启用库（后端 change_watcher._check_once 的口径） */
function chaseLibraryIds(): number[] {
  return (chaseNew.value?.libraries || '')
    .split(/[,，\n]/)
    .map((x) => Number(x.trim()))
    .filter((x) => Number.isInteger(x) && x > 0)
}

/** 清单为空 = 「所有启用库都监听」，此时单个库的开关没有意义（关掉自己 = 还是全选） */
function chaseCoversAll(): boolean {
  return !!chaseNew.value && !chaseNew.value.libraries.trim()
}

/** 把当前库挪进 / 挪出追新清单（改的是全局配置里的一行，保存即生效） */
async function toggleChase(on: boolean) {
  const cfg = chaseNew.value
  if (!cfg || libForm.id == null) return
  const ids = new Set(chaseLibraryIds())
  if (on) ids.add(libForm.id)
  else ids.delete(libForm.id)
  if (!ids.size) {
    ElMessage.warning('追新清单不能全空：清空代表「所有启用库都监听」。要只排除某几个库，先在别的库上打开它。')
    return
  }
  chaseLibSaving.value = true
  try {
    const res = await saveChaseNew(cfg.enabled, cfg.interval, [...ids].sort((a, b) => a - b).join(','))
    chaseNew.value = {
      enabled: res.enabled,
      interval: res.interval,
      libraries: res.libraries,
      last_check: res.last_check,
      last_found: res.last_found,
    }
    libForm.chase = on
    // 追新是即时保存的，不算「未保存的改动」——只把指纹里的这一项对齐，
    // 其余字段的改动状态要原样留着
    const before = JSON.parse(libFormFingerprintAtOpen.value || '{}')
    before.chase = on
    libFormFingerprintAtOpen.value = JSON.stringify(before)
    ElMessage.success(on
      ? `已纳入追新监听（每 ${res.interval} 分钟检查一次新文件）`
      : '已移出追新监听')
  } catch {
    // 拦截器已提示；开关弹回去，别留一个「看起来生效了」的假状态
    libForm.chase = !on
  } finally {
    chaseLibSaving.value = false
  }
}

// ---- 卡片上的一句话策略摘要（不用点进设置就知道这个库怎么跑的） ----

function policyLabel(value: string | null | undefined): string {
  return optionOf(POLICIES, value)?.label || '仅缺失时刮削'
}

/** 这个库在不在追新轮询里；不在也要说清是「追新没开」还是「就它没参与」 */
function chaseFact(l: EmbyLibrary): string {
  const cfg = chaseNew.value
  // 配置没读到时不能说「追新关」——那是在编一个结论
  if (!cfg) return '追新状态未知'
  if (!cfg.enabled) return '追新关'
  const covered = chaseCoversAll() || chaseLibraryIds().includes(l.id)
  return covered ? `追新每 ${cfg.interval} 分钟` : '不参与追新'
}

function libSummary(l: EmbyLibrary): string {
  if (l.is_virtual) return `虚拟库 · ${l.platform || '按平台聚合'} · 刮削 ${policyLabel(l.scrape_policy)}`
  const total = l.paths?.length || 0
  const pathBit = total
    ? `${total} 个路径${l.paths[0] ? `（${l.paths[0]}）` : ''}`
    : (l.mount_ids?.length ? '无本机路径 · 走挂载' : '未配路径')
  return [pathBit, chaseFact(l), `刮削 ${policyLabel(l.scrape_policy)}`].join(' · ')
}

/** 摘要的悬停全文：路径逐条列全（卡片上只留一行，看全靠悬停） */
function libSummaryTitle(l: EmbyLibrary): string {
  const lines: string[] = []
  if (l.is_virtual) {
    lines.push(`虚拟库：按发行平台「${l.platform || '—'}」聚合，没有自己的目录`)
  } else if (l.paths?.length) {
    lines.push(`媒体路径（${l.paths.length}）：`)
    lines.push(...l.paths.map((p) => `· ${p}`))
  } else {
    lines.push('媒体路径：未配置本机路径')
  }
  if (l.mount_ids?.length) {
    lines.push(`存储挂载：${l.mount_ids.map((id) => mounts.value.find((m) => m.id === id)?.name || `#${id}`).join('、')}`)
  }
  lines.push(`追新监听：${chaseFact(l)}`)
  lines.push(`刮削策略：${policyLabel(l.scrape_policy)}`)
  return lines.join('\n')
}


async function load() {
  loading.value = true
  try {
    // 归属服下拉要用服的清单（Layout 已加载过就不重复请求）
    if (!realm.loaded) realm.load().catch(() => undefined)
    const [l, r, a, m, srv, reach] = await Promise.all([
      fetchLibraries(),
      fetchRepairQueue().catch(() => ({ total: 0, items: [] })),
      fetchPan115Accounts().catch(() => ({ accounts: [], env_cookie_configured: false })),
      fetchMounts().catch(() => ({ mounts: [], mount_types: [] })),
      fetchServers().catch(() => null),
      fetchReachability().catch(() => null),
      loadTmdbStatus().catch(() => undefined),
      loadAutoScanConfig(),
      loadChaseNewConfig().catch(() => undefined),
    ])
    // mount_ids 兼容旧响应（老后端没有这个字段）
    libraries.value = l.libraries.map((lib) => ({ ...lib, mount_ids: lib.mount_ids || [] }))
    void loadCoverImages(libraries.value)
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
// 定时扫描：开关 + 每天几点扫，全部由用户在后台决定（默认关闭）
const autoScan = ref<AutoScanConfig | null>(null)
const autoScanSaving = ref(false)

async function loadAutoScanConfig() {
  try {
    const res = await fetchAutoScan()
    autoScan.value = { enabled: res.enabled, time: res.time, last_run: res.last_run }
  } catch {
    autoScan.value = null // 出错不挡页面其它内容
  }
}

// 追新：开关 + 轮询间隔（分钟），默认关闭
const chaseNew = ref<ChaseNewConfig | null>(null)
const chaseNewSaving = ref(false)

async function loadChaseNewConfig() {
  try {
    const res = await fetchChaseNew()
    chaseNew.value = { enabled: res.enabled, interval: res.interval, libraries: res.libraries, last_check: res.last_check, last_found: res.last_found }
  } catch {
    chaseNew.value = null
  }
}

async function saveChaseNewAction() {
  if (!chaseNew.value) return
  chaseNewSaving.value = true
  try {
    const res = await saveChaseNew(chaseNew.value.enabled, chaseNew.value.interval, chaseNew.value.libraries)
    chaseNew.value = { enabled: res.enabled, interval: res.interval, libraries: res.libraries, last_check: res.last_check, last_found: res.last_found }
    ElMessage.success(res.enabled ? '追新已开启（每 ' + res.interval + ' 分钟）' : '追新已关闭')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    chaseNewSaving.value = false
  }
}

async function saveAutoScanAction() {
  if (!autoScan.value) return
  autoScanSaving.value = true
  try {
    const res = await saveAutoScan(autoScan.value.enabled, autoScan.value.time)
    autoScan.value = { enabled: res.enabled, time: res.time, last_run: res.last_run }
    ElMessage.success(`定时扫描已${res.enabled ? `开启（每天 ${res.time}）` : '关闭'}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    autoScanSaving.value = false
  }
}

const tmdbStatus = ref<TmdbKeysStatus | null>(null)
const tmdbKeysInput = ref('')
const tmdbSaving = ref(false)
const tmdbTesting = ref(false)
const tmdbTestResults = ref<TmdbTestResult[]>([])
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
  if (libFormTarget.value?.id === l.id) {
    libFormVisible.value = false
    libFormTarget.value = null
  }
  if (coverUrls.value[l.id]) {
    URL.revokeObjectURL(coverUrls.value[l.id])
    delete coverUrls.value[l.id]
  }
  ElMessage.success('已删除')
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

function typeLabel(t: string): string {
  return { movies: '电影', tvshows: '剧集', music: '音乐', mixed: '混合' }[t] || t
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">媒体库</h1>
        <p class="admin-page-desc">
          点「新建媒体库」或卡片上的「设置」打开同一张配置表单：分组改完路径、归属、刮削与追新
        </p>
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
        <el-button type="primary" @click="openCreate">
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
          <!-- 扫描拆给 worker 执行后，本进程看不到它的内存队列：
               这两列来自它写进库里的状态（进度按刷盘间隔更新），说清楚免得被当成实时值 -->
          <span
            v-if="scanQueue?.view === 'db'"
            class="fact"
            title="扫描由执行节点（worker）运行；「正在扫描」「最近完成」两列来自它写进数据库的状态，进度按刷盘间隔更新"
          >
            进度来自执行节点
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
              <span
                v-if="t.via === 'db'"
                class="mini-badge muted"
                title="本轮由执行扫描的节点运行；这里显示的是它写进数据库的进度快照"
              >执行节点</span>
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
          <h3>定时扫描</h3>
          <p class="drawer-hint">
            打开后，每天到点自动把所有本机负责的启用库入队扫描（增量：没变化的目录跳过）。
            有扫描正在跑 / 排队时会跳过，不打断手工扫描。时间是服务器本地时间。
          </p>
          <div v-if="autoScan" class="scrape-actions" style="align-items: center">
            <el-switch v-model="autoScan.enabled" active-text="开启" inactive-text="关闭" />
            <el-time-picker
              v-model="autoScan.time"
              format="HH:mm"
              value-format="HH:mm"
              placeholder="每天几点"
              style="width: 130px"
              :disabled="!autoScan.enabled"
            />
            <el-button type="primary" size="small" :loading="autoScanSaving" @click="saveAutoScanAction">
              保存
            </el-button>
          </div>
          <div v-if="autoScan?.last_run" class="drawer-hint" style="margin-top: 6px">
            上次执行：{{ autoScan.last_run }}
          </div>
          <div v-else-if="autoScan" class="drawer-hint" style="margin-top: 6px">
            还没有执行过
          </div>
        </div>
        <div class="scrape-block">
          <h3>追新</h3>
          <p class="drawer-hint">
            打开后，每隔 N 分钟检查挂载上的新视频文件，发现即自动触发扫描 +
            刮削（NFO 优先 → TMDB → 豆瓣）。只支持本机可读的挂载（含 rclone 挂载的网盘）。
          </p>
          <div v-if="chaseNew" class="scrape-actions" style="align-items: center">
            <el-switch v-model="chaseNew.enabled" active-text="开启" inactive-text="关闭" />
            <el-input-number
              v-model="chaseNew.interval"
              :min="5" :max="120" :step="5"
              placeholder="分钟"
              style="width: 130px"
              :disabled="!chaseNew.enabled"
            />
            <span class="drawer-hint">分钟</span>
            <el-button type="primary" size="small" :loading="chaseNewSaving" @click="saveChaseNewAction">
              保存
            </el-button>
          </div>
          <div v-if="chaseNew?.last_check" class="drawer-hint" style="margin-top: 6px">
            上次检查：{{ chaseNew.last_check }} ｜ 上轮发现 {{ chaseNew.last_found }} 个新文件
          </div>
          <div v-else-if="chaseNew" class="drawer-hint" style="margin-top: 6px">
            还没有检查过
          </div>
        </div>
        <div class="scrape-block">
          <h3>媒体库封面</h3>
          <p class="drawer-hint">
            选个样式，系统会从<strong>最新入库</strong>的条目里挑海报自动拼一张横版封面
            （1920×1080），不用自己找图配字。刮完新片点「按最新海报重新生成」即可换封面。
          </p>

          <el-form-item label="自动生成样式" style="margin-bottom: 12px">
            <el-select
              v-model="coverTemplate"
              placeholder="留空 = 用上传的封面"
              clearable
              style="width: 100%"
            >
              <el-option
                v-for="t in COVER_TEMPLATES"
                :key="t.value"
                :label="t.label"
                :value="t.value"
              />
            </el-select>
            <p class="drawer-hint" style="margin-top: 4px">
              选中的样式：{{ optionOf(COVER_TEMPLATES, coverTemplate)?.hint || '不生成，仍用上传的封面' }}
            </p>
          </el-form-item>

          <template v-if="coverTemplate">
            <el-form-item label="封面标题" style="margin-bottom: 12px">
              <el-input
                v-model="coverTitle"
                placeholder="例如：{library}"
                maxlength="100"
              />
            </el-form-item>
            <el-form-item label="封面副标题" style="margin-bottom: 12px">
              <el-input
                v-model="coverSubtitle"
                placeholder="例如：{type} · {year}"
                maxlength="100"
              />
            </el-form-item>
            <p class="drawer-hint" style="margin: -6px 0 10px">
              可用变量：<code>{library}</code> 媒体库名、<code>{type}</code> 内容类型、<code>{year}</code> 当前年份。
              只渲染纯文字，不执行 HTML 或样式；字体不可用时自动省略文字，不影响封面生成。
            </p>

            <div class="cover-preview-wrap">
              <div class="cover-preview-box">
                <img
                  v-if="coverPreviewUrl"
                  :src="coverPreviewUrl"
                  alt="封面预览"
                  class="cover-preview-img"
                />
                <el-empty
                  v-else-if="coverPreviewLoading"
                  description="正在渲染预览…"
                  :image-size="52"
                />
                <div v-else class="cover-preview-hint">
                  {{ coverPreviewError || '选好样式后自动出预览' }}
                </div>
              </div>
              <div class="cover-preview-actions">
                <el-button
                  size="small"
                  :loading="coverPreviewLoading"
                  :disabled="!canPreviewCover()"
                  @click="loadCoverPreview"
                >
                  刷新预览
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="coverSaving"
                  :disabled="!canPreviewCover()"
                  @click="saveCoverConfig"
                >
                  生成并保存
                </el-button>
                <el-button
                  v-if="libFormTarget?.cover_template"
                  size="small"
                  :loading="coverRegenerating"
                  @click="regenerateCover"
                >
                  按最新海报重新生成
                </el-button>
                <p v-if="!canPreviewCover()" class="drawer-hint">
                  新建的库还没有条目，保存后扫出内容才能生成封面。
                </p>
              </div>
            </div>
          </template>
        </div>
        <div class="scrape-block">
          <h3>云盘挂载</h3>
          <p class="drawer-hint">
            rclone remote 与服务账号统一在「存储来源」页管理。
          </p>
          <div class="scrape-actions">
            <RouterLink to="/mounts"><el-button size="small" type="primary">去存储来源页管理</el-button></RouterLink>
          </div>
        </div>
        <div class="scrape-block">
          <h3>条目级元数据</h3>
          <p class="drawer-hint">
            条目元数据刷新、手动绑定 TMDB、补全进度已经移到
            <RouterLink to="/metadata-sources">「元数据来源」</RouterLink>页：
            它们回答的是「这一条的元数据从哪来、错了怎么纠」，与按库的扫描 / 刮削策略不是一层。
          </p>
          <div class="scrape-actions">
            <RouterLink to="/metadata-sources">
              <el-button size="small" type="primary">去元数据来源页</el-button>
            </RouterLink>
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

          <!-- 一句话策略摘要：路径 / 轮询间隔 / 刮削策略，不点进设置也知道这个库怎么跑 -->
          <div class="lib-summary" :title="libSummaryTitle(l)">{{ libSummary(l) }}</div>

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

    <!--
      媒体库配置：新建与编辑共用这一张单页表单（借鉴 Emby Manager）。
      以前这里是两个地方——「新建弹窗」管一半、「设置抽屉」管另一半，路径在设置里只能看
      不能改、启用状态与追新监听干脆没入口。现在一张表单分组改完，每个选项都有一句
      人话说明，推荐项直接标出来。
    -->
    <el-drawer
      v-model="libFormVisible"
      :title="libForm.id ? `媒体库设置 · ${libFormTarget?.name || ''}` : '新建媒体库'"
      size="min(680px, 96vw)"
      :before-close="beforeCloseForm"
    >
      <div class="library-settings">
        <!-- 分组一：基础信息 -->
        <div class="settings-section">
          <div class="settings-section-title">基础信息</div>
          <p class="form-hint">
            库叫什么、装什么内容、归谁管。「归属」两项决定了这个库的内容会不会出现在
            别的服 / 别的机器上，是多服多机部署里最容易配错的一处。
          </p>
          <el-form label-position="top">
            <el-form-item label="媒体库名称">
              <el-input v-model="libForm.name" placeholder="如：电影库 / 剧集库 / 动漫库" />
            </el-form-item>

            <el-form-item label="内容类型">
              <el-select
                v-model="libForm.collection_type"
                style="width: 100%"
                popper-class="lib-opt-popper"
              >
                <el-option
                  v-for="t in COLLECTION_TYPES"
                  :key="t.value"
                  :label="optionLabel(COLLECTION_TYPES, t.value)"
                  :value="t.value"
                >
                  <div class="opt">
                    <div class="opt-label">{{ t.label }}</div>
                    <div class="opt-hint">{{ t.hint }}</div>
                  </div>
                </el-option>
              </el-select>
              <p class="field-help">{{ optionOf(COLLECTION_TYPES, libForm.collection_type)?.hint }}</p>
            </el-form-item>

            <el-form-item label="启用状态">
              <el-switch v-model="libForm.is_enabled" active-text="启用" inactive-text="停用" />
              <p class="field-help">
                停用后客户端看不到这个库，它也不参与定时扫描与追新；已入库的条目留着不删，
                重新启用就回来。
              </p>
            </el-form-item>

            <el-form-item label="归属服">
              <el-select
                v-model="libForm.realm_id"
                clearable
                placeholder="未标注（所有服可见）"
                style="width: 100%"
              >
                <el-option
                  v-for="r in realmOptions"
                  :key="r.id"
                  :label="r.id === realm.activeId ? `${r.name}（推荐 · 当前服）` : r.name"
                  :value="r.id"
                />
              </el-select>
              <p class="field-help">
                内容隔离的边界：只有这个服的 EA 会向客户端提供这个库。换服等于把内容交给另一个服，
                绑定在旧服上的挂载会跟着搬过去。
              </p>
            </el-form-item>

            <el-form-item v-if="!libFormTarget?.is_virtual" label="归属播放节点">
              <el-select
                v-model="libForm.node_id"
                clearable
                placeholder="未分配（所有节点可见，由面板扫描）"
                style="width: 100%"
              >
                <el-option v-for="n in nodes" :key="n.id" :label="nodeLabel(n)" :value="n.id" />
              </el-select>
              <p class="field-help">
                决定「谁向客户端展示这个库、谁来扫描它」。内容只在那台机器上（本机目录 / 只在那里配了的
                rclone）就分配给它；留空则所有节点可见、由面板扫。
              </p>
            </el-form-item>

            <el-form-item v-if="!libFormTarget?.is_virtual" label="存储挂载">
              <el-select
                v-model="libForm.mount_ids"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="不绑定（只用下面的媒体路径）"
                style="width: 100%"
              >
                <el-option v-for="m in mounts" :key="m.id" :label="m.name" :value="m.id" />
              </el-select>
              <p class="field-help">
                网盘 / WebDAV / 115 直挂这类远程来源用它，扫描时与「媒体路径」一起遍历；挂载在
                「存储来源」页创建与测试。路径与挂载可以同时用。
              </p>
            </el-form-item>
          </el-form>
        </div>

        <!-- 虚拟库：没有自己的目录与挂载，后面两组不适用 -->
        <div v-if="libFormTarget?.is_virtual" class="settings-paths">
          <span>虚拟媒体库</span>
          <p>
            按发行平台「{{ libFormTarget.platform || '—' }}」聚合库里已识别到的条目，条目仍归属原媒体库。
            它没有自己的目录与挂载，所以下面不列「媒体路径」与「追新监听」——要改内容来源，去改原始媒体库。
          </p>
        </div>

        <!-- 分组二：扫描性能 -->
        <div class="settings-section">
          <div class="settings-section-title">扫描性能与刮削</div>
          <p class="form-hint">
            这一组决定扫描时花多少力气：刮削策略决定要不要回头重刮「已经刮过」的条目，
            直接影响 TMDB 配额与扫描耗时。
          </p>
          <el-form label-position="top">
            <el-form-item label="刮削策略">
              <el-select
                v-model="libForm.scrape_policy"
                style="width: 100%"
                popper-class="lib-opt-popper"
              >
                <el-option
                  v-for="p in POLICIES"
                  :key="p.value"
                  :label="optionLabel(POLICIES, p.value)"
                  :value="p.value"
                >
                  <div class="opt">
                    <div class="opt-label">
                      {{ p.label }}<span v-if="p.recommended" class="opt-rec">（推荐）</span>
                    </div>
                    <div class="opt-hint">{{ p.hint }}</div>
                  </div>
                </el-option>
              </el-select>
              <p class="field-help">{{ optionOf(POLICIES, libForm.scrape_policy)?.hint }}</p>
            </el-form-item>

            <el-form-item label="115 账号">
              <el-select
                v-model="libForm.account_115_id"
                clearable
                placeholder="默认账号（面板级 PAN115_COOKIE）"
                style="width: 100%"
              >
                <el-option v-for="a in panAccounts" :key="a.id" :label="a.name" :value="a.id" />
              </el-select>
              <p class="field-help">这个库用哪个 115 配置档转存 / 下载；留空 = 用默认账号。</p>
            </el-form-item>

            <div class="settings-paths">
              <span>定时扫描（全局）</span>
              <p v-if="autoScan">
                {{ autoScan.enabled
                  ? `已开启：每天 ${autoScan.time} 把所有启用库入队扫描（增量，没变化的目录跳过）。`
                  : '未开启：只在手动点「扫描」、或追新发现新文件时扫。' }}
                上次执行：{{ autoScan.last_run || '还没有执行过' }}。
              </p>
              <p v-else>读取中…</p>
              <p>所有启用库共用一份计划，开关与时间在本页下方「元数据与刮削」里改。</p>
            </div>
          </el-form>
        </div>

        <!-- 分组三：媒体库封面 -->
        <div v-if="libFormTarget" class="settings-section">
          <div class="settings-section-title">媒体库封面</div>
          <p class="form-hint">
            封面只影响列表与首页的观感，不参与刮削，扫描也不会覆盖它。支持 JPG / PNG / WebP，单张最大 8 MB。
          </p>
          <div class="lib-cover-edit">
            <div class="lib-cover-thumb">
              <img
                v-if="libFormTarget.cover_url && coverUrls[libFormTarget.id]"
                :src="coverUrls[libFormTarget.id]"
                :alt="`${libFormTarget.name} 封面`"
              />
              <div v-else class="lib-cover-empty">
                <Film :size="20" />
                <span>未设置封面</span>
              </div>
            </div>
            <div class="lib-cover-ops">
              <el-upload
                :accept="'image/jpeg,image/png,image/webp'"
                :show-file-list="false"
                :disabled="!!coverUploading[libFormTarget.id]"
                :http-request="(options: UploadRequestOptions) => requestCoverUpload(libFormTarget!, options)"
              >
                <el-button :loading="!!coverUploading[libFormTarget.id]">
                  <ImagePlus :size="14" style="margin-right: 4px" />{{ libFormTarget.cover_url ? '更换封面' : '上传封面' }}
                </el-button>
              </el-upload>
              <el-button v-if="libFormTarget.cover_url" @click="removeCover(libFormTarget)">
                <X :size="14" style="margin-right: 4px" />移除封面
              </el-button>
            </div>
          </div>
        </div>

        <!-- 分组四：媒体路径 -->
        <div v-if="!libFormTarget?.is_virtual" class="settings-section">
          <div class="settings-section-title">媒体路径</div>
          <p class="form-hint">
            决定扫描哪些目录，<strong>一行一个</strong>。也可以写 <code>mount://挂载ID/子目录</code>
            只扫挂载下的某个子目录（如 <code>mount://2/video/剧集/动漫剧</code>）；想扫整个挂载就用上面「存储挂载」。
          </p>
          <el-form label-position="top">
            <el-form-item>
              <div class="paths-input-row">
                <el-input
                  v-model="libForm.paths"
                  type="textarea"
                  :rows="4"
                  placeholder="服务器上的媒体目录，一行一个&#10;/media/movies&#10;/media/tv/breaking-bad"
                />
                <el-button class="paths-browse-btn" @click="pathPicker?.open()">浏览</el-button>
              </div>
              <div class="form-hint">
                点「浏览」逐级选挂载目录；切到「多选」可一次勾多个目录批量追加，已存在的会自动跳过并报出个数。
                <strong>不要带方括号或引号</strong>（从 JSON 里粘贴时容易带上，保存就会报「目录不存在或不可读」）。
                共 {{ parsePaths(libForm.paths).length }} 条路径。
              </div>
            </el-form-item>
          </el-form>
        </div>

        <!-- 分组五：目录变更监听 -->
        <div v-if="libFormTarget && !libFormTarget.is_virtual" class="settings-section">
          <div class="settings-section-title">目录变更监听</div>
          <p class="form-hint">
            「追新」每隔几分钟扫一遍目录，发现新视频文件就自动触发一次扫描 + 刮削（NFO 优先 → TMDB → 豆瓣），
            不用等手动扫描。开关与间隔是全局的，纳不纳入某个库在这里定。
          </p>
          <el-form label-position="top">
            <el-form-item label="本库是否纳入追新监听">
              <el-switch
                :model-value="libForm.chase"
                :loading="chaseLibSaving"
                :disabled="chaseCoversAll()"
                active-text="纳入"
                inactive-text="不纳入"
                @change="onChaseSwitch"
              />
              <p class="field-help">
                <template v-if="chaseCoversAll()">
                  当前是「所有启用库都监听」（清单留空即代表全部），此时单独关掉本库没有意义。
                  要只排除某几个库，先在别的库上打开它、让清单列出来，再回来关本库。
                </template>
                <template v-else-if="chaseNew">
                  改动即时生效：写进全局追新清单（当前 {{ chaseLibraryIds().length }} 个库）。
                </template>
                <template v-else>追新配置读取中…</template>
              </p>
            </el-form-item>
            <div class="settings-paths">
              <span>追新总开关（全局）</span>
              <p v-if="chaseNew">
                {{ chaseNew.enabled
                  ? `已开启 · 每 ${chaseNew.interval} 分钟检查一次`
                  : '未开启（开关与间隔在本页下方「元数据与刮削」）' }}
              </p>
              <p v-if="chaseNew?.last_check">
                上次检查：{{ chaseNew.last_check }} ｜ 上轮发现 {{ chaseNew.last_found }} 个新文件
              </p>
            </div>
          </el-form>
        </div>
      </div>

      <template #footer>
        <div class="lib-form-foot">
          <span class="lib-form-dirty">
            {{ libFormDirty
              ? (libFormPathsChanged ? '路径已改：保存后需要重新扫描一次' : '有未保存的改动')
              : '' }}
          </span>
          <div class="lib-form-foot-btns">
            <el-button :disabled="!libFormDirty" @click="revertForm">还原</el-button>
            <el-button @click="cancelForm">取消</el-button>
            <el-button
              v-if="libForm.id && libFormPathsChanged"
              :loading="libFormSaving"
              @click="saveForm(true)"
            >
              保存并扫描
            </el-button>
            <el-button type="primary" :loading="libFormSaving" @click="saveForm(false)">
              {{ libForm.id ? '保存' : '创建' }}
            </el-button>
          </div>
        </div>
      </template>
    </el-drawer>
    <MountPathPicker ref="pathPicker" @select="onPickMountPath" @select-multi="onPickMountPaths" />

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
.sa-panel {
  margin-top: 6px;
  padding: 8px;
  background: rgba(0,0,0,0.2);
  border-radius: 6px;
}
.sa-search {
  margin-bottom: 6px;
}
.sa-email-list {
  max-height: 220px;
  overflow-y: auto;
  font-size: 12px;
}
.sa-email-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  color: var(--text-secondary);
}
.sa-email-item.sa-disabled {
  opacity: 0.45;
}
.sa-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #555;
  flex-shrink: 0;
}
.sa-dot.on {
  background: var(--success);
}
.sa-email {
  word-break: break-all;
  flex: 1;
}
.sa-project {
  font-size: 11px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}
.sa-enabled-count {
  color: var(--success);
  font-size: 12px;
}
</style>
