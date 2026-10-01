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
 *
 * v2.42.1（借鉴纸片人控制台的设计语言）：首页改版为「资产仪表盘」口径——
 * 顶栏常驻积分 / 订阅资产 pill；hero 收敛成一张带装饰光晕的欢迎卡；
 * 原账号速览条升级为四段式资产卡（积分 / 订阅 / 观影数据），每种资产一个固定
 * 功能色（青 / 金 / 紫），从 pill → 卡片图标 / 数字 / CTA 全链路同色；
 * hero 右侧的会员卡并入订阅资产卡（进度条按真实周期算的口径不变）。
 * ≤768px 由底部导航坞（AppDock）承担主导航，卡片单列。
 *
 * v2.42.2：参考的纸片人 dashboard 只有账户资产与服务入口、没有媒体浏览，
 * 首页据此砍掉「最近上新」海报墙与空态卡——媒体浏览统一走媒体库独立页
 * （顶栏 / 底部坞的「媒体库」入口不变）。首页收敛为：欢迎卡 → 说明条幅
 * （置顶公告 / 公益服 / 未开通三态）→ 资产卡 → 新手任务 → 面板 → 帮助。
 * 同时接入双主题（跟随系统 / 白日 / 黑暗，见 useTheme.ts）：组件全部消费
 * --au-* 原料（在浅色下有独立调色），性能上移动端不启用卡片级 backdrop-blur、
 * 脉动与进度条动画只走 opacity/transform。
 */
