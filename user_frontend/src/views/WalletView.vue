<script setup lang="ts">
/**
 * 钱包 — 余额总览 / 积分充值（支付下单）/ 兑换码 / 订单记录 / 积分流水
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Wallet, Coins, TicketCheck, Receipt, RefreshCw, Sparkles, Zap,
  Copy, Check, ExternalLink, ArrowUpRight, ArrowDownLeft, CircleCheck, Clock, CircleAlert,
} from 'lucide-vue-next'
import {
  pointsApi, checkinApi, exchangeApi, paymentApi,
  type PointsLogEntry, type RechargePackage, type SubscriptionPlan,
  type OrderRow, type PaymentMethod, type CheckinStatus,
} from '@/api/economy'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'

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

// ===== 兑换码 =====
const redeemCode = ref('')
const redeemLoading = ref(false)

async function handleRedeem() {
  const code = redeemCode.value.trim()
  if (!code) {
    toast.error('请输入兑换码')
    return
  }
  redeemLoading.value = true
  try {
    const res = await exchangeApi.redeem(code)
    toast.success(res.message || '兑换成功')
    redeemCode.value = ''
    await refreshBalance()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '兑换失败，请稍后重试')
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
    const emptyPlans = { enabled: false, plans: [] as SubscriptionPlan[] }
    const emptyMethods: PaymentMethod[] = []
    const emptyOrders = { orders: [] as OrderRow[] }
    const emptyLogs = { total: 0, balance: 0, logs: [] as PointsLogEntry[] }

    const statusFallback: CheckinStatus | null = null
    const [pkgRes, planRes, methodRes, orderRes, logRes, statusRes] = await Promise.all([
      paymentApi.packages().catch(() => emptyPkgs),
      paymentApi.plans().catch(() => emptyPlans),
      paymentApi.methods().catch(() => emptyMethods),
      paymentApi.orders({ limit: 20 }).catch(() => emptyOrders),
      pointsApi.log({ limit: 30 }).catch(() => emptyLogs),
      checkinApi.status().catch(() => statusFallback),
    ])
    packages.value = pkgRes.packages || []
    plans.value = planRes.plans || []
    methods.value = Array.isArray(methodRes) ? methodRes : []
    orders.value = orderRes.orders || []
    logs.value = logRes.logs || []
    balance.value = logRes.balance
    checkin.value = statusRes
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

onMounted(async () => {
  await loadAll()
  // 支付完成跳回时刷新余额并提示
  if (paidFlag.value) {
    toast.info('支付已提交，若已到账余额将自动更新', 5000)
  }
})
</script>

<template>
  <div class="au-page wallet-view">
    <!-- 余额卡 -->
    <section class="balance-card au-anim-up">
      <div class="balance-left">
        <span class="balance-label">
          <Wallet :size="15" />
          积分余额
        </span>
        <div class="balance-num">
          <span class="num">{{ balance }}</span>
          <span class="unit">积分</span>
        </div>
        <div v-if="checkin" class="balance-sub">
          <Zap :size="13" />
          今日{{ checkin.checked_today ? '已' : '未' }}签到 · 连签 {{ checkin.streak }} 天 ·
          <RouterLink to="/checkin" class="link">去签到 →</RouterLink>
        </div>
      </div>
      <button class="au-btn au-btn-ghost au-btn-sm refresh" @click="loadAll">
        <RefreshCw :size="14" :class="{ spinning: loading }" />
        刷新
      </button>
    </section>

    <!-- 兑换码 -->
    <section class="redeem-card au-card au-card-pad au-anim-up" style="animation-delay: 60ms">
      <div class="redeem-head">
        <TicketCheck :size="17" class="redeem-icon" />
        <div>
          <h3>兑换码</h3>
          <p>输入兑换码，积分或订阅时长立即到账</p>
        </div>
      </div>
      <form class="redeem-form" @submit.prevent="handleRedeem">
        <input
          v-model="redeemCode"
          class="au-input redeem-input"
          placeholder="例如：ABCD-1234-EFGH"
          maxlength="32"
          autocomplete="off"
        >
        <button type="submit" class="au-btn au-btn-primary" :disabled="redeemLoading">
          <Sparkles v-if="!redeemLoading" :size="15" />
          <span v-if="redeemLoading" class="au-spinner spinner-sm" />
          立即兑换
        </button>
      </form>
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

    <!-- 充值积分 -->
    <section v-if="tab === 'recharge'" class="tab-body au-anim-up">
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

      <div v-if="!packages.length" class="au-empty">
        <Coins :size="30" />
        <p>暂无可用充值套餐</p>
      </div>
      <div v-else class="pkg-grid">
        <button
          v-for="p in packages"
          :key="p.id"
          class="pkg-card"
          :class="{ popular: p.is_popular }"
          :disabled="orderLoading === p.id"
          @click="handleOrder('recharge', p.id)"
        >
          <span v-if="p.is_popular" class="pkg-pop-tag">超值</span>
          <span class="pkg-name">{{ p.name }}</span>
          <span class="pkg-points">
            <strong>{{ p.total_points }}</strong>
            <em>积分</em>
          </span>
          <span v-if="p.bonus > 0" class="pkg-bonus">含赠送 {{ p.bonus }} 积分</span>
          <span class="pkg-price">¥ {{ p.price.toFixed(2) }}</span>
          <span class="pkg-cta">
            <span v-if="orderLoading === p.id" class="au-spinner spinner-sm" />
            <template v-else>立即购买 <ExternalLink :size="12" /></template>
          </span>
        </button>
      </div>
    </section>

    <!-- 购买订阅 -->
    <section v-if="tab === 'plans'" class="tab-body au-anim-up">
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

      <div v-if="!plans.length" class="au-empty">
        <Zap :size="30" />
        <p>暂无可购买套餐，请联系管理员开通</p>
      </div>
      <div v-else class="plan-grid">
        <div v-for="p in plans" :key="p.id" class="plan-card" :class="{ popular: p.is_popular }">
          <span v-if="p.is_popular" class="pkg-pop-tag">推荐</span>
          <h4 class="plan-name">{{ p.name }}</h4>
          <p class="plan-desc">{{ p.description || '会员专属权益' }}</p>
          <ul v-if="p.features && p.features.length" class="plan-features">
            <li v-for="(f, i) in p.features" :key="i">
              <CircleCheck :size="13" /> {{ f }}
            </li>
          </ul>
          <div class="plan-foot">
            <span class="plan-price">¥ {{ p.price.toFixed(2) }} <em>/ {{ p.duration_days }} 天</em></span>
            <button
              class="au-btn au-btn-primary au-btn-sm"
              :disabled="orderLoading === p.id"
              @click="handleOrder('subscription', p.id)"
            >
              <span v-if="orderLoading === p.id" class="au-spinner spinner-sm" />
              <template v-else>立即开通</template>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- 订单 -->
    <section v-if="tab === 'orders'" class="tab-body au-anim-up">
      <div v-if="!orders.length" class="au-empty">
        <Receipt :size="30" />
        <p>还没有订单记录</p>
      </div>
      <div v-else class="order-list">
        <div v-for="o in orders" :key="o.order_id" class="order-item au-card">
          <div class="order-main">
            <span class="order-name">{{ o.item_name }}</span>
            <span class="order-id mono">{{ o.order_id }}</span>
            <span class="order-time">{{ fmtTime(o.created_at) }}</span>
          </div>
          <div class="order-side">
            <span class="order-amount">¥ {{ o.amount.toFixed(2) }}</span>
            <span :class="orderStatusMeta(o.status).cls">
              <Clock v-if="o.status === 'pending'" :size="11" />
              <CircleCheck v-else-if="o.status === 'paid'" :size="11" />
              <CircleAlert v-else :size="11" />
              {{ orderStatusMeta(o.status).label }}
            </span>
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

/* ===== 余额卡 ===== */
.balance-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 1.5rem;
  border-radius: var(--au-r-xl);
  background: linear-gradient(135deg, rgba(34, 211, 238, 0.14), rgba(167, 139, 250, 0.14) 55%, rgba(7, 11, 18, 0.2));
  border: 1px solid var(--au-primary-border);
  backdrop-filter: blur(14px);
  position: relative;
  overflow: hidden;
}
.balance-card::after {
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
  margin-top: 0.5rem;
}
.balance-num .num {
  font-size: 2.5rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  background: var(--au-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-variant-numeric: tabular-nums;
}
.balance-num .unit { font-size: 0.875rem; color: var(--au-text-3); }

.balance-sub {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
}
.balance-sub .link { color: var(--au-primary); text-decoration: none; font-weight: 600; }
.balance-sub .link:hover { text-decoration: underline; }

.refresh { flex-shrink: 0; }
.spinning { animation: au-spin 0.9s linear infinite; }

/* ===== 兑换卡 ===== */
.redeem-card { display: flex; flex-direction: column; gap: 0.875rem; }

.redeem-head { display: flex; align-items: center; gap: 0.625rem; }
.redeem-icon { color: var(--au-violet); flex-shrink: 0; }
.redeem-head h3 { margin: 0; font-size: 0.9375rem; font-weight: 700; color: var(--au-text); }
.redeem-head p { margin: 0.125rem 0 0; font-size: 0.75rem; color: var(--au-text-3); }

.redeem-form { display: flex; gap: 0.625rem; }
.redeem-input { flex: 1; text-transform: uppercase; letter-spacing: 0.04em; }

/* ===== 选项卡 ===== */
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

/* ===== 支付方式 ===== */
.pay-methods { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
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

/* ===== 充值套餐 ===== */
.pkg-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.875rem;
}

.pkg-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
  padding: 1.375rem 1rem 1rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
  text-align: center;
}
.pkg-card:hover:not(:disabled) {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(34, 211, 238, 0.15);
}
.pkg-card.popular { border-color: var(--au-primary-border); }
.pkg-card:disabled { opacity: 0.6; cursor: wait; }

