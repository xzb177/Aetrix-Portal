<script setup lang="ts">
/**
 * 仪表盘 — 经营驾驶舱
 *
 * v2.25.0：顶部换成**交付链数据卡**（用户总数 / 当前播放 / 待处理求片 / 待处理工单 /
 * 扫描状态 / 存储健康）：先看「现在能不能用、有没有要处理的」，再往下才是经营与排行。
 * 每张卡都直接点进对应页面，不用先想「这个数字在哪一页」。
 *
 * - 顶部「待办」条：待处理工单 / 待审求片 / 待支付订单，一点直达对应页面
 * - 交易概览：今日营收、累计营收、积分存量、今日签到、兑换码核销、邀请人数
 * - 趋势图：近 7/14/30 天的新增用户 / 播放 / 营收 / 签到（纯 SVG，无额外依赖）
 * - 播放榜：用户榜 + 热门内容榜
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  Film, MessageSquareDashed, Radio, Ticket, Users, Wallet,
  Coins, CalendarCheck, TicketCheck, Gift, ArrowRight, TrendingUp,
  Server, HardDrive, ScanSearch, CloudDownload, Download, Route as RealmIcon, ShieldAlert,
  AlertTriangle, RefreshCw,
} from 'lucide-vue-next'
import {
  fetchLibraries, fetchMounts, fetchOverview, fetchPlaybackStats, fetchRealmOverview,
  fetchServersSummary, fetchSessions, fetchStatsTrend, fetchBackendServices,
  fetchQuotaBreakerStatus, resetQuotaBreaker,
  type BackendServiceStatus } from '@/api/admin'
import { fetchEconomyStats, type EconomyStats } from '@/api/economy'
import type {
  EmbyLibrary, EmbySessionRow, OverviewStats, PlaybackStats, RealmOverview, ServerSummary,
  StorageMount, TrendStats,
} from '@/types'

const overview = ref<OverviewStats | null>(null)
const playback = ref<PlaybackStats | null>(null)
const economy = ref<EconomyStats | null>(null)
const trend = ref<TrendStats | null>(null)
const libraries = ref<EmbyLibrary[]>([])
const sessions = ref<EmbySessionRow[]>([])
/** 存储来源：交付链的起点——挂载断了，媒体库扫不到、也播不了 */
const mounts = ref<StorageMount[]>([])
/** 服务器接入情况：面板到底接了几台后端服 / 几台 Emby 服 / 有没有接下载器 */
const servers = ref<ServerSummary | null>(null)
/** 后端服务：aetrix-api + aetrix-worker 的运行状态 */
const backendServices = ref<BackendServiceStatus[]>([])
/** 配额熔断器状态 */
const quotaBreaker = ref<{ tripped: boolean; consecutive_403: number; threshold: number; tripped_at: number | null; backoff_sec: number } | null>(null)
const resettingBreaker = ref(false)
/** 多服运营：每个服的会员 / 内容 / 节点，一个面板同时管几个服一眼看完 */
const realms = ref<RealmOverview | null>(null)
const loading = ref(true)
const trendLoading = ref(false)
/** 各数据分区的独立错误态：key 为分区名，value 为错误信息；失败不再静默，展示可重试的错误条 */
const loadErrors = ref<Record<string, string>>({})

const days = ref(14)
type Metric = 'new_users' | 'plays' | 'revenue' | 'checkins'
const metric = ref<Metric>('new_users')
const metricTabs: { key: Metric; label: string; color: string }[] = [
  { key: 'new_users', label: '新增用户', color: 'var(--chart-1)' },
  { key: 'plays', label: '播放次数', color: 'var(--chart-2)' },
  { key: 'revenue', label: '营收 (¥)', color: 'var(--chart-3)' },
  { key: 'checkins', label: '签到次数', color: 'var(--chart-4)' },
]

async function loadTrend() {
  trendLoading.value = true
  try {
    trend.value = await fetchStatsTrend(days.value)
    delete loadErrors.value.trend
  } catch (err: unknown) {
    loadErrors.value.trend = err instanceof Error ? err.message : '请求失败'
  } finally {
    trendLoading.value = false
  }
}

/** 各分区的加载器：互相独立，一个挂了不影响其它分区 */
const sectionLoaders: Record<string, () => Promise<void>> = {
  overview: async () => { overview.value = await fetchOverview() },
  playback: async () => { playback.value = await fetchPlaybackStats() },
  economy: async () => { economy.value = await fetchEconomyStats() },
  libraries: async () => { libraries.value = (await fetchLibraries()).libraries },
  sessions: async () => { sessions.value = (await fetchSessions()).sessions },
  servers: async () => { servers.value = await fetchServersSummary() },
  realms: async () => { realms.value = await fetchRealmOverview() },
  mounts: async () => { mounts.value = (await fetchMounts())?.mounts || [] },
  services: async () => { backendServices.value = ((await fetchBackendServices()) as any)?.services || [] },
  breaker: async () => { quotaBreaker.value = ((await fetchQuotaBreakerStatus()) as any)?.breaker || null },
}

/** 安全加载单个分区：失败记入 loadErrors，前端展示错误条 + 重试按钮 */
async function safeLoad(key: string) {
  try {
    await sectionLoaders[key]()
    delete loadErrors.value[key]
  } catch (err: unknown) {
    loadErrors.value[key] = err instanceof Error ? err.message : '请求失败'
  }
}

function retrySection(key: string) {
  if (key === 'trend') {
    loadTrend()
    return
  }
  safeLoad(key)
}

onMounted(() => {
  // 并行加载：各分区独立 settle，全都 settle 后撤掉整页 loading；
  // 单个分区失败只影响自己，不再拖垮整页（之前 Promise.all 里三个核心接口无 catch，一挂全挂还静默）。
  Promise.allSettled(Object.keys(sectionLoaders).map((k) => safeLoad(k))).finally(() => {
    loading.value = false
  })
  loadTrend()
})

