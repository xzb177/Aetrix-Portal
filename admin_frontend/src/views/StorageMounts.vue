<script setup lang="ts">
/**
 * 存储挂载：媒体库的内容来源
 *
 * 一个挂载就是「把内容接进媒体库」的一种方式：
 * - 本机目录：rclone / CloudDrive2 / SMB / NFS 已经挂到本机后的目录；
 * - STRM 目录：本地只放 .strm 小文件，内容是播放直链；
 * - 网盘直挂：115 / 阿里云盘 / 夸克 / OneDrive，直接读网盘，不用挂到本机；
 * - 网关与对象存储：WebDAV / AList；S3 兼容对象存储（MinIO / R2 / Backblaze）。
 *
 * 类型列表、表单字段、必填项、目录浏览入口全部由后端下发的类型元数据驱动，
 * 所以后端新增一种挂载类型时，这个页面不用改。
 *
 * 挂载本身不拥有条目：媒体库通过「绑定挂载」引用它，同一个挂载可被多个库共用。
 *
 * v2.6.24：挂载是**一个服一个**的（存储是主机相对资源：乙服的 EA 未必碰得到甲服挂的盘）。
 * 默认只看当前服的挂载，顶部可切到「全部服」做跨服汇总；新建 / 编辑时可以指定归属服，
 * 换归属服时引用它的媒体库会跟着走（避免库跨服引用存储）。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { AlertTriangle, Cloud, FolderOpen, HardDrive, Info, Network, Pencil, Plug, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import {
  browseMount,
  createMount,
  deleteMount,
  fetchLibraries,
  fetchMounts,
  fetchPan115Accounts,
  fetchRcloneRemotes,
  probeMountsHealth,
  refreshEaMountHealth,
  testMountConfig,
  testSavedMount,
  updateMount,
} from '@/api/admin'
import type {
  EaMountHealth,
  EmbyLibrary,
  MountDirEntry,
  MountTypeMeta,
  Pan115Account,
  PlaybackNode,
  StorageMount,
} from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'
import NoticePanel from '@/components/NoticePanel.vue'

const realm = useRealmStore()
/** 统计范围：当前服（默认）或全部服 */
const scope = ref<'realm' | 'all'>('realm')
/** 后端给的挂载 id → 服名映射（跨服汇总时用） */
const realmNames = ref<Record<string, string>>({})
/**
 * 媒体库清单：挂载 → 「被哪些库用着」（只读，不额外发请求）
 *
 * 以前这一列只写「绑定 N 个」，要弄清是哪几个库就得跳到媒体库页一个个对；
 * 在这里直接显示库名，存储与内容的关系在一页里看得完。
 */
const libraries = ref<EmbyLibrary[]>([])

const libraryNames = computed(() => {
  const map = new Map<number, string>()
  for (const lib of libraries.value) map.set(lib.id, lib.name)
  return map
})

function usedByNames(mount: StorageMount): string[] {
  return (mount.library_ids || [])
    .map((id) => libraryNames.value.get(id) || `已删除的库 #${id}`)
}

/** 挂载 → 引用它的媒体库（直接给链接，点一下到那个库的卡片） */
function usedByLibraries(mount: StorageMount): { id: number; label: string }[] {
  return (mount.library_ids || []).map((id) => ({
    id, label: libraryNames.value.get(id) || `已删除的库 #${id}`,
  }))
}

/** 挂载列表：手机端挂载名做标题，来源与可达性仍保留 */
const columns = computed<DataColumn[]>(() => [
  { key: 'name', label: '挂载', minWidth: 170, mobile: 'title' },
  { key: 'mount_type_label', label: '类型', width: 110 },
  ...(scope.value === 'all'
    ? [{ key: 'realm', label: '归属服', minWidth: 120 } as DataColumn]
    : []),
  { key: 'source', label: '来源', minWidth: 200 },
  { key: 'libraries', label: '被哪些媒体库使用', minWidth: 170 },
  { key: 'reach', label: 'EM / EA 可达', width: 200 },
  { key: 'is_enabled', label: '状态', width: 90 },
  // 浏览 / 测试 / 编辑 / 删除收进「管理」弹窗：行里只留一个入口
  { key: 'actions', label: '操作', width: 100, fixed: 'right', align: 'right' },
])

/** 归属服展示名：未标注 = 所有服可见的内容来源（老数据就是这个口径） */
function realmLabel(m: StorageMount): string {
  if (!m.realm_id) return '未标注'
  return realmNames.value[String(m.realm_id)] || realm.realms.find((r) => r.id === m.realm_id)?.name || `#${m.realm_id}`
}

