<script setup lang="ts">
/**
 * 仪表盘 — 经营驾驶舱
 *
 * v2.25.0：顶部换成**交付链数据卡**（用户总数 / 当前播放 / 待处理求片 / 待处理工单 /
 * 扫描状态 / 存储健康）：先看「现在能不能用、有没有要处理的」，再往下才是经营与排行。
 * 每张卡都直接点进对应页面，不用先想「这个数字在哪一页」。
 *
 * v2.42.10（Phase 5·KPI 深链）：**每一个数字都能点**，而且点进去**已经带上筛选**——
 * 「待处理工单 3」进的是 `/tickets?status=open`（只看待处理的那几条），不是全部工单；
 * 「待支付订单」进 `/orders?status=pending`。落地页用 `useQueryFilter` 接这个参数
 * （见 composables/useQueryFilter.ts），所以从仪表盘、待办条、命令面板点过去口径一致。
 *
 * - 顶部「待办」条：待处理工单 / 待审求片 / 待支付订单，一点直达对应页面（带筛选）
 * - 交易概览：今日营收、累计营收、积分存量、今日签到、兑换码核销、邀请人数（均可点）
 * - 趋势图：近 7/14/30 天的新增用户 / 播放 / 营收 / 签到（纯 SVG，无额外依赖）
 * - 播放榜：用户榜 + 热门内容榜
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  Film, MessageSquareDashed, Ticket, Users, Wallet,
  Coins, CalendarCheck, TicketCheck, Gift, ArrowRight, TrendingUp,
  Server, HardDrive, ScanSearch, CloudDownload, Download, Route as RealmIcon, ShieldAlert,
} from 'lucide-vue-next'
import {
  fetchLibraries, fetchMounts, fetchOverview, fetchPlaybackStats, fetchRealmOverview,
  fetchServersSummary, fetchStatsTrend, fetchBackendServices,
  type BackendServiceStatus } from '@/api/admin'
import { fetchEconomyStats, type EconomyStats } from '@/api/economy'
import type {
  EmbyLibrary, OverviewStats, PlaybackStats, RealmOverview, ServerSummary,
  StorageMount, TrendStats,
} from '@/types'

const overview = ref<OverviewStats | null>(null)
const playback = ref<PlaybackStats | null>(null)
const economy = ref<EconomyStats | null>(null)
const trend = ref<TrendStats | null>(null)
const libraries = ref<EmbyLibrary[]>([])
/** 存储来源：交付链的起点——挂载断了，媒体库扫不到、也播不了 */
const mounts = ref<StorageMount[]>([])
/** 服务器接入情况：面板到底接了几台后端服 / 几台 Emby 服 / 有没有接下载器 */
const servers = ref<ServerSummary | null>(null)
/** 后端服务：aetrix-api + aetrix-worker 的运行状态 */
const backendServices = ref<BackendServiceStatus[]>([])
/** 多服运营：每个服的会员 / 内容 / 节点，一个面板同时管几个服一眼看完 */
const realms = ref<RealmOverview | null>(null)
const loading = ref(true)
const trendLoading = ref(false)

const days = ref(14)
type Metric = 'new_users' | 'plays' | 'revenue' | 'checkins'
const metric = ref<Metric>('new_users')
// 趋势图指标语义色：每个指标固定一种颜色便于区分，且 stop-color / stroke 等 SVG 属性不支持 var()，故保留硬编码
const metricTabs: { key: Metric; label: string; color: string }[] = [
  { key: 'new_users', label: '新增用户', color: '#22d3ee' },
  { key: 'plays', label: '播放次数', color: '#a78bfa' },
  { key: 'revenue', label: '营收 (¥)', color: '#34d399' },
  { key: 'checkins', label: '签到次数', color: '#fbbf24' },
]

async function loadTrend() {
  trendLoading.value = true
  try {
    trend.value = await fetchStatsTrend(days.value)
  } finally {
    trendLoading.value = false
  }
}