async function handleResetBreaker() {
  if (!confirm('确定要手动重置配额熔断器吗？请确认 Google Drive 配额已恢复。')) return
  resettingBreaker.value = true
  try {
    await resetQuotaBreaker()
    const data = await fetchQuotaBreakerStatus().catch(() => null)
    quotaBreaker.value = (data as any)?.breaker || null
    alert('熔断器已重置，worker 恢复工作')
  } catch (e) {
    alert('重置失败，请稍后重试')
  } finally {
    resettingBreaker.value = false
  }
}

// ==================== 服务器接入（信息展示）====================

const SERVER_ICONS: Record<string, unknown> = {
  ea: Server,
  emby: HardDrive,
  moviepilot: CloudDownload,
  qbittorrent: Download,
}

const serverTiles = computed(() => {
  const kinds = servers.value?.kinds || {}
  return Object.values(kinds).map((stat) => ({
    stat,
    icon: SERVER_ICONS[stat.kind] || Server,
  }))
})

watch(days, loadTrend)

// ==================== 待办 ====================

const todos = computed(() => {
  const list: { label: string; count: number; to: string; icon: unknown; tone: string }[] = []
  if (overview.value) {
    list.push({ label: '待处理工单', count: overview.value.tickets.open, to: '/tickets', icon: Ticket, tone: 'danger' })
    list.push({ label: '待审求片', count: overview.value.media_seeks.pending, to: '/media-seek', icon: MessageSquareDashed, tone: 'warning' })
  }
  if (economy.value) {
    list.push({ label: '待支付订单', count: economy.value.orders.pending, to: '/orders', icon: Wallet, tone: 'info' })
  }
  return list
})

const todoTotal = computed(() => todos.value.reduce((s, t) => s + t.count, 0))

// ==================== 交付链数据卡 ====================

/** 正在转码的会话数：直连很轻，转码才是吃 CPU 的那种 */
const transcodeCount = computed(
  () => sessions.value.filter((s) => s.play_method === 'Transcode').length,
)

/** 扫描状态：正常 / 异常（partial、failed）/ 正在扫 / 从没扫过 */
const scanSummary = computed(() => {
  const list = libraries.value
  const statusOf = (l: EmbyLibrary) => (l.is_scanning ? 'running' : l.last_scan?.status || '')
  return {
    total: list.length,
    ok: list.filter((l) => statusOf(l) === 'success').length,
    bad: list.filter((l) => statusOf(l) === 'partial' || statusOf(l) === 'failed').length,
    scanning: list.filter((l) => statusOf(l) === 'running').length,
    never: list.filter((l) => !l.last_scan && !l.is_scanning).length,
  }
})

/**
 * 存储健康：以 EM（面板进程）能不能碰到为准（em_reachable），没有体检结果时退回落库结果
 *
 * 「被媒体库绑定、但播放节点（EA）够不着」是唯一阻断播放的一种，单独点出来。
 */
const mountSummary = computed(() => {
  const list = mounts.value.filter((m) => m.is_enabled)
  const reach = (m: StorageMount) => (m.em_reachable === null ? m.last_check_ok : m.em_reachable)
  const failed = list.filter((m) => reach(m) === false)
  return {
    total: mounts.value.length,
    ok: list.filter((m) => reach(m) === true).length,
    failed: failed.length,
    unchecked: list.filter((m) => reach(m) === null).length,
    blocked: list.filter((m) => m.ea_reachable === false && (m.library_ids?.length || 0) > 0).length,
    failedNames: failed.slice(0, 3).map((m) => m.name).join('、'),
  }
})

type KpiTone = 'plain' | 'ok' | 'info' | 'warn' | 'danger'

/** 顶部六张卡：一条交付链看下来（用户 → 播放 → 待办 → 内容 → 存储） */
const kpis = computed<{
  key: string; label: string; value: number | string; foot: string
  to: string; icon: unknown; tone: KpiTone; title: string
}[]>(() => {
  const scan = scanSummary.value
  const mount = mountSummary.value
  return [
    {
      key: 'users', label: '用户总数', value: overview.value?.users.total ?? 0,
      foot: `活跃 ${overview.value?.users.active ?? 0} · 今日播放 ${playback.value?.today.plays ?? 0} 次`,
      to: '/users', icon: Users, tone: 'plain', title: '用户与账号',
    },
    {
      key: 'playing', label: '当前播放', value: sessions.value.length,
      foot: sessions.value.length ? `转码 ${transcodeCount.value} 路` : '当前没有播放会话',
      to: '/emby', icon: Radio, tone: sessions.value.length ? 'ok' : 'plain',
      title: '实时会话（媒体库页）',
    },
    {
      key: 'seeks', label: '待处理求片', value: overview.value?.media_seeks.pending ?? 0,
      foot: (overview.value?.media_seeks.pending ?? 0) > 0 ? '点开去处理' : '没有待处理求片',
      to: '/media-seek', icon: MessageSquareDashed,
      tone: (overview.value?.media_seeks.pending ?? 0) > 0 ? 'warn' : 'plain',
      title: '求片与内容',
    },
    {
      key: 'tickets', label: '待处理工单', value: overview.value?.tickets.open ?? 0,
      foot: (overview.value?.tickets.open ?? 0) > 0 ? '点开去回复' : '没有待处理工单',
      to: '/tickets', icon: Ticket,
      tone: (overview.value?.tickets.open ?? 0) > 0 ? 'danger' : 'plain',
      title: '服务支持',
    },
    {
      key: 'scan', label: '扫描状态', value: `${scan.ok}/${scan.total}`,
      foot: scan.total
        ? `正常 / 共 ${scan.total} 个库`
          + (scan.bad ? ` · 异常 ${scan.bad}` : '')
          + (scan.scanning ? ` · 扫描中 ${scan.scanning}` : '')
          + (scan.never ? ` · 未扫过 ${scan.never}` : '')
        : '还没有媒体库',
      to: '/emby', icon: ScanSearch,
      tone: scan.bad ? 'warn' : scan.scanning ? 'info' : scan.total ? 'ok' : 'plain',
      title: '媒体库与扫描',
    },
    {
      key: 'mounts', label: '存储健康', value: `${mount.ok}/${mount.total}`,
      foot: mount.total
        ? `可用 / 共 ${mount.total} 条来源`
          + (mount.failed ? ` · 异常 ${mount.failed}${mount.failedNames ? `（${mount.failedNames}）` : ''}` : '')
          + (mount.unchecked ? ` · 未体检 ${mount.unchecked}` : '')
          + (mount.blocked ? ` · 播放节点够不着 ${mount.blocked}` : '')
        : '还没有存储来源',
      to: '/mounts', icon: HardDrive,
      tone: mount.failed || mount.blocked ? 'warn' : mount.total ? 'ok' : 'plain',
      title: '存储来源',
    },
  ]
})

