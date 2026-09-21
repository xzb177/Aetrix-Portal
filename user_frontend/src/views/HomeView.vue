<script setup lang="ts">
/**
 * 首页 — 内容优先的个人门户
 *
 * 布局：**站内消息条（置顶）** → Hero 双栏（左：问候与主行动；右：会员状态卡）
 * → 账号速览条 → 「我的内容」（继续观看 / 最近入库）→ 「站点与账号」（连接播放器）
 * 功能入口交给顶部导航 / 底部导航坞，首页只展示「内容」与「状态」。
 *
 * v2.6.22：站内消息**置顶常驻**——它是页面上第一个可点的东西。
 * 先前它排在「最近入库」下面，内容一多就被顶出屏幕；后来挪到速览条之后仍然要往下看，
 * 所以现在直接放到 Hero 之上：未读时整条高亮 + 数字徽标，没有新消息时也是一条安静的入口。
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { messageApi, announcementApi, subscriptionApi, type Announcement, type MySubscription } from '@/api'
import { useToast } from '@/composables/useToast'
import MediaRow from '@/components/media/MediaRow.vue'
import { embyApi as protocolApi, type EmbyItem } from '@/api/emby'
import { pointsApi, checkinApi, inviteApi } from '@/api/economy'
import {
  ChevronRight, Crown, Inbox,
  Wallet, CalendarCheck, Gift, Sparkles, Tv,
} from 'lucide-vue-next'

const userStore = useUserStore()
const toast = useToast()

const loading = ref(true)
const notices = ref<Announcement[]>([])
const unreadCount = ref(0)
const resumeItems = ref<EmbyItem[]>([])
const latestItems = ref<EmbyItem[]>([])
const subscriptions = ref<MySubscription[]>([])

// 经济速览（账号速览条数据）
const quickStats = ref({
  balance: null as number | null,
  streak: null as number | null,
  checkedToday: false,
  invited: null as number | null,
})

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

const user = computed(() => userStore.user)

const activeSub = computed(
  () => subscriptions.value.find(s => s.status === 'active' && s.days_left > 0) || null,
)

// 会员状态卡：订阅中显示套餐与剩余天数；未订阅时展示付费墙引导
const isMember = computed(() => !!activeSub.value)
const gateOn = computed(() => !!userStore.user?.subscription_required)
const gateMessage = computed(() =>
  gateOn.value && !isMember.value
    ? '当前账号没有生效中的订阅，开通后即可播放全库内容'
    : '',
)
const memberProgress = computed(() => {
  const sub = activeSub.value
  if (!sub) return 0
  // 以「已用天数 / 总天数」估算套餐消耗进度（仅用于视觉提示）
  const total = Math.max(sub.days_left, 1)
  return Math.max(6, Math.min(100, Math.round((sub.days_left / (total + 30)) * 100)))
})

// 账号速览条：四格数据（非按钮），点击进入对应页面
const accountCells = computed(() => [
  {
    to: '/wallet?tab=plans',
    icon: Crown,
    label: '会员订阅',
    value: activeSub.value ? activeSub.value.plan_name : '未开通',
    sub: activeSub.value ? `${activeSub.value.end_date?.slice(0, 10)} 到期` : '开通后可播放全库',
    hot: !activeSub.value,
  },
  {
    to: '/wallet',
    icon: Wallet,
    label: '积分余额',
    value: quickStats.value.balance !== null ? quickStats.value.balance.toLocaleString() : '—',
    sub: '签到 · 兑换 · 充值',
    hot: false,
  },
  {
    to: '/checkin',
    icon: CalendarCheck,
    label: '每日签到',
    value: quickStats.value.streak !== null ? `${quickStats.value.streak} 天` : '—',
    sub: quickStats.value.checkedToday ? '今日已签' : '今日未签',
    hot: quickStats.value.streak !== null && !quickStats.value.checkedToday,
  },
  {
    to: '/invite',
    icon: Gift,
    label: '邀请返利',
    value: quickStats.value.invited !== null ? String(quickStats.value.invited) : '—',
    sub: '位好友已加入',
    hot: false,
  },
])

onMounted(async () => {
  try {
    const [unread, anns, resume, latest, pointsRes, checkinRes, inviteRes, subs] = await Promise.all([
      messageApi.getUnreadCount().catch((): { unread_count: number } => ({ unread_count: 0 })),
      announcementApi.getAnnouncements().catch((): Announcement[] => []),
      protocolApi.getResume(12).catch((): EmbyItem[] => []),
      protocolApi.getLatest(16).catch((): EmbyItem[] => []),
      pointsApi.log({ limit: 1 }).catch((): null => null),
      checkinApi.status().catch((): null => null),
      inviteApi.myCode().catch((): null => null),
      subscriptionApi.getMine().catch((): MySubscription[] => []),
    ])
    unreadCount.value = (unread as any)?.unread_count ?? 0
    notices.value = Array.isArray(anns) ? anns : []
    resumeItems.value = resume
    latestItems.value = latest
    if (pointsRes) quickStats.value.balance = pointsRes.balance
    if (checkinRes) {
      quickStats.value.streak = checkinRes.streak
      quickStats.value.checkedToday = checkinRes.checked_today
    }
    if (inviteRes) quickStats.value.invited = inviteRes.invited_count
    subscriptions.value = Array.isArray(subs) ? subs : []
  } catch (err: any) {
    if (err?.response?.status !== 401) {
      toast.error('加载失败，请刷新重试')
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="home-view">
    <!-- Hero：左问候与主行动，右会员状态卡（双栏） -->
    <section class="hero">
      <div class="hero-glow" aria-hidden="true"></div>
      <div class="container hero-grid">
        <div class="hero-inner">
          <!-- 站内消息：不占通栏，也不藏到页尾——就挂在问候语旁边，未读时自己亮 -->
          <div class="hero-top">
            <p class="hero-eyebrow">{{ greeting }}，欢迎回来</p>
            <RouterLink
              to="/messages"
              class="msg-chip"
              :class="{ alert: unreadCount > 0, loading }"
            >
              <span class="msg-chip-ping" aria-hidden="true"></span>
              <Inbox :size="13" />
              <span class="msg-chip-text">
                <template v-if="unreadCount > 0">你有 {{ unreadCount }} 条未读消息</template>
                <template v-else-if="notices.length">公告 · {{ notices[0].title }}</template>
                <template v-else>站内消息</template>
              </span>
              <ChevronRight :size="12" class="msg-chip-go" />
            </RouterLink>
          </div>
          <div class="hero-title-row">
            <h1 class="hero-title">{{ user?.username || '观影用户' }}</h1>
            <span v-if="isMember" class="hero-vip">
              <Crown :size="12" />
              会员
            </span>
          </div>
          <p class="hero-sub">门户账号即 Emby 账号 — 同一凭据登录任意客户端开始观影。</p>

          <!-- 轻量快捷入口：媒体库已在顶栏与底部导航，这里只做文字级入口，不与会员 CTA 抢视觉 -->
          <div class="hero-quick">
            <RouterLink to="/media" class="quick-link">
              进入媒体库
              <ChevronRight :size="13" />
            </RouterLink>
            <template v-if="resumeItems.length">
              <span class="quick-sep" aria-hidden="true"></span>
              <RouterLink :to="`/media/${resumeItems[0].Id}`" class="quick-link">
                继续观看《{{ resumeItems[0].Name }}》
                <ChevronRight :size="13" />
              </RouterLink>
            </template>
          </div>
        </div>

        <!-- 会员状态卡 -->
        <aside class="member-card" :class="{ inactive: !isMember }">
          <div class="member-head">
            <span class="member-badge">
              <Crown :size="13" />
              {{ isMember ? '会员生效中' : '会员专享' }}
            </span>
            <!-- 已开通时给续费入口；未开通时卡内只留一个 CTA，避免同时出现两个开通按钮 -->
            <RouterLink v-if="isMember" to="/wallet?tab=plans" class="member-link">
              续费
              <ChevronRight :size="13" />
            </RouterLink>
          </div>

          <template v-if="isMember && activeSub">
            <p class="member-plan">{{ activeSub.plan_name }}</p>
            <div class="member-progress">
              <div class="member-progress-fill" :style="{ width: memberProgress + '%' }"></div>
            </div>
            <p class="member-meta">
              剩 <strong>{{ activeSub.days_left }}</strong> 天 · {{ activeSub.end_date?.slice(0, 10) }} 到期
            </p>
          </template>

          <template v-else>
            <p class="member-plan">解锁全库影视</p>
            <p class="member-meta">{{ gateMessage || '开通会员后可无限观看全部影视内容' }}</p>
            <RouterLink to="/wallet?tab=plans" class="au-btn au-btn-primary au-btn-sm member-cta">
              <Crown :size="14" />
              立即开通会员
            </RouterLink>
          </template>
        </aside>
      </div>
    </section>

    <main class="container main">
      <!-- 账号速览条：订阅 / 积分 / 签到 / 邀请（数据展示，非按钮堆） -->
      <section class="acct-strip au-card au-anim-up" :class="{ loading }">
        <RouterLink
          v-for="c in accountCells"
          :key="c.to"
          :to="c.to"
          class="acct-cell"
        >
          <span class="cell-label">
            <component :is="c.icon" :size="13" />
            {{ c.label }}
          </span>
          <span class="cell-value">{{ c.value }}</span>
          <span class="cell-sub" :class="{ hot: c.hot }">{{ c.sub }}</span>
        </RouterLink>
      </section>

      <!-- 分组一：我的内容 -->
      <div class="section-label">
        <span class="section-title">我的内容</span>
        <RouterLink to="/favorites" class="section-more">我的收藏 <ChevronRight :size="12" /></RouterLink>
      </div>

      <MediaRow v-if="resumeItems.length" title="继续观看" :items="resumeItems.slice(0, 12)" more-to="/history" class="row" />
      <MediaRow v-if="latestItems.length" title="最近入库" :items="latestItems.slice(0, 16)" class="row" />

      <div v-if="!resumeItems.length && !latestItems.length" class="au-empty content-empty">
        <Sparkles :size="28" />
        <p>媒体库还没有内容，稍后再来看看</p>
      </div>

      <!-- 分组二：站点与账号 -->
      <div class="section-label">
        <span class="section-title">站点与账号</span>
        <RouterLink to="/profile" class="section-more">个人中心 <ChevronRight :size="12" /></RouterLink>
      </div>

      <!-- 播放器入口：凭据与一键导入都在个人中心，首页只留一行指引避免重复 -->
      <RouterLink to="/profile" class="connect-row au-card">
        <span class="connect-row-icon">
          <Tv :size="17" />
        </span>
        <span class="connect-row-body">
          <strong>连接播放器</strong>
          <em>Infuse / Forward 等客户端的服务器地址、账号与一键导入都在个人中心</em>
        </span>
        <ChevronRight :size="16" class="connect-row-arrow" />
      </RouterLink>
    </main>
  </div>
</template>

<style scoped>
.home-view {
  min-height: 100vh;
  color: var(--au-text);
}

.container {
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 1.25rem;
}

/* ==================== Hero ==================== */