.pkg-pop-tag {
  position: absolute;
  top: -9px;
  right: 12px;
  padding: 0.125rem 0.5625rem;
  background: var(--au-gradient-warm);
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

.pkg-name { font-size: 0.8125rem; color: var(--au-text-2); font-weight: 600; }
.pkg-points strong {
  font-size: 1.75rem;
  font-weight: 800;
  background: var(--au-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-variant-numeric: tabular-nums;
}
.pkg-points em { font-style: normal; font-size: 0.75rem; color: var(--au-text-3); margin-left: 0.25rem; }
.pkg-bonus { font-size: 0.6875rem; color: var(--au-success); }
.pkg-price { font-size: 1.0625rem; font-weight: 700; color: var(--au-text); margin-top: 0.25rem; }

.pkg-cta {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  margin-top: 0.5rem;
  height: 30px;
  padding: 0 0.875rem;
  background: var(--au-surface-2);
  border-radius: var(--au-r-full);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--au-text-2);
}
.pkg-card:hover:not(:disabled) .pkg-cta { background: var(--au-gradient); color: #05141c; }

.spinner-sm { width: 14px; height: 14px; border-width: 2px; }

/* ===== 订阅套餐 ===== */
.plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0.875rem;
}

.plan-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  padding: 1.375rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  transition: all var(--au-fast);
}
.plan-card.popular { border-color: var(--au-primary-border); box-shadow: 0 0 24px rgba(34, 211, 238, 0.08); }

