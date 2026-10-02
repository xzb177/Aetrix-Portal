<script setup lang="ts">
/**
 * 客户端策略（v2.26.0）
 *
 * 一句话回答「客户端这边到底允许做什么」：
 *
 * - **转码**：允不允许服务端转码、同时几路、码率上限（省 CPU / 省上行）；
 * - **客户端准入**：哪些 UA 不许进（老版本、盗版客户端），或反过来只允许白名单；
 * - **下载与设备**：是否允许下载、每人几台设备、超限是拒绝还是自动踢最久未用的
 *   （这一组原来在「系统设置」里，属于「客户端能做什么」，搬到这里）。
 *
 * 策略落在 SystemConfig 里，EM 与 EA 共用同一个库 → 面板上改完，出流的 EA 立刻生效。
 * 判定口径：**管理员不受限**（排障时不能被自己的策略挡住）；所有开关缺省 = 与升级前一致。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Activity, AlertTriangle, Cloud, Download, Gauge, HardDrive, Info, RefreshCw, Save, ShieldBan, Smartphone, Trash2, Tv,
} from 'lucide-vue-next'
import {
  cleanLocalCache, fetchCdnConfig, fetchLocalCacheConfig, fetchPlayLines, fetchPlaybackPolicy,
  updateCdnConfig, updateLocalCacheConfig, updatePlaybackPolicy,
} from '@/api/admin'
// 下载与设备风控落在经济设置里（同一批 SystemConfig 键），这里只是换个更顺手的入口
import { fetchEconomySettings, updateEconomySettings } from '@/api/economy'
import type {
  CdnConfig, LocalCacheConfig, LocalCacheEntryInfo, LocalCacheStats, PlaybackPolicy, PlaybackRuntime,
  PlayLineCard, PlayLinesSnapshot,
} from '@/types'
import { useAuthStore } from '@/stores/auth'
import NoticePanel from '@/components/NoticePanel.vue'

const auth = useAuthStore()
// 这两组策略都由服务端限定为超级管理员（见 backend/admin_roles.py 的前缀规则），
// 所以只有一个口径：不是 super 就只读
const isSuper = computed(() => auth.admin?.is_super !== false)

const loading = ref(false)
const savingPolicy = ref(false)
const savingOps = ref(false)
const savingCdn = ref(false)
const savingCache = ref(false)
const cleaningCache = ref(false)

const policy = ref<PlaybackPolicy>({
  transcode_enabled: true,
  max_concurrent_transcodes: 0,
  max_bitrate_kbps: 0,
  blocked_agents: '',
  allowed_agents: '',
})
const runtime = ref<PlaybackRuntime | null>(null)

/** 下载与设备风控（与「系统设置」共用同一批键，这里只是换个更顺手的入口） */
const ops = ref({ allow_download: 'true', device_limit_per_user: '0', device_limit_auto_evict: 'false' })

/** CDN 域名预留（播放三层第 2/3 层）：只做域名预留，默认关闭 */
const cdnConfig = ref<CdnConfig>({
  domain: '', normalized: '', enabled: false, segment_cache_header: '',
})
/** 服务端注册的线路清单（direct / cdn / relay）——展示用，不在这里改 */
const cdnPlayLines = ref<string[]>([])

/**
 * VPS 本地缓存（播放线路「本地缓存」）：默认关闭，开启后热门片自动拉到本机。
 *
 * 用 `reactive` 而不是 `ref`：这一整个对象都是表单字段，模板里到处是 `localCache.xxx` 的
 * v-model 与回显，`reactive` 的对象语义最直白，也不依赖 ref 在模板里的解包行为。
 */
const localCache = reactive<LocalCacheConfig>({
  enabled: false, dir: '', default_dir: '', max_gb: 500, max_bytes: 0,
  hot_days: 7, hot_plays: 3, rate_mbps: 20, busy_rate_mbps: 2, play_line: 'cache',
  max_attempts: 3, active_playback_window_sec: 300,
})
const cacheStats = ref<LocalCacheStats | null>(null)
const cacheEntries = ref<LocalCacheEntryInfo[]>([])

function fmtBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

function fmtRate(r: number | null): string {
  return r === null || r === undefined ? '—' : `${(r * 100).toFixed(1)}%`
}

const cacheStateLabel: Record<string, string> = {
  pending: '排队中', downloading: '下载中', ready: '已缓存', failed: '已失败',
}

