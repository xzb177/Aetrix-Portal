<script setup lang="ts">
/**
 * 邀请与积分管理：邀请记录、积分流水、手动调整、经济系统设置
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshCw, Settings, Plus } from 'lucide-vue-next'
import {
  fetchInvitations,
  fetchPointsLogs,
  adjustUserPoints,
  fetchEconomySettings,
  updateEconomySettings,
  type InvitationRow,
  type PointsLogRow,
  type EconomySettings as EconomySettingsMap,
} from '@/api/economy'

const loading = ref(false)

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

// ===== 经济设置 =====
const settingsVisible = ref(false)
const settings = ref<EconomySettingsMap>({})
const settingsLoading = ref(false)

const SECRET_LABELS: Record<string, string> = {
  checkin_enabled: '签到开启 (true/false)',
  checkin_base_points: '签到基础积分',
  checkin_streak_bonus: '连签每日加成',
  checkin_streak_max_bonus: '连签加成上限',
  exchange_enabled: '兑换码开启 (true/false)',
  recharge_enabled: '充值开启 (true/false)',
  subscription_purchase_enabled: '订阅购买开启 (true/false)',
  payment_gateway_url: '支付网关地址（易支付 submit.php 同级）',
  payment_partner_id: '支付商户 ID (pid)',
  payment_partner_key: '支付商户密钥（留 ****** 不变）',
  payment_qqpay_enabled: 'QQ 钱包支付 (true/false)',
  site_url: '站点地址（回调用，如 https://example.com）',
  invitation_enabled: '邀请开启 (true/false)',
  invitation_reward_points: '邀请者奖励积分',
  invitation_invitee_reward_points: '被邀请者奖励积分',
  invitation_rebate_percent: '充值返利百分比 (%)',
}

async function load() {
  loading.value = true
  try {
    const [inv, log] = await Promise.all([
      fetchInvitations({ limit: 100 }).catch(() => ({ records: [] })),
      fetchPointsLogs({ limit: 30, offset: (logPage.value - 1) * 30, type_filter: logTypeFilter.value || undefined }),
    ])
    invitations.value = inv.records
    logs.value = log.logs
    logTotal.value = log.total
  } finally {
    loading.value = false
  }
}

async function openAdjust() {
  adjustVisible.value = true
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
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '调整失败')
  } finally {
    adjustLoading.value = false
  }
}

async function openSettings() {
  settingsVisible.value = true
  settingsLoading.value = true
  try {
    const res = await fetchEconomySettings()
    settings.value = res.settings
  } finally {
    settingsLoading.value = false
  }
}

async function saveSettings() {
  settingsLoading.value = true
  try {
    await updateEconomySettings(settings.value)
    ElMessage.success('设置已保存')
    settingsVisible.value = false
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '保存失败')
  } finally {
    settingsLoading.value = false
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
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-title">运营 · 邀请与积分</h2>
        <p class="page-sub">邀请记录、全站积分流水与经济系统设置</p>
      </div>
      <div class="head-actions">
        <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
        <el-button :icon="Plus" @click="openAdjust">调整积分</el-button>
        <el-button :icon="Settings" type="primary" @click="openSettings">经济设置</el-button>
      </div>
    </header>

    <div class="grid">
      <!-- 邀请记录 -->
      <section class="block">
        <h3>邀请记录（最新 {{ invitations.length }} 条）</h3>
        <el-table :data="invitations" size="small" stripe max-height="420">
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
      <section class="block">
        <div class="block-head-row">
          <h3>积分流水（共 {{ logTotal }} 条）</h3>
          <el-select v-model="logTypeFilter" placeholder="全部类型" clearable size="small" style="width: 130px" @change="logPage = 1; load()">
            <el-option v-for="(label, key) in TYPE_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </div>
        <el-table :data="logs" size="small" stripe max-height="420">
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
    <el-dialog v-model="adjustVisible" title="手动调整用户积分" width="420">
      <el-form label-width="90px">
        <el-form-item label="用户 ID">
          <el-input-number v-model="adjustForm.user_id" :min="1" style="width: 100%" placeholder="WebUser ID" />
        </el-form-item>
        <el-form-item label="调整数量">
          <el-input-number v-model="adjustForm.amount" :step="10" style="width: 100%" />
          <div class="hint">正数发放 / 负数扣除（记账留审计）</div>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="adjustForm.reason" maxlength="100" placeholder="活动补偿等（选填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button type="primary" :loading="adjustLoading" @click="handleAdjust">确认调整</el-button>
      </template>
    </el-dialog>

    <!-- 经济设置对话框 -->
    <el-dialog v-model="settingsVisible" title="经济系统设置" width="640" top="5vh">
      <div v-loading="settingsLoading" class="settings-grid">
        <el-form v-if="Object.keys(settings).length" label-position="top" size="default">
          <el-form-item v-for="(label, key) in SECRET_LABELS" :key="key" :label="String(label)">
            <el-switch
              v-if="key.endsWith('_enabled')"
              :model-value="settings[key] === 'true'"
              active-text="开"
              inactive-text="关"
              @update:model-value="(v: string | number | boolean) => settings[key] = v ? 'true' : 'false'"
            />
            <el-input-number
              v-else-if="key.includes('points') || key.includes('percent') || key.includes('bonus')"
              :model-value="Number(settings[key] || 0)"
              :min="0"
              style="width: 100%"
              @update:model-value="(v?: number) => settings[key] = String(v ?? 0)"
            />
            <el-input
              v-else
              :model-value="settings[key]"
              :placeholder="key === 'payment_partner_key' ? '未设置' : ''"
              @update:model-value="(v: string) => settings[key] = v"
            />
          </el-form-item>
        </el-form>
        <div class="hint">密钥显示为 ****** 表示已设置且保持不变；填写新值即可替换。</div>
      </div>
      <template #footer>
        <el-button @click="settingsVisible = false">取消</el-button>
        <el-button type="primary" :loading="settingsLoading" @click="saveSettings">保存设置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }

.page-head { display: flex; align-items: flex-start; justify-content: space-between; }
.page-title { margin: 0 0 4px; font-size: 20px; font-weight: 700; }
.page-sub { margin: 0; font-size: 13px; opacity: 0.6; }

.head-actions { display: flex; gap: 8px; }

.grid {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 16px;
  align-items: start;
}

.block {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  padding: 16px;
}
.block h3 { margin: 0 0 12px; font-size: 15px; font-weight: 700; }

.block-head-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.block-head-row h3 { margin: 0; font-size: 15px; font-weight: 700; }

.amt-in { color: var(--el-color-success); font-weight: 600; }
.amt-out { color: var(--el-color-danger); font-weight: 600; }

.pager { margin-top: 10px; justify-content: flex-end; }

.hint { font-size: 12px; opacity: 0.55; margin-top: 4px; }

.settings-grid { max-height: 62vh; overflow-y: auto; padding-right: 8px; }

@media (max-width: 1000px) {
  .grid { grid-template-columns: 1fr; }
}
</style>
