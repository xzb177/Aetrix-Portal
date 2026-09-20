<script setup lang="ts">
/**
 * 首页 — 内容优先的个人门户
 *
 * 布局（v2.5.2 优化）：Hero 双栏（左：问候与主行动；右：会员状态卡）
 * 账号速览数据条 → 「我的内容」（继续观看 / 最近入库）→ 「站点与设备」（动态 / 连接播放器）
 * 功能入口交给顶部导航 / 底部导航坞，首页只展示「内容」与「状态」。
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { embyApi, messageApi, announcementApi, subscriptionApi, type AccountCard, type Announcement, type MySubscription } from '@/api'
import { useToast } from '@/composables/useToast'
import MediaRow from '@/components/media/MediaRow.vue'
import { embyApi as protocolApi, type EmbyItem } from '@/api/emby'
import { pointsApi, checkinApi, inviteApi } from '@/api/economy'
import {
  Play, Copy, Check, Key, Lock, ChevronRight, Crown, Megaphone,
  Wallet, CalendarCheck, Gift, Sparkles, Tv,
} from 'lucide-vue-next'

const userStore = useUserStore()
const toast = useToast()

const serverOrigin = window.location.origin

const loading = ref(true)
const account = ref<AccountCard | null>(null)
const notices = ref<Announcement[]>([])
const unreadCount = ref(0)
const resumeItems = ref<EmbyItem[]>([])
const latestItems = ref<EmbyItem[]>([])
const subscriptions = ref<MySubscription[]>([])
const copiedField = ref('')

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
const embyUsername = computed(() => account.value?.emby_username || user.value?.username || '—')
const serverUrl = computed(() => account.value?.base_url || serverOrigin)
const hasPassword = computed(() => !!account.value?.has_password)
const importSchemes = computed(() => account.value?.import_schemes || {})
const hasSchemes = computed(() => Object.keys(importSchemes.value).length > 0)

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

async function copyText(text: string, field: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = field
    toast.success('已复制')
    setTimeout(() => { if (copiedField.value === field) copiedField.value = '' }, 1600)
  } catch {
    toast.error('复制失败')
  }
}

const copyAll = () => {
  const lines = [
    `服务器: ${serverUrl.value}`,
    `用户名: ${embyUsername.value}`,
    '密码: 与门户登录密码相同',
  ]
  copyText(lines.join('\n'), 'all')
}

// 播放器一键导入
const openScheme = (url: string) => {
  window.location.href = url
}

onMounted(async () => {
  try {
    const [card, unread, anns, resume, latest, pointsRes, checkinRes, inviteRes, subs] = await Promise.all([
      embyApi.getAccountCard(),
      messageApi.getUnreadCount().catch((): { unread_count: number } => ({ unread_count: 0 })),
      announcementApi.getAnnouncements().catch((): Announcement[] => []),
      protocolApi.getResume(12).catch((): EmbyItem[] => []),
      protocolApi.getLatest(16).catch((): EmbyItem[] => []),
      pointsApi.log({ limit: 1 }).catch((): null => null),
      checkinApi.status().catch((): null => null),
      inviteApi.myCode().catch((): null => null),
      subscriptionApi.getMine().catch((): MySubscription[] => []),
    ])
    account.value = card
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
          <p class="hero-eyebrow">{{ greeting }}，欢迎回来</p>
          <div class="hero-title-row">
            <h1 class="hero-title">{{ user?.username || '观影用户' }}</h1>
            <span v-if="isMember" class="hero-vip">
              <Crown :size="12" />
              会员
            </span>
          </div>
          <p class="hero-sub">门户账号即 Emby 账号 — 同一凭据登录任意客户端开始观影。</p>
          <div class="hero-actions">
            <RouterLink class="btn btn-primary" to="/media">
              <Play :size="16" />
              进入媒体库
            </RouterLink>
            <RouterLink v-if="resumeItems.length" class="btn btn-ghost" :to="`/media/${resumeItems[0].Id}`">
              继续观看
            </RouterLink>
          </div>
        </div>

        <!-- 会员状态卡 -->
        <aside class="member-card" :class="{ inactive: !isMember }">
          <div class="member-head">
            <span class="member-badge">
              <Crown :size="13" />
              {{ isMember ? '会员生效中' : '会员专享' }}
            </span>
            <RouterLink to="/wallet?tab=plans" class="member-link">
              {{ isMember ? '续费' : '开通' }}
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

      <!-- 分组二：站点与设备 -->
      <div class="section-label">
        <span class="section-title">站点与设备</span>
      </div>

      <!-- 站点动态：单行细条 -->
      <RouterLink v-if="notices.length || unreadCount > 0" to="/messages" class="news-strip au-card">
        <Megaphone :size="15" class="news-icon" />
        <span class="news-text">
          <template v-if="notices.length">
            {{ notices[0].title }}<template v-if="notices.length > 1"> 等 {{ notices.length }} 条公告</template>
          </template>
          <template v-else>查看站点动态与私信</template>
        </span>
        <span v-if="unreadCount > 0" class="news-badge">{{ unreadCount }} 条未读</span>
        <ChevronRight :size="15" class="news-arrow" />
      </RouterLink>

      <!-- 连接播放器：凭据 + 一键导入，合并为一张卡 -->
      <section class="connect-card au-card">
        <header class="connect-head">
          <span class="connect-title">
            <Tv :size="16" />
            连接播放器
          </span>
          <p class="connect-desc">在 Infuse、Forward 等 Emby 客户端中用以下凭据登录，或一键导入</p>
        </header>

        <div class="cred-strip">
          <button
            v-for="row in [
              { key: 'server', label: '服务器', value: serverUrl, mono: true },
              { key: 'user', label: '用户名', value: embyUsername, mono: true },
              { key: 'pwd', label: '密码', value: hasPassword ? '与门户密码相同' : '未设置', mono: false },
            ]"
            :key="row.key"
            class="cred-chip"
            :title="`点击复制${row.label}`"
            @click="row.key !== 'pwd' && copyText(row.value, row.key)"
          >
            <span class="cred-chip-label">{{ row.label }}</span>
            <span class="cred-chip-value mono" :class="{ dim: row.key === 'pwd' }">{{ row.value }}</span>
            <Check v-if="copiedField === row.key" :size="13" class="chip-ok" />
            <Copy v-else-if="row.key !== 'pwd'" :size="13" class="chip-copy" />
            <Lock v-else :size="13" class="chip-copy" />
          </button>
        </div>
        <p class="cred-hint">
          <Key :size="12" />
          凭据与门户账号一致，可在个人中心管理 ·
          <button class="hint-link" @click="copyAll">复制全部</button>
        </p>

        <div v-if="hasSchemes" class="scheme-row">
          <button
            v-for="(url, name) in importSchemes"
            :key="name"
            class="scheme-btn"
            @click="openScheme(url)"
          >
            <Sparkles :size="14" />
            {{ name }}
          </button>
        </div>
      </section>
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

.hero-actions {
  display: flex;
  gap: 0.625rem;
  flex-wrap: wrap;
}

.btn-ghost {
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  color: var(--au-text);
}

.btn-ghost:hover {
  background: var(--au-surface-3);
  border-color: var(--au-border-strong);
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

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  height: 40px;
  padding: 0 1.125rem;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
  border: none;
}

.btn-primary {
  background: linear-gradient(135deg, var(--au-primary), var(--au-primary-strong));
  color: #05141c;
  font-weight: 600;
  box-shadow: 0 4px 14px var(--au-primary-glow);
}

.btn-primary:hover {
  box-shadow: 0 6px 18px var(--au-primary-glow);
  transform: translateY(-1px);
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

/* ==================== 站点动态条 ==================== */

