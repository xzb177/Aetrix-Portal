<script setup lang="ts">
/**
 * 每日签到 — 打卡日历式 UI，连签加成，积分到账动效
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import {
  CalendarCheck, Flame, Zap, CalendarDays, PartyPopper, ChevronRight,
} from 'lucide-vue-next'
import { checkinApi, pointsApi, type CheckinStatus, type PointsLogEntry } from '@/api/economy'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const loading = ref(true)
const status = ref<CheckinStatus | null>(null)
const signing = ref(false)
const justSigned = ref(false)
const rewardPreview = ref(0)

// 签到获得积分的流水（用于日历标记与最近列表）
const checkinLogs = ref<{ id: number; amount: number; created_at: string | null }[]>([])

// ===== 当月日历 =====
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth())

const monthDays = computed(() => {
  const first = new Date(year.value, month.value, 1)
  const startWeekday = first.getDay() // 0=周日
  const daysInMonth = new Date(year.value, month.value + 1, 0).getDate()
  const cells: (null | { day: number; isToday: boolean; isFuture: boolean })[] = []
  for (let i = 0; i < startWeekday; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) {
    const isToday = d === now.getDate() && month.value === now.getMonth() && year.value === now.getFullYear()
    cells.push({ day: d, isToday, isFuture: false })
  }
  return cells
})

const monthLabel = computed(() => `${year.value} 年 ${month.value + 1} 月`)

// 本月已签到的日期集合（来自真实签到流水）
const checkedDays = computed(() => {
  const days = new Set<number>()
  for (const l of checkinLogs.value) {
    if (!l.created_at) continue
    const d = new Date(l.created_at)
    if (d.getFullYear() === year.value && d.getMonth() === month.value) {
      days.add(d.getDate())
    }
  }
  return days
})

// 今日预期奖励（若未签）
const todayReward = computed(() => {
  if (!status.value) return 0
  const { base_points, streak_bonus, streak_max_bonus, streak, checked_today } = status.value
  const nextStreak = checked_today ? streak : streak + 1
  const bonus = Math.min(streak_bonus * (nextStreak - 1), streak_max_bonus)
  return base_points + bonus
})

async function load() {
  loading.value = true
  try {
    const emptyLog = { total: 0, balance: 0, logs: [] as PointsLogEntry[] }
    const [s, log] = await Promise.all([
      checkinApi.status(),
      pointsApi.log({ limit: 50, type_filter: 'checkin' }).catch(() => emptyLog),
    ])
    status.value = s
    rewardPreview.value = todayReward.value
    checkinLogs.value = log.logs.map(l => ({ id: l.id, amount: l.amount, created_at: l.created_at }))
  } catch {
    /* 静默 */
  } finally {
    loading.value = false
  }
}

