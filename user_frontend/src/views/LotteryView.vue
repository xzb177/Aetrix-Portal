<script setup lang="ts">
/**
 * 幸运抽奖 — 积分抽奖：奖品宫格、抽奖按钮、中奖弹窗、我的记录
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import {
  PartyPopper, Gift, Coins, CalendarDays, Crown, Sparkles, History, Ticket,
} from 'lucide-vue-next'
import {
  lotteryApi, pointsApi,
  type LotteryPrize, type LotteryDrawResult, type LotteryLogEntry,
} from '@/api/economy'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const prizes = ref<LotteryPrize[]>([])
const prizesLoading = ref(true)
const balance = ref<number | null>(null)
const balanceLoading = ref(true)

const drawing = ref(false)
const drawCost = ref(10)
const lastResult = ref<LotteryDrawResult | null>(null)
const showResult = ref(false)
const highlightPrizeId = ref<number | null>(null)

const logs = ref<LotteryLogEntry[]>([])
const logsLoading = ref(true)
const logsPage = ref(1)
const logsTotal = ref(0)
const logsMoreLoading = ref(false)
const LOG_PAGE_SIZE = 20

const hasMoreLogs = computed(() => logs.value.length < logsTotal.value)

const canDraw = computed(() => {
  if (balance.value === null) return false
  return balance.value >= drawCost.value && !drawing.value
})

function prizeIcon(type: LotteryPrize['type']) {
  if (type === 'days') return CalendarDays
  if (type === 'points') return Coins
  return Crown
}

function prizeDesc(p: LotteryPrize): string {
  if (p.type === 'days') return `公益服 ${p.value} 天`
  if (p.type === 'points') return '直接到账'
  return '永不过期'
}

function grantText(res: LotteryDrawResult): string {
  const g = res.grant
  if (res.prize.type === 'days') return `已为你续 ${g.days ?? res.prize.value} 天公益`
  if (res.prize.type === 'points') return `已到账 ${g.points ?? res.prize.value} 积分`
  return '已获得永久白名单'
}

function formatTime(ts: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

async function loadPrizes() {
  prizesLoading.value = true
  try {
    const res = await lotteryApi.prizes()
    prizes.value = res.prizes || []
  } catch {
    prizes.value = []
  } finally {
    prizesLoading.value = false
  }
}

async function loadBalance() {
  balanceLoading.value = true
  try {
    const res = await pointsApi.log({ limit: 1 })
    balance.value = res.balance ?? 0
  } catch {
    balance.value = 0
  } finally {
    balanceLoading.value = false
  }
}

async function loadLogs(reset = false) {
  if (reset) {
    logsPage.value = 1
    logs.value = []
    logsTotal.value = 0
  }
  if (reset) logsLoading.value = true
  else logsMoreLoading.value = true
  try {
    const res = await lotteryApi.logs({ page: logsPage.value, page_size: LOG_PAGE_SIZE })
    logsTotal.value = res.total ?? 0
    logs.value = reset ? (res.items || []) : [...logs.value, ...(res.items || [])]
  } catch {
    /* 静默 */
  } finally {
    logsLoading.value = false
    logsMoreLoading.value = false
  }
}

function loadMoreLogs() {
  if (!hasMoreLogs.value || logsMoreLoading.value) return
  logsPage.value += 1
  loadLogs(false)
}

async function handleDraw() {
  if (drawing.value || !canDraw.value) return
  drawing.value = true
  try {
    const res = await lotteryApi.draw()
    drawCost.value = res.cost ?? drawCost.value
    lastResult.value = res
    showResult.value = true
    highlightPrizeId.value = res.prize.id
    setTimeout(() => { highlightPrizeId.value = null }, 3000)
    toast.success(`恭喜抽中「${res.prize.name}」`)
    await Promise.all([loadBalance(), loadLogs(true)])
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '抽奖失败，请稍后重试')
  } finally {
    drawing.value = false
  }
}

function closeResult() {
  showResult.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && showResult.value) closeResult()
}