.plan-name { margin: 0; font-size: 1.0625rem; font-weight: 700; color: var(--au-text); }
.plan-desc { margin: 0; font-size: 0.8125rem; color: var(--au-text-3); line-height: 1.5; }

.plan-features {
  list-style: none;
  margin: 0.25rem 0 0;
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

.plan-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 0.875rem;
  border-top: 1px dashed var(--au-border);
}
.plan-price { font-size: 1.125rem; font-weight: 800; color: var(--au-text); }
.plan-price em { font-style: normal; font-size: 0.75rem; font-weight: 400; color: var(--au-text-3); }

/* ===== 订单 ===== */
.order-list { display: flex; flex-direction: column; gap: 0.625rem; }

.order-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.125rem;
}

.order-main { display: flex; flex-direction: column; gap: 0.1875rem; min-width: 0; }
.order-name { font-size: 0.875rem; font-weight: 600; color: var(--au-text); }
.order-id { font-size: 0.6875rem; color: var(--au-text-4); }
.order-time { font-size: 0.6875rem; color: var(--au-text-4); }

.order-side { display: flex; flex-direction: column; align-items: flex-end; gap: 0.3125rem; flex-shrink: 0; }
.order-amount { font-size: 0.9375rem; font-weight: 700; color: var(--au-text); }

/* ===== 流水 ===== */
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

@media (max-width: 640px) {
  .redeem-form { flex-direction: column; }
  .order-item { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
  .order-side { flex-direction: row; align-items: center; gap: 0.625rem; }
  .balance-num .num { font-size: 2rem; }
}
</style>
