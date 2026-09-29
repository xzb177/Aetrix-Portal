<script setup lang="ts">
/**
 * 邀请与积分管理：邀请记录、积分流水、手动调整
 *
 * 参数配置（签到 / 支付 / 返利比例）已统一收归「系统设置」页，
 * 本页只负责台账与人工干预，避免两处入口改同一份配置。
 *
 * v2.6.11：两张台账改用 DataTable（手机上变成卡片列表，不再需要横向拖），
 * 统计瓦片统一为全局 .stat-tile。
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
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const loading = ref(false)
const stats = ref<EconomyStats | null>(null)

// ===== 邀请记录 =====
const invitations = ref<InvitationRow[]>([])

const inviteColumns: DataColumn[] = [
  { key: 'inviter', label: '邀请人', width: 140, mobile: 'title' },
  { key: 'invitee', label: '被邀请人', width: 140 },
  { key: 'reward_points', label: '奖励', width: 100 },
  { key: 'created_at', label: '时间' },
]

// ===== 积分流水 =====
const logs = ref<PointsLogRow[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logTypeFilter = ref('')

const logColumns: DataColumn[] = [
  { key: 'username', label: '用户', width: 130, mobile: 'title' },
  { key: 'amount', label: '变动', width: 90 },
  { key: 'type', label: '类型', width: 100 },
  { key: 'description', label: '说明', minWidth: 170 },
  { key: 'balance_after', label: '余额', width: 90 },
  { key: 'created_at', label: '时间', width: 160 },
]

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
      <div class="admin-page-actions">
        <el-button :loading="loading" @click="load">
          <RefreshCw :size="15" style="margin-right: 4px" />刷新
        </el-button>
        <el-button @click="openAdjust">
          <Plus :size="15" style="margin-right: 4px" />调整积分
        </el-button>
        <RouterLink to="/settings" class="link-button">
          <el-button type="primary">
            <Settings :size="15" style="margin-right: 4px" />规则设置
          </el-button>
        </RouterLink>
      </div>
    </div>

    <section class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label"><Gift :size="13" /> 本页邀请记录</div>
        <div class="stat-value stat-accent">{{ inviteTotal }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label"><Coins :size="13" /> 全站积分存量</div>
        <div class="stat-value">{{ stats?.total_points ?? '—' }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">累计邀请关系</div>
        <div class="stat-value">{{ stats?.invitations ?? '—' }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">本页返利合计</div>
        <div class="stat-value stat-accent">{{ rebateTotal }}</div>
      </div>
    </section>

    <div class="grid">
      <!-- 邀请记录 -->
      <section class="admin-card block">
        <div class="block-head">
          <h3>邀请记录（最新 {{ invitations.length }} 条）</h3>
        </div>
        <DataTable :rows="invitations" :columns="inviteColumns" :loading="loading" empty="暂无邀请记录">
          <template #cell-inviter="{ row }">
            <span class="user-name">{{ row.inviter }}</span>
          </template>
          <template #cell-invitee="{ row }">{{ row.invitee }}</template>
          <template #cell-reward_points="{ row }">
            <span class="amt-in">+{{ row.reward_points }}</span>
          </template>
          <template #cell-created_at="{ row }">{{ fmtTime(row.created_at) }}</template>
        </DataTable>
      </section>

      <!-- 积分流水 -->
      <section class="admin-card block">
        <div class="block-head">
          <h3>积分流水（共 {{ logTotal }} 条）</h3>
          <el-select
            v-model="logTypeFilter"
            placeholder="全部类型"
            clearable
            size="small"
            style="width: 140px"
            @change="logPage = 1; load()"
          >
            <el-option v-for="(label, key) in TYPE_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </div>

        <DataTable :rows="logs" :columns="logColumns" :loading="loading" empty="暂无积分流水">
          <template #cell-username="{ row }">
            <span class="user-name">{{ row.username }}</span>
          </template>
          <template #cell-amount="{ row }">
            <span :class="row.amount > 0 ? 'amt-in' : 'amt-out'">
              {{ row.amount > 0 ? '+' : '' }}{{ row.amount }}
            </span>
          </template>
          <template #cell-type="{ row }">{{ TYPE_LABELS[row.type] || row.type }}</template>
          <template #cell-description="{ row }">
            <span v-if="!row.description" class="muted">—</span>
            <span v-else>{{ row.description }}</span>
          </template>
          <template #cell-balance_after="{ row }">{{ row.balance_after }}</template>
          <template #cell-created_at="{ row }">{{ fmtTime(row.created_at) }}</template>
        </DataTable>

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
    <el-dialog v-model="adjustVisible" title="手动调整用户积分" width="440px">
      <el-form label-position="top">
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
          <div class="form-hint">支持按用户名模糊搜索，无需再手填数据库 ID</div>
        </el-form-item>
        <el-form-item label="调整数量">
          <el-input-number v-model="adjustForm.amount" :step="10" style="width: 100%" />
          <div class="form-hint">正数发放 / 负数扣除（记账留审计）</div>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="adjustForm.reason" maxlength="100" placeholder="活动补偿等（选填）" />
        </el-form-item>
        <div v-if="selectedUser" class="adjust-preview">
          将对「{{ selectedUser }}」发放 / 扣减 {{ adjustForm.amount }} 积分
        </div>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button type="primary" :loading="adjustLoading" @click="handleAdjust">确认调整</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.link-button { text-decoration: none; }

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.35fr);
  gap: 14px;
  align-items: start;
}

.block-head h3 {
  margin: 0;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.user-name { font-weight: 600; color: var(--text-primary); }
.amt-in { color: #6ee7b7; font-weight: 600; font-variant-numeric: tabular-nums; }
.amt-out { color: #fda4af; font-weight: 600; font-variant-numeric: tabular-nums; }

.adjust-preview {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--primary-soft);
  border: 1px solid var(--primary-border);
  color: #a5eefb;
  font-size: var(--font-size-xs);
}

@media (max-width: 1000px) {
  .grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