import { ref, computed, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { RouterLink } from 'vue-router'
// 观影数据卡无落地页（媒体库已下线），同模板里 RouterLink 与 div 二选一
import { useUserStore } from '@/stores/user'
import {
  subscriptionApi, isExpiringSoon, embyApi, mediaSeekApi, ticketApi, announcementApi,
  type MySubscription, type WatchStats, type MyPlaybackSession, type Announcement,
} from '@/api'
import { useToast } from '@/composables/useToast'
import Modal from '@/components/ui/Modal.vue'
import { pointsApi, checkinApi, inviteApi } from '@/api/economy'
import {
  ChevronRight, Crown, MessageSquareDashed, Inbox,
  Sparkles, Tv, TriangleAlert, Zap,
  Clapperboard, Ticket, MonitorSmartphone, CircleStop,
  RotateCcw, X, Megaphone,
} from 'lucide-vue-next'

const userStore = useUserStore()
const toast = useToast()

const loading = ref(true)
const subscriptions = ref<MySubscription[]>([])

/** 说明条幅（v2.42.2）：置顶公告优先，其余按运营位兜底；内容型条幅可关闭 */
const banners = ref<Announcement[]>([])
const dismissedBannerIds = ref<number[]>([])

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

// 资产卡（v2.42.1，四段式）：积分 / 订阅 / 观影数据。每种资产一个固定功能色（tone），
// 从卡片图标 → 数字 / CTA 全链路同色：积分 = 品牌青，订阅 = 会员金，
// 观影数据 = 极光紫。卡底统一「灰色说明 + 功能色 CTA」，全站一个模式。
const assetCards = computed(() => {
  const st = stats.value

  // 观影数据的大数字：≥1 小时按小时、不足 1 小时按分钟（别让新用户一上来就看到「0」）
  let watchValue = '—'
  let watchUnit = ''
  if (st && st.total_seconds > 0) {
    const hours = Math.floor(st.total_seconds / 3600)
    if (hours >= 1) {
      watchValue = String(hours)
      watchUnit = '小时'
    } else {
      watchValue = String(Math.max(1, Math.round(st.total_seconds / 60)))
      watchUnit = '分钟'
    }
  }

  const memberCard = isMember.value && activeSub.value
    ? {
        value: String(activeSub.value.days_left),
        unit: '天',
        progress: memberProgress.value,
        desc: `${activeSub.value.plan_name} · ${activeSub.value.end_date?.slice(0, 10) || ''}到期`,
        note: expiringSoon.value ? '续费后新时长在到期日之后叠加' : '会员权益全库通用',
        footer: '续费',
        badge: expiringSoon.value ? '临期' : '生效中',
        hot: expiringSoon.value,
      }
    : isFreeRealm.value
      ? {
          value: '免费',
          unit: '',
          progress: null,
          desc: userStore.realmNote || '公益服开放中，无需订阅即可观看全库内容',
          note: '本服不需要会员',
          footer: '查看套餐',
          badge: null,
          hot: false,
        }
      : {
          value: '未开通',
          unit: '',
          progress: null,
          desc: gateMessage.value || '开通会员后可无限观看全部影视内容',
          note: '开通后解锁全库',
          footer: '立即开通',
          badge: null,
          hot: false,
        }

  return [
    {
      key: 'points',
      to: '/wallet',
      icon: Zap,
      // 功能色定稿（v2.42.4）：积分=金（钱的语义）、订阅=青（品牌主色）、
      // 观影数据=紫；顶栏 pill 已删（v2.42.8），资产卡是唯一的常驻资产入口
      tone: 'amber',
      title: '积分',
      value: quickStats.value.balance !== null ? quickStats.value.balance.toLocaleString() : '—',
      unit: '',
      progress: null,
      desc: '签到、邀请与兑换都能攒积分',
      // 连击天数并进说明行，数据不丢（原速览条的独立「每日签到」格不再重复）
      note: quickStats.value.checkedToday
        ? (quickStats.value.streak ? `今日已签 · 连续 ${quickStats.value.streak} 天` : '今日已签 · 明天再来')
        : '今天还没签到',
      footer: '去钱包',
      badge: quickStats.value.checkedToday ? null : '今日未签',
      // 未签时徽章走警示色（hot），与订阅临期同一套提醒语言
      hot: !quickStats.value.checkedToday,
    },
    {
      key: 'member',
      to: '/wallet?tab=plans',
      icon: Crown,
      tone: 'cyan',
      title: '订阅',
      ...memberCard,
    },
    {
      key: 'watch',
      to: '',
      icon: Clapperboard,
      tone: 'violet',
      title: '观影数据',
      value: watchValue,
      unit: watchUnit,
      progress: null,
      desc: `播放 ${st ? st.total_plays : '—'} 次 · 看过 ${st ? st.watched_items : '—'} 部`,
      note: '在 Infuse 等客户端继续观影',
      footer: '',
      badge: null,
      hot: false,
    },
  ]
})

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

// 「结束播放」是踢掉其他设备的高危操作，先弹窗二次确认
const stopTarget = ref<MyPlaybackSession | null>(null)
const showStopConfirm = computed({
  get: () => stopTarget.value !== null,
  set: (v: boolean) => { if (!v) stopTarget.value = null },
})

function askStopSession(session: MyPlaybackSession) {
  stopTarget.value = session
}

function confirmStopSession() {
  const session = stopTarget.value
  stopTarget.value = null
  if (session) stopSession(session)
}

// 会员订阅是首页核心数据（会员卡/三步指引都依赖它）：失败时显示错误态 + 重试，
// 而不是静默吞掉让用户看到错误的「未开通」形态
const loadError = ref(false)

// 首屏只出骨架：数据统一走 loadDeferred（公告与资产同批，不再分关键/延后两波）
// silent = true 时为 KeepAlive 切回 tab 的后台静默刷新：不碰 loading，
// 不闪骨架屏，数据到了直接更新视图
const hasLoaded = ref(false)
async function loadDeferred(silent = false) {
  let memberFailed = false
  if (!silent) loading.value = true
  try {
    const [pointsRes, checkinRes, inviteRes, subs, notices,
      statsRes, seekRes, ticketsRes, sessionsRes] = await Promise.all([
      pointsApi.log({ limit: 1 }).catch((): null => null),
      checkinApi.status().catch((): null => null),
      inviteApi.myCode().catch((): null => null),
      subscriptionApi.getMine().catch((): MySubscription[] => { memberFailed = true; return [] }),
      // 说明条幅：置顶公告；失败静默（条幅只是运营位，不值得为它报错）
      announcementApi.getAnnouncements().catch((): Announcement[] => []),
      // 面板数据：任一项失败都各归各的（catch 成 null），不会连带整页报错
      embyApi.getStats().catch((): WatchStats | null => null),
      mediaSeekApi.getMyRequests().catch((): null => null),
      ticketApi.getMyTickets().catch((): null => null),
      embyApi.getSessions().catch((): { sessions: MyPlaybackSession[] } | null => null),
    ])
    if (pointsRes) quickStats.value.balance = pointsRes.balance
    if (checkinRes) {
      quickStats.value.streak = checkinRes.streak
      quickStats.value.checkedToday = checkinRes.checked_today
    }
    if (inviteRes) quickStats.value.invited = inviteRes.invited_count
    // 静默刷新失败时不降级：不覆盖已有数据、不弹错误态（首屏失败才走错误态）
    if (!silent || !memberFailed) {
      subscriptions.value = Array.isArray(subs) ? subs : []
      loadError.value = memberFailed
    }
    banners.value = (Array.isArray(notices) ? notices : [])
      .filter((a) => a.is_pinned && !dismissedBannerIds.value.includes(a.id))
      .slice(0, 1)

    // 观看统计失败时静默刷新不降级：保持上次的数据，不刷成"—"
    if (!silent || statsRes) stats.value = statsRes
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
    if (!silent || sessionsRes) sessions.value = sessionsRes?.sessions || []
    loadError.value = memberFailed
  } catch (err: any) {
    // 兜底：正常情况下到不了这里（每项请求都有自己的 catch）
    // 静默刷新失败不打扰用户：保留上次数据，不弹错误
    if (silent) return
    loadError.value = true
    if (err?.response?.status !== 401) {
      toast.error('加载失败，请刷新重试')
    }
  } finally {
    loading.value = false
    hasLoaded.value = true
  }
}

/** 错误态重试：重新拉同一批数据 */
async function retryLoad() {
  await loadDeferred()
}

function dismissBanner() {
  const current = banners.value[0]
  if (current) dismissedBannerIds.value = [...dismissedBannerIds.value, current.id]
  banners.value = banners.value.slice(1)
}

/** 运营位条幅：无公告时按账号状态兑底（公益服 / 未开通），都是静态文案不需请求 */
const fallbackBanner = computed(() => {
  if (isFreeRealm.value) {
    return { icon: Sparkles, tone: 'cyan' as const, title: '公益服 · 免费开放', text: realmNoteText() }
  }
  if (!isMember.value) {
    return { icon: Crown, tone: 'amber' as const, title: '会员未开通', text: '开通后即可播放全库内容，资产卡里的「订阅」可直接前往。' }
  }
  return null
})

function realmNoteText() {
  return userStore.realmNote || '本服为公益服 · 免费开放：无需开通会员即可观看全库内容。'
}

// 首屏只出骨架：数据统一走 loadDeferred（公告与资产同批，不再分关键/延后两波）
onMounted(() => {
  loadDeferred()
})

// 从别的 tab 切回来（KeepAlive 缓存命中）：后台静默刷新，不闪骨架屏
onActivated(() => {
  if (hasLoaded.value) void loadDeferred(true)
})
</script>

<template>
  <div class="home-view">
    <!-- Hero：问候与主行动（会员/订阅状态在下方「我的资产」金色卡里，不再占右栏） -->
    <section class="hero">
      <div class="hero-glow" aria-hidden="true"></div>
      <div class="hero-glow-2" aria-hidden="true"></div>
      <div class="hero-orb" aria-hidden="true"></div>
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

      </div>
    </section>

    <main class="container main">
      <!-- 会员数据加载失败：给错误态 + 重试，而不是静默显示「未开通」 -->
      <div v-if="loadError && !loading" class="au-empty load-error-card au-card">
        <TriangleAlert :size="28" />
        <p>会员信息加载失败，页面数据可能不完整</p>
        <button class="au-btn au-btn-primary au-btn-sm" @click="retryLoad">
          <RotateCcw :size="13" />
          重新加载
        </button>
      </div>

      <!-- 说明条幅（v2.42.2）：置顶公告（可关闭）优先；无公告时按账号状态兑底
           （公益服 / 未开通）。加载中不渲染，避免先出兑底再跳成公告 -->
      <Transition name="banner">
        <div v-if="!loading && banners.length" class="notice-banner au-card tone-cyan">
          <Megaphone :size="16" class="banner-icon" />
          <div class="banner-body">
            <strong class="banner-title">{{ banners[0].title }}</strong>
            <p class="banner-text">{{ banners[0].content }}</p>
          </div>
          <button class="banner-close" title="关闭" @click="dismissBanner">
            <X :size="14" />
          </button>
        </div>
        <div
          v-else-if="!loading && fallbackBanner"
          class="notice-banner au-card"
          :class="fallbackBanner.tone === 'amber' ? 'tone-amber' : 'tone-cyan'"
        >
          <component :is="fallbackBanner.icon" :size="16" class="banner-icon" />
          <div class="banner-body">
            <strong class="banner-title">{{ fallbackBanner.title }}</strong>
            <p class="banner-text">{{ fallbackBanner.text }}</p>
          </div>
        </div>
      </Transition>

      <!-- 我的资产（v2.42.1）：积分 / 订阅 / 观影数据，四段式资产卡。
           每种资产一个固定功能色（青 / 金 / 紫），从卡片图标 → 数字 / CTA
           全链路同色；卡底统一「灰色说明 + 功能色 CTA」。加载中显示真骨架占位，
           而不是把「—」压暗——压暗的「—」会被读成「没有数据」 -->
      <div class="section-label">
        <span class="section-title">我的资产</span>
      </div>
      <section v-if="loading" class="asset-grid" aria-hidden="true">
        <div v-for="i in 3" :key="i" class="asset-card au-card">
          <div class="asset-head">
            <span class="au-skeleton sk-asset-icon"></span>
            <span class="au-skeleton sk-asset-title"></span>
          </div>
          <span class="au-skeleton sk-asset-value"></span>
          <span class="au-skeleton sk-asset-desc"></span>
          <span class="au-skeleton sk-asset-foot"></span>
        </div>
      </section>
      <section v-else class="asset-grid au-anim-up">
        <component
          :is="c.to ? RouterLink : 'div'"
          v-for="c in assetCards"
          :key="c.key"
          :to="c.to || undefined"
          class="asset-card au-card"
          :class="[{ 'asset-card-static': !c.to }, `tone-${c.tone}`]"
        >
          <!-- ① 图标盒 + 标题（功能色 10% 底 + 20% 边框） -->
          <div class="asset-head">
            <span class="asset-icon">
              <component :is="c.icon" :size="19" />
            </span>
            <span class="asset-title-row">
              <span class="asset-title">{{ c.title }}</span>
              <span v-if="c.badge" class="asset-badge" :class="{ hot: c.hot }">{{ c.badge }}</span>
            </span>
          </div>

          <!-- ② 巨型等宽数字（染功能色）+ 订阅进度条（按真实周期算的口径不变） -->
          <div class="asset-value-row">
            <span class="asset-value">{{ c.value }}</span>
            <span v-if="c.unit" class="asset-unit">{{ c.unit }}</span>
          </div>
          <div v-if="c.progress !== null" class="asset-progress" :title="`套餐周期已过 ${c.progress}%`">
            <!-- 进度条用 scaleX 而不是改 width：合成器线程就能跑，不触发布局 -->
            <div class="asset-progress-fill" :style="{ transform: `scaleX(${c.progress / 100})` }"></div>
          </div>

          <!-- ③ 说明文案 -->
          <p class="asset-desc">{{ c.desc }}</p>

          <!-- ④ 底部分隔条：左灰色说明 + 右功能色 CTA（全站统一模式）；
               没有落地页的卡（如观影数据）不渲染 CTA，只留说明 -->
          <div class="asset-foot">
            <span class="asset-note">{{ c.note }}</span>
            <span v-if="c.footer" class="asset-cta">
              {{ c.footer }}
              <ChevronRight :size="13" />
            </span>
          </div>
        </component>
      </section>

      <!-- 我的面板（v2.34.0）：进行中的事项 / 正在播放（只在本账号真在播时出现）。
           口径：这些是门户独有、客户端给不了的——账号名下的求片与工单状态、跨设备在播概况。
           完整会话清单与设备管理仍在个人中心，这里只给「一眼看到 + 一键处理」。
           观影数据已升级为「我的资产」里的紫色资产卡，这里不再重复一张同义卡。
           加载中显示真骨架占位，避免内容突然出现顶开页面（CLS） -->
      <section v-if="loading" class="panel-grid" aria-hidden="true">
        <div class="panel-card">
          <div class="au-skeleton sk-panel-title"></div>
          <div class="au-skeleton sk-panel-row"></div>
          <div class="au-skeleton sk-panel-row"></div>
          <div class="au-skeleton sk-panel-row short"></div>
        </div>
      </section>
      <section v-else class="panel-grid au-anim-up">
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
              @click="askStopSession(s)"
            >
              <CircleStop :size="13" />
              {{ stoppingSession === s.session_key ? '结束中' : '结束' }}
            </button>
          </div>
        </div>
      </section>

      <!-- v2.42.2：「最近上新」海报墙已移除——参考的纸片人 dashboard 没有媒体浏览，
           首页只做资产与服务；媒体浏览统一在媒体库独立页（顶栏/底部坞入口不变） -->

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

    <!-- 结束播放二次确认：这是踢掉其他设备的操作，对方会立即断开 -->
    <Modal v-model="showStopConfirm" title="结束播放" size="sm">
      <p class="stop-confirm-text">
        确定要结束「{{ stopTarget?.device || '未知设备' }}」上的播放吗？对方将立即断开连接。
      </p>
      <template #footer>
        <div class="stop-confirm-actions">
          <button class="au-btn au-btn-ghost au-btn-sm" @click="showStopConfirm = false">取消</button>
          <button class="au-btn au-btn-danger au-btn-sm" @click="confirmStopSession">确定结束</button>
        </div>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.home-view {
  min-height: 100dvh;
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

/* 浅色下氛围光再减淡一档：白底上 12% 透明度的青色已经很显，
   不减会发灰发脏（深色下同样透明度是氛围，浅色下是污渍） */
html[data-theme='light'] .hero-glow,
html[data-theme='light'] .hero-glow-2 {
  opacity: 0.5;
}

/* 欢迎卡的第二层装饰：左下角极光紫低透明度光斑，与右侧青色光晕呼应，
   不抢内容、只给首屏多一层深度 */
.hero-glow-2 {
  position: absolute;
  bottom: -55%;
  left: -6%;
  width: 420px;
  height: 320px;
  background: radial-gradient(ellipse at center, var(--au-violet-soft) 0%, transparent 70%);
  filter: blur(56px);
  pointer-events: none;
}

/* 品牌色装饰圆（v2.42.4，纸片人做法）：右上角 ~240px 实心圆 + 5% 透明度 +
   64px 高斯模糊。纯静态单次合成，不参与任何动画，成本可忽略；
   深色下给首屏一角一点品牌色呼吸，浅色下是极淡的一团色渍（同样协调） */
.hero-orb {
  position: absolute;
  top: -72px;
  right: -48px;
  width: 240px;
  height: 240px;
  border-radius: 50%;
  background: var(--au-primary);
  opacity: 0.05;
  filter: blur(64px);
  pointer-events: none;
}

/* 会员卡已并入订阅资产卡，hero 只剩左栏：双栏网格收敛为单列流 */
.hero-grid {
  position: relative;
  display: block;
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
  color: var(--au-text-3);
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

/* ==================== 我的资产（v2.42.1，四段式资产卡） ====================
   卡片规格全站统一：16px 圆角（--au-r-lg）、1px 细边框、极克制阴影（--au-shadow-1）、
   内边距移动端 20px / 桌面 28px。每种资产一个固定功能色（tone），
   图标盒（10% 底 + 20% 边框）→ 巨型等宽数字 → 底部 CTA 全链路同色。 */

.asset-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
  margin-bottom: 2.25rem;
}

.asset-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.25rem;
  min-width: 0;
  text-decoration: none;
  box-shadow: var(--au-shadow-1);
  transition: border-color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease),
    box-shadow var(--au-fast) var(--au-ease);
}

