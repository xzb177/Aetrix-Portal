<script setup lang="ts">
/**
 * 商店 — 充积分 / 买会员 / 花积分 / 核销（卡码·兑换码·优惠券）
 * 布局：套餐卡横向结构化行；核销面板固定在底部
 *
 * v2.11.0：从 WalletView 拆分。订单记录、积分流水、余额总览、会员等级
 * 搬去钱包页；本页只留「花钱 / 花积分」的入口。优惠券试算不再跟随分页
 * （本页无分页），改为两类商品同时试算、数据刷新后静默重算。
 */
import { ref, computed, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  Coins, TicketCheck, Sparkles, Zap, Crown, Flame, ExternalLink, ChevronRight,
  CircleCheck, CircleAlert, TriangleAlert, X, Percent,
} from 'lucide-vue-next'
import {
  pointsApi, exchangeApi, paymentApi, membershipApi, couponApi, currencyApi,
  vitalityApi, memberApi,
  type RechargePackage, type SubscriptionPlan,
  type OrderRow, type PaymentMethod, type CodePreview, type CouponQuote,
  type VitalityStatus, type PointsLogEntry, type MyMemberInfo,
} from '@/api/economy'
import { subscriptionApi, isExpiringSoon, type MySubscription } from '@/api'
import { useToast } from '@/composables/useToast'
import { tgApi, type TgBindStatus } from '@/api/tg'
import TgBindCard from '@/components/TgBindCard.vue'

const toast = useToast()
const route = useRoute()
const userStore = useUserStore()

// ===== 状态 =====
const loading = ref(true)
const balance = ref(0)
/** 活力值（仅公益服用户有值） */
const vitality = ref<VitalityStatus | null>(null)
/** 会员等级（含订阅折扣） */
const member = ref<MyMemberInfo | null>(null)
const rechargeQty = ref(1)
const recharging = ref(false)
const vitalityPointCost = ref(10)
const packages = ref<RechargePackage[]>([])
const plans = ref<SubscriptionPlan[]>([])
const methods = ref<PaymentMethod[]>([])

const payMethod = ref('alipay')
const orderLoading = ref<number | null>(null)

// ===== 优惠券（v2.10.0；v2.10.1 收进统一核销入口）=====
// 优惠额度是按「商品」算的（同一张 9 折券，100 元的包和 30 元的会员省得不一样），
// 所以应用时对商品各试算一次，行内直接显示折后价；下单时后端会再算一遍。
const couponEnabled = ref(true)
const couponApplied = ref('')          // 已生效的码（空 = 没在用券）
const couponLoading = ref(false)
const couponError = ref('')
const couponQuotes = ref<Record<string, CouponQuote>>({})

/** 一次试算的结果：用不了的商品带上后端给的说明（满减门槛、适用范围等） */
interface QuoteRow {
  key: string
  quote: CouponQuote | null
  detail?: unknown
}

const quoteOf = (kind: 'recharge' | 'subscription', id: number) => couponQuotes.value[`${kind}:${id}`] || null
/** 折后实付（未用券 = 原价），模板里直接取字符串，避免到处写非空断言 */
const paidPrice = (kind: 'recharge' | 'subscription', id: number, price: number) =>
  (quoteOf(kind, id)?.paid_amount ?? price).toFixed(2)
const wasPrice = (kind: 'recharge' | 'subscription', id: number) => {
  const q = quoteOf(kind, id)
  return q ? q.list_price.toFixed(2) : ''
}
const couponSavings = computed(() => {
  const values = Object.values(couponQuotes.value)
  return values.length ? Math.max(...values.map((q) => q.discount_amount)) : 0
})

// 核销面板下面那一行：出错（券用不了 / 邀请码指引 / 卡码无效）优先，其次才是默认口径
const redeemNotice = computed(() => couponError.value || codeNotice.value)
const redeemHint = computed(() => {
  if (couponApplied.value) return '下单时按折后价支付，关单或退款后优惠次数自动退回'
  return '会员时长 · 积分 · 订阅 · 优惠券，自动识别'
})

function clearCoupon() {
  couponApplied.value = ''
  couponError.value = ''
  couponQuotes.value = {}
}