onMounted(() => {
  loadPrizes()
  loadBalance()
  loadLogs(true)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="au-page lottery-view">
    <!-- 主卡：标题 + 余额 + 抽奖按钮 -->
    <section class="lottery-hero au-anim-up">
      <div class="hero-main">
        <div class="hero-icon-wrap">
          <Gift :size="26" />
        </div>
        <div>
          <h1 class="hero-title">幸运抽奖</h1>
          <p class="hero-sub">
            每次抽奖消耗 <strong>{{ drawCost }}</strong> 积分，奖品包含公益天数、积分与永久白名单
          </p>
        </div>
      </div>
      <div class="hero-side">
        <div class="hero-balance">
          <span class="balance-label">我的积分</span>
          <span class="balance-value">
            <span v-if="balanceLoading" class="au-skeleton sk-num">···</span>
            <template v-else>{{ (balance ?? 0).toLocaleString() }}</template>
          </span>
        </div>
        <button
          class="lottery-btn"
          :disabled="!canDraw"
          @click="handleDraw"
        >
          <span class="lottery-btn-face">
            <span v-if="drawing" class="au-spinner spinner-sm" />
            <PartyPopper v-else :size="17" />
            <span class="lottery-btn-label">
              {{ drawing ? '抽奖中…' : `抽一次 · ${drawCost} 积分` }}
            </span>
          </span>
        </button>
        <p v-if="!balanceLoading && balance !== null && balance < drawCost" class="hero-tip warn">
          积分不足，去签到、邀请好友攒积分吧
        </p>
      </div>
    </section>

    <!-- 奖品宫格 -->
    <section class="au-card au-card-pad au-anim-up" style="animation-delay: 80ms">
      <header class="sec-head">
        <h2 class="sec-title"><Sparkles :size="16" />奖品一览</h2>
        <span class="au-badge au-badge-cyan">{{ prizes.length }} 种奖品</span>
      </header>
      <div v-if="prizesLoading" class="prize-grid" aria-hidden="true">
        <div v-for="i in 4" :key="i" class="prize-card skeleton">
          <span class="au-skeleton sk-icon" />
          <span class="au-skeleton sk-line" />
        </div>
      </div>
      <div v-else-if="!prizes.length" class="au-empty">
        <Gift :size="30" />
        <p>暂无可用奖品</p>
      </div>
      <div v-else class="prize-grid">
        <div
          v-for="p in prizes"
          :key="p.id"
          class="prize-card"
          :class="{ highlight: highlightPrizeId === p.id }"
        >
          <span class="prize-icon" :class="`tone-${p.type}`">
            <component :is="prizeIcon(p.type)" :size="22" />
          </span>
          <strong class="prize-name">{{ p.name }}</strong>
          <span class="prize-desc">{{ prizeDesc(p) }}</span>
        </div>
      </div>
    </section>

    <!-- 我的抽奖记录 -->
    <section class="au-card au-card-pad au-anim-up" style="animation-delay: 140ms">
      <header class="sec-head">
        <h2 class="sec-title"><History :size="16" />我的抽奖记录</h2>
        <span v-if="logsTotal > 0" class="au-badge">共 {{ logsTotal }} 次</span>
      </header>
      <div v-if="logsLoading" class="log-list" aria-hidden="true">
        <div v-for="i in 3" :key="i" class="log-row">
          <span class="au-skeleton sk-line" />
        </div>
      </div>
      <div v-else-if="!logs.length" class="au-empty compact">
        <Ticket :size="26" />
        <p>还没有抽奖记录，快去试试手气吧</p>
      </div>
      <template v-else>
        <ul class="log-list">
          <li v-for="l in logs" :key="l.id" class="log-row">
            <span class="log-prize"><Gift :size="14" />{{ l.prize_name }}</span>
            <span class="log-time">{{ formatTime(l.created_at) }}</span>
          </li>
        </ul>
        <div v-if="hasMoreLogs" class="log-more">
          <button class="au-btn au-btn-ghost au-btn-sm" :disabled="logsMoreLoading" @click="loadMoreLogs">
            <span v-if="logsMoreLoading" class="au-spinner spinner-sm" />
            {{ logsMoreLoading ? '加载中…' : '加载更多' }}
          </button>
        </div>
      </template>
    </section>

    <!-- 中奖弹窗 -->
    <div v-if="showResult && lastResult" class="result-mask" @click.self="closeResult">
      <div class="result-card au-anim-up">
        <span class="result-icon"><PartyPopper :size="34" /></span>
        <h3 class="result-title">恭喜中奖</h3>
        <p class="result-prize">{{ lastResult.prize.name }}</p>
        <p class="result-grant">{{ grantText(lastResult) }}</p>
        <button class="au-btn au-btn-primary" @click="closeResult">收下奖品</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lottery-view { display: flex; flex-direction: column; gap: 1.125rem; }

/* ===== 主卡 ===== */
.lottery-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.25rem;
  flex-wrap: wrap;
  border-radius: var(--au-r-xl);
  border: 1px solid var(--au-border);
  background: var(--au-surface);
  padding: 1.625rem 1.75rem;
}

.hero-main {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  min-width: 0;
}

.hero-icon-wrap {
  width: 54px;
  height: 54px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-lg);
  border: 1px solid var(--au-warning-border);
  background: var(--au-warning-soft);
  color: var(--au-warning);
  flex-shrink: 0;
}

