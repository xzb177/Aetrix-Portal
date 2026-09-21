<script setup lang="ts">
/**
 * 首页 — 内容优先的个人门户
 *
 * 布局：Hero 双栏（左：问候与主行动；右：会员状态卡）→ 账号速览条
 * → 「我的内容」（继续观看 / 最近入库）→ 「站点与账号」（连接播放器）
 * 功能入口交给顶部导航 / 底部导航坞，首页只展示「内容」与「状态」。
 *
 * v2.6.26：站内消息既不置顶、也不挤进账号速览条（挤进去会把「数据条」变成混合体，
 * 而且仍在首屏最显眼处）。改为：
 *   - 账号速览条只留「账号与经济」四格（会员 / 积分 / 签到 / 邀请），语义干净；
 *   - 消息中心做成「站点与账号」区的第一张卡：一行标题 + 最多两条最新内容（未读优先，
 *     没未读时显示最新公告）+ 未读胶囊，永远在页面上，但不抢会员 CTA 的视觉；
 *   - 随时随地可进的地方是顶栏那个带角标的音铃（点开先看预览）。
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  messageApi, announcementApi, subscriptionApi,
  type Announcement, type MySubscription, type StationMessage,
} from '@/api'
import { useToast } from '@/composables/useToast'
import MediaRow from '@/components/media/MediaRow.vue'
import { embyApi as protocolApi, type EmbyItem } from '@/api/emby'
import { pointsApi, checkinApi, inviteApi } from '@/api/economy'
import {
  ChevronRight, Crown, Inbox, Megaphone,
  Wallet, CalendarCheck, Gift, Sparkles, Tv,
} from 'lucide-vue-next'

const userStore = useUserStore()
const toast = useToast()

const loading = ref(true)
const notices = ref<Announcement[]>([])
const recentMessages = ref<StationMessage[]>([])
const unreadCount = ref(0)

// 消息卡里的时间：只给相对时间，避免首页出现一串精确到秒的时间戳
function relTime(iso?: string): string {
  if (!iso) return ''
  const at = new Date(iso).getTime()
  if (!at) return ''
  const diff = Date.now() - at
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return iso.slice(0, 10)
}

// 消息卡的两行：未读优先，名额不满时补一条最新公告（没有未读时就是纯公告）
const inboxItems = computed(() => {
  const rows: { key: string; title: string; time: string; icon: unknown; unread: boolean }[] = []
  for (const m of recentMessages.value.filter((x) => !x.is_read).slice(0, 2)) {
    rows.push({ key: `m${m.id}`, title: m.title, time: relTime(m.created_at), icon: Inbox, unread: true })
  }
  if (rows.length < 2 && notices.value.length) {
    const a = notices.value[0]
    rows.push({ key: `a${a.id}`, title: a.title, time: relTime(a.created_at), icon: Megaphone, unread: false })
  }
  return rows.slice(0, 2)
})
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
    alert: false,
  },
  {
    to: '/wallet',
    icon: Wallet,
    label: '积分余额',
    value: quickStats.value.balance !== null ? quickStats.value.balance.toLocaleString() : '—',
    sub: '签到 · 兑换 · 充值',
    hot: false,
    alert: false,
  },
  {
    to: '/checkin',
    icon: CalendarCheck,
    label: '每日签到',
    value: quickStats.value.streak !== null ? `${quickStats.value.streak} 天` : '—',
    sub: quickStats.value.checkedToday ? '今日已签' : '今日未签',
    hot: quickStats.value.streak !== null && !quickStats.value.checkedToday,
    alert: false,
  },
  {
    to: '/invite',
    icon: Gift,
    label: '邀请返利',
    value: quickStats.value.invited !== null ? String(quickStats.value.invited) : '—',
    // 一位好友都还没邀请时，“0 位好友已加入”读起来像一条数据，
    // 看不出这里能点、后面有奖励；换成一句可执行的说明，邀请才找得到入口
    sub: quickStats.value.invited ? '位好友已加入' : '邀请好友得积分',
    hot: quickStats.value.invited === 0,
    alert: false,
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
    recentMessages.value = await messageApi
      .getMessages({ limit: 3 })
      .catch((): StationMessage[] => [])
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
          <p class="hero-eyebrow">{{ greeting }}，欢迎回来</p>
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
      <!-- 账号速览条：会员 / 积分 / 签到 / 邀请（纯账号与经济数据；消息不在其中，见下方消息卡） -->
      <section class="acct-strip au-card au-anim-up" :class="{ loading }">
        <RouterLink
          v-for="c in accountCells"
          :key="c.to"
          :to="c.to"
          class="acct-cell"
          :class="{ alert: c.alert }"
        >
          <span class="cell-label">
            <component :is="c.icon" :size="13" />
            {{ c.label }}
            <span v-if="c.alert" class="cell-dot" aria-hidden="true"></span>
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

      <!-- 消息中心：不占首屏头条，但总是在“站点与账号”区的第一眼看得到；随时可进的是顶栏音铃 -->
      <RouterLink to="/messages" class="inbox-card au-card" :class="{ alert: unreadCount > 0 }">
        <span class="inbox-ic">
          <Inbox :size="17" />
          <span v-if="unreadCount > 0" class="inbox-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
        </span>
        <span class="inbox-main">
          <span class="inbox-head">
            <strong>消息中心</strong>
            <em v-if="unreadCount > 0" class="inbox-state unread">{{ unreadCount }} 条未读</em>
            <em v-else class="inbox-state">已全部读完</em>
          </span>
          <span v-if="inboxItems.length" class="inbox-list">
            <span v-for="row in inboxItems" :key="row.key" class="inbox-item">
              <component :is="row.icon" :size="12" class="inbox-item-ic" :class="{ hot: row.unread }" />
              <span class="inbox-item-title">{{ row.title }}</span>
              <span class="inbox-item-time">{{ row.time }}</span>
            </span>
          </span>
          <span v-else class="inbox-empty">工单回复、求片进度与会员提醒都会出现在这里</span>
        </span>
        <ChevronRight :size="16" class="inbox-arrow" />
      </RouterLink>

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

/*
 * 数据条：固定四格（会员 / 积分 / 签到 / 邀请），分隔线用「容器底色 + 1px gap + 格子自身底色」，
 * 格子增减或列数变化都不会错位。
 */
