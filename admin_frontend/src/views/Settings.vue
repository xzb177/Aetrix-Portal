<script setup lang="ts">
/**
 * 系统设置
 *
 * v2.4.0 注册策略（开放 / 注册码 / 关闭 + 关闭提示文案）与经济配置分组
 * v2.5.2 付费墙分组（要求有效订阅 + 拦截提示文案）
 * v2.6.0 下载与设备风控分组（下载开关 / 设备上限 / 自动踢人 / 日志保留）
 * v2.19.0 **外部服务能力中心**：代理 / 人机验证 / 邮件与模板 / Telegram / AI 模型 / IP 归属地
 *
 * 能力中心的口径：**项目只提供能力，凭据一律由管理员自己填**。字段表由后端下发，
 * 这里只按类型渲染控件，所以后端加字段不需要改这个页面，也不会出现「界面漏了字段」。
 * 密钥字段后端只回 ******，留空即保持原值不变。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CalendarCheck, Coins, Globe, KeyRound, Mail, MapPin, Network, Palette, RefreshCw, Save,
  ShieldCheck, Send, Sparkles, TicketCheck, UserPlus, Wallet, ShieldAlert, Lock, Zap,
} from 'lucide-vue-next'
import { fetchRegistrationSettings, updateRegistrationSettings } from '@/api/admin'
import { fetchEconomySettings, updateEconomySettings, type EconomySettings } from '@/api/economy'
import {
  fetchCapabilities, fetchCapability, saveCapability, testCapability,
  type CapabilityCard, type CapabilityField, type CapabilityTestResult,
} from '@/api/capabilities'
import NoticePanel from '@/components/NoticePanel.vue'

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
    id: 'risk',
    title: '下载与设备风控',
    desc: '下载开关、设备上限与安全日志保留策略',
    icon: ShieldAlert,
    fields: [
      {
        key: 'allow_download',
        label: '允许下载',
        type: 'bool',
        hint: '关闭后客户端下载（含 /Items/{id}/File）一并拦截，管理员不受限',
      },
      {
        key: 'device_limit_per_user',
        label: '设备上限',
        type: 'int',
        suffix: '台/人',
        hint: '0 或不填表示不限；只统计近 30 天活跃设备',
      },
      {
        key: 'device_limit_auto_evict',
        label: '超限自动踢人',
        type: 'bool',
        hint: '开启则自动移除最久未使用的设备；关闭则直接拒绝新设备',
      },
      {
        key: 'login_log_retention_days',
        label: '日志保留',
        type: 'int',
        suffix: '天',
        hint: '登录与安全日志的保留期，未设置时默认 90 天',
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

// ==================== 外部服务能力中心 ====================

const CAP_ICONS: Record<string, unknown> = {
  proxy: Network, captcha: ShieldCheck, mail: Mail,
  telegram: Send, ai: Sparkles, geoip: MapPin, branding: Palette,
}

/** 少数能力测试需要额外输入（收件地址 / 要查的 IP / 探测地址） */
const TEST_INPUTS: Record<string, { key: string; label: string; placeholder: string }> = {
  mail: { key: 'to', label: '收件地址', placeholder: '留空则发给发件地址' },
  geoip: { key: 'ip', label: '要查的 IP', placeholder: '默认 8.8.8.8' },
  proxy: { key: 'target', label: '探测地址', placeholder: '默认 https://www.gstatic.com/generate_204' },
}

const capabilities = ref<CapabilityCard[]>([])
const capsLoading = ref(true)
const capGroups = computed(() => {
  const groups: { name: string; items: CapabilityCard[] }[] = []
  for (const card of capabilities.value) {
    const found = groups.find((g) => g.name === card.group)
    if (found) found.items.push(card)
    else groups.push({ name: card.group, items: [card] })
  }
  return groups
})

const drawerOpen = ref(false)
const drawerSlug = ref('')
const drawerTitle = ref('')
const drawerDesc = ref('')
const drawerHint = ref('')
const drawerFields = ref<CapabilityField[]>([])
const drawerValues = reactive<Record<string, string>>({})
const drawerOriginal = ref<Record<string, string>>({})
const drawerTestLabel = ref('测试连接')
// 没有 test() 的能力（例如站点与品牌）不显示「测试」按钮——
// 点了只会回一句「不支持测试」的按钮，本质是界面在骗人
const drawerTestable = ref(true)
const capSaving = ref(false)
const capTesting = ref(false)
const testInput = reactive({ value: '' })
const testResult = ref<CapabilityTestResult | null>(null)

const drawerDirty = computed(() =>
  drawerFields.value.some((f) => String(drawerValues[f.key] ?? '') !== String(drawerOriginal.value[f.key] ?? ''))
)
const drawerTestInput = computed(() => TEST_INPUTS[drawerSlug.value])

function capStatus(card: CapabilityCard): { label: string; tone: 'ok' | 'warn' | 'idle' } {
  if (card.enabled) return { label: '已启用', tone: 'ok' }
  if (card.configured) return { label: '已配置 · 未启用', tone: 'warn' }
  return { label: '未配置', tone: 'idle' }
}