onMounted(async () => {
  try {
    const [o, p, e, libraryData, serverData, realmData, mountData, backendData] = await Promise.all([
      fetchOverview(),
      fetchPlaybackStats(),
      fetchEconomyStats(),
      fetchLibraries().catch(() => ({ libraries: [] as EmbyLibrary[] })),
      fetchServersSummary().catch(() => null),
      fetchRealmOverview().catch(() => null),
      fetchMounts().catch(() => null),
      fetchBackendServices().catch(() => ({ services: [] as BackendServiceStatus[] })),
    ])
    overview.value = o
    playback.value = p
    economy.value = e
    libraries.value = libraryData.libraries
    servers.value = serverData
    realms.value = realmData
    mounts.value = mountData?.mounts || []
    backendServices.value = (backendData as any)?.services || []
    await loadTrend()
  } finally {
    loading.value = false
  }
})

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
    list.push({ label: '待处理工单', count: overview.value.tickets.open, to: '/tickets?status=open', icon: Ticket, tone: 'danger' })
    list.push({ label: '待审求片', count: overview.value.media_seeks.pending, to: '/media-seek?status=pending', icon: MessageSquareDashed, tone: 'warning' })
  }
  if (economy.value) {
    list.push({ label: '待支付订单', count: economy.value.orders.pending, to: '/orders?status=pending', icon: Wallet, tone: 'info' })
  }
  return list
})

const todoTotal = computed(() => todos.value.reduce((s, t) => s + t.count, 0))

// ==================== 交付链数据卡 ====================


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
/** 存储卡改看**本机目录可读性**（v2.46.0）

之前这里看的是 EA 可达性（旧的挂载体检状态），但面板自己真正会因挂载断掉而扫不到的是
本机路径：那个路径在容器里读不到，扫描就会把它当成“来源没了”。所以改成按库的本机目录
判：ok=能列举 / false=有路径读不到 / null=纯远程或没配本机路径，不参与判定。
 */
