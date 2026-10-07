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
 *
 * 「暗房影院」改版：首页从上到下是——
 *   ① 幕布 Hero：整幅背景图（取「追新日历」近 7 天入库里第一张带背景图的条目，
 *      没有就是一块暖黑渐变），左下角琥珀眉题 + 衬线问候 + 状态行 + 唯一一个琥珀主按钮；
 *   ② 票根卡：原三张资产卡（积分 / 订阅 / 观影数据）合成一张电影票，右侧票根是续费入口；
 *   ③ 今日入库：近 7 天入库的竖版海报横滑（同一份日历数据，点击走 Rex deep link）；
 *   ④ 正在播放 → ⑤ 进行中 → ⑥ 帮助中心（纯文字列表）。
 * 数据口径一律沿用原有绑定，只换视觉；新增的只有一次追新日历请求（失败静默，不影响首屏）。
 */
import { ref, computed, onMounted, onActivated } from 'vue'
import { RouterLink } from 'vue-router'
// 观影数据卡无落地页（媒体库已下线），同模板里 RouterLink 与 div 二选一
import { useUserStore } from '@/stores/user'
import {
  isExpiringSoon, embyApi,
  type MySubscription, type WatchStats, type MyPlaybackSession, type Announcement,
} from '@/api'
import { useToast } from '@/composables/useToast'
import Modal from '@/components/ui/Modal.vue'
import { homeApi, type HomeSummary } from '@/api/economy'
import { fetchCalendar, type CalendarItem } from '@/api/calendar'
import { backdropUrl, posterUrl, type EmbyItem } from '@/api/emby'
import { rexDeepLink } from '@/utils/rexDeepLink'
import {
  ChevronRight, Crown, MessageSquareDashed,
  Sparkles, TriangleAlert, Zap,
  Clapperboard, Ticket, CircleStop,
  RotateCcw, X, Megaphone, Film,
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

// 票根卡的三格（暗房影院改版起由原三张资产卡合并而来）：积分 / 订阅 / 观影数据。
// 暗房影院只有一支强调色，tone 字段保留但不再决定颜色（数字一律正文色）。
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

/**
 * 首屏数据快照（v2.42.9）
 *
 * 这批数据（积分 / 连签 / 观影统计 / 求片与工单数量…）变化以天为单位，秒级刷新
 * 没有意义，但每次进页面都要等接口回来才出内容，首屏就得先闪一段骨架。
 *
 * 做法：数据到手后按账号存一份快照；下次进页面先用快照渲染真实内容，同时
 * 静默拉一次更新数字。回访用户首屏 0 骨架，只有首次访问才看得到加载态。
 *
 * 快照按 user_id 分键：同一台设备换账号登录不会看到上一个账号的数据。
 */
const SNAPSHOT_KEY = 'aetrix:home-summary:v1'
const SNAPSHOT_MAX_AGE_MS = 24 * 60 * 60 * 1000

interface HomeSnapshot {
  savedAt: number
  userId: number
  data: HomeSummary
}

function readSnapshot(userId: number): HomeSummary | null {
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY)
    if (!raw) return null
    const snap = JSON.parse(raw) as HomeSnapshot
    if (snap.userId !== userId) return null
    if (Date.now() - snap.savedAt > SNAPSHOT_MAX_AGE_MS) return null
    return snap.data
  } catch {
    return null
  }
}

function writeSnapshot(userId: number, data: HomeSummary) {
  try {
    const snap: HomeSnapshot = { savedAt: Date.now(), userId, data }
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snap))
  } catch {
    // 隐私模式 / 配额满：快照只是优化，拿不到就算了，不影响正常加载
  }
}

/** 把聚合响应套用到各视图状态（快照与实时数据走同一条路，保证渲染口径一致） */
function applySummary(data: HomeSummary) {
  if (data.points) quickStats.value.balance = data.points.balance
  if (data.checkin) {
    quickStats.value.streak = data.checkin.streak
    quickStats.value.checkedToday = data.checkin.checked_today
  }
  if (data.invite) quickStats.value.invited = data.invite.invited_count
  if (data.subscriptions) subscriptions.value = data.subscriptions
  if (data.announcements) {
    banners.value = data.announcements
      .filter((a) => a.is_pinned && !dismissedBannerIds.value.includes(a.id))
      .slice(0, 1)
  }
  if (data.stats) stats.value = data.stats
  if (data.media_seek) {
    const rows = data.media_seek.requests || []
    seekCounts.value = {
      active: rows.filter((r) => r.status === 'pending' || r.status === 'approved').length,
      completed: rows.filter((r) => r.status === 'completed').length,
    }
  }
  if (data.tickets) {
    ticketCounts.value = {
      active: data.tickets.filter((t) => t.status === 'open' || t.status === 'pending').length,
      settled: data.tickets.filter((t) => t.status === 'closed' || t.status === 'resolved').length,
    }
  }
  if (data.sessions) sessions.value = data.sessions.sessions || []
}

