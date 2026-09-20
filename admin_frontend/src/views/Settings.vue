<script setup lang="ts">
/**
 * 系统设置
 *
 * v2.4.0 新增：
 * - 注册策略（开放 / 注册码 / 关闭 + 关闭提示文案）
 * - 经济与支付配置（签到、兑换、充值、支付网关、邀请返利）按域分组保存
 * v2.5.2 新增：付费墙分组（要求有效订阅 + 拦截提示文案）
 *
 * 说明：支付密钥等敏感项由后端以 ****** 掩码返回，留空即保持原值不变。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CalendarCheck, Coins, KeyRound, RefreshCw, Save, TicketCheck,
  UserPlus, Wallet, ShieldAlert, Lock,
} from 'lucide-vue-next'
import { fetchRegistrationSettings, updateRegistrationSettings } from '@/api/admin'
import { fetchEconomySettings, updateEconomySettings, type EconomySettings } from '@/api/economy'

type FieldType = 'bool' | 'int' | 'str' | 'secret'

interface Field {
  key: string
  label: string
  type: FieldType
  hint?: string
  suffix?: string
}

interface Group {
  id: string
  title: string
  desc: string
  icon: unknown
  fields: Field[]
}

const GROUPS: Group[] = [
  {
    id: 'checkin',
    title: '每日签到',
    desc: '签到基础积分与连签加成规则',
    icon: CalendarCheck,
    fields: [
      { key: 'checkin_enabled', label: '启用签到', type: 'bool' },
      { key: 'checkin_base_points', label: '基础积分', type: 'int', suffix: '积分/次' },
      { key: 'checkin_streak_bonus', label: '连签加成', type: 'int', suffix: '积分/天', hint: '每多连签一天额外增加的积分' },
      { key: 'checkin_streak_max_bonus', label: '加成上限', type: 'int', suffix: '积分', hint: '连签加成的封顶值' },
    ],
  },
  {
    id: 'exchange',
    title: '兑换码 · 求片',
    desc: '兑换开关与用户每日求片上限',
    icon: TicketCheck,
    fields: [
      { key: 'exchange_enabled', label: '启用兑换', type: 'bool' },
      {
        key: 'media_seek_daily_limit',
        label: '每日求片上限',
        type: 'int',
        suffix: '条/天',
        hint: '用户端提交求片时的硬性限额，未设置时默认 5 条',
      },
    ],
  },
  {
    id: 'payment',
    title: '充值 · 支付',
    desc: '易支付兼容网关；留空的密钥项表示保持不变',
    icon: Wallet,
    fields: [
      { key: 'recharge_enabled', label: '启用充值', type: 'bool' },
      { key: 'subscription_purchase_enabled', label: '启用订阅购买', type: 'bool' },
      { key: 'payment_gateway_url', label: '网关地址', type: 'str', hint: '例如 https://pay.example.com/' },
      { key: 'payment_partner_id', label: '商户 ID', type: 'str' },
      { key: 'payment_partner_key', label: '商户密钥', type: 'secret', hint: '已配置时显示为 ******，留空不修改' },
      { key: 'payment_qqpay_enabled', label: '启用 QQ 钱包', type: 'bool' },
      { key: 'site_url', label: '站点地址', type: 'str', hint: '用于支付回调，必须是外网可访问地址' },
    ],
  },
  {
    id: 'paywall',
    title: '付费墙（会员门禁）',
    desc: '开启后，非会员无法播放与下载；管理员账号始终放行',
    icon: Lock,
    fields: [
      {
        key: 'subscription_required',
        label: '要求有效订阅',
        type: 'bool',
        hint: '关闭则所有人均可直接播放',
      },
      {
        key: 'subscription_gate_message',
        label: '拦截提示文案',
        type: 'str',
        hint: '留空使用默认：需要有效的会员订阅才能播放，请先开通会员',
      },
    ],
  },
  {
    id: 'invitation',
    title: '邀请返利',
    desc: '邀请奖励与下级消费返利比例',
    icon: UserPlus,
    fields: [
      { key: 'invitation_enabled', label: '启用邀请', type: 'bool' },
      { key: 'invitation_reward_points', label: '邀请人奖励', type: 'int', suffix: '积分' },
      { key: 'invitation_invitee_reward_points', label: '被邀请人奖励', type: 'int', suffix: '积分' },
      { key: 'invitation_rebate_percent', label: '消费返利', type: 'int', suffix: '%', hint: '下级充值/消费时邀请人可得的比例' },
    ],
  },
]

const loading = ref(true)
const savingGroup = ref('')
const settings = reactive<EconomySettings>({})
const original = ref<EconomySettings>({})

/** 注册策略 */
const reg = reactive({ mode: 'open', message: '' })
const regSaving = ref(false)

