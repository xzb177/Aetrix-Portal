<script setup lang="ts">
/**
 * 邀请与积分管理：邀请记录、积分流水、手动调整
 *
 * 参数配置（签到 / 支付 / 返利比例）已统一收归「系统设置」页，
 * 本页只负责台账与人工干预，避免两处入口改同一份配置。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Coins, Gift, RefreshCw, Settings, Plus } from 'lucide-vue-next'
import {
  fetchInvitations,
  fetchPointsLogs,
  fetchEconomyStats,
  adjustUserPoints,
  type InvitationRow,
  type PointsLogRow,
  type EconomyStats,
} from '@/api/economy'
import { fetchUsers } from '@/api/admin'

const loading = ref(false)
const stats = ref<EconomyStats | null>(null)

// ===== 邀请记录 =====
const invitations = ref<InvitationRow[]>([])

// ===== 积分流水 =====
const logs = ref<PointsLogRow[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logTypeFilter = ref('')

// ===== 手动调整 =====
const adjustVisible = ref(false)
const adjustForm = ref({ user_id: undefined as number | undefined, amount: 100, reason: '' })
const adjustLoading = ref(false)

/** 用户搜索（远程）：不再要求管理员手填数据库 ID */
const userOptions = ref<{ id: number; username: string }[]>([])
const userSearching = ref(false)

async function searchUsers(keyword: string) {
  userSearching.value = true
  try {
    const res = await fetchUsers({ search: keyword || undefined, limit: 20 })
    userOptions.value = res.users.map((u) => ({ id: u.id, username: u.username }))
  } catch {
    userOptions.value = []
  } finally {
    userSearching.value = false
  }
}

const selectedUser = computed(() =>
  userOptions.value.find((u) => u.id === adjustForm.value.user_id)?.username,
)

const inviteTotal = computed(() => invitations.value.length)
const rebateTotal = computed(() =>
  logs.value.filter((l) => l.type === 'rebate').reduce((s, l) => s + l.amount, 0),
)

async function load() {
  loading.value = true
  try {
    const [inv, log, econ] = await Promise.all([
      fetchInvitations({ limit: 100 }).catch(() => ({ records: [] })),
      fetchPointsLogs({ limit: 30, offset: (logPage.value - 1) * 30, type_filter: logTypeFilter.value || undefined }),
      fetchEconomyStats().catch(() => null),
    ])
    invitations.value = inv.records
    logs.value = log.logs
    logTotal.value = log.total
    stats.value = econ
  } finally {
    loading.value = false
  }
}

async function openAdjust() {
  adjustForm.value = { user_id: undefined, amount: 100, reason: '' }
  adjustVisible.value = true
  await searchUsers('')
}

async function handleAdjust() {
  if (!adjustForm.value.user_id) { ElMessage.warning('请输入用户 ID'); return }
  if (!adjustForm.value.amount) { ElMessage.warning('请输入调整数量'); return }
  adjustLoading.value = true
  try {
    const res = await adjustUserPoints(adjustForm.value.user_id, {
      amount: adjustForm.value.amount,
      reason: adjustForm.value.reason || undefined,
    })
    ElMessage.success(`调整成功，该用户当前余额 ${res.balance}`)
    adjustVisible.value = false
    load()
  } catch {
    // 错误提示由 HTTP 拦截器统一处理
  } finally {
    adjustLoading.value = false
  }
}

function fmtTime(iso?: string | null) {
  return iso ? iso.slice(0, 19).replace('T', ' ') : '—'
}