// ==================== 趋势图 ====================

const currentMetric = computed(() => metricTabs.find((t) => t.key === metric.value)!)

const series = computed(() => trend.value?.series ?? [])

const values = computed(() => series.value.map((p) => Number(p[metric.value]) || 0))

const maxValue = computed(() => Math.max(...values.value, 1))

const CHART_W = 720
const CHART_H = 150
/** 绘图区内边距：左侧留给 Y 轴标签，Y 轴用 HTML 覆盖层渲染（SVG 拉伸会压扁文字） */
const PAD_L = 46
const PAD_R = 10
const PAD_T = 12
const PAD_B = 8

const plotW = CHART_W - PAD_L - PAD_R
const plotH = CHART_H - PAD_T - PAD_B

const points = computed(() => {
  const list = values.value
  const n = list.length
  if (n === 0) return []
  const step = n > 1 ? plotW / (n - 1) : 0
  return list.map((v, i) => {
    const x = PAD_L + i * step
    const y = PAD_T + plotH - (v / maxValue.value) * plotH
    return [x, y] as const
  })
})

/** Y 轴刻度：0 / 1/3 / 2/3 / 最大值 */
const yTicks = computed(() => {
  const ticks: { v: number; y: number }[] = []
  for (let i = 0; i <= 3; i++) {
    const v = (maxValue.value * i) / 3
    ticks.push({ v, y: PAD_T + plotH - (v / maxValue.value) * plotH })
  }
  return ticks
})