// silent = true 时为 KeepAlive 切回 tab 的后台静默刷新：不碰 loading，不闪骨架屏
const hasLoaded = ref(false)
async function loadDeferred(silent = false) {
  // 有快照：先用它出内容（不闪骨架），再静默刷新；没有才走完整加载态
  const userId = userStore.user?.id
  const snapshot = userId != null ? readSnapshot(userId) : null
  if (snapshot) {
    applySummary(snapshot)
    hasLoaded.value = true
    loading.value = false
  }
  if (!silent && !snapshot) loading.value = true
  let memberFailed = false
  try {
    // 9 项首屏数据一次取回（原来是 9 个并发请求，浏览器 6 连接上限要分两波排队）
    const data = await homeApi.summary()
    memberFailed = data.subscriptions === null
    applySummary(data)
    // 静默刷新失败时不降级：不覆盖已有数据、不弹错误态（首屏失败才走错误态）
    if (!silent || !memberFailed) {
      subscriptions.value = Array.isArray(data.subscriptions) ? data.subscriptions : []
      loadError.value = memberFailed
    }
    if (userId != null) writeSnapshot(userId, data)
    loadError.value = memberFailed
  } catch (err: any) {
    // 兜底：正常情况下到不了这里
    // 静默刷新失败，或已有快照可显示时，都不打扰用户
    if (silent || snapshot) return
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
    return { icon: Crown, tone: 'amber' as const, title: '会员未开通', text: '开通后即可播放全库内容，票根上的「立即开通」可直接前往。' }
  }
  return null
})

function realmNoteText() {
  return userStore.realmNote || '本服为公益服 · 免费开放：无需开通会员即可观看全库内容。'
}


// ===== 暗房影院 暗房影院：幕布 Hero / 今日入库（追新日历近 7 天） =====
// 只读一次追新日历：同一份数据既给 Hero 当背景图，也给「今日入库」海报横滑。
// 失败（未开通被拦、后端老版本没有这个端点）一律静默：Hero 回落到暖黑渐变，海报行不渲染。
const recentItems = ref<CalendarItem[]>([])
const recentHasToday = ref(false)

function isoDay(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

async function loadRecent() {
  const end = new Date()
  const start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 6)
  try {
    const res = await fetchCalendar({ start: isoDay(start), end: isoDay(end) })
    const days = [...res.days].sort((a, b) => (a.date < b.date ? 1 : -1))
    recentHasToday.value = days.some((d) => d.date === isoDay(end) && d.items.length > 0)
    const seen = new Set<string>()
    const flat: CalendarItem[] = []
    for (const day of days) {
      for (const item of day.items) {
        // 同一部剧一天进好几集：海报行只留一张（按剧去重），否则一排全是同一张海报
        const key = item.Type === 'Episode' && item.SeriesName ? `s:${item.SeriesName}` : item.Id
        if (seen.has(key)) continue
        seen.add(key)
        flat.push(item)
      }
    }
    recentItems.value = flat.slice(0, 12)
  } catch {
    recentItems.value = []
  }
}

/** Hero 背景：近 7 天入库里第一张带背景图（Backdrop）的条目 */
const heroItem = computed(() => recentItems.value.find((i) => i.BackdropImageTags?.length) || null)
const heroImage = computed(() => (heroItem.value ? backdropUrl(heroItem.value, 1600) : ''))
const heroImageFailed = ref(false)

function recentTitle(item: CalendarItem): string {
  if (item.Type === 'Episode' && item.SeriesName) return item.SeriesName
  return item.Name
}

function recentPoster(item: CalendarItem): string {
  return posterUrl(item, 240)
}

