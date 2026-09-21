<script setup lang="ts">
/**
 * 钱包 — 余额总览 / 积分充值（支付下单）/ 卡码·兑换码核销 / 订单记录 / 积分流水
 * 布局：余额卡左右分区（左余额+签到态，右统一核销面板）；套餐卡横向结构化行
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  Wallet, Coins, TicketCheck, Receipt, RefreshCw, Sparkles, Zap, Flame, Crown,
  ExternalLink, ArrowUpRight, ArrowDownLeft, CircleCheck, Clock, CircleAlert, ChevronRight,
  KeyRound, Film,
} from 'lucide-vue-next'
import {
  pointsApi, checkinApi, exchangeApi, paymentApi, membershipApi,
  type PointsLogEntry, type RechargePackage, type SubscriptionPlan,
  type OrderRow, type PaymentMethod, type CheckinStatus, type CodePreview,
} from '@/api/economy'
import { subscriptionApi, type MySubscription } from '@/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const route = useRoute()
const userStore = useUserStore()

// ===== 状态 =====
const loading = ref(true)
const balance = ref(0)
const checkin = ref<CheckinStatus | null>(null)
const packages = ref<RechargePackage[]>([])
const plans = ref<SubscriptionPlan[]>([])
const methods = ref<PaymentMethod[]>([])
const orders = ref<OrderRow[]>([])
const logs = ref<PointsLogEntry[]>([])

const tab = ref<'recharge' | 'plans' | 'orders' | 'log'>('recharge')
const payMethod = ref('alipay')
const orderLoading = ref<number | null>(null)

// ===== 功能开关（管理端可关；关闭时给出提示，不让用户白提交）=====
const rechargeEnabled = ref(true)
const plansEnabled = ref(true)
const exchangeEnabled = ref(true)

// ===== 公益服（v2.7.0）：这个服免费开放，不需要买会员 =====
// 后端 /payment/plans 会下发当前服的接入方式；公益服一律不展示套餐与购买引导，
// 否则用户会以为“不买就看不了”，而实际上他本来就能看。
const isFreeRealm = ref(false)
const realmNote = ref('')

// ===== 当前会员（订阅 tab 顶部状态行）=====
const subscriptions = ref<MySubscription[]>([])
const currentSub = computed(
  () => subscriptions.value.find((s) => s.status === 'active' && s.days_left > 0) || null,
)

// ===== 统一核销入口（卡码 / 兑换码 / 邀请码自动识别）=====
// 卡码（会员时长）与兑换码（积分/订阅）原本是两个输入框，用户得自己判断该填哪个。
// 现在只留一个入口：先向后端预检识别来源，再走对应链路（邀请码给出指引）。
const redeemCode = ref('')
const redeemLoading = ref(false)
const codePreview = ref<CodePreview | null>(null)
const codeNotice = ref('')
const redeemInputRef = ref<HTMLInputElement | null>(null)

/** 重新输入时清掉上一轮预检结果，避免残留提示误导 */
function resetCodeFeedback() {
  codePreview.value = null
  codeNotice.value = ''
}

/** 订阅页的一行指引：把焦点交回顶部唯一的核销面板 */
function focusRedeem() {
  redeemInputRef.value?.focus()
  redeemInputRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function handleRedeem() {
  const code = redeemCode.value.trim()
  if (!code) {
    toast.error('请输入卡码或兑换码')
    return
  }
  redeemLoading.value = true
  codePreview.value = null
  codeNotice.value = ''
  try {
    const preview = await membershipApi.preview(code)

    if (preview.kind === 'exchange') {
      // 兑换码：无预检态，直接核销（积分或订阅时长）
      if (!exchangeEnabled.value) {
        codeNotice.value = '管理员已关闭兑换，如有兑换码请稍后再试'
        return
      }
      const res = await exchangeApi.redeem(code)
      toast.success(res.message || '兑换成功')
      redeemCode.value = ''
      await Promise.all([refreshBalance(), refreshSubscriptions()])
      return
    }

    if (preview.kind === 'code' && preview.valid) {
      // 会员卡码：先展示类型与天数，确认后再核销
      codePreview.value = preview
      return
    }

    // 邀请码 / 无效码 / 未识别：直接把后端给出的指引显示在面板下方
    codeNotice.value = preview.message || '卡码或兑换码不存在'
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '核销失败，请稍后重试')
  } finally {
    redeemLoading.value = false
  }
}