/** 刻度/提示里的数值格式化：营收显示金额，大数缩写 */
function fmtTick(v: number): string {
  if (metric.value === 'revenue') {
    return v >= 1000 ? `¥${(v / 1000).toFixed(1)}k` : `¥${Math.round(v)}`
  }
  return v >= 10000 ? `${(v / 10000).toFixed(1)}万` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${Math.round(v)}`
}

/** tooltip：当前悬停的数据点下标（null = 未悬停） */
const hoverIndex = ref<number | null>(null)
const chartPlotRef = ref<HTMLElement | null>(null)

function showTip(clientX: number) {
  const n = values.value.length
  const el = chartPlotRef.value
  if (!n || !el) return
  const rect = el.getBoundingClientRect()
  const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  hoverIndex.value = Math.round(frac * (n - 1))
}

function onChartMove(e: MouseEvent) {
  showTip(e.clientX)
}

function onChartTouch(e: TouchEvent) {
  const t = e.touches[0]
  if (t) showTip(t.clientX)
}

function hideTip() {
  hoverIndex.value = null
}

const hoverPoint = computed(() =>
  hoverIndex.value != null ? points.value[hoverIndex.value] : null,
)

/** tooltip 在容器内的水平位置（百分比，SVG 拉伸下依然对齐数据点） */
const tipLeftPct = computed(() => {
  if (hoverIndex.value == null) return 0
  const n = values.value.length
  const frac = n > 1 ? hoverIndex.value / (n - 1) : 0.5
  return ((PAD_L + frac * plotW) / CHART_W) * 100
})

const tipDate = computed(() => {
  if (hoverIndex.value == null) return ''
  return series.value[hoverIndex.value]?.date.slice(5) || ''
})

const tipValue = computed(() => {
  if (hoverIndex.value == null) return ''
  const v = values.value[hoverIndex.value]
  return metric.value === 'revenue' ? fmtMoney(v) : `${v}`
})

/** x 轴日期标签左右留白，与绘图区对齐 */
const xPadL = `${((PAD_L / CHART_W) * 100).toFixed(2)}%`
const xPadR = `${((PAD_R / CHART_W) * 100).toFixed(2)}%`

const linePath = computed(() =>
  points.value.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' '),
)

const areaPath = computed(() =>
  points.value.length ? `${linePath.value} L${CHART_W} ${CHART_H} L0 ${CHART_H} Z` : '',
)

/** x 轴标签：首 / 中 / 末，避免拥挤 */
const axisLabels = computed(() => {
  const list = series.value
  if (list.length === 0) return []
  const idx = [0, Math.floor(list.length / 2), list.length - 1]
  return [...new Set(idx)].map((i) => list[i].date.slice(5))
})

function fmtMoney(v: number): string {
  return `¥${v.toFixed(2)}`
}

function libraryStatus(library: EmbyLibrary): string {
  if (library.is_scanning) return '扫描中'
  if (!library.is_enabled) return '已停用'
  return '正常'
}

function sessionProgress(session: EmbySessionRow): number {
  if (!session.duration_ticks) return 0
  return Math.min(100, Math.round((session.position_ticks / session.duration_ticks) * 100))
}
</script>

<template>
  <div class="admin-page">
    <div v-if="loading" class="page-loading">加载中…</div>

    <template v-else>
      <!--
        交付链数据卡：先回答「现在能不能用、有没有要处理的」——
        用户 → 播放 → 待办 → 内容（扫描）→ 存储，每张卡点进去就是这个数的明细页。
      -->
      <!-- 分区加载失败条：失败不静默，可单独重试 -->
      <button
        v-if="loadErrors.overview || loadErrors.playback"
        class="load-error"
        @click="loadErrors.overview ? retrySection('overview') : retrySection('playback')"
      >
        <AlertTriangle :size="14" />
        <span>部分核心数据加载失败，点击重试</span>
        <RefreshCw :size="13" />
      </button>
      <section class="kpi-grid">
        <RouterLink
          v-for="k in kpis"
          :key="k.key"
          :to="k.to"
          class="kpi-card"
          :class="`tone-${k.tone}`"
          :title="k.title"
        >
          <span class="kpi-icon"><component :is="k.icon" :size="16" /></span>
          <div class="kpi-body">
            <div class="kpi-label">{{ k.label }}</div>
            <div class="kpi-value">{{ k.value }}</div>
            <div class="kpi-foot">{{ k.foot }}</div>
          </div>
        </RouterLink>
      </section>

      <!-- 待办 -->
      <section v-if="todos.length" class="todo-bar" :class="{ clear: todoTotal === 0 }">
        <div class="todo-lead">
          <span class="todo-lead-label">{{ todoTotal === 0 ? '全部处理完毕' : '待办事项' }}</span>
          <span v-if="todoTotal > 0" class="todo-lead-count">{{ todoTotal }}</span>
        </div>
        <RouterLink
          v-for="t in todos"
          :key="t.label"
          :to="t.to"
          class="todo-pill"
          :class="[t.tone, { zero: t.count === 0 }]"
        >
          <component :is="t.icon" :size="14" />
          <span>{{ t.label }}</span>
          <strong>{{ t.count }}</strong>
          <ArrowRight :size="13" class="todo-arrow" />
        </RouterLink>
      </section>

      <!--
        服务器接入：接了什么、几台能用、当前用哪台。以前只能靠「服务入口」那一页猜，
        接入 MoviePilot / qB 之后更需要一个一眼能看完的地方（明细在「服务器」页）。
      -->
      <section v-if="serverTiles.length" class="stat-grid">
        <RouterLink
          v-for="tile in serverTiles"
          :key="tile.stat.kind"
          to="/servers"
          class="stat-tile server-tile"
        >
          <div class="stat-label">
            <component :is="tile.icon" :size="13" /> {{ tile.stat.short }}
            <span v-if="tile.stat.active_name" class="server-current">当前</span>
          </div>
          <div class="stat-value" :class="{ 'stat-accent': tile.stat.reachable > 0 }">
            {{ tile.stat.total }}<span class="stat-sub"> 台 · 可用 {{ tile.stat.reachable }}</span>
          </div>
          <div class="stat-foot">
            <template v-if="tile.stat.activatable">
              {{ tile.stat.active_name || '未设置当前使用' }}
            </template>
            <template v-else>
              {{ tile.stat.reachable > 0 ? '可用于求片' : '未连接' }}
            </template>
          </div>
        </RouterLink>
      </section>

      <!-- 后端服务：aetrix-api + aetrix-worker 运行状态 -->
      <section v-if="backendServices.length" class="stat-grid">
        <div
          v-for="svc in backendServices"
          :key="svc.name"
          class="stat-tile server-tile"
        >
          <div class="stat-label">
            <Server :size="13" /> {{ svc.name }}
            <span class="server-current">{{ svc.role }}</span>
          </div>
          <div class="stat-value" :class="{ 'stat-accent': svc.status === 'healthy' }">
            {{ svc.status === 'healthy' ? '运行中' : svc.status }}
            <span v-if="svc.lag_seconds != null" class="stat-sub"> · 心跳 {{ svc.lag_seconds }}s 前</span>
          </div>
          <div class="stat-foot">
            <template v-if="svc.role === 'worker' && svc.pid">
              PID {{ svc.pid }}
            </template>
            <template v-else>
              API 服务
            </template>
          </div>
        </div>
      </section>

      <!-- 配额熔断器：连续 403 触发，保护 Google Drive 配额 -->
      <section v-if="quotaBreaker" class="stat-grid">
        <div class="stat-tile server-tile" :class="{ 'breaker-tripped': quotaBreaker.tripped }">
          <div class="stat-label">
            <ShieldAlert :size="13" /> 配额熔断器
            <span class="server-current">{{ quotaBreaker.tripped ? '已触发' : '正常' }}</span>
          </div>
          <div class="stat-value" :class="{ 'stat-accent': !quotaBreaker.tripped, 'breaker-danger': quotaBreaker.tripped }">
            {{ quotaBreaker.tripped ? '已熔断' : '运行中' }}
            <span class="stat-sub"> · 连续 403: {{ quotaBreaker.consecutive_403 }}/{{ quotaBreaker.threshold }}</span>
          </div>
          <div class="stat-foot">
            <template v-if="quotaBreaker.tripped">
              <span>配额耗尽，worker 已暂停</span>
              <button
                class="breaker-reset-btn"
                :disabled="resettingBreaker"
                @click="handleResetBreaker"
              >
                {{ resettingBreaker ? '重置中...' : '手动恢复' }}
              </button>
            </template>
            <template v-else>
              Google Drive 配额保护
            </template>
          </div>
        </div>
      </section>

      <!--
        各服概况：每个服的会员 / 内容 / 播放节点都在这里，不用一个个切过去看。
        「多服」不是一个要单独学的模块：切当前作用域在顶栏，服与线路的归属在
        「服务器与线路」页按范围看（这里的每行也直接进那一页）。
      -->
      <section v-if="realms?.realms.length" class="admin-card realm-block">
        <div class="card-header">
          <h2><RealmIcon :size="15" /> 各服概况</h2>
          <span class="realm-sum">
            {{ realms.summary.total_realms }} 个服 · 有效订阅 {{ realms.summary.active_subscriptions }} ·
            播放节点在线 {{ realms.summary.nodes_online }}/{{ realms.summary.nodes }}
          </span>
          <span class="realm-links">
            <RouterLink class="realm-manage" to="/servers">
              服务器与线路<ArrowRight :size="13" />
            </RouterLink>
            <RouterLink class="realm-manage" to="/realms">
              服管理<ArrowRight :size="13" />
            </RouterLink>
          </span>
        </div>
        <div class="realm-rows">
          <RouterLink
            v-for="r in realms.realms"
            :key="r.id"
            to="/servers"
            class="realm-row"
            :class="{ current: r.id === realms.active_realm_id, off: !r.is_active }"
          >
            <div class="realm-name">
              <strong>{{ r.name }}</strong>
              <span class="mini-badge muted">{{ r.slug }}</span>
              <span v-if="r.id === realms.active_realm_id" class="mini-badge ok">当前服</span>
              <span v-if="r.is_default" class="mini-badge info">默认服</span>
            </div>
            <div class="realm-stats">
              <span>媒体库 <b>{{ r.stats.libraries }}</b></span>
              <span>条目 <b>{{ r.stats.items }}</b></span>
              <span>挂载 <b>{{ r.stats.mounts }}</b></span>
              <span>套餐 <b>{{ r.stats.plans }}</b></span>
              <span>有效订阅 <b>{{ r.stats.active_subscriptions }}</b></span>
              <span :class="{ warn: r.stats.nodes_online < r.stats.nodes }">
                节点 <b>{{ r.stats.nodes_online }}/{{ r.stats.nodes }}</b>
              </span>
              <span :class="{ warn: r.stats.pending_requests > 0 }">
                待审求片 <b>{{ r.stats.pending_requests }}</b>
              </span>
            </div>
          </RouterLink>
        </div>
      </section>

      <!-- 交易概览 -->
      <button v-if="loadErrors.economy" class="load-error" @click="retrySection('economy')">
        <AlertTriangle :size="14" />
        <span>交易数据加载失败，点击重试</span>
        <RefreshCw :size="13" />
      </button>
      <section class="stat-grid">
        <div class="stat-tile">
          <div class="stat-label"><Wallet :size="13" /> 累计营收</div>
          <div class="stat-value stat-accent">{{ fmtMoney(economy?.orders.revenue ?? 0) }}</div>
          <div class="stat-foot">{{ economy?.orders.pending ?? 0 }} 笔待支付</div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Coins :size="13" /> 积分存量</div>
          <div class="stat-value">{{ economy?.total_points ?? 0 }}</div>
          <div class="stat-foot">全站用户持有</div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><CalendarCheck :size="13" /> 今日签到</div>
          <div class="stat-value">{{ economy?.checkins_today ?? 0 }}</div>
          <div class="stat-foot">人已签到</div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><TicketCheck :size="13" /> 兑换码</div>
          <div class="stat-value">
            {{ economy?.exchange_codes.used ?? 0 }}<span class="stat-sub"> / {{ economy?.exchange_codes.total ?? 0 }}</span>
          </div>
          <div class="stat-foot">已核销 / 已生成</div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Gift :size="13" /> 邀请关系</div>
          <div class="stat-value">{{ economy?.invitations ?? 0 }}</div>
          <div class="stat-foot">累计成功邀请</div>
        </div>
      </section>

      <!-- 趋势 -->
      <section class="admin-card trend-card">
        <div class="card-header">
          <h2><TrendingUp :size="15" /> 趋势</h2>
          <div class="trend-controls">
            <div class="metric-tabs" role="group" aria-label="趋势指标切换">
              <button
                v-for="t in metricTabs"
                :key="t.key"
                class="metric-tab"
                :class="{ active: metric === t.key }"
                :aria-pressed="metric === t.key"
                :style="metric === t.key ? { color: t.color, borderColor: t.color } : undefined"
                @click="metric = t.key"
              >
                {{ t.label }}
              </button>
            </div>
            <el-radio-group v-model="days" size="small">
              <el-radio-button :value="7">7 天</el-radio-button>
              <el-radio-button :value="14">14 天</el-radio-button>
              <el-radio-button :value="30">30 天</el-radio-button>
            </el-radio-group>
          </div>
        </div>

        <div class="trend-total">
          <span class="trend-total-label">近 {{ days }} 天合计</span>
          <span class="trend-total-value" :style="{ color: currentMetric.color }">
            {{ metric === 'revenue' ? fmtMoney(trend?.totals.revenue ?? 0) : (trend?.totals[metric] ?? 0) }}
          </span>
        </div>

        <div class="chart-wrap" v-loading="trendLoading">
          <div v-if="loadErrors.trend && !trendLoading" class="chart-error">
            <button class="load-error" @click="retrySection('trend')">
              <AlertTriangle :size="14" />
              <span>趋势数据加载失败，点击重试</span>
              <RefreshCw :size="13" />
            </button>
          </div>
          <template v-else>
          <!-- chart-plot：SVG 绘图区 + 覆盖层（Y 轴标签 / tooltip）共用同一坐标系 -->
          <div
            ref="chartPlotRef"
            class="chart-plot"
            @mousemove="onChartMove"
            @mouseleave="hideTip"
            @touchstart.passive="onChartTouch"
            @touchmove.passive="onChartTouch"
            @touchend="hideTip"
          >
            <svg
              class="chart"
              :viewBox="`0 0 ${CHART_W} ${CHART_H}`"
              preserveAspectRatio="none"
              role="img"
              :aria-label="`近 ${days} 天${currentMetric.label}趋势图`"
            >
              <defs>
                <linearGradient :id="`grad-${metric}`" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" :style="{ stopColor: currentMetric.color }" stop-opacity="0.36" />
                  <stop offset="100%" :style="{ stopColor: currentMetric.color }" stop-opacity="0" />
                </linearGradient>
              </defs>
              <!-- Y 轴网格线 -->
              <g aria-hidden="true">
                <line
                  v-for="t in yTicks"
                  :key="'g' + t.v"
                  :x1="PAD_L"
                  :x2="CHART_W - PAD_R"
                  :y1="t.y"
                  :y2="t.y"
                  class="grid-line"
                />
              </g>
              <path :d="areaPath" :fill="`url(#grad-${metric})`" />
              <path
                :d="linePath"
                fill="none"
                :style="{ stroke: currentMetric.color }"
                stroke-width="2"
                vector-effect="non-scaling-stroke"
                stroke-linejoin="round"
                stroke-linecap="round"
              />
              <!-- 悬停指示：竖线 + 数据点 -->
              <g v-if="hoverPoint" aria-hidden="true">
                <line
                  :x1="hoverPoint[0]"
                  :x2="hoverPoint[0]"
                  :y1="PAD_T"
                  :y2="CHART_H - PAD_B"
                  class="hover-line"
                />
                <circle
                  :cx="hoverPoint[0]"
                  :cy="hoverPoint[1]"
                  r="4.5"
                  :style="{ fill: currentMetric.color }"
                  stroke="#fff"
                  stroke-width="1.5"
                  vector-effect="non-scaling-stroke"
                />
              </g>
            </svg>
            <!-- Y 轴标签：HTML 覆盖层，避免 SVG 拉伸压扁文字 -->
            <div class="y-labels" aria-hidden="true">
              <span
                v-for="t in yTicks"
                :key="'y' + t.v"
                :style="{ top: `${((t.y / CHART_H) * 100).toFixed(2)}%` }"
              >{{ fmtTick(t.v) }}</span>
            </div>
            <!-- tooltip：日期 + 数值 -->
            <div
              v-if="hoverIndex != null"
              class="chart-tip"
              :style="{ left: `${tipLeftPct.toFixed(2)}%` }"
              aria-hidden="true"
            >
              <strong>{{ tipDate }}</strong>
              <span :style="{ color: currentMetric.color }">{{ tipValue }}</span>
            </div>
          </div><!-- /chart-plot -->
            <div class="chart-axis" :style="{ paddingLeft: xPadL, paddingRight: xPadR }">
              <span v-for="(l, i) in axisLabels" :key="l + i">{{ l }}</span>
            </div>
          </template>
        </div>
      </section>

      <!-- 媒体服务运行态：把媒体库、扫描与在线播放放到首页，而不是让管理员逐页排查 -->
      <section v-if="libraries.length || sessions.length || loadErrors.libraries || loadErrors.sessions" class="ops-grid">
        <div class="admin-card ops-card">
          <div class="card-header">
            <h2>
              <Film :size="15" /> 媒体服务
              <span class="range-hint">条 {{ overview?.emby.total_items ?? 0 }}</span>
            </h2>
            <RouterLink to="/emby" class="card-link">管理媒体库 <ArrowRight :size="13" /></RouterLink>
          </div>
          <div v-if="loadErrors.libraries && !libraries.length" class="empty-hint">
            <button class="load-error inline" @click="retrySection('libraries')">
              <AlertTriangle :size="14" />
              <span>加载失败，点击重试</span>
            </button>
          </div>
          <div v-else-if="libraries.length" class="ops-list">
            <div v-for="library in libraries.slice(0, 5)" :key="library.id" class="ops-row">
              <div class="ops-main">
                <strong>{{ library.name }}</strong>
                <span>{{ library.item_count }} 个条目 · {{ libraryStatus(library) }}</span>
              </div>
              <span class="status-dot" :class="{ warning: library.is_scanning, danger: !library.is_enabled }" />
            </div>
          </div>
          <div v-else class="empty-hint">暂无媒体库</div>
        </div>

        <div class="admin-card ops-card">
          <div class="card-header">
            <h2>
              <Radio :size="15" /> 实时播放
              <span class="range-hint">{{ sessions.length }} 路 · 今日 {{ playback?.today.plays ?? 0 }} 次 / {{ playback?.today.users ?? 0 }} 人</span>
            </h2>
            <RouterLink to="/emby" class="card-link">查看会话 <ArrowRight :size="13" /></RouterLink>
          </div>
          <div v-if="loadErrors.sessions && !sessions.length" class="empty-hint">
            <button class="load-error inline" @click="retrySection('sessions')">
              <AlertTriangle :size="14" />
              <span>加载失败，点击重试</span>
            </button>
          </div>
          <div v-else-if="sessions.length" class="ops-list">
            <div v-for="session in sessions.slice(0, 5)" :key="session.session_key" class="ops-row">
              <div class="ops-main">
                <strong>{{ session.username }} · {{ session.item }}</strong>
                <span>{{ session.client || '未知客户端' }} · {{ sessionProgress(session) }}% · {{ session.play_method === 'Transcode' ? '转码' : '直连' }}</span>
              </div>
              <span class="play-dot" :class="{ paused: session.is_paused }" />
            </div>
          </div>
          <div v-else class="empty-hint">当前没有播放会话</div>
        </div>
      </section>

      <!-- 排行榜 -->
      <section class="stats-two-col" v-if="playback || loadErrors.playback">
        <div class="admin-card">
          <div class="card-header">
            <h2>用户播放排行 <span class="range-hint">近 7 天</span></h2>
          </div>
          <div v-if="loadErrors.playback && !playback" class="empty-hint">
            <button class="load-error inline" @click="retrySection('playback')">
              <AlertTriangle :size="14" />
              <span>加载失败，点击重试</span>
            </button>
          </div>
          <template v-else-if="playback">
            <div v-if="playback.user_ranking.length === 0" class="empty-hint">暂无播放数据</div>
            <div v-for="(u, i) in playback.user_ranking" :key="u.username" class="rank-row">
              <span class="rank-index">{{ i + 1 }}</span>
              <span class="rank-name">{{ u.username }}</span>
              <span class="rank-value">{{ u.plays }} 次</span>
            </div>
          </template>
        </div>

        <div class="admin-card">
          <div class="card-header">
            <h2>热门内容 <span class="range-hint">近 7 天</span></h2>
          </div>
          <div v-if="loadErrors.playback && !playback" class="empty-hint">
            <button class="load-error inline" @click="retrySection('playback')">
              <AlertTriangle :size="14" />
              <span>加载失败，点击重试</span>
            </button>
          </div>
          <template v-else-if="playback">
            <div v-if="playback.item_ranking.length === 0" class="empty-hint">暂无播放数据</div>
            <div v-for="(it, i) in playback.item_ranking" :key="it.name" class="rank-row">
              <span class="rank-index">{{ i + 1 }}</span>
              <span class="rank-name">
                {{ it.name }}
                <span class="rank-type">{{ it.type === 'episode' ? '剧集' : it.type === 'movie' ? '电影' : it.type }}</span>
              </span>
              <span class="rank-value">{{ it.plays }} 次</span>
            </div>
          </template>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
/* 配额熔断器 */
.breaker-tripped {
  border-color: var(--danger-border) !important;
  background: var(--danger-bg) !important;
}
.breaker-danger {
  color: var(--danger) !important;
}
.breaker-reset-btn {
  margin-left: 8px;
  padding: 4px 12px;
  background: var(--danger-strong);
  color: var(--danger-on);
  border: none;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.breaker-reset-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.breaker-reset-btn:hover:not(:disabled) {
  filter: brightness(1.12);
}
.page-loading { text-align: center; color: var(--text-secondary); padding: 60px 0; }

/* 分区加载失败条：失败不静默，可单独重试 */
.load-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 10px 14px;
  margin-bottom: 12px;
  border-radius: var(--radius-md);
  border: 1px dashed var(--danger-border);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 12.5px;
  cursor: pointer;
  transition: filter var(--transition-fast);
}
.load-error:hover { filter: brightness(1.15); }
.load-error.inline {
  width: auto;
  margin-bottom: 0;
  padding: 8px 12px;
  border-style: solid;
}

/* ===== 交付链数据卡（顶部六张，一点直达明细页）===== */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.kpi-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--bg-card);
  text-decoration: none;
  transition: border-color var(--transition-fast), background var(--transition-fast), transform var(--transition-fast);
}