/** Hero 眉题：有今日入库叫「今日新片」，否则「本周新片」；没有片单就只写站点氛围 */
const heroEyebrow = computed(() => {
  if (!heroItem.value) return '今晚放映'
  return `${recentHasToday.value ? '今日新片' : '本周新片'} · ${recentTitle(heroItem.value)}`
})

/** Hero 状态行：会员状态 + 签到（都是首页已有的数据，不额外请求） */
const heroStatus = computed(() => {
  const parts: string[] = []
  if (isMember.value && activeSub.value) parts.push(`会员剩 ${activeSub.value.days_left} 天`)
  else if (isFreeRealm.value) parts.push('公益服 · 免费开放')
  else parts.push('会员未开通')
  if (sessions.value.length) parts.push(`${sessions.value.length} 台设备正在播放`)
  else parts.push(quickStats.value.checkedToday ? '今日已签到' : '今日还没签到')
  return parts.join(' · ')
})

// 票根：订阅那一格的 CTA 文案就是票根上的按钮（续费 / 立即开通 / 查看套餐）
const memberStat = computed(() => assetCards.value.find((c) => c.key === 'member') || null)

// 正在播放的缩略图：会话里只有 item_id，按 Emby 图片端点拼海报地址；加载失败就退回图标
const failedThumbs = ref<string[]>([])
function sessionThumb(s: MyPlaybackSession): string {
  if (!s.item_id || failedThumbs.value.includes(s.item_id)) return ''
  return posterUrl({ Id: s.item_id, ImageTags: { Primary: '1' } } as unknown as EmbyItem, 160)
}
function onThumbError(s: MyPlaybackSession) {
  failedThumbs.value = [...failedThumbs.value, s.item_id]
}

// 首屏只出骨架：数据统一走 loadDeferred（公告与资产同批，不再分关键/延后两波）
// 追新日历与之并行、互不阻塞
onMounted(() => {
  loadDeferred()
  void loadRecent()
})

// 从别的 tab 切回来（KeepAlive 缓存命中）：后台静默刷新，不闪骨架屏
onActivated(() => {
  if (hasLoaded.value) void loadDeferred(true)
})
</script>