.acct-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--au-border);
  margin-bottom: 2rem;
  overflow: hidden;
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
  padding: 1rem 1.125rem;
  min-width: 0;
  background: var(--au-surface);
  text-decoration: none;
  transition: background var(--au-fast) var(--au-ease);
}

.acct-cell:hover {
  background: var(--au-surface-2);
}

/* 有未读：只用左侧一道细亮线与一个呼吸点提示，不做整格高亮（不与会员 CTA 抢视觉） */
.acct-cell.alert {
  background: linear-gradient(180deg, rgba(251, 191, 36, 0.07), transparent 70%);
}

.acct-cell.alert .cell-value {
  color: var(--au-warning);
}

.cell-label {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.cell-dot {
  width: 5px;
  height: 5px;
  margin-left: auto;
  border-radius: 50%;
  background: var(--au-warning);
  animation: cell-dot 2.6s ease-out infinite;
}

@keyframes cell-dot {
  0% { box-shadow: 0 0 0 0 rgba(251, 191, 36, 0.5); }
  70% { box-shadow: 0 0 0 5px rgba(251, 191, 36, 0); }
  100% { box-shadow: 0 0 0 0 rgba(251, 191, 36, 0); }
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

/* ==================== 消息中心卡 ==================== */
/*
 * 一行标题 + 最多两条内容：信息密度和「连接播放器」卡一致，所以放同一区看起来是一套。
 * 不做整卡高亮，只在有未读时给左侧一道细亮线与暖色值标签——注意力归会员 CTA。
 */
.inbox-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1.125rem;
  margin-bottom: 0.75rem;
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.inbox-card:hover {
  border-color: var(--au-primary-border);
  transform: translateY(-1px);
}

.inbox-card.alert::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12%;
  bottom: 12%;
  width: 2px;
  border-radius: 0 2px 2px 0;
  background: var(--au-warning);
}

.inbox-ic {
  position: relative;
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

.inbox-card.alert .inbox-ic {
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.32);
  color: var(--au-warning);
}

.inbox-badge {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--au-warning);
  color: #1a1206;
  font-size: 0.625rem;
  font-weight: 800;
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}

.inbox-main {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  flex: 1;
}

.inbox-head {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  min-width: 0;
}

.inbox-head strong {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.inbox-state {
  font-style: normal;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.inbox-state.unread {
  color: var(--au-warning);
  font-weight: 700;
}

.inbox-list {
  display: flex;
  flex-direction: column;
  gap: 0.1875rem;
  min-width: 0;
}

.inbox-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.inbox-item-ic {
  flex-shrink: 0;
  color: var(--au-text-4);
}

.inbox-item-ic.hot {
  color: var(--au-warning);
}

.inbox-item-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--au-text-2);
}

.inbox-item-time {
  flex-shrink: 0;
  margin-left: auto;
  color: var(--au-text-4);
  font-variant-numeric: tabular-nums;
}

.inbox-empty {
  font-size: 0.75rem;
  color: var(--au-text-4);
}

.inbox-arrow {
  flex-shrink: 0;
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.inbox-card:hover .inbox-arrow {
  color: var(--au-primary);
  transform: translateX(2px);
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
  /* 2 列：分隔线由 gap 自动产生，不需要按格数算 nth-child */
  .acct-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
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
