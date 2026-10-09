<script setup lang="ts">
/**
 * 系统设置
 *
 * v2.4.0 注册策略（开放 / 注册码 / 关闭 + 关闭提示文案）与经济配置分组
 * v2.5.2 付费墙分组（要求有效订阅 + 拦截提示文案）
 * v2.6.0 下载与设备风控分组（下载开关 / 设备上限 / 自动踢人 / 日志保留）
 * v2.19.0 **外部服务能力中心**：代理 / 人机验证 / 邮件与模板 / Telegram / AI 模型 / IP 归属地
 *
 * v2.42.10（Phase 5·危险操作独立 tab）：页面改成三个页签——「能力与服务」「运营参数」
 * 「**危险操作**」。前两个装的都是日常要改的东西，第三个装的是**会立刻改变线上数据、
 * 且大多不能撤销**的操作（手动恢复配额熔断器 / 清空本地缓存 / 清理登录与安全日志）。
 * 把它们从仪表盘、客户端策略、登录日志三个页面里搬到这里，是为了让「不可撤销」这件事
 * 在**一个地方**说清楚：先备份、再确认、再执行。原来三处的按钮改成深链指过来
 * （如 `/settings?tab=danger&op=cache`），**执行逻辑只在这里一份**。
 *
 * 能力中心的口径：**项目只提供能力，凭据一律由管理员自己填**。字段表由后端下发，
 * 这里只按类型渲染控件，所以后端加字段不需要改这个页面，也不会出现「界面漏了字段」。
 * 密钥字段后端只回 ******，留空即保持原值不变。
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  CalendarCheck, Coins, Globe, KeyRound, Mail, MapPin, Network, Palette, RefreshCw, Save,
  ShieldCheck, Send, Sparkles, TicketCheck, UserPlus, Wallet, ShieldAlert, Lock, Zap,
  DatabaseBackup, HardDrive, History, TriangleAlert, Eraser, SlidersHorizontal, PlugZap,
} from 'lucide-vue-next'
import { EmptyState, PageHeader, SectionCard } from '@/components/ui'
import { useBreakpoint } from '@/composables/useBreakpoint'
import {
  fetchRegistrationSettings, updateRegistrationSettings,
} from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
import { useQueryFilter } from '@/composables/useQueryFilter'
import { useDangerOps, fmtBytes } from '@/composables/useDangerOps'
import { fetchEconomySettings, updateEconomySettings, type EconomySettings } from '@/api/economy'
import {
  fetchCapabilities, fetchCapability, saveCapability, testCapability,
  type CapabilityCard, type CapabilityField, type CapabilityTestResult,
} from '@/api/capabilities'
import NoticePanel from '@/components/NoticePanel.vue'

const route = useRoute()
const auth = useAuthStore()
/** 手机上能力配置抽屉铺满整屏 */
const { isPhone } = useBreakpoint()
const capDrawerSize = computed(() => (isPhone.value ? '100%' : '520px'))

/** ==================== 页签（Phase 5） ==================== */

const TAB_KEYS = ['capabilities', 'params', 'danger']
const tab = ref<string>('capabilities')
// 深链：/settings?tab=danger（仪表盘 / 命令面板 / 其它页面的「去危险操作」都指这里）
useQueryFilter(tab, 'tab')
watch(
  tab,
  (value) => {
    // 非法值回默认页签：宁可回到第一页，也不要停在一个不存在的页签上（空白页）
    if (!TAB_KEYS.includes(value)) tab.value = 'capabilities'
  },
  { immediate: true },
)

type FieldType = 'bool' | 'int' | 'str' | 'secret'

