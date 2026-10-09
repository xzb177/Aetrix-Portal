<script setup lang="ts">
/**
 * 商店 — 充值积分 / 购买订阅 / 优惠券
 *
 * v2.43.0：从 WalletView 拆分出来。钱包（余额/流水/订单/核销）在 /wallet。
 * 原钱包页逻辑： / 积分充值（支付下单）/ 卡码·兑换码·优惠券核销 / 订单记录 / 积分流水
 * 布局：余额卡左右分区（左余额+签到态，右唯一的核销面板）；套餐卡横向结构化行
 *
 * v2.10.1：优惠券并进顶部那一个核销面板。此前「卡码 · 兑换码」在余额卡里、
 * 「优惠码」是分页上另起的一条输入框，同一页两个「输入码 → 应用」的面板，
 * 既割裂又让用户猜手里那张码该填哪边；现在只有一个入口，由后端预检识别来源。
 */
import { ref, computed, onMounted, onActivated, onBeforeUnmount, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  Wallet, Coins, Sparkles, Zap, Crown,
  CircleCheck, CircleAlert, ChevronRight,
  Percent, User, Medal, Award, Gem,
  Ticket, Clapperboard, Glasses, Projector,
} from 'lucide-vue-next'
import {
  pointsApi, paymentApi, couponApi, memberApi, currencyApi,
  type RechargePackage, type SubscriptionPlan,
  type OrderRow, type PaymentMethod, type CouponQuote,
  type MyMemberInfo,
} from '@/api/economy'
import { subscriptionApi, isExpiringSoon, type MySubscription } from '@/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const route = useRoute()
const userStore = useUserStore()

const loading = ref(true)
const balance = ref(0)
const packages = ref<RechargePackage[]>([])
const plans = ref<SubscriptionPlan[]>([])
const methods = ref<PaymentMethod[]>([])
const orders = ref<OrderRow[]>([])
const tab = ref<'recharge' | 'plans'>('recharge')
const payMethod = ref('alipay')
const orderLoading = ref<number | null>(null)

// ===== 会员等级（P1 统一货币体系）=====
const member = ref<MyMemberInfo | null>(null)
const showLevels = ref(false)
/** 徽章图标名 → lucide 组件（暗房影院主题：票根/场记板/鉴赏镜/放映机/星芒/王冠） */
const levelIconMap: Record<string, unknown> = {
  User, Medal, Award, Crown, Gem, Sparkles,
  Ticket, Clapperboard, Glasses, Projector,
}
const levelIcon = (name: string) => levelIconMap[name] || Ticket

/** 徽章样式：暗房影院质感——深色底上的径向高光渐变，而非纯色圆块 */
const badgeStyle = (color: string, level: number) => {
  const c = color || '#9ca3af'
  // 高等级（造梦者/传奇）用更亮的高光，低等级保持沉稳
  const highlight = level >= 5 ? 'rgba(255,255,255,0.45)' : 'rgba(255,255,255,0.28)'
  const glow = level >= 5 ? `${c}66` : 'transparent'
  return {
    background: `radial-gradient(circle at 32% 28%, ${highlight}, transparent 55%), linear-gradient(145deg, ${c}, ${c}cc)`,
    boxShadow: `0 2px 8px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.25), 0 0 12px ${glow}`,
  } as Record<string, string>
}
/** 徽章档位：用于 CSS 分级动画（仅传奇有呼吸光晕） */
const badgeTier = (level: number) => (level >= 6 ? 'legend' : 'common')

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

// （优惠券状态直接显示在面板内，不再需要独立的 hint）


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

/** 面板自己切了分页（券只适用于另一类商品）：这一次不要再触发一遍试算 */
let skipRequote = false

/**
 * 试算并应用优惠券
 *
 * silent：不弹 toast（换分页自动重算时不打扰用户）
 * follow：券只适用于另一类商品时，把用户带到有折后价的那一页
 *         ——只在用户刚填完码时跟随；被动重算不动用户正在看的分页
 */
