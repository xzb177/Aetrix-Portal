<script setup lang="ts">
/**
 * 首页 — 内容优先的个人门户
 *
 * 布局（v2.10.3 收敛）：Hero 双栏（左：问候与主行动；右：会员状态卡）
 * → 账号速览条（积分 / 签到 / 邀请）→ 最近入库 → 求片提示 → 继续观看
 * → 「账号与支持」（连接播放器）。
 *
 * v2.10.3：底部那张「消息中心」卡去掉——它和顶栏带角标的音铃列的是同一批未读，
 * 同一件事在首页出现两遍。站内消息统一由顶栏铃铛承担（角标 + 点开预览 + 落到消息
 * 中心），首页不再单独占一条高度，也少一组首页请求。
 *
 * 排序口径：客户端（Infuse / Forward …）已经做得很好的事（继续观看、收藏、
 * 完整片库浏览）在首页只保留一条、且排在后面；门户独有的价值——跟着更新追新、
 * 库里没有就求片、账号与经济状态——放在前面。功能入口统一由顶栏导航承担。
 *
 * v2.10.1：首屏与尾部的两处布局收一收——会员卡里的进度条改成按订阅的真实周期
 * （start_date → end_date）算，不再用「剩余天数猜一个分母」；「账号与支持」的两张卡
 * 宽屏并排成两列，不再一前一后各占一条高度。
 *
 * v2.10.2：预览不再「看起来重复」——同名未读合并成一条并标条数，公告已作为未读
 * 站内信在列时不再重复列（口径在顶栏铃铛里，见 AppHeader.loadMsgPreview）。
 *
 * v2.6.26：站内消息不置顶、也不挤进账号速览条（挤进去会把「数据条」变成混合体）：
 * 速览条只留「账号与经济」（积分 / 签到 / 邀请），消息由顶栏带角标的音铃承担。
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { subscriptionApi, isExpiringSoon, type MySubscription } from '@/api'
import { useToast } from '@/composables/useToast'
import MediaRow from '@/components/media/MediaRow.vue'
import { embyApi as protocolApi, type EmbyItem } from '@/api/emby'
import { pointsApi, checkinApi, inviteApi } from '@/api/economy'
import {
  ChevronRight, Crown, MessageSquareDashed,
  Wallet, CalendarCheck, Gift, Sparkles, Tv, TriangleAlert,
} from 'lucide-vue-next'

const userStore = useUserStore()
const toast = useToast()

const loading = ref(true)
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
// 临期提醒：与后台「到期前 7 天提醒」同一口径（见 backend/reminders.py），
// 让收到站内信的同一刻在首屏也能看到，续费入口就在旁边
const expiringSoon = computed(() => isExpiringSoon(activeSub.value))
const gateOn = computed(() => !!userStore.user?.subscription_required)
const gateMessage = computed(() =>
  gateOn.value && !isMember.value
    ? '当前账号没有生效中的订阅，开通后即可播放全库内容'
    : '',
)
// 公益服（v2.7.0）：这个服免费开放，不需要会员，首屏不再推销会员
const isFreeRealm = computed(() => userStore.isFreeRealm)
const realmNote = computed(
  () => userStore.realmNote || '本服为公益服 · 免费开放：无需开通会员即可观看全库内容。',
)
// 套餐周期已过多少：按订阅自己的 start_date → end_date 算，不再用「剩余天数猜一个分母」——
// 那条旧公式（days_left / (days_left + 30)）画出来的进度与真实周期无关，
// 一个刚买的 30 天套餐会显示成 50%，反而让人以为已经消耗了一半。
const memberProgress = computed(() => {
  const sub = activeSub.value
  if (!sub) return 0
  const start = new Date(sub.start_date).getTime()
  const end = new Date(sub.end_date).getTime()
  if (!start || !end || end <= start) return 0   // 日期不全就不画进度
  const total = end - start
  const used = Math.min(Math.max(Date.now() - start, 0), total)
  return Math.max(1, Math.min(100, Math.round((used / total) * 100)))
})

// 账号速览条：三格经济数据（非按钮），点击进入对应页面。
// 会员状态不进这一条：首屏的会员卡已经在讲同一件事（套餐 / 剩余天数 / 开通或续费），
// 再来一格只是把“会员”在一屏里说两遍。
const accountCells = computed(() => [
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
    // 一位好友都还没邀请时，“0 位好友已加入”读起来像一条数据，
    // 看不出这里能点、后面有奖励；换成一句可执行的说明，邀请才找得到入口
    sub: quickStats.value.invited ? '位好友已加入' : '邀请好友得积分',
    hot: quickStats.value.invited === 0,
  },
])

onMounted(async () => {
  try {
    // v2.10.3：消息与公告不再在首页拉取——那是顶栏铃铛的事（它本来就在每次轮询未读数），
    // 首页少一组请求，也不再重复展示同一批未读
    const [resume, latest, pointsRes, checkinRes, inviteRes, subs] = await Promise.all([
      protocolApi.getResume(12).catch((): EmbyItem[] => []),
      protocolApi.getLatest(16).catch((): EmbyItem[] => []),
      pointsApi.log({ limit: 1 }).catch((): null => null),
      checkinApi.status().catch((): null => null),
      inviteApi.myCode().catch((): null => null),
      subscriptionApi.getMine().catch((): MySubscription[] => []),
    ])
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
            <span v-else-if="isFreeRealm" class="hero-vip hero-free">
              <Sparkles :size="12" />
              公益服 · 免费开放
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

        <!-- 会员状态卡；公益服换成「免费开放」的说明卡，不出现任何购买引导 -->
        <aside v-if="isFreeRealm" class="member-card free-card">
          <div class="member-head">
            <span class="member-badge free">
              <Sparkles :size="13" />
              公益服 · 免费开放
            </span>
          </div>
          <p class="member-plan">无需会员，直接看</p>
          <p class="member-meta">{{ realmNote }}</p>
          <RouterLink to="/media" class="au-btn au-btn-primary au-btn-sm member-cta">
            <Tv :size="14" />
            进入媒体库
          </RouterLink>
        </aside>

        <aside v-else class="member-card" :class="{ inactive: !isMember }">
          <div class="member-head">
            <span class="member-badge" :class="{ warn: expiringSoon }">
              <Crown :size="13" />
              {{ expiringSoon ? '即将到期' : (isMember ? '会员生效中' : '会员专享') }}
            </span>
            <!-- 已开通时给续费入口；未开通时卡内只留一个 CTA，避免同时出现两个开通按钮 -->
            <RouterLink v-if="isMember" to="/wallet?tab=plans" class="member-link">
              续费
              <ChevronRight :size="13" />
            </RouterLink>
          </div>

          <template v-if="isMember && activeSub">
            <p class="member-plan">{{ activeSub.plan_name }}</p>
            <div v-if="memberProgress" class="member-progress" :title="`套餐周期已过 ${memberProgress}%`">
              <div class="member-progress-fill" :style="{ width: memberProgress + '%' }"></div>
            </div>
            <p class="member-meta">
              剩 <strong>{{ activeSub.days_left }}</strong> 天 · {{ activeSub.end_date?.slice(0, 10) }} 到期
            </p>
            <p v-if="expiringSoon" class="member-warn">
              <TriangleAlert :size="13" />
              即将到期，续费后新时长在当前到期日之后叠加
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
      <!-- 账号速览条：积分 / 签到 / 邀请（纯经济数据；会员在首屏会员卡，消息在下方消息卡） -->
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

      <!-- 片库动态：追新在前。
           「最近入库」是门户做、客户端不做的部分（跟着更新追剧），所以放在第一条；
           「继续观看」是客户端已经替我们做了的，保留但排在后面，只做一条。
           收藏 / 观看记录不再是顶栏的一级入口（v2.10.0 方案 A）：它们是媒体库内的分段，
           所以这里既不重复链接、也不另起一区，只在行的「更多」里落到对应分段。 -->
      <MediaRow v-if="latestItems.length" title="最近入库" :items="latestItems.slice(0, 16)" more-to="/media" class="row" />

      <!-- 求片：库里没有的内容，用户在这里能做的事（客户端给不了） -->
      <RouterLink to="/request" class="req-hint">
        <MessageSquareDashed :size="15" class="req-hint-ic" />
        <span class="req-hint-text">没找到想看的？发个求片，入库后在消息中心通知你</span>
        <ChevronRight :size="14" class="req-hint-arrow" />
      </RouterLink>

      <!-- 「更多」落到媒体库的观看记录分段（旧地址 /history 会重定向过来，书签不失效） -->
      <MediaRow v-if="resumeItems.length" title="继续观看" :items="resumeItems.slice(0, 12)" more-to="/media?tab=history" class="row" />

      <div v-if="!resumeItems.length && !latestItems.length" class="au-empty content-empty">
        <Sparkles :size="28" />
        <p>媒体库还没有内容，稍后再来看看</p>
      </div>

      <!-- 分组：账号与支持（个人中心入口在顶栏导航里，这里不再重复） -->
      <div class="section-label">
        <span class="section-title">账号与支持</span>
      </div>

      <!-- 消息入口不在首页：v2.10.3 去掉了底部那张消息卡——它和顶栏带角标的音铃
           列的是同一批未读，同一件事在首页出现两遍。顶栏铃铛已有角标 + 点开预览 + 落到消息中心 -->

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
  background: radial-gradient(ellipse at center, var(--au-primary-soft) 0%, transparent 70%);
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
  background: linear-gradient(150deg, var(--au-primary-soft), var(--au-violet-soft));
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-lg);
  backdrop-filter: blur(12px);
}

.member-card.inactive {
  background: linear-gradient(150deg, var(--au-warning-soft), var(--au-violet-soft));
  border-color: var(--au-warning-border);
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
  background: var(--au-overlay-soft);
  border-radius: var(--au-r-full);
  color: var(--au-primary);
  font-size: 0.6875rem;
  font-weight: 700;
}

/* 临期：与后台到期提醒同色系，一眼能看出“该续费了” */
.member-badge.warn {
  background: var(--au-warning-soft);
  color: var(--au-warning);
}