.kpi-card:hover {
  border-color: var(--primary-border);
  background: var(--bg-elevated);
  transform: translateY(-1px);
}

.kpi-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: var(--radius-sm);
  background: var(--bg-glass);
  color: var(--text-secondary);
}

.kpi-body { min-width: 0; flex: 1; }
.kpi-label { font-size: 12px; color: var(--text-tertiary); }

.kpi-value {
  margin-top: 3px;
  font-size: 24px;
  font-weight: var(--font-weight-bold);
  line-height: 1.15;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

.kpi-foot {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 状态包：颜色只用来提示「有没有要看的」，不当装饰 */
.kpi-card.tone-ok .kpi-icon { background: var(--success-bg); color: var(--success); }
.kpi-card.tone-info .kpi-icon { background: var(--info-bg); color: var(--info); }
.kpi-card.tone-warn { border-color: var(--warning-border); }
.kpi-card.tone-warn .kpi-icon { background: var(--warning-bg); color: var(--warning); }
.kpi-card.tone-warn .kpi-value { color: var(--warning); }
.kpi-card.tone-danger { border-color: var(--danger-border); }
.kpi-card.tone-danger .kpi-icon { background: var(--danger-bg); color: var(--danger); }
.kpi-card.tone-danger .kpi-value { color: var(--danger); }

.realm-links { display: inline-flex; align-items: center; gap: 10px; }

.ops-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.ops-card { min-width: 0; }
.ops-list { display: flex; flex-direction: column; }
.ops-row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); }
.ops-row:last-child { border-bottom: none; }
.ops-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.ops-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--text-primary); }
.ops-main span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; color: var(--text-muted); }
.status-dot, .play-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: var(--success); box-shadow: 0 0 0 4px var(--success-bg); }
.status-dot.warning { background: var(--warning); box-shadow: 0 0 0 4px var(--warning-bg); }
.status-dot.danger { background: var(--danger); box-shadow: 0 0 0 4px var(--danger-bg); }
.play-dot.paused { background: var(--warning); box-shadow: 0 0 0 4px var(--warning-bg); }
.card-link { display: inline-flex; align-items: center; gap: 4px; color: var(--primary); font-size: 11.5px; text-decoration: none; }
.card-link:hover { color: var(--text-primary); }
.stat-sub { font-size: 15px; color: var(--text-secondary); font-weight: 500; }
.stat-label { display: flex; align-items: center; gap: 6px; }
.stat-foot { font-size: 11.5px; color: var(--text-muted); margin-top: 4px; }