<template>
  <div class="home-view">
    <!-- ① 幕布 Hero：整幅背景图（近 7 天入库的第一张背景图，没有就是暖黑渐变），
         底部渐隐到页面底色；左下角眉题 + 衬线问候 + 状态行 + 唯一一个琥珀主按钮 -->
    <section class="hero" :class="{ 'has-image': heroImage && !heroImageFailed }">
      <img
        v-if="heroImage && !heroImageFailed"
        class="hero-backdrop"
        :src="heroImage"
        alt=""
        aria-hidden="true"
        decoding="async"
        @error="heroImageFailed = true"
      />
      <div class="hero-shade" aria-hidden="true"></div>
      <div class="container hero-inner">
        <p class="au-eyebrow hero-eyebrow">{{ heroEyebrow }}</p>
        <h1 class="hero-title">{{ greeting }}，{{ user?.username || '观影用户' }}</h1>
        <p class="hero-status">
          <span v-if="isMember" class="hero-tag">
            <Crown :size="12" />
            会员
          </span>
          <span v-else-if="isFreeRealm" class="hero-tag">
            <Sparkles :size="12" />
            公益服
          </span>
          <span>{{ heroStatus }}</span>
        </p>

        <!-- 未开通：三步看片指引。门户最大的 friction 是"付了钱不会配置客户端"，
             所以首屏不讲会员权益、讲"怎么看上片"；主按钮只有一个（开通） -->
        <template v-if="!isMember && !isFreeRealm">
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
            <RouterLink to="/wallet?tab=plans" class="au-btn au-btn-primary">
              立即开通
            </RouterLink>
            <RouterLink to="/profile" class="hero-link">
              连接教程
              <ChevronRight :size="14" />
            </RouterLink>
          </div>
        </template>

        <!-- 已开通 / 公益服：看片在第三方客户端完成，主按钮就是「把服务器导进播放器」 -->
        <template v-else>
          <p class="hero-sub">门户账号即 Emby 账号 — 在 Infuse 等客户端登录即可观影。</p>
          <div class="hero-cta">
            <RouterLink to="/profile" class="au-btn au-btn-primary">
              一键导入播放器
            </RouterLink>
            <RouterLink to="/profile" class="hero-link">
              连接教程
              <ChevronRight :size="14" />
            </RouterLink>
            <RouterLink to="/request" class="hero-link">
              求片
              <ChevronRight :size="14" />
            </RouterLink>
          </div>
        </template>
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

      <!-- 说明条幅：置顶公告（可关闭）优先；无公告时按账号状态兜底（公益服 / 未开通）。
           加载中不渲染，避免先出兜底再跳成公告。暗房影院：左侧一根琥珀发丝线，不铺色 -->
      <Transition name="banner">
        <div v-if="!loading && banners.length" class="notice-banner">
          <Megaphone :size="16" class="banner-icon" />
          <div class="banner-body">
            <strong class="banner-title">{{ banners[0].title }}</strong>
            <p class="banner-text">{{ banners[0].content }}</p>
          </div>
          <button class="banner-close" title="关闭" @click="dismissBanner">
            <X :size="14" />
          </button>
        </div>
        <div v-else-if="!loading && fallbackBanner" class="notice-banner">
          <component :is="fallbackBanner.icon" :size="16" class="banner-icon" />
          <div class="banner-body">
            <strong class="banner-title">{{ fallbackBanner.title }}</strong>
            <p class="banner-text">{{ fallbackBanner.text }}</p>
          </div>
        </div>
      </Transition>

      <!-- ② 票根卡：积分 / 订阅 / 观影数据合成一张电影票。左边票面是三格数字，
           中间一条打孔虚线（上下各一个半圆缺口），右边票根是订阅主操作 + ADMIT ONE -->
      <section v-if="loading" class="ticket" aria-hidden="true">
        <div class="ticket-main">
          <div v-for="i in 3" :key="i" class="ticket-stat">
            <span class="au-skeleton sk-stat-label"></span>
            <span class="au-skeleton sk-stat-value"></span>
            <span class="au-skeleton sk-stat-desc"></span>
          </div>
        </div>
        <div class="ticket-stub">
          <span class="au-skeleton sk-stub-btn"></span>
        </div>
      </section>
      <section v-else class="ticket au-anim-up" aria-label="我的资产">
        <div class="ticket-main">
          <component
            :is="c.to ? RouterLink : 'div'"
            v-for="c in assetCards"
            :key="c.key"
            :to="c.to || undefined"
            class="ticket-stat"
            :class="{ 'is-static': !c.to }"
          >
            <span class="stat-label">
              <component :is="c.icon" :size="14" class="stat-icon" />
              {{ c.title }}
              <span v-if="c.badge" class="stat-badge" :class="{ hot: c.hot }">{{ c.badge }}</span>
            </span>
            <span class="stat-value-row">
              <span class="stat-value">{{ c.value }}</span>
              <span v-if="c.unit" class="stat-unit">{{ c.unit }}</span>
            </span>
            <span
              v-if="c.progress !== null"
              class="stat-progress"
              :title="`套餐周期已过 ${c.progress}%`"
            >
              <!-- 进度条用 scaleX 而不是改 width：合成器线程就能跑，不触发布局 -->
              <span class="stat-progress-fill" :style="{ transform: `scaleX(${c.progress / 100})` }"></span>
            </span>
            <span class="stat-desc">{{ c.desc }}</span>
            <span class="stat-note">{{ c.note }}</span>
          </component>
        </div>
        <div class="ticket-stub">
          <RouterLink v-if="memberStat" to="/wallet?tab=plans" class="au-btn au-btn-primary stub-btn">
            {{ memberStat.footer }}
          </RouterLink>
          <RouterLink to="/wallet" class="stub-link">去钱包</RouterLink>
          <span class="stub-admit" aria-hidden="true">ADMIT ONE</span>
        </div>
      </section>

      <!-- ③ 今日入库：近 7 天入库的竖版海报横滑（追新日历同一份数据），
           点击与追新日历一致走 Rex deep link；没有数据整段不渲染 -->
      <section v-if="recentItems.length" class="recent au-anim-up">
        <div class="section-label">
          <span class="section-title">{{ recentHasToday ? '今日入库' : '本周入库' }}</span>
          <RouterLink to="/calendar" class="section-more">
            追新日历
            <ChevronRight :size="14" />
          </RouterLink>
        </div>
        <div class="poster-row">
          <a
            v-for="item in recentItems"
            :key="item.Id"
            :href="rexDeepLink(item)"
            class="poster-card"
            :title="`在 Rex 里打开：${recentTitle(item)}`"
          >
            <span class="poster-frame">
              <img
                v-if="recentPoster(item)"
                :src="recentPoster(item)"
                :alt="recentTitle(item)"
                loading="lazy"
                decoding="async"
              />
              <Film v-else :size="20" aria-hidden="true" />
            </span>
            <span class="poster-name">{{ recentTitle(item) }}</span>
          </a>
        </div>
      </section>

      <!-- ④ 正在播放：有会话才出现（一条状态，不是管理清单）；完整清单在个人中心 -->
      <section v-if="sessions.length" class="playing au-anim-up">
        <div class="section-label">
          <span class="section-title">正在播放</span>
          <span class="section-hint">{{ sessions.length }} 个会话</span>
        </div>
        <div class="playing-list">
          <div v-for="s in sessions" :key="s.session_key" class="playing-row">
            <RouterLink :to="`/media/${s.item_id}`" class="playing-thumb" :aria-label="s.item">
              <img
                v-if="sessionThumb(s)"
                :src="sessionThumb(s)"
                alt=""
                loading="lazy"
                decoding="async"
                @error="onThumbError(s)"
              />
              <Film v-else :size="18" aria-hidden="true" />
            </RouterLink>
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

      <!-- ⑤ 进行中：自己提交的求片 / 工单处理到哪了 -->
      <div class="section-label">
        <span class="section-title">进行中</span>
      </div>
      <section v-if="loading" class="todo-card" aria-hidden="true">
        <div class="au-skeleton sk-panel-row"></div>
        <div class="au-skeleton sk-panel-row short"></div>
      </section>
      <section v-else class="todo-card au-anim-up">
        <RouterLink v-for="t in todoRows" :key="t.key" :to="t.to" class="todo-row">
          <component :is="t.icon" :size="16" class="todo-icon" />
          <span class="todo-body">
            <span class="todo-label">{{ t.label }}</span>
            <span class="todo-sub">{{ t.sub }}</span>
          </span>
          <span class="todo-value" :class="{ hot: t.hot }">{{ t.value }}</span>
          <ChevronRight :size="14" class="todo-arrow" />
        </RouterLink>
      </section>

      <!-- ⑥ 帮助中心：纯文字列表 + 发丝分隔线，不再有图标方块 -->
      <div class="section-label">
        <span class="section-title">帮助中心</span>
      </div>
      <nav class="help-list" aria-label="帮助中心">
        <RouterLink to="/profile" class="help-row">
          <span class="help-row-body">
            <strong>连接播放器</strong>
            <em>Infuse / Forward 等客户端的服务器地址、账号与一键导入</em>
          </span>
          <span class="help-row-arrow" aria-hidden="true">›</span>
        </RouterLink>
        <RouterLink to="/request" class="help-row">
          <span class="help-row-body">
            <strong>求片</strong>
            <em>库里没有想看的？提交求片，入库后在消息中心通知你</em>
          </span>
          <span class="help-row-arrow" aria-hidden="true">›</span>
        </RouterLink>
        <RouterLink to="/tickets" class="help-row">
          <span class="help-row-body">
            <strong>联系客服</strong>
            <em>遇到问题提交工单，客服会尽快回复</em>
          </span>
          <span class="help-row-arrow" aria-hidden="true">›</span>
        </RouterLink>
      </nav>
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

