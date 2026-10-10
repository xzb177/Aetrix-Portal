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
  type PointsLogEntry, type TransferConfig,
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

// ===== 积分转账（C2）=====
const transferConfig = ref<TransferConfig | null>(null)
const transferRecipient = ref('')
const transferAmount = ref<number | null>(null)
const transferring = ref(false)
/** 手续费预览：向上取整 */
const transferFeePreview = computed(() => {
  if (transferAmount.value == null || transferAmount.value <= 0 || !transferConfig.value) return 0
  const pct = transferConfig.value.fee_pct
  return pct > 0 ? Math.ceil(transferAmount.value * pct / 100) : 0
})
async function loadTransferConfig() {
  try { transferConfig.value = await pointsApi.transferConfig() }
  catch { transferConfig.value = null }
}
async function handleTransfer() {
  const to = transferRecipient.value.trim()
  const amt = transferAmount.value
  if (!to) { toast.error('请输入对方用户名'); return }
  if (!amt || amt <= 0 || !Number.isInteger(amt)) { toast.error('请输入正整数金额'); return }
  transferring.value = true
  try {
    const res = await pointsApi.transfer(to, amt)
    toast.success(`已转给 ${res.recipient} ${res.amount} 积分` + (res.fee > 0 ? `（手续费 ${res.fee} 积分）` : ''))
    transferRecipient.value = ''
    transferAmount.value = null
    balance.value = res.balance
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || '转账失败')
  } finally {
    transferring.value = false
  }
}

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
  transfer_out: { label: '转账转出', income: false },
  transfer_in: { label: '转账转入', income: true },
  transfer_fee: { label: '转账手续费', income: false },
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
  loadTransferConfig()
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
      <div class="bh-divider"></div>

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
    </section>

    <!-- 积分转账（C2）：开关关闭时隐藏 -->
    <section v-if="transferConfig?.enabled" class="au-card transfer-card au-anim-up">
      <div class="transfer-head">
        <ArrowUpRight :size="15" />
        <strong>积分转账</strong>
        <span class="transfer-fee-note">手续费 {{ transferConfig.fee_pct }}%</span>
      </div>
      <div class="transfer-row">
        <input v-model="transferRecipient" class="redeem-input" placeholder="对方用户名" maxlength="50" />
        <input v-model.number="transferAmount" type="number" min="1" class="redeem-input" placeholder="转账金额（积分）" />
        <button class="au-btn au-btn-primary" :disabled="transferring" @click="handleTransfer">
          <span v-if="transferring" class="spinner"></span>
          转账
        </button>
      </div>
      <p class="redeem-hint" v-if="transferFeePreview > 0">
        将扣除 <span class="nw">{{ (transferAmount || 0) }} 积分</span> + <span class="nw">手续费 {{ transferFeePreview }} 积分</span>
      </p>
      <p class="redeem-hint" v-else>输入金额后显示手续费</p>
    </section>

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
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr);
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

/* ==================== 订单原价删除线 ==================== */
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
  .order-item { flex-wrap: wrap; }
}

/* 积分转账卡片（C2） */
.transfer-card { margin-top: 16px; padding: 16px; }
.transfer-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.transfer-head strong { font-size: 15px; }
.transfer-fee-note { margin-left: auto; font-size: 12px; color: var(--au-text-3); white-space: nowrap; }
.transfer-row { display: flex; gap: 8px; }
.transfer-row .redeem-input { flex: 1; min-width: 0; }
.nw { white-space: nowrap; }
@media (max-width: 768px) {
  .transfer-row { flex-direction: column; }
}

</style>