const mounts = ref<StorageMount[]>([])
const types = ref<MountTypeMeta[]>([])
/** 类型说明收起时的一句话：各几种（不写死类型名，后端加一种这里不用改） */
const typeSummary = computed(() => {
  const remote = types.value.filter((t) => t.kind === 'remote').length
  return `${types.value.length} 种：本机 ${types.value.length - remote} 种 · 远程 ${remote} 种`
})
const accounts = ref<Pan115Account[]>([])
const loading = ref(false)
/** 当前出流的节点 + EA 体检快照（快照缺失时 ea_reachable 为 null） */
const playbackNode = ref<PlaybackNode>('panel')
const eaHealth = ref<EaMountHealth>({ ok: false, checked_at: null, error: '' })
const checkingPanel = ref(false)
const checkingEa = ref(false)

const dialogVisible = ref(false)
const editing = ref<StorageMount | null>(null)
const saving = ref(false)
const testing = ref(false)
const testMessage = ref('')
const form = ref({
  name: '',
  mount_type: 'local',
  path: '',
  config: {} as Record<string, string>,
  is_enabled: true,
  remark: '',
  /** 归属服：新建时默认当前服 */
  realm_id: null as number | null,
})

/** rclone：远端已配置的 remote（点「获取 remote 列表」才拉） */
const rcloneRemotes = ref<string[]>([])
const remotesLoading = ref(false)

const browseVisible = ref(false)
const browseTarget = ref<StorageMount | null>(null)
const browseRel = ref('/')
const browseEntries = ref<MountDirEntry[]>([])
const browseLoading = ref(false)

const currentType = computed<MountTypeMeta | undefined>(
  () => types.value.find((t) => t.value === form.value.mount_type)
)
/** 当前类型下需要渲染的配置项（115 的账号用下拉框，其它按文本输入） */
const currentFields = computed(() => currentType.value?.fields ?? [])
/** 保存过的挂载能不能浏览目录：类型元数据说了算（本机类型有路径也行） */
const canBrowseSaved = (m: StorageMount) => !!typeMeta(m.mount_type)?.browse || !!m.path

function typeMeta(mountType: string): MountTypeMeta | undefined {
  return types.value.find((t) => t.value === mountType)
}

/** 图标按分组区分：本机盘 / 云盘 / 网关（WebDAV、AList） */
function iconOf(mountType: string) {
  const group = typeMeta(mountType)?.group || 'local'
  if (group === 'cloud') return Cloud
  if (group === 'gateway') return Network
  return HardDrive
}

/** 概要：本机类型显示路径，远程类型显示第一个「能代表来源」的字段 */
function sourceSummary(m: StorageMount): string {
  const meta = typeMeta(m.mount_type)
  if (meta?.needs_path) return m.path || '未配置路径'
  for (const f of meta?.fields ?? []) {
    const value = (m.config?.[f.key] ?? '').toString().trim()
    if (value) {
      const shown = f.secret ? '已配置' : value
      return `${f.label} ${shown}`
    }
  }
  return m.path || '未配置'
}

/** 可达性徽标：true=可达 / false=不可达 / null=未体检（或已停用） */
function reachText(v: boolean | null | undefined): string {
  if (v === true) return '可达'
  if (v === false) return '不可达'
  return '未体检'
}

function reachClass(v: boolean | null | undefined): string {
  if (v === true) return 'ok'
  if (v === false) return 'danger'
  return 'off'
}

/** 谁在出流：只有 EA 时，「EA 不可达」才会真的导致播放失败 */
const playbackNodeLabel = computed(() => ({
  ea: 'EA（分离部署的网关）',
  external: '外部 Emby',
  panel: '面板自身（一体化）',
}[playbackNode.value] || playbackNode.value))

/** 被媒体库引用、却在当前播放节点（EA）上不可达的挂载：会「扫得到、播不了」 */
const eaBlockedMounts = computed(() => {
  if (playbackNode.value !== 'ea') return []
  return mounts.value.filter(
    (m) => m.is_enabled && m.library_ids.length > 0 && m.ea_reachable === false
  )
})

/** EA 快照本身失效时，逐条「 EA 可达」其实是旧结论 */
const eaSnapshotStale = computed(() => playbackNode.value === 'ea' && !!eaHealth.value.error)