const PLAYBACK_NODE_LABEL: Record<string, string> = {
  ea: '分离部署的 EA 节点',
  external: '已有 Emby 服',
  panel: '面板自己（一体化）',
}

async function load() {
  loading.value = true
  try {
    const [p, s, c, lc, ln] = await Promise.all([
      fetchPlaybackPolicy(),
      fetchEconomySettings().catch(() => ({ settings: {} as Record<string, string> })),
      fetchCdnConfig().catch(() => null),
      fetchLocalCacheConfig().catch(() => null),
      // 线路可观测读不到不影响本页其它卡片（CDN / 本地缓存配置）
      fetchPlayLines().catch(() => null),
    ])
    policy.value = p.policy
    runtime.value = p.runtime
    playLines.value = ln
    if (c) {
      cdnConfig.value = c.cdn
      cdnPlayLines.value = c.play_lines
    }
    if (lc) {
      // Object.assign 而不是整体替换：reactive 对象保持同一个引用，模板绑定不会断
      Object.assign(localCache, lc.local_cache)
      cacheStats.value = lc.stats
      cacheEntries.value = lc.entries
    }
    ops.value = {
      allow_download: s.settings.allow_download ?? '',
      device_limit_per_user: s.settings.device_limit_per_user ?? '',
      device_limit_auto_evict: s.settings.device_limit_auto_evict ?? '',
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ==================== 播放线路可观测（Phase 3） ====================
// 四条线路各一张卡片。这里**不改任何线路配置**（配置在下面 CDN / 本地缓存卡片里），
// 只回答“这会儿每条线路怎么样”：能不能用、是不是在降级、有多少人多少流量、效果如何。

const playLines = ref<PlayLinesSnapshot | null>(null)

/** 本机文件整文件直发 / 转码拉流不走本服务响应体，流量口径不包含它们 */
const lineBytesHint = '流量 = 本进程经手的出流量（不含转码时 ffmpeg 的拉流与整文件直发）'

function lineState(card: PlayLineCard): { text: string; cls: string } {
  if (!card.ready) return { text: '降级中', cls: 'warn' }
  if (card.degraded_requests > 0) return { text: '有降级', cls: 'warn' }
  return { text: '正常', cls: 'ok' }
}

/** 降级原因合并成一行（配置缺口 + 运行态，按次数降序） */
function lineDegradeText(card: PlayLineCard): string {
  const parts: string[] = []
  if (card.degraded_by_config) parts.push(card.degraded_by_config)
  card.degraded_reasons.forEach((r) => parts.push(`${r.reason}（${r.count} 次）`))
  return parts.join('；')
}

function lineIdleText(card: PlayLineCard): string {
  if (card.idle_seconds === null) return '本进程内还没人用过'
  if (card.idle_seconds < 60) return '刚刚还在用'
  if (card.idle_seconds < 3600) return `${Math.floor(card.idle_seconds / 60)} 分钟前用过`
  return `${Math.floor(card.idle_seconds / 3600)} 小时前用过`
}

/** 每条线路“效果”那一栏：按线路给不同口径（缓存给命中率、CDN 给缓存口径…） */
function lineEffectText(card: PlayLineCard): string {
  const e = card.effect
  if (card.line === 'cache') {
    if (e.hit_rate === null || e.hit_rate === undefined) return '还没有过查找，命中率待观察'
    return `命中率 ${fmtRate(e.hit_rate)}（命中 ${e.hits ?? 0} / 未命中 ${e.misses ?? 0}）`
  }
  if (card.line === 'cdn') {
    return e.domain ? `回源域名 ${e.domain}` : '未启用或域名未填，播放 URL 走本服务'
  }
  return e.note || ''
}

async function savePolicy() {
  savingPolicy.value = true
  try {
    const res = await updatePlaybackPolicy(policy.value)
    policy.value = res.policy
    ElMessage.success('播放策略已保存（出流的节点下次判定即生效）')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingPolicy.value = false
  }
}

async function saveOps() {
  savingOps.value = true
  try {
    await updateEconomySettings({ ...ops.value })
    ElMessage.success('下载与设备策略已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingOps.value = false
  }
}

async function saveCdn() {
  savingCdn.value = true
  try {
    const res = await updateCdnConfig({
      domain: cdnConfig.value.domain,
      enabled: cdnConfig.value.enabled,
    })
    cdnConfig.value = res.cdn
    ElMessage.success(cdnConfig.value.enabled
      ? 'CDN 预留已启用：播放 URL 走该域名，热门分片由边缘缓存'
      : 'CDN 预留已保存（未启用，播放 URL 与升级前逐字节一致）')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingCdn.value = false
  }
}

const blockedCount = computed(
  () => (policy.value.blocked_agents || '').split(/[,，\n]/).filter((v) => v.trim()).length,
)
const idleSeconds = computed(() => Math.round(runtime.value?.idle_timeout_seconds ?? 0))

/**
 * 数字框写回兜底：el-input-number 自身会钳制，这里再做一次「取整 + 范围」写回，
 * 保证提交的永远是合法整数；清空 / 非法输入回落到下限，不会把 undefined 留在表单里。
 */
function clampCacheNumber(
  field: 'max_gb' | 'hot_days' | 'hot_plays' | 'rate_mbps',
  lo: number,
  hi: number,
  raw: unknown,
) {
  const num = Math.trunc(Number(raw))
  localCache[field] = Number.isFinite(num) ? Math.min(hi, Math.max(lo, num)) : lo
}

async function saveLocalCache() {
  savingCache.value = true
  try {
    const res = await updateLocalCacheConfig({
      enabled: localCache.enabled,
      dir: localCache.dir,
      max_gb: Number(localCache.max_gb) || 0,
      hot_days: Number(localCache.hot_days) || 1,
      hot_plays: Number(localCache.hot_plays) || 1,
      rate_mbps: Number(localCache.rate_mbps) || 0,
    })
    Object.assign(localCache, res.local_cache)
    cacheStats.value = res.stats
    ElMessage.success(localCache.enabled
      ? '本地缓存已启用：热门片会限速拉到本机，用户侧新增「本地缓存」线路'
      : '本地缓存配置已保存（未启用，播放行为与升级前一致）')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingCache.value = false
  }
}

async function cleanLocalCacheMode(mode: 'ready' | 'all') {
  const s = cacheStats.value
  const desc = mode === 'ready'
    ? `清理全部已缓存副本（当前占用 ${fmtBytes(s?.bytes_used || 0)}），记录一并删除，下次播放会重新回源。`
    : '清空本地缓存的全部记录与副本（下载中的那条会等下载完再清）。'
  try {
    await ElMessageBox.confirm(desc, '手动清理本地缓存', {
      type: 'warning', confirmButtonText: '确认清理', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  cleaningCache.value = true
  try {
    const res = await cleanLocalCache(mode)
    cacheStats.value = res.stats
    const fresh = await fetchLocalCacheConfig().catch(() => null)
    if (fresh) cacheEntries.value = fresh.entries
    ElMessage.success(`已清理 ${res.cleaned.removed} 条，释放 ${fmtBytes(res.cleaned.freed_bytes)}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '清理失败')
  } finally {
    cleaningCache.value = false
  }
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">客户端策略</h1>
        <p class="admin-page-desc">
          转码、清晰度与客户端准入：改完对面板与出流的节点同时生效（管理员不受这些策略限制）
        </p>
      </div>
      <div class="admin-page-actions">
        <el-button :loading="loading" @click="load"><RefreshCw :size="15" /></el-button>
      </div>
    </div>

    <el-alert v-if="!isSuper" type="warning" :closable="false" show-icon class="warn">
      <template #title>保存需要超级管理员角色</template>
      <template #default>你可以查看当前策略，但保存会被服务端拒绝。</template>
    </el-alert>

    <!-- 运行态：改上限之前先知道现在跑到什么程度 -->
    <section v-if="runtime" class="admin-card runtime-card">
      <div class="card-header">
        <h2><Gauge :size="15" /> 运行态<span class="range-hint">本进程</span></h2>
        <span class="hint">分离部署时转码跑在 EA 上，这里的数字是面板本机的</span>
      </div>
      <div class="runtime-grid">
        <div class="rt-item">
          <b :class="{ warn: runtime.active_transcodes > 0 }">{{ runtime.active_transcodes }}</b>
          <em>正在转码</em>
        </div>
        <div class="rt-item">
          <b>{{ policy.max_concurrent_transcodes || runtime.capacity }}</b>
          <em>{{ policy.max_concurrent_transcodes ? '策略上限' : '内置上限' }}</em>
        </div>
        <div class="rt-item">
          <b>{{ idleSeconds }}s</b>
          <em>闲置回收</em>
        </div>
        <div class="rt-item">
          <b :class="{ warn: !runtime.ffmpeg_available }">{{ runtime.ffmpeg_available ? '可用' : '未安装' }}</b>
          <em>ffmpeg</em>
        </div>
        <div class="rt-item">
          <b>{{ PLAYBACK_NODE_LABEL[runtime.playback_node] || runtime.playback_node }}</b>
          <em>当前出流</em>
        </div>
      </div>
      <p class="runtime-foot">
        内置上限 {{ runtime.capacity }} 路（来自 <code>EMBY_MAX_TRANSCODES</code> 或 CPU 核数）；
        超上限时只拒绝**新的**转码请求，不会中断正在看的人。
      </p>
    </section>

    <!-- 转码与清晰度 -->
    <section class="admin-card">
      <div class="card-header">
        <h2><Tv :size="15" /> 转码与清晰度</h2>
        <el-button type="primary" :loading="savingPolicy" :disabled="!isSuper" @click="savePolicy">
          <Save :size="14" style="margin-right: 4px" />保存
        </el-button>
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>允许服务端转码</label>
          <p class="field-hint">
            关闭后只放直连 / 直接播放：省 CPU 与上行，但客户端兼容性会变差
            （网页端播放器遇到不支持的编码会播不了）。
          </p>
        </div>
        <el-switch v-model="policy.transcode_enabled" :disabled="!isSuper" />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>并发转码上限</label>
          <p class="field-hint">
            0 = 用进程内置上限（默认按 CPU 核数）。设成具体值后，满了会**拒绝新的转码请求**
            并提示稍后再试，而不是把整台机器的 CPU 打满、所有人一起卡。
          </p>
        </div>
        <el-input-number
          v-model="policy.max_concurrent_transcodes"
          :min="0" :max="200"
          :disabled="!isSuper"
        />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>码率上限</label>
          <p class="field-hint">
            单位 kbps，0 = 不限。客户端就算要 40Mbps 也只按上限给，且直连判定会跟着收紧
            （超过上限的条目改走转码），适合上行有限的部署。
          </p>
        </div>
        <el-input-number
          v-model="policy.max_bitrate_kbps"
          :min="0" :max="200000" :step="1000"
          :disabled="!isSuper"
        />
      </div>
    </section>

    <!-- CDN 域名预留（播放三层第 2/3 层，默认关闭） -->
    <!-- 播放线路可观测（Phase 3）：四条线路各一张卡片，只读；配置在下面两张卡片里改 -->
    <section class="admin-card">
      <div class="card-header">
        <h2><Activity :size="15" /> 播放线路</h2>
        <span class="badge-hint">
          {{ playLines ? `${playLines.lines.filter((l) => l.ready).length} / ${playLines.lines.length} 条就绪` : '加载中…' }}
        </span>
      </div>

      <p class="field-hint" style="margin-top: 0">
        四条线路的<b>健康状态、流量与降级</b>。它们都不会“挂”：任何一条都以降级方式回退到
        另一条（所以功能不会坏），但“降级中”意味着它此刻<b>没按自己该有的方式工作</b>——
        比如本地缓存线路没副本时，用户拿到的其实是回源流。
        <br />
        {{ playLines?.scope_note || lineBytesHint }}
      </p>

      <div v-if="playLines" class="line-grid">
        <div v-for="card in playLines.lines" :key="card.line" class="line-card">
          <div class="line-head">
            <b>{{ card.label }}</b>
            <span class="mini-badge" :class="lineState(card).cls">{{ lineState(card).text }}</span>
            <span v-if="card.degraded_requests > 0" class="mini-badge warn">
              降级 {{ card.degraded_requests }} 次
            </span>
          </div>
          <p class="line-summary">{{ card.summary }}</p>

          <div class="line-metrics">
            <div class="line-metric">
              <b>{{ card.requests }}</b><em>播放请求（本进程）</em>
            </div>
            <div class="line-metric">
              <b>{{ fmtBytes(card.bytes_out) }}</b><em>出流量（本进程）</em>
            </div>
            <div class="line-metric">
              <b>{{ card.users }}</b><em>选了这条的用户</em>
            </div>
          </div>

          <p class="line-ready">
            <span class="line-dot" :class="lineState(card).cls" />{{ card.ready_note }}
          </p>
          <p v-if="lineDegradeText(card)" class="line-degrade">{{ lineDegradeText(card) }}</p>
          <p class="line-effect">{{ lineEffectText(card) }}</p>
          <p class="line-idle">{{ lineIdleText(card) }}</p>
        </div>
      </div>
      <div v-else class="field-hint">线路数据读取失败，下方策略与配置不受影响；点「刷新」重试。</div>
    </section>

    <section class="admin-card">
      <div class="card-header">
        <h2><Cloud :size="15" /> CDN 域名预留</h2>
        <span class="badge-hint">{{ cdnConfig.enabled ? '已启用' : '未启用（默认）' }}</span>
      </div>

      <p class="field-hint" style="margin-top: 0">
        把一个回源到本服务的 CDN 域名填进来并启用：播放 URL（直连流 / HLS 播放列表 / 字幕）
        改走该域名，热门视频分片由 CDN 边缘缓存，省掉源站（Google Drive）的单文件下载配额。
        <b>只做域名预留</b>：备案、证书、回源与缓存规则都在 CDN 厂商控制台自行配置，本服务不代管。
      </p>

      <div class="field-row">
        <div class="field-main">
          <label>CDN 域名</label>
          <p class="field-hint">
            例如 cdn.example.com 或 https://cdn.example.com（省略协议默认 https）。
            该域名必须回源到本服务，否则播放会失败。
          </p>
        </div>
        <el-input
          v-model="cdnConfig.domain"
          class="cdn-input"
          :disabled="!isSuper"
          placeholder="cdn.example.com"
          clearable
        />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>启用 CDN（总开关）</label>
          <p class="field-hint">
            关闭时（默认）播放 URL 与升级前一致；开启后还需域名合法才生效。
            用户侧「线路选择」里的 cdn 线路也只在总开关开启后才出现并生效。
          </p>
        </div>
        <el-switch v-model="cdnConfig.enabled" :disabled="!isSuper" />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>缓存口径</label>
          <p class="field-hint">
            视频分片：<code>{{ cdnConfig.segment_cache_header || 'public, max-age=300, s-maxage=21600' }}</code>
            （边缘可缓存）；播放列表 / API / 302 跳转：<code>no-store</code>（绝不被缓存）。
          </p>
        </div>
        <span class="badge-hint">
          {{ cdnConfig.normalized || '域名未填写' }}
          <template v-if="cdnPlayLines.length">· 线路 {{ cdnPlayLines.join(' / ') }}</template>
        </span>
      </div>

      <div class="save-row">
        <el-button type="primary" :loading="savingCdn" :disabled="!isSuper" @click="saveCdn">
          <Save :size="14" style="margin-right: 4px" />保存 CDN 预留
        </el-button>
      </div>
    </section>

    <!-- VPS 本地缓存（播放线路「本地缓存」，默认关闭） -->
    <section class="admin-card">
      <div class="card-header">
        <h2><HardDrive :size="15" /> VPS 本地缓存</h2>
        <span class="badge-hint">{{ localCache.enabled ? '已启用' : '未启用（默认）' }}</span>
      </div>

      <p class="field-hint" style="margin-top: 0">
        把热门的远程挂载片提前拉到 VPS 本机磁盘：用户切到「本地缓存」线路时优先读本机，
        没有才回源并触发缓存。下载<b>单线程 + 限速</b>，有人在播放时自动降到
        {{ localCache.busy_rate_mbps }}MB/s 让路，不碰 direct / relay / cdn 三条现有线路；
        超配额按 LRU 删最久未访问的副本。只缓存远程挂载来源的条目（本机文件不需要副本）。
      </p>

      <div v-if="cacheStats" class="runtime-grid">
        <div class="rt-item">
          <b>{{ fmtBytes(cacheStats.bytes_used) }}</b>
          <em>已占用 / {{ cacheStats.max_bytes ? fmtBytes(cacheStats.max_bytes) : '不限' }}</em>
        </div>
        <div class="rt-item">
          <b>{{ fmtRate(cacheStats.hit_rate) }}</b>
          <em>命中率（命中 {{ cacheStats.hits }} / 未命中 {{ cacheStats.misses }}）</em>
        </div>
        <div class="rt-item">
          <b>{{ cacheStats.entries.ready || 0 }}</b>
          <em>已缓存 / 共 {{ cacheStats.entries_total }} 条</em>
        </div>
        <div class="rt-item">
          <b :class="{ warn: !cacheStats.dir_exists }">
            {{ cacheStats.dir_exists ? fmtBytes(cacheStats.disk_free_bytes) : '目录不存在' }}
          </b>
          <em>磁盘剩余</em>
        </div>
        <div class="rt-item">
          <b>{{ cacheStats.entries.downloading || 0 }} / {{ cacheStats.entries.pending || 0 }}</b>
          <em>下载中 / 排队</em>
        </div>
      </div>
      <p v-if="cacheStats" class="runtime-foot">
        目录 <code>{{ cacheStats.dir }}</code>；热门规则：近 {{ localCache.hot_days }} 天播放
        ≥ {{ localCache.hot_plays }} 次即自动缓存；下载限速
        {{ localCache.rate_mbps ? `${localCache.rate_mbps} MB/s` : '不限速' }}。
        <template v-if="cacheStats.entries.failed">失败 {{ cacheStats.entries.failed }} 条（可在下方清理）。</template>
      </p>

      <div class="field-row">
        <div class="field-main">
          <label>启用本地缓存（总开关）</label>
          <p class="field-hint">
            关闭时（默认）播放行为与升级前一致；开启后用户侧「线路选择」才会出现 cache 线路，
            后台 worker 开始按热门规则拉片。
          </p>
        </div>
        <el-switch v-model="localCache.enabled" :disabled="!isSuper" />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>缓存目录</label>
          <p class="field-hint">
            绝对路径，留空用默认目录 <code>{{ localCache.default_dir }}</code>。
            目录所在磁盘要装得下配额，建议指向数据盘。
          </p>
        </div>
        <el-input
          v-model="localCache.dir"
          class="cdn-input"
          :disabled="!isSuper"
          :placeholder="localCache.default_dir"
          clearable
        />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>最大占用（GB）</label>
          <p class="field-hint">超过配额时按 LRU 删除最久未访问的副本；0 = 不限制。</p>
        </div>
        <el-input-number
          v-model="localCache.max_gb"
          :min="0" :max="100000" :step="50"
          :disabled="!isSuper"
          @change="clampCacheNumber('max_gb', 0, 100000, $event)"
        />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>热门判定规则</label>
          <p class="field-hint">近 N 天内播放达到 M 次的片子自动入队下载（按播放次数从多到少排队）。</p>
        </div>
        <!--
          两个数字框放在 .num-pair 里：桌面并排；窄屏（响应式层会把 .el-input-number 拉成 100%）
          允许换行、并保留可读宽度——之前挤在一行里时数字会被两侧按钮盖住、看着像空框。
        -->
        <div class="num-pair">
          <el-input-number
            v-model="localCache.hot_days"
            :min="1" :max="90" :step="1"
            :disabled="!isSuper"
            @change="clampCacheNumber('hot_days', 1, 90, $event)"
          />
          <span class="badge-hint">天内 ≥</span>
          <el-input-number
            v-model="localCache.hot_plays"
            :min="1" :max="1000" :step="1"
            :disabled="!isSuper"
            @change="clampCacheNumber('hot_plays', 1, 1000, $event)"
          />
          <span class="badge-hint">次</span>
        </div>
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>下载限速（MB/s）</label>
          <p class="field-hint">
            缓存下载占用的带宽上限，0 = 不限速；检测到有人在播放时自动降到
            {{ localCache.busy_rate_mbps }}MB/s 给播放让路，绝不抢当前播放的带宽。
          </p>
        </div>
        <el-input-number
          v-model="localCache.rate_mbps"
          :min="0" :max="10000" :step="5"
          :disabled="!isSuper"
          @change="clampCacheNumber('rate_mbps', 0, 10000, $event)"
        />
      </div>

      <div v-if="cacheEntries.length" class="cache-list">
        <div v-for="e in cacheEntries.slice(0, 6)" :key="e.item_guid" class="cache-item">
          <span class="ci-name">{{ e.name || e.source_path }}</span>
          <span class="ci-meta">
            <b :class="{ warn: e.state === 'failed' }">{{ cacheStateLabel[e.state] || e.state }}</b>
            · {{ fmtBytes(e.file_size) }} · 命中 {{ e.hits }}
            <template v-if="e.last_accessed_at"> · 最近访问 {{ e.last_accessed_at.slice(0, 16).replace('T', ' ') }}</template>
          </span>
        </div>
      </div>

      <div class="save-row">
        <el-button
          :loading="cleaningCache" :disabled="!isSuper || !cacheEntries.length"
          @click="cleanLocalCacheMode('ready')"
        >
          <Trash2 :size="14" style="margin-right: 4px" />清理缓存副本
        </el-button>
        <el-button
          :loading="cleaningCache" :disabled="!isSuper"
          @click="cleanLocalCacheMode('all')"
        >
          <Trash2 :size="14" style="margin-right: 4px" />清空全部
        </el-button>
        <el-button type="primary" :loading="savingCache" :disabled="!isSuper" @click="saveLocalCache">
          <Save :size="14" style="margin-right: 4px" />保存本地缓存
        </el-button>
      </div>
    </section>

    <!-- 客户端准入 -->
    <section class="admin-card">
      <div class="card-header">
        <h2><ShieldBan :size="15" /> 客户端准入</h2>
        <span class="badge-hint">{{ blockedCount }} 条黑名单规则</span>
      </div>

      <div class="field-row column">
        <label>客户端黑名单（UA 子串，逗号分隔）</label>
        <el-input
          v-model="policy.blocked_agents"
          type="textarea"
          :rows="2"
          :disabled="!isSuper"
          placeholder="例如：Old-TV, Emby/2.0, 盗版播放器"
        />
        <p class="field-hint">
          按子串匹配（不区分大小写）：命中就拒绝，连播放信息都拿不到。
          <b>管理员不受限</b>，排障时不会被自己的规则挡住。
        </p>
      </div>

      <div class="field-row column">
        <label>客户端白名单（填了就只放行列表内的客户端）</label>
        <el-input
          v-model="policy.allowed_agents"
          type="textarea"
          :rows="2"
          :disabled="!isSuper"
          placeholder="例如：Emby, Infuse, SenPlayer（留空 = 不限制）"
        />
        <p class="field-hint">
          白名单优先于黑名单；开启后无法识别 UA 的请求（脚本 / 未知客户端）也会被拒。
        </p>
      </div>

      <div class="save-row">
        <el-button type="primary" :loading="savingPolicy" :disabled="!isSuper" @click="savePolicy">
          <Save :size="14" style="margin-right: 4px" />保存客户端准入
        </el-button>
      </div>
    </section>

    <!-- 下载与设备（原来在系统设置里） -->
    <section class="admin-card">
      <div class="card-header">
        <h2><Download :size="15" /> 下载与设备</h2>
        <el-button :loading="savingOps" :disabled="!isSuper" @click="saveOps">
          <Save :size="14" style="margin-right: 4px" />保存
        </el-button>
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>允许下载</label>
          <p class="field-hint">
            关闭后客户端下载（含 <code>/Items/{id}/File</code>）一并拦截，管理员不受限。
          </p>
        </div>
        <el-switch
          :model-value="ops.allow_download === 'true'"
          :disabled="!isSuper"
          @update:model-value="(v: string | number | boolean) => (ops.allow_download = v ? 'true' : 'false')"
        />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>设备上限（台 / 人）</label>
          <p class="field-hint">0 或不填表示不限；只统计近 30 天活跃设备。</p>
        </div>
        <el-input v-model="ops.device_limit_per_user" class="num-input" :disabled="!isSuper" />
      </div>

      <div class="field-row">
        <div class="field-main">
          <label>超限自动踢人</label>
          <p class="field-hint">
            开启则自动移除最久未使用的设备；关闭则直接拒绝新设备登录。
          </p>
        </div>
        <el-switch
          :model-value="ops.device_limit_auto_evict === 'true'"
          :disabled="!isSuper"
          @update:model-value="(v: string | number | boolean) => (ops.device_limit_auto_evict = v ? 'true' : 'false')"
        />
      </div>

      <p class="runtime-foot">
        <Smartphone :size="13" /> 逐台设备与登录日志在「设备与安全 / 登录日志」；这里的策略只决定
        「多一台设备时怎么处理」。
      </p>
    </section>

    <NoticePanel
      title="为什么这些策略在这里，而系统设置在别处"
      summary="客户端能力与站点运营设置各归其位"
      :icon="Info"
      storage-key="client-policy-scope"
      class="guide-panel"
    >
      <div class="policy-guide">
        这里只放「客户端能做什么」（转码、清晰度、准入、下载与设备）；
        「站点怎么运营」（注册、支付、付费墙、邀请返利）仍然在系统设置里。
      </div>
    </NoticePanel>

    <p v-if="!isSuper" class="readonly-foot">
      <AlertTriangle :size="13" />
      当前账号不是超级管理员：这一页可以查看，保存会被服务端拒绝（这些策略会改变所有人的播放体验）。
    </p>
  </div>
</template>

<style scoped>
.warn { margin-top: 14px; }
.guide-panel { margin-top: 14px; }
.policy-guide { line-height: 1.7; }
.hint, .badge-hint { font-size: var(--font-size-xs); color: var(--text-muted); }
.range-hint { font-size: var(--font-size-xs); color: var(--text-muted); font-weight: 400; }

.runtime-card { margin-bottom: 14px; }
.runtime-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
}
.rt-item { display: flex; flex-direction: column; gap: 2px; }
.rt-item b {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.rt-item b.warn { color: var(--warning); }
.rt-item em { font-style: normal; font-size: var(--font-size-xs); color: var(--text-muted); }
.runtime-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 14px 0 0;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  flex-wrap: wrap;
}

.admin-card + .admin-card { margin-top: 14px; }

/* ============ 播放线路可观测卡片（Phase 3） ============ */
.line-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
}

.line-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
}

/* 就绪 / 降级：只在标题行的小圆点上用颜色，卡片本体不染色（避免整块变色压迫阅读） */
.line-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.line-head b { font-size: var(--font-size-sm); color: var(--text-primary); }

.line-summary {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  line-height: 1.7;
}

.line-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin: 2px 0;
}
.line-metric { display: flex; flex-direction: column; gap: 1px; }
.line-metric b {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.line-metric em {
  font-style: normal;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  line-height: 1.4;
}

.line-ready,
.line-degrade,
.line-effect,
.line-idle {
  margin: 0;
  font-size: var(--font-size-xs);
  line-height: 1.7;
  color: var(--text-muted);
}
.line-ready { display: flex; align-items: flex-start; gap: 6px; }
.line-degrade { color: var(--warning); }
.line-idle { color: var(--text-tertiary); }

.line-dot {
  width: 6px;
  height: 6px;
  margin-top: 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
  background: var(--text-muted);
}
.line-dot.ok { background: var(--success); }
.line-dot.warn { background: var(--warning); }

.field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.field-row:last-of-type { border-bottom: none; }
.field-row.column { flex-direction: column; align-items: stretch; gap: 8px; }
.field-main { min-width: 0; }
.field-row label { font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--text-primary); }
.field-hint { margin: 4px 0 0; font-size: var(--font-size-xs); color: var(--text-muted); line-height: 1.6; }
.num-input { width: 120px; }
.cdn-input { width: 260px; }

/* 热门判定规则的两个数字框：并排时不被压扁，窄屏允许换行 */
.num-pair { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
.num-pair .el-input-number { flex: none; }

@media (max-width: 640px) {
  /*
    窄屏下响应式层会把 .el-input-number 统一拉成 100%：两个数字框挤在同一行里会
    互相抢宽度，数字被两侧的加减按钮盖住（看着像空框、点了也“没反应”）。
    这里让它们各占一行、并保证一个可读的最小宽度。
  */
  .admin-card .num-pair { width: 100%; }
  .admin-card .num-pair .el-input-number {
    flex: 1 1 120px;
    width: auto !important;
    min-width: 112px;
  }
}
.cache-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 12px;
  border-bottom: 1px solid var(--border-subtle);
}
.cache-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg-glass);
}
.cache-item .ci-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}
.cache-item .ci-meta {
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.cache-item .ci-meta b { font-weight: var(--font-weight-medium); }
.cache-item .ci-meta b.warn { color: var(--warning); }
.save-row { display: flex; justify-content: flex-end; padding-top: 4px; }
code {
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: var(--bg-glass);
  font-size: 11.5px;
}
.readonly-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 12px 0 0;
  font-size: var(--font-size-xs);
  color: var(--warning);
}
</style>