.member-warn {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  margin: 0.5rem 0 0;
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--au-warning);
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
  background: var(--au-track);
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
  color: var(--au-on-primary);
  font-size: 0.6875rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

/* 公益服（v2.7.0）：免费开放用站点主色，不跟会员的金色混在一起 */
.hero-free {
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  color: var(--au-primary);
}

.free-card {
  background: linear-gradient(150deg, var(--au-primary-soft), var(--au-primary-soft));
}

.free-card .member-badge.free {
  color: var(--au-primary);
}

.hero-sub {
  font-size: 0.875rem;
  color: var(--au-text-3);
  margin: 0 0 1.125rem;
}

/* ==================== 账号速览条 ==================== */

/*
 * 数据条：三格（积分 / 签到 / 邀请），分隔线用「容器底色 + 1px gap + 格子自身底色」，
 * 格子增减或列数变化都不会错位。（会员那一格已去掉，详见脚本里的口径）
 */
.acct-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
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

/* 第一条内容行（最近入库）之后紧跟一条求片提示，行距收到半个身位 */
.row + .req-hint {
  margin-top: -1.125rem;
}

/* ==================== 求片提示（细描边，不做成卡片） ==================== */

.req-hint {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.875rem;
  margin-bottom: 2.25rem;
  border: 1px dashed var(--au-border-strong);
  border-radius: var(--au-r-md);
  background: var(--au-surface);
  color: var(--au-text-2);
  font-size: 0.8125rem;
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease), color var(--au-fast) var(--au-ease);
}

.req-hint:hover {
  border-color: var(--au-primary-border);
  color: var(--au-text);
}

.req-hint-ic {
  flex-shrink: 0;
  color: var(--au-primary);
}

.req-hint-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.req-hint-arrow {
  flex-shrink: 0;
  margin-left: auto;
  color: var(--au-text-4);
}

.req-hint:hover .req-hint-arrow {
  color: var(--au-primary);
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
  /* 这里曾为底部导航坞留 7rem 底部留白；导航坞去掉后，页面尾部不再需要避开任何东西 */
  .acct-cell {
    padding: 0.875rem 0.875rem;
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

  /* 三格的横向留白要比原来四格紧一档，否则窄屏上数字会被挤成省略号 */
  .acct-cell {
    padding: 0.75rem 0.75rem;
  }

  .cell-value {
    font-size: 1.0625rem;
  }
}

/* 最窄的手机（≤380px）：三个格子仍保持一行 —— 换成两行会在数据条中间留一道空白缝 */
@media (max-width: 380px) {
  .acct-cell {
    padding: 0.6875rem 0.5rem;
  }

  .cell-value {
    font-size: 1rem;
  }
}
</style>