.news-strip {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.8125rem 1.125rem;
  margin-bottom: 1.25rem;
  text-decoration: none;
  color: var(--au-text-2);
  font-size: 0.8125rem;
  transition: border-color var(--au-fast) var(--au-ease);
}

.news-strip:hover {
  border-color: var(--au-primary-border);
}

.news-icon {
  color: var(--au-primary);
  flex-shrink: 0;
}

.news-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.news-badge {
  padding: 0.125rem 0.5rem;
  background: var(--au-warning-soft);
  color: var(--au-warning);
  border-radius: var(--au-r-full);
  font-size: 0.6875rem;
  font-weight: 600;
  flex-shrink: 0;
}

.news-arrow {
  color: var(--au-text-4);
  flex-shrink: 0;
  transition: color var(--au-fast) var(--au-ease);
}

.news-strip:hover .news-arrow {
  color: var(--au-primary);
}

/* ==================== 连接播放器 ==================== */

.connect-card {
  padding: 1.125rem 1.25rem 1.25rem;
}

.connect-head {
  margin-bottom: 0.875rem;
}

.connect-title {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.connect-title svg {
  color: var(--au-primary);
}

.connect-desc {
  margin: 0.25rem 0 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.cred-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.cred-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  max-width: 100%;
  height: 36px;
  padding: 0 0.75rem;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}

.cred-chip:hover {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
}

.cred-chip-label {
  flex-shrink: 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.cred-chip-value {
  font-size: 0.75rem;
  color: var(--au-text-2);
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cred-chip-value.dim {
  letter-spacing: 0.12em;
}

.chip-copy,
.chip-ok {
  flex-shrink: 0;
  color: var(--au-text-4);
}

.cred-chip:hover .chip-copy {
  color: var(--au-primary);
}

.chip-ok {
  color: var(--au-primary);
}

.cred-hint {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin: 0.625rem 0 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.hint-link {
  background: none;
  border: none;
  padding: 0;
  font-size: inherit;
  color: var(--au-primary);
  cursor: pointer;
}

.hint-link:hover {
  text-decoration: underline;
}

.scheme-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.875rem;
  padding-top: 0.875rem;
  border-top: 1px dashed var(--au-border);
}

.scheme-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  height: 34px;
  padding: 0 0.875rem;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-sm);
  color: var(--au-text-2);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.scheme-btn:hover {
  background: var(--au-primary-soft);
  border-color: var(--au-primary-border);
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