async function refreshSubscriptions() {
  subscriptions.value = await subscriptionApi.getMine().catch(() => subscriptions.value)
  try {
    await userStore.fetchUser()
  } catch {
    // 会员身份刷新失败不影响核销结果
  }
}

async function confirmCodeRedeem() {
  const code = redeemCode.value.trim()
  if (!code) return
  redeemLoading.value = true
  try {
    const res = await membershipApi.redeem(code)
    toast.success(res.message || '卡码核销成功')
    redeemCode.value = ''
    codePreview.value = null
    await refreshSubscriptions()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '核销失败，请稍后重试')
  } finally {
    redeemLoading.value = false
  }
}

// ===== 下单 =====
async function handleOrder(kind: 'recharge' | 'subscription', itemId: number) {
  orderLoading.value = itemId
  try {
    const res = await paymentApi.createOrder({ kind, item_id: itemId, payment_method: payMethod.value })
    if (res.pay_url) {
      toast.success('正在跳转支付…')
      window.location.href = res.pay_url
    } else {
      toast.error('未获取到支付链接')
    }
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '下单失败，请稍后重试')
  } finally {
    orderLoading.value = null
  }
}

// ===== 数据加载 =====
async function refreshBalance() {
  try {
    const statusFallback: CheckinStatus | null = null
    const [logRes, status] = await Promise.all([
      pointsApi.log({ limit: 1 }),
      checkinApi.status().catch(() => statusFallback),
    ])
    balance.value = logRes.balance
    if (status) checkin.value = status
  } catch { /* 静默 */ }
}

async function loadAll() {
  loading.value = true
  try {
    const emptyPkgs = { enabled: false, packages: [] as RechargePackage[] }
    // 兜底也要带上接入方式字段：公益服下接口失败时不能退回“付费服”的口径
    const emptyPlans = {
      enabled: false,
      plans: [] as SubscriptionPlan[],
      access_mode: 'paid' as 'paid' | 'free',
      is_free: false,
      access_note: '',
    }
    const emptyMethods: PaymentMethod[] = []
    const emptyOrders = { orders: [] as OrderRow[] }
    const emptyLogs = { total: 0, balance: 0, logs: [] as PointsLogEntry[] }

    const statusFallback: CheckinStatus | null = null
    const emptySubs: MySubscription[] = []
    const exchangeFallback = { enabled: true }
    const [pkgRes, planRes, methodRes, orderRes, logRes, statusRes, exchangeRes, subsRes] = await Promise.all([
      paymentApi.packages().catch(() => emptyPkgs),
      paymentApi.plans().catch(() => emptyPlans),
      paymentApi.methods().catch(() => emptyMethods),
      paymentApi.orders({ limit: 20 }).catch(() => emptyOrders),
      pointsApi.log({ limit: 30 }).catch(() => emptyLogs),
      checkinApi.status().catch(() => statusFallback),
      exchangeApi.config().catch(() => exchangeFallback),
      subscriptionApi.getMine().catch(() => emptySubs),
    ])
    packages.value = pkgRes.packages || []
    plans.value = planRes.plans || []
    isFreeRealm.value = planRes.is_free === true || planRes.access_mode === 'free'
    realmNote.value = planRes.access_note || ''
    methods.value = Array.isArray(methodRes) ? methodRes : []
    orders.value = orderRes.orders || []
    logs.value = logRes.logs || []
    balance.value = logRes.balance
    checkin.value = statusRes
    rechargeEnabled.value = pkgRes.enabled !== false
    plansEnabled.value = planRes.enabled !== false
    exchangeEnabled.value = exchangeRes.enabled !== false
    subscriptions.value = Array.isArray(subsRes) ? subsRes : []
  } finally {
    loading.value = false
  }
}

const TYPE_META: Record<string, { label: string; income: boolean }> = {
  checkin: { label: '签到', income: true },
  invite: { label: '邀请奖励', income: true },
  invitee: { label: '受邀奖励', income: true },
  rebate: { label: '充值返利', income: true },
  exchange: { label: '兑换码', income: true },
  recharge: { label: '充值', income: true },
  admin_grant: { label: '管理员发放', income: true },
  admin_deduct: { label: '管理员扣除', income: false },
}

function typeMeta(t: string) {
  return TYPE_META[t] || { label: t, income: true }
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}

