<script setup lang="ts">
/**
 * 首页 — 服务台口径的个人门户（不再是"内容货架"）
 *
 * 背景：用户实际在 Infuse / Forward 等第三方客户端里看片，web 端首页的任务不是
 * "让人找片"，而是"让人看上片"——新用户引导、会员状态、求片、帮助。
 *
 * 布局：Hero 双栏（左：按用户状态分三种形态；右：会员状态卡）
 * → 新手任务（有未完成步骤时才出现）→ 账号速览条（积分 / 签到 / 邀请）
 * → 我的面板（观影数据 / 进行中的事项 / 正在播放）→ 最近上新（上新公告）
 * → 帮助中心（连接播放器 / 求片 / 联系客服）。
 *
 * Hero 左栏三形态：未开通显示"三步看片"指引（开通→下载客户端→一键导入），
 * 已开通/公益服显示服务台快捷入口（求片/连接播放器）。看片在客户端完成，
 * 首页不再造"继续观看"（观看记录保留在媒体库的 tab 里）。
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
 *
 * v2.34.0：速览条下面补上「我的面板」——观影数据（累计时长 / 播放次数 / 看过影片）、
 * 进行中的事项（我的求片 / 我的工单，带数量与入口）、以及**只有本账号真在播时才出现**的
 * 「正在播放」（带一键结束）。这三件都是门户独有、客户端给不了的：客户端只知道「这台机器在放
 * 什么」，不知道账号名下还有哪些设备在放、求片处理到哪一步、工单有没有人回。
 *
 * 面板只做「一眼看到状态 + 点进去办事」：完整的会话清单与设备管理仍在个人中心（控制面板），
 * 与顶栏铃铛 / 消息中心的分工一致——同一个语义，摘要在一处、全量在另一处，不会两处都铺全。
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  subscriptionApi, isExpiringSoon, embyApi, mediaSeekApi, ticketApi,
  type MySubscription, type WatchStats, type MyPlaybackSession,
} from '@/api'
import { useToast } from '@/composables/useToast'
import MediaRow from '@/components/media/MediaRow.vue'
import { embyApi as protocolApi, type EmbyItem } from '@/api/emby'
import { pointsApi, checkinApi, inviteApi } from '@/api/economy'
import {
  ChevronRight, Crown, MessageSquareDashed, LayoutDashboard, Inbox,
  Wallet, CalendarCheck, Gift, Sparkles, Tv, TriangleAlert,
  Clock, Clapperboard, Film, Ticket, MonitorSmartphone, CircleStop,
  Rocket, Check,
} from 'lucide-vue-next'

const userStore = useUserStore()
const toast = useToast()

const loading = ref(true)
const latestItems = ref<EmbyItem[]>([])
const subscriptions = ref<MySubscription[]>([])

// 经济速览（账号速览条数据）
const quickStats = ref({
  balance: null as number | null,
  streak: null as number | null,
  checkedToday: false,
  invited: null as number | null,
})

// ===== 我的面板（v2.34.0）：观影数据 / 进行中的事项 / 正在播放 =====
// 「正在播放」在这里只是**状态**（有会话才渲染），不是管理清单——完整会话列表在个人中心。
const stats = ref<WatchStats | null>(null)
const seekCounts = ref<{ active: number; completed: number } | null>(null)
const ticketCounts = ref<{ active: number; settled: number } | null>(null)
const sessions = ref<MyPlaybackSession[]>([])
const stoppingSession = ref('')

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

/** 累计观看时长：不足 1 小时按分钟显示，别让新用户一上来就看到「0 小时」 */
function formatWatchTime(seconds?: number | null) {
  if (!seconds || seconds <= 0) return '—'
  const hours = Math.floor(seconds / 3600)
  if (hours >= 1) return `${hours} 小时`
  return `${Math.max(1, Math.round(seconds / 60))} 分钟`
}

