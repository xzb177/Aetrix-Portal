<script setup lang="ts">
/**
 * 媒体库可见范围（v2.43.0）：服务器默认范围 + 指定用户单独覆盖
 *
 * 这一页回答三个问题，顺序就是管理员用它的顺序：
 *
 * 1. **全站默认让谁看到哪些库**（默认范围卡）。**默认关闭** = 所有启用的库照旧
 *    全部可见，升级上来的部署行为与升级前逐字一致。
 * 2. **谁被单独开了一张单子**（覆盖表）。覆盖开着 = 看自己那份；关掉 = 恢复
 *    跟随服务器默认（列表留着，方便再打开）。
 * 3. **现在真的生效了吗**（统计与警示）。开启却一个库都没选 / 选的库被删光，
 *    后端会退回「不过滤」而不是把媒体库清空——这里如实显示成「未生效」。
 *
 * 一条必须说清的口径：**工作人员账号不受可见范围限制**（排障要看到全部库），
 * 与「防共享」对管理员豁免是同一个理由。所以勾选范围时不提示「这会挡住管理员」，
 * 反而要在说明里点明。
 *
 * 判定与生效在后端 `backend/library_scope.py`（客户端列表 / 搜索 / 继续观看 /
 * 最近上新 / 接下来看都按它过滤），本页只做配置与展示。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Eye, RefreshCw, Save, Plus, ShieldCheck, TriangleAlert, Trash2, UserCog } from 'lucide-vue-next'
import {
  fetchLibraryScope,
  removeLibraryScopeUser,
  saveLibraryScopeDefault,
  saveLibraryScopeUser,
  type LibraryScopeOverride,
  type LibraryScopeResponse,
} from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
import { confirmIrreversible } from '@/composables/useDangerOps'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

/** 覆盖表：用户（标题）/ 状态 / 名单 / 操作 */
const columns: DataColumn[] = [
  { key: 'username', label: '用户', width: 160, mobile: 'title' },
  { key: 'state', label: '状态', width: 130 },
  { key: 'libraries', label: '可见媒体库', minWidth: 260 },
  { key: 'action', label: '操作', width: 200 },
]

const data = ref<LibraryScopeResponse | null>(null)
const loading = ref(false)
const saving = ref(false)

/** 本地草稿：改完点「保存」才写后端，不动后端就不算改 */
const draftEnabled = ref(false)
const draftIds = ref<number[]>([])
const filter = ref('')

const auth = useAuthStore()
/** 与「系统设置」同一口径：有写权限才能改（普通只读账号可读） */
const canWrite = computed(() => auth.admin?.can_write !== false)
const WRITE_HINT = '当前账号是只读角色，下面的按钮已置灰，但配置仍然可读'

const sameIds = (a: number[], b: number[]) => {
  const x = [...a].sort((m, n) => m - n)
  const y = [...b].sort((m, n) => m - n)
  return x.length === y.length && x.every((v, i) => v === y[i])
}

const dirty = computed(() => {
  const cur = data.value?.default
  if (!cur) return false
  return cur.enabled !== draftEnabled.value || !sameIds(cur.library_ids, draftIds.value)
})

/** 当前草稿勾选的库（用来在列表里画出「已选」以及算条数） */
const libraryOptions = computed(() => data.value?.libraries ?? [])
const visibleOptions = computed(() => {
  const kw = filter.value.trim().toLowerCase()
  if (!kw) return libraryOptions.value
  return libraryOptions.value.filter((lib) => lib.name.toLowerCase().includes(kw))
})
const users = computed(() => data.value?.users ?? [])

const overrideRows = computed(() => {
  const overrides = data.value?.overrides ?? {}
  const byId = new Map(users.value.map((u) => [u.id, u]))
  return Object.entries(overrides).map(([uid, value]) => {
    const id = Number(uid)
    const user = byId.get(id)
    return {
      user_id: id,
      username: user?.username ?? `用户 #${uid}`,
      is_staff: !!user?.is_staff,
      state: value.enabled ? 'enabled' : 'disabled',
      state_label: value.enabled ? '单独覆盖' : '跟随默认',
      libraries: namesOf(value.library_ids),
      _override: value,
    }
  })
})