.hero {
  position: relative;
  padding: 2.75rem 0 2rem;
  border-bottom: 1px solid var(--au-border);
  overflow: hidden;
}

.hero-glow {
  position: absolute;
  top: -40%;
  right: -8%;
  width: 480px;
  height: 360px;
  background: radial-gradient(ellipse at center, rgba(34, 211, 238, 0.1) 0%, transparent 70%);
  filter: blur(52px);
  pointer-events: none;
}

.hero-grid {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(260px, 0.65fr);
  gap: 1.75rem;
  align-items: center;
}

.hero-inner {
  position: relative;
  min-width: 0;
}

/* 轻量快捷入口（文字级，不抢 CTA） */
.hero-quick {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.625rem;
}

.quick-link {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  font-size: 0.8125rem;
  color: var(--au-text-2);
  text-decoration: none;
  transition: color var(--au-fast) var(--au-ease);
}

.quick-link:hover {
  color: var(--au-primary);
}

.quick-link svg {
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.quick-link:hover svg {
  color: var(--au-primary);
  transform: translateX(2px);
}

.quick-sep {
  width: 1px;
  height: 12px;
  background: var(--au-border-strong);
}

/* ==================== 会员状态卡 ==================== */

.member-card {
  min-width: 0;
  padding: 1.125rem 1.25rem 1.25rem;
  background: linear-gradient(150deg, rgba(34, 211, 238, 0.1), rgba(167, 139, 250, 0.08));
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-lg);
  backdrop-filter: blur(12px);
}