async function applyCoupon(code: string, { silent = false, follow = false } = {}) {
  const text = (code || '').trim()
  couponError.value = ''
  if (!text) {
    clearCoupon()
    return
  }
  couponLoading.value = true
  try {
    // 一张券可能只适用于充值、或只适用于会员：先算眼前这一页，本页全用不了再试另一类
    // （公益服没有会员可卖，就不去试订阅了。）
    const candidates: Array<'recharge' | 'subscription'> = tab.value === 'plans' && !isFreeRealm.value
      ? ['subscription', 'recharge']
      : (isFreeRealm.value ? ['recharge'] : ['recharge', 'subscription'])

    let used: { kind: 'recharge' | 'subscription'; rows: QuoteRow[] } | null = null
    let failed: QuoteRow[] = []
    for (const kind of candidates) {
      const rows = await quoteCoupon(text, kind)
      if (rows.some((r) => r.quote)) {
        used = { kind, rows }
        break
      }
      if (!failed.length) failed = rows   // 第一次失败的原因留着给用户看
    }

    if (!used) {
      const detail = failed.find((r) => r.detail)?.detail
      couponApplied.value = ''
      couponQuotes.value = {}
      couponError.value = typeof detail === 'string'
        ? detail
        : (failed.length ? '优惠码不可用' : '暂无可购买的商品')
      if (!silent) toast.error(couponError.value)
      return
    }

    // 折扣只长在商品上：券既然只适用于另一类商品，就把用户带到那一页，
    // 否则「已应用」在眼前这一页看不出省在哪。
    const target = used.kind === 'subscription' ? 'plans' : 'recharge'
    if (follow && tab.value !== target) {
      skipRequote = true
      tab.value = target
    }

    const valid = used.rows.filter((r) => r.quote)
    couponQuotes.value = Object.fromEntries(valid.map((r) => [r.key, r.quote as CouponQuote]))
    couponApplied.value = valid[0].quote!.code
    // 有些商品不满足这张券（如满减门槛）：说清楚，不默默只给一部分打折
    const skipped = used.rows.length - valid.length
    if (skipped > 0) {
      couponError.value = `已应用，但本页有 ${skipped} 个商品不满足该券条件（原价购买）`
    }
    if (!silent) toast.success(`已应用「${couponApplied.value}」`)
  } finally {
    couponLoading.value = false
  }
}

// 切换分页（充值 ↔ 会员）后商品变了，已应用的券要重新试算，否则价格显示会对不上
watch(tab, () => {
  if (skipRequote) {
    skipRequote = false
    return
  }
  if (couponApplied.value) void applyCoupon(couponApplied.value, { silent: true })
})

const rechargeEnabled = ref(true)
const plansEnabled = ref(true)
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
// 临期：与后台到期提醒同口径（默认 7 天）——套餐页本来就是续费的地方，
// 剩余天数不多时直接把状态行染成警示色，别再让用户自己数天数
const subExpiringSoon = computed(() => isExpiringSoon(currentSub.value))