function namesOf(ids: number[]): string[] {
  const map = new Map(libraryOptions.value.map((lib) => [lib.id, lib.name]))
  return ids.map((id) => map.get(id) ?? `已删除的库 #${id}`)
}

const statDefault = computed(() => {
  const d = data.value?.default
  if (!d) return '—'
  if (!d.enabled) return '未限制'
  return d.active ? `限定 ${d.library_ids.length} 个` : '未生效'
})

async function load() {
  loading.value = true
  try {
    data.value = await fetchLibraryScope()
    draftEnabled.value = data.value.default.enabled
    draftIds.value = [...data.value.default.library_ids]
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function saveDefault() {
  saving.value = true
  try {
    const res = await saveLibraryScopeDefault({
      enabled: draftEnabled.value,
      library_ids: draftIds.value,
    })
    data.value = { ...(data.value as LibraryScopeResponse), ...res.policy }
    // 以后端返回的**真实生效值**回填（非法输入后端会 400，不会存半个坏配置）
    draftEnabled.value = res.policy.default.enabled
    draftIds.value = [...res.policy.default.library_ids]
    ElMessage.success('默认可见范围已保存并立即生效')
  } catch {
    /* 拦截器已提示（启用却一个都没勾会走 400） */
  } finally {
    saving.value = false
  }
}

function revert() {
  if (!data.value) return
  draftEnabled.value = data.value.default.enabled
  draftIds.value = [...data.value.default.library_ids]
}

function toggleAll() {
  const all = visibleOptions.value.map((lib) => lib.id)
  if (!all.length) return
  const everything = sameIds(draftIds.value, all)
  draftIds.value = everything
    ? draftIds.value.filter((id) => !all.includes(id))
    : [...new Set([...draftIds.value, ...all])]
}

/** 勾选框改一个 id：写进默认范围那份草稿（点「保存」才落库） */
function setDraft(id: number, on: boolean) {
  draftIds.value = on
    ? [...new Set([...draftIds.value, id])]
    : draftIds.value.filter((i) => i !== id)
}


// ==================== 逐用户覆盖 ====================

const dialogVisible = ref(false)
const savingUser = ref(false)
/** 正在编辑的用户 id（0 = 新增）。新增时可以换人，编辑时锁死 */
const editingUserId = ref(0)
const formUserId = ref<number | null>(null)
const formEnabled = ref(true)
const formIds = ref<number[]>([])

const isStaffUser = computed(
  () => users.value.find((u) => u.id === formUserId.value)?.is_staff ?? false,
)

/** 同上，覆盖对话框里那一份（勾选可见媒体库） */
function setForm(id: number, on: boolean) {
  formIds.value = on
    ? [...new Set([...formIds.value, id])]
    : formIds.value.filter((i) => i !== id)
}

/** 已经有覆盖的人不进「新增」下拉：重复添加只会静默覆盖旧名单 */
const candidateUsers = computed(() => {
  if (editingUserId.value) return users.value
  const overridden = new Set(Object.keys(data.value?.overrides ?? {}).map(Number))
  return users.value.filter((u) => !overridden.has(u.id))
})

const formValid = computed(
  () => !!formUserId.value && (!formEnabled.value || formIds.value.length > 0),
)

function openCreate() {
  editingUserId.value = 0
  formUserId.value = null
  formEnabled.value = true
  formIds.value = []
  dialogVisible.value = true
}

function openEdit(row: { user_id: number; _override: LibraryScopeOverride }) {
  editingUserId.value = row.user_id
  formUserId.value = row.user_id
  formEnabled.value = row._override.enabled
  formIds.value = [...row._override.library_ids]
  dialogVisible.value = true
}

async function saveUserScope() {
  const userId = formUserId.value
  if (!userId || !formValid.value) return
  savingUser.value = true
  try {
    const res = await saveLibraryScopeUser(userId, {
      enabled: formEnabled.value,
      library_ids: formIds.value,
    })
    data.value = { ...(data.value as LibraryScopeResponse), ...res.policy }
    dialogVisible.value = false
    ElMessage.success(
      res.policy.overrides[String(userId)]?.enabled
        ? '该用户的单独覆盖已生效'
        : '已恢复跟随服务器默认',
    )
  } catch {
    /* 拦截器已提示 */
  } finally {
    savingUser.value = false
  }
}

async function toggleOverride(row: { user_id: number; _override: LibraryScopeOverride }) {
  if (!canWrite.value) return
  try {
    const res = await saveLibraryScopeUser(row.user_id, {
      enabled: !row._override.enabled,
      library_ids: row._override.library_ids,
    })
    data.value = { ...(data.value as LibraryScopeResponse), ...res.policy }
    ElMessage.success(res.policy.overrides[String(row.user_id)]?.enabled ? '已开启单独覆盖' : '已恢复跟随默认')
  } catch {
    /* 拦截器已提示 */
  }
}

async function removeOverride(row: { username: string; user_id: number }) {
  const ok = await confirmIrreversible(
    `删除后「${row.username}」完全恢复跟随服务器默认，且这份名单不再保留。`,
    '删除覆盖',
    `删除 ${row.username} 的可见范围覆盖`,
  )
  if (!ok) return
  try {
    const res = await removeLibraryScopeUser(row.user_id)
    data.value = { ...(data.value as LibraryScopeResponse), ...res.policy }
    ElMessage.success('已删除该用户的单独覆盖')
  } catch {
    /* 拦截器已提示 */
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">媒体库可见范围</h1>
        <p class="admin-page-desc">
          服务器默认范围 + 指定用户单独覆盖。默认关闭——所有启用的媒体库照旧全部可见。
        </p>
      </div>
      <div class="toolbar">
        <el-button :loading="loading" @click="load">
          <RefreshCw :size="14" style="margin-right: 4px" />刷新
        </el-button>
      </div>
    </div>

    <div v-if="data" class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label"><Eye :size="13" /> 媒体库</div>
        <div class="stat-value">{{ data.counts.libraries }}</div>
        <div class="stat-hint">其中 {{ libraryOptions.filter((l) => l.is_enabled).length }} 个启用中</div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': data.default.enabled }">
        <div class="stat-label"><ShieldCheck :size="13" /> 默认范围</div>
        <div class="stat-value">{{ statDefault }}</div>
        <div class="stat-hint">「未限制」= 所有启用的库都可见</div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': data.counts.overrides > 0 }">
        <div class="stat-label"><UserCog :size="13" /> 单独覆盖</div>
        <div class="stat-value">{{ data.counts.overrides }}</div>
        <div class="stat-hint">关掉覆盖就回到默认范围</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label"><TriangleAlert :size="13" /> 工作人员</div>
        <div class="stat-value">豁免</div>
        <div class="stat-hint">排障需要看全部库，不受本设置限制</div>
      </div>
    </div>

    <!-- 默认范围 -->
    <section class="admin-card">
      <header class="card-header">
        <h2>服务器默认范围</h2>
        <span v-if="dirty" class="fact warn">有未保存的改动</span>
      </header>

      <el-alert
        v-if="data && data.default.enabled && !data.default.active"
        type="warning"
        :closable="false"
        show-icon
        class="ls-alert"
      >
        这份范围<strong>当前没有生效</strong>：勾选的媒体库已经不存在了（可能被删掉）。
        此时按「不处理」退回全部可见，而不是把所有人的媒体库清空。请重新勾选后再保存。
      </el-alert>

      <el-alert
        v-if="!canWrite"
        type="info"
        :closable="false"
        show-icon
        class="ls-alert"
      >
        {{ WRITE_HINT }}。下面的说明仍然可读。
      </el-alert>

      <p class="ls-hint">
        打开后，<strong>没有单独覆盖</strong>的用户只看到勾选的媒体库；关闭则所有人
        （除工作人员外）照旧看到全部启用的库。勾选只决定「列表里显不显示」，
        判定发生在后端：客户端列表、搜索、继续观看、最近上新、接下来看都按它过滤。
      </p>

      <div class="ls-switch-row">
        <el-switch
          v-model="draftEnabled"
          :disabled="!canWrite"
          active-text="限定可见范围"
          inactive-text="不限制（全部可见）"
        />
        <span v-if="draftEnabled" class="ls-hint ls-inline">
          已勾选 {{ draftIds.length }} 个媒体库
        </span>
      </div>

      <div v-show="draftEnabled" class="ls-pick">
        <div class="ls-pick-head">
          <el-input v-model="filter" placeholder="筛选媒体库名称" clearable size="small" style="width: 220px" />
          <el-button size="small" :disabled="!canWrite" @click="toggleAll">
            {{ visibleOptions.length ? '全选当前筛选结果' : '无可选项' }}
          </el-button>
        </div>
        <div v-if="!libraryOptions.length" class="ls-empty">
          站点还没有任何媒体库，先到「媒体与交付 → 媒体库」建库再回来配置。
        </div>
        <div v-else class="ls-pick-list">
          <div v-for="lib in visibleOptions" :key="lib.id" class="ls-pick-item">
            <el-checkbox
              :model-value="draftIds.includes(lib.id)"
              :disabled="!canWrite"
              @change="(v: boolean | string | number) => setDraft(lib.id, v === true)"
            >
              <span class="ls-lib-name">{{ lib.name }}</span>
            </el-checkbox>
            <span class="ls-lib-meta">
              <span v-if="!lib.is_enabled" class="mini-badge muted">已停用</span>
              <span v-else-if="lib.is_virtual" class="mini-badge info">虚拟库</span>
              <span class="muted">{{ lib.item_count }} 条</span>
            </span>
          </div>
          <div v-if="!visibleOptions.length" class="ls-empty">没有名称匹配「{{ filter }}」的媒体库</div>
        </div>
      </div>

      <div class="ls-actions">
        <el-button
          type="primary"
          :disabled="!canWrite || !dirty"
          :loading="saving"
          @click="saveDefault"
        >
          <Save :size="14" style="margin-right: 4px" />保存默认范围
        </el-button>
        <el-button :disabled="!canWrite || !dirty" @click="revert">还原</el-button>
        <span v-if="data" class="ls-hint ls-inline">
          保存后对<strong>未单独覆盖</strong>的用户生效（工作人员不受本设置限制）。
          已有 {{ data.counts.overrides }} 个用户挂了自己的名单。
        </span>
      </div>
    </section>

    <!-- 单独覆盖 -->
    <section class="admin-card">
      <header class="card-header">
        <h2>指定用户单独覆盖</h2>
        <div class="ls-facts">
          <el-button size="small" :disabled="!canWrite" @click="openCreate">
            <Plus :size="14" style="margin-right: 4px" />新增覆盖
          </el-button>
        </div>
      </header>

      <p class="ls-hint">
        这里列出的用户看<strong>自己那份</strong>名单，优先于服务器默认范围。
        把开关拨到「跟随默认」= 关掉覆盖、恢复按默认范围走；名单会留着，方便再打开。
      </p>

      <DataTable
        :rows="overrideRows"
        :columns="columns"
        :loading="loading"
        empty="还没有给任何用户单独设置：所有人都按服务器默认范围看媒体库"
      >
        <template #cell-username="{ row }">
          <span class="ls-user">{{ row.username }}</span>
          <span v-if="row.is_staff" class="mini-badge info">工作人员</span>
        </template>

        <template #cell-state="{ row }">
          <span class="mini-badge" :class="row.state === 'enabled' ? 'warn' : 'muted'">
            {{ row.state_label }}
          </span>
        </template>

        <template #cell-libraries="{ row }">
          <span v-if="!row.libraries.length" class="muted">—</span>
          <template v-else>{{ row.libraries.join('、') }}</template>
        </template>

        <template #cell-action="{ row }">
          <div class="ls-row-actions">
            <el-button size="small" :disabled="!canWrite" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" :disabled="!canWrite" @click="toggleOverride(row)">
              {{ row.state === 'enabled' ? '恢复跟随默认' : '开启覆盖' }}
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!canWrite"
              @click="removeOverride(row)"
            >
              <Trash2 :size="13" />
            </el-button>
          </div>
        </template>
      </DataTable>
    </section>

    <!-- 新增 / 编辑覆盖 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingUserId ? '编辑可见范围覆盖' : '新增可见范围覆盖'"
      width="520px"
      class="ls-dialog"
    >
      <el-form label-position="top">
        <el-form-item label="用户">            <el-select
              v-model="formUserId"
              :placeholder="candidateUsers.length ? '搜索并选择用户' : '所有用户都已有覆盖：先删掉一条再新增'"
              filterable
            :disabled="!!editingUserId || !canWrite"
            style="width: 100%"
          >
            <el-option
              v-for="u in candidateUsers"
              :key="u.id"
              :value="u.id"
              :label="`${u.username}（#${u.id}）`"
            />
          </el-select>
          <span v-if="isStaffUser" class="ls-hint">
            这是工作人员账号：<strong>它不受可见范围限制</strong>，这条覆盖不会改变他实际看到的库。
          </span>
        </el-form-item>

        <el-form-item label="覆盖开关">
          <el-switch
            v-model="formEnabled"
            :disabled="!canWrite"
            active-text="单独覆盖"
            inactive-text="跟随默认"
          />
        </el-form-item>

        <el-form-item v-if="formEnabled" label="可见媒体库">
          <div class="ls-pick-list ls-dialog-list">
            <div v-for="lib in libraryOptions" :key="lib.id" class="ls-pick-item">
              <el-checkbox
                :model-value="formIds.includes(lib.id)"
                :disabled="!canWrite"
                @change="(v: boolean | string | number) => setForm(lib.id, v === true)"
              >
                <span class="ls-lib-name">{{ lib.name }}</span>
              </el-checkbox>
              <span class="ls-lib-meta">
                <span v-if="!lib.is_enabled" class="mini-badge muted">已停用</span>
              </span>
            </div>
            <div v-if="!libraryOptions.length" class="ls-empty">站点还没有任何媒体库</div>
          </div>
          <span v-if="formEnabled" class="ls-hint">已勾选 {{ formIds.length }} 个</span>
        </el-form-item>

        <p v-else class="ls-hint">
          关闭覆盖后该用户按服务器默认范围看媒体库，这里的选择会被保留。
        </p>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!canWrite || !formValid"
          :loading="savingUser"
          @click="saveUserScope"
        >
          <Save :size="14" style="margin-right: 4px" />保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ls-hint {
  display: block;
  margin: 0 0 10px;
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  line-height: 1.8;
}
.ls-inline { margin: 0; }
.ls-alert { margin: 0 0 12px; }
.ls-switch-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.ls-pick { margin-bottom: 4px; }
.ls-pick-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.ls-pick-list {
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md, 8px);
  padding: 8px 10px;
}
.ls-dialog-list { max-height: 300px; width: 100%; }
.ls-pick-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  padding: 4px 2px;
}
.ls-lib-name {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  word-break: break-all;
}
.ls-lib-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  font-size: 11.5px;
}
.ls-empty {
  padding: 10px 4px;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  line-height: 1.7;
}
.ls-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}
.ls-facts { display: flex; align-items: center; gap: 8px; }
.ls-row-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ls-user { font-weight: var(--font-weight-semibold); color: var(--text-primary); margin-right: 6px; }
.fact.warn { color: var(--warning); font-size: var(--font-size-xs); }
.stat-tile.is-warn { border-color: var(--warning-border); }

/* 手机：筛选条与按钮竖排，勾选列表占满整行 */
@media (max-width: 767px) {
  .ls-pick-head { width: 100%; }
  .ls-pick-head .el-input { flex: 1 1 auto; width: auto; }
  .ls-actions .el-button { flex: 1 1 auto; }
  .ls-actions .ls-hint { flex: 1 1 100%; }
  .ls-pick-list { max-height: 320px; }
}
</style>