function orderStatusMeta(s: string) {
  if (s === 'paid') return { label: '已支付', cls: 'au-badge au-badge-green' }
  if (s === 'pending') return { label: '待支付', cls: 'au-badge au-badge-amber' }
  return { label: s, cls: 'au-badge au-badge-rose' }
}

const paidFlag = computed(() => route.query.paid === '1')

// ===== 支付回跳后的到账轮询 =====
// 网关异步回调可能稍晚于浏览器跳转，这里轮询订单状态，到账后自动刷新积分与会员身份
let payPollTimer: number | null = null
const payPolling = ref(false)

function stopPayPoll() {
  if (payPollTimer !== null) {
    window.clearInterval(payPollTimer)
    payPollTimer = null
  }
  payPolling.value = false
}

async function pollPaymentResult() {
  const targetOrder = (route.query.order as string) || ''
  const paidBefore = new Set(
    orders.value.filter((o) => o.status === 'paid').map((o) => o.order_id),
  )
  let attempts = 0
  payPolling.value = true

  payPollTimer = window.setInterval(async () => {
    attempts += 1
    try {
      const res = await paymentApi.orders({ limit: 20 })
      const list = res.orders || []
      orders.value = list

      const arrived = list.find((o) => {
        if (o.status !== 'paid' || paidBefore.has(o.order_id)) return false
        return targetOrder ? o.order_id === targetOrder : true
      })

      if (arrived) {
        await refreshBalance()
        // 会员身份 / 付费墙状态随之刷新（头像、VIP 标识、详情页提示）
        userStore.fetchUser().catch(() => {})
        toast.success(`支付成功，「${arrived.item_name}」已到账`)
        stopPayPoll()
        return
      }
    } catch {
      /* 轮询失败不打断，等下一轮 */
    }

    if (attempts >= 10) {
      stopPayPoll()
      toast.info('暂未收到支付结果，到账后余额与会员会自动更新（可点刷新）', 5000)
    }
  }, 3000)
}

onMounted(async () => {
  await loadAll()
  // 支持 ?tab=log 等定位到指定选项卡（签到页「全部流水」链接）
  const tabParam = route.query.tab
  if (tabParam === 'recharge' || tabParam === 'plans' || tabParam === 'orders' || tabParam === 'log') {
    tab.value = tabParam
  }
  // 支付完成跳回：轮询到账结果（订单号来自 ?order=，兼容旧 ?paid=1）
  if (paidFlag.value || route.query.order) {
    toast.info('支付已提交，正在确认到账结果…', 4000)
    pollPaymentResult()
  }
})

onBeforeUnmount(stopPayPoll)
</script>