@media (min-width: 769px) {
  .asset-card { padding: 1.75rem; }
}

/* hover 微交互克制：边框与阴影走功能色、整卡轻抬，图标稍放大。
   纯展示卡（无落地页，如观影数据）不参与 hover 位移 */
.asset-card:hover {
  border-color: var(--asset-border);
  box-shadow: var(--au-shadow-2);
  transform: translateY(-2px);
}
.asset-card-static:hover {
  transform: none;
  box-shadow: var(--au-shadow-1);
}

.asset-card:hover .asset-icon {
  transform: scale(1.06);
}

.asset-card-static:hover .asset-icon { transform: none; }

.asset-card:hover .asset-title {
  color: var(--asset);
}

/* tone-x 类的功能色变量定义在 styles/aurora.css（全局唯一 token 源），
   这里只消费；hoover 态与卡片结构样式都走 var(--asset*) */

/* ① 图标盒：功能色 10% 底 + 20% 边框；小标题同行 */
.asset-head {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  min-width: 0;
}

.asset-icon {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: var(--asset-soft);
  border: 1px solid var(--asset-border);
  color: var(--asset);
  transition: transform var(--au-fast) var(--au-ease);
}

.asset-title-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
  flex: 1;
}

.asset-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text-2);
  transition: color var(--au-fast) var(--au-ease);
}

