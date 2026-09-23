<script setup lang="ts">
/**
 * 管理员与权限（v2.26.0）
 *
 * 后台账号就是前台账号（同一套 token 与密码），所以这一页**不新建账号**：
 * 只是把已注册的人标记成管理员，并给他一个角色。
 *
 * - 超级管理员：全部（含系统设置、上游 Key、播放与客户端策略、本页）
 * - 运营：日常运营全都能做，改不了上面那几项
 * - 只读审计：能看所有页面，任何修改都会被服务端拒绝
 *
 * 服务端才是判定的地方（backend/admin_roles.py），这一页只负责「看得懂 + 改得动」：
 * 角色说明直接来自后端下发的元数据，不在前端再维护一份。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  AlertTriangle, CheckCircle2, Mail, RefreshCw, ShieldCheck, ShieldHalf, UserPlus, Eye,
} from 'lucide-vue-next'
import { fetchAdmins, grantAdmin, revokeAdmin, updateAdmin } from '@/api/admin'
import type { AdminListResponse, AdminRole, AdminRoleMeta, AdminRow } from '@/types'
import { useAuthStore } from '@/stores/auth'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const auth = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const data = ref<AdminListResponse | null>(null)

const admins = computed(() => data.value?.admins || [])
const roles = computed<AdminRoleMeta[]>(() => data.value?.roles || [])
const superCount = computed(() => data.value?.super_count || 0)
const myId = computed(() => data.value?.me.id ?? auth.admin?.id ?? 0)
const isSuper = computed(() => auth.admin?.is_super !== false)

const ROLE_ICONS: Record<AdminRole, unknown> = {
  super: ShieldCheck,
  operator: ShieldHalf,
  viewer: Eye,
}

const columns = computed<DataColumn[]>(() => [
  { key: 'username', label: '管理员', minWidth: 180, mobile: 'title' },
  { key: 'role', label: '角色', width: 170 },
  { key: 'last_login_at', label: '最近登录', width: 150 },
  { key: 'is_active', label: '状态', width: 110 },
  { key: 'actions', label: '操作', width: 150 },
])

const form = ref<{ account: string; role: AdminRole }>({ account: '', role: 'operator' })

async function load() {
  loading.value = true
  try {
    data.value = await fetchAdmins()
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 授权：用户名或邮箱都能填（管理员不新建账号，只标记已注册的用户） */
async function submitGrant() {
  const account = form.value.account.trim()
  if (!account) {
    ElMessage.warning('请填写要授权的用户名或邮箱')
    return
  }
  saving.value = true
  try {
    const payload = account.includes('@') ? { email: account } : { username: account }
    const res = await grantAdmin({ ...payload, role: form.value.role })
    ElMessage.success(`已把「${res.admin.username}」设为${res.admin.role_label}`)
    form.value.account = ''
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '授权失败')
  } finally {
    saving.value = false
  }
}

async function changeRole(row: AdminRow, role: AdminRole) {
  if (role === row.admin_role) return
  saving.value = true
  try {
    await updateAdmin(row.id, { role })
    ElMessage.success(`「${row.username}」已改为${roles.value.find((r) => r.value === role)?.label || role}`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '修改失败')
    await load()
  } finally {
    saving.value = false
  }
}

async function toggleActive(row: AdminRow) {
  saving.value = true
  try {
    await updateAdmin(row.id, { is_active: !row.is_active })
    ElMessage.success(row.is_active ? `已停用「${row.username}」` : `已启用「${row.username}」`)
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    saving.value = false
  }
}