/* ==================== ① 幕布 Hero ==================== */

.hero {
  position: relative;
  display: flex;
  align-items: flex-end;
  min-height: 46vh;
  overflow: hidden;
  /* 没有背景图时：一块暖黑渐变，像放映前的幕布 */
  background:
    linear-gradient(180deg, var(--au-bg-soft) 0%, var(--au-surface) 55%, var(--au-bg) 100%);
  animation: hero-fade var(--au-fade-in) var(--au-ease) both;
}

.hero.has-image {
  min-height: 56vh;
}

.hero-backdrop {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  max-width: none;
  object-fit: cover;
  object-position: center 30%;
}

/* 背景图上叠两层：自左向右压暗（文字区可读）+ 自上而下渐隐到页面底色 */
.hero-shade {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(90deg, var(--au-overlay-strong) 0%, var(--au-overlay-mid) 45%, transparent 80%),
    linear-gradient(180deg, transparent 30%, var(--au-overlay-mid) 65%, var(--au-bg) 100%);
}

.hero:not(.has-image) .hero-shade {
  background: linear-gradient(180deg, transparent 50%, var(--au-bg) 100%);
}

.hero-inner {
  position: relative;
  width: 100%;
  padding-top: 3rem;
  padding-bottom: 2.25rem;
}