const regModeHint = computed(() => {
  const map: Record<string, string> = {
    open: '任何人都可以直接注册',
    code: '必须填写有效注册码才能注册',
    closed: '关闭注册入口，仅显示提示文案',
  }
  return map[reg.mode] || ''
})

async function load() {
  loading.value = true
  try {
    const [econ, registration] = await Promise.all([
      fetchEconomySettings(),
      fetchRegistrationSettings(),
    ])
    Object.assign(settings, econ.settings)
    original.value = { ...econ.settings }
    reg.mode = registration.mode
    reg.message = registration.message || ''
  } catch {
    // 错误提示由 HTTP 拦截器统一处理
  } finally {
    loading.value = false
  }
}

onMounted(load)

function isDirty(group: Group): boolean {
  return group.fields.some((f) => String(settings[f.key] ?? '') !== String(original.value[f.key] ?? ''))
}

async function saveGroup(group: Group) {
  const payload: EconomySettings = {}
  for (const f of group.fields) {
    const raw = String(settings[f.key] ?? '').trim()
    if (f.type === 'int') {
      const n = Number.parseInt(raw === '' ? '0' : raw, 10)
      payload[f.key] = String(Number.isFinite(n) && n >= 0 ? n : 0)
    } else if (f.type === 'bool') {
      payload[f.key] = raw === 'false' ? 'false' : 'true'
    } else {
      payload[f.key] = raw
    }
  }
  savingGroup.value = group.id
  try {
    await updateEconomySettings(payload)
    ElMessage.success(`「${group.title}」已保存`)
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    savingGroup.value = ''
  }
}

const paymentReady = computed(() => {
  const url = String(settings.payment_gateway_url || '')
  const pid = String(settings.payment_partner_id || '')
  const keySet = String(settings.payment_partner_key || '') === '******'
  return Boolean(url && pid && keySet)
})