async function loadCapabilities() {
  capsLoading.value = true
  try {
    const res = await fetchCapabilities()
    capabilities.value = res.capabilities
  } catch {
    // 拦截器已提示
  } finally {
    capsLoading.value = false
  }
}

async function openCapability(slug: string) {
  try {
    const detail = await fetchCapability(slug)
    drawerSlug.value = slug
    drawerTitle.value = detail.spec.title
    drawerDesc.value = detail.spec.desc
    drawerHint.value = detail.spec.docs_hint || ''
    drawerFields.value = detail.spec.fields
    drawerTestLabel.value = detail.item.test_label || '测试连接'
    drawerTestable.value = detail.item.testable !== false
    for (const key of Object.keys(drawerValues)) delete drawerValues[key]
    for (const f of detail.spec.fields) {
      drawerValues[f.key] = detail.values[f.key] ?? f.default ?? ''
    }
    drawerOriginal.value = { ...drawerValues }
    testResult.value = null
    testInput.value = ''
    drawerOpen.value = true
  } catch {
    // 拦截器已提示
  }
}

async function saveCurrentCapability() {
  capSaving.value = true
  try {
    await saveCapability(drawerSlug.value, { ...drawerValues })
    ElMessage.success(`「${drawerTitle.value}」已保存${drawerSlug.value === 'proxy' ? '，出站代理立即生效' : ''}`)
    drawerOriginal.value = { ...drawerValues }
    await Promise.all([loadCapabilities(), openCapability(drawerSlug.value)])
    await load()
  } catch {
    // 拦截器已提示
  } finally {
    capSaving.value = false
  }
}

async function runCapabilityTest() {
  capTesting.value = true
  testResult.value = null
  try {
    const payload: Record<string, unknown> = {}
    if (drawerTestInput.value && testInput.value.trim()) {
      payload[drawerTestInput.value.key] = testInput.value.trim()
    }
    testResult.value = await testCapability(drawerSlug.value, payload)
  } catch {
    // 拦截器已提示
  } finally {
    capTesting.value = false
  }
}

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

onMounted(async () => {
  await Promise.all([load(), loadCapabilities()])
})

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
        <p class="admin-page-subtitle">外部服务能力与运营参数；修改后立即对用户端生效</p>
      </div>
      <el-button @click="loadCapabilities(); load()">
        <RefreshCw :size="14" style="margin-right: 4px" />重新载入
      </el-button>
    </div>

    <!-- ==================== 外部服务能力 ==================== -->
    <NoticePanel
      title="外部服务能力说明"
      summary="凭据由管理员自行填写，填入后即可测试连接"
      :icon="Zap"
      storage-key="settings-capabilities"
    >
      <p class="capability-note">
        能力由面板提供，<strong>凭据全部由你自己填</strong>：各家的 API Key / 站点密钥 / 代理地址 / Bot Token
        都由本项目之外的账号体系签发，填进来即可用，每个能力都能当场「测试连接」。
      </p>
    </NoticePanel>

    <div v-loading="capsLoading" class="settings-body">
      <section v-for="g in capGroups" :key="g.name" class="cap-section">
        <h2 class="cap-group-title">{{ g.name }}</h2>
        <div class="cap-grid">
          <button
            v-for="card in g.items"
            :key="card.slug"
            type="button"
            class="cap-card"
            :class="capStatus(card).tone"
            @click="openCapability(card.slug)"
          >
            <div class="cap-card-top">
              <span class="cap-icon">
                <component :is="CAP_ICONS[card.slug] || Globe" :size="18" />
              </span>
              <span class="cap-badge" :class="capStatus(card).tone">{{ capStatus(card).label }}</span>
            </div>
            <h3>{{ card.title }}</h3>
            <p>{{ card.desc }}</p>
            <span class="cap-more">配置与测试 →</span>
          </button>
        </div>
      </section>
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

        <el-form label-position="top" class="field-form">
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

        <el-form label-position="top" class="field-form">
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

    <!-- ==================== 能力配置抽屉 ==================== -->
    <el-drawer v-model="drawerOpen" :title="drawerTitle" size="520px">
      <div class="cap-drawer">
        <p class="cap-drawer-desc">{{ drawerDesc }}</p>
        <p v-if="drawerHint" class="field-hint">{{ drawerHint }}</p>

        <el-form label-position="top" class="field-form">
          <el-form-item v-for="f in drawerFields" :key="f.key" :label="f.label">
            <el-switch
              v-if="f.type === 'bool'"
              v-model="drawerValues[f.key]"
              active-value="true"
              inactive-value="false"
            />
            <el-select v-else-if="f.type === 'select'" v-model="drawerValues[f.key]">
              <el-option v-for="opt in f.options" :key="opt" :label="opt" :value="opt" />
            </el-select>
            <el-input
              v-else-if="f.type === 'int'"
              v-model="drawerValues[f.key]"
              type="number"
              class="num-input"
            />
            <el-input
              v-else
              v-model="drawerValues[f.key]"
              :type="f.type === 'secret' ? 'password' : 'text'"
              :show-password="f.type === 'secret'"
              :placeholder="f.type === 'secret' && drawerValues[f.key] === '******'
                ? '已配置：保持 ****** 不修改，清空则删除' : (f.placeholder || '')"
            />
            <span v-if="f.hint" class="field-hint">{{ f.hint }}</span>
          </el-form-item>

          <el-form-item v-if="drawerTestInput" :label="drawerTestInput.label">
            <el-input v-model="testInput.value" :placeholder="drawerTestInput.placeholder" />
          </el-form-item>
        </el-form>

        <el-alert
          v-if="testResult"
          :type="testResult.ok ? 'success' : 'error'"
          :title="testResult.ok ? '测试通过' : '测试未通过'"
          :description="testResult.message"
          :closable="false"
          show-icon
        />

        <div class="cap-drawer-footer">
          <el-button v-if="drawerTestable" :loading="capTesting" @click="runCapabilityTest">
            {{ drawerTestLabel }}
          </el-button>
          <el-button type="primary" :loading="capSaving" @click="saveCurrentCapability">
            <Save :size="14" style="margin-right: 4px" />{{ drawerDirty ? '保存修改' : '保存' }}
          </el-button>
        </div>
        <p class="foot-note">
          <ShieldCheck :size="13" />密钥字段只以掩码回显（保持 ****** 不修改，清空则删除）<template v-if="drawerTestable">；测试会真实发起一次请求或投递，便于区分「密钥错」与「网络不通」</template>。
        </p>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.settings-body { display: flex; flex-direction: column; gap: 14px; }