.member-card.inactive {
  background: linear-gradient(150deg, rgba(251, 191, 36, 0.1), rgba(167, 139, 250, 0.06));
  border-color: rgba(251, 191, 36, 0.3);
}

.member-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.member-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  padding: 0.1875rem 0.5625rem;
  background: rgba(7, 11, 18, 0.45);
  border-radius: var(--au-r-full);
  color: var(--au-primary);
  font-size: 0.6875rem;
  font-weight: 700;
}

.member-card.inactive .member-badge {
  color: var(--au-warning);
}

.member-link {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  text-decoration: none;
  transition: color var(--au-fast) var(--au-ease);
}

.member-link:hover {
  color: var(--au-primary);
}

.member-plan {
  margin: 0 0 0.5rem;
  font-size: 1.0625rem;
  font-weight: 700;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-progress {
  height: 5px;
  margin-bottom: 0.5rem;
  background: rgba(7, 11, 18, 0.5);
  border-radius: 3px;
  overflow: hidden;
}

.member-progress-fill {
  height: 100%;
  background: var(--au-gradient);
  border-radius: 3px;
}

.member-meta {
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--au-text-3);
}

.member-meta strong {
  color: var(--au-primary);
  font-variant-numeric: tabular-nums;
}

.member-cta {
  margin-top: 0.75rem;
  width: 100%;
}