.hero-eyebrow {
  margin: 0 0 0.75rem;
  max-width: 34rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hero-title {
  margin: 0;
  font-size: clamp(1.75rem, 4.2vw, 2.75rem);
  font-weight: 700;
  line-height: 1.2;
  color: var(--au-text);
}

/* 有背景图时字一律走浅色（图片在浅色主题下也是暗的） */
.hero.has-image .hero-title { color: #f3ede4; text-shadow: var(--au-shadow-text); }
.hero.has-image .hero-status,
.hero.has-image .hero-sub,
.hero.has-image .hero-steps em { color: rgba(243, 237, 228, 0.78); }
.hero.has-image .hero-steps strong,
.hero.has-image .hero-link { color: #f3ede4; }

.hero-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0.75rem 0 0;
  font-size: 0.875rem;
  color: var(--au-text-2);
}

.hero-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-full);
  color: var(--au-primary);
  font-size: 0.8125rem;
  font-weight: 600;
}

.hero-sub {
  margin: 0.875rem 0 0;
  max-width: 34rem;
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--au-text-3);
}

.hero-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
  max-width: 44rem;
  margin: 1.25rem 0 0;
  padding: 0;
  list-style: none;
}

.hero-steps li {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
}

.step-num {
  flex-shrink: 0;
  width: 1.5rem;
  font-family: var(--au-font-serif);
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.2;
  color: var(--au-primary);
}

.step-body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
}

.step-body strong {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.step-body em {
  font-style: normal;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--au-text-3);
}

.hero-cta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem 1.25rem;
  margin-top: 1.5rem;
}

.hero-cta .au-btn-primary {
  height: 44px;
  padding: 0 1.5rem;
  font-size: 0.9375rem;
}

.hero-link {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--au-text-2);
  text-decoration: none;
  transition: color var(--au-fast) var(--au-ease);
}

.hero-link:hover { color: var(--au-primary); }

@keyframes hero-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ==================== 主体 ==================== */

.main {
  padding-top: 1.5rem;
  padding-bottom: 4rem;
  display: flex;
  flex-direction: column;
}

.load-error-card {
  margin-bottom: 1.25rem;
}

.section-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin: 2.25rem 0 0.875rem;
}

.section-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--au-text);
}

.section-more,
.section-hint {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.8125rem;
  color: var(--au-text-3);
  text-decoration: none;
}

.section-more:hover { color: var(--au-primary); }

/* ==================== 说明条幅 ==================== */

.notice-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
  padding: 0.875rem 1rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-left: 2px solid var(--au-primary);
  border-radius: var(--au-r-sm);
}

.banner-icon {
  flex-shrink: 0;
  margin-top: 0.125rem;
  color: var(--au-primary);
}

.banner-body {
  flex: 1;
  min-width: 0;
}

.banner-title {
  display: block;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.banner-text {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--au-text-2);
  white-space: pre-line;
}

.banner-close {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--au-r-sm);
  background: transparent;
  color: var(--au-text-3);
  cursor: pointer;
}

.banner-close:hover {
  background: var(--au-surface-2);
  color: var(--au-text);
}

.banner-enter-active,
.banner-leave-active {
  transition: opacity var(--au-med) var(--au-ease);
}

.banner-enter-from,
.banner-leave-to {
  opacity: 0;
}

/* ==================== ② 票根卡 ==================== */

.ticket {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 156px;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
}

.ticket-main {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  min-width: 0;
}

.ticket-stat {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  min-width: 0;
  padding: 1.25rem 1.25rem 1.125rem;
  color: inherit;
  text-decoration: none;
  transition: background var(--au-fast) var(--au-ease);
}

.ticket-stat + .ticket-stat {
  border-left: 1px solid var(--au-border);
}

.ticket-stat:first-child { border-radius: var(--au-r-lg) 0 0 var(--au-r-lg); }

a.ticket-stat:hover { background: var(--au-surface-2); }