/* ===== 服务器接入卡（一点直达「服务器」页）===== */
.server-tile { text-decoration: none; display: block; }
.server-tile:hover { border-color: var(--primary); }
.server-current {
  margin-left: 4px; padding: 0 6px; border-radius: 999px;
  background: var(--primary-bg); color: var(--primary); font-size: 10px; font-weight: 700;
}

/* ===== 多服运营卡（每个服一行，切服在顶栏）===== */
.realm-block { margin-bottom: 14px; }
.realm-sum { color: var(--text-muted); font-size: 12px; margin-left: auto; }
.realm-manage { display: inline-flex; align-items: center; gap: 4px; color: var(--primary); font-size: 11.5px; text-decoration: none; }
.realm-manage:hover { color: var(--text-primary); }
.realm-rows { display: flex; flex-direction: column; gap: 6px; }
.realm-row {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 10px 12px; border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle); background: var(--bg-glass);
  text-decoration: none; transition: border-color var(--transition-fast), background var(--transition-fast);
}
.realm-row:hover { border-color: var(--primary); }
.realm-row.current { border-color: var(--primary-border); background: var(--primary-bg); }
.realm-row.off { opacity: 0.7; }
.realm-name { display: flex; align-items: center; gap: 7px; min-width: 190px; }
.realm-name strong { color: var(--text-primary); font-size: 13px; }
.realm-stats { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-left: auto; }
.realm-stats span { color: var(--text-muted); font-size: 11.5px; }
.realm-stats b { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.realm-stats span.warn b { color: var(--warning); }

/* ===== 待办条 ===== */
.todo-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 12px 16px;
  margin-bottom: 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--bg-card);
}