const TYPE_LABELS: Record<string, string> = {
  checkin: '签到', invite: '邀请奖励', invitee: '受邀奖励', rebate: '充值返利',
  exchange: '兑换码', recharge: '充值', admin_grant: '管理发放', admin_deduct: '管理扣除',
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">邀请与积分</h1>
        <p class="admin-page-subtitle">邀请台账与全站积分流水；规则参数已移至「系统设置」</p>
      </div>
      <div class="head-actions">
        <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
        <el-button :icon="Plus" @click="openAdjust">调整积分</el-button>
        <RouterLink to="/settings">
          <el-button :icon="Settings" type="primary">规则设置</el-button>
        </RouterLink>
      </div>
    </div>

    <section class="stat-row">
      <div class="stat-item">
        <span class="stat-label"><Gift :size="13" /> 本页邀请记录</span>
        <span class="stat-value">{{ inviteTotal }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label"><Coins :size="13" /> 全站积分存量</span>
        <span class="stat-value">{{ stats?.total_points ?? '—' }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">累计邀请关系</span>
        <span class="stat-value">{{ stats?.invitations ?? '—' }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">本页返利合计</span>
        <span class="stat-value">{{ rebateTotal }}</span>
      </div>
    </section>

    <div class="grid">
      <!-- 邀请记录 -->
      <section class="admin-card block">
        <div class="block-head">
          <h3>邀请记录（最新 {{ invitations.length }} 条）</h3>
        </div>
        <el-table :data="invitations" size="small" max-height="420">
          <el-table-column prop="inviter" label="邀请人" width="120" />
          <el-table-column prop="invitee" label="被邀请人" width="120" />
          <el-table-column label="奖励" width="90">
            <template #default="{ row }">+{{ row.reward_points }}</template>
          </el-table-column>
          <el-table-column label="时间">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <!-- 积分流水 -->
      <section class="admin-card block">
        <div class="block-head">
          <h3>积分流水（共 {{ logTotal }} 条）</h3>
          <el-select v-model="logTypeFilter" placeholder="全部类型" clearable size="small" style="width: 130px" @change="logPage = 1; load()">
            <el-option v-for="(label, key) in TYPE_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </div>
        <el-table :data="logs" size="small" max-height="420">
          <el-table-column prop="username" label="用户" width="110" />
          <el-table-column label="变动" width="80">
            <template #default="{ row }">
              <span :class="row.amount > 0 ? 'amt-in' : 'amt-out'">{{ row.amount > 0 ? '+' : '' }}{{ row.amount }}</span>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ TYPE_LABELS[row.type] || row.type }}</template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="150" show-overflow-tooltip />
          <el-table-column label="余额" width="80">
            <template #default="{ row }">{{ row.balance_after }}</template>
          </el-table-column>
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="logTotal > 30"
          v-model:current-page="logPage"
          :page-size="30"
          :total="logTotal"
          layout="prev, pager, next"
          size="small"
          class="pager"
          @current-change="load"
        />
      </section>
    </div>

    <!-- 调整积分对话框 -->
    <el-dialog v-model="adjustVisible" title="手动调整用户积分" width="440">
      <el-form label-width="90px">
        <el-form-item label="用户">
          <el-select
            v-model="adjustForm.user_id"
            filterable
            remote
            reserve-keyword
            :remote-method="searchUsers"
            :loading="userSearching"
            placeholder="搜索用户名"
            style="width: 100%"
          >
            <el-option
              v-for="u in userOptions"
              :key="u.id"
              :label="u.username"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="调整数量">
          <el-input-number v-model="adjustForm.amount" :step="10" style="width: 100%" />
          <div class="hint">正数发放 / 负数扣除（记账留审计）</div>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="adjustForm.reason" maxlength="100" placeholder="活动补偿等（选填）" />
        </el-form-item>
        <el-form-item v-if="selectedUser" label=" ">
          <span class="hint">将对「{{ selectedUser }}」发放/扣减 {{ adjustForm.amount }} 积分</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button type="primary" :loading="adjustLoading" @click="handleAdjust">确认调整</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<style scoped>
.head-actions { display: flex; gap: 8px; align-items: center; }

.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.stat-item {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 12px 14px;
}

.stat-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.stat-value {
  display: block;
  font-size: var(--font-size-3xl);
  font-weight: 700;
  margin-top: 2px;
  color: var(--primary);
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 14px;
  align-items: start;
}

.block { /* 沿用 .admin-card 视觉，仅补标题间距 */ }

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.block-head h3 { margin: 0; font-size: 14.5px; font-weight: 600; }

.amt-in { color: var(--success); font-weight: 600; }
.amt-out { color: var(--danger); font-weight: 600; }

.pager { margin-top: 10px; justify-content: flex-end; }

.hint { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

@media (max-width: 1000px) {
  .grid { grid-template-columns: 1fr; }
}
</style>