async function runPanelHealth() {
  checkingPanel.value = true
  try {
    const res = await probeMountsHealth()
    ElMessage.success(`本机体检完成：${res.ok_count}/${res.total} 条可达`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    checkingPanel.value = false
  }
}

async function runEaHealth() {
  checkingEa.value = true
  try {
    const res = await refreshEaMountHealth()
    if (res.success) ElMessage.success('EA 体检完成：已刷新每条挂载在 EA 上的可达性')
    else ElMessage.error(res.health?.error || 'EA 体检失败')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    checkingEa.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [res, acc, libs] = await Promise.all([
      // realm_id=0 → 全部服；其余按服过滤（后端以当前服作为兜底）
      fetchMounts(scope.value === 'all' ? 0 : realm.activeId ?? 0),
      fetchPan115Accounts().catch(() => ({ accounts: [], env_cookie_configured: false })),
      // 媒体库清单只为把「绑定 N 个」写成人能认的名字，拉不到不影响挂载管理
      fetchLibraries().catch(() => ({ libraries: [] as EmbyLibrary[] })),
    ])
    mounts.value = res.mounts
    libraries.value = libs.libraries
    types.value = res.mount_types
    accounts.value = acc.accounts
    playbackNode.value = res.playback_node || 'panel'
    eaHealth.value = res.ea_health || { ok: false, checked_at: null, error: '' }
    realmNames.value = res.realm_names || {}
  } finally {
    loading.value = false
  }
}

onMounted(load)

function resetForm() {
  form.value = {
    name: '',
    mount_type: types.value[0]?.value || 'local',
    path: '',
    config: {},
    is_enabled: true,
    remark: '',
    realm_id: realm.activeId ?? null,
  }
  testMessage.value = ''
}

function openCreate() {
  editing.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(m: StorageMount) {
  editing.value = m
  form.value = {
    name: m.name,
    mount_type: m.mount_type,
    path: m.path,
    config: { ...(m.config || {}) },
    is_enabled: m.is_enabled,
    remark: m.remark,
    realm_id: m.realm_id ?? realm.activeId ?? null,
  }
  testMessage.value = ''
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写挂载名称')
    return
  }
  if (currentType.value?.needs_path && !form.value.path.trim()) {
    ElMessage.warning('请填写目录路径')
    return
  }
  // 必填字段由后端类型元数据声明；密钥字段在编辑时留空表示沿用已保存的值
  for (const f of currentFields.value) {
    if (!f.required) continue
    if (editing.value && f.secret) continue
    if (!(form.value.config[f.key] ?? '').toString().trim()) {
      ElMessage.warning(`请填写${f.label}`)
      return
    }
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      mount_type: form.value.mount_type,
      path: form.value.path.trim(),
      config: form.value.config,
      is_enabled: form.value.is_enabled,
      remark: form.value.remark,
      // 归属服：留空交给后端按当前服归（老代码路径也就能继续用）
      realm_id: form.value.realm_id ?? undefined,
    }
    if (editing.value) {
      const res = await updateMount(editing.value.id, payload)
      ElMessage.success(
        res.rescan_required ? '挂载已保存：重新扫描对应媒体库后生效' : '挂载已保存'
      )
    } else {
      await createMount(payload)
      ElMessage.success('挂载已创建：到媒体库页把它绑定到库上即可扫描')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function testForm() {
  testing.value = true
  try {
    const res = await testMountConfig({
      mount_type: form.value.mount_type,
      path: form.value.path.trim(),
      config: form.value.config,
    })
    testMessage.value = res.result?.message || ''
    if (res.success) ElMessage.success(`连接正常：${testMessage.value}`)
    else ElMessage.error(testMessage.value || '连接失败')
  } finally {
    testing.value = false
  }
}

// ==================== 挂载管理弹窗（v2.29.0） ====================
// 以前行尾摆着「浏览 / 测试 / 编辑 / 删除」四个按钮，而「这条挂载到底谁能用」还得回头
// 看那一行的小徽标；现在一个入口，弹窗里把来源、被谁用、EM/EA 两边的结论与测试结果放在一起。
const manage = ref({ visible: false, row: null as StorageMount | null })

function openManage(m: StorageMount) {
  manage.value = { visible: true, row: m }
}

/** 动作后刷新列表，并把弹窗里的挂载换成最新快照（测试结果 / 绑定情况就地变化） */
async function refreshManage(id: number) {
  await load()
  const fresh = mounts.value.find((m) => m.id === id)
  if (fresh) {
    manage.value.row = fresh
  } else {
    manage.value.visible = false
  }
}

/** 从弹窗进编辑 / 浏览：先关掉这一层，避免两个弹窗叠着 */
function editFromManage(m: StorageMount) {
  manage.value.visible = false
  openEdit(m)
}

function browseFromManage(m: StorageMount) {
  manage.value.visible = false
  openBrowse(m)
}

async function testSaved(m: StorageMount) {
  const res = await testSavedMount(m.id)
  if (res.success) ElMessage.success(`${m.name}：${res.result.message}`)
  else ElMessage.error(`${m.name}：${res.result.message}`)
  await refreshManage(m.id)
}

async function remove(m: StorageMount) {
  const bound = m.library_ids?.length || 0
  try {
    await ElMessageBox.confirm(
      bound
        ? `挂载「${m.name}」已被 ${bound} 个媒体库绑定，删除会同时解绑（不删除源上的文件），确定吗？`
        : `删除挂载「${m.name}」？不会删除源上的文件。`,
      '确认删除',
      { type: 'warning' }
    )
  } catch {
    return
  }
  const res = await deleteMount(m.id)
  ElMessage.success(res.unbound_libraries ? `已删除，并解绑 ${res.unbound_libraries} 个媒体库` : '已删除')
  await refreshManage(m.id)
}

async function toggleEnabled(m: StorageMount) {
  await updateMount(m.id, { is_enabled: m.is_enabled })
  ElMessage.success(m.is_enabled ? `「${m.name}」已启用（重扫后生效）` : `「${m.name}」已停用（重扫后生效）`)
  await refreshManage(m.id)
}

async function openBrowse(m: StorageMount) {
  browseTarget.value = m
  browseRel.value = '/'
  browseVisible.value = true
  await browseTo('/')
}

async function browseTo(rel: string) {
  if (!browseTarget.value) return
  browseLoading.value = true
  try {
    const res = await browseMount(browseTarget.value.id, rel)
    browseRel.value = res.rel || '/'
    browseEntries.value = res.entries
  } finally {
    browseLoading.value = false
  }
}

/** 正在编辑的类型声明了 root_key（115 的 cid / S3 的 prefix / 网盘的目录 ID）时才回写 */
const browseRootKey = computed(() => {
  const target = browseTarget.value
  if (!target || !dialogVisible.value) return ''
  if (form.value.mount_type !== target.mount_type) return ''
  return typeMeta(target.mount_type)?.root_key || ''
})

function entryIdLabel(entry: MountDirEntry): string {
  if (!entry.entry_id || !entry.is_dir) return ''
  return browseRootKey.value === 'prefix' ? entry.entry_id : `ID ${entry.entry_id}`
}

/** rclone：用当前表单里的 RC 地址 / 路径去问远端有哪些 remote（未保存的配置也能查） */
async function loadRcloneRemotes() {
  remotesLoading.value = true
  try {
    const params: Record<string, string> = {
      mode: form.value.config.mode || 'rc',
      rc_url: form.value.config.rc_url || '',
      rc_user: form.value.config.rc_user || '',
      rc_pass: form.value.config.rc_pass || '',
      rclone_bin: form.value.config.rclone_bin || '',
      rclone_config: form.value.config.rclone_config || '',
    }
    const res = await fetchRcloneRemotes(params)
    rcloneRemotes.value = res.remotes
    ElMessage.success(
      res.remotes.length ? `已获取 ${res.remotes.length} 个 remote` : '远端没有配置任何 remote'
    )
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '获取 remote 列表失败')
  } finally {
    remotesLoading.value = false
  }
}

/** 目录选择：点目录即把「根目录标识」写回表单（没有这个概念的挂载就是进入目录） */
function pickEntry(entry: MountDirEntry) {
  if (!entry.is_dir) return
  const key = browseRootKey.value
  if (!key) {
    browseTo(entry.rel)
    return
  }
  const value = key === 'prefix' ? entry.rel.replace(/^\//, '') : (entry.entry_id || '0')
  form.value.config = { ...form.value.config, [key]: value }
  ElMessage.success(
    key === 'prefix'
      ? `已把「${entry.name}」设为挂载根前缀（${value}）`
      : `已把「${entry.name}」设为挂载根目录（ID ${value}）`
  )
  browseVisible.value = false
  dialogVisible.value = true
}

function fmtDate(s: string | null): string {
  return s ? s.slice(0, 16).replace('T', ' ') : '—'
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">存储来源</h1>
        <p class="admin-page-subtitle">
          媒体库的内容来源：本机目录 / STRM 直链 / 115 / 阿里云盘 / 夸克 / OneDrive / S3 / WebDAV / AList / rclone；
          每条都标明被哪些媒体库使用
        </p>
      </div>
      <div class="toolbar">
        <el-radio-group v-model="scope" size="small" @change="load">
          <el-radio-button value="realm">当前服</el-radio-button>
          <el-radio-button value="all">全部服</el-radio-button>
        </el-radio-group>
        <el-button type="primary" @click="openCreate">
          <Plus :size="14" style="margin-right: 4px" />新建挂载
        </el-button>
        <el-button :loading="checkingPanel" @click="runPanelHealth">
          <Plug :size="14" style="margin-right: 4px" />本机体检
        </el-button>
        <el-button :loading="checkingEa" @click="runEaHealth">
          <Plug :size="14" style="margin-right: 4px" />EA 体检
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <!--
      挂载里的本机路径、rclone RC 地址这类配置是「跟着服务器走」的：
      后台测试跑在 EM 里，通过不代表那台 EA 能播。被媒体库引用却在 EA 上不可达的
      挂载会「扫得到、播不了」，所以单独报红。
    -->
    <el-alert
      v-if="eaBlockedMounts.length"
      class="ea-warning"
      type="error"
      :closable="false"
      show-icon
    >
      <template #title>
        <AlertTriangle :size="14" style="margin-right: 5px" />
        {{ eaBlockedMounts.length }} 条被媒体库引用的挂载在 {{ playbackNodeLabel }} 上不可达
      </template>
      <div class="ea-warning-body">
        这些库会扫得到、播不了：{{ eaBlockedMounts.map((m) => m.name).join('、') }}。<br />
        「本机 / 已挂载目录」「STRM 直链目录」的路径与 rclone 的 RC 地址都是那台机器上的
        资源，要在 EA 所在机器上配好（或把它们改成网络型来源：115 / WebDAV / AList / S3）。
      </div>
    </el-alert>

    <el-alert
      v-else-if="eaSnapshotStale"
      class="ea-warning"
      type="warning"
      :closable="false"
      show-icon
      :title="`EA 体检未完成：${eaHealth.error}（下面的 EA 可达性可能不是最新的，可点「EA 体检」重试）`"
    />

    <!--
      类型说明：默认收起（v2.32.0）
      八张说明卡常驻时把挂载清单挤到下一屏，要新建来源的人在表单里就能选到这些类型。
    -->
    <NoticePanel
      title="支持的来源类型"
      :summary="typeSummary"
      :icon="Info"
      storage-key="mounts-types"
    >
      <div class="type-grid">
        <div v-for="t in types" :key="t.value" class="admin-card type-card">
          <div class="type-head">
            <component :is="iconOf(t.value)" :size="15" />
            <span class="type-name">{{ t.label }}</span>
            <span class="mini-badge" :class="t.kind === 'remote' ? 'remote' : 'local'">
              {{ t.kind === 'remote' ? '远程' : '本机' }}
            </span>
          </div>
          <p class="type-hint">{{ t.hint }}</p>
        </div>
      </div>
    </NoticePanel>

    <!-- 挂载列表 -->
    <div class="admin-card">
      <DataTable
        :rows="mounts"
        :columns="columns"
        :loading="loading"
        empty="还没有存储来源。建一条，再到「媒体库」把它绑定到库上即可扫描。"
      >
        <template #cell-name="{ row }">
          <span class="mount-head">
            <component :is="iconOf(row.mount_type)" :size="15" />
            <span class="mount-name">{{ row.name }}</span>
          </span>
        </template>

        <template #cell-mount_type_label="{ row }">
          <span class="mini-badge">{{ row.mount_type_label }}</span>
        </template>

        <template #cell-realm="{ row }">
          <span class="mini-badge" :class="row.realm_id ? '' : 'muted'">{{ realmLabel(row) }}</span>
        </template>

        <template #cell-source="{ row }">
          <span class="mount-path">{{ sourceSummary(row) }}</span>
        </template>

        <template #cell-libraries="{ row }">
          <div v-if="!row.library_ids.length" class="used-none">未被使用</div>
          <div v-else class="used-cell" :title="usedByNames(row).join('、')">
            <RouterLink
              v-for="lib in usedByLibraries(row).slice(0, 2)"
              :key="lib.id"
              :to="`/emby`"
              class="used-link"
            >{{ lib.label }}</RouterLink>
            <span v-if="row.library_ids.length > 2" class="used-more">
              +{{ row.library_ids.length - 2 }} 个
            </span>
          </div>
        </template>

        <template #cell-reach="{ row }">
          <div class="reach-cell">
            <span class="reach-line">
              <span class="reach-tag">EM</span>
              <span class="mini-badge" :class="reachClass(row.em_reachable)">
                {{ reachText(row.em_reachable) }}
              </span>
              <el-tooltip
                v-if="row.em_message"
                :content="row.em_message"
                placement="top"
              >
                <Info :size="12" class="check-info" />
              </el-tooltip>
            </span>
            <span class="reach-line">
              <span class="reach-tag">EA</span>
              <span class="mini-badge" :class="reachClass(row.ea_reachable)">
                {{ reachText(row.ea_reachable) }}
              </span>
              <el-tooltip
                v-if="row.ea_message"
                :content="row.ea_message"
                placement="top"
              >
                <Info :size="12" class="check-info" />
              </el-tooltip>
            </span>
            <em v-if="row.em_checked_at" class="muted reach-time">
              测于 {{ fmtDate(row.em_checked_at) }}
            </em>
          </div>
        </template>

        <template #cell-is_enabled="{ row }">
          <el-switch v-model="row.is_enabled" size="small" @change="toggleEnabled(row)" />
        </template>

        <template #cell-actions="{ row }">
          <!-- 一个入口：浏览 / 测试 / 编辑 / 停用 / 删除 都在弹窗里（原来这行有 4 个按钮） -->
          <el-button size="small" plain @click="openManage(row)">管理</el-button>
        </template>
      </DataTable>
    </div>

    <!--
      挂载管理（弹窗）：来源、归属服、被哪些媒体库使用、EM 与 EA 两边的可达结论、上次测试结果
      都在这里；需要改配置再进「编辑」，不用在一行小徽标里猜。
    -->
    <el-dialog v-model="manage.visible" :title="`管理来源：${manage.row?.name || ''}`" width="560px">
      <div v-if="manage.row" class="mg-body">
        <div class="kv-list">
          <div class="kv-row"><span class="kv-key">名称</span><span class="kv-value">{{ manage.row.name }}</span></div>
          <div class="kv-row"><span class="kv-key">类型 / 归属服</span>
            <span class="kv-value">{{ manage.row.mount_type_label }} · {{ realmLabel(manage.row) }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">来源</span>
            <span class="kv-value mono">{{ sourceSummary(manage.row) }}</span>
          </div>
          <div class="kv-row"><span class="kv-key">被哪些媒体库使用</span>
            <span class="kv-value">
              <template v-if="!manage.row.library_ids.length">未被使用</template>
              <template v-else>{{ usedByNames(manage.row).join('、') }}</template>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">EM（面板）</span>
            <span class="kv-value">
              <span class="mini-badge" :class="reachClass(manage.row.em_reachable)">
                {{ reachText(manage.row.em_reachable) }}
              </span>
              <span v-if="manage.row.em_message" class="mg-msg">{{ manage.row.em_message }}</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">EA（播放节点）</span>
            <span class="kv-value">
              <span class="mini-badge" :class="reachClass(manage.row.ea_reachable)">
                {{ reachText(manage.row.ea_reachable) }}
              </span>
              <span v-if="manage.row.ea_message" class="mg-msg">{{ manage.row.ea_message }}</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">上次测试</span>
            <span class="kv-value">
              {{ fmtDate(manage.row.last_checked_at) }}
              <span v-if="manage.row.last_check_message" class="mg-msg">{{ manage.row.last_check_message }}</span>
            </span>
          </div>
          <div class="kv-row"><span class="kv-key">备注</span><span class="kv-value">{{ manage.row.remark || '—' }}</span></div>
          <div class="kv-row"><span class="kv-key">状态</span>
            <span class="kv-value">
              <el-switch v-model="manage.row.is_enabled" size="small" @change="toggleEnabled(manage.row)" />
              <span class="mg-msg">{{ manage.row.is_enabled ? '启用中' : '已停用（扫描跳过，客户端也无内容）' }}</span>
            </span>
          </div>
        </div>

        <p class="mg-hint">
          停用只是让扫描与播放不再用它（源上的文件不动）；删除会同时解绑引用它的媒体库。
          两条可达结论分别来自面板自己的「测试连接」与 EA 的挂载体检——EA 显示「未体检」时，
          先去「服务器与线路」页拉一次体检。
        </p>
      </div>

      <template #footer>
        <div class="mg-footer">
          <el-button v-if="manage.row" type="danger" plain @click="remove(manage.row)">
            <Trash2 :size="13" style="margin-right: 3px" />删除
          </el-button>
          <div class="mg-footer-right">
            <el-button @click="manage.visible = false">关闭</el-button>
            <template v-if="manage.row">
              <el-button v-if="canBrowseSaved(manage.row)" @click="browseFromManage(manage.row)">
                <FolderOpen :size="13" style="margin-right: 3px" />浏览
              </el-button>
              <el-button @click="testSaved(manage.row)">
                <Plug :size="13" style="margin-right: 3px" />测试连接
              </el-button>
              <el-button type="primary" @click="editFromManage(manage.row)">
                <Pencil :size="13" style="margin-right: 3px" />编辑
              </el-button>
            </template>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `编辑挂载：${editing.name}` : '新建挂载'"
      width="520px"
    >
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：115 影库 / 本地电影盘" maxlength="60" />
        </el-form-item>
        <!-- 挂载是主机相对资源：乙服的 EA 未必碰得到甲服挂的盘，所以要能指定归属 -->
        <el-form-item label="归属服">
          <el-select v-model="form.realm_id" placeholder="选择归属服" style="width: 220px">
            <el-option v-for="r in realm.realms" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
          <div class="form-hint">
            只有归属服的播放节点会用它；换归属服时，引用它的媒体库会一起跟过去。
          </div>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.mount_type" :disabled="!!editing" style="width: 220px">
            <el-option v-for="t in types" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
          <div v-if="editing" class="form-hint">
            类型决定条目路径的解析方式，不支持改类型；要换请新建挂载后重新绑定。
          </div>
        </el-form-item>
        <el-form-item v-if="currentType?.needs_path" label="目录路径">
          <el-input v-model="form.path" :placeholder="form.mount_type === 'strm' ? '/media/strm' : '/media/movies'" />
          <div class="form-hint">服务器本机路径。rclone / CloudDrive2 / SMB 挂到本机后填挂载点。</div>
        </el-form-item>
        <el-form-item v-for="f in currentFields" :key="f.key" :label="f.label">
          <el-select
            v-if="f.type === 'account115'"
            v-model="form.config[f.key]"
            clearable
            placeholder="默认账号"
            style="width: 220px"
          >
            <el-option v-for="a in accounts" :key="a.id" :label="a.name" :value="String(a.id)" />
          </el-select>
          <div v-else-if="f.type === 'rclone_fs'" class="fs-row">
            <el-select
              v-model="form.config[f.key]"
              filterable
              allow-create
              default-first-option
              placeholder="gdrive:Movies"
              style="width: 260px"
            >
              <el-option v-for="r in rcloneRemotes" :key="r" :label="r" :value="r" />
            </el-select>
            <el-button native-type="button" :loading="remotesLoading" size="small" @click="loadRcloneRemotes">
              获取 remote 列表
            </el-button>
            <div class="form-hint">
              列表来自远端的 rclone 配置；选一个 remote 后可以继续补子目录（如 gdrive:Movies）。
            </div>
          </div>
          <el-select
            v-else-if="f.type === 'select'"
            v-model="form.config[f.key]"
            style="width: 220px"
          >
            <el-option
              v-for="o in f.options || []"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
          <el-input
            v-else
            v-model="form.config[f.key]"
            :show-password="!!f.secret"
            :placeholder="f.placeholder"
          />
          <div v-if="f.secret && editing?.secret_keys?.includes(f.key)" class="form-hint">
            已保存密钥，留空表示不修改。
          </div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
          <span class="form-hint" style="margin-left: 8px">停用后不再参与扫描（已入库条目保留）。</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" maxlength="200" placeholder="选填" />
        </el-form-item>
        <el-alert v-if="testMessage" :title="testMessage" type="info" :closable="false" />
      </el-form>
      <template #footer>
        <el-button native-type="button" :loading="testing" @click="testForm">测试连接</el-button>
        <el-button native-type="button" @click="dialogVisible = false">取消</el-button>
        <el-button native-type="button" type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 目录浏览 -->
    <el-dialog v-model="browseVisible" :title="`浏览：${browseTarget?.name || ''}`" width="560px">
      <div class="browse-bar">
        <el-button size="small" text :disabled="browseRel === '/'" @click="browseTo('/')">根目录</el-button>
        <span class="browse-path">{{ browseRel }}</span>
        <el-button size="small" text :loading="browseLoading" @click="browseTo(browseRel)">刷新</el-button>
      </div>
      <div class="browse-list">
        <div
          v-for="e in browseEntries"
          :key="e.rel"
          class="browse-item"
          :class="{ dir: e.is_dir }"
          @click="pickEntry(e)"
        >
          <FolderOpen v-if="e.is_dir" :size="14" />
          <span class="browse-name">{{ e.name }}</span>
          <span v-if="entryIdLabel(e)" class="browse-id">{{ entryIdLabel(e) }}</span>
          <span v-else class="browse-size">{{ e.is_dir ? '' : (e.size / 1024 / 1024).toFixed(1) + ' MB' }}</span>
        </div>
        <div v-if="browseEntries.length === 0 && !browseLoading" class="browse-empty">目录为空</div>
      </div>
      <template #footer>
        <span v-if="browseRootKey" class="form-hint">
          点目录可把它设为挂载根{{ browseRootKey === 'prefix' ? '前缀' : '目录' }}。
        </span>
        <el-button @click="browseVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
.fs-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.type-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 12px;
}

.type-card { padding: 12px 14px; }
.type-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.type-name { font-weight: 600; font-size: 13px; }
.type-hint { margin: 0; font-size: 11.5px; line-height: 1.5; color: var(--color-text-secondary, #a3a3a3); }

.mount-head { display: inline-flex; align-items: center; gap: 8px; }
.mount-name { font-weight: 600; font-size: var(--font-size-md); }
.mount-path {
  font-size: var(--font-size-xs);
  font-family: var(--font-mono);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.check-state { display: inline-flex; align-items: center; gap: 6px; }
.check-state em { font-style: normal; font-size: var(--font-size-xs); }
.check-info { color: var(--text-muted); margin-left: 4px; vertical-align: -2px; }

.form-hint { font-size: 11px; color: var(--color-text-muted, #737373); margin-top: 4px; }
.ok-text { color: var(--success, #22c55e); }
.err-text { color: var(--danger, #ef4444); }

.browse-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.browse-path {
  flex: 1;
  font-size: 11.5px;
  font-family: ui-monospace, monospace;
  color: var(--color-text-muted, #737373);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.browse-list { max-height: 380px; overflow-y: auto; border-radius: 10px; background: rgba(255, 255, 255, 0.03); }
.browse-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 13px;
  cursor: default;
}
.browse-item.dir { cursor: pointer; }
.browse-item.dir:hover { background: rgba(255, 255, 255, 0.06); }
.browse-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.browse-id, .browse-size { font-size: 11px; color: var(--color-text-muted, #737373); }
.browse-empty { padding: 20px; text-align: center; font-size: 12px; color: var(--color-text-muted, #737373); }

.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; font-weight: 600; }
.mini-badge.ok { background: var(--success-bg); color: var(--success); }
.mini-badge.off { background: rgba(255, 255, 255, 0.08); color: var(--color-text-muted, #737373); }
.mini-badge.remote { background: rgba(59, 130, 246, 0.16); color: #3b82f6; }
.mini-badge.local { background: rgba(16, 185, 129, 0.16); color: #10b981; }

/* EM / EA 可达性：两个播放节点各自能不能碰到这条挂载 */
.reach-cell { display: flex; flex-direction: column; gap: 3px; }

/* 被哪些媒体库使用：直接写库名，不写「绑定 N 个」
   （挂载与内容的关系在这一页看得完，不用去媒体库页一个个对）*/
.used-cell { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.used-link {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--primary);
  font-size: var(--font-size-xs);
  text-decoration: none;
}
.used-link:hover { color: var(--text-primary); text-decoration: underline; }
.used-more { font-size: var(--font-size-xs); color: var(--text-muted); }
.used-none { font-size: var(--font-size-xs); color: var(--text-faint); }
.reach-line { display: inline-flex; align-items: center; gap: 5px; }
.reach-tag { font-size: 10px; font-weight: 700; color: var(--text-muted); letter-spacing: 0.4px; }
.reach-time { font-style: normal; font-size: var(--font-size-xs); }

.ea-warning { margin-bottom: 12px; }
.ea-warning-body { margin-top: 4px; font-size: var(--font-size-sm); line-height: 1.7; }

/* 管理弹窗：详情用全局 .kv-list，只补长文案与页脚布局 */
.mg-body { display: flex; flex-direction: column; gap: 12px; }
.mg-body .kv-row .kv-value { text-align: left; }
.mg-msg { display: block; margin-top: 3px; font-size: var(--font-size-xs); color: var(--text-muted); word-break: break-word; }
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
</style>