/* 徽章/胶囊配方：rounded-full + 功能色 10% 底 + 20~25% 边框 + semibold 彩色字 */
.asset-badge {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  border-radius: var(--au-r-full);
  background: var(--asset-soft);
  border: 1px solid var(--asset-border);
  color: var(--asset);
  font-size: 0.6875rem;
  font-weight: 600;
}

.asset-badge.hot {
  background: var(--au-warning-soft);
  border-color: var(--au-warning-border);
  color: var(--au-warning);
}

/* ② 巨型等宽数字：移动端 30px / 桌面 48px，font-variant-numeric 保证数字不跳动 */
.asset-value-row {
  display: flex;
  align-items: baseline;
  gap: 0.3125rem;
  min-width: 0;
}

.asset-value {
  font-family: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 1.875rem;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -0.02em;
  color: var(--asset);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (min-width: 769px) {
  .asset-value { font-size: 3rem; }
}

.asset-unit {
  flex-shrink: 0;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text-3);
}

/* 进度条：10px 全圆角 + transition-all（只有订阅卡有） */
.asset-progress {
  height: 10px;
  border-radius: var(--au-r-full);
  background: var(--au-track);
  overflow: hidden;
}

.asset-progress-fill {
  height: 100%;
  width: 100%;
  border-radius: var(--au-r-full);
  transform-origin: left center;
  /* 跟卡片的 tone 走（订阅卡 = 会员金），未来其它卡加进度条不用再改这里 */
  background: var(--asset);
  transition: transform var(--au-med) var(--au-ease);
}

