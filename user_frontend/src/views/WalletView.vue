<script setup lang="ts">
/**
 * 钱包 — 余额 / 卡码·兑换码核销 / 订单 / 积分流水
 *
 * v2.43.0：购买功能（充值/订阅/优惠券）已拆到 StoreView（/store）。
 * 原钱包页逻辑： / 积分充值（支付下单）/ 卡码·兑换码·优惠券核销 / 订单记录 / 积分流水
 * 布局：余额卡左右分区（左余额+签到态，右唯一的核销面板）；套餐卡横向结构化行
 *
 * v2.10.1：优惠券并进顶部那一个核销面板。此前「卡码 · 兑换码」在余额卡里、
 * 「优惠码」是分页上另起的一条输入框，同一页两个「输入码 → 应用」的面板，
 * 既割裂又让用户猜手里那张码该填哪边；现在只有一个入口，由后端预检识别来源。
 */
import { ref, computed, onMounted, onActivated, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  Wallet, TicketCheck, Receipt, RefreshCw, Sparkles, Flame,
  ArrowUpRight, ArrowDownLeft, CircleCheck, Clock, CircleAlert, ChevronRight,
  Undo2, Percent, Zap,
} from 'lucide-vue-next'
import {
  pointsApi, checkinApi, exchangeApi, paymentApi, membershipApi, vitalityApi,
  type PointsLogEntry,
  type OrderRow, type CheckinStatus, type CodePreview, type VitalityStatus,
} from '@/api/economy'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(true)
const balance = ref(0)
const checkin = ref<CheckinStatus | null>(null)
/** 活力值（仅公益服用户有值，非公益服 403 则为 null 不显示） */
const vitality = ref<VitalityStatus | null>(null)
const showRechargeVitality = ref(false)
const rechargeQty = ref(1)
const recharging = ref(false)
const vitalityPointCost = ref(10)
const orders = ref<OrderRow[]>([])
const logs = ref<PointsLogEntry[]>([])
const tab = ref<'orders' | 'log'>('orders')

// ===== 统一核销入口（卡码 / 兑换码 / 邀请码自动识别）=====
// 卡码（会员时长）与兑换码（积分/订阅）原本是两个输入框，用户得自己判断该填哪个。
// 现在只留一个入口：先向后端预检识别来源，再走对应链路（邀请码给出指引）。
const redeemCode = ref('')
const redeemLoading = ref(false)
const codePreview = ref<CodePreview | null>(null)
const codeNotice = ref('')
const couponHint = ref(false)
const redeemInputRef = ref<HTMLInputElement | null>(null)
/** 核销面板下方提示：卡码/兑换码的错误信息 */
const redeemNotice = computed(() => codeNotice.value)