const watchCells = computed(() => [
  { key: 'time', icon: Clock, label: '累计观看', value: formatWatchTime(stats.value?.total_seconds) },
  { key: 'plays', icon: Clapperboard, label: '播放次数', value: stats.value ? String(stats.value.total_plays) : '—' },
  { key: 'items', icon: Film, label: '看过影片', value: stats.value ? String(stats.value.watched_items) : '—' },
])

// 进行中的事项：只列「自己提交的东西处理到哪了」。数量为 0 时显示「—」而不显示 0，
// sub 再说清下一步会发生什么——一个孤零零的 0 读起来像「功能坏了」，不像「没事可做」。
const todoRows = computed(() => {
  const seek = seekCounts.value
  const seekActive = seek?.active ?? 0
  const ticket = ticketCounts.value
  const ticketActive = ticket?.active ?? 0
  return [
    {
      key: 'seek',
      to: '/request',
      icon: MessageSquareDashed,
      label: '我的求片',
      value: seekActive > 0 ? String(seekActive) : '—',
      sub: !seek
        ? '查看求片进度'
        : seekActive > 0
          ? '入库后会在消息中心通知你'
          : seek.completed > 0
            ? `已入库 ${seek.completed} 部`
            : '还没提交过求片',
      hot: seekActive > 0,
    },
    {
      key: 'ticket',
      to: '/tickets',
      icon: Ticket,
      label: '我的工单',
      value: ticketActive > 0 ? String(ticketActive) : '—',
      sub: !ticket
        ? '查看工单状态'
        : ticketActive > 0
          ? '客服回复会推送到消息中心'
          : ticket.settled > 0
            ? `已处理 ${ticket.settled} 个`
            : '遇到问题可以提交工单',
      hot: ticketActive > 0,
    },
  ]
})

// 新手任务：门户是"服务台"不是"内容货架"，新用户的核心 friction 是
// "付了钱不会配置客户端"。步骤能自动判定的自动判定（开通看订阅、
// 有过播放记录视为已连接播放器），全部完成后整段隐藏，老用户不被打扰。
const onboardingTasks = computed(() => [
  {
    key: 'member',
    title: '开通会员',
    desc: '解锁全库影视资源',
    done: isMember.value || isFreeRealm.value,
    to: '/wallet?tab=plans',
  },
  {
    key: 'connect',
    title: '连接播放器',
    desc: '在个人中心一键导入服务器地址与账号',
    done: (stats.value?.total_plays || 0) > 0,
    to: '/profile',
  },
  {
    key: 'watch',
    title: '看第一部片',
    desc: '在 Infuse 等客户端开始播放',
    done: (stats.value?.watched_items || 0) > 0,
    to: '/media',
  },
])
const onboardingDoneCount = computed(() => onboardingTasks.value.filter(t => t.done).length)

async function stopSession(session: MyPlaybackSession) {
  stoppingSession.value = session.session_key
  try {
    await embyApi.stopSession(session.session_key)
    toast.success(`已结束「${session.device || '未知设备'}」上的播放`)
    sessions.value = sessions.value.filter((s) => s.session_key !== session.session_key)
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '结束播放失败')
  } finally {
    stoppingSession.value = ''
  }
}

