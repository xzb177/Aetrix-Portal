<script setup lang="ts">
/**
 * 钱包 — 余额总览 / 会员等级 / 订单记录 / 积分流水（只看资产，不做购买）
 * 布局：余额卡 + 会员等级卡 + 订单 / 流水双 tab
 *
 * v2.11.0：从原 WalletView 拆分。充值 / 订阅 / 卡码·兑换码·优惠券核销 /
 * 自定义金额充值 / 活力续命等购买操作全部迁至商店页（StoreView，/store）；
 * 支付回跳与旧的 ?tab=recharge|plans 深链也统一转发到商店页。
 */
import { ref, onMounted, onActivated } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import {
  Wallet, Receipt, ArrowDownLeft, ArrowUpRight, RefreshCw, Flame, ChevronRight,
  Clock, CircleCheck, CircleAlert, Undo2, Percent, Zap,
  User, Medal, Award, Crown, Gem, Sparkles,
  Ticket, Clapperboard, Glasses, Projector,
} from 'lucide-vue-next'
import {
  pointsApi, checkinApi, memberApi, vitalityApi, paymentApi,
  type PointsLogEntry, type OrderRow, type CheckinStatus,
  type MyMemberInfo, type VitalityStatus,
} from '@/api/economy'

const route = useRoute()
const router = useRouter()

// ===== 状态 =====
const loading = ref(true)
const balance = ref(0)
const checkin = ref<CheckinStatus | null>(null)
/** 活力值（仅公益服用户有值） */
const vitality = ref<VitalityStatus | null>(null)
const orders = ref<OrderRow[]>([])
const logs = ref<PointsLogEntry[]>([])
const tab = ref<'orders' | 'log'>('orders')

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

/** 订单记录：单独拉取（需要保持新鲜），onMounted / onActivated 都会调用 */
async function refreshOrders() {
  try {
    const res = await paymentApi.orders({ limit: 20 })
    orders.value = res.orders || []
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
  // silent = true 时为 KeepAlive 切回 tab 的后台静默刷新：不碰 loading，
  // 不闪骨架屏，数据到了直接更新视图
  if (!silent) loading.value = true
  try {
    const emptyLogs = { total: 0, balance: 0, logs: [] as PointsLogEntry[] }
    const statusFallback: CheckinStatus | null = null
    const emptyMember: MyMemberInfo | null = null
    const [logR, statusR, memberR, vitalityR] = await Promise.allSettled([
      pointsApi.log({ limit: 30 }),
      checkinApi.status(),
      memberApi.info(),
      // 活力值：非公益服用户 403，兜底为 null 不展示
      vitalityApi.status(),
    ])
    const logData = settled(logR, emptyLogs, silent)
    if (logData !== undefined) {
      logs.value = logData.logs || []
      balance.value = logData.balance
    }
    const checkinStatus = settled(statusR, statusFallback, silent)
    if (checkinStatus !== undefined) checkin.value = checkinStatus
    const memberData = settled(memberR, emptyMember, silent)
    if (memberData !== undefined) member.value = memberData
    const vitalityData = settled(vitalityR, null, silent)
    if (vitalityData !== undefined) {
      vitality.value = vitalityData && vitalityData.success ? vitalityData : null
    }
  } finally {
    loading.value = false
    hasLoaded.value = true
  }
}

/** 进入时的 query 处理：?tab= 定位选项卡；?paid=1 / ?order= 转发商店页轮询。
 * KeepAlive 下 query 变化不再触发重建，所以 onMounted / onActivated 都要走这里。 */
function handleEntryQuery() {
  // 支付完成跳回：统一去商店页轮询到账结果（订单号来自 ?order=，兼容旧 ?paid=1）
  // 后端 return_url 不动，由商店页接管轮询
  if (route.query.paid === '1' || route.query.order) {
    void router.replace({ path: '/store', query: route.query })
    return
  }
  // 支持 ?tab= 定位选项卡（签到页「全部流水」链接）
  const tabParam = route.query.tab
  if (tabParam === 'orders' || tabParam === 'log') {
    tab.value = tabParam
  } else if (tabParam === 'recharge' || tabParam === 'plans') {
    // 旧深链兼容：购买相关入口已迁至商店页
    void router.replace('/store')
  }
}

onMounted(async () => {
  await loadAll()
  await refreshOrders()
  handleEntryQuery()
})

// 从别的 tab 切回来（KeepAlive 缓存命中）：先处理 query，再后台静默刷新
onActivated(() => {
  handleEntryQuery()
  if (hasLoaded.value) {
    void loadAll(true)
    void refreshOrders()
  }
})
</script>

<template>
  <div class="au-page wallet-view">
    <!-- 余额主卡（单栏：只看资产） -->
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

        <!-- 会员等级：徽章 + 经验进度 -->
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

        <!-- 活力值：仅公益服用户；续活入口改去商店 -->
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
          <RouterLink to="/store#spend" class="vitality-recharge-btn">去续命</RouterLink>
        </div>
      </div>

      <button class="au-btn au-btn-ghost au-btn-sm refresh" title="刷新" @click="() => loadAll()">
        <RefreshCw :size="14" :class="{ spinning: loading }" />
      </button>
    </section>

    <!-- 选项卡：只剩订单/流水 -->
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
  </div>
</template>

<style scoped>
.wallet-view { display: flex; flex-direction: column; gap: 1.125rem; }

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

.member-badge[data-tier="legend"] {
  animation: badge-breathe 3.2s ease-in-out infinite;
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

.refresh { align-self: flex-start; margin-top: 0.25rem; }

.spinning { animation: au-spin 0.9s linear infinite; }

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

.spinner-sm { width: 14px; height: 14px; border-width: 2px; }

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

.vitality-row { display: flex; align-items: center; gap: 0.75rem; margin-top: 0.75rem; padding: 0.625rem 0.875rem; border: 1px solid var(--au-border); border-radius: var(--au-r-lg); background: var(--au-surface-2); }

.vitality-icon { color: var(--au-warning, #f59e0b); display: inline-flex; flex-shrink: 0; }

.vitality-meta { flex: 1; min-width: 0; }

.vitality-top { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem; font-size: 0.8125rem; margin-bottom: 0.375rem; }

.vitality-warn { color: var(--au-danger, #ef4444); font-size: 0.75rem; }

.vitality-ok { color: var(--au-text-3); font-size: 0.75rem; }

.vitality-recharge-btn { flex-shrink: 0; padding: 0.375rem 0.75rem; border-radius: var(--au-r-full); border: 1px solid var(--au-primary); color: var(--au-primary); background: transparent; font-size: 0.75rem; font-weight: 700; cursor: pointer; }

.vitality-recharge-btn:hover { background: var(--au-primary-soft); }
</style>
