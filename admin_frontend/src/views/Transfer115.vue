<script setup lang="ts">
/**
 * 115 下载与转存
 *
 * - 账号配置档：多账号 + 默认账号 + 启用开关；Cookie 不回传明文，可即时校验
 * - 转存任务：粘贴分享链接（或口令文本）→ 选择目标目录 → 转存 / 只取下载地址
 *   任务状态、已完成文件与下载地址都会持久化，进程重启后自动续跑，不会重复转存
 * - 未配置或失效的 Cookie 不会丢任务：置为「等待 Cookie」，修好后重试即可继续
 *
 * v2.6.11：两张表改用 DataTable（手机变卡片列表），页面里写死的灰度色换成主题令牌，
 * 行内「重试 / 取消」由文字按钮改为描边按钮，手机上不再挤成一条被截断的窄条。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ExternalLink, FolderOpen, Link2, Plus, RefreshCw, RotateCw, Trash2, XCircle } from 'lucide-vue-next'
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
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const tab = ref<'tasks' | 'accounts'>('tasks')
const loading = ref(false)
const tasks = ref<Pan115Task[]>([])
const accounts = ref<Pan115Account[]>([])
const libraries = ref<EmbyLibrary[]>([])
const envCookieConfigured = ref(false)
const activeCount = ref(0)
const waitingAuthCount = ref(0)

const taskColumns: DataColumn[] = [
  { key: 'share_code', label: '分享码', minWidth: 170, mobile: 'title' },
  { key: 'status', label: '状态', width: 140 },
  { key: 'progress', label: '进度', width: 190 },
  { key: 'target', label: '账号 / 目标', minWidth: 190, mobile: 'hide' },
  { key: 'library', label: '完成后扫描', minWidth: 130, mobile: 'hide' },
  { key: 'created_at', label: '创建时间', width: 150 },
  { key: 'actions', label: '操作', width: 190, fixed: 'right', align: 'right' },
]

const accountColumns: DataColumn[] = [
  { key: 'name', label: '名称', minWidth: 150, mobile: 'title' },
  { key: 'cookie_preview', label: 'Cookie', width: 130, mobile: 'hide' },
  { key: 'is_default', label: '默认', width: 80 },
  { key: 'is_enabled', label: '状态', width: 100 },
  { key: 'last_verified_at', label: '最近校验', minWidth: 190 },
  { key: 'remark', label: '备注', minWidth: 120, mobile: 'hide' },
  { key: 'actions', label: '操作', width: 170, fixed: 'right', align: 'right' },
]

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
  if (status === 'failed') return 'danger'
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
        </p>
        <div v-if="activeCount > 0 || waitingAuthCount > 0" class="page-tags">
          <span v-if="activeCount > 0" class="mini-badge running">{{ activeCount }} 个进行中</span>
          <span v-if="waitingAuthCount > 0" class="mini-badge warn">
            {{ waitingAuthCount }} 个任务等待 Cookie
          </span>
        </div>
      </div>
      <div class="admin-page-actions">
        <el-button :loading="loading" aria-label="刷新" @click="load">
          <RefreshCw :size="15" />
        </el-button>
        <el-button type="primary" @click="openCreate">
          <Plus :size="15" style="margin-right: 4px" />新建转存任务
        </el-button>
      </div>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane label="转存任务" name="tasks">
        <div class="admin-card">
          <DataTable
            :rows="tasks"
            :columns="taskColumns"
            :loading="loading"
            empty="暂无任务"
            clickable
          >
            <template #cell-share_code="{ row }">
              <span class="mono">{{ row.share_code }}</span>
              <span class="s-method">{{ row.mode_label }}</span>
            </template>

            <template #cell-status="{ row }">
              <span class="mini-badge" :class="badgeClass(row.status)">{{ row.status_label }}</span>
            </template>

            <template #cell-progress="{ row }">
              <div class="progress-track">
                <div class="progress-fill" :style="{ width: `${row.progress || 0}%` }" />
              </div>
              <span class="progress-num">{{ row.done_files }}/{{ row.total_files }} 个文件</span>
            </template>

            <template #cell-target="{ row }">
              <div>{{ accountName(row.account_id) }}</div>
              <div class="mono muted">{{ row.target_path || '（115 根目录）' }}</div>
            </template>

            <template #cell-library="{ row }">{{ libraryName(row.library_id) }}</template>

            <template #cell-created_at="{ row }">{{ fmtDate(row.created_at) }}</template>

            <template #cell-actions="{ row }">
              <el-button
                v-if="row.status !== 'done'"
                size="small"
                type="primary"
                plain
                @click="retry(row)"
              >
                <RotateCw :size="13" style="margin-right: 3px" />重试
              </el-button>
              <el-button
                v-if="row.status === 'pending' || row.status === 'waiting_auth'"
                size="small"
                type="danger"
                plain
                @click="cancel(row)"
              >
                <XCircle :size="13" style="margin-right: 3px" />取消
              </el-button>
              <span v-if="row.status === 'done'" class="muted done-hint">已完成</span>
            </template>

            <template #card-extra="{ row }">
              <div v-if="row.error" class="detail-error">{{ row.error }}</div>
              <div v-if="row.items.length" class="detail-title">分享内容（{{ row.items.length }} 项）</div>
              <div v-for="it in row.items.slice(0, 6)" :key="it.fid" class="detail-line">
                <span class="mono">{{ it.is_dir ? '📁' : '🎬' }}</span>{{ it.name }}
              </div>
              <div v-if="row.items.length > 6" class="detail-line muted">
                还有 {{ row.items.length - 6 }} 项…
              </div>
              <template v-if="row.urls.length">
                <div class="detail-title">下载地址（{{ row.urls.length }}）</div>
                <a
                  v-for="(u, i) in row.urls.slice(0, 3)"
                  :key="i"
                  class="detail-line detail-link"
                  :href="u"
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink :size="12" />{{ u.slice(0, 46) }}…
                </a>
              </template>
            </template>
          </DataTable>
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
              <Plus :size="15" style="margin-right: 4px" />添加账号
            </el-button>
          </div>

          <DataTable
            :rows="accounts"
            :columns="accountColumns"
            :loading="loading"
            empty="还没有账号配置档"
            clickable
          >
            <template #cell-cookie_preview="{ row }">
              <span class="mono muted">{{ row.cookie_preview || '—' }}</span>
            </template>

            <template #cell-is_default="{ row }">
              <span v-if="row.is_default" class="mini-badge ok">默认</span>
              <span v-else class="muted">—</span>
            </template>

            <template #cell-is_enabled="{ row }">
              <span class="mini-badge" :class="row.is_enabled ? 'ok' : 'off'">
                {{ row.is_enabled ? '启用' : '停用' }}
              </span>
            </template>

            <template #cell-last_verified_at="{ row }">
              <template v-if="row.last_verified_at">
                {{ fmtDate(row.last_verified_at) }}
                <span :class="row.last_verify_ok ? 'ok-text' : 'bad-text'">
                  {{ row.last_verify_ok ? '有效' : '无效' }}
                </span>
                <span v-if="row.last_verify_message && !row.last_verify_ok" class="muted">
                  · {{ row.last_verify_message }}
                </span>
              </template>
              <span v-else class="muted">未校验</span>
            </template>

            <template #cell-remark="{ row }">
              <span v-if="!row.remark" class="muted">—</span>
              <span v-else>{{ row.remark }}</span>
            </template>

            <template #cell-actions="{ row }">
              <el-button size="small" type="primary" plain @click="openAccount(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="removeAccount(row)">
                <Trash2 :size="13" style="margin-right: 3px" />删除
              </el-button>
            </template>
          </DataTable>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建任务 -->
    <el-dialog v-model="createVisible" title="新建 115 转存任务" width="560px">
      <el-form label-position="top">
        <el-form-item label="分享链接">
          <el-input
            v-model="form.share_url"
            type="textarea"
            :rows="2"
            placeholder="粘贴 https://115.com/s/xxxx?password=abcd，或「链接 提取码：abcd」整段口令"
          />
          <div class="parse-row">
            <el-button size="small" :loading="parsing" @click="doParse">
              <Link2 :size="13" style="margin-right: 3px" />解析
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
          <el-select v-model="form.account_id" clearable placeholder="默认账号">
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
                <FolderOpen :size="13" style="margin-right: 3px" />浏览
              </el-button>
              <span class="browser-path">{{ targetLabel }}</span>
              <el-button size="small" type="primary" plain @click="pickCurrentDir">用当前目录</el-button>
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
              该目录下没有子目录（来源：{{ cookieSource }}）
            </div>
          </div>
        </el-form-item>
        <el-form-item label="完成后扫描">
          <el-select v-model="form.library_id" clearable placeholder="不触发扫描">
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
      <el-form label-position="top">
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
          <div class="form-hint">同一时间只有一个默认账号；媒体库未单独绑定时会用它</div>
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
.page-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }

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
  max-width: 160px;
}

.progress-fill {
  height: 100%;
  background: var(--gradient-brand);
  border-radius: 3px;
  transition: width 0.4s ease;
}

.progress-num { font-size: var(--font-size-xs); color: var(--text-muted); }

.ok-text { color: #6ee7b7; font-weight: 600; }
.bad-text { color: #fda4af; font-weight: 600; }
.done-hint { font-size: var(--font-size-xs); }

.detail-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  margin: 8px 0 4px;
  color: var(--text-tertiary);
}

.detail-line {
  font-size: var(--font-size-xs);
  padding: 2px 0;
  word-break: break-all;
  color: var(--text-secondary);
}

.detail-line .mono { margin-right: 4px; }
.detail-link { display: flex; align-items: center; gap: 5px; color: var(--primary); }
.detail-error { font-size: var(--font-size-xs); color: #fcd34d; margin-bottom: 6px; }

.acc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.acc-title { font-size: var(--font-size-lg); font-weight: var(--font-weight-bold); color: var(--text-primary); }
.acc-hint { font-size: var(--font-size-xs); color: var(--text-muted); margin-top: 5px; max-width: 640px; line-height: 1.6; }

.parse-row { display: flex; align-items: center; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
.parsed { font-size: var(--font-size-xs); color: #6ee7b7; }

.browser {
  width: 100%;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 10px;
  background: var(--bg-inset);
}

.browser-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.browser-path {
  flex: 1 1 140px;
  font-size: var(--font-size-xs);
  font-family: var(--font-mono);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.crumbs { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.crumb-item { font-size: var(--font-size-xs); cursor: pointer; color: var(--primary); }
.crumb-item::after { content: ' /'; color: var(--text-faint); }

.dir-list { margin-top: 8px; max-height: 180px; overflow-y: auto; }

.dir-item {
  font-size: var(--font-size-xs);
  padding: 7px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-secondary);
}

.dir-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.dir-empty { margin-top: 8px; font-size: var(--font-size-xs); }

@media (max-width: 640px) {
  .acc-head { flex-direction: column; align-items: stretch; }
  .progress-track { max-width: none; }
}
</style>