.hero-title { margin: 0; font-size: 1.5rem; font-weight: 700; color: var(--au-text); }
.hero-sub { margin: 0.1875rem 0 0; font-size: 0.8125rem; color: var(--au-text-2); }
.hero-sub strong { color: var(--au-warning); font-weight: 700; }

.hero-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.625rem;
}

.hero-balance {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.balance-label { font-size: 0.8125rem; color: var(--au-text-3); }
.balance-value { font-size: 1.75rem; font-weight: 800; color: var(--au-warning); font-variant-numeric: tabular-nums; }

.hero-tip { margin: 0; font-size: 0.8125rem; color: var(--au-text-2); }
.hero-tip.warn { color: var(--au-warning); }

/* ===== 抽奖按钮（琥珀实色胶囊） ===== */
.lottery-btn {
  display: inline-flex;
  align-items: center;
  border: none;
  padding: 0;
  height: 46px;
  background: none;
  cursor: pointer;
  font: inherit;
}

.lottery-btn-face {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  height: 100%;
  padding: 0 1.625rem;
  border-radius: 999px;
  background: var(--au-gold-a);
  color: var(--au-on-warning);
  font-size: 0.9375rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  transition: transform var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}

.lottery-btn:hover:not(:disabled) .lottery-btn-face { background: var(--au-gold-b); }
.lottery-btn:active:not(:disabled) .lottery-btn-face { transform: scale(0.98); }
.lottery-btn:disabled { cursor: not-allowed; }
.lottery-btn:disabled .lottery-btn-face { opacity: 0.45; }
.lottery-btn-label { white-space: nowrap; }

/* ===== 分区标题 ===== */
.sec-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.sec-title {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  font-size: 1rem;
  font-weight: 700;
  color: var(--au-text);
}

/* ===== 奖品宫格 ===== */
.prize-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

@media (min-width: 768px) {
  .prize-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}

.prize-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4375rem;
  padding: 1.125rem 0.75rem;
  border-radius: var(--au-r-lg);
  border: 1px solid var(--au-border);
  background: var(--au-surface-2);
  text-align: center;
  transition: border-color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.prize-card.highlight {
  border-color: var(--au-warning-border);
  transform: scale(1.03);
  box-shadow: 0 0 0 3px var(--au-warning-soft);
}

.prize-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-lg);
  border: 1px solid var(--au-border);
  background: var(--au-surface-3);
  color: var(--au-text-2);
}

.prize-icon.tone-days {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.prize-icon.tone-points {
  border-color: var(--au-warning-border);
  background: var(--au-warning-soft);
  color: var(--au-warning);
}

.prize-icon.tone-whitelist {
  border-color: var(--au-gold-b);
  background: var(--au-warning-soft);
  color: var(--au-gold-b);
}

.prize-name { font-size: 0.9375rem; font-weight: 700; color: var(--au-text); }
.prize-desc { font-size: 0.75rem; color: var(--au-text-3); }

/* ===== 记录列表 ===== */
.log-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }

.log-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.6875rem 0.25rem;
  border-bottom: 1px solid var(--au-border);
  font-size: 0.875rem;
}

.log-row:last-child { border-bottom: none; }

.log-prize {
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  color: var(--au-text);
  font-weight: 600;
  min-width: 0;
}

.log-prize svg { color: var(--au-warning); flex-shrink: 0; }
.log-time { color: var(--au-text-3); font-size: 0.75rem; flex-shrink: 0; font-variant-numeric: tabular-nums; }

.log-more { display: flex; justify-content: center; margin-top: 0.875rem; }

/* ===== 中奖弹窗 ===== */
.result-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
  background: rgba(0, 0, 0, 0.62);
  backdrop-filter: blur(4px);
}

.result-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  width: min(340px, 100%);
  padding: 2rem 1.5rem 1.5rem;
  border-radius: var(--au-r-xl);
  border: 1px solid var(--au-warning-border);
  background: var(--au-surface);
  text-align: center;
  animation: result-in 0.28s var(--au-ease) both;
}

@keyframes result-in {
  from { opacity: 0; transform: scale(0.92) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.result-icon {
  width: 64px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--au-warning-soft);
  border: 1px solid var(--au-warning-border);
  color: var(--au-warning);
  margin-bottom: 0.25rem;
}

.result-title { margin: 0; font-size: 1.125rem; font-weight: 700; color: var(--au-text); }
.result-prize { margin: 0; font-size: 1.5rem; font-weight: 800; color: var(--au-warning); }
.result-grant { margin: 0 0 0.75rem; font-size: 0.875rem; color: var(--au-text-2); }

/* ===== 骨架 ===== */
.sk-num { display: inline-block; min-width: 3ch; }
.sk-icon { width: 44px; height: 44px; border-radius: var(--au-r-lg); }
.sk-line { display: block; width: 100%; height: 0.875rem; border-radius: var(--au-r-sm); }
</style>