<template>
  <div class="au-page wallet-view">
    <!-- 余额主卡：左右分区 — 左侧余额与签到态，右侧核销面板 -->
    <section class="balance-hero au-anim-up">
      <div class="bh-main">
        <span class="balance-label">
          <Wallet :size="15" />
          积分余额
        </span>
        <div class="balance-num">
          <span class="num">{{ balance }}</span>
          <span class="unit">积分</span>
        </div>
        <!-- 多服运营下这句必须写明：积分是一份通用的，会员才是一个服一个 -->
        <p class="balance-note">积分与余额全站通用（多服共用一份）；会员是一个服一个。</p>

        <!-- 签到态：紧凑胶囊 -->
        <RouterLink v-if="checkin" to="/checkin" class="checkin-pill" :class="{ done: checkin.checked_today }">
          <Flame :size="13" />
          <span>连签 <strong>{{ checkin.streak }}</strong> 天</span>
          <span class="pill-divider" />
          <span>{{ checkin.checked_today ? '今日已签' : '今日未签' }}</span>
          <ChevronRight :size="12" class="pill-arrow" />
        </RouterLink>
      </div>

      <div class="bh-divider" aria-hidden="true" />

      <!-- 统一核销面板：卡码与兑换码共用同一个入口，由后端预检自动识别 -->
      <form class="bh-redeem" @submit.prevent="handleRedeem">
        <span class="redeem-label">
          <TicketCheck :size="14" />
          卡码 · 兑换码
        </span>
        <div class="redeem-row">
          <input
            ref="redeemInputRef"
            v-model="redeemCode"
            class="au-input redeem-input"
            placeholder="输入卡码或兑换码"
            maxlength="64"
            autocomplete="off"
            @input="resetCodeFeedback"
          >
          <button
            type="submit"
            class="au-btn au-btn-primary"
            :disabled="redeemLoading || !redeemCode.trim()"
          >
            <Sparkles v-if="!redeemLoading" :size="15" />
            <span v-else class="au-spinner spinner-sm" />
            核销
          </button>
        </div>

        <!-- 会员卡码预检通过：先给类型与天数，确认后再核销 -->
        <div v-if="codePreview" class="redeem-preview">
          <CircleCheck :size="14" />
          <span class="rp-text">
            {{ codePreview.type_name }}
            <strong>· {{ codePreview.days_text }}</strong>
            <template v-if="codePreview.realm_name"> · 开「{{ codePreview.realm_name }}」的会员</template>
            <template v-if="codePreview.is_named"> · 限指定账号</template>
          </span>
          <button
            type="button"
            class="au-btn au-btn-primary au-btn-sm"
            :disabled="redeemLoading"
            @click="confirmCodeRedeem"
          >
            <span v-if="redeemLoading" class="au-spinner spinner-sm" />
            确认开通
          </button>
        </div>

        <p v-else class="redeem-hint" :class="{ warn: !!codeNotice }">
          {{ codeNotice || '会员时长 · 积分 · 订阅，自动识别类型' }}
        </p>
      </form>

      <button class="au-btn au-btn-ghost au-btn-sm refresh" title="刷新" @click="loadAll">
        <RefreshCw :size="14" :class="{ spinning: loading }" />
      </button>
    </section>

    <!-- 选项卡 -->
    <nav class="tabs au-anim-up" style="animation-delay: 100ms">
      <button class="tab" :class="{ active: tab === 'recharge' }" @click="tab = 'recharge'">
        <Coins :size="15" /> 充值积分
      </button>
      <button class="tab" :class="{ active: tab === 'plans' }" @click="tab = 'plans'">
        <Zap :size="15" /> 购买订阅
      </button>
      <button class="tab" :class="{ active: tab === 'orders' }" @click="tab = 'orders'">
        <Receipt :size="15" /> 订单
      </button>
      <button class="tab" :class="{ active: tab === 'log' }" @click="tab = 'log'">
        <ArrowDownLeft :size="15" /> 流水
      </button>
    </nav>

    <!-- 支付方式：仅在购买类选项卡显示一次 -->
    <div v-if="(tab === 'recharge' || tab === 'plans') && methods.length" class="pay-methods au-anim-up">
      <span class="pay-methods-label">支付方式</span>
      <button
        v-for="m in methods"
        :key="m.id"
        class="pay-method"
        :class="{ active: payMethod === m.id }"
        @click="payMethod = m.id"
      >
        {{ m.name }}
      </button>
    </div>

    <!-- 充值积分：横向行卡 — 左侧点数信息，右侧价格与购买 -->
    <section v-if="tab === 'recharge'" class="tab-body au-anim-up">
      <div v-if="!rechargeEnabled" class="au-empty">
        <CircleAlert :size="30" />
        <p>充值通道暂未开启，可先通过签到、邀请或兑换获取积分</p>
      </div>
      <div v-else-if="!packages.length" class="au-empty">
        <Coins :size="30" />
        <p>暂无可用充值套餐</p>
      </div>
      <div v-else class="pkg-list">
        <button
          v-for="p in packages"
          :key="p.id"
          class="pkg-row"
          :class="{ popular: p.is_popular }"
          :disabled="orderLoading === p.id"
          @click="handleOrder('recharge', p.id)"
        >
          <span class="pkg-points-wrap">
            <span class="pkg-points">
              <strong>{{ p.total_points }}</strong>
              <em>积分</em>
            </span>
            <span class="pkg-name">{{ p.name }}</span>
            <span v-if="p.bonus > 0" class="pkg-bonus">
              <Sparkles :size="11" />
              含赠送 {{ p.bonus }} 积分
            </span>
          </span>

          <span class="pkg-buy">
            <span v-if="p.is_popular" class="pkg-pop-tag">超值</span>
            <span class="pkg-price">¥{{ p.price.toFixed(2) }}</span>
            <span class="pkg-cta">
              <span v-if="orderLoading === p.id" class="au-spinner spinner-sm" />
              <template v-else>
                购买
                <ExternalLink :size="12" />
              </template>
            </span>
          </span>
        </button>
      </div>
    </section>

    <!-- 购买订阅：公益服换成「免费开放」说明，其余按原样卖套餐 -->
    <section v-if="tab === 'plans'" class="tab-body au-anim-up">
      <!-- 公益服：没有付费墙，也没有要卖的东西 -->
      <div v-if="isFreeRealm" class="free-callout au-card">
        <span class="free-badge">
          <Sparkles :size="13" />
          公益服 · 免费开放
        </span>
        <p class="free-lead">本服无需开通会员，登录后即可播放全库内容。</p>
        <p class="free-note">{{ realmNote || '资源请勿下载、转卖或外传，账号仅限本人使用。' }}</p>
        <RouterLink to="/media" class="au-btn au-btn-primary au-btn-sm">
          <Film :size="14" />
          进入媒体库
        </RouterLink>
      </div>

      <!-- 当前会员状态：已开通显示套餐与到期，未开通提示付费墙 -->
      <div v-else-if="plansEnabled" class="member-status" :class="{ inactive: !currentSub }" >
        <Crown :size="15" />
        <template v-if="currentSub">
          <span>当前会员：<strong>{{ currentSub.plan_name }}</strong></span>
          <span class="ms-sep">·</span>
          <span>剩 <strong>{{ currentSub.days_left }}</strong> 天（{{ currentSub.end_date?.slice(0, 10) }} 到期）</span>
        </template>
        <span v-else>当前未开通会员，选择套餐即可解锁全库播放</span>
      </div>

      <!-- 卡码核销入口已收归顶部面板，这里只留一行指引，避免两个输入框让用户猜该填哪个 -->
      <button v-if="plansEnabled && !isFreeRealm" type="button" class="code-tip" @click="focusRedeem">
        <KeyRound :size="14" />
        <span>已有卡码 / 兑换码？用顶部「卡码 · 兑换码」入口，注册码 / 续期码 / 白名单码自动识别</span>
        <ChevronRight :size="14" class="ct-arrow" />
      </button>

      <div v-if="!isFreeRealm && !plansEnabled" class="au-empty">
        <CircleAlert :size="30" />
        <p>订阅购买暂未开启，可联系管理员换用卡码开通</p>
      </div>
      <div v-else-if="!isFreeRealm && !plans.length" class="au-empty">
        <Zap :size="30" />
        <p>暂无可购买套餐，请联系管理员开通</p>
      </div>
      <div v-else-if="!isFreeRealm" class="plan-grid">
        <div v-for="p in plans" :key="p.id" class="plan-card" :class="{ popular: p.is_popular }">
          <span v-if="p.is_popular" class="pkg-pop-tag">推荐</span>

          <div class="plan-head">
            <h4 class="plan-name">
              {{ p.name }}
              <em v-if="p.realm_name" class="plan-realm">{{ p.realm_name }}</em>
            </h4>
            <span class="plan-price">
              ¥{{ p.price.toFixed(2) }}
              <em>/ {{ p.duration_days }} 天</em>
            </span>
          </div>
          <p class="plan-desc">{{ p.description || '会员专属权益' }}</p>

          <ul v-if="p.features && p.features.length" class="plan-features">
            <li v-for="(f, i) in p.features" :key="i">
              <CircleCheck :size="13" /> {{ f }}
            </li>
          </ul>

          <button
            class="au-btn plan-btn"
            :class="p.is_popular ? 'au-btn-primary' : 'au-btn-ghost'"
            :disabled="orderLoading === p.id"
            @click="handleOrder('subscription', p.id)"
          >
            <span v-if="orderLoading === p.id" class="au-spinner spinner-sm" />
            <template v-else>立即开通</template>
          </button>
        </div>
      </div>
    </section>

    <!-- 订单 -->
    <section v-if="tab === 'orders'" class="tab-body au-anim-up">
      <div v-if="!orders.length" class="au-empty">
        <Receipt :size="30" />
        <p>还没有订单记录</p>
      </div>
      <div v-else class="order-list au-card">
        <div v-for="o in orders" :key="o.order_id" class="order-item">
          <span class="order-icon" :class="{ pending: o.status === 'pending' }">
            <Clock v-if="o.status === 'pending'" :size="14" />
            <CircleCheck v-else-if="o.status === 'paid'" :size="14" />
            <CircleAlert v-else :size="14" />
          </span>
          <div class="order-main">
            <span class="order-name">{{ o.item_name }}</span>
            <span class="order-sub">
              <span class="order-id mono">{{ o.order_id }}</span>
              <span class="order-sep">·</span>
              <span>{{ fmtTime(o.created_at) }}</span>
            </span>
          </div>
          <div class="order-side">
            <span class="order-amount">¥{{ o.amount.toFixed(2) }}</span>
            <span :class="orderStatusMeta(o.status).cls">{{ orderStatusMeta(o.status).label }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 流水 -->
    <section v-if="tab === 'log'" class="tab-body au-anim-up">
      <div v-if="!logs.length" class="au-empty">
        <ArrowDownLeft :size="30" />
        <p>暂无积分流水</p>
      </div>
      <div v-else class="log-list au-card">
        <div v-for="l in logs" :key="l.id" class="log-item">
          <span class="log-icon" :class="typeMeta(l.type).income ? 'in' : 'out'">
            <ArrowDownLeft v-if="typeMeta(l.type).income" :size="14" />
            <ArrowUpRight v-else :size="14" />
          </span>
          <div class="log-body">
            <span class="log-desc">{{ l.description || typeMeta(l.type).label }}</span>
            <span class="log-time">{{ fmtTime(l.created_at) }}</span>
          </div>
          <div class="log-amount" :class="typeMeta(l.type).income ? 'in' : 'out'">
            {{ typeMeta(l.type).income ? '+' : '' }}{{ l.amount }}
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.wallet-view { display: flex; flex-direction: column; gap: 1.125rem; }

/* ==================== 余额主卡（左右分区） ==================== */
.balance-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1.1fr) auto;
  align-items: stretch;
  gap: 1.5rem;
  padding: 1.5rem 1.625rem;
  border-radius: var(--au-r-xl);
  background: linear-gradient(135deg, rgba(34, 211, 238, 0.14), rgba(167, 139, 250, 0.14) 55%, rgba(7, 11, 18, 0.2));
  border: 1px solid var(--au-primary-border);
  backdrop-filter: blur(14px);
  position: relative;
  overflow: hidden;
}
.balance-hero::after {
  content: '';
  position: absolute;
  top: -60%;
  right: -10%;
  width: 300px;
  height: 200px;
  background: radial-gradient(ellipse, rgba(34, 211, 238, 0.18), transparent 70%);
  filter: blur(30px);
  pointer-events: none;
}