async function revoke(row: AdminRow) {
  try {
    await ElMessageBox.confirm(
      `撤销「${row.username}」的管理员身份？账号本身、会员与订阅都不受影响。`,
      '撤销管理员', { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    await revokeAdmin(row.id)
    ElMessage.success('已撤销')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '撤销失败')
  } finally {
    saving.value = false
  }
}

function fmtDate(value: string | null): string {
  if (!value) return '—'
  return value.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">管理员与权限</h1>
        <p class="admin-page-subtitle">
          后台账号就是前台账号：这里只把已注册的人标记为管理员并给他一个角色，不新建账号
        </p>
      </div>
      <div class="admin-page-actions">
        <el-button :loading="loading" @click="load"><RefreshCw :size="15" /></el-button>
      </div>
    </div>

    <el-alert v-if="!isSuper" type="warning" :closable="false" show-icon class="role-warn">
      <template #title>当前账号不是超级管理员</template>
      <template #default>
        你可以查看这一页，但授权 / 改角色 / 撤销会被服务端拒绝（需要超级管理员角色）。
      </template>
    </el-alert>

    <!-- 角色说明：来自后端元数据，前端不维护第二份 -->
    <section class="role-grid">
      <div v-for="role in roles" :key="role.value" class="role-card admin-card">
        <div class="role-head">
          <span class="role-icon"><component :is="ROLE_ICONS[role.value]" :size="16" /></span>
          <strong>{{ role.label }}</strong>
          <span class="role-key">{{ role.value }}</span>
        </div>
        <p class="role-hint">{{ role.hint }}</p>
      </div>
    </section>

    <!-- 授权 -->
    <section class="admin-card">
      <div class="card-header">
        <h2><UserPlus :size="15" /> 授予管理员</h2>
        <span class="hint">账号需要先在站点注册过；被停用的账号要先启用</span>
      </div>
      <div class="grant-row">
        <el-input
          v-model="form.account"
          placeholder="用户名或邮箱"
          clearable
          :disabled="!isSuper"
          @keyup.enter="submitGrant"
        >
          <template #prefix><Mail :size="14" /></template>
        </el-input>
        <el-select v-model="form.role" :disabled="!isSuper" class="role-select">
          <el-option v-for="role in roles" :key="role.value" :label="role.label" :value="role.value" />
        </el-select>
        <el-button type="primary" :loading="saving" :disabled="!isSuper" @click="submitGrant">
          授权
        </el-button>
      </div>
      <p class="grant-foot">
        当前 {{ admins.length }} 名管理员（其中超级管理员 {{ superCount }} 名）
      </p>
    </section>

    <!-- 清单 -->
    <section class="admin-card">
      <div class="card-header">
        <h2><ShieldCheck :size="15" /> 管理员清单</h2>
        <span class="hint">不能改自己、不能没有超级管理员（服务端护栏）</span>
      </div>
      <DataTable :rows="admins" :columns="columns" :loading="loading" empty="还没有管理员" row-key="id">
        <template #cell-username="{ row }">
          <div class="who-cell">
            <span class="who-name">{{ row.username }}</span>
            <span v-if="row.id === myId" class="mini-badge info">我</span>
            <span v-if="!row.is_active" class="mini-badge warn">已停用</span>
            <span v-if="row.email" class="who-mail">{{ row.email }}</span>
          </div>
        </template>

        <template #cell-role="{ row }">
          <el-select
            :model-value="row.admin_role"
            size="small"
            :disabled="!isSuper || row.id === myId"
            class="role-inline"
            @change="(value: AdminRole) => changeRole(row, value)"
          >
            <el-option v-for="role in roles" :key="role.value" :label="role.label" :value="role.value" />
          </el-select>
        </template>

        <template #cell-last_login_at="{ row }">{{ fmtDate(row.last_login_at) }}</template>

        <template #cell-is_active="{ row }">
          <span class="mini-badge" :class="row.is_active ? 'ok' : 'off'">
            {{ row.is_active ? '启用' : '停用' }}
          </span>
        </template>

        <template #cell-actions="{ row }">
          <div class="row-actions">
            <el-button
              size="small"
              :disabled="!isSuper || row.id === myId"
              @click="toggleActive(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!isSuper || row.id === myId"
              @click="revoke(row)"
            >
              撤销
            </el-button>
          </div>
        </template>
      </DataTable>
    </section>

    <section class="admin-card tips">
      <div class="card-header"><h2><AlertTriangle :size="15" /> 三条护栏（服务端强制执行）</h2></div>
      <ul>
        <li><CheckCircle2 :size="13" /> <b>不能改自己</b>：把自己的角色降下去或撤销自己，等于把自己关在门外。</li>
        <li><CheckCircle2 :size="13" /> <b>不能没有超级管理员</b>：最后一名 super 既不能降级也不能撤销。</li>
        <li><CheckCircle2 :size="13" /> <b>停用账号不能当管理员</b>：那种号永远登不进来，先启用再说。</li>
      </ul>
      <p class="tips-foot">
        只读角色在服务端拦截一切写操作（包括扫描、扫描与挂载体检），不是「界面置灰」而已。
      </p>
    </section>
  </div>
</template>

<style scoped>
.role-warn { margin-bottom: 14px; }

.role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.role-card { display: flex; flex-direction: column; gap: 8px; }
.role-head { display: flex; align-items: center; gap: 8px; }

.role-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary);
}

.role-key { margin-left: auto; font-size: var(--font-size-xs); color: var(--text-faint); }
.role-hint { margin: 0; font-size: var(--font-size-xs); color: var(--text-tertiary); line-height: 1.6; }

.grant-row { display: flex; gap: 10px; flex-wrap: wrap; }
.grant-row .el-input { flex: 1; min-width: 200px; }
.role-select { width: 160px; }
.grant-foot { margin: 10px 0 0; font-size: var(--font-size-xs); color: var(--text-muted); }

.who-cell { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.who-name { font-weight: var(--font-weight-semibold); }
.who-mail { font-size: var(--font-size-xs); color: var(--text-muted); }

.role-inline { width: 140px; }
.row-actions { display: flex; gap: 6px; }

.tips ul { margin: 0; padding-left: 4px; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.tips li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}
.tips li :deep(svg) { color: var(--success); flex-shrink: 0; }
.tips-foot { margin: 12px 0 0; font-size: var(--font-size-xs); color: var(--text-muted); }
</style>