async function handleSign() {
  if (signing.value || status.value?.checked_today) return
  signing.value = true
  try {
    const res = await checkinApi.doCheckin()
    justSigned.value = true
    toast.success(res.message || `签到成功 +${res.points_awarded}`)
    await load()
    setTimeout(() => { justSigned.value = false }, 2600)
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '签到失败，请稍后重试')
  } finally {
    signing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="au-page checkin-view">
    <!-- 主打卡卡：左文右数据的横向布局 -->
    <section class="sign-card au-anim-up" :class="{ signed: status?.checked_today }">
      <div class="sign-glow" aria-hidden="true" />

      <div class="sign-body">
        <!-- 左：打卡主区 -->
        <div class="sign-main">
          <div class="sign-icon-row">
            <div class="sign-icon-wrap" :class="{ pulsing: !status?.checked_today && !loading }">
              <PartyPopper v-if="justSigned || status?.checked_today" :size="26" />
              <CalendarCheck v-else :size="26" />
            </div>
            <div>
              <h1 class="sign-title">
                <template v-if="loading">加载中…</template>
                <template v-else-if="justSigned">签到成功！</template>
                <template v-else-if="status?.checked_today">今日已签到</template>
                <template v-else>今日还没签到</template>
              </h1>
              <p class="sign-sub">
                <template v-if="!loading && status">
                  连续签到 <strong>{{ status.streak }}</strong> 天
                </template>
                <template v-else>…</template>
              </p>
            </div>
          </div>

          <button
            class="au-btn sign-btn"
            :class="{ done: status?.checked_today || justSigned }"
            :disabled="loading || signing || status?.checked_today"
            @click="handleSign"
          >
            <span v-if="signing" class="au-spinner spinner-sm" />
            <template v-else-if="justSigned">+{{ rewardPreview }} 积分到账 🎉</template>
            <template v-else-if="status?.checked_today">明日再来</template>
            <template v-else>立即签到 +{{ rewardPreview }}</template>
          </button>
        </div>

        <div class="sign-divider" aria-hidden="true" />

        <!-- 右：连签进度与奖励规则 -->
        <div v-if="status" class="sign-side">
          <div class="streak-row">
            <div
              v-for="i in 7"
              :key="i"
              class="streak-dot"
              :class="{ lit: i <= Math.min(status.streak, 7) }"
              :title="`连续第 ${i} 天`"
            >
              <Flame v-if="i <= Math.min(status.streak, 7)" :size="12" />
              <span v-else>{{ i }}</span>
            </div>
          </div>
          <p class="streak-hint">
            今日可得 <strong class="reward-num">+{{ justSigned ? status.base_points : rewardPreview }}</strong> 积分
          </p>
          <p class="streak-rule">
            基础 +{{ status.base_points }} / 天 · 连签每天多 +{{ status.streak_bonus }}（封顶 +{{ status.streak_max_bonus }}）
          </p>
        </div>
      </div>
    </section>

    <!-- 日历 + 流水 -->
    <div class="bottom-grid">
      <section class="au-card au-card-pad cal au-anim-up" style="animation-delay: 80ms">
        <header class="cal-head">
          <h3><CalendarDays :size="16" /> {{ monthLabel }}</h3>
          <span class="au-badge au-badge-cyan">本月已签 {{ checkedDays.size }} 天</span>
        </header>
        <div class="cal-week">
          <span v-for="w in ['日', '一', '二', '三', '四', '五', '六']" :key="w">{{ w }}</span>
        </div>
        <div class="cal-grid">
          <template v-for="(cell, i) in monthDays" :key="i">
            <span v-if="cell === null" />
            <span
              v-else
              class="cal-day"
              :class="{ today: cell.isToday, done: checkedDays.has(cell.day) && !cell.isToday }"
            >{{ cell.day }}</span>
          </template>
        </div>
        <p class="cal-note">日历标记最近签到记录，连续签到以实际记录为准</p>
      </section>

      <section class="au-card au-card-pad gains au-anim-up" style="animation-delay: 140ms">
        <header class="cal-head">
          <h3><Zap :size="16" /> 最近签到奖励</h3>
          <RouterLink to="/wallet?tab=log" class="gains-more">
            全部流水
            <ChevronRight :size="13" />
          </RouterLink>
        </header>
        <div v-if="!checkinLogs.length" class="au-empty compact">
          <CalendarCheck :size="26" />
          <p>还没有签到记录</p>
        </div>
        <ul v-else class="gains-list">
          <li v-for="g in checkinLogs.slice(0, 7)" :key="g.id">
            <span class="gains-dot" />
            <span class="gains-desc">签到奖励</span>
            <span class="gains-time">{{ (g.created_at || '').slice(0, 10) }}</span>
            <strong class="gains-amt">+{{ g.amount }}</strong>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.checkin-view { display: flex; flex-direction: column; gap: 1.125rem; }

/* ===== 主卡（左文右数据） ===== */
.sign-card {
  position: relative;
  overflow: hidden;
  border-radius: var(--au-r-xl);
  border: 1px solid var(--au-primary-border);
  background: linear-gradient(160deg, rgba(34, 211, 238, 0.12), rgba(167, 139, 250, 0.1) 60%, rgba(10, 16, 26, 0.4));
  backdrop-filter: blur(14px);
  padding: 1.625rem 1.75rem;
}
.sign-card.signed { border-color: rgba(52, 211, 153, 0.35); }

.sign-glow {
  position: absolute;
  top: -40%;
  left: 50%;
  transform: translateX(-50%);
  width: 420px;
  height: 280px;
  background: radial-gradient(ellipse, rgba(34, 211, 238, 0.2), transparent 70%);
  filter: blur(36px);
  pointer-events: none;
}

.sign-body {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr);
  gap: 1.75rem;
  align-items: center;
}