.bh-main {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.375rem;
  min-width: 0;
}

.balance-label {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: var(--au-text-2);
}

.balance-num {
  display: flex;
  align-items: baseline;
  gap: 0.375rem;
}
.balance-num .num {
  font-size: 2.75rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  background: var(--au-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.balance-num .unit { font-size: 0.875rem; color: var(--au-text-3); }

.balance-note {
  margin: 0.5rem 0 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  line-height: 1.5;
}

/* 签到态胶囊 */
.checkin-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  width: fit-content;
  margin-top: 0.375rem;
  padding: 0.3125rem 0.6875rem;
  background: var(--au-warning-soft);
  border: 1px solid rgba(251, 191, 36, 0.28);
  border-radius: var(--au-r-full);
  color: var(--au-warning);
  font-size: 0.75rem;
  text-decoration: none;
  transition: all var(--au-fast) var(--au-ease);
}
.checkin-pill strong { font-weight: 700; }
.checkin-pill.done {
  background: var(--au-success-soft);
  border-color: rgba(52, 211, 153, 0.28);
  color: var(--au-success);
}
.checkin-pill:hover {
  transform: translateY(-1px);
  border-color: var(--au-primary-border);
  color: var(--au-primary);
}
.pill-divider {
  width: 1px;
  height: 11px;
  background: currentColor;
  opacity: 0.35;
}
.pill-arrow { opacity: 0.6; }

.bh-divider {
  background: var(--au-border);
  margin: 0.25rem 0;
}

/* 兑换面板 */
.bh-redeem {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.4375rem;
  min-width: 0;
}

.redeem-label {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text-2);
}