@media (prefers-reduced-motion: reduce) {
  .asset-progress-fill { transition: none; }
}

/* ③ 说明文案 */
.asset-desc {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--au-text-3);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ④ 底部分隔条：左灰色说明 + 右功能色加粗 CTA（全站统一模式） */
.asset-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: auto;
  padding-top: 0.75rem;
  border-top: 1px solid var(--au-border);
}

.asset-note {
  font-size: 0.75rem;
  color: var(--au-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-cta {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  flex-shrink: 0;
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--asset);
}

.asset-card:hover .asset-cta svg {
  transform: translateX(2px);
}

.asset-cta svg {
  transition: transform var(--au-fast) var(--au-ease);
}

/* 资产卡加载骨架：与真实卡片同高，加载完成不跳动（CLS） */
.sk-asset-icon {
  display: block;
  width: 44px;
  height: 44px;
  border-radius: 12px;
}

.sk-asset-title {
  display: block;
  width: 64px;
  height: 14px;
}

.sk-asset-value {
  display: block;
  width: 96px;
  height: 30px;
  margin-top: 0.25rem;
}

.sk-asset-desc {
  display: block;
  width: 85%;
  height: 13px;
}

.sk-asset-foot {
  display: block;
  width: 100%;
  height: 30px;
  margin-top: 0.25rem;
}

/* ==================== 说明条幅（v2.42.2） ====================
   公告 / 公益服 / 未开通三态共用一条：图标走对应功能色，正文两行截断。
   广告牌法则：只告知，不抢资产的戏，高度克在两行文案内 */

.notice-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  padding: 0.875rem 1rem;
  margin-bottom: 1.5rem;
  box-shadow: var(--au-shadow-1);
}