.card-title { display: flex; align-items: flex-start; gap: 10px; }
.card-title h2 { font-size: 15px; margin: 0; }
.card-title p { font-size: 12px; color: var(--text-muted); margin: 2px 0 0; }

.field-form { max-width: 640px; }
.field-suffix { margin-left: 8px; font-size: var(--font-size-xs); color: var(--text-tertiary); }
.field-hint { font-size: var(--font-size-xs); color: var(--text-muted); line-height: 1.6; }
.num-input { width: 160px; }

/* 控件与标签之间留出呼吸位：label 在上时不再挤在一行里 */
.field-form :deep(.el-form-item) { margin-bottom: 20px; }
.field-form :deep(.el-form-item__content) { flex-wrap: wrap; gap: 6px 0; }

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
  gap: 9px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  line-height: 1.6;
  border: 1px solid var(--warning-border);
  background: var(--warning-bg);
  color: #fde68a;
}

.notice :deep(svg) { flex-shrink: 0; }

.notice.ok {
  border-color: var(--success-border);
  background: var(--success-bg);
  color: #a7f3d0;
}

.notice strong,
.capability-note strong { color: var(--text-primary); font-weight: var(--font-weight-semibold); }

.capability-note { margin: 0; line-height: 1.7; }

.foot-note {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  padding: 4px 2px 10px;
}

/* ==================== 能力卡片 ==================== */

.cap-section { display: flex; flex-direction: column; gap: 10px; }

.cap-group-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-tertiary);
  letter-spacing: var(--tracking-wide);
  margin: 6px 0 0;
}

.cap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.cap-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-align: left;
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition: border-color var(--transition-fast), transform var(--transition-fast),
    box-shadow var(--transition-fast);
}

.cap-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.cap-card.ok { border-color: var(--success-border); }
.cap-card.warn { border-color: var(--warning-border); }

.cap-card-top { display: flex; align-items: center; justify-content: space-between; }

.cap-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--primary-bg);
  color: var(--primary);
}

.cap-badge {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  color: var(--text-muted);
  background: var(--bg-inset);
}

.cap-badge.ok { color: var(--success); background: var(--success-bg); }
.cap-badge.warn { color: var(--warning); background: var(--warning-bg); }

.cap-card h3 { font-size: var(--font-size-md); margin: 2px 0 0; color: var(--text-primary); }
.cap-card p { font-size: var(--font-size-xs); color: var(--text-muted); line-height: 1.6; margin: 0; }
.cap-more { font-size: var(--font-size-xs); color: var(--primary); margin-top: 4px; }

.cap-drawer { display: flex; flex-direction: column; gap: 10px; }
.cap-drawer-desc { font-size: var(--font-size-sm); color: var(--text-secondary); margin: 0; line-height: 1.6; }
.cap-drawer :deep(.el-select) { width: 100%; }

.cap-drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

/* 手机：数字输入铺满、保存按钮拉满整行、提示图标不压缩 */
@media (max-width: 640px) {
  .num-input { width: 100%; }
  .card-footer { justify-content: stretch; }
  .card-footer :deep(.el-button) { flex: 1; margin-left: 0; }
  .settings-body { gap: 12px; }
  .cap-grid { grid-template-columns: 1fr; }
  .cap-drawer-footer { justify-content: stretch; }
  .cap-drawer-footer :deep(.el-button) { flex: 1; margin-left: 0; }
}
</style>