interface Field {
  key: string
  label: string
  type: FieldType
  hint?: string
  suffix?: string
  /** 有值时渲染成下拉（type 仍是 str，保存走同一串行化分支） */
  choices?: Array<{ value: string; label: string }>
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
    desc: '签到基础积分与连签加成规则（积分仅限公益服用户）',
    icon: CalendarCheck,
    fields: [
      { key: 'checkin_enabled', label: '启用签到', type: 'bool' },
      { key: 'checkin_base_points', label: '基础积分', type: 'int', suffix: '积分/次', hint: '未设置随机范围时的默认值' },
      { key: 'checkin_base_min', label: '基础积分下限', type: 'int', suffix: '积分/次', hint: '随机范围下限，默认跟随基础积分' },
      { key: 'checkin_base_max', label: '基础积分上限', type: 'int', suffix: '积分/次', hint: '随机范围上限，与下限相同=固定值' },
      { key: 'checkin_streak_bonus', label: '连签加成', type: 'int', suffix: '积分/天', hint: '每多连签一天额外增加的积分' },
      { key: 'checkin_streak_max_bonus', label: '加成上限', type: 'int', suffix: '积分', hint: '连签加成的封顶值' },
      { key: 'checkin_penalty_pct', label: '惩罚概率', type: 'int', suffix: '%', hint: '0=关闭惩罚' },
      { key: 'checkin_penalty_min', label: '惩罚下限', type: 'int', suffix: '积分' },
      { key: 'checkin_penalty_max', label: '惩罚上限', type: 'int', suffix: '积分' },
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
      {
        key: 'promotion_reward_enabled',
        label: '推广奖励',
        type: 'bool',
        hint: '邀请成功后在双向积分之外「另发」一笔；默认关闭，不打开就不会发',
      },
      {
        key: 'promotion_reward_type',
        label: '推广奖励类型',
        type: 'str',
        choices: [
          { value: 'balance', label: '余额（积分）' },
          { value: 'days', label: '有效期（天）' },
        ],
        hint: '选「有效期」时给邀请人叠加会员天数，归属当前服',
      },
      { key: 'promotion_reward_amount', label: '推广奖励·余额数值', type: 'int', suffix: '积分', hint: '类型为「余额」时生效；0 = 不发' },
      { key: 'promotion_reward_days', label: '推广奖励·有效期天数', type: 'int', suffix: '天', hint: '类型为「有效期」时生效；0 = 不发' },
    ],
  },
  {
    id: 'stream_accel',
    title: '流媒体加速',
    desc: '一键开启：强制域名访问（防 IP 直连） + 自动信任 CF 真实 IP + 播放地址统一用加速域名',
    icon: Zap,
    fields: [
      { key: 'stream_accel_enabled', label: '启用加速', type: 'bool' },
      {
        key: 'stream_accel_domain',
        label: '加速域名',
        type: 'str',
        hint: '例如 cdn.example.com，不带 https://；保存后最长 60 秒生效；开启后只能用该域名访问',
      },
    ],
  },
]

const loading = ref(true)
/** 运营参数读取失败：显示错误态，避免管理员对着空表单点保存 */
const paramsError = ref(false)
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
const capsError = ref(false)
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
  capsError.value = false
  try {
    const res = await fetchCapabilities()
    capabilities.value = res.capabilities
  } catch {
    // 拦截器已提示
    capsError.value = !capabilities.value.length
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
  paramsError.value = false
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
    paramsError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(), loadCapabilities()])
})