.todo-bar.clear { border-color: var(--success-border); }

.todo-lead {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  padding-right: 6px;
}

.todo-lead-count {
  background: var(--danger-bg);
  color: var(--danger);
  border-radius: var(--radius-full);
  padding: 1px 9px;
  font-size: 12px;
}

.todo-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: var(--bg-glass);
  color: var(--text-secondary);
  font-size: 12.5px;
  text-decoration: none;
  transition: all var(--transition-fast);
}

.todo-pill:hover { border-color: var(--primary-border); color: var(--text-primary); }
.todo-pill strong { color: var(--text-primary); font-size: 13.5px; }
.todo-pill.zero { opacity: 0.5; }
.todo-pill.zero strong { color: var(--text-muted); }
.todo-pill.danger strong { color: var(--danger); }
.todo-pill.warning strong { color: var(--warning); }
.todo-pill.info strong { color: var(--info); }
.todo-arrow { opacity: 0; transition: opacity var(--transition-fast); }
.todo-pill:hover .todo-arrow { opacity: 1; }

/* ===== 趋势卡 ===== */
.trend-card { margin-bottom: 14px; }

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.card-header h2 { display: flex; align-items: center; gap: 8px; font-size: 15px; margin: 0; }

.trend-controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

.metric-tabs { display: flex; gap: 6px; }

