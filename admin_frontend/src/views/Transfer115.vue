<script setup lang="ts">
/**
 * 115 下载与转存
 *
 * - 账号配置档：多账号 + 默认账号 + 启用开关；Cookie 不回传明文，可即时校验
 * - 转存任务：粘贴分享链接（或口令文本）→ 选择目标目录 → 转存 / 只取下载地址
 *   任务状态、已完成文件与下载地址都会持久化，进程重启后自动续跑，不会重复转存
 * - 未配置或失效的 Cookie 不会丢任务：置为「等待 Cookie」，修好后重试即可继续
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpen, Link2, Plus, RefreshCw, RotateCw, Trash2, XCircle } from 'lucide-vue-next'
import {
  browsePan115,
  cancelPan115Task,
  createPan115Account,
  createPan115Task,
  deletePan115Account,
  fetchLibraries,
  fetchPan115Accounts,
  fetchPan115Tasks,
  parsePan115Share,
  retryPan115Task,
  updatePan115Account,
  verifyPan115Account,
  verifyPan115Cookie,
} from '@/api/admin'
import type { EmbyLibrary, Pan115Account, Pan115DirEntry, Pan115Task } from '@/types'

const tab = ref<'tasks' | 'accounts'>('tasks')
const loading = ref(false)
const tasks = ref<Pan115Task[]>([])
const accounts = ref<Pan115Account[]>([])
const libraries = ref<EmbyLibrary[]>([])
const envCookieConfigured = ref(false)
const activeCount = ref(0)
const waitingAuthCount = ref(0)

async function load() {
  loading.value = true
  try {
    const [t, a, l] = await Promise.all([
      fetchPan115Tasks({ limit: 100 }),
      fetchPan115Accounts(),
      fetchLibraries(),
    ])
    tasks.value = t.tasks
    activeCount.value = t.active_count
    waitingAuthCount.value = t.waiting_auth_count
    accounts.value = a.accounts
    envCookieConfigured.value = a.env_cookie_configured
    libraries.value = l.libraries.filter((x) => !x.is_virtual)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

function badgeClass(status: string): string {
  if (status === 'done') return 'ok'
  if (status === 'running') return 'running'
  if (status === 'waiting_auth') return 'warn'
  if (status === 'failed') return 'bad'
  return 'off'
}

function accountName(id: number | null): string {
  if (!id) return '默认账号'
  return accounts.value.find((a) => a.id === id)?.name || `#${id}`
}

function libraryName(id: number | null): string {
  if (!id) return '不触发扫描'
  return libraries.value.find((l) => l.id === id)?.name || `#${id}`
}

async function retry(t: Pan115Task) {
  await retryPan115Task(t.id)
  ElMessage.success('已重新入队，已完成文件不会重复转存')
  setTimeout(load, 800)
}

async function cancel(t: Pan115Task) {
  await ElMessageBox.confirm(`取消任务「${t.share_code}」？已完成的部分会保留。`, '确认取消', {
    type: 'warning',
  })
  await cancelPan115Task(t.id)
  ElMessage.success('已取消')
  load()
}

// ==================== 新建任务 ====================

const createVisible = ref(false)
const parsing = ref(false)
const creating = ref(false)
const parsedCode = ref('')
const form = reactive({
  share_url: '',
  mode: 'receive',
  account_id: undefined as number | undefined,
  library_id: undefined as number | undefined,
  cookie: '',
  target_cid: '0',
  target_path: '/',
})

function openCreate() {
  form.share_url = ''
  form.mode = 'receive'
  form.account_id = undefined
  form.library_id = undefined
  form.cookie = ''
  form.target_cid = '0'
  form.target_path = '/'
  parsedCode.value = ''
  buildPathStack()
  createVisible.value = true
}

async function doParse() {
  if (!form.share_url.trim()) {
    ElMessage.warning('请粘贴 115 分享链接或口令')
    return
  }
  parsing.value = true
  try {
    const res = await parsePan115Share(form.share_url.trim())
    parsedCode.value = res.parsed.receive_code
      ? `${res.parsed.share_code}（提取码 ${res.parsed.receive_code}）`
      : res.parsed.share_code
  } catch {
    parsedCode.value = ''
  } finally {
    parsing.value = false
  }
}

async function submitCreate() {
  if (!form.share_url.trim()) {
    ElMessage.warning('请粘贴 115 分享链接')
    return
  }
  creating.value = true
  try {
    await createPan115Task({
      share_url: form.share_url.trim(),
      target_cid: form.target_cid,
      target_path: form.target_path,
      account_id: form.account_id ?? null,
      library_id: form.library_id ?? null,
      mode: form.mode,
      cookie: form.cookie.trim() || undefined,
    })
    ElMessage.success('任务已创建')
    createVisible.value = false
    tab.value = 'tasks'
    setTimeout(load, 800)
  } finally {
    creating.value = false
  }
}

// ==================== 目标目录浏览 ====================

const pathStack = ref<{ cid: string; name: string }[]>([])
const dirs = ref<Pan115DirEntry[]>([])
const browsing = ref(false)
const cookieSource = ref('')

function buildPathStack() {
  pathStack.value = [{ cid: '0', name: '根目录' }]
  dirs.value = []
}

async function browse(cid: string) {
  browsing.value = true
  try {
    const res = await browsePan115({
      cid,
      account_id: form.account_id,
      cookie: form.cookie.trim() || undefined,
    })
    dirs.value = res.entries
    cookieSource.value = res.cookie_source
  } finally {
    browsing.value = false
  }
}

function enterDir(entry: Pan115DirEntry) {
  pathStack.value.push({ cid: entry.cid || entry.fid, name: entry.name })
  browse(pathStack.value[pathStack.value.length - 1].cid)
}

function popTo(index: number) {
  pathStack.value = pathStack.value.slice(0, index + 1)
  browse(pathStack.value[index].cid)
}

function pickCurrentDir() {
  const current = pathStack.value[pathStack.value.length - 1]
  form.target_cid = current.cid
  form.target_path = '/' + pathStack.value.slice(1).map((p) => p.name).join('/')
  ElMessage.success(`目标目录：${form.target_path}`)
}

async function startBrowse() {
  buildPathStack()
  await browse('0')
}

// ==================== 账号配置档 ====================

const accVisible = ref(false)
const accEditing = ref<Pan115Account | null>(null)
const accSaving = ref(false)
const accTesting = ref(false)
const accForm = reactive({ name: '', cookie: '', is_default: false, is_enabled: true, remark: '' })

function openAccount(a: Pan115Account | null) {
  accEditing.value = a
  accForm.name = a?.name || ''
  accForm.cookie = ''
  accForm.is_default = a?.is_default ?? false
  accForm.is_enabled = a?.is_enabled ?? true
  accForm.remark = a?.remark || ''
  accVisible.value = true
}

async function saveAccount() {
  if (!accForm.name.trim()) {
    ElMessage.warning('请填写账号名称')
    return
  }
  if (!accEditing.value && !accForm.cookie.trim()) {
    ElMessage.warning('请粘贴 115 Cookie')
    return
  }
  accSaving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: accForm.name.trim(),
      is_default: accForm.is_default,
      is_enabled: accForm.is_enabled,
      remark: accForm.remark,
    }
    if (accForm.cookie.trim()) payload.cookie = accForm.cookie.trim()
    if (accEditing.value) {
      await updatePan115Account(accEditing.value.id, payload)
    } else {
      await createPan115Account(payload as { name: string; cookie: string })
    }
    ElMessage.success('已保存')
    accVisible.value = false
    load()
  } finally {
    accSaving.value = false
  }
}

async function testCookie() {
  if (!accForm.cookie.trim() && !accEditing.value) {
    ElMessage.warning('请粘贴 Cookie 后再测试')
    return
  }
  accTesting.value = true
  try {
    if (accForm.cookie.trim()) {
      const res = await verifyPan115Cookie(accForm.cookie.trim())
      ElMessage[res.result.ok ? 'success' : 'error'](
        res.result.ok ? 'Cookie 有效' : res.result.message || 'Cookie 无效'
      )
    } else if (accEditing.value) {
      const res = await verifyPan115Account(accEditing.value.id)
      ElMessage[res.result.ok ? 'success' : 'error'](
        res.result.ok ? 'Cookie 有效' : res.result.message || 'Cookie 无效'
      )
      load()
    }
  } finally {
    accTesting.value = false
  }
}

async function removeAccount(a: Pan115Account) {
  await ElMessageBox.confirm(
    `删除账号「${a.name}」？绑定了它的媒体库会回退到默认账号。`,
    '确认删除',
    { type: 'warning' }
  )
  await deletePan115Account(a.id)
  ElMessage.success('已删除')
  load()
}

const targetLabel = computed(() => form.target_path || '/')
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">115 下载与转存</h1>
        <p class="admin-page-subtitle">
          分享链接转存进 115 网盘，完成后自动触发媒体库扫描入库
          <span v-if="activeCount > 0" class="mini-badge running" style="margin-left: 6px">
            {{ activeCount }} 个进行中
          </span>
          <span v-if="waitingAuthCount > 0" class="mini-badge warn" style="margin-left: 6px">
            {{ waitingAuthCount }} 个任务等待 Cookie
          </span>
        </p>
      </div>
      <div class="toolbar">
        <el-button :loading="loading" @click="load"><RefreshCw :size="14" /></el-button>
        <el-button type="primary" @click="openCreate">
          <Plus :size="14" style="margin-right: 4px" />新建转存任务
        </el-button>
      </div>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane label="转存任务" name="tasks">
        <div class="admin-card">
          <el-table :data="tasks" style="width: 100%" empty-text="暂无任务">
            <el-table-column label="分享码" min-width="150">
              <template #default="{ row }">
                <span class="mono">{{ row.share_code }}</span>
                <span class="s-method">{{ row.mode_label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="140">
              <template #default="{ row }">
                <span class="mini-badge" :class="badgeClass(row.status)">{{ row.status_label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="180">
              <template #default="{ row }">
                <div class="progress-track">
                  <div class="progress-fill" :style="{ width: `${row.progress || 0}%` }" />
                </div>
                <span class="progress-num">{{ row.done_files }}/{{ row.total_files }} 个文件</span>
              </template>
            </el-table-column>
            <el-table-column label="账号 / 目标" min-width="180">
              <template #default="{ row }">
                <div>{{ accountName(row.account_id) }}</div>
                <div class="mono muted">{{ row.target_path || '（115 根目录）' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="完成后扫描" min-width="120">
              <template #default="{ row }">{{ libraryName(row.library_id) }}</template>
            </el-table-column>
            <el-table-column label="创建时间" width="150">
              <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="row.status !== 'done'"
                  size="small"
                  text
                  type="primary"
                  @click="retry(row)"
                >
                  <RotateCw :size="12" style="margin-right: 2px" />重试
                </el-button>
                <el-button
                  v-if="row.status === 'pending' || row.status === 'waiting_auth'"
                  size="small"
                  text
                  type="danger"
                  @click="cancel(row)"
                >
                  <XCircle :size="12" />
                </el-button>
              </template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="detail">
                  <div v-if="row.error" class="detail-error">{{ row.error }}</div>
                  <div class="detail-title">分享内容（{{ row.items.length }} 项）</div>
                  <div v-for="it in row.items" :key="it.fid" class="detail-line">
                    <span class="mono">{{ it.is_dir ? '📁' : '🎬' }}</span>
                    {{ it.name }}
                  </div>
                  <template v-if="row.urls.length">
                    <div class="detail-title">下载地址（{{ row.urls.length }}）</div>
                    <div v-for="(u, i) in row.urls" :key="i" class="detail-line mono">{{ u }}</div>
                  </template>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="账号配置" name="accounts">
        <div class="admin-card">
          <div class="acc-head">
            <div>
              <div class="acc-title">115 Cookie 配置档</div>
              <div class="acc-hint">
                支持多账号与默认账号，媒体库可单独绑定；未绑定 / 未配置时回退到默认账号
                <template v-if="envCookieConfigured">，环境变量 PAN115_COOKIE 也会作为兜底</template>
              </div>
            </div>
            <el-button type="primary" @click="openAccount(null)">
              <Plus :size="14" style="margin-right: 4px" />添加账号
            </el-button>
          </div>
          <el-table :data="accounts" style="width: 100%" empty-text="还没有账号配置档">
            <el-table-column label="名称" prop="name" min-width="140" />
            <el-table-column label="Cookie" width="120">
              <template #default="{ row }"><span class="mono muted">{{ row.cookie_preview || '—' }}</span></template>
            </el-table-column>
            <el-table-column label="默认" width="80">
              <template #default="{ row }">
                <span v-if="row.is_default" class="mini-badge ok">默认</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <span class="mini-badge" :class="row.is_enabled ? 'ok' : 'off'">
                  {{ row.is_enabled ? '启用' : '停用' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="最近校验" min-width="180">
              <template #default="{ row }">
                <span v-if="row.last_verified_at">
                  {{ fmtDate(row.last_verified_at) }}
                  <span :class="row.last_verify_ok ? 'ok-text' : 'bad-text'">
                    {{ row.last_verify_ok ? '有效' : '无效' }}
                  </span>
                  <span v-if="row.last_verify_message && !row.last_verify_ok" class="muted">
                    · {{ row.last_verify_message }}
                  </span>
                </span>
                <span v-else class="muted">未校验</span>
              </template>
            </el-table-column>
            <el-table-column label="备注" prop="remark" min-width="120" />
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openAccount(row)">编辑</el-button>
                <el-button size="small" text type="danger" @click="removeAccount(row)">
                  <Trash2 :size="12" />
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建任务 -->
    <el-dialog v-model="createVisible" title="新建 115 转存任务" width="560px">
      <el-form label-width="96px">
        <el-form-item label="分享链接">
          <el-input
            v-model="form.share_url"
            type="textarea"
            :rows="2"
            placeholder="粘贴 https://115.com/s/xxxx?password=abcd，或「链接 提取码：abcd」整段口令"
          />
          <div class="parse-row">
            <el-button size="small" :loading="parsing" @click="doParse">
              <Link2 :size="12" style="margin-right: 2px" />解析
            </el-button>
            <span v-if="parsedCode" class="parsed">已识别：{{ parsedCode }}</span>
          </div>
        </el-form-item>
        <el-form-item label="模式">
          <el-radio-group v-model="form.mode">
            <el-radio-button value="receive">转存到网盘</el-radio-button>
            <el-radio-button value="download">只取下载地址</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="账号">
          <el-select v-model="form.account_id" clearable placeholder="默认账号" style="width: 220px">
            <el-option v-for="a in accounts" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="临时 Cookie">
          <el-input v-model="form.cookie" placeholder="可选：只用于本次任务，不保存" />
        </el-form-item>
        <el-form-item label="目标目录">
          <div class="browser">
            <div class="browser-bar">
              <el-button size="small" :loading="browsing" @click="startBrowse">
                <FolderOpen :size="12" style="margin-right: 2px" />浏览
              </el-button>
              <span class="browser-path">{{ targetLabel }}</span>
              <el-button size="small" text type="primary" @click="pickCurrentDir">用当前目录</el-button>
            </div>
            <div v-if="pathStack.length" class="crumbs">
              <span
                v-for="(p, i) in pathStack"
                :key="p.cid + i"
                class="crumb-item"
                @click="popTo(i)"
              >{{ p.name }}</span>
            </div>
            <div v-if="dirs.length" class="dir-list">
              <div v-for="d in dirs" :key="d.fid" class="dir-item" @click="enterDir(d)">
                📁 {{ d.name }}
              </div>
            </div>
            <div v-else-if="cookieSource" class="muted dir-empty">
              该目录下没有子目录{{ cookieSource ? `（来源：${cookieSource}）` : '' }}
            </div>
          </div>
        </el-form-item>
        <el-form-item label="完成后扫描">
          <el-select v-model="form.library_id" clearable placeholder="不触发扫描" style="width: 220px">
            <el-option v-for="l in libraries" :key="l.id" :label="l.name" :value="l.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建任务</el-button>
      </template>
    </el-dialog>

    <!-- 账号编辑 -->
    <el-dialog v-model="accVisible" :title="accEditing ? '编辑 115 账号' : '添加 115 账号'" width="480px">
      <el-form label-width="88px">
        <el-form-item label="名称">
          <el-input v-model="accForm.name" placeholder="如：主号 / 影库专号" />
        </el-form-item>
        <el-form-item label="Cookie">
          <el-input
            v-model="accForm.cookie"
            type="textarea"
            :rows="3"
            :placeholder="accEditing ? '留空表示不修改' : '粘贴浏览器里的 uid=…; cid=…; seid=…; kid=…'"
          />
        </el-form-item>
        <el-form-item label="默认账号">
          <el-switch v-model="accForm.is_default" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="accForm.is_enabled" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="accForm.remark" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :loading="accTesting" @click="testCookie">测试 Cookie</el-button>
        <el-button @click="accVisible = false">取消</el-button>
        <el-button type="primary" :loading="accSaving" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
.muted { color: var(--color-text-muted, #737373); }
.ok-text { color: var(--success, #22c55e); }
.bad-text { color: #ef4444; }

.s-method {
  font-size: 10px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  padding: 1px 6px;
  margin-left: 6px;
  color: var(--color-text-secondary, #a3a3a3);
}

.progress-track { height: 4px; border-radius: 2px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
.progress-fill { height: 100%; background: var(--gradient-brand); border-radius: 2px; transition: width 0.4s ease; }
.progress-num { font-size: 11px; color: var(--color-text-muted, #737373); }

.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; font-weight: 600; }
.mini-badge.ok { background: var(--success-bg); color: var(--success); }
.mini-badge.off { background: rgba(255, 255, 255, 0.08); color: var(--color-text-muted, #737373); }
.mini-badge.running { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.mini-badge.warn { background: rgba(245, 158, 11, 0.16); color: #f59e0b; }
.mini-badge.bad { background: rgba(239, 68, 68, 0.16); color: #ef4444; }

.detail { padding: 6px 18px 12px; }
.detail-title { font-size: 12px; font-weight: 600; margin: 8px 0 4px; color: var(--color-text-secondary, #a3a3a3); }
.detail-line { font-size: 12px; padding: 2px 0; word-break: break-all; }
.detail-error { font-size: 12px; color: #f59e0b; margin-bottom: 6px; }

.acc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.acc-title { font-size: 15px; font-weight: 700; }
.acc-hint { font-size: 12px; color: var(--color-text-muted, #737373); margin-top: 4px; max-width: 640px; }

.parse-row { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.parsed { font-size: 12px; color: var(--success, #22c55e); }

.browser { width: 100%; border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.1)); border-radius: 8px; padding: 8px; }
.browser-bar { display: flex; align-items: center; gap: 8px; }
.browser-path { flex: 1; font-size: 12px; font-family: ui-monospace, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.crumbs { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.crumb-item { font-size: 12px; cursor: pointer; color: var(--primary); }
.crumb-item::after { content: ' /'; color: var(--color-text-muted, #737373); }
.dir-list { margin-top: 6px; max-height: 160px; overflow-y: auto; }
.dir-item { font-size: 12px; padding: 4px 6px; border-radius: 6px; cursor: pointer; }
.dir-item:hover { background: var(--bg-hover, rgba(255, 255, 255, 0.06)); }
.dir-empty { margin-top: 6px; font-size: 12px; }
</style>
