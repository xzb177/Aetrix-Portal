<script setup lang="ts">
/**
 * 数据概览 — 经营驾驶舱
 *
 * v2.4.0 重构：
 * - 顶部「待办」条：待处理工单 / 待审求片 / 待支付订单，一点直达对应页面
 * - 交易概览：今日营收、累计营收、积分存量、今日签到、兑换码核销、邀请人数
 * - 趋势图：近 7/14/30 天的新增用户 / 播放 / 营收 / 签到（纯 SVG，无额外依赖）
 * - 播放榜：用户榜 + 热门内容榜
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  Film, MessageSquareDashed, Play, Radio, Ticket, Users, Wallet,
  Coins, CalendarCheck, TicketCheck, Gift, ArrowRight, TrendingUp,
  Server, HardDrive, CloudDownload, Download, Route as RealmIcon,
} from 'lucide-vue-next'
import {
  fetchLibraries, fetchOverview, fetchPlaybackStats, fetchRealmOverview, fetchServersSummary,
  fetchSessions, fetchStatsTrend,
} from '@/api/admin'
import { fetchEconomyStats, type EconomyStats } from '@/api/economy'
import type {
  EmbyLibrary, EmbySessionRow, OverviewStats, PlaybackStats, RealmOverview, ServerSummary, TrendStats,
} from '@/types'

const overview = ref<OverviewStats | null>(null)
const playback = ref<PlaybackStats | null>(null)
const economy = ref<EconomyStats | null>(null)
const trend = ref<TrendStats | null>(null)
const libraries = ref<EmbyLibrary[]>([])
const sessions = ref<EmbySessionRow[]>([])
/** 服务器接入情况：面板到底接了几台后端服 / 几台 Emby 服 / 有没有接下载器 */
const servers = ref<ServerSummary | null>(null)
/** 多服运营：每个服的会员 / 内容 / 节点，一个面板同时管几个服一眼看完 */
const realms = ref<RealmOverview | null>(null)
const loading = ref(true)
const trendLoading = ref(false)

const days = ref(14)
type Metric = 'new_users' | 'plays' | 'revenue' | 'checkins'
const metric = ref<Metric>('new_users')
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
    const [o, p, e, libraryData, sessionData, serverData, realmData] = await Promise.all([
      fetchOverview(),
      fetchPlaybackStats(),
      fetchEconomyStats(),
      fetchLibraries().catch(() => ({ libraries: [] as EmbyLibrary[] })),
      fetchSessions().catch(() => ({ sessions: [] as EmbySessionRow[] })),
      fetchServersSummary().catch(() => null),
      fetchRealmOverview().catch(() => null),
    ])
    overview.value = o
    playback.value = p
    economy.value = e
    libraries.value = libraryData.libraries
    sessions.value = sessionData.sessions
    servers.value = serverData
    realms.value = realmData
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
    list.push({ label: '待处理工单', count: overview.value.tickets.open, to: '/tickets', icon: Ticket, tone: 'danger' })
    list.push({ label: '待审求片', count: overview.value.media_seeks.pending, to: '/media-seek', icon: MessageSquareDashed, tone: 'warning' })
  }
  if (economy.value) {
    list.push({ label: '待支付订单', count: economy.value.orders.pending, to: '/orders', icon: Wallet, tone: 'info' })
  }
  return list
})

const todoTotal = computed(() => todos.value.reduce((s, t) => s + t.count, 0))

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

function sessionProgress(session: EmbySessionRow): number {
  if (!session.duration_ticks) return 0
  return Math.min(100, Math.round((session.position_ticks / session.duration_ticks) * 100))
}
</script>

<template>
  <div class="admin-page">
    <div v-if="loading" class="page-loading">加载中…</div>

    <template v-else>
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

      <!-- 系统概览 -->
      <section class="stat-grid">
        <div class="stat-tile">
          <div class="stat-label"><Users :size="13" /> 总用户 / 活跃</div>
          <div class="stat-value">
            {{ overview?.users.total ?? 0 }}<span class="stat-sub"> / {{ overview?.users.active ?? 0 }}</span>
          </div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Film :size="13" /> 媒体条目</div>
          <div class="stat-value stat-accent">{{ overview?.emby.total_items ?? 0 }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Radio :size="13" /> 在线会话</div>
          <div class="stat-value" :class="{ 'stat-accent': (overview?.emby.active_sessions ?? 0) > 0 }">
            {{ overview?.emby.active_sessions ?? 0 }}
          </div>
        </div>
        <div class="stat-tile">
          <div class="stat-label"><Play :size="13" /> 今日播放</div>
          <div class="stat-value">{{ playback?.today.plays ?? 0 }}<span class="stat-sub"> 次 / {{ playback?.today.users ?? 0 }} 人</span></div>
        </div>
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

      <!--
        多服运营：一个面板可以同时运营多个服，每个服的会员 / 内容 / 播放节点都在这里，
        不用一个个切过去看（切当前服在顶栏，管服去「服管理」页）。
      -->
      <section v-if="realms?.realms.length" class="admin-card realm-block">
        <div class="card-header">
          <h2><RealmIcon :size="15" /> 多服运营</h2>
          <span class="realm-sum">
            {{ realms.summary.total_realms }} 个服 · 有效订阅 {{ realms.summary.active_subscriptions }} ·
            播放节点在线 {{ realms.summary.nodes_online }}/{{ realms.summary.nodes }}
          </span>
          <RouterLink class="realm-manage" to="/realms">
            服管理<ArrowRight :size="13" />
          </RouterLink>
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

      <!-- 交易概览 -->
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

      <!-- 媒体服务运行态：把媒体库、扫描与在线播放放到首页，而不是让管理员逐页排查 -->
      <section v-if="libraries.length || sessions.length" class="ops-grid">
        <div class="admin-card ops-card">
          <div class="card-header">
            <h2><Film :size="15" /> 媒体服务</h2>
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

        <div class="admin-card ops-card">
          <div class="card-header">
            <h2><Radio :size="15" /> 实时播放 <span class="range-hint">{{ sessions.length }} 路</span></h2>
            <RouterLink to="/emby" class="card-link">查看会话 <ArrowRight :size="13" /></RouterLink>
          </div>
          <div v-if="sessions.length" class="ops-list">
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
.page-loading { text-align: center; color: var(--text-secondary); padding: 60px 0; }

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
