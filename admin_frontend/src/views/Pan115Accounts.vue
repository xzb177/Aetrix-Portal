<script setup lang="ts">
/**
 * 115 账号
 *
 * 115 以「存储挂载」（类型选 115）的形式接入媒体库：面板 / EA 用 Cookie 型 Web API
 * 列目录、换直链，不需要转存。
 *
 * - 账号配置档：多账号 + 默认账号 + 启用开关；Cookie 不回传明文，可即时校验
 * - 目录浏览：用某个配置档实测一次列目录，既能确认 Cookie 可用，也能看清直挂的目录结构
 *
 * v2.18.0：分享链接转存 / 下载任务那一整套（标签页、任务表、新建任务弹窗）已下线，
 * 页面只保留账号配置。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpen, Plus, RefreshCw, ShieldCheck, Trash2 } from 'lucide-vue-next'
import {
  browsePan115,
  createPan115Account,
  deletePan115Account,
  fetchPan115Accounts,
  updatePan115Account,
  verifyPan115Account,
  verifyPan115Cookie,
} from '@/api/admin'
import type { Pan115Account, Pan115DirEntry } from '@/types'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const loading = ref(false)
const accounts = ref<Pan115Account[]>([])
const envCookieConfigured = ref(false)

const accountColumns: DataColumn[] = [
  { key: 'name', label: '名称', minWidth: 150, mobile: 'title' },
  { key: 'cookie_preview', label: 'Cookie', width: 130, mobile: 'hide' },
  { key: 'is_default', label: '默认', width: 80 },
  { key: 'is_enabled', label: '状态', width: 100 },
  { key: 'last_verified_at', label: '最近校验', minWidth: 190 },
  { key: 'remark', label: '备注', minWidth: 120, mobile: 'hide' },
  { key: 'actions', label: '操作', width: 230, fixed: 'right', align: 'right' },
]

async function load() {
  loading.value = true
  try {
    const res = await fetchPan115Accounts()
    accounts.value = res.accounts
    envCookieConfigured.value = res.env_cookie_configured
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
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

async function verify(row: Pan115Account) {
  const res = await verifyPan115Account(row.id)
  ElMessage[res.result.ok ? 'success' : 'error'](
    res.result.ok ? `「${row.name}」Cookie 有效` : res.result.message || 'Cookie 无效'
  )
  load()
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

// ==================== 目录浏览（实测一次列目录） ====================

const browseVisible = ref(false)
const browseAccount = ref<Pan115Account | null>(null)
const browseStack = ref<{ cid: string; name: string }[]>([])
const browseDirs = ref<Pan115DirEntry[]>([])
const browseSource = ref('')
const browsing = ref(false)

async function goto(cid: string) {
  browsing.value = true
  try {
    const res = await browsePan115({ cid, account_id: browseAccount.value?.id })
    browseDirs.value = res.entries
    browseSource.value = res.cookie_source
  } catch {
    browseDirs.value = []
  } finally {
    browsing.value = false
  }
}

async function openBrowser(row: Pan115Account) {
  browseAccount.value = row
  browseStack.value = [{ cid: '0', name: '根目录' }]
  browseDirs.value = []
  browseSource.value = ''
  browseVisible.value = true
  await goto('0')
}

function enterDir(entry: Pan115DirEntry) {
  browseStack.value = [...browseStack.value, { cid: entry.cid || entry.fid, name: entry.name }]
  goto(browseStack.value[browseStack.value.length - 1].cid)
}

function popTo(index: number) {
  browseStack.value = browseStack.value.slice(0, index + 1)
  goto(browseStack.value[index].cid)
}

function currentPath(): string {
  return '/' + browseStack.value.slice(1).map((p) => p.name).join('/')
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-head">
      <div>
        <h1 class="admin-page-title">115 账号</h1>
        <p class="admin-page-desc">
          配置 115 Cookie 以使用「存储来源 → 115」直挂：面板 / EA 直接列目录、换直链播放
        </p>
      </div>
      <div class="head-actions">
        <el-button :loading="loading" @click="load">
          <RefreshCw :size="15" style="margin-right: 4px" />刷新
        </el-button>
        <el-button type="primary" @click="openAccount(null)">
          <Plus :size="15" style="margin-right: 4px" />添加账号
        </el-button>
      </div>
    </div>

    <div class="admin-card">
      <div class="acc-head">
        <div>
          <div class="acc-title">115 Cookie 配置档</div>
          <div class="acc-hint">
            支持多账号与默认账号，媒体库可单独绑定；未绑定 / 未配置时回退到默认账号
            <template v-if="envCookieConfigured">，环境变量 PAN115_COOKIE 也会作为兜底</template>
          </div>
        </div>
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
          <el-button size="small" plain @click="verify(row)">
            <ShieldCheck :size="13" style="margin-right: 3px" />校验
          </el-button>
          <el-button size="small" plain @click="openBrowser(row)">
            <FolderOpen :size="13" style="margin-right: 3px" />浏览
          </el-button>
          <el-button size="small" type="danger" plain @click="removeAccount(row)">
            <Trash2 :size="13" style="margin-right: 3px" />删除
          </el-button>
        </template>
      </DataTable>
    </div>

    <!-- 账号编辑 -->
    <el-dialog v-model="accVisible" :title="accEditing ? '编辑 115 账号' : '添加 115 账号'" width="560px">
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

    <!-- 目录浏览：用该配置档实测列目录 -->
    <el-dialog v-model="browseVisible" title="115 目录浏览" width="560px">
      <div class="browser">
        <div class="browser-bar">
          <span class="browser-path">{{ currentPath() }}</span>
          <el-button size="small" :loading="browsing" @click="goto(browseStack[browseStack.length - 1].cid)">
            <RefreshCw :size="13" style="margin-right: 3px" />刷新
          </el-button>
        </div>
        <div class="crumbs">
          <span
            v-for="(p, i) in browseStack"
            :key="p.cid + i"
            class="crumb-item"
            @click="popTo(i)"
          >{{ p.name }}</span>
        </div>
        <div v-loading="browsing" class="dir-list">
          <div v-if="!browseDirs.length" class="dir-empty muted">该目录下没有子目录</div>
          <div
            v-for="e in browseDirs"
            :key="e.cid || e.fid"
            class="dir-item"
            @click="enterDir(e)"
          >📁 {{ e.name }}</div>
        </div>
      </div>
      <template #footer>
        <span class="form-hint" style="margin-right: auto">
          <template v-if="browseSource">Cookie 来源：{{ browseSource }}</template>
        </span>
        <el-button @click="browseVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions { display: flex; gap: 8px; }

.acc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.acc-title { font-size: var(--font-size-lg); font-weight: var(--font-weight-bold); color: var(--text-primary); }
.acc-hint { font-size: var(--font-size-xs); color: var(--text-muted); margin-top: 5px; max-width: 640px; line-height: 1.6; }

.ok-text { color: #6ee7b7; font-weight: 600; }
.bad-text { color: #fda4af; font-weight: 600; }

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

.dir-list { margin-top: 8px; max-height: 240px; overflow-y: auto; }

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
}
</style>