/* ==================== 分组标签 ==================== */

.section-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin: 0 0 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--au-border);
}

.section-title {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--au-text-4);
}

.section-more {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  text-decoration: none;
  transition: color var(--au-fast) var(--au-ease);
}

.section-more:hover {
  color: var(--au-primary);
}

.content-empty {
  padding: 2rem 1rem;
}

.hero-eyebrow {
  font-size: 0.8125rem;
  color: var(--au-primary);
  margin: 0 0 0.4375rem;
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}

.hero-title {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--au-text);
  margin: 0;
}

.hero-vip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1875rem 0.5625rem;
  background: var(--au-gradient-warm);
  color: #fff;
  font-size: 0.6875rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

.hero-sub {
  font-size: 0.875rem;
  color: var(--au-text-3);
  margin: 0 0 1.125rem;
}

/* ==================== 账号速览条 ==================== */

.acct-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-bottom: 2rem;
  transition: opacity var(--au-fast) var(--au-ease);
}

.acct-strip.loading {
  opacity: 0.45;
  pointer-events: none;
}

.acct-cell {
  display: flex;
  flex-direction: column;
  gap: 0.1875rem;
  padding: 1rem 1.25rem;
  min-width: 0;
  text-decoration: none;
  border-right: 1px solid var(--au-border);
  transition: background var(--au-fast) var(--au-ease);
}

.acct-cell:nth-child(4n) {
  border-right: none;
}

.acct-cell:hover {
  background: var(--au-surface-2);
}