.notice-banner.banner-enter-from,
.notice-banner.banner-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.banner-enter-active,
.banner-leave-active {
  transition: opacity var(--au-med) var(--au-ease), transform var(--au-med) var(--au-ease);
}

.notice-banner .banner-icon {
  flex-shrink: 0;
  margin-top: 0.125rem;
  color: var(--asset, var(--au-primary));
}

.banner-body {
  flex: 1;
  min-width: 0;
}

.banner-title {
  display: block;
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--text-main);
}

.banner-text {
  margin: 0.125rem 0 0;
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.banner-close {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--au-r-full);
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.banner-close:hover {
  background: var(--au-surface-2);
  color: var(--text-main);
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

/* 中文标题：uppercase / letter-spacing 对中文无效，反而让字间距发虚，这里去掉 */
.section-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--au-text-3);
}

.hero-eyebrow {
  font-size: 0.8125rem;
  color: var(--au-primary);
  margin: 0 0 0.4375rem;
}

/* 问候主标题（v2.42.4 加大）：20px / 桌面 24px，让首屏第一眼有主次 */
.hero-title {
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--au-text);
  margin: 0;
}

@media (min-width: 769px) {
  .hero-title { font-size: 1.5rem; }
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}

.hero-vip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1875rem 0.5625rem;
  background: var(--au-gradient-warm);
  color: var(--au-on-primary);
  font-size: 0.75rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