.metric-tab {
  padding: 4px 11px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.metric-tab:hover { color: var(--text-primary); border-color: var(--border-strong); }
.metric-tab.active { background: var(--bg-glass); }

.trend-total { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.trend-total-label { font-size: 12px; color: var(--text-muted); }
.trend-total-value { font-size: 22px; font-weight: 700; }

.chart-wrap { position: relative; }
.chart-plot { position: relative; }
.chart { width: 100%; height: 150px; display: block; }

/* Y 轴网格线 / 悬停指示线：非等比拉伸下用 vector-effect 保持 1px */
.grid-line {
  stroke: var(--border-subtle);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
  stroke-dasharray: 3 3;
}
.hover-line {
  stroke: var(--text-muted);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
  stroke-dasharray: 4 3;
}

/* Y 轴标签：HTML 覆盖层，避免 SVG preserveAspectRatio 拉伸压扁文字 */
.y-labels {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 40px;
  pointer-events: none;
}
.y-labels span {
  position: absolute;
  left: 0;
  transform: translateY(-50%);
  font-size: 10.5px;
  line-height: 1;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 图表 tooltip：日期 + 数值 */
.chart-tip {
  position: absolute;
  top: 6px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-md);
  font-size: 12px;
  color: var(--text-primary);
  white-space: nowrap;
  pointer-events: none;
  z-index: 2;
}
.chart-tip span {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.chart-error { padding: 24px 0; }

.chart-axis {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
}

/* ===== 双列 ===== */
.stats-two-col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}

.range-hint { font-size: 11px; color: var(--text-muted); font-weight: 400; }

.rank-name { flex: 1; font-size: 13px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank-type { font-size: 11px; color: var(--text-muted); margin-left: 6px; }
.rank-value { font-size: 12px; color: var(--text-secondary); }
.empty-hint { font-size: 13px; color: var(--text-muted); padding: 12px 0; }

/* ===== 手机 ===== */
@media (max-width: 640px) {
  .kpi-grid { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
  .kpi-card { padding: 12px; gap: 10px; }
  .kpi-value { font-size: 20px; }
  .kpi-foot { white-space: normal; }
  .todo-bar { padding: 10px 12px; gap: 8px; }
  .todo-lead { width: 100%; padding-right: 0; }
  .metric-tabs { flex-wrap: wrap; }
  .chart { height: 132px; }
  /* 7-30 个日期标签在窄屏会挤成一团，隔一个显示一个 */
  .chart-axis span:nth-child(even) { display: none; }
  .trend-total-value { font-size: 18px; }
  .stat-sub { font-size: 13px; }
  .stats-two-col { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .ops-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