const mountSummary = computed(() => {
  const libs = libraries.value.filter((l) => !l.is_virtual)
  const local = libs.filter((l) => l.local_dirs_readable !== null)
  const failed = local.filter((l) => l.local_dirs_readable === false)
  return {
    total: libs.length,
    ok: local.filter((l) => l.local_dirs_readable === true).length,
    failed: failed.length,
    unchecked: libs.length - local.length,
    blocked: libs.filter((l) => (l.local_dirs_readable === false)
      && (l.path_entries?.length || 0) > 0).length,
    failedNames: failed.slice(0, 2).map((l) => l.name).join('、'),
    failedMore: failed.length > 2,
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
      key: 'seeks', label: '待处理求片', value: overview.value?.media_seeks.pending ?? 0,
      foot: (overview.value?.media_seeks.pending ?? 0) > 0 ? '点开只看待审核' : '没有待处理求片',
      to: '/media-seek?status=pending', icon: MessageSquareDashed,
      tone: (overview.value?.media_seeks.pending ?? 0) > 0 ? 'warn' : 'plain',
      title: '求片与内容',
    },
    {
      key: 'tickets', label: '待处理工单', value: overview.value?.tickets.open ?? 0,
      foot: (overview.value?.tickets.open ?? 0) > 0 ? '点开只看进行中' : '没有待处理工单',
      to: '/tickets?status=open', icon: Ticket,
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
          + (mount.failed ? ` · 异常 ${mount.failed}${mount.failedNames ? `（${mount.failedNames}${mount.failedMore ? ' 等' : ''}）` : ''}` : '')
          + (mount.unchecked ? ` · 未体检 ${mount.unchecked}` : '')
          + (mount.blocked ? ` · 播放节点够不着 ${mount.blocked}` : '')
        : '还没有存储来源',
      to: '/servers', icon: HardDrive,
      tone: mount.failed || mount.blocked ? 'warn' : mount.total ? 'ok' : 'plain',
      title: '存储来源（按服务器配置）',
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
const PAD = 14

const points = computed(() => {
  const list = values.value
  const n = list.length
  if (n === 0) return []
  const step = n > 1 ? CHART_W / (n - 1) : 0
  return list.map((v, i) => {
    const x = i * step
    const y = CHART_H - PAD - (v / maxValue.value) * (CHART_H - PAD * 2)
    return [x, y] as const
  })
})

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

/** 后端服务状态中文映射：redis_unavailable 这类英文枚举不直接上界面 */
const SERVICE_STATUS_LABEL: Record<string, string> = {
  healthy: '运行中',
  degraded: '降级',
  redis_unavailable: 'Redis 不可用',
  unreachable: '心跳丢失',
}

function serviceStatusLabel(status: string): string {
  return SERVICE_STATUS_LABEL[status] || status
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
      <section class="kpi-grid">
        <RouterLink
          v-for="k in kpis"
          :key="k.key"
          :to="k.to"
          class="admin-card kpi-card"
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
          <div class="stat-value" :class="{ 'stat-accent': svc.status === 'healthy', 'stat-warn-text': svc.status !== 'healthy' }">
            {{ serviceStatusLabel(svc.status) }}
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
            to="/realms"
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

      <!-- 交易概览：每个数字都能点进它自己的明细页（v2.42.10 带筛选深链） -->
      <section class="stat-grid">
        <RouterLink class="stat-tile stat-link" to="/orders?status=paid">
          <div class="stat-label"><Wallet :size="13" /> 累计营收</div>
          <div class="stat-value stat-accent">{{ fmtMoney(economy?.orders.revenue ?? 0) }}</div>
          <div class="stat-foot">{{ economy?.orders.pending ?? 0 }} 笔待支付</div>
        </RouterLink>
        <RouterLink class="stat-tile stat-link" to="/invitations">
          <div class="stat-label"><Coins :size="13" /> 积分存量</div>
          <div class="stat-value">{{ economy?.total_points ?? 0 }}</div>
          <div class="stat-foot">全站用户持有</div>
        </RouterLink>
        <RouterLink class="stat-tile stat-link" to="/users">
          <div class="stat-label"><CalendarCheck :size="13" /> 今日签到</div>
          <div class="stat-value">{{ economy?.checkins_today ?? 0 }}</div>
          <div class="stat-foot">人已签到</div>
        </RouterLink>
        <RouterLink class="stat-tile stat-link" to="/exchange-codes">
          <div class="stat-label"><TicketCheck :size="13" /> 兑换码</div>
          <div class="stat-value">
            {{ economy?.exchange_codes.used ?? 0 }}<span class="stat-sub"> / {{ economy?.exchange_codes.total ?? 0 }}</span>
          </div>
          <div class="stat-foot">已核销 / 已生成</div>
        </RouterLink>
        <RouterLink class="stat-tile stat-link" to="/invitations">
          <div class="stat-label"><Gift :size="13" /> 邀请关系</div>
          <div class="stat-value">{{ economy?.invitations ?? 0 }}</div>
          <div class="stat-foot">累计成功邀请</div>
        </RouterLink>
      </section>

      <!-- 趋势 -->
      <section class="admin-card trend-card">
        <div class="card-header">
          <h2><TrendingUp :size="15" /> 趋势</h2>
          <div class="trend-controls">
            <div class="metric-tabs">
              <button
                v-for="t in metricTabs"
                :key="t.key"
                class="metric-tab"
                :class="{ active: metric === t.key }"
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
          <svg class="chart" :viewBox="`0 0 ${CHART_W} ${CHART_H}`" preserveAspectRatio="none" role="img">
            <defs>
              <linearGradient :id="`grad-${metric}`" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" :stop-color="currentMetric.color" stop-opacity="0.36" />
                <stop offset="100%" :stop-color="currentMetric.color" stop-opacity="0" />
              </linearGradient>
            </defs>
            <path :d="areaPath" :fill="`url(#grad-${metric})`" />
            <path
              :d="linePath"
              fill="none"
              :stroke="currentMetric.color"
              stroke-width="2"
              vector-effect="non-scaling-stroke"
              stroke-linejoin="round"
              stroke-linecap="round"
            />
          </svg>
          <div class="chart-axis">
            <span v-for="(l, i) in axisLabels" :key="l + i">{{ l }}</span>
          </div>
        </div>
      </section>

      <!-- 媒体服务运行态：把媒体库与扫描状态放到首页，而不是让管理员逐页排查（实时会话只在服务健康页展示） -->
      <section v-if="libraries.length" class="ops-grid">
        <div class="admin-card ops-card">
          <div class="card-header">
            <h2>
              <Film :size="15" /> 媒体服务
              <span class="range-hint">条 {{ overview?.emby.total_items ?? 0 }}</span>
            </h2>
            <RouterLink to="/emby" class="card-link">管理媒体库 <ArrowRight :size="13" /></RouterLink>
          </div>
          <div v-if="libraries.length" class="ops-list">
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

      </section>

      <!-- 排行榜 -->
      <section class="stats-two-col" v-if="playback">
        <div class="admin-card">
          <div class="card-header">
            <h2>用户播放排行 <span class="range-hint">近 7 天</span></h2>
          </div>
          <div v-if="playback.user_ranking.length === 0" class="empty-hint">暂无播放数据</div>
          <div v-for="(u, i) in playback.user_ranking" :key="u.username" class="rank-row">
            <span class="rank-index">{{ i + 1 }}</span>
            <span class="rank-name">{{ u.username }}</span>
            <span class="rank-value">{{ u.plays }} 次</span>
          </div>
        </div>

        <div class="admin-card">
          <div class="card-header">
            <h2>热门内容 <span class="range-hint">近 7 天</span></h2>
          </div>
          <div v-if="playback.item_ranking.length === 0" class="empty-hint">暂无播放数据</div>
          <div v-for="(it, i) in playback.item_ranking" :key="it.name" class="rank-row">
            <span class="rank-index">{{ i + 1 }}</span>
            <span class="rank-name">
              {{ it.name }}
              <span class="rank-type">{{ it.type === 'episode' ? '剧集' : it.type === 'movie' ? '电影' : it.type }}</span>
            </span>
            <span class="rank-value">{{ it.plays }} 次</span>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
/* 非健康服务（如 Redis 不可用）：警示色小号字，不再和 30px 大数字抢权重 */
.stat-warn-text {
  color: var(--warning);
  font-size: 16px;
  font-variant-numeric: normal;
  letter-spacing: 0;
}
/* 危险操作全部收在「系统设置 → 危险操作」：这里给个入口，不在仪表盘开第二个现场 */
.danger-jump {
  margin-left: 8px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 11.5px;
}
.danger-jump:hover { color: var(--danger); text-decoration: underline; }
.page-loading { text-align: center; color: var(--text-secondary); padding: 60px 0; }

/* ===== 交付链数据卡（顶部六张，一点直达明细页）===== */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

/* 修饰类：只保留 KPI 横向排版（卡片基础样式走全局 .admin-card） */
.kpi-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
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

/* KPI 大数字：仪表字型（等宽 + tabular-nums + 800，见 tokens.css 的 .stat-num 配方） */
.kpi-value {
  margin-top: 3px;
  font-family: var(--font-mono);
  font-size: 26px;
  font-weight: 800;
  line-height: 1.1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

/* 脚注允许换行（v2.42.5）：nowrap + ellipsis 会把「异常 2（日…」截断，
   到底哪个来源异常反而看不到；换行后完整可读，卡片高度由网格自行拉齐。 */
.kpi-foot {
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text-muted);
  overflow-wrap: anywhere;
  white-space: normal;
}

/* 状态包：颜色只用来提示「有没有要看的」，不当装饰 */
.kpi-card.tone-ok .kpi-icon { background: var(--success-bg); color: var(--success); }
.kpi-card.tone-info .kpi-icon { background: var(--info-bg); color: var(--info); }
.kpi-card.tone-warn { border-color: rgba(251, 191, 36, 0.28); }
.kpi-card.tone-warn .kpi-icon { background: var(--warning-bg); color: var(--warning); }
.kpi-card.tone-warn .kpi-value { color: var(--warning); }
.kpi-card.tone-danger { border-color: rgba(248, 113, 113, 0.28); }
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

/* 交易概览的数字也点得进去：与服务器接入卡同一套「悬停亮边」反馈 */
.stat-link { text-decoration: none; display: block; }
.stat-link:hover { border-color: var(--primary); }
.stat-link .stat-value { color: inherit; }
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

.todo-bar.clear { border-color: rgba(52, 211, 153, 0.25); }

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
.chart { width: 100%; height: 150px; display: block; }

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
  .kpi-card { gap: 10px; }
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