.redeem-row { display: flex; gap: 0.5rem; }
.redeem-input { flex: 1; min-width: 0; height: 40px; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.8125rem; }

.redeem-hint {
  margin: 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.refresh { align-self: flex-start; margin-top: 0.25rem; }
.spinning { animation: au-spin 0.9s linear infinite; }

/* ==================== 选项卡 ==================== */
.tabs {
  display: flex;
  gap: 0.375rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  padding: 0.3125rem;
  overflow-x: auto;
  scrollbar-width: none;
}
.tabs::-webkit-scrollbar { display: none; }

.tab {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  height: 38px;
  padding: 0 0.875rem;
  background: none;
  border: none;
  border-radius: var(--au-r-md);
  color: var(--au-text-3);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--au-fast);
  white-space: nowrap;
}
.tab:hover { color: var(--au-text); background: var(--au-surface-2); }
.tab.active {
  background: var(--au-gradient);
  color: #05141c;
  box-shadow: 0 3px 12px var(--au-primary-glow);
}

/* ==================== 支付方式 ==================== */
.pay-methods { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.pay-methods-label { font-size: 0.8125rem; color: var(--au-text-3); }
.pay-method {
  height: 32px;
  padding: 0 0.875rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  color: var(--au-text-2);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all var(--au-fast);
}
.pay-method:hover { border-color: var(--au-border-strong); color: var(--au-text); }
.pay-method.active {
  background: var(--au-primary-soft);
  border-color: var(--au-primary-border);
  color: var(--au-primary);
  font-weight: 600;
}

/* ==================== 充值套餐：横向行卡 ==================== */
.pkg-list {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.pkg-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.25rem;
  padding: 0.9375rem 1.25rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
  text-align: left;
  position: relative;
}
.pkg-row:hover:not(:disabled) {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(34, 211, 238, 0.12);
}
.pkg-row.popular { border-color: var(--au-primary-border); }
.pkg-row:disabled { opacity: 0.6; cursor: wait; }

.pkg-points-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.1875rem;
  min-width: 0;
}