async function refreshSubscriptions() {
  subscriptions.value = await subscriptionApi.getMine().catch(() => subscriptions.value)
  try {
    await userStore.fetchUser()
  } catch {
    // 会员身份刷新失败不影响结果
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
async function handlePointsOrder(plan: SubscriptionPlan) {
  orderLoading.value = -plan.id
  try {
    const res = await paymentApi.createOrder({ kind: 'subscription', item_id: plan.id, payment_method: 'points', pay_with_points: true })
    if (res.paid_with_points) {
      toast.success(res.message || '积分支付成功，订阅已开通')
      await refreshSubscriptions()
      await refreshBalance()
    } else if (res.pay_url) {
      window.location.href = res.pay_url
    }
  } catch (err: any) {
    toast.error(err?.response?.data?.detail || '下单失败，请稍后重试')
  } finally { orderLoading.value = null }
}


// ===== 数据加载 =====
async function refreshBalance() {
  try {
    const logRes = await pointsApi.log({ limit: 1 })
    balance.value = logRes.balance
  } catch { /* 静默 */ }
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
    const emptyPkgs = { enabled: false, packages: [] as RechargePackage[] }
    const emptyPlans = {
      enabled: false,
      plans: [] as SubscriptionPlan[],
      access_mode: 'paid' as 'paid' | 'free',
      is_free: false,
      access_note: '',
    }
    const emptyMethods: PaymentMethod[] = []
    const emptyOrders = { orders: [] as OrderRow[] }
    const emptySubs: MySubscription[] = []
    const couponFallback = { enabled: false }
    const [pkgR, planR, methodR, orderR, subsR, couponR, memberR] = await Promise.allSettled([
      paymentApi.packages(),
      paymentApi.plans(),
      paymentApi.methods(),
      paymentApi.orders({ limit: 20 }),
      subscriptionApi.getMine(),
      couponApi.config(),
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
    const orderData = settled(orderR, emptyOrders, silent)
    if (orderData !== undefined) orders.value = orderData.orders || []
    const subs = settled(subsR, emptySubs, silent)
    if (subs !== undefined) subscriptions.value = Array.isArray(subs) ? subs : []
    const couponCfg = settled(couponR, couponFallback, silent)
    if (couponCfg !== undefined) couponEnabled.value = couponCfg.enabled === true
    const memberData = memberR.status === 'fulfilled' ? memberR.value : null
    member.value = memberData
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

const couponCode = ref('')
const couponPanelRef = ref<HTMLElement | null>(null)

/** 订阅页的一行指引：把焦点交回顶部优惠券面板 */
function focusCoupon() {
  couponPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

const lastHandledEntry = ref('')
function handleEntryQuery() {
  const tabParam = route.query.tab
  if (tabParam === 'recharge' || tabParam === 'plans') {
    tab.value = tabParam
  }
  // 支付完成跳回：轮询到账结果（订单号来自 ?order=，兼容旧 ?paid=1）
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
})

// 从别的 tab 切回来（KeepAlive 缓存命中）：先处理 query，再后台静默刷新
onActivated(() => {
  handleEntryQuery()
  if (hasLoaded.value) void loadAll(true)
})

// 停留在本页时 query 变化：同样要定位选项卡
watch(() => route.query.tab, (tabParam) => {
  if (tabParam === 'recharge' || tabParam === 'plans') {
    tab.value = tabParam
  }
})

onBeforeUnmount(stopPayPoll)

</script>

<template>
  <div class="au-page store-view">

<RouterLink to="/wallet" class="wallet-strip au-card au-anim-up">
  <span class="ws-left">
    <Wallet :size="15" />
    <span>积分余额</span>
    <strong>{{ balance }}</strong>
  </span>
  <span class="ws-right">
    <span>我的钱包</span>
    <ChevronRight :size="13" />
  </span>
</RouterLink>

<section class="member-hero au-anim-up">
        <!-- 会员等级：徽章 + 经验进度（P1 统一货币体系） -->
        <div v-if="member" class="member-row">
          <span class="member-badge" :style="badgeStyle(member.badge_color, member.level)" :data-tier="badgeTier(member.level)">
            <component :is="levelIcon(member.badge_icon)" :size="17" />
          </span>
          <div class="member-meta">
            <div class="member-top">
              <strong class="member-name">{{ member.level_name }}</strong>
              <span class="member-xp">{{ member.xp }} 经验</span>
            </div>
            <div class="member-bar" role="progressbar" :aria-valuenow="member.progress_pct" aria-valuemin="0" aria-valuemax="100">
              <i :style="{ width: member.progress_pct + '%' }" />
            </div>
            <div class="member-next">
              <span v-if="member.next_level">距 Lv.{{ member.next_level }} 还差 {{ member.xp_to_next }} 经验</span>
              <span v-else>已满级</span>
              <button type="button" class="member-levels-toggle" @click="showLevels = !showLevels">
                等级权益 {{ showLevels ? '收起' : '展开' }}
                <ChevronRight :size="12" :class="{ rotated: showLevels }" />
              </button>
            </div>
          </div>
        </div>

        <!-- 全等级权益（公开透明） -->
        <div v-if="member && showLevels" class="levels-grid">
          <div
            v-for="lv in member.levels"
            :key="lv.level"
            class="level-card"
            :class="{ current: lv.level === member.level }"
            :style="{ borderTopColor: lv.badge_color }"
          >
            <span class="member-badge sm" :style="badgeStyle(lv.badge_color, lv.level)" :data-tier="badgeTier(lv.level)">
              <component :is="levelIcon(lv.badge_icon)" :size="14" />
            </span>
            <div class="level-head">
              <strong>Lv.{{ lv.level }} {{ lv.name }}</strong>
              <span class="level-th">{{ lv.xp_threshold }} 经验</span>
            </div>
            <ul class="level-benefits">
              <li v-for="(b, i) in lv.benefits" :key="i">{{ b }}</li>
            </ul>
          </div>
        </div>
    </section>

<section ref="couponPanelRef" class="coupon-panel au-card au-anim-up">
  <div class="coupon-panel-row">
    <span class="coupon-panel-label"><Percent :size="14" /> 优惠券</span>
    <div v-if="couponApplied" class="coupon-panel-applied">
      <span class="coupon-panel-status"><CircleCheck :size="14" /> 优惠券 <strong>{{ couponApplied }}</strong> 已应用 · 最高省 ¥{{ couponSavings.toFixed(2) }}</span>
      <button type="button" class="au-btn au-btn-ghost au-btn-sm" @click="clearCoupon">清除</button>
    </div>
    <div v-else class="coupon-panel-form">
      <input v-model="couponCode" type="text" class="au-input" placeholder="输入优惠券码，购买时抵扣" @keyup.enter="applyCoupon(couponCode)" />
      <button type="button" class="au-btn au-btn-primary au-btn-sm" :disabled="couponLoading || !couponCode.trim()" @click="applyCoupon(couponCode)">应用</button>
    </div>
  </div>
  <p v-if="couponError" class="coupon-error">{{ couponError }}</p>
</section>

    <!-- 选项卡 -->
    <nav class="tabs au-anim-up" style="animation-delay: 100ms">
      <button class="tab" :class="{ active: tab === 'recharge' }" @click="tab = 'recharge'">
        <Coins :size="15" /> 充值积分
      </button>
      <button class="tab" :class="{ active: tab === 'plans' }" @click="tab = 'plans'">
        <Zap :size="15" /> 购买订阅
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


    <!-- 充值积分：横向行卡 — 左侧点数信息，右侧价格与购买。
         首次加载（loading）先出骨架，不渲染空态——否则请求回来前
         会先闪一下「暂无可用充值套餐」再变成套餐列表 -->
    <section v-if="tab === 'recharge'" class="tab-body au-anim-up">
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
      <!-- 自定义金额充值（P2）：按 recharge_ratio 换算积分 -->
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
      </div>

      <!-- 当前会员状态：已开通显示套餐与到期，未开通提示付费墙 -->
      <div v-else-if="plansEnabled" class="member-status"
        :class="{ inactive: !currentSub, warn: subExpiringSoon }">
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

      <!-- 优惠券入口在顶部面板，这里只留一行指引；
           卡码 / 兑换码请到「钱包」页核销 -->
      <button v-if="plansEnabled && !isFreeRealm" type="button" class="code-tip" @click="focusCoupon">
        <KeyRound :size="14" />
        <span>已有优惠券？用顶部「优惠券」入口，购买时自动抵扣；卡码 / 兑换码请到钱包核销</span>
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
          <div class="plan-head">
            <h4 class="plan-name">
              {{ p.name }}
              <!-- 推荐：套餐名旁一颗琥珀小标签（不再是整条琥珀横幅），卡片本身换 1px 琥珀描边 -->
              <span v-if="p.is_popular" class="pop-pill">推荐</span>
              <em v-if="p.realm_name" class="plan-realm">{{ p.realm_name }}</em>
            </h4>
            <span class="plan-price">
              <em v-if="wasPrice('subscription', p.id)" class="price-was">¥{{ wasPrice('subscription', p.id) }}</em>
              ¥{{ paidPrice('subscription', p.id, p.price) }}
              <em class="plan-days">/ {{ p.duration_days }} 天</em>
            </span>
            <span v-if="p.points_price != null" class="plan-points-price">
              或 {{ p.points_price }} 积分
            </span>
          </div>
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
            <button
              v-if="p.points_price != null"
              class="au-btn au-btn-ghost plan-btn"
              :disabled="orderLoading === -p.id"
              @click="handlePointsOrder(p)"
            >
              <span v-if="orderLoading === -p.id" class="au-spinner spinner-sm" />
              <template v-else>{{ p.points_price }} 积分开通</template>
            </button>
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

/* 商店页：优惠券面板 */
.coupon-panel { margin-bottom: 1rem; padding: 0.875rem 1rem; }
.coupon-panel-row { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.coupon-panel-label { display: inline-flex; align-items: center; gap: 0.375rem; font-weight: 600; font-size: 0.875rem; white-space: nowrap; }
.coupon-panel-form { display: flex; gap: 0.5rem; flex: 1; min-width: 200px; }
.coupon-panel-form .au-input { flex: 1; }
.coupon-panel-applied { display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 200px; }
.coupon-panel-status { display: inline-flex; align-items: center; gap: 0.375rem; font-size: 0.875rem; color: var(--au-primary); }
.coupon-error { margin: 0.5rem 0 0; font-size: 0.8125rem; color: var(--au-danger); }
/* 商店页：钱包跳转条 */
.wallet-strip { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; padding: 0.625rem 0.875rem; text-decoration: none; color: var(--au-text); }
.wallet-strip .ws-left { display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--au-text-2); }
.wallet-strip .ws-left strong { color: var(--au-primary); font-size: 1rem; }
.wallet-strip .ws-right { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.8125rem; color: var(--au-text-3); }
/* 商店页：会员卡 */
.member-hero { margin-bottom: 1rem; }
</style>