.sign-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1rem;
  min-width: 0;
}

.sign-icon-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.sign-icon-wrap {
  width: 54px;
  height: 54px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: var(--au-gradient);
  color: #05141c;
  box-shadow: 0 8px 28px var(--au-primary-glow);
  flex-shrink: 0;
}
.sign-icon-wrap.pulsing { animation: au-pulse-soft 1.8s ease-in-out infinite; }

.sign-title { margin: 0; font-size: 1.3125rem; font-weight: 800; color: var(--au-text); letter-spacing: -0.01em; }
.sign-sub { margin: 0.1875rem 0 0; font-size: 0.8125rem; color: var(--au-text-2); }
.sign-sub strong { color: var(--au-text); font-weight: 700; }

.sign-btn {
  height: 44px;
  padding: 0 1.75rem;
  font-size: 0.9375rem;
}
.sign-btn.done {
  background: var(--au-success-soft);
  color: var(--au-success);
  box-shadow: none;
  cursor: default;
}

.sign-divider {
  background: var(--au-border);
  height: 100%;
  min-height: 72px;
}

/* 右侧：进度与规则 */
.sign-side {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  min-width: 0;
}

.streak-row {
  display: flex;
  gap: 0.4375rem;
  flex-wrap: wrap;
}

.streak-dot {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  color: var(--au-text-4);
  font-size: 0.6875rem;
  font-weight: 600;
  transition: all var(--au-med);
}
.streak-dot.lit {
  background: var(--au-gradient);
  border-color: transparent;
  color: #05141c;
  box-shadow: 0 3px 12px var(--au-primary-glow);
}

.streak-hint { margin: 0.125rem 0 0; font-size: 0.8125rem; color: var(--au-text-2); }
.reward-num {
  background: var(--au-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent !important;
  font-weight: 800;
  font-size: 0.9375rem;
}
.streak-rule { margin: 0; font-size: 0.6875rem; color: var(--au-text-4); }

.spinner-sm { width: 15px; height: 15px; border-width: 2px; }

/* ===== 底部 ===== */
.bottom-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 1.125rem;
  align-items: start;
}

.cal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.cal-head h3 {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 700;
  color: var(--au-text);
}
.cal-head svg { color: var(--au-primary); }

.gains-more {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.75rem;
  color: var(--au-text-4);
  text-decoration: none;
  transition: color var(--au-fast) var(--au-ease);
}
.gains-more:hover { color: var(--au-primary); }

.cal-week {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 0.25rem;
  margin-bottom: 0.375rem;
}
.cal-week span {
  text-align: center;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  font-weight: 600;
}

.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 0.25rem;
}

.cal-day {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-sm);
  font-size: 0.8125rem;
  color: var(--au-text-2);
  font-variant-numeric: tabular-nums;
}
.cal-day.today {
  background: var(--au-gradient);
  color: #05141c;
  font-weight: 800;
  box-shadow: 0 3px 10px var(--au-primary-glow);
}
.cal-day.done {
  background: var(--au-primary-soft);
  color: var(--au-primary);
  font-weight: 600;
}

.cal-note { margin: 0.875rem 0 0; font-size: 0.6875rem; color: var(--au-text-4); }

.gains-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.gains-list li {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.625rem 0;
  border-bottom: 1px solid var(--au-border);
  font-size: 0.8125rem;
}
.gains-list li:last-child { border-bottom: none; }

.gains-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--au-gradient);
  flex-shrink: 0;
}
.gains-desc { color: var(--au-text-2); flex: 1; }
.gains-time { color: var(--au-text-4); font-size: 0.6875rem; }
.gains-amt { color: var(--au-success); font-variant-numeric: tabular-nums; }

.au-empty.compact { padding: 2rem 1rem; }
.au-empty.compact p { margin: 0; font-size: 0.8125rem; }

@media (max-width: 720px) {
  .bottom-grid { grid-template-columns: 1fr; }
  .sign-card { padding: 1.375rem 1.25rem; }
  .sign-body { grid-template-columns: 1fr; gap: 1.25rem; }
  .sign-divider { height: 1px; width: 100%; min-height: 0; }
}
</style>