/** 运营参数页签顶部的分组跳转：分组多（8 块），先看目录再定位，不用一路滚 */
function scrollToGroup(id: string) {
  document.getElementById(`group-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 「重新载入」：当前页签用得上的都重拉一遍 */
function reloadAll() {
  loadCapabilities()
  load()
  if (tab.value === 'danger') loadDanger()
}

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

// ==================== 危险操作（Phase 5） ====================

/** 只读审计角色：服务端会拒，这里先置灰并说清原因（口径同导航上的锁标记） */
const canWrite = computed(() => auth.admin?.can_write !== false)
const WRITE_HINT = '当前账号是只读审计角色：可以看，不能执行写操作'

/** 逻辑与确认文案都在 useDangerOps 里（仪表盘 / 客户端策略 / 登录日志共用同一份） */
const dangerOps = useDangerOps()
const {
  backup: backupInfo,
  busy: dangerBusy,
  cacheStats,
  loadState: loadDanger,
  loading: dangerLoading,
} = dangerOps
const {
  backupNow: doBackup,
  cleanCache: doCleanCache,
  purgeLogs: doPurgeLogs,
} = dangerOps

/** 保留天数：0 = 清空全部登录与安全日志 */
const purgeDays = ref(90)
/** 从别的页面深链过来时高亮对应卡片（?op=cache|logs） */
const TAB_OPS = ['cache', 'logs']
const target = ref('')

// 切到危险操作页签时才拉数据：这三个接口在另外两个页签里用不上
watch(tab, (value) => {
  if (value === 'danger' && !cacheStats.value) loadDanger()
})

/** 深链定位：?op=xxx → 高亮对应卡片并滚过去（其它页面「去危险操作」的落点） */
function scrollToTarget(key: string) {
  document.getElementById(`danger-${key}`)?.scrollIntoView({ block: 'center' })
}

watch(
  () => route.query.op,
  (op) => {
    const key = Array.isArray(op) ? (op[0] ?? '') : (op ?? '')
    target.value = TAB_OPS.includes(key) ? key : ''
    if (!target.value) return
    nextTick(() => scrollToTarget(target.value))
    // el-tabs 的页签内容是懒渲染的：首次切过去时 DOM 可能还没挂上，滚不到就再试一次
    window.setTimeout(() => scrollToTarget(target.value), 150)
    // 高亮只用来「指给你看这是哪一张」，停几秒就淡掉（否则一直亮着反而像出错了）
    window.setTimeout(() => { target.value = '' }, 4000)
  },
  { immediate: true },
)
</script>

<template>
  <div class="admin-page settings-page">
    <PageHeader
      eyebrow="系统与审计"
      title="系统设置"
      description="外部服务能力、运营参数与危险操作；修改后立即对用户端生效。"
    >
      <template #actions>
        <el-button @click="reloadAll">
          <RefreshCw :size="14" class="btn-ico" />重新载入
        </el-button>
      </template>
    </PageHeader>

    <!-- Phase 5：日常要改的放前两个页签，不可撤销的独立一页 -->
    <el-tabs v-model="tab" class="settings-tabs">
      <el-tab-pane name="capabilities">
        <template #label>
          <span class="tab-label"><Globe :size="13" />能力与服务</span>
        </template>

        <div class="settings-body">
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

          <div v-if="capsLoading && !capabilities.length" class="cap-skeleton" aria-busy="true" aria-label="加载中">
            <div v-for="n in 6" :key="n" class="au-skeleton sk-cap" />
          </div>

          <EmptyState
            v-else-if="capsError"
            :icon="PlugZap"
            title="能力列表读取失败"
            description="可能是网络或后端暂时不可用。"
          >
            <template #actions><el-button size="small" @click="loadCapabilities">重试</el-button></template>
          </EmptyState>

          <EmptyState
            v-else-if="!capabilities.length"
            :icon="PlugZap"
            title="暂无可配置的外部能力"
            description="后端没有下发任何能力项。"
          />

          <div v-else class="cap-flow" :class="{ 'is-refreshing': capsLoading }">
            <section v-for="g in capGroups" :key="g.name" class="cap-section">
              <h2 class="au-eyebrow cap-group-title">{{ g.name }}</h2>
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
                    <span
                      class="au-badge"
                      :class="capStatus(card).tone === 'ok' ? 'au-badge-green' : capStatus(card).tone === 'warn' ? 'au-badge-amber' : 'au-badge-muted'"
                    >{{ capStatus(card).label }}</span>
                  </div>
                  <h3 class="cap-title">{{ card.title }}</h3>
                  <p>{{ card.desc }}</p>
                  <span class="cap-more">配置与测试 →</span>
                </button>
              </div>
            </section>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane name="params">
        <template #label>
          <span class="tab-label"><SlidersHorizontal :size="13" />运营参数</span>
        </template>

        <div v-if="loading && !Object.keys(original).length" class="params-skeleton" aria-busy="true" aria-label="加载中">
          <div class="au-skeleton sk-nav" />
          <div v-for="n in 3" :key="n" class="au-skeleton sk-card" />
        </div>

        <div v-else class="settings-body" :class="{ 'is-refreshing': loading }">
          <el-alert
            v-if="paramsError"
            type="error"
            show-icon
            :closable="false"
            title="运营参数读取失败"
            description="下面的表单可能不是当前生效值，请先点右上角「重新载入」再修改。"
          />

          <!-- 分组目录：8 块配置一眼看全，带未保存标记，点击跳转 -->
          <nav class="group-nav" aria-label="运营参数分组">
            <button type="button" class="group-chip" @click="scrollToGroup('registration')">
              <KeyRound :size="13" />注册策略
            </button>
            <button
              v-for="g in GROUPS"
              :key="g.id"
              type="button"
              class="group-chip"
              :class="{ 'is-dirty': isDirty(g) }"
              @click="scrollToGroup(g.id)"
            >
              <component :is="g.icon" :size="13" />{{ g.title }}
              <span v-if="isDirty(g)" class="chip-dot" aria-label="有未保存的改动" />
            </button>
          </nav>

          <!-- 注册策略 -->
          <SectionCard
            id="group-registration"
            title="注册策略"
            :icon="KeyRound"
            description="决定新用户如何进入站点"
            class="group-card"
          >
            <el-form label-position="top" class="field-form">
              <el-form-item label="注册模式">
                <div class="field-stack">
                  <el-radio-group v-model="reg.mode">
                    <el-radio-button value="open">开放注册</el-radio-button>
                    <el-radio-button value="code">注册码</el-radio-button>
                    <el-radio-button value="closed">关闭注册</el-radio-button>
                  </el-radio-group>
                  <span class="field-hint">{{ regModeHint }}</span>
                </div>
              </el-form-item>
              <el-form-item v-if="reg.mode === 'closed'" label="关闭提示">
                <el-input v-model="reg.message" type="textarea" :rows="2" placeholder="展示给无法注册的用户…" />
              </el-form-item>
            </el-form>

            <template #footer>
              <div class="card-footer">
                <el-button type="primary" :loading="regSaving" @click="saveRegistration">
                  <Save :size="14" class="btn-ico" />保存注册策略
                </el-button>
              </div>
            </template>
          </SectionCard>

          <!-- 支付状态提示 -->
          <el-alert
            :type="paymentReady ? 'success' : 'warning'"
            show-icon
            :closable="false"
            :title="paymentReady
              ? '支付网关已配置完成，用户端可直接下单充值。'
              : '支付网关尚未配置齐全（需要网关地址 + 商户 ID + 商户密钥），用户端充值下单会提示未启用。'"
          />

          <!-- 经济配置分组 -->
          <SectionCard
            v-for="g in GROUPS"
            :id="`group-${g.id}`"
            :key="g.id"
            :title="g.title"
            :icon="g.icon"
            :description="g.desc"
            :tone="isDirty(g) ? 'accent' : 'default'"
            class="group-card"
          >
            <template v-if="isDirty(g)" #actions>
              <span class="au-badge au-badge-amber">未保存</span>
            </template>

            <el-form label-position="top" class="field-form field-grid">
              <el-form-item
                v-for="f in g.fields"
                :key="f.key"
                :label="f.label"
                :class="{ 'is-wide': f.type === 'str' || f.type === 'secret' }"
              >
                <div class="field-stack">
                  <div class="field-control">
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
                    <el-select
                      v-else-if="f.choices"
                      v-model="settings[f.key]"
                      class="w-full"
                    >
                      <el-option
                        v-for="c in f.choices"
                        :key="c.value"
                        :label="c.label"
                        :value="c.value"
                      />
                    </el-select>
                    <el-input
                      v-else
                      v-model="settings[f.key]"
                      :type="f.type === 'secret' ? 'password' : 'text'"
                      :show-password="f.type === 'secret'"
                      :placeholder="f.type === 'secret' ? '留空表示不修改' : ''"
                    />
                    <span v-if="f.suffix" class="field-suffix">{{ f.suffix }}</span>
                  </div>
                  <span v-if="f.hint" class="field-hint">{{ f.hint }}</span>
                </div>
              </el-form-item>
            </el-form>

            <template #footer>
              <div class="card-footer">
                <el-button
                  type="primary"
                  :disabled="!isDirty(g)"
                  :loading="savingGroup === g.id"
                  @click="saveGroup(g)"
                >
                  <Save :size="14" class="btn-ico" />保存{{ g.title }}
                </el-button>
              </div>
            </template>
          </SectionCard>

          <p class="foot-note">
            <Coins :size="13" />
            积分、套餐与兑换码的明细请前往「商品与套餐」「兑换码」「邀请与积分」页面管理。
          </p>
        </div>
      </el-tab-pane>

      <!-- ==================== 危险操作（Phase 5） ==================== -->
      <el-tab-pane name="danger">
        <template #label>
          <span class="tab-label"><TriangleAlert :size="13" />危险操作</span>
        </template>

        <div v-loading="dangerLoading" class="settings-body">
          <!-- 先备份：不可撤销的操作之前，总得有个能回退的地方 -->
          <SectionCard title="动手之前，先备份一次" :icon="DatabaseBackup" class="danger-guard">
            <template #actions>
              <el-button
                type="primary"
                :loading="dangerBusy === 'backup'"
                :disabled="!canWrite"
                :title="canWrite ? '' : WRITE_HINT"
                @click="doBackup"
              >
                <DatabaseBackup :size="14" class="btn-ico" />立即备份
              </el-button>
            </template>
            <p class="danger-effect">
              下面的操作都会立刻改变线上数据，大多不可恢复。
              定时备份是每天一次，不等于「刚才那一刻的状态」。
            </p>
            <p class="danger-guard-meta">
              定时备份 {{ backupInfo?.enabled ? `已开启 · 每天 ${backupInfo.time} · 保留 ${backupInfo.keep_days} 天` : '未开启' }}
              · 上次执行 {{ backupInfo?.last_run || '—' }}
              · 已有 {{ backupInfo?.backups.length ?? 0 }} 份备份
            </p>
          </SectionCard>

          <el-alert
            v-if="!canWrite"
            type="warning"
            show-icon
            :closable="false"
            :title="`${WRITE_HINT}。下面的按钮已置灰，但内容仍然可读。`"
          />

          <!-- 1. 本地播放缓存 -->
          <SectionCard
            id="danger-cache"
            title="清空本地播放缓存"
            :icon="HardDrive"
            description="清的是 VPS 本机副本（热门片提前拉到本机的那份），不是媒体库里的文件"
            class="danger-card"
            :class="{ 'is-target': target === 'cache' }"
          >
            <template #actions>
              <span class="au-badge au-badge-amber">清掉不可恢复</span>
            </template>
            <p class="danger-effect">
              当前占用 <strong>{{ fmtBytes(cacheStats?.bytes_used || 0) }}</strong>
              （上限 {{ fmtBytes(cacheStats?.max_bytes || 0) }}）
              <template v-if="cacheStats?.hit_rate != null">
                · 命中率 {{ Math.round(cacheStats.hit_rate * 100) }}%
              </template>
              。清完之后这些片子要重新回源拉一次，热门时段会变慢。
            </p>
            <template #footer>
              <div class="card-footer">
                <el-button
                  :disabled="!canWrite"
                  :loading="dangerBusy === 'cache:ready'"
                  :title="canWrite ? '' : WRITE_HINT"
                  @click="doCleanCache('ready')"
                >
                  <Eraser :size="14" class="btn-ico" />清理已缓存副本
                </el-button>
                <el-button
                  :disabled="!canWrite"
                  :loading="dangerBusy === 'cache:failed'"
                  :title="canWrite ? '' : WRITE_HINT"
                  @click="doCleanCache('failed')"
                >
                  清理失败记录
                </el-button>
                <el-button
                  type="danger"
                  plain
                  :disabled="!canWrite"
                  :loading="dangerBusy === 'cache:all'"
                  :title="canWrite ? '' : WRITE_HINT"
                  @click="doCleanCache('all')"
                >
                  清空全部
                </el-button>
              </div>
            </template>
          </SectionCard>

          <!-- 2. 登录与安全日志 -->
          <SectionCard
            id="danger-logs"
            title="清理登录与安全日志"
            :icon="History"
            description="登录成功/失败、设备超限被拒、诱饵码触发封禁等风控事件的流水"
            class="danger-card"
            :class="{ 'is-target': target === 'logs' }"
          >
            <template #actions>
              <span class="au-badge au-badge-rose">删掉就查不到了</span>
            </template>
            <p class="danger-effect">
              保留 <strong>0</strong> 天 = 清空全部。删掉之后，风控与安全审计就查不到那段历史了。
              想让它自然收敛，应该去「系统设置 → 运营参数 → 下载与设备风控」改日志保留天数。
            </p>
            <template #footer>
              <div class="card-footer">
                <label class="field-suffix" for="purge-days">保留天数</label>
                <el-input-number
                  id="purge-days"
                  v-model="purgeDays"
                  :min="0"
                  :max="3650"
                  :controls="false"
                  class="purge-input"
                />
                <el-button
                  type="danger"
                  :disabled="!canWrite"
                  :loading="dangerBusy === 'logs'"
                  :title="canWrite ? '' : WRITE_HINT"
                  @click="doPurgeLogs(purgeDays)"
                >
                  清理日志
                </el-button>
              </div>
            </template>
          </SectionCard>

          <p class="foot-note">
            <TriangleAlert :size="13" />
            删除媒体库、删除服务器、删除挂载这类<strong>针对单个对象</strong>的操作仍然留在它们各自的页面上——
            那里才看得到要删的是什么；本页只收「跨对象、不可逆」的那几项。
          </p>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ==================== 能力配置抽屉 ==================== -->
    <el-drawer v-model="drawerOpen" :title="drawerTitle" :size="capDrawerSize">
      <div class="cap-drawer">
        <p class="cap-drawer-desc">{{ drawerDesc }}</p>
        <p v-if="drawerHint" class="field-hint cap-drawer-hint">{{ drawerHint }}</p>

        <el-form label-position="top" class="field-form">
          <el-form-item v-for="f in drawerFields" :key="f.key" :label="f.label">
            <div class="field-stack">
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
            </div>
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
            <Save :size="14" class="btn-ico" />{{ drawerDirty ? '保存修改' : '保存' }}
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
.settings-page { gap: 16px; }
.btn-ico { margin-right: 4px; }
.w-full { width: 100%; }
.settings-body { display: flex; flex-direction: column; gap: 16px; }
.is-refreshing { opacity: 0.6; transition: opacity var(--au-fast) var(--au-ease); }

/* ==================== 页签 ==================== */
.tab-label { display: inline-flex; align-items: center; gap: 4px; }

/* ==================== 骨架 ==================== */
.cap-skeleton {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.sk-cap { height: 132px; border-radius: var(--au-r-lg); }
.params-skeleton { display: flex; flex-direction: column; gap: 16px; }
.sk-nav { height: 40px; border-radius: var(--au-r-md); }
.sk-card { height: 220px; border-radius: var(--au-r-lg); }

/* ==================== 运营参数：分组目录 ==================== */
.group-nav {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.group-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  background: var(--au-surface);
  color: var(--au-text-2);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color var(--au-fast) var(--au-ease), color var(--au-fast) var(--au-ease);
}
.group-chip:hover { border-color: var(--au-border-strong); color: var(--au-text); }
.group-chip:focus-visible { outline: 2px solid var(--au-border-focus); outline-offset: 2px; }
.group-chip svg { color: var(--au-primary); }
.group-chip.is-dirty { border-color: var(--au-primary-border); color: var(--au-text); }
.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--au-r-full);
  background: var(--au-primary);
}
/* 跳转落点别被顶栏压住 */
.group-card { scroll-margin-top: 80px; }

/* ==================== 表单 ==================== */
.field-form :deep(.el-form-item) { margin-bottom: 18px; }
.field-form :deep(.el-form-item:last-child) { margin-bottom: 0; }
.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0 24px;
}
.field-grid :deep(.el-form-item.is-wide) { grid-column: 1 / -1; max-width: 640px; }
.field-grid :deep(.el-form-item:last-child) { margin-bottom: 18px; }
.field-stack { display: flex; flex-direction: column; gap: 6px; width: 100%; min-width: 0; }
.field-control { display: flex; align-items: center; gap: 8px; min-width: 0; }
.field-suffix { font-size: 12px; color: var(--au-text-3); white-space: nowrap; }
.field-hint { font-size: 12px; color: var(--au-text-3); line-height: 1.6; }
.num-input { width: 160px; }

.card-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.capability-note { margin: 0; line-height: 1.7; }
.capability-note strong { color: var(--au-text); font-weight: 600; }

.foot-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 12px;
  color: var(--au-text-3);
  padding: 0 2px 8px;
}
.foot-note strong { color: var(--au-text-2); }

/* ==================== 危险操作 ==================== */
/* 危险操作卡：左边一条警示色，与前两个页签的日常配置卡区分开 */
.danger-card { border-left: 3px solid var(--au-danger-border); scroll-margin-top: 80px; }
.danger-card.is-target {
  border-color: var(--au-danger);
  outline: 3px solid var(--au-danger-soft);
}
.danger-guard { border-color: var(--au-success-border); }
.danger-guard-meta { margin: 6px 0 0; font-size: 12px; color: var(--au-text-3); line-height: 1.6; }
.danger-effect {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--au-text-2);
}
.danger-effect strong { color: var(--au-text); font-weight: 600; }
.purge-input { width: 120px; }

/* ==================== 能力卡片 ==================== */
.cap-section { display: flex; flex-direction: column; gap: 10px; }
.cap-group-title { margin: 4px 0 2px; }

.cap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

/*
  能力卡按列打包（v2.42.5）：单卡分组与相邻分组并排；分组本身不被拆开（break-inside: avoid），
  阅读顺序仍是分组的自然顺序。
*/
.cap-flow {
  display: block;
  column-width: 300px;
  column-gap: 12px;
}
.cap-flow .cap-section {
  display: block;
  break-inside: avoid;
  margin-bottom: 16px;
}
.cap-flow .cap-grid { display: block; }
.cap-flow .cap-card { margin-bottom: 12px; break-inside: avoid; }

.cap-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  text-align: left;
  padding: 16px;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition: border-color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}
.cap-card:hover { border-color: var(--au-border-strong); background: var(--au-surface-2); }
.cap-card:active { transform: scale(0.98); }
.cap-card:focus-visible { outline: 2px solid var(--au-border-focus); outline-offset: 2px; }
.cap-card.ok { border-color: var(--au-success-border); }
.cap-card.warn { border-color: var(--au-warning-border); }

.cap-card-top { display: flex; align-items: center; justify-content: space-between; }

.cap-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--au-r-md);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.cap-title { font-size: 15px; margin: 2px 0 0; color: var(--au-text); }
.cap-card p { font-size: 12px; color: var(--au-text-3); line-height: 1.6; margin: 0; }
.cap-more { font-size: 12px; color: var(--au-primary); margin-top: 4px; }

.cap-drawer { display: flex; flex-direction: column; gap: 12px; }
.cap-drawer-desc { font-size: 13px; color: var(--au-text-2); margin: 0; line-height: 1.6; }
.cap-drawer-hint { margin: 0; }
.cap-drawer :deep(.el-select) { width: 100%; }

.cap-drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--au-border);
}

/* 手机：数字输入铺满、保存按钮拉满整行 */
@media (max-width: 768px) {
  .num-input { width: 100%; }
  .field-grid { grid-template-columns: 1fr; }
  .card-footer { justify-content: stretch; }
  .card-footer :deep(.el-button) { flex: 1 1 auto; margin-left: 0; }
  .purge-input { flex: 1 1 100px; }
  .settings-body { gap: 12px; }
  .group-nav { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; scrollbar-width: none; }
  .group-chip { flex: none; }
  .cap-grid { grid-template-columns: 1fr; }
  .cap-flow { column-width: auto; column-count: 1; }
  .cap-flow .cap-section { margin-bottom: 12px; }
  .cap-flow .cap-card { margin-bottom: 10px; }
  .cap-drawer-footer { justify-content: stretch; }
  .cap-drawer-footer :deep(.el-button) { flex: 1; margin-left: 0; }
  .danger-guard :deep(.au-section__head) { flex-wrap: wrap; }
}
</style>