/** 重新输入时清掉上一轮预检结果，避免残留提示误导 */
function resetCodeFeedback() {
  codePreview.value = null
  codeNotice.value = ''
  couponHint.value = false
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

    if (preview.kind === 'coupon') {
      // 钱包页不处理优惠券：引导用户去商店使用
      couponHint.value = true
      return
    }

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


const exchangeEnabled = ref(true)

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

/** 活力值：用积分续活力 */
async function doRechargeVitality() {
  recharging.value = true
  try {
    const r = await vitalityApi.recharge(rechargeQty.value * vitalityPointCost.value)
    if (vitality.value) vitality.value.vitality = r.vitality
    balance.value = r.points_balance
    showRechargeVitality.value = false
  } catch (e: any) {
    alert(e?.response?.data?.detail || '续活失败，请稍后重试')
  } finally {
    recharging.value = false
  }
}

/** 是否已完成过首屏加载：KeepAlive 缓存命中时走静默刷新 */
const hasLoaded = ref(false)

/** 取 settled 结果：成功用返回值；失败时首屏/手动刷新走兜底，静默刷新返回 undefined（调用方跳过赋值，不碰已有数据） */
function settled<T>(r: PromiseSettledResult<T>, fallback: T, silent: boolean): T | undefined {
  if (r.status === 'fulfilled') return r.value
  return silent ? undefined : fallback
}


async function loadAll(silent = false) {
  if (!silent) loading.value = true
  try {
    const emptyOrders = { orders: [] as OrderRow[] }
    const emptyLogs = { total: 0, balance: 0, logs: [] as PointsLogEntry[] }
    const statusFallback: CheckinStatus | null = null
    const exchangeFallback = { enabled: true }
    const [orderR, logR, statusR, exchangeR, vitalityR] = await Promise.allSettled([
      paymentApi.orders({ limit: 20 }),
      pointsApi.log({ limit: 30 }),
      checkinApi.status(),
      exchangeApi.config(),
      // 活力值：非公益服用户 403，settled 兜底为 null 不展示
      vitalityApi.status(),
    ])
    const orderData = settled(orderR, emptyOrders, silent)
    if (orderData !== undefined) orders.value = orderData.orders || []
    const logData = settled(logR, emptyLogs, silent)
    if (logData !== undefined) {
      logs.value = logData.logs || []
      balance.value = logData.balance
    }
    const checkinStatus = settled(statusR, statusFallback, silent)
    if (checkinStatus !== undefined) checkin.value = checkinStatus
    const exchangeCfg = settled(exchangeR, exchangeFallback, silent)
    if (exchangeCfg !== undefined) exchangeEnabled.value = exchangeCfg.enabled !== false
    const vitalityData = vitalityR.status === 'fulfilled' ? vitalityR.value : null
    vitality.value = vitalityData && vitalityData.success ? vitalityData : null
  } finally {
    loading.value = false
    hasLoaded.value = true
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
  // 退款 / 关单（v2.9.0）：用户端要说清楚这笔钱的状态，否则只会来问客服
  if (s === 'refunded') return { label: '已退款', cls: 'au-badge au-badge-rose' }
  if (s === 'closed') return { label: '已关闭', cls: 'au-badge au-badge-violet' }
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

/** 旧地址兼容：/wallet?tab=recharge|plans 跳到商店 */
const lastHandledEntry = ref('')
function handleEntryQuery() {
  const tabQuery = route.query.tab as string | undefined

  if (tabQuery === 'recharge' || tabQuery === 'plans') {
    const query = { ...route.query }
    delete query.tab
    router.replace({ path: '/store', query: { ...query, tab: tabQuery } })
    return
  }

  if (tabQuery === 'orders' || tabQuery === 'log') {
    tab.value = tabQuery
  }

  const order = route.query.order
  if ((paidFlag.value || order) && !payPolling.value) {
    const key = `${order ?? ''}|${route.query.paid ?? ''}`
    if (lastHandledEntry.value !== key) {
      lastHandledEntry.value = key
      toast.info('支付已提交，正在确认到账结果…', 4000)
      pollPaymentResult()
    }
  }
}

onMounted(async () => {
  await loadAll()
  handleEntryQuery()
})

onActivated(() => {
  handleEntryQuery()
  if (hasLoaded.value) {
    loadAll(true)
  }
})

watch(() => route.query.tab, (tabQuery) => {
  const t = tabQuery as string | undefined
  if (t === 'recharge' || t === 'plans') {
    const query = { ...route.query }
    delete query.tab
    router.replace({ path: '/store', query: { ...query, tab: t } })
    return
  }
  if (t === 'orders' || t === 'log') {
    tab.value = t
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

        <!-- 签到态：紧凑胶囊（签到开关关闭时隐藏） -->
        <RouterLink v-if="checkin && checkin.enabled !== false" to="/checkin" class="checkin-pill" :class="{ done: checkin.checked_today }">
          <Flame :size="13" />
          <span>连签 <strong>{{ checkin.streak }}</strong> 天</span>
          <span class="pill-divider" />
          <span>{{ checkin.checked_today ? '今日已签' : '今日未签' }}</span>
          <ChevronRight :size="12" class="pill-arrow" />
        </RouterLink>

        <!-- 活力值：仅公益服用户 -->
        <div v-if="vitality" class="vitality-row">
          <span class="vitality-icon"><Zap :size="15" /></span>
          <div class="vitality-meta">
            <div class="vitality-top">
              <strong>活力值 {{ vitality.vitality }} / {{ vitality.max }}</strong>
              <span v-if="!vitality.can_play" class="vitality-warn">低于观影阈值 {{ vitality.limit_threshold }}，已限制观影</span>
              <span v-else class="vitality-ok">每日 00:00 自动扣 1 点</span>
            </div>
            <div class="member-bar" role="progressbar" :aria-valuenow="vitality.vitality" aria-valuemin="0" :aria-valuemax="vitality.max">
              <i :style="{ width: (vitality.vitality / vitality.max * 100) + '%' }" />
            </div>
          </div>
          <button type="button" class="vitality-recharge-btn" @click="showRechargeVitality = true">用积分续</button>
        </div>

      </div>
    </section>

<form class="bh-redeem" @submit.prevent="handleRedeem">
  <label class="redeem-label">
    <TicketCheck :size="14" /> 卡码 · 兑换码
  </label>

  <div class="redeem-row">
    <input
      ref="redeemInputRef"
      class="redeem-input"
      v-model="redeemCode"
      placeholder="输入卡码 / 兑换码"
      maxlength="64"
      @input="resetCodeFeedback"
    />
    <button class="au-btn au-btn-primary" type="submit" :disabled="redeemLoading || !redeemCode.trim()">
      <Sparkles :size="14" />
      <span v-if="redeemLoading" class="spinner"></span>
      使用
    </button>
  </div>

  <p v-if="couponHint" class="redeem-hint warn">
    这是优惠券，请到 <RouterLink to="/store">商店</RouterLink> 使用
  </p>

  <div v-if="codePreview" class="redeem-preview">
    <div class="rp-text">
      <CircleCheck :size="14" />
      <strong>{{ codePreview.type_name }}</strong>
      <span>{{ codePreview.days_text }}</span>
      <span>{{ codePreview.realm_name }}</span>
      <span>{{ codePreview.is_named ? '记名' : '不记名' }}</span>
    </div>
    <button class="au-btn au-btn-primary au-btn-sm" type="button" :disabled="redeemLoading" @click="confirmCodeRedeem">
      确认开通
    </button>
  </div>

  <p class="redeem-hint" :class="{ warn: !!codeNotice }">{{ codeNotice || '会员时长 · 积分 · 兑换码，自动识别' }}</p>

  <button class="au-btn au-btn-ghost au-btn-sm refresh" title="刷新" @click="() => loadAll()">
    <RefreshCw :size="14" :class="{ spinning: loading }" />
  </button>
</form>

    <!-- 选项卡 -->
    <nav class="tabs au-anim-up" style="animation-delay: 100ms">
      <button class="tab" :class="{ active: tab === 'orders' }" @click="tab = 'orders'">
        <Receipt :size="15" /> 订单
      </button>
      <button class="tab" :class="{ active: tab === 'log' }" @click="tab = 'log'">
        <ArrowDownLeft :size="15" /> 流水
      </button>
    </nav>

    <!-- 订单 -->
    <section v-if="tab === 'orders'" class="tab-body au-anim-up">
      <div v-if="!orders.length" class="au-empty">
        <Receipt :size="30" />
        <p>还没有订单记录</p>
      </div>
      <div v-else class="order-list au-card">
        <div v-for="o in orders" :key="o.order_id" class="order-item">
          <span class="order-icon" :class="{ pending: o.status === 'pending', refunded: o.status === 'refunded' }">
            <Clock v-if="o.status === 'pending'" :size="14" />
            <CircleCheck v-else-if="o.status === 'paid'" :size="14" />
            <Undo2 v-else-if="o.status === 'refunded'" :size="14" />
            <CircleAlert v-else :size="14" />
          </span>
          <div class="order-main">
            <span class="order-name">{{ o.item_name }}</span>
            <span class="order-sub">
              <span class="order-id mono">{{ o.order_id }}</span>
              <span class="order-sep">·</span>
              <span>{{ fmtTime(o.created_at) }}</span>
            </span>
            <span v-if="o.status === 'refunded' && o.refund_reason" class="order-sub order-refund">
              退款原因：{{ o.refund_reason }}
            </span>
            <span v-if="(o.discount_amount || 0) > 0" class="order-sub order-coupon">
              <Percent :size="11" />
              优惠码 {{ o.coupon_code || '已用券' }} 已减 ¥{{ (o.discount_amount || 0).toFixed(2) }}
            </span>
          </div>
          <div class="order-side">
            <span class="order-amount">
              <em v-if="(o.discount_amount || 0) > 0" class="price-was">¥{{ (o.list_price || 0).toFixed(2) }}</em>
              ¥{{ o.amount.toFixed(2) }}
            </span>
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

    <!-- 活力值续活弹窗 -->
    <div v-if="showRechargeVitality" class="result-mask" @click.self="showRechargeVitality = false">
      <div class="result-card vitality-dialog">
        <h3 class="result-title">用积分续活力</h3>
        <p class="dialog-note">1 点活力 = {{ vitalityPointCost }} 积分（当前 {{ vitality?.vitality }}/{{ vitality?.max }}）</p>
        <div class="qty-row">
          <button v-for="n in [1,3,7,14]" :key="n" type="button" class="qty-btn" :class="{ active: rechargeQty === n }" @click="rechargeQty = n">+{{ n }}</button>
        </div>
        <p class="dialog-note">将消耗 {{ rechargeQty * vitalityPointCost }} 积分</p>
        <div class="dialog-actions">
          <button type="button" class="au-btn" @click="showRechargeVitality = false">取消</button>
          <button type="button" class="au-btn au-btn-primary" :disabled="recharging" @click="doRechargeVitality">{{ recharging ? '处理中…' : '确认续活' }}</button>
        </div>
      </div>
    </div>
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
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  position: relative;
  overflow: hidden;
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
  font-family: var(--au-font-serif);
  font-size: 2.75rem;
  font-weight: 700;
  color: var(--au-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.balance-num .unit { font-size: 0.875rem; color: var(--au-text-3); }

.balance-note {
  margin: 0.5rem 0 0;
  font-size: 0.8125rem;
  color: var(--au-text-3);
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
  border: 1px solid var(--au-warning-border);
  border-radius: var(--au-r-full);
  color: var(--au-warning);
  font-size: 0.8125rem;
  text-decoration: none;
  transition: all var(--au-fast) var(--au-ease);
}
.checkin-pill strong { font-weight: 700; }
.checkin-pill.done {
  background: var(--au-success-soft);
  border-color: var(--au-success-border);
  color: var(--au-success);
}

/* ==================== 会员等级（P1 统一货币体系） ==================== */
.member-row {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  margin-top: 0.75rem;
  padding: 0.75rem 0.875rem;
  background: var(--au-surface-2, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
}
.member-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 50%;
  color: #fff;
  flex-shrink: 0;
  /* 暗房质感：内高光 + 边框（具体背景/光晕由 badgeStyle() 行内设置） */
  border: 1px solid rgba(255, 255, 255, 0.18);
}
/* 传奇档：缓慢呼吸光晕，影殿不朽的气场（传奇固定为 #eab308 金） */
.member-badge[data-tier="legend"] {
  animation: badge-breathe 3.2s ease-in-out infinite;
}
@keyframes badge-breathe {
  0%, 100% { box-shadow: 0 2px 8px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.25), 0 0 10px #eab30866; }
  50% { box-shadow: 0 2px 8px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.25), 0 0 22px #eab30899; }
}
@media (prefers-reduced-motion: reduce) {
  .member-badge[data-tier="legend"] { animation: none; }
}
.member-badge.sm { width: 2rem; height: 2rem; }
.member-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.375rem; }
.member-top { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.member-name { font-size: 0.9375rem; color: var(--au-text); }
.member-xp { font-size: 0.75rem; color: var(--au-text-3); font-variant-numeric: tabular-nums; }
.member-bar {
  height: 0.375rem;
  border-radius: var(--au-r-full);
  background: var(--au-border);
  overflow: hidden;
}
.member-bar i {
  display: block;
  height: 100%;
  border-radius: var(--au-r-full);
  background: linear-gradient(90deg, var(--au-primary), var(--au-gold-b));
  transition: width 0.5s var(--au-ease);
}
.member-next {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
}
.member-levels-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  background: none;
  border: none;
  padding: 0;
  font-size: 0.75rem;
  color: var(--au-primary);
  cursor: pointer;
}
.member-levels-toggle .rotated { transform: rotate(90deg); }

/* 全等级权益卡片 */
.levels-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem;
  margin-top: 0.75rem;
}
.level-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.875rem;
  background: var(--au-surface-2, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  /* 顶部等级色带：暗房影院的色带感（颜色由行内 borderTopColor 按等级设置） */
  border-top-width: 2px;
}
.level-card.current {
  border-color: var(--au-primary);
  box-shadow: 0 0 0 1px var(--au-primary);
}
.level-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.level-head strong { font-size: 0.875rem; color: var(--au-text); }
.level-th { font-size: 0.75rem; color: var(--au-text-3); white-space: nowrap; }
.level-benefits {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.8125rem;
  color: var(--au-text-2);
}
.level-benefits li::before {
  content: '·';
  margin-right: 0.375rem;
  color: var(--au-primary);
}
.checkin-pill:hover {
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
  font-size: 0.8125rem;
  color: var(--au-text-3);
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
  background: var(--au-primary);
  color: var(--au-on-primary);
}

/* ==================== 支付方式 ==================== */
.pay-methods { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.pay-methods-label { font-size: 0.8125rem; color: var(--au-text-3); }

/* ==================== 折后价（v2.10.0；券入口已收进核销面板） ==================== */
/* 原价删除线 + 实付价（选择器带上父级，盖过 .plan-price em 的旧规则） */
.pkg-price .price-was,
.plan-price .price-was,
.order-amount .price-was {
  margin-right: 0.375rem;
  font-style: normal;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--au-text-3);
  text-decoration: line-through;
}

.order-coupon { color: var(--au-primary); }
.order-coupon svg { flex-shrink: 0; }
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
  background: var(--au-surface-2);
}
.pkg-row.popular { border-color: var(--au-primary); }
.pkg-row:disabled { opacity: 0.6; cursor: wait; }

/* 首载骨架行：占位不闪空态；不可点、无 hover */
.pkg-row-skeleton { cursor: default; pointer-events: none; opacity: 0.6; }
.skel-num { letter-spacing: 0.1em; }
.pkg-row-skeleton strong,
.pkg-row-skeleton .pkg-price {
  background: linear-gradient(90deg, var(--au-border) 25%, var(--au-surface) 50%, var(--au-border) 75%);
  background-size: 200% 100%;
  animation: skel-slide 1.2s linear infinite;
  border-radius: var(--au-r-sm);
  color: transparent;
}
@keyframes skel-slide { to { background-position: -200% 0; } }

.pkg-points-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.1875rem;
  min-width: 0;
}

.pkg-points { display: flex; align-items: baseline; gap: 0.3125rem; }
.pkg-points strong {
  font-family: var(--au-font-serif);
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--au-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}
.pkg-points em { font-style: normal; font-size: 0.8125rem; color: var(--au-text-3); }

.pkg-name { font-size: 0.8125rem; color: var(--au-text-3); }

.pkg-bonus {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.8125rem;
  color: var(--au-success);
}

.pkg-buy {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  flex-shrink: 0;
}

.pkg-pop-tag {
  padding: 0.0625rem 0.4375rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  color: var(--au-primary);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  border-radius: var(--au-r-full);
}

.pkg-price {
  font-family: var(--au-font-serif);
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--au-text);
  font-variant-numeric: tabular-nums lining-nums;
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
  background: var(--au-primary);
  border-color: transparent;
  color: var(--au-on-primary);
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
  font-size: 0.8125rem;
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
  font-size: 0.8125rem;
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
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  color: var(--au-text-3, var(--au-text-2));
  font-size: 0.8125rem;
  text-align: left;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}
.code-tip svg { color: var(--au-primary); flex-shrink: 0; }
.code-tip span { flex: 1; min-width: 0; }
.code-tip .ct-arrow { color: var(--au-text-3); }
.code-tip:hover {
  border-color: var(--au-primary-border);
  color: var(--au-text-2);
}

.member-status.warn {
  background: var(--au-warning-soft);
  border-color: var(--au-warning-soft);
}

.member-status.warn svg,
.member-status.warn .ms-warn {
  color: var(--au-warning);
}

.ms-warn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.8125rem;
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
  border-color: var(--au-warning-border);
}

.member-status.inactive svg {
  color: var(--au-warning);
}

.ms-sep {
  color: var(--au-text-3);
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
.plan-card.popular { border-color: var(--au-primary); }

.pop-pill {
  display: inline-flex;
  align-items: center;
  height: 20px;
  margin-left: 0.375rem;
  padding: 0 0.4375rem;
  border-radius: var(--au-r-full);
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  color: var(--au-primary);
  font-family: var(--au-font-sans);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  vertical-align: 2px;
}

.plan-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}
.plan-name { margin: 0; font-family: var(--au-font-serif); font-size: 1.0625rem; font-weight: 700; color: var(--au-text); }
/* 归属服：多服运营下同一页会列出几个服的套餐，买哪份要看得清 */
.plan-realm {
  display: inline-block;
  margin-left: 0.375rem;
  padding: 0.0625rem 0.4375rem;
  border-radius: 999px;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  color: var(--au-text-3);
  font-size: 0.8125rem;
  font-weight: 500;
  font-style: normal;
  vertical-align: middle;
}

.plan-price {
  font-family: var(--au-font-serif);
  font-size: 1.375rem;
  font-weight: 700;
  color: var(--au-text);
  white-space: nowrap;
  font-variant-numeric: tabular-nums lining-nums;
}
.plan-price em { font-family: var(--au-font-sans); font-style: normal; font-size: 0.8125rem; font-weight: 400; color: var(--au-text-3); }

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

/* P2 双轨订阅：人民币/积分双按钮 */
.plan-actions { display: flex; flex-direction: column; gap: 8px; margin-top: auto; }
.plan-actions .plan-btn { margin-top: 0; }
.plan-points-price {
  display: inline-block;
  margin-left: 8px;
  font-size: 0.75rem;
  color: var(--au-warning);
  font-weight: 600;
}

/* P2 自定义金额充值 */
.custom-recharge { margin-top: 16px; padding: 16px; }
.custom-recharge-head {
  display: flex; align-items: center; gap: 8px;
  font-weight: 600; font-size: 0.9rem; margin-bottom: 12px;
}
.custom-recharge-body { display: flex; gap: 12px; align-items: center; }
.custom-input-wrap {
  display: flex; align-items: center; flex: 1;
  border: 1px solid var(--au-border);
  border-radius: 8px; padding: 0 12px;
  background: var(--au-surface-2);
}
.custom-prefix { color: var(--au-text-3); margin-right: 6px; font-weight: 600; }
.custom-input {
  flex: 1; border: none; outline: none; background: transparent;
  padding: 10px 0; font-size: 1rem; color: var(--au-text);
  -moz-appearance: textfield;
}
.custom-input::-webkit-outer-spin-button,
.custom-input::-webkit-inner-spin-button { -webkit-appearance: none; }
.custom-hint { margin: 10px 0 0; font-size: 0.75rem; color: var(--au-text-3); }

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
.order-icon.refunded {
  color: var(--au-danger);
  background: var(--au-danger-soft);
}

.order-refund {
  color: var(--au-danger);
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
  font-size: 0.8125rem;
  color: var(--au-text-3);
  overflow: hidden;
}
.order-id { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.order-sep { opacity: 0.5; }

.order-side { display: flex; flex-direction: column; align-items: flex-end; gap: 0.3125rem; flex-shrink: 0; }
.order-amount { font-family: var(--au-font-serif); font-size: 1rem; font-weight: 700; color: var(--au-text); font-variant-numeric: tabular-nums lining-nums; }

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
.log-time { font-size: 0.8125rem; color: var(--au-text-3); }

.log-amount { font-weight: 700; font-size: 0.9375rem; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.log-amount.in { color: var(--au-success); }
.log-amount.out { color: var(--au-danger); }

.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

/* ==================== 活力值 ==================== */
.vitality-row { display: flex; align-items: center; gap: 0.75rem; margin-top: 0.75rem; padding: 0.625rem 0.875rem; border: 1px solid var(--au-border); border-radius: var(--au-r-lg); background: var(--au-surface-2); }
.vitality-icon { color: var(--au-warning, #f59e0b); display: inline-flex; flex-shrink: 0; }
.vitality-meta { flex: 1; min-width: 0; }
.vitality-top { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem; font-size: 0.8125rem; margin-bottom: 0.375rem; }
.vitality-warn { color: var(--au-danger, #ef4444); font-size: 0.75rem; }
.vitality-ok { color: var(--au-text-3); font-size: 0.75rem; }
.vitality-recharge-btn { flex-shrink: 0; padding: 0.375rem 0.75rem; border-radius: var(--au-r-full); border: 1px solid var(--au-primary); color: var(--au-primary); background: transparent; font-size: 0.75rem; font-weight: 700; cursor: pointer; }
.vitality-recharge-btn:hover { background: var(--au-primary-soft); }
.vitality-dialog { align-items: stretch; text-align: left; }
.dialog-note { margin: 0; font-size: 0.8125rem; color: var(--au-text-2); }
.dialog-actions { display: flex; gap: 0.75rem; justify-content: flex-end; margin-top: 1rem; }
.qty-row { display: flex; gap: 0.5rem; margin: 0.75rem 0; }
.qty-btn { padding: 0.5rem 1rem; border-radius: var(--au-r-full); border: 1px solid var(--au-border); background: var(--au-surface-2); color: var(--au-text); cursor: pointer; font-weight: 700; }
.qty-btn.active { border-color: var(--au-primary); color: var(--au-primary); }

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
