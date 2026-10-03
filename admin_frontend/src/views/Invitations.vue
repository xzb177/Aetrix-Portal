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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Coins, Gift, Megaphone, Plus, QrCode, RefreshCw, Settings } from 'lucide-vue-next'
import {
  fetchInvitations,
  fetchPointsLogs,
  fetchEconomyStats,
  adjustUserPoints,
  type InvitationRow,
  type PointsLogRow,
  type EconomyStats,
} from '@/api/economy'
import {
  fetchInvitationCodes,
  fetchPromotion,
  fetchUsers,
  generateInvitationCodes,
  revokeInvitationCodes,
  savePromotionPolicy,
  updateInvitationCode,
  type InvitationCodeRow,
  type PromotionResponse,
} from '@/api/admin'
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

// ===== 邀请码管理（v2.44.0） =====
const invLoading = ref(false)
const invCodes = ref<InvitationCodeRow[]>([])
const invSummary = ref<Record<string, number>>({})
const invStates = ref<{ value: string; label: string }[]>([])
const invKeyword = ref('')
const invState = ref('')

const invColumns: DataColumn[] = [
  { key: 'code', label: '邀请码', width: 130, mobile: 'title' },
  { key: 'owner_username', label: '归属', width: 120 },
  { key: 'use_count', label: '使用情况', width: 120 },
  { key: 'state_label', label: '状态', width: 90 },
  { key: 'expires_at', label: '有效期', width: 150 },
  { key: 'whitelist', label: '白名单', minWidth: 150 },
  // 用 actions：DataTable 会把这一列渲染到手机卡片的底部操作区，
  // 用 action 会退化成一行「标签 / 值」，按钮变得不好按
  { key: 'actions', label: '操作', width: 150 },
]

async function loadCodes() {
  invLoading.value = true
  try {
    const res = await fetchInvitationCodes({
      keyword: invKeyword.value || undefined,
      state: invState.value || undefined,
      limit: 300,
    })
    invCodes.value = res.codes
    invSummary.value = res.summary
    invStates.value = res.states
  } catch {
    /* 拦截器已提示 */
  } finally {
    invLoading.value = false
  }
}

const usesText = (row: InvitationCodeRow) =>
  row.max_uses ? `${row.use_count} / ${row.max_uses}` : `${row.use_count} / 不限`

// --- 批量生成 ---
const genVisible = ref(false)
const genLoading = ref(false)
const genForm = ref({ owner_user_id: null as number | null, count: 5, max_uses: 100, expires_days: 0, whitelist: '' })
const genOwner = computed(() =>
  userOptions.value.find((u) => u.id === genForm.value.owner_user_id)?.username,
)

async function openGen() {
  genForm.value = { owner_user_id: null, count: 5, max_uses: 100, expires_days: 0, whitelist: '' }
  genVisible.value = true
  if (!userOptions.value.length) await searchUsers('')
}

async function handleGen() {
  if (!genForm.value.owner_user_id) { ElMessage.warning('请先选择归属用户'); return }
  genLoading.value = true
  try {
    const res = await generateInvitationCodes({
      owner_user_id: genForm.value.owner_user_id,
      count: genForm.value.count,
      max_uses: genForm.value.max_uses,
      expires_days: genForm.value.expires_days,
      whitelist: genForm.value.whitelist,
    })
    ElMessage.success(res.message)
    genVisible.value = false
    await loadCodes()
  } catch {
    /* 拦截器已提示 */
  } finally {
    genLoading.value = false
  }
}

// --- 改单张 ---
const editVisible = ref(false)
const editLoading = ref(false)
const editForm = ref({ id: 0, code: '', max_uses: 100, expires_days: 0, whitelist: '', is_active: true })

function openEdit(row: InvitationCodeRow) {
  editForm.value = {
    id: row.id,
    code: row.code,
    max_uses: row.max_uses,
    // 有效天数按「从现在起」重算；0 = 永不过期
    expires_days: row.expires_days_left ?? 0,
    whitelist: row.whitelist.join(','),
    is_active: row.is_active,
  }
  editVisible.value = true
}

async function handleEdit() {
  editLoading.value = true
  try {
    const res = await updateInvitationCode(editForm.value.id, {
      max_uses: editForm.value.max_uses,
      expires_days: editForm.value.expires_days,
      whitelist: editForm.value.whitelist,
      is_active: editForm.value.is_active,
    })
    ElMessage.success('邀请码已更新')
    editVisible.value = false
    const idx = invCodes.value.findIndex((c) => c.id === res.code.id)
    if (idx >= 0) invCodes.value.splice(idx, 1, res.code)
  } catch {
    /* 拦截器已提示 */
  } finally {
    editLoading.value = false
  }
}

