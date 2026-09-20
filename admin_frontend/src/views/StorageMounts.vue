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
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Cloud, FolderOpen, HardDrive, Network, Pencil, Plug, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import {
  browseMount,
  createMount,
  deleteMount,
  fetchMounts,
  fetchPan115Accounts,
  fetchRcloneRemotes,
  testMountConfig,
  testSavedMount,
  updateMount,
} from '@/api/admin'
import type { MountDirEntry, MountTypeMeta, Pan115Account, StorageMount } from '@/types'

const mounts = ref<StorageMount[]>([])
const types = ref<MountTypeMeta[]>([])
const accounts = ref<Pan115Account[]>([])
const loading = ref(false)

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
const isRemote = computed(() => currentType.value?.kind === 'remote')
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

async function load() {
  loading.value = true
  try {
    const [res, acc] = await Promise.all([
      fetchMounts(),
      fetchPan115Accounts().catch(() => ({ accounts: [], env_cookie_configured: false })),
    ])
    mounts.value = res.mounts
    types.value = res.mount_types
    accounts.value = acc.accounts
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

async function testSaved(m: StorageMount) {
  const res = await testSavedMount(m.id)
  if (res.success) ElMessage.success(`${m.name}：${res.result.message}`)
  else ElMessage.error(`${m.name}：${res.result.message}`)
  load()
}

async function remove(m: StorageMount) {
  const bound = m.library_ids?.length || 0
  await ElMessageBox.confirm(
    bound
      ? `挂载「${m.name}」已被 ${bound} 个媒体库绑定，删除会同时解绑（不删除源上的文件），确定吗？`
      : `删除挂载「${m.name}」？不会删除源上的文件。`,
    '确认删除',
    { type: 'warning' }
  )
  const res = await deleteMount(m.id)
  ElMessage.success(res.unbound_libraries ? `已删除，并解绑 ${res.unbound_libraries} 个媒体库` : '已删除')
  load()
}

async function toggleEnabled(m: StorageMount) {
  await updateMount(m.id, { is_enabled: m.is_enabled })
  ElMessage.success(m.is_enabled ? `「${m.name}」已启用（重扫后生效）` : `「${m.name}」已停用（重扫后生效）`)
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
        <h1 class="admin-page-title">存储挂载</h1>
        <p class="admin-page-subtitle">
          媒体库的内容来源：本机目录 / STRM 直链 / 115 / 阿里云盘 / 夸克 / OneDrive / S3 / WebDAV / AList / rclone
        </p>
      </div>
      <div class="toolbar">
        <el-button type="primary" @click="openCreate">
          <Plus :size="14" style="margin-right: 4px" />新建挂载
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <!-- 类型说明 -->
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

    <!-- 挂载列表 -->
    <div class="mount-grid">
      <div v-for="m in mounts" :key="m.id" class="admin-card mount-card">
        <div class="mount-head">
          <component :is="iconOf(m.mount_type)" :size="15" />
          <span class="mount-name">{{ m.name }}</span>
          <span class="mini-badge">{{ m.mount_type_label }}</span>
          <span class="mini-badge" :class="m.is_enabled ? 'ok' : 'off'">
            {{ m.is_enabled ? '启用' : '停用' }}
          </span>
        </div>
        <div class="mount-path">{{ sourceSummary(m) }}</div>
        <div class="mount-meta">
          绑定 {{ m.library_ids.length }} 个媒体库
          <template v-if="m.last_checked_at">
            · 上次测试 {{ fmtDate(m.last_checked_at) }}
            <span :class="m.last_check_ok ? 'ok-text' : 'err-text'">
              {{ m.last_check_ok ? '正常' : '失败' }}
            </span>
          </template>
          <template v-else> · 未测试</template>
        </div>
        <div v-if="m.last_check_message" class="mount-msg">{{ m.last_check_message }}</div>
        <div class="mount-foot">
          <el-switch v-model="m.is_enabled" size="small" @change="toggleEnabled(m)" />
          <div class="mount-actions">
            <el-button v-if="canBrowseSaved(m)" size="small" text @click="openBrowse(m)">
              <FolderOpen :size="13" style="margin-right: 2px" />浏览
            </el-button>
            <el-button size="small" text @click="testSaved(m)">
              <Plug :size="13" style="margin-right: 2px" />测试
            </el-button>
            <el-button size="small" text @click="openEdit(m)"><Pencil :size="13" /></el-button>
            <el-button size="small" text type="danger" @click="remove(m)"><Trash2 :size="13" /></el-button>
          </div>
        </div>
      </div>
      <div v-if="mounts.length === 0 && !loading" class="admin-card empty-card">
        还没有挂载。建一个挂载，再到「媒体库管理」把它绑定到库上即可扫描。
      </div>
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `编辑挂载：${editing.name}` : '新建挂载'"
      width="520px"
    >
      <el-form label-width="96px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：115 影库 / 本地电影盘" maxlength="60" />
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
            <el-button :loading="remotesLoading" size="small" @click="loadRcloneRemotes">
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
        <el-button :loading="testing" @click="testForm">测试连接</el-button>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
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
  margin-bottom: 16px;
}

.type-card { padding: 12px 14px; }
.type-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.type-name { font-weight: 600; font-size: 13px; }
.type-hint { margin: 0; font-size: 11.5px; line-height: 1.5; color: var(--color-text-secondary, #a3a3a3); }

.mount-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.mount-card { display: flex; flex-direction: column; gap: 6px; }
.mount-head { display: flex; align-items: center; gap: 8px; }
.mount-name { font-weight: 700; font-size: 15px; }
.mount-path {
  font-size: 11.5px;
  font-family: ui-monospace, monospace;
  color: var(--color-text-muted, #737373);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mount-meta { font-size: 11.5px; color: var(--color-text-secondary, #a3a3a3); }
.mount-msg {
  font-size: 11px;
  color: var(--color-text-muted, #737373);
  background: rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  padding: 4px 8px;
}
.mount-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 4px; }
.mount-actions { display: flex; align-items: center; }
.empty-card { text-align: center; color: var(--color-text-muted, #737373); padding: 40px 0; }

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
</style>