.stat-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-family: var(--au-font-serif);
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text-2);
}

.stat-icon { color: var(--au-primary); flex-shrink: 0; }

.stat-badge {
  margin-left: auto;
  padding: 0 0.4375rem;
  border: 1px solid var(--au-border-strong);
  border-radius: var(--au-r-full);
  font-family: var(--au-font-sans);
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--au-text-3);
  white-space: nowrap;
}

.stat-badge.hot {
  border-color: var(--au-primary-border);
  color: var(--au-primary);
}

.stat-value-row {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
  min-width: 0;
}

.stat-value {
  font-family: var(--au-font-serif);
  font-size: 2.25rem;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  color: var(--asset-value, var(--au-text));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-unit {
  font-size: 0.875rem;
  color: var(--au-text-3);
}

.stat-progress {
  display: block;
  height: 2px;
  background: var(--au-track);
  border-radius: 1px;
  overflow: hidden;
}

.stat-progress-fill {
  display: block;
  height: 100%;
  background: var(--au-primary);
  transform-origin: left center;
}

.stat-desc {
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--au-text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.stat-note {
  margin-top: auto;
  font-size: 0.8125rem;
  color: var(--au-text-4);
}

/* 票根：左侧一条打孔虚线，上下各挖一个与页面同色的半圆缺口 */
.ticket-stub {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.625rem;
  padding: 1.25rem 1rem;
  border-left: 1px dashed var(--au-border-strong);
}

.ticket-stub::before,
.ticket-stub::after {
  content: '';
  position: absolute;
  left: -11.5px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--au-bg);
  border: 1px solid var(--au-border);
}

.ticket-stub::before {
  top: -12px;
  clip-path: inset(50% 0 0 0);
}

.ticket-stub::after {
  bottom: -12px;
  clip-path: inset(0 0 50% 0);
}

.stub-btn {
  width: 100%;
}

.stub-link {
  font-size: 0.8125rem;
  color: var(--au-text-3);
  text-decoration: none;
}

.stub-link:hover { color: var(--au-primary); }

.stub-admit {
  margin-top: 0.25rem;
  font-family: var(--au-font-serif);
  font-size: 0.8125rem;
  font-weight: 700;
  letter-spacing: 0.28em;
  color: var(--au-text-4);
  white-space: nowrap;
}

/* 骨架 */
.sk-stat-label { display: block; width: 4rem; height: 14px; }
.sk-stat-value { display: block; width: 5.5rem; height: 36px; margin: 0.25rem 0; }
.sk-stat-desc { display: block; width: 80%; height: 13px; }
.sk-stub-btn { display: block; width: 100%; height: 40px; }

/* ==================== ③ 今日入库 ==================== */

.poster-row {
  display: flex;
  gap: 0.875rem;
  margin: 0 calc(var(--gutter) * -1);
  padding: 0 var(--gutter) 0.25rem;
  overflow-x: auto;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
}

.poster-row::-webkit-scrollbar { display: none; }

.poster-card {
  flex: 0 0 auto;
  width: 120px;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  color: inherit;
  text-decoration: none;
  scroll-snap-align: start;
}

.poster-frame {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 2 / 3;
  overflow: hidden;
  border-radius: var(--au-r-sm);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  color: var(--au-text-4);
}

.poster-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: filter var(--au-fast) var(--au-ease);
}

.poster-card:hover .poster-frame img { filter: brightness(1.08); }

.poster-name {
  font-size: 0.8125rem;
  line-height: 1.4;
  color: var(--au-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ==================== ④ 正在播放 ==================== */

.playing-list {
  display: flex;
  flex-direction: column;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
}

.playing-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.875rem 1rem;
}

.playing-row + .playing-row { border-top: 1px solid var(--au-border); }

.playing-thumb {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  aspect-ratio: 2 / 3;
  overflow: hidden;
  border-radius: 6px;
  background: var(--au-surface-2);
  color: var(--au-text-4);
}

.playing-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.playing-main {
  flex: 1;
  min-width: 0;
}

.playing-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  font-size: 0.9375rem;
  font-weight: 600;
}

.playing-title a {
  color: var(--au-text);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.playing-title a:hover { color: var(--au-primary); }

.playing-tag {
  flex-shrink: 0;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--au-text-3);
}