// --- 作废（可逆：只是把 is_active 翻成 false，行不删） ---
async function handleRevoke(rows: InvitationCodeRow[]) {
  if (!rows.length) return
  try {
    await ElMessageBox.confirm(
      `将作废 ${rows.length} 个邀请码？它们不能再被使用，但已产生的邀请关系不受影响。`,
      '作废邀请码',
      { type: 'warning', confirmButtonText: '作废', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const res = await revokeInvitationCodes(rows.map((r) => r.id))
  ElMessage.success(res.message)
  await loadCodes()
}

// ===== 推广奖励（v2.44.0） =====
const promo = ref<PromotionResponse | null>(null)
const promoLoading = ref(false)
const promoSaving = ref(false)
const promoDraft = ref({ enabled: false, reward_type: 'balance', amount: 0, days: 0 })

const promoDirty = computed(() => {
  const p = promo.value?.policy
  if (!p) return false
  return (
    p.enabled !== promoDraft.value.enabled ||
    p.reward_type !== promoDraft.value.reward_type ||
    p.amount !== promoDraft.value.amount ||
    p.days !== promoDraft.value.days
  )
})

const promoHint = computed(() => {
  const d = promoDraft.value
  if (!d.enabled) return '当前关闭：邀请成功只发原有的双向积分，不发推广奖励。'
  const value = d.reward_type === 'days' ? d.days : d.amount
  if (value <= 0) return '开关已开但数值为 0，等同没发——填一个大于 0 的数才会真的发。'
  return d.reward_type === 'days'
    ? `开启中：每邀请成功 1 人，给邀请人加 ${d.days} 天会员有效期。`
    : `开启中：每邀请成功 1 人，给邀请人加 ${d.amount} 积分。`
})

async function loadPromotion() {
  promoLoading.value = true
  try {
    promo.value = await fetchPromotion({ limit: 100 })
    const p = promo.value.policy
    promoDraft.value = { enabled: p.enabled, reward_type: p.reward_type, amount: p.amount, days: p.days }
  } catch {
    /* 拦截器已提示 */
  } finally {
    promoLoading.value = false
  }
}

async function savePromotion() {
  promoSaving.value = true
  try {
    const res = await savePromotionPolicy({
      promotion_reward_enabled: promoDraft.value.enabled ? 'true' : 'false',
      promotion_reward_type: promoDraft.value.reward_type,
      promotion_reward_amount: String(promoDraft.value.amount),
      promotion_reward_days: String(promoDraft.value.days),
    })
    promo.value = { ...(promo.value as PromotionResponse), policy: res.policy }
    promoDraft.value = {
      enabled: res.policy.enabled,
      reward_type: res.policy.reward_type,
      amount: res.policy.amount,
      days: res.policy.days,
    }
    ElMessage.success('推广奖励配置已保存并立即生效')
  } catch {
    /* 拦截器已提示 */
  } finally {
    promoSaving.value = false
  }
}

const promoColumns: DataColumn[] = [
  { key: 'inviter_username', label: '邀请人', width: 130, mobile: 'title' },
  { key: 'invitee_username', label: '被邀请人', width: 130 },
  { key: 'reward_type_label', label: '类型', width: 120 },
  { key: 'reward_value', label: '数值', width: 90 },
  { key: 'created_at', label: '时间' },
]

const TYPE_LABELS: Record<string, string> = {
  checkin: '签到', invite: '邀请奖励', invitee: '受邀奖励', rebate: '充值返利',
  exchange: '兑换码', recharge: '充值', admin_grant: '管理发放', admin_deduct: '管理扣除',
}

function reloadAll() {
  load()
  loadCodes()
  loadPromotion()
}

onMounted(reloadAll)
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">邀请与积分</h1>
        <p class="admin-page-desc">邀请台账与全站积分流水；规则参数已移至「系统设置」</p>
      </div>
      <div class="admin-page-actions">
        <el-button :loading="loading" @click="reloadAll">
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

    <!-- 邀请码管理（v2.44.0） -->
    <section class="admin-card block inv-card">
      <div class="block-head inv-head">
        <h3><QrCode :size="15" class="head-icon" />邀请码</h3>
        <div class="inv-tools">
          <span class="inv-summary">
            共 {{ invSummary.total ?? 0 }} 张 · 可用 {{ invSummary.active ?? 0 }} ·
            已用 {{ invSummary.uses ?? 0 }} 次
          </span>
          <el-select
            v-model="invState"
            placeholder="全部状态"
            clearable
            size="small"
            style="width: 118px"
            @change="loadCodes"
          >
            <el-option v-for="s in invStates" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
          <el-input
            v-model="invKeyword"
            size="small"
            placeholder="搜邀请码"
            clearable
            style="width: 150px"
            @change="loadCodes"
            @clear="loadCodes"
          />
          <el-button size="small" type="primary" @click="openGen">
            <Plus :size="14" style="margin-right: 4px" />批量生成
          </el-button>
        </div>
      </div>
      <p class="inv-hint">
        这里是<strong>管理员维度</strong>发的渠道码；每个用户自己那张码（个人中心 → 邀请）不受影响。
        「0 次数」= 不限，「无有效期」= 永不过期，白名单留空 = 谁都能用。
      </p>

      <DataTable :rows="invCodes" :columns="invColumns" :loading="invLoading"
                 empty="还没有邀请码：点右上角「批量生成」发一批">
        <template #cell-code="{ row }">
          <span class="inv-code mono">{{ row.code }}</span>
        </template>
        <template #cell-owner_username="{ row }">
          <span class="user-name">{{ row.owner_username }}</span>
        </template>
        <template #cell-use_count="{ row }">{{ usesText(row) }}</template>
        <template #cell-state_label="{ row }">
          <span class="mini-badge"
                :class="row.state === 'active' ? 'success'
                  : row.state === 'revoked' ? 'muted'
                  : row.state === 'expired' ? 'danger' : 'warn'">
            {{ row.state_label }}
          </span>
        </template>
        <template #cell-expires_at="{ row }">
          <span v-if="!row.expires_at" class="muted">永久</span>
          <span v-else>{{ fmtTime(row.expires_at) }}</span>
        </template>
        <template #cell-whitelist="{ row }">
          <span v-if="!row.whitelist.length" class="muted">不限</span>
          <span v-else>{{ row.whitelist.join('、') }}</span>
        </template>
        <template #cell-actions="{ row }">
          <div class="inv-row-actions">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.is_active" size="small" type="danger" plain
                       @click="handleRevoke([row])">作废</el-button>
          </div>
        </template>
      </DataTable>
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

    <!-- 推广奖励（v2.44.0）：开关与阈值全在系统设置里也能改，这里两处同一份 -->
    <section class="admin-card block" style="margin-top: 14px">
      <div class="block-head inv-head">
        <h3><Megaphone :size="15" class="head-icon" />推广奖励</h3>
        <span v-if="promoDirty" class="promo-dirty">有未保存的改动</span>
      </div>
      <p class="inv-hint">
        邀请成功后在双向积分之外「另发」一笔，类型与数值全走配置。
        <strong>默认关闭</strong>——不手动打开就不会发；明细同时在「系统设置 → 邀请返利」里可改。
      </p>

      <div v-if="promo" class="promo-form">
        <el-switch v-model="promoDraft.enabled" active-text="开启" inactive-text="关闭" />
        <el-select v-model="promoDraft.reward_type" style="width: 170px">
          <el-option v-for="t in promo.policy.reward_types" :key="t"
                     :value="t" :label="promo.policy.reward_type_labels[t] || t" />
        </el-select>
        <template v-if="promoDraft.reward_type === 'days'">
          <el-input-number v-model="promoDraft.days" :min="0" :max="3650"
                           controls-position="right" style="width: 130px" />
          <span class="field-suffix">天</span>
        </template>
        <template v-else>
          <el-input-number v-model="promoDraft.amount" :min="0" :max="1000000"
                           controls-position="right" style="width: 150px" />
          <span class="field-suffix">积分</span>
        </template>
        <el-button type="primary" size="small" :disabled="!promoDirty" :loading="promoSaving"
                   @click="savePromotion">保存</el-button>
        <span class="promo-state" :class="{ 'is-off': !promoDraft.enabled }">{{ promoHint }}</span>
      </div>

      <DataTable :rows="promo?.rewards || []" :columns="promoColumns" :loading="promoLoading"
                 empty="还没有推广奖励记录（开关默认关闭，打开后邀请成功才会记在这里）">
        <template #cell-inviter_username="{ row }">
          <span class="user-name">{{ row.inviter_username || '—' }}</span>
        </template>
        <template #cell-invitee_username="{ row }">{{ row.invitee_username }}</template>
        <template #cell-reward_type_label="{ row }">
          <span class="mini-badge info">{{ row.reward_type_label }}</span>
        </template>
        <template #cell-reward_value="{ row }">
          <span class="amt-in">+{{ row.reward_value }}</span>
        </template>
        <template #cell-created_at="{ row }">{{ fmtTime(row.created_at) }}</template>
      </DataTable>
    </section>

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

    <!-- 批量生成邀请码 -->
    <el-dialog v-model="genVisible" title="批量生成邀请码" width="460px">
      <el-form label-position="top">
        <el-form-item label="归属用户">
          <el-select
            v-model="genForm.owner_user_id"
            filterable
            remote
            reserve-keyword
            :remote-method="searchUsers"
            :loading="userSearching"
            placeholder="搜索用户名（这些码都算他的邀请）"
            style="width: 100%"
          >
            <el-option v-for="u in userOptions" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="生成数量">
          <el-input-number v-model="genForm.count" :min="1" :max="200" style="width: 100%" />
          <div class="form-hint">1–200 张，同一规格，每张码不同</div>
        </el-form-item>
        <el-form-item label="每码可用次数">
          <el-input-number v-model="genForm.max_uses" :min="0" :max="100000" style="width: 100%" />
          <div class="form-hint">0 = 不限次数</div>
        </el-form-item>
        <el-form-item label="有效天数">
          <el-input-number v-model="genForm.expires_days" :min="0" :max="3650" style="width: 100%" />
          <div class="form-hint">0 = 永不过期；从生成那一刻开始算</div>
        </el-form-item>
        <el-form-item label="白名单（可选）">
          <el-input v-model="genForm.whitelist" placeholder="留空 = 谁都能用；多个用户名用逗号分隔"
                    type="textarea" :rows="2" />
          <div class="form-hint">填了就只有这些人能拿这个码注册（内测码 / 渠道码）</div>
        </el-form-item>
        <div v-if="genOwner" class="adjust-preview">将为「{{ genOwner }}」生成 {{ genForm.count }} 个邀请码</div>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="genLoading" @click="handleGen">生成</el-button>
      </template>
    </el-dialog>

    <!-- 改单张邀请码 -->
    <el-dialog v-model="editVisible" :title="`编辑邀请码 ${editForm.code}`" width="460px">
      <el-form label-position="top">
        <el-form-item label="每码可用次数">
          <el-input-number v-model="editForm.max_uses" :min="0" :max="100000" style="width: 100%" />
          <div class="form-hint">0 = 不限次数</div>
        </el-form-item>
        <el-form-item label="有效天数（从现在起）">
          <el-input-number v-model="editForm.expires_days" :min="0" :max="3650" style="width: 100%" />
          <div class="form-hint">0 = 永不过期</div>
        </el-form-item>
        <el-form-item label="白名单">
          <el-input v-model="editForm.whitelist" placeholder="留空 = 不限；多个用户名用逗号分隔"
                    type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="editForm.is_active" active-text="可用" inactive-text="已作废" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="handleEdit">保存</el-button>
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
/* 收支金额：写死的浅绿/浅玫瑰在白日模式下只有 1.6~2:1，改走语义 token */
.amt-in { color: var(--success); font-weight: 600; font-variant-numeric: tabular-nums; }
.amt-out { color: var(--danger); font-weight: 600; font-variant-numeric: tabular-nums; }

.adjust-preview {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--primary-soft);
  border: 1px solid var(--primary-border);
  color: var(--primary);
  font-size: var(--font-size-xs);
}

/* ===== 邀请码 / 推广奖励（v2.44.0）=====
   block-head 是全局原语，这里只补头部的换行与右侧工具条 */
.inv-card { margin-bottom: 14px; }
.inv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.head-icon { margin-right: 6px; vertical-align: -2px; color: var(--text-secondary); }
.inv-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.inv-summary { font-size: var(--font-size-xs); color: var(--text-tertiary); }
.inv-hint {
  margin: 6px 0 12px;
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  line-height: 1.8;
}
.inv-code { font-size: var(--font-size-sm); color: var(--text-primary); letter-spacing: 0.4px; }
.inv-row-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.promo-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
.promo-state {
  flex: 1 1 220px;
  font-size: var(--font-size-xs);
  color: var(--success);
  line-height: 1.7;
}
.promo-state.is-off { color: var(--text-tertiary); }
.promo-dirty { color: var(--warning); font-size: var(--font-size-xs); }
.field-suffix { font-size: var(--font-size-xs); color: var(--text-tertiary); }

@media (max-width: 1000px) {
  .grid { grid-template-columns: minmax(0, 1fr); }
}

/* 手机：工具条竖排，提示文案占满整行
   宽度覆盖要 !important：这些 el-input / el-select / el-input-number 在标记上写了
   行内 style（桌面端固定宽），普通样式表压不住行内样式 */
@media (max-width: 767px) {
  .inv-head { align-items: flex-start; }
  .inv-tools { width: 100%; }
  .inv-tools .el-input,
  .inv-tools .el-select { flex: 1 1 auto; width: auto !important; min-width: 110px; }
  .inv-tools .el-button { flex: 1 1 auto; }
  .promo-form { flex-direction: column; align-items: stretch; }
  .promo-form .el-input-number,
  .promo-form .el-select { width: 100% !important; }
  .promo-state { flex: 1 1 auto; }
}
</style>