.cell-label {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.cell-label svg {
  color: var(--au-primary);
  flex-shrink: 0;
}

.cell-value {
  font-size: 1.1875rem;
  font-weight: 700;
  line-height: 1.2;
  color: var(--au-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-variant-numeric: tabular-nums;
}

.cell-sub {
  font-size: 0.6875rem;
  color: var(--au-text-4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-sub.hot {
  color: var(--au-warning);
  font-weight: 600;
}

/* ==================== 内容行 ==================== */

.main {
  padding: 2rem 1.25rem 3.5rem;
}

.row {
  margin-bottom: 2.25rem;
}

/* ==================== 站内消息：问候语旁的胶囊（不占通栏）==================== */

.hero-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 0.4375rem;
}

.hero-top .hero-eyebrow {
  margin: 0;
}

.msg-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  max-width: 100%;
  padding: 0.3125rem 0.6875rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  color: var(--au-text-2);
  font-size: 0.75rem;
  font-weight: 600;
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease),
    color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}

.msg-chip.loading {
  opacity: 0.5;
}

.msg-chip:hover {
  color: var(--au-text);
  border-color: var(--au-border-strong);
}

.msg-chip.alert {
  color: var(--au-warning);
  border-color: rgba(251, 191, 36, 0.34);
  background: rgba(251, 191, 36, 0.1);
}

.msg-chip.alert:hover {
  border-color: var(--au-warning);
  background: rgba(251, 191, 36, 0.16);
}

.msg-chip-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-chip-ping {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--au-border-strong);
  transition: background var(--au-fast) var(--au-ease);
}

.msg-chip.alert .msg-chip-ping {
  background: var(--au-warning);
  animation: chip-ping 2.6s ease-out infinite;
}

.msg-chip-go {
  flex-shrink: 0;
  opacity: 0.65;
}

@keyframes chip-ping {
  0% { box-shadow: 0 0 0 0 rgba(251, 191, 36, 0.45); }
  70% { box-shadow: 0 0 0 6px rgba(251, 191, 36, 0); }
  100% { box-shadow: 0 0 0 0 rgba(251, 191, 36, 0); }
}

/* ==================== 播放器入口（单行，详情在个人中心） ==================== */

.connect-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1.125rem;
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease);
}

.connect-row:hover {
  border-color: var(--au-primary-border);
}

.connect-row-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: 10px;
  color: var(--au-primary);
}

.connect-row-body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
  flex: 1;
}

.connect-row-body strong {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.connect-row-body em {
  font-style: normal;
  font-size: 0.75rem;
  color: var(--au-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.connect-row-arrow {
  flex-shrink: 0;
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease);
}

.connect-row:hover .connect-row-arrow {
  color: var(--au-primary);
}

/* ==================== 响应式 ==================== */

@media (max-width: 900px) {
  .main {
    padding-bottom: 7rem;
  }
}

@media (max-width: 860px) {
  .hero-grid {
    grid-template-columns: 1fr;
    gap: 1.25rem;
  }

  .member-card {
    padding: 1rem 1.125rem 1.125rem;
  }
}

@media (max-width: 760px) {
  .acct-strip {
    grid-template-columns: repeat(2, 1fr);
  }

  .acct-cell:nth-child(4n) {
    border-right: 1px solid var(--au-border);
  }

  .acct-cell:nth-child(2n) {
    border-right: none;
  }

  .acct-cell:nth-child(-n+2) {
    border-bottom: 1px solid var(--au-border);
  }
}

@media (max-width: 640px) {
  /* 窄屏：胶囊只留「几条未读」，标题不再往右挤 */
  .hero-top .hero-eyebrow {
    width: 100%;
  }

  .msg-chip-text {
    max-width: 15ch;
  }

  .hero {
    padding: 1.75rem 0 1.5rem;
  }

  .hero-title {
    font-size: 1.5rem;
  }

  .hero-sub {
    font-size: 0.8125rem;
    margin-bottom: 1rem;
  }

  .acct-cell {
    padding: 0.875rem 1rem;
  }

  .cell-value {
    font-size: 1.0625rem;
  }
}
</style>