.pkg-points { display: flex; align-items: baseline; gap: 0.3125rem; }
.pkg-points strong {
  font-size: 1.5rem;
  font-weight: 800;
  background: var(--au-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}
.pkg-points em { font-style: normal; font-size: 0.75rem; color: var(--au-text-3); }

.pkg-name { font-size: 0.75rem; color: var(--au-text-4); }

.pkg-bonus {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.6875rem;
  color: var(--au-success);
}

.pkg-buy {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  flex-shrink: 0;
}

.pkg-pop-tag {
  padding: 0.125rem 0.5rem;
  background: var(--au-gradient-warm);
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

.pkg-price {
  font-size: 1.125rem;
  font-weight: 800;
  color: var(--au-text);
  font-variant-numeric: tabular-nums;
}

.pkg-cta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.3125rem;
  height: 34px;
  min-width: 76px;
  padding: 0 1rem;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text-2);
  transition: all var(--au-fast) var(--au-ease);
}
.pkg-row:hover:not(:disabled) .pkg-cta {
  background: var(--au-gradient);
  border-color: transparent;
  color: #05141c;
}

.spinner-sm { width: 14px; height: 14px; border-width: 2px; }

/* ==================== 当前会员状态行 ==================== */
.member-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-bottom: 0.875rem;
  padding: 0.6875rem 0.9375rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-md);
  font-size: 0.8125rem;
  color: var(--au-text-2);
}

/* 公益服（v2.7.0）：免费开放说明卡，替代套餐区 */
.free-callout {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 1rem 1.125rem;
}

.free-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  padding: 0.1875rem 0.5625rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-full);
  color: var(--au-primary);
  font-size: 0.6875rem;
  font-weight: 700;
}

.free-lead { margin: 0; font-size: 0.875rem; color: var(--au-text); }
.free-note { margin: 0; font-size: 0.8125rem; line-height: 1.6; color: var(--au-text-3); }

/* 卡码预检通过后的确认行（内联在核销面板里） */
.redeem-preview {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.4375rem 0.625rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-md);
  font-size: 0.75rem;
  color: var(--au-text-2);
}
.redeem-preview svg { color: var(--au-primary); flex-shrink: 0; }
.redeem-preview strong { color: var(--au-text); font-variant-numeric: tabular-nums; }
.redeem-preview .rp-text { flex: 1; min-width: 0; }
.redeem-preview .au-btn { margin-left: auto; }

.redeem-hint.warn { color: var(--au-warning); }

/* ===== 订阅页的核销指引（入口已统一到顶部） ===== */
.code-tip {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  margin-bottom: 0.875rem;
  padding: 0.625rem 0.875rem;
  background: var(--au-surface-2, rgba(255, 255, 255, 0.02));
  border: 1px dashed var(--au-border, rgba(255, 255, 255, 0.08));
  border-radius: var(--au-r-md);
  color: var(--au-text-3, var(--au-text-2));
  font-size: 0.75rem;
  text-align: left;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}
