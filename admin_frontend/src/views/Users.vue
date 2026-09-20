<script setup lang="ts">
/** 用户管理：搜索/筛选/禁用启用/重置密码/发消息/授权管理员 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { KeyRound, Megaphone, RefreshCw, Search, ShieldCheck, UserX } from 'lucide-vue-next'
import { broadcastMessage, fetchUsers, resetUserPassword, sendUserMessage, updateUser } from '@/api/admin'
import type { AdminUserRow } from '@/types'

const users = ref<AdminUserRow[]>([])
const total = ref(0)
const search = ref('')
const activeFilter = ref<string>('')
const loading = ref(false)
const page = ref(0)
const PAGE_SIZE = 20

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { limit: PAGE_SIZE, offset: page.value * PAGE_SIZE }
    if (search.value) params.search = search.value
    if (activeFilter.value !== '') params.active = activeFilter.value === 'true'
    const res = await fetchUsers(params)
    users.value = res.users
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

async function toggleActive(u: AdminUserRow) {
  const action = u.is_active ? '禁用' : '启用'
  await ElMessageBox.confirm(`确定要${action}用户「${u.username}」吗？`, '确认', { type: 'warning' })
  await updateUser(u.id, { is_active: !u.is_active })
  ElMessage.success(`已${action}`)
  load()
}

async function toggleStaff(u: AdminUserRow) {
  const action = u.is_staff ? '移除管理员' : '设为管理员'
  await ElMessageBox.confirm(`确定要${action}「${u.username}」吗？`, '确认', { type: 'warning' })
  await updateUser(u.id, { is_staff: !u.is_staff })
  ElMessage.success('已更新')
  load()
}

async function resetPwd(u: AdminUserRow) {
  const { value } = await ElMessageBox.prompt(`为「${u.username}」设置新密码（≥6 位，将同步为 Emby 播放密码）`, '重置密码', {
    inputPattern: /^.{6,64}$/,
    inputErrorMessage: '密码长度需为 6-64 位',
  })
  await resetUserPassword(u.id, value)
  ElMessage.success('密码已重置并同步 Emby')
}

async function dmUser(u: AdminUserRow) {
  const { value } = await ElMessageBox.prompt('消息内容', `发送消息给 ${u.username}`, {
    inputPlaceholder: '输入站内消息内容…',
  })
  if (!value?.trim()) return
  await sendUserMessage(u.id, { title: '管理员消息', content: value })
  ElMessage.success('消息已发送')
}

async function broadcast() {
  const { value } = await ElMessageBox.prompt('广播内容（将推送给全部用户）', '全站广播', {
    inputPlaceholder: '输入广播内容…',
  })
  if (!value?.trim()) return
  await broadcastMessage({ title: '系统广播', content: value })
  ElMessage.success('广播已发送')
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">用户管理</h1>
        <p class="admin-page-subtitle">共 {{ total }} 位用户</p>
      </div>
      <div class="toolbar">
        <el-input v-model="search" placeholder="搜索用户名 / 邮箱" clearable style="width: 220px" @keyup.enter="page = 0; load()" @clear="page = 0; load()">
          <template #prefix><Search :size="14" /></template>
        </el-input>
        <el-select v-model="activeFilter" placeholder="状态" clearable style="width: 110px" @change="page = 0; load()">
          <el-option label="正常" value="true" />
          <el-option label="已禁用" value="false" />
        </el-select>
        <el-button @click="broadcast"><Megaphone :size="14" style="margin-right: 4px" />广播</el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="admin-card">
      <el-table :data="users" v-loading="loading" style="width: 100%" :header-cell-style="{ background: 'transparent', color: '#a3a3a3' }">
        <el-table-column label="用户" min-width="180">
          <template #default="{ row }">
            <div class="user-cell">
              <span class="user-name">{{ row.username }}</span>
              <span v-if="row.is_staff" class="mini-badge staff">管理员</span>
              <span v-if="!row.is_active" class="mini-badge disabled">已禁用</span>
            </div>
            <div class="user-sub">{{ row.email || '未绑定邮箱' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Emby" min-width="130">
          <template #default="{ row }">{{ row.emby_username || '—' }}</template>
        </el-table-column>
        <el-table-column label="订阅" width="110">
          <template #default="{ row }">
            <span v-if="row.has_subscription" class="mini-badge vip">生效中</span>
            <span v-else class="user-sub">—</span>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="150">
          <template #default="{ row }">{{ fmtDate(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="注册时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="toggleActive(row)">
              <UserX :size="14" style="margin-right: 2px" />{{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button size="small" text @click="resetPwd(row)"><KeyRound :size="14" style="margin-right: 2px" />重置密码</el-button>
            <el-button size="small" text @click="dmUser(row)">消息</el-button>
            <el-button size="small" text :type="row.is_staff ? 'danger' : 'success'" @click="toggleStaff(row)">
              <ShieldCheck :size="14" style="margin-right: 2px" />{{ row.is_staff ? '降级' : '授权' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager" v-if="total > PAGE_SIZE">
        <el-pagination
          layout="prev, pager, next"
          :total="total"
          :page-size="PAGE_SIZE"
          :current-page="page + 1"
          @current-change="(p: number) => { page = p - 1; load() }"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.user-cell { display: flex; align-items: center; gap: 6px; }
.user-name { font-weight: 600; }
.user-sub { font-size: 12px; color: var(--color-text-muted, #737373); }
.mini-badge {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 600;
}
.mini-badge.staff { background: rgba(16, 185, 129, 0.15); color: #10b981; }
.mini-badge.disabled { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.mini-badge.vip { background: rgba(234, 179, 8, 0.15); color: #eab308; }
.pager { display: flex; justify-content: center; padding: 14px 0 4px; }
</style>