/** 一类商品的试算清单（券是按商品算的，所以先算用户眼前这一页） */
function couponTargets(kind: 'recharge' | 'subscription') {
  return kind === 'subscription'
    ? plans.value.map((p) => ({ kind: 'subscription' as const, id: p.id }))
    : packages.value.map((p) => ({ kind: 'recharge' as const, id: p.id }))
}

async function quoteCoupon(code: string, kind: 'recharge' | 'subscription'): Promise<QuoteRow[]> {
  return await Promise.all(couponTargets(kind).map(async (t): Promise<QuoteRow> => {
    try {
      return {
        key: `${t.kind}:${t.id}`,
        quote: await couponApi.quote({ code, kind: t.kind, item_id: t.id }),
      }
    } catch (err: any) {
      return { key: `${t.kind}:${t.id}`, quote: null, detail: err?.response?.data?.detail }
    }
  }))
}

/**
 * 试算并应用优惠券
 *
 * silent：不弹 toast（数据刷新自动重算时不打扰用户）
 *
 * 本页没有分页，两类商品同时试算：券可能只适用于充值包或只适用于会员套餐，
 * 任一命中即应用，两类的折后价合并进 couponQuotes。
 */
async function applyCoupon(code: string, { silent = false } = {}) {
  const text = (code || '').trim()
  couponError.value = ''
  if (!text) {
    clearCoupon()
    return
  }
  couponLoading.value = true
  try {
    // 公益服没有会员可卖，就不去试订阅了
    const kinds: Array<'recharge' | 'subscription'> = isFreeRealm.value
      ? ['recharge']
      : ['recharge', 'subscription']

    const allRows = (await Promise.all(kinds.map((k) => quoteCoupon(text, k)))).flat()
    const valid = allRows.filter((r) => r.quote)

    if (!valid.length) {
      const detail = allRows.find((r) => r.detail)?.detail
      couponApplied.value = ''
      couponQuotes.value = {}
      couponError.value = typeof detail === 'string'
        ? detail
        : (allRows.length ? '优惠码不可用' : '暂无可购买的商品')
      if (!silent) toast.error(couponError.value)
      return
    }

    couponQuotes.value = Object.fromEntries(valid.map((r) => [r.key, r.quote as CouponQuote]))
    couponApplied.value = valid[0].quote!.code
    // 有些商品不满足这张券（如满减门槛）：说清楚，不默默只给一部分打折
    const skipped = allRows.length - valid.length
    if (skipped > 0) {
      couponError.value = `已应用，但有 ${skipped} 个商品不满足该券条件（原价购买）`
    }
    if (!silent) toast.success(`已应用「${couponApplied.value}」`)
  } finally {
    couponLoading.value = false
  }
}

// ===== 功能开关（管理端可关；关闭时给出提示，不让用户白提交）=====
const rechargeEnabled = ref(true)
const plansEnabled = ref(true)
const exchangeEnabled = ref(true)

// ===== 公益服（v2.7.0）：这个服免费开放，不需要买会员 =====
// 后端 /payment/plans 会下发当前服的接入方式；公益服一律不展示套餐与购买引导，
// 否则用户会以为“不买就看不了”，而实际上他本来就能看。
const isFreeRealm = ref(false)
const realmNote = ref('')

// ===== 当前会员（订阅区顶部状态行）=====
const subscriptions = ref<MySubscription[]>([])
const currentSub = computed(
  () => subscriptions.value.find((s) => s.status === 'active' && s.days_left > 0) || null,
)
// 临期：与后台到期提醒同口径（默认 7 天）——商店页本来就是续费的地方，
// 剩余天数不多时直接把状态行染成警示色，别再让用户自己数天数
const subExpiringSoon = computed(() => isExpiringSoon(currentSub.value))

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