.code-tip svg { color: var(--au-primary); flex-shrink: 0; }
.code-tip span { flex: 1; min-width: 0; }
.code-tip .ct-arrow { color: var(--au-text-4); }
.code-tip:hover {
  border-color: var(--au-primary-border);
  color: var(--au-text-2);
  transform: translateY(-1px);
}

.member-status svg {
  color: var(--au-primary);
  flex-shrink: 0;
}

.member-status strong {
  color: var(--au-text);
  font-variant-numeric: tabular-nums;
}

.member-status.inactive {
  background: var(--au-warning-soft);
  border-color: rgba(251, 191, 36, 0.28);
}

.member-status.inactive svg {
  color: var(--au-warning);
}

.ms-sep {
  color: var(--au-text-4);
}

/* ==================== 订阅套餐 ==================== */
.plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 0.875rem;
}

.plan-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1.25rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  transition: all var(--au-fast);
}
.plan-card.popular { border-color: var(--au-primary-border); box-shadow: 0 0 24px rgba(34, 211, 238, 0.08); }

.plan-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}
.plan-name { margin: 0; font-size: 1rem; font-weight: 700; color: var(--au-text); }
/* 归属服：多服运营下同一页会列出几个服的套餐，买哪份要看得清 */
.plan-realm {
  display: inline-block;
  margin-left: 0.375rem;
  padding: 0.0625rem 0.4375rem;
  border-radius: 999px;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  color: var(--au-text-3);
  font-size: 0.625rem;
  font-weight: 500;
  font-style: normal;
  vertical-align: middle;
}

.plan-price { font-size: 1.125rem; font-weight: 800; color: var(--au-text); white-space: nowrap; }
.plan-price em { font-style: normal; font-size: 0.6875rem; font-weight: 400; color: var(--au-text-3); }

.plan-desc { margin: 0; font-size: 0.8125rem; color: var(--au-text-3); line-height: 1.5; }

.plan-features {
  list-style: none;
  margin: 0.125rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
.plan-features li {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  font-size: 0.8125rem;
  color: var(--au-text-2);
}
.plan-features svg { color: var(--au-success); flex-shrink: 0; }

.plan-btn { margin-top: auto; width: 100%; }

/* ==================== 订单 ==================== */
.order-list { overflow: hidden; }

.order-item {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.9375rem 1.125rem;
  border-bottom: 1px solid var(--au-border);
}
.order-item:last-child { border-bottom: none; }

.order-icon {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-md);
  background: var(--au-success-soft);
  color: var(--au-success);
  flex-shrink: 0;
}
.order-icon.pending {
  background: var(--au-warning-soft);
  color: var(--au-warning);
}

.order-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.1875rem; }
.order-name { font-size: 0.875rem; font-weight: 600; color: var(--au-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.order-sub {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  overflow: hidden;
}
.order-id { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.order-sep { opacity: 0.5; }

.order-side { display: flex; flex-direction: column; align-items: flex-end; gap: 0.3125rem; flex-shrink: 0; }
.order-amount { font-size: 0.9375rem; font-weight: 700; color: var(--au-text); }

/* ==================== 流水 ==================== */
.log-list { overflow: hidden; }

.log-item {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.875rem 1.125rem;
  border-bottom: 1px solid var(--au-border);
}
.log-item:last-child { border-bottom: none; }

.log-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-md);
  flex-shrink: 0;
}
.log-icon.in { background: var(--au-success-soft); color: var(--au-success); }
.log-icon.out { background: var(--au-danger-soft); color: var(--au-danger); }

.log-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.125rem; }
.log-desc { font-size: 0.8125rem; color: var(--au-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-time { font-size: 0.6875rem; color: var(--au-text-4); }

.log-amount { font-weight: 700; font-size: 0.9375rem; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.log-amount.in { color: var(--au-success); }
.log-amount.out { color: var(--au-danger); }

.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

@media (max-width: 720px) {
  .balance-hero {
    grid-template-columns: 1fr;
    gap: 1.25rem;
    padding: 1.375rem 1.25rem;
  }
  .bh-divider { height: 1px; width: 100%; margin: 0; }
  .refresh { position: absolute; top: 1.125rem; right: 1.125rem; margin: 0; }
  .balance-num .num { font-size: 2.25rem; }
  .pkg-row { flex-direction: column; align-items: stretch; gap: 0.875rem; }
  .pkg-buy { justify-content: space-between; }
  .order-item { flex-wrap: wrap; }
}
</style>