async function saveRegistration() {
  regSaving.value = true
  try {
    await updateRegistrationSettings({ mode: reg.mode, message: reg.message })
    ElMessage.success('注册策略已保存')
  } catch {
    // 拦截器已提示
  } finally {
    regSaving.value = false
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">系统设置</h1>
        <p class="admin-page-subtitle">注册策略与运营参数；修改后立即对用户端生效</p>
      </div>
      <el-button @click="load"><RefreshCw :size="14" style="margin-right: 4px" />重新载入</el-button>
    </div>

    <div v-loading="loading" class="settings-body">
      <!-- 注册策略 -->
      <section class="admin-card">
        <header class="card-header">
          <div class="card-title">
            <KeyRound :size="16" />
            <div>
              <h2>注册策略</h2>
              <p>决定新用户如何进入站点</p>
            </div>
          </div>
        </header>

        <el-form label-width="96px" class="field-form">
          <el-form-item label="注册模式">
            <el-radio-group v-model="reg.mode">
              <el-radio-button value="open">开放注册</el-radio-button>
              <el-radio-button value="code">注册码</el-radio-button>
              <el-radio-button value="closed">关闭注册</el-radio-button>
            </el-radio-group>
            <span class="field-hint">{{ regModeHint }}</span>
          </el-form-item>
          <el-form-item v-if="reg.mode === 'closed'" label="关闭提示">
            <el-input v-model="reg.message" type="textarea" :rows="2" placeholder="展示给无法注册的用户…" />
          </el-form-item>
        </el-form>

        <div class="card-footer">
          <el-button type="primary" :loading="regSaving" @click="saveRegistration">
            <Save :size="14" style="margin-right: 4px" />保存注册策略
          </el-button>
        </div>
      </section>

      <!-- 支付状态提示 -->
      <div class="notice" :class="{ ok: paymentReady }">
        <ShieldAlert :size="15" />
        <span v-if="paymentReady">支付网关已配置完成，用户端可直接下单充值。</span>
        <span v-else>支付网关尚未配置齐全（需要网关地址 + 商户 ID + 商户密钥），用户端充值下单会提示未启用。</span>
      </div>

      <!-- 经济配置分组 -->
      <section v-for="g in GROUPS" :key="g.id" class="admin-card">
        <header class="card-header">
          <div class="card-title">
            <component :is="g.icon" :size="16" />
            <div>
              <h2>{{ g.title }}</h2>
              <p>{{ g.desc }}</p>
            </div>
          </div>
          <span v-if="isDirty(g)" class="dirty-dot">未保存</span>
        </header>

        <el-form label-width="120px" class="field-form">
          <el-form-item v-for="f in g.fields" :key="f.key" :label="f.label">
            <el-switch
              v-if="f.type === 'bool'"
              v-model="settings[f.key]"
              active-value="true"
              inactive-value="false"
            />
            <el-input
              v-else-if="f.type === 'int'"
              v-model="settings[f.key]"
              type="number"
              min="0"
              class="num-input"
            />
            <el-input
              v-else
              v-model="settings[f.key]"
              :type="f.type === 'secret' ? 'password' : 'text'"
              :show-password="f.type === 'secret'"
              :placeholder="f.type === 'secret' ? '留空表示不修改' : ''"
            />
            <span v-if="f.suffix" class="field-suffix">{{ f.suffix }}</span>
            <span v-if="f.hint" class="field-hint">{{ f.hint }}</span>
          </el-form-item>
        </el-form>

        <div class="card-footer">
          <el-button
            type="primary"
            :disabled="!isDirty(g)"
            :loading="savingGroup === g.id"
            @click="saveGroup(g)"
          >
            <Save :size="14" style="margin-right: 4px" />保存{{ g.title }}
          </el-button>
        </div>
      </section>

      <p class="foot-note">
        <Coins :size="13" />
        积分、套餐与兑换码的明细请前往「商品与套餐」「兑换码」「邀请与积分」页面管理。
      </p>
    </div>
  </div>
</template>

<style scoped>
.settings-body { display: flex; flex-direction: column; gap: 14px; }

.card-title { display: flex; align-items: flex-start; gap: 10px; }
.card-title h2 { font-size: 15px; margin: 0; }
.card-title p { font-size: 12px; color: var(--text-muted); margin: 2px 0 0; }

.field-form { max-width: 640px; }
.field-suffix { margin-left: 8px; font-size: 12px; color: var(--text-muted); }
.field-hint { margin-left: 10px; font-size: 12px; color: var(--text-muted); }
.num-input { width: 140px; }
.num-input :deep(.el-input__wrapper) { padding-left: 11px; }

.card-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
  margin-top: 4px;
}

.dirty-dot {
  font-size: 11px;
  color: var(--warning);
  background: var(--warning-bg);
  border-radius: var(--radius-full);
  padding: 2px 10px;
}

.notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 13px;
  border: 1px solid rgba(251, 191, 36, 0.28);
  background: var(--warning-bg);
  color: var(--warning);
}

.notice.ok {
  border-color: rgba(52, 211, 153, 0.28);
  background: var(--success-bg);
  color: var(--success);
}

.foot-note {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-muted);
  padding: 4px 2px 10px;
}
</style>