onMounted(async () => {
  try {
    // v2.10.3：消息与公告不再在首页拉取——那是顶栏铃铛的事（它本来就在每次轮询未读数），
    // 首页少一组请求，也不再重复展示同一批未读
    const [latest, pointsRes, checkinRes, inviteRes, subs,
      statsRes, seekRes, ticketsRes, sessionsRes] = await Promise.all([
      protocolApi.getLatest(16).catch((): EmbyItem[] => []),
      pointsApi.log({ limit: 1 }).catch((): null => null),
      checkinApi.status().catch((): null => null),
      inviteApi.myCode().catch((): null => null),
      subscriptionApi.getMine().catch((): MySubscription[] => []),
      // 面板数据：任一项失败都各归各的（catch 成 null），不会连带整页报错
      embyApi.getStats().catch((): WatchStats | null => null),
      mediaSeekApi.getMyRequests().catch((): null => null),
      ticketApi.getMyTickets().catch((): null => null),
      embyApi.getSessions().catch((): { sessions: MyPlaybackSession[] } | null => null),
    ])
    latestItems.value = latest
    if (pointsRes) quickStats.value.balance = pointsRes.balance
    if (checkinRes) {
      quickStats.value.streak = checkinRes.streak
      quickStats.value.checkedToday = checkinRes.checked_today
    }
    if (inviteRes) quickStats.value.invited = inviteRes.invited_count
    subscriptions.value = Array.isArray(subs) ? subs : []

    stats.value = statsRes
    if (seekRes) {
      const rows = seekRes.requests || []
      seekCounts.value = {
        active: rows.filter((r) => r.status === 'pending' || r.status === 'approved').length,
        completed: rows.filter((r) => r.status === 'completed').length,
      }
    }
    if (Array.isArray(ticketsRes)) {
      ticketCounts.value = {
        active: ticketsRes.filter((t) => t.status === 'open' || t.status === 'pending').length,
        settled: ticketsRes.filter((t) => t.status === 'closed' || t.status === 'resolved').length,
      }
    }
    sessions.value = sessionsRes?.sessions || []
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
          <!-- 未开通：三步看片指引。门户最大的 friction 是"付了钱不会配置客户端"，
               所以首屏不讲会员权益、讲"怎么看上片"；开通 CTA 在右侧会员卡里只留一个，
               这里不再重复，避免同一屏出现两个开通按钮 -->
          <template v-if="!isMember && !isFreeRealm">
            <p class="hero-sub">三步开始观影：</p>
            <ol class="hero-steps">
              <li>
                <span class="step-num">1</span>
                <span class="step-body"><strong>开通会员</strong><em>解锁全库影视资源</em></span>
              </li>
              <li>
                <span class="step-num">2</span>
                <span class="step-body"><strong>下载播放器</strong><em>Infuse / Forward 等 Emby 客户端</em></span>
              </li>
              <li>
                <span class="step-num">3</span>
                <span class="step-body"><strong>一键导入</strong><em>在个人中心导入服务器地址与账号</em></span>
              </li>
            </ol>
            <div class="hero-cta">
              <RouterLink to="/profile" class="au-btn au-btn-ghost au-btn-sm">
                查看连接教程
              </RouterLink>
            </div>
          </template>

          <!-- 已开通 / 公益服：服务台口径。看片在第三方客户端完成，
               首页只给办事入口，不再造一个"继续观看"（那是客户端的事） -->
          <template v-else>
            <p class="hero-sub">门户账号即 Emby 账号 — 在 Infuse 等客户端登录即可观影。</p>
            <div class="hero-quick">
              <RouterLink to="/request" class="quick-link">
                求片
                <ChevronRight :size="13" />
              </RouterLink>
              <span class="quick-sep" aria-hidden="true"></span>
              <RouterLink to="/profile" class="quick-link">
                连接播放器
                <ChevronRight :size="13" />
              </RouterLink>
            </div>
          </template>
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
      <!-- 新手任务：只在还有未完成步骤时出现，全部完成后整段隐藏。
           首页是服务台，新用户的第一件事是"连上播放器看上片"，不是"浏览内容" -->
      <section v-if="!loading && onboardingTasks.some(t => !t.done)" class="onboard-card au-card au-anim-up">
        <header class="panel-head">
          <span class="panel-title">
            <Rocket :size="15" />
            新手任务
          </span>
          <span class="panel-hint">{{ onboardingDoneCount }}/{{ onboardingTasks.length }}</span>
        </header>
        <div class="onboard-list">
          <div v-for="t in onboardingTasks" :key="t.key" class="onboard-row" :class="{ done: t.done }">
            <span class="onboard-check">
              <Check v-if="t.done" :size="14" />
            </span>
            <span class="onboard-body">
              <strong>{{ t.title }}</strong>
              <em>{{ t.desc }}</em>
            </span>
            <RouterLink v-if="!t.done" :to="t.to" class="au-btn au-btn-primary au-btn-sm">
              去完成
            </RouterLink>
            <span v-else class="onboard-done-text">已完成</span>
          </div>
        </div>
      </section>

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

      <!-- 我的面板（v2.34.0）：观影数据 / 进行中的事项 / 正在播放（只在本账号真在播时出现）。
           口径：这些是门户独有、客户端给不了的——账号名下的求片与工单状态、跨设备在播概况。
           完整会话清单与设备管理仍在个人中心，这里只给「一眼看到 + 一键处理」。 -->
      <section class="panel-grid au-anim-up" :class="{ loading }">
        <div class="panel-card">
          <header class="panel-head">
            <span class="panel-title">
              <LayoutDashboard :size="15" />
              我的观影
            </span>
            <RouterLink to="/media?tab=history" class="panel-more">
              观看记录
              <ChevronRight :size="13" />
            </RouterLink>
          </header>
          <div class="panel-stats">
            <div v-for="c in watchCells" :key="c.key" class="panel-stat">
              <strong>{{ c.value }}</strong>
              <span class="panel-stat-label">
                <component :is="c.icon" :size="12" />
                {{ c.label }}
              </span>
            </div>
          </div>
        </div>

        <div class="panel-card">
          <header class="panel-head">
            <span class="panel-title">
              <Inbox :size="15" />
              进行中的事项
            </span>
          </header>
          <div class="todo-list">
            <RouterLink v-for="t in todoRows" :key="t.key" :to="t.to" class="todo-row">
              <span class="todo-icon">
                <component :is="t.icon" :size="15" />
              </span>
              <span class="todo-body">
                <span class="todo-label">{{ t.label }}</span>
                <span class="todo-sub">{{ t.sub }}</span>
              </span>
              <span class="todo-value" :class="{ hot: t.hot }">{{ t.value }}</span>
              <ChevronRight :size="14" class="todo-arrow" />
            </RouterLink>
          </div>
        </div>
      </section>

      <!-- 正在播放：有会话才出现（一条状态，不是管理清单）；完整清单在个人中心 -->
      <section v-if="sessions.length" class="panel-card playing-card au-anim-up">
        <header class="panel-head">
          <span class="panel-title">
            <MonitorSmartphone :size="15" />
            正在播放
          </span>
          <span class="panel-hint">{{ sessions.length }} 个会话</span>
        </header>
        <div class="playing-list">
          <div v-for="s in sessions" :key="s.session_key" class="playing-row">
            <div class="playing-main">
              <div class="playing-title">
                <RouterLink :to="`/media/${s.item_id}`">{{ s.item }}</RouterLink>
                <span v-if="s.is_paused" class="playing-tag">已暂停</span>
              </div>
              <div class="playing-meta">
                <span>{{ s.device || '未知设备' }}</span>
                <template v-if="s.client">
                  <span class="dot">·</span>
                  <span>{{ s.client }}</span>
                </template>
                <template v-if="s.play_method">
                  <span class="dot">·</span>
                  <span>{{ s.play_method === 'Transcode' ? '转码' : '直连' }}</span>
                </template>
              </div>
              <div class="playing-bar">
                <div class="playing-fill" :style="{ width: s.progress + '%' }"></div>
              </div>
            </div>
            <button
              class="au-btn au-btn-danger au-btn-sm"
              :disabled="stoppingSession === s.session_key"
              @click="stopSession(s)"
            >
              <CircleStop :size="13" />
              {{ stoppingSession === s.session_key ? '结束中' : '结束' }}
            </button>
          </div>
        </div>
      </section>

      <!-- 片库动态：「最近上新」是上新公告（告诉用户片库在持续更新），不是浏览入口——
           浏览与继续观看是第三方客户端的事，观看记录在媒体库的 tab 里保留 -->
      <MediaRow v-if="latestItems.length" title="最近上新" :items="latestItems.slice(0, 16)" more-to="/media" class="row" />

      <div v-if="!latestItems.length" class="au-empty content-empty">
        <Sparkles :size="28" />
        <p>媒体库还没有内容，稍后再来看看</p>
      </div>

      <!-- 分组：帮助中心。首页是服务台，底部给办事入口；
           账号类入口（订阅/设备/安全）在顶栏「我的」里，这里不重复 -->
      <div class="section-label">
        <span class="section-title">帮助中心</span>
      </div>

      <div class="help-list au-card">
        <RouterLink to="/profile" class="help-row">
          <span class="help-row-icon">
            <Tv :size="17" />
          </span>
          <span class="help-row-body">
            <strong>连接播放器</strong>
            <em>Infuse / Forward 等客户端的服务器地址、账号与一键导入</em>
          </span>
          <ChevronRight :size="16" class="help-row-arrow" />
        </RouterLink>
        <RouterLink to="/request" class="help-row">
          <span class="help-row-icon">
            <MessageSquareDashed :size="17" />
          </span>
          <span class="help-row-body">
            <strong>求片</strong>
            <em>库里没有想看的？提交求片，入库后在消息中心通知你</em>
          </span>
          <ChevronRight :size="16" class="help-row-arrow" />
        </RouterLink>
        <RouterLink to="/tickets" class="help-row">
          <span class="help-row-icon">
            <Ticket :size="17" />
          </span>
          <span class="help-row-body">
            <strong>联系客服</strong>
            <em>遇到问题提交工单，客服会尽快回复</em>
          </span>
          <ChevronRight :size="16" class="help-row-arrow" />
        </RouterLink>
      </div>
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

/* 三步看片指引（未开通用户首屏）：数字序号 + 两行文字，移动端不挤 */
.hero-steps {
  list-style: none;
  margin: 0 0 1.25rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.hero-steps li {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.step-num {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  color: var(--au-primary);
  font-size: 0.75rem;
  font-weight: 700;
}

.step-body {
  display: flex;
  flex-direction: column;
  gap: 0.0625rem;
  min-width: 0;
}

.step-body strong {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.step-body em {
  font-style: normal;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.hero-cta {
  display: flex;
  gap: 0.625rem;
  flex-wrap: wrap;
}

/* ==================== 新手任务 ==================== */

.onboard-card {
  margin-bottom: 1.5rem;
  padding: 1.125rem 1.25rem;
}

.onboard-list {
  display: flex;
  flex-direction: column;
}

.onboard-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 0;
}

.onboard-row + .onboard-row {
  border-top: 1px dashed var(--au-border);
}

.onboard-row.done {
  opacity: 0.75;
}

.onboard-check {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid var(--au-border-strong);
  color: transparent;
}

.onboard-row.done .onboard-check {
  background: var(--au-primary-soft);
  border-color: var(--au-primary-border);
  color: var(--au-primary);
}

.onboard-body {
  display: flex;
  flex-direction: column;
  gap: 0.0625rem;
  min-width: 0;
  flex: 1;
}

.onboard-body strong {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.onboard-row.done .onboard-body strong {
  text-decoration: line-through;
  text-decoration-color: var(--au-text-4);
}

.onboard-body em {
  font-style: normal;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.onboard-done-text {
  font-size: 0.75rem;
  color: var(--au-text-4);
  flex-shrink: 0;
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

/* ==================== 我的面板（v2.34.0） ==================== */

.panel-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1rem;
  margin-bottom: 2rem;
  transition: opacity var(--au-fast) var(--au-ease);
}

/* 与账号速览条同一口径：加载中先压暗，避免一闪而过的「—」被读成「没有数据」 */
.panel-grid.loading {
  opacity: 0.45;
  pointer-events: none;
}

.panel-card {
  padding: 1rem 1.125rem 1.125rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.875rem;
}

.panel-title {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--au-text);
}

.panel-title svg {
  color: var(--au-primary);
  flex-shrink: 0;
}

.panel-hint {
  font-size: 0.75rem;
  color: var(--au-text-4);
  white-space: nowrap;
}

.panel-more {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  text-decoration: none;
  transition: color var(--au-fast) var(--au-ease);
}

.panel-more:hover {
  color: var(--au-primary);
}

.panel-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
}

.panel-stat {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.panel-stat strong {
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.2;
  color: var(--au-text);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.panel-stat-label {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.panel-stat-label svg {
  flex-shrink: 0;
}

/* 进行中的事项：两行（求片 / 工单），每行一条真实状态 */
.todo-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.todo-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.625rem 0.75rem;
  border-radius: var(--au-r-md);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}

.todo-row:hover {
  border-color: var(--au-primary-border);
  background: var(--au-surface-3);
}

.todo-icon {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-sm);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.todo-body {
  display: flex;
  flex-direction: column;
  gap: 0.0625rem;
  min-width: 0;
  flex: 1;
}

.todo-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text);
}

.todo-sub {
  font-size: 0.6875rem;
  color: var(--au-text-4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.todo-value {
  flex-shrink: 0;
  font-size: 1rem;
  font-weight: 700;
  color: var(--au-text-3);
  font-variant-numeric: tabular-nums;
}

.todo-value.hot {
  color: var(--au-warning);
}

.todo-arrow {
  flex-shrink: 0;
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease);
}

.todo-row:hover .todo-arrow {
  color: var(--au-primary);
}

/* 正在播放：跨整行的一条状态卡 */
.playing-card {
  margin-bottom: 2rem;
}

.playing-list {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.playing-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.75rem 0.875rem;
  border-radius: var(--au-r-md);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
}

.playing-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.playing-title {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
}

.playing-title a {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.playing-title a:hover {
  color: var(--au-primary);
}

.playing-tag {
  flex-shrink: 0;
  padding: 0.0625rem 0.375rem;
  border-radius: var(--au-r-full);
  background: var(--au-warning-soft);
  color: var(--au-warning);
  font-size: 0.6875rem;
  font-weight: 600;
}

.playing-meta {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  min-width: 0;
}

.playing-meta .dot {
  color: var(--au-text-4);
}

.playing-bar {
  height: 4px;
  background: var(--au-track);
  border-radius: 2px;
  overflow: hidden;
}

.playing-fill {
  height: 100%;
  background: var(--au-gradient);
  border-radius: 2px;
}

/* ==================== 内容行 ==================== */

.main {
  padding: 2rem 1.25rem 3.5rem;
}

.row {
  margin-bottom: 2.25rem;
}

/* ==================== 帮助中心（三行入口，行间虚线分隔） ==================== */

.help-list {
  overflow: hidden;
}

.help-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1.125rem;
  text-decoration: none;
  transition: background var(--au-fast) var(--au-ease);
}

.help-row + .help-row {
  border-top: 1px dashed var(--au-border);
}

.help-row:hover {
  background: var(--au-surface-2);
}

.help-row-icon {
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

.help-row-body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
  flex: 1;
}

.help-row-body strong {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.help-row-body em {
  font-style: normal;
  font-size: 0.75rem;
  color: var(--au-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.help-row-arrow {
  flex-shrink: 0;
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.help-row:hover .help-row-arrow {
  color: var(--au-primary);
  transform: translateX(2px);
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

  /* 窄屏：两块面板竖排（观影数据在上、进行中的事项在下） */
  .panel-grid {
    grid-template-columns: 1fr;
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