.playing-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.25rem;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.playing-meta .dot { color: var(--au-text-4); }

.playing-bar {
  height: 2px;
  margin-top: 0.625rem;
  background: var(--au-track);
  border-radius: 1px;
  overflow: hidden;
}

.playing-fill {
  height: 100%;
  background: var(--au-primary);
}

/* ==================== ⑤ 进行中 ==================== */

.todo-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
}

section.todo-card[aria-hidden='true'] { padding: 1rem; }

.todo-card.au-anim-up { gap: 0; }

.todo-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  color: inherit;
  text-decoration: none;
  transition: background var(--au-fast) var(--au-ease);
}

.todo-row + .todo-row { border-top: 1px solid var(--au-border); }
.todo-row:first-child { border-radius: var(--au-r-lg) var(--au-r-lg) 0 0; }
.todo-row:last-child { border-radius: 0 0 var(--au-r-lg) var(--au-r-lg); }
.todo-row:hover { background: var(--au-surface-2); }

.todo-icon {
  flex-shrink: 0;
  color: var(--au-text-3);
}

.todo-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
}

.todo-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--au-text);
}

.todo-sub {
  font-size: 0.8125rem;
  color: var(--au-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.todo-value {
  font-family: var(--au-font-serif);
  font-size: 1.25rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--au-text-3);
}

.todo-value.hot { color: var(--au-primary); }

.todo-arrow {
  flex-shrink: 0;
  color: var(--au-text-4);
}

.sk-panel-row { height: 44px; }
.sk-panel-row.short { width: 60%; }

/* ==================== ⑥ 帮助中心 ==================== */

.help-list {
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--au-border);
}

.help-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 0.25rem;
  border-bottom: 1px solid var(--au-border);
  color: inherit;
  text-decoration: none;
}

.help-row-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.help-row-body strong {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--au-text);
  transition: color var(--au-fast) var(--au-ease);
}

.help-row-body em {
  font-style: normal;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--au-text-3);
}

.help-row-arrow {
  flex-shrink: 0;
  font-size: 1.25rem;
  line-height: 1;
  color: var(--au-text-4);
  transition: color var(--au-fast) var(--au-ease);
}

.help-row:hover .help-row-body strong,
.help-row:hover .help-row-arrow { color: var(--au-primary); }

/* ==================== 弹窗 ==================== */

.stop-confirm-text {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--au-text-2);
}

.stop-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

/* ==================== 响应式 ==================== */

@media (max-width: 768px) {
  .hero,
  .hero.has-image {
    min-height: 60vh;
  }

  .main {
    padding-bottom: calc(3.5rem + var(--au-dock-space));
  }

  /* 票根竖排：票面在上、票根在下，打孔线横过来，缺口挪到左右两侧 */
  .ticket {
    grid-template-columns: 1fr;
  }

  .ticket-stub {
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: space-between;
    padding: 1rem 1.125rem;
    border-left: none;
    border-top: 1px dashed var(--au-border-strong);
  }

  .ticket-stub::before,
  .ticket-stub::after {
    top: -11.5px;
    bottom: auto;
  }

  .ticket-stub::before {
    left: -12px;
    clip-path: inset(0 0 0 50%);
  }

  .ticket-stub::after {
    left: auto;
    right: -12px;
    clip-path: inset(0 50% 0 0);
  }

  .stub-btn {
    width: auto;
    flex: 1 1 auto;
    order: 2;
  }

  .stub-admit {
    order: 1;
    margin-top: 0;
  }

  .stub-link { order: 3; }

  .ticket-stat:first-child { border-radius: var(--au-r-lg) 0 0 0; }
}

@media (max-width: 640px) {
  .hero-inner {
    padding-bottom: 1.75rem;
  }

  .hero-steps {
    grid-template-columns: 1fr;
    gap: 0.625rem;
  }

  .main {
    padding-left: 1rem;
    padding-right: 1rem;
  }

  .ticket-stat {
    padding: 1rem 0.75rem 0.875rem;
  }

  .stat-value {
    font-size: 1.625rem;
  }

  .stat-badge {
    display: none;
  }

  .stat-desc {
    display: none;
  }

  .poster-card {
    width: 104px;
  }

  .poster-row {
    margin: 0 -1rem;
    padding: 0 1rem 0.25rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero {
    animation: none;
  }
}
</style>