/* 公益服（v2.7.0）：免费开放用站点主色，不跟会员的金色混在一起 */
.hero-free {
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
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

/* ==================== 我的面板（v2.34.0） ==================== */

.panel-grid {
  display: grid;
  /* 观影数据已并入资产卡：事项卡单独一条时占满整行，未来加回第二张卡时自动变两列 */
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

/* 面板骨架：与真实卡片同高，加载完成不跳动 */
.sk-panel-title {
  width: 96px;
  height: 18px;
  margin-bottom: 1rem;
}

.sk-panel-row {
  height: 14px;
  margin-bottom: 0.75rem;
}

.sk-panel-row.short {
  width: 55%;
  margin-bottom: 0;
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
  color: var(--au-text-3);
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
  font-size: 0.75rem;
  color: var(--au-text-3);
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
  color: var(--au-text-3);
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
  font-size: 0.75rem;
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

/* 超长设备名截断，不把「结束」按钮挤出可视区 */
.playing-meta > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.playing-meta .dot {
  flex-shrink: 0;
  color: var(--au-text-3);
}

/* 「结束」按钮不被挤压 */
.playing-row .au-btn {
  flex-shrink: 0;
}

/* 结束播放二次确认弹窗 */
.stop-confirm-text {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--au-text-2);
}

.stop-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.625rem;
}

/* 会员加载失败的错误卡 */
.load-error-card {
  margin-bottom: 1.5rem;
  padding: 1.75rem 1.25rem;
  gap: 0.75rem;
}

.load-error-card svg {
  color: var(--au-warning);
}

.load-error-card p {
  margin: 0;
  font-size: 0.875rem;
  color: var(--au-text-2);
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
  color: var(--au-text-3);
  transition: color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.help-row:hover .help-row-arrow {
  color: var(--au-primary);
  transform: translateX(2px);
}

/* ==================== 响应式 ==================== */

@media (max-width: 900px) {
  /* 装饰光晕收一收：小屏上再占这么大面积会顶到内容 */
  .hero-glow {
    width: 340px;
    height: 260px;
  }

  .hero-glow-2 {
    width: 300px;
    height: 220px;
  }

  /* 窄屏：两块面板竖排（观影数据在上、进行中的事项在下） */
  .panel-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  /* 底部坞（AppDock）出现后，页面尾部统一让位（--au-dock-space 由 App.vue 定义） */
  .main {
    padding-bottom: calc(3.5rem + var(--au-dock-space));
  }

  /* 资产卡单列（卡片间距收窄一档） */
  .asset-grid {
    grid-template-columns: 1fr;
    gap: 0.75rem;
  }
}

@media (max-width: 640px) {
  .hero {
    padding: 1.75rem 0 1.5rem;
  }

  .hero-title {
    font-size: 1.125rem;
  }

  .hero-sub {
    font-size: 0.8125rem;
    margin-bottom: 1rem;
  }

  /* 内容区 padding 收窄：与底部坞时代移动端的卡片密度匹配 */
  .main {
    padding-left: 1rem;
    padding-right: 1rem;
  }
}
</style>