async function handleRedeem() {
  const code = redeemCode.value.trim()
  if (!code) {
    toast.error('请输入卡码、兑换码或优惠券')
    return
  }
  redeemLoading.value = true
  codePreview.value = null
  codeNotice.value = ''
  try {
    const preview = await membershipApi.preview(code)

    if (preview.kind === 'coupon') {
      // 优惠券不核销，是「按商品试算折扣」：同一入口，只是后续动作不同
      if (!preview.valid) {
        codeNotice.value = preview.message || '该优惠券已停用'
        return
      }
      if (!couponEnabled.value) {
        codeNotice.value = '管理员已关闭优惠券，如有券请稍后再试'
        return
      }
      await applyCoupon(code)
      // 用上了就清空输入：已应用的码就在面板里写着，不必再占着输入框
      if (couponApplied.value) redeemCode.value = ''
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
async function handleOrder(kind: 'recharge' | 'subscription', itemId?: number) {
  orderLoading.value = itemId
  try {
    // 优惠码在试算通过的商品上才带：后端会按同一套口径再算一遍并占额度
    const quote = quoteOf(kind, itemId)
    const res = await paymentApi.createOrder({
      kind,
      item_id: itemId,
      payment_method: payMethod.value,
      coupon_code: quote ? quote.code : undefined,
    })
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

// ===== 自定义金额充值（P2）=====
const customAmount = ref<number | null>(null)
const rechargeRatio = ref(1.2)
const canCustomRecharge = computed(() => (customAmount.value ?? 0) >= 1)
const customPointsPreview = computed(() => {
  const amt = customAmount.value ?? 0
  if (amt < 1) return ''
  return ` ${Math.floor(amt * rechargeRatio.value)} `
})
async function handleCustomRecharge() {
  const amt = customAmount.value ?? 0
  if (amt < 1 || amt > 100000) { toast.error('请输入 1~100000 元'); return }
  orderLoading.value = -1
  try {
    const res = await paymentApi.createOrder({ kind: 'recharge', payment_method: payMethod.value, custom_amount: amt })
    if (res.pay_url) { toast.success('正在跳转支付…'); window.location.href = res.pay_url }
    else toast.error('未获取到支付链接')
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || '下单失败，请稍后重试')
  } finally { orderLoading.value = null }
}
// ===== 数据加载 =====
async function refreshBalance() {
  try {
    // 只取余额：流水明细在钱包页展示
    const res = await pointsApi.log({ limit: 1 })
    balance.value = res.balance
  } catch { /* 静默 */ }
}

/** 活力值：用积分续活力（花积分区卡片直接操作，无弹窗） */
async function doRechargeVitality() {
  recharging.value = true
  try {
    const r = await vitalityApi.recharge(rechargeQty.value * vitalityPointCost.value)
    if (vitality.value) vitality.value.vitality = r.vitality
    balance.value = r.points_balance
    toast.success('续命成功')
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
  // silent = true 时为 KeepAlive 切回 tab 的后台静默刷新：不碰 loading，
  // 不闪骨架屏，数据到了直接更新视图
  if (!silent) loading.value = true
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
    const emptyLogs = { total: 0, balance: 0, logs: [] as PointsLogEntry[] }
    const emptySubs: MySubscription[] = []
    const couponFallback = { enabled: false }
    const [pkgR, planR, methodR, logR, subsR, couponR, vitalityR, memberR] = await Promise.allSettled([
      paymentApi.packages(),
      paymentApi.plans(),
      paymentApi.methods(),
      pointsApi.log({ limit: 1 }),
      subscriptionApi.getMine(),
      // 接口失败时按「关闭」处理：宁可不展示，也不让用户填完码才报错
      couponApi.config(),
      // 活力值：非公益服用户 403，兜底为 null 不展示
      vitalityApi.status(),
      // 会员等级：失败时走 settled 兜底为 null，不展示折扣
      memberApi.info(),
    ])
    const pkg = settled(pkgR, emptyPkgs, silent)
    if (pkg !== undefined) {
      packages.value = pkg.packages || []
      rechargeEnabled.value = pkg.enabled !== false
    }
    const plan = settled(planR, emptyPlans, silent)
    if (plan !== undefined) {
      plans.value = plan.plans || []
      isFreeRealm.value = plan.is_free === true || plan.access_mode === 'free'
      realmNote.value = plan.access_note || ''
      plansEnabled.value = plan.enabled !== false
    }
    const methodList = settled(methodR, emptyMethods, silent)
    if (methodList !== undefined) methods.value = Array.isArray(methodList) ? methodList : []
    const logData = settled(logR, emptyLogs, silent)
    if (logData !== undefined) balance.value = logData.balance
    const subs = settled(subsR, emptySubs, silent)
    if (subs !== undefined) subscriptions.value = Array.isArray(subs) ? subs : []
    const couponCfg = settled(couponR, couponFallback, silent)
    if (couponCfg !== undefined) couponEnabled.value = couponCfg.enabled === true
    const vitalityData = vitalityR.status === 'fulfilled' ? vitalityR.value : null
    vitality.value = vitalityData && vitalityData.success ? vitalityData : null
    const memberData = settled(memberR, null, silent)
    if (memberData !== undefined) member.value = memberData

    // 商品与价格回来后，已应用的券要按最新价格重算一次
    // （替代原来的 watch(tab)：本页没有分页，只在数据刷新时重算）
    if (couponApplied.value) void applyCoupon(couponApplied.value, { silent: true })
  } finally {
    loading.value = false
    hasLoaded.value = true
  }
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
  // paidBefore 基准：轮询前先拉一次订单，区分「以前就支付过的」和「新到账的」
  let paidBefore = new Set<string>()
  try {
    const base = await paymentApi.orders({ limit: 20 })
    paidBefore = new Set(
      (base.orders || []).filter((o) => o.status === 'paid').map((o) => o.order_id),
    )
  } catch {
    /* 拉取失败则按空集处理，任何已支付订单都会被视为新到账 */
  }
  let attempts = 0
  payPolling.value = true

  payPollTimer = window.setInterval(async () => {
    attempts += 1
    try {
      const res = await paymentApi.orders({ limit: 20 })
      const list: OrderRow[] = res.orders || []

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

/** 进入时的 query 处理：?order= / ?paid=1 触发支付到账轮询。
 * KeepAlive 下 query 变化不再触发重建，所以 onMounted / onActivated 都要走这里；
 * 用 lastHandledEntry 去重，避免同一笔订单反复弹"支付已提交"。 */
const lastHandledEntry = ref('')
function handleEntryQuery() {
  const entryKey = `${String(route.query.order ?? '')}|${String(route.query.paid ?? '')}`
  if ((paidFlag.value || route.query.order) && !payPolling.value && entryKey !== lastHandledEntry.value) {
    lastHandledEntry.value = entryKey
    toast.info('支付已提交，正在确认到账结果…', 4000)
    pollPaymentResult()
  }
}

onMounted(async () => {
  await loadAll()
  handleEntryQuery()
  // P2：拉取充值比例（自定义金额换算用），失败时保持默认 1.2
  try {
    const info = await currencyApi.info()
    if (info?.recharge_ratio) rechargeRatio.value = info.recharge_ratio
  } catch { /* 静默 */ }
  tgApi.status().then(s => { tgStatus.value = s }).catch(() => {})
})

// 从别的 tab 切回来（KeepAlive 缓存命中）：先处理 query，再后台静默刷新
onActivated(() => {
  handleEntryQuery()
  if (hasLoaded.value) void loadAll(true)
})

onBeforeUnmount(stopPayPoll)
const tgStatus = ref<TgBindStatus | null>(null)
const showTgBanner = computed(() => !!tgStatus.value && tgStatus.value.required && !tgStatus.value.bound && !tgStatus.value.in_grace)
</script>

<template>
  <div class="au-page store-view">
    <TgBindCard v-if="showTgBanner" compact class="tg-banner" />

    <header class="store-head au-anim-up">
      <div class="sh-title"><h1>商店</h1><p>{{ isFreeRealm ? '积分当钱花，全部免费玩' : '充值积分，开通会员' }}</p></div>
      <RouterLink to="/wallet" class="balance-pill"><Sparkles :size="13" /><span>{{ balance }} 积分</span><ChevronRight :size="12" /></RouterLink>
    </header>

    <!-- 充积分区 -->
    <section class="store-group au-card au-anim-up">
      <div class="group-head"><h2><Coins :size="16" /> 充积分</h2><p class="group-desc">用人民币购买积分</p></div>

      <div v-if="!rechargeEnabled" class="au-empty">
        <CircleAlert :size="30" />
        <p>充值通道暂未开启，可先通过签到、邀请或兑换获取积分</p>
      </div>
      <div v-else-if="loading && !packages.length" class="pkg-list" aria-hidden="true">
        <div v-for="i in 3" :key="i" class="pkg-row pkg-row-skeleton">
          <span class="pkg-points-wrap">
            <span class="pkg-points"><strong class="skel-num">···</strong><em>积分</em></span>
          </span>
          <span class="pkg-buy"><span class="pkg-price">¥··</span></span>
        </div>
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
            <span class="pkg-price">
              <em v-if="wasPrice('recharge', p.id)" class="price-was">¥{{ wasPrice('recharge', p.id) }}</em>
              ¥{{ paidPrice('recharge', p.id, p.price) }}
            </span>
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

      <!-- 自定义金额充值：按 recharge_ratio 换算积分 -->
      <div class="custom-recharge au-card">
        <div class="custom-recharge-head">
          <Coins :size="15" />
          <span>自定义金额充值</span>
        </div>
        <div class="custom-recharge-body">
          <div class="custom-input-wrap">
            <span class="custom-prefix">¥</span>
            <input v-model.number="customAmount" type="number" min="1" max="100000" placeholder="输入金额" class="custom-input" />
          </div>
          <button class="au-btn au-btn-primary" :disabled="!canCustomRecharge || orderLoading === -1" @click="handleCustomRecharge">
            <span v-if="orderLoading === -1" class="au-spinner spinner-sm" />
            <template v-else>充值{{ customPointsPreview }}积分</template>
          </button>
        </div>
        <p class="custom-hint">按当前比例 {{ rechargeRatio }} 兑换（1 元 = {{ rechargeRatio }} 积分）</p>
      </div>

      <!-- 支付方式：收进本区底部 -->
      <div v-if="methods.length" class="pay-methods">
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
    </section>

    <!-- 买会员区 -->
    <section class="store-group au-card au-anim-up">
      <div class="group-head"><h2><Zap :size="16" /> 买会员</h2><p class="group-desc">人民币开通会员，解锁全库播放</p></div>

      <div v-if="isFreeRealm" class="free-line"><Sparkles :size="13" /><span>公益服免费开放，无需购买会员</span></div>

      <template v-else>
        <!-- 当前会员状态条 -->
        <div v-if="plansEnabled" class="member-status" :class="{ inactive: !currentSub, warn: subExpiringSoon }">
          <Crown :size="15" />
          <template v-if="currentSub">
            <span>当前会员：<strong>{{ currentSub.plan_name }}</strong></span>
            <span class="ms-sep">·</span>
            <span>剩 <strong>{{ currentSub.days_left }}</strong> 天（{{ currentSub.end_date?.slice(0, 10) }} 到期）</span>
            <span v-if="subExpiringSoon" class="ms-warn">
              <TriangleAlert :size="13" />
              即将到期，现在续费可无缝接续
            </span>
          </template>
          <span v-else>当前未开通会员，选择套餐即可解锁全库播放</span>
        </div>

        <div v-if="!plansEnabled" class="au-empty">
          <CircleAlert :size="30" />
          <p>订阅购买暂未开启，可联系管理员换用卡码开通</p>
        </div>
        <div v-else-if="!plans.length" class="au-empty">
          <Zap :size="30" />
          <p>暂无可购买套餐，请联系管理员开通</p>
        </div>
        <div v-else class="plan-grid">
          <div v-for="p in plans" :key="p.id" class="plan-card" :class="{ popular: p.is_popular }">
            <div class="plan-head">
              <h4 class="plan-name">
                {{ p.name }}
                <span v-if="p.is_popular" class="pop-pill">推荐</span>
                <em v-if="p.realm_name" class="plan-realm">{{ p.realm_name }}</em>
              </h4>
              <span class="plan-price">
                <em v-if="wasPrice('subscription', p.id)" class="price-was">¥{{ wasPrice('subscription', p.id) }}</em>
                ¥{{ paidPrice('subscription', p.id, p.price) }}
                <em class="plan-days">/ {{ p.duration_days }} 天</em>
              </span>
            </div>
            <p v-if="(member?.discount_pct || 0) > 0" class="plan-member-hint">
              <Percent :size="12" /> 会员 {{ (100 - (member?.discount_pct || 0)) / 10 }} 折，下单自动抵扣
            </p>
            <p class="plan-desc">{{ p.description || '会员专属权益' }}</p>

            <ul v-if="p.features && p.features.length" class="plan-features">
              <li v-for="(f, i) in p.features" :key="i">
                <CircleCheck :size="13" /> {{ f }}
              </li>
            </ul>

            <div class="plan-actions">
              <button
                class="au-btn plan-btn"
                :class="p.is_popular ? 'au-btn-primary' : 'au-btn-ghost'"
                :disabled="orderLoading === p.id"
                @click="handleOrder('subscription', p.id)"
              >
                <span v-if="orderLoading === p.id" class="au-spinner spinner-sm" />
                <template v-else>¥{{ paidPrice('subscription', p.id, p.price) }} 开通</template>
              </button>
            </div>
          </div>
        </div>
      </template>
    </section>

    <!-- 花积分区 -->
    <section class="store-group au-card au-anim-up" id="spend">
      <div class="group-head"><h2><Sparkles :size="16" /> 花积分</h2><p class="group-desc">积分能换这些服务</p></div>

      <div v-if="vitality" class="spend-card">
        <div class="spend-top">
          <span class="spend-icon"><Zap :size="15" /></span>
          <div class="spend-meta"><strong>活力值续命</strong><span class="spend-sub">当前 {{ vitality.vitality }} / {{ vitality.max }} · 1 点 = {{ vitalityPointCost }} 积分</span></div>
        </div>
        <div class="member-bar" role="progressbar"><i :style="{ width: (vitality.vitality / vitality.max * 100) + '%' }" /></div>
        <div class="spend-actions">
          <div class="qty-row">
            <button v-for="n in [1,3,7,14]" :key="n" type="button" class="qty-btn" :class="{ active: rechargeQty === n }" @click="rechargeQty = n">+{{ n }}</button>
          </div>
          <button type="button" class="au-btn au-btn-primary" :disabled="recharging" @click="doRechargeVitality">
            <span v-if="recharging" class="au-spinner spinner-sm" /><template v-else>消耗 {{ rechargeQty * vitalityPointCost }} 积分续命</template>
          </button>
        </div>
        <p v-if="!vitality.can_play" class="spend-warn"><TriangleAlert :size="13" /> 活力值低于观影阈值 {{ vitality.limit_threshold }}，已限制观影</p>
      </div>

      <div class="spend-card spend-soon">
        <span class="spend-icon"><Flame :size="15" /></span><span>积分兑换公益天数 · 即将上线</span>
      </div>
    </section>

    <!-- 核销区 -->
    <section class="store-group au-card au-anim-up">
      <div class="group-head"><h2><TicketCheck :size="16" /> 核销</h2><p class="group-desc">卡码 · 兑换码 · 优惠券，自动识别</p></div>

      <form class="bh-redeem" @submit.prevent="handleRedeem">
        <span class="redeem-label">
          <TicketCheck :size="14" />
          卡码 · 兑换码 · 优惠券
        </span>
        <div class="redeem-row">
          <input
            ref="redeemInputRef"
            v-model="redeemCode"
            class="au-input redeem-input"
            placeholder="输入卡码 / 兑换码 / 优惠券"
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
            使用
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

        <!-- 优惠券已应用 -->
        <div v-else-if="couponApplied" class="redeem-preview">
          <Percent :size="14" />
          <span class="rp-text">
            优惠券 <strong>{{ couponApplied }}</strong> 已应用<template v-if="couponSavings > 0"> · 本页最高省 ¥{{ couponSavings.toFixed(2) }}</template>
          </span>
          <button type="button" class="au-btn au-btn-ghost au-btn-sm" :disabled="couponLoading" @click="clearCoupon">
            <X :size="13" />
            清除
          </button>
        </div>

        <p class="redeem-hint" :class="{ warn: !!redeemNotice }">
          {{ redeemNotice || redeemHint }}
        </p>
      </form>
    </section>
  </div>
</template>

<style scoped>
/* 页面容器：纵向排列，组间距 16px（1rem），与 au-page 搭配 */
.store-view { display: flex; flex-direction: column; gap: 1rem; }

/* 页头：标题左，余额 pill 右 */
.store-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; }
.sh-title h1 { margin: 0; font-size: 1.375rem; font-weight: 800; color: var(--au-text); font-family: var(--au-font-serif); }
.sh-title p { margin: 0.25rem 0 0; font-size: 0.8125rem; color: var(--au-text-3); }
.balance-pill { display: inline-flex; align-items: center; gap: 0.375rem; padding: 0.5rem 0.875rem; border-radius: var(--au-r-full); background: var(--au-primary-soft); color: var(--au-primary); font-size: 0.8125rem; font-weight: 700; text-decoration: none; white-space: nowrap; }
.balance-pill:hover { filter: brightness(1.05); }

/* 分组卡：组标题 16px 加粗 + 灰色说明 12px */
.store-group { padding: 1.125rem; }
.group-head { margin-bottom: 1rem; }
.group-head h2 { margin: 0; display: flex; align-items: center; gap: 0.5rem; font-size: 1rem; font-weight: 700; color: var(--au-text); }
.group-head h2 svg { color: var(--au-primary); }
.group-desc { margin: 0.375rem 0 0; font-size: 0.75rem; color: var(--au-text-3); }

/* 公益服一行说明 */
.free-line { display: flex; align-items: center; gap: 0.5rem; padding: 0.875rem 1rem; border-radius: var(--au-r-lg); background: var(--au-surface-2); border: 1px dashed var(--au-border); font-size: 0.875rem; color: var(--au-text-2); }
.free-line svg { color: var(--au-primary); flex-shrink: 0; }

/* 花积分区卡片 */
.spend-card { border: 1px solid var(--au-border); border-radius: var(--au-r-lg); background: var(--au-surface-2); padding: 1rem; }
.spend-card + .spend-card { margin-top: 0.75rem; }
.spend-top { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem; }
.spend-icon { display: inline-flex; align-items: center; justify-content: center; width: 2.25rem; height: 2.25rem; border-radius: var(--au-r-lg); background: var(--au-primary-soft); color: var(--au-primary); flex-shrink: 0; }
.spend-meta { display: flex; flex-direction: column; gap: 0.125rem; }
.spend-meta strong { font-size: 0.9375rem; color: var(--au-text); }
.spend-sub { font-size: 0.75rem; color: var(--au-text-3); }
.spend-actions { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; margin-top: 0.75rem; flex-wrap: wrap; }
.spend-warn { display: flex; align-items: center; gap: 0.375rem; margin: 0.75rem 0 0; font-size: 0.75rem; color: var(--au-danger); }
.spend-soon { display: flex; align-items: center; gap: 0.75rem; color: var(--au-text-3); font-size: 0.875rem; border-style: dashed; }

/* 移动端微调 */
@media (max-width: 480px) {
  .store-group { padding: 1rem 0.875rem; }
  .spend-actions { flex-direction: column; align-items: stretch; }
}

/* ===== 以下复用原 WalletView 样式（商品卡/核销/支付） ===== */
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

.spinning { animation: au-spin 0.9s linear infinite; }

.pay-methods { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }

.pay-methods-label { font-size: 0.8125rem; color: var(--au-text-3); }

.pkg-price .price-was,

.plan-price .price-was,

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

.pkg-row-skeleton { cursor: default; pointer-events: none; opacity: 0.6; }

.pkg-row-skeleton strong,

.pkg-row-skeleton .pkg-price {
  background: linear-gradient(90deg, var(--au-border) 25%, var(--au-surface) 50%, var(--au-border) 75%);
  background-size: 200% 100%;
  animation: skel-slide 1.2s linear infinite;
  border-radius: var(--au-r-sm);
  color: transparent;
}

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

.plan-member-hint {
  display: flex; align-items: center; gap: 0.3rem;
  margin: 0.35rem 0 0; font-size: 0.75rem; font-weight: 600; color: var(--au-primary);
  white-space: nowrap;
}
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

.plan-actions { display: flex; flex-direction: column; gap: 8px; margin-top: auto; }

.plan-actions .plan-btn { margin-top: 0; }

.custom-recharge { margin-top: 16px; padding: 16px; }

.custom-recharge-head {
  display: flex; align-items: center; gap: 8px;
  font-weight: 600; font-size: 0.9rem; margin-bottom: 12px;
}

.custom-recharge-body { display: flex; gap: 12px; align-items: center; }

.qty-row { display: flex; gap: 0.5rem; margin: 0.75rem 0; }

.qty-btn { padding: 0.5rem 1rem; border-radius: var(--au-r-full); border: 1px solid var(--au-border); background: var(--au-surface-2); color: var(--au-text); cursor: pointer; font-weight: 700; }

.qty-btn.active { border-color: var(--au-primary); color: var(--au-primary); }
</style>
