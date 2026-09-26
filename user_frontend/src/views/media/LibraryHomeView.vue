<script setup lang="ts">
/**
 * 媒体库 —— 一个页面三个分段：浏览 / 收藏 / 观看记录（方案 A，v2.10.0）
 *
 * 此前这三个目的地是顶栏上三个并列的一级入口，占掉主导航 3/5 个位置；
 * 收藏与观看记录本质是媒体库的两种视图（后者也是本站自己的一份历史数据），
 * 于是降级为本页的分段标签，主导航收成：首页 / 媒体库 / 我的。
 *
 * - 分段状态写在 `?tab=`（收藏 / 观看记录），旧地址 `/favorites`、`/history`
 *   重定向过来，书签与外部链接都不会失效；
 * - 只渲染当前分段（v-if），访问 /media 时不会多发两组列表请求；
 * - 浏览分段的数据来自 /emby/* 协议端点（JWT 鉴权），与 Infuse 等客户端共享同一套进度。
 */
import { ref, computed, onMounted, watch, type Component } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { embyApi, backdropUrl, ticksToSeconds, progressPercent, type EmbyItem } from '@/api/emby'
import type { ResumeInfo } from '@/components/media/MediaCard.vue'
import { useToast } from '@/composables/useToast'
import { pageTitle } from '@/composables/useBranding'
import MediaRow from '@/components/media/MediaRow.vue'
import FavoritesView from '@/views/media/FavoritesView.vue'
import HistoryView from '@/views/HistoryView.vue'
import {
  Play, Library, FolderOpen, RefreshCw, Info, Search, Heart, History, Film, ChevronRight,
} from 'lucide-vue-next'

const toast = useToast()

// ==================== 分段：浏览 / 收藏 / 观看记录 ====================

type MediaTab = 'browse' | 'favorites' | 'history'

const TABS: { key: MediaTab; label: string; icon: Component }[] = [
  { key: 'browse', label: '浏览', icon: Film },
  { key: 'favorites', label: '收藏', icon: Heart },
  { key: 'history', label: '观看记录', icon: History },
]

const route = useRoute()
const router = useRouter()

const tab = computed<MediaTab>(() => {
  const t = String(route.query.tab || '')
  return t === 'favorites' || t === 'history' ? t : 'browse'
})

function goTab(key: MediaTab) {
  // replace 而不是 push：切换分段不该在历史栈里堆一串「同一页面」的返回步骤
  router.replace(key === 'browse' ? '/media' : `/media?tab=${key}`)
}

const TAB_TITLES: Record<MediaTab, string> = {
  browse: '媒体库',
  favorites: '我的收藏',
  history: '观看记录',
}

// 路由守卫先写的是「媒体库」，分段不同标题不同，这里覆盖成对应标题
watch(tab, (t) => {
  document.title = pageTitle(TAB_TITLES[t])
}, { immediate: true })

const loading = ref(true)
const views = ref<EmbyItem[]>([])
/**
 * 继续观看：顶层只放 series/movie 级别卡片。
 * 续播的单集按 SeriesId 折叠成剧集卡，卡片用 resume 承载
 * 「看到第X季第X集 · 共Y集」+ 进度条；NextUp 里只有下一集、
 * 没有实际进度的剧集排在后面，副标题显示「下一集：第X季第X集」。
 */
const continueItems = ref<EmbyItem[]>([])
const resumeMap = ref<Record<string, ResumeInfo>>({})
/**
 * 按库分区海报轨：key 为库 Id。完全数据驱动——用户建几个库、叫什么名，
 * 这里就渲染几个分区，不写死任何库名；有内容的库才出分区。
 */
const libraryRails = ref<Record<string, EmbyItem[]>>({})
const railsLoading = ref(false)
/** 有内容的库（ChildCount > 0）：出海报分区；0 条目的库只出现在顶部横滑卡里 */
const viewsWithContent = computed(() => views.value.filter((v) => (v.ChildCount || 0) > 0))
const latest = ref<EmbyItem[]>([])
const favorites = ref<EmbyItem[]>([])

/** 我的收藏行：只放顶层（电影/剧集），单集/季不进首页行 */
const topLevelFavorites = computed(() =>
  favorites.value.filter((f) => f.Type === 'Movie' || f.Type === 'Series').slice(0, 12),
)

// Hero：优先取继续观看第一条（剧集卡带续播信息）
const hero = computed(() => continueItems.value[0] || latest.value[0] || null)
const heroResume = computed(() => (hero.value ? resumeMap.value[hero.value.Id] : null))
const heroBackdrop = computed(() => (hero.value ? backdropUrl(hero.value) : ''))
const heroProgress = computed(() => {
  if (heroResume.value) return heroResume.value.progress
  if (!hero.value?.RunTimeTicks) return 0
  const pos = hero.value.UserData?.PlaybackPositionTicks || 0
  return Math.min(100, Math.round((pos / hero.value.RunTimeTicks) * 100))
})
const heroTag = computed(() => {
  if (!hero.value) return ''
  const r = heroResume.value
  if (r) {
    const ep = r.seasonNumber != null && r.episodeNumber != null
      ? `第${r.seasonNumber}季第${r.episodeNumber}集`
      : r.episodeNumber != null
        ? `第${r.episodeNumber}集`
        : ''
    return r.progress > 0 ? `剧集 · 看到${ep}` : `剧集 · 下一集${ep}`
  }
  return `${typeLabel(hero.value.Type)} · ${heroLeft.value || '继续观看'}`
})
/** Hero 主按钮：续播剧集直达该集（详情页读 ?ep= 自动定位），其余进详情页 */
const heroPlayTo = computed(() => {
  if (!hero.value) return '/media'
  const r = heroResume.value
  return r ? `/media/${hero.value.Id}?ep=${r.episodeId}` : `/media/${hero.value.Id}`
})
const heroLeft = computed(() => {
  if (!hero.value?.RunTimeTicks) return ''
  const remain = ticksToSeconds(hero.value.RunTimeTicks - (hero.value.UserData?.PlaybackPositionTicks || 0))
  const h = Math.floor(remain / 3600)
  const m = Math.round((remain % 3600) / 60)
  return h > 0 ? `还剩 ${h}小时${m}分钟` : `还剩 ${m}分钟`
})

const typeLabel = (t?: string) =>
  ({ Movie: '电影', Series: '剧集', Episode: '剧集' }[t || ''] || '影片')

/** 媒体库入口缩略图：有 backdrop 用图，没有用渐变 + 首字 */
const viewBackdrop = (v: EmbyItem) => backdropUrl(v, 640)

/** Emby CollectionType → 中文类型标签 */
const VIEW_TYPE_LABELS: Record<string, string> = {
  movies: '电影',
  tvshows: '剧集',
  mixed: '混合',
  music: '音乐',
  musicvideos: '音乐视频',
  books: '图书',
  games: '游戏',
  photos: '图片',
  homevideos: '家庭视频',
}
const viewTypeLabel = (v: EmbyItem) =>
  VIEW_TYPE_LABELS[(v.CollectionType || '').toLowerCase()] || ''

async function loadAll() {
  loading.value = true
  try {
    const [v, l, f] = await Promise.all([
      embyApi.getViews().catch((): EmbyItem[] => []),
      embyApi.getLatest().catch((): EmbyItem[] => []),
      embyApi.getFavorites().catch((): EmbyItem[] => []),
    ])
    views.value = v
    latest.value = l
    favorites.value = f
    await loadContinue().catch(() => {})
  } finally {
    loading.value = false
  }
  // 按库海报轨随后流式载入：单个库失败不影响整页
  void loadRails()
}

/** 每个有内容的库取最新 12 个（电影/剧集），做横滑海报轨 */
async function loadRails() {
  railsLoading.value = true
  try {
    const targets = viewsWithContent.value
    const results = await Promise.all(
      targets.map(async (v) => {
        try {
          const res = await embyApi.getItems({
            parentId: v.Id,
            limit: 12,
            sortBy: 'DateCreated',
            sortOrder: 'Descending',
            includeTypes: ['Movie', 'Series'],
          })
          return [v.Id, res.Items] as const
        } catch {
          return [v.Id, [] as EmbyItem[]] as const
        }
      }),
    )
    const map: Record<string, EmbyItem[]> = {}
    for (const [id, items] of results) map[id] = items
    libraryRails.value = map
  } finally {
    railsLoading.value = false
  }
}

/** 继续观看：单集按剧折叠成剧集卡（带续播信息），电影保持原样 */
async function loadContinue() {
  const [resumeEps, nextEps] = await Promise.all([
    embyApi.getResume(24).catch((): EmbyItem[] => []),
    embyApi.getNextUp(24).catch((): EmbyItem[] => []),
  ])
  type Entry =
    | { t: 'm'; item: EmbyItem }
    | { t: 's'; seriesId: string; ep: EmbyItem; partial: boolean }
  const ordered: Entry[] = []
  const seenSeries = new Set<string>()
  const seenMovies = new Set<string>()
  // 有实际进度的优先（后端已按最近播放排序）；NextUp 只补「没有进度但有下一集」的剧
  for (const ep of resumeEps) {
    if (ep.Type === 'Movie') {
      if (!seenMovies.has(ep.Id)) {
        seenMovies.add(ep.Id)
        ordered.push({ t: 'm', item: ep })
      }
    } else if (ep.Type === 'Episode' && ep.SeriesId && !seenSeries.has(ep.SeriesId)) {
      seenSeries.add(ep.SeriesId)
      ordered.push({ t: 's', seriesId: ep.SeriesId, ep, partial: true })
    }
  }
  for (const ep of nextEps) {
    if (ep.Type === 'Episode' && ep.SeriesId && !seenSeries.has(ep.SeriesId)) {
      seenSeries.add(ep.SeriesId)
      ordered.push({ t: 's', seriesId: ep.SeriesId, ep, partial: false })
    } else if (ep.Type === 'Movie' && !seenMovies.has(ep.Id)) {
      seenMovies.add(ep.Id)
      ordered.push({ t: 'm', item: ep })
    }
  }
  // 批量取剧集条目（海报/标题/集数来自剧集本身）
  let seriesById = new Map<string, EmbyItem>()
  if (seenSeries.size) {
    const ids = [...seenSeries]
    const res = await embyApi
      .getItems({ ids, limit: ids.length, recursive: false })
      .catch((): { Items: EmbyItem[] } => ({ Items: [] }))
    seriesById = new Map(res.Items.map((x) => [x.Id, x]))
  }
  const items: EmbyItem[] = []
  const rmap: Record<string, ResumeInfo> = {}
  for (const o of ordered) {
    if (o.t === 'm') {
      items.push(o.item)
      continue
    }
    const sv = seriesById.get(o.seriesId)
    if (!sv) continue
    items.push(sv)
    rmap[sv.Id] = {
      episodeId: o.ep.Id,
      seasonNumber: o.ep.ParentIndexNumber,
      episodeNumber: o.ep.IndexNumber,
      progress: o.partial ? progressPercent(o.ep) : 0,
      totalEpisodes: sv.ChildCount,
    }
  }
  continueItems.value = items.slice(0, 18)
  resumeMap.value = rmap
}

onMounted(() => {
  loadAll().catch(() => toast.error('媒体库加载失败'))
})
</script>

<template>
  <div class="lib-home">
    <!-- 分段：浏览 / 收藏 / 观看记录（导航只留一项，这两个是媒体库的视图） -->
    <div class="container tabs-bar">
      <nav class="seg-tabs au-anim-up" role="tablist" aria-label="媒体库分段">
        <button
          v-for="t in TABS"
          :key="t.key"
          type="button"
          role="tab"
          class="seg-tab"
          :class="{ active: tab === t.key }"
          :aria-selected="tab === t.key"
          @click="goTab(t.key)"
        >
          <component :is="t.icon" :size="15" />
          {{ t.label }}
        </button>
      </nav>
    </div>

    <template v-if="tab === 'browse'">
    <!-- Hero -->
    <section v-if="hero" class="hero" :style="heroBackdrop ? { backgroundImage: `url(${heroBackdrop})` } : {}">
      <div class="hero-shade"></div>
      <div class="container hero-content">
        <span class="hero-tag">{{ heroTag }}</span>
        <h1 class="hero-title">{{ hero.Name }}</h1>
        <div v-if="heroProgress > 0" class="hero-progress">
          <div class="hero-progress-fill" :style="{ width: heroProgress + '%' }"></div>
        </div>
        <div class="hero-actions">
          <RouterLink class="btn primary" :to="heroPlayTo">
            <Play :size="16" />
            {{ heroProgress > 0 ? '继续播放' : heroResume ? '播放下一集' : '立即播放' }}
          </RouterLink>
          <RouterLink class="btn ghost" :to="`/media/${hero.Id}`">
            <Info :size="16" />
            详情
          </RouterLink>
        </div>
      </div>
    </section>

    <div class="container main">
      <!-- 加载中 -->
      <div v-if="loading" class="loading">
        <RefreshCw :size="22" class="spinning" />
        <p>正在加载媒体库…</p>
      </div>

      <!-- 空库 -->
      <div v-else-if="!hero && views.length === 0" class="empty">
        <FolderOpen :size="36" />
        <h2>媒体库还是空的</h2>
        <p>请联系管理员添加媒体目录并扫描，扫描完成后即可在这里浏览和播放。</p>
      </div>

      <template v-else>
        <!-- 搜索入口：跨库检索 -->
        <RouterLink to="/search" class="search-entry au-anim-up">
          <Search :size="17" />
          <span>搜索电影、剧集…</span>
          <span class="search-kbd">全局</span>
        </RouterLink>

        <MediaRow title="继续观看" :items="continueItems" :resume-map="resumeMap" more-to="/media?tab=history" />
        <MediaRow title="最新添加" :items="latest" />
        <MediaRow title="我的收藏" :items="topLevelFavorites" more-to="/media?tab=favorites" />

        <!-- 我的媒体：横向滑动的库卡片（数据驱动：用户建几个库、叫什么名，就显示几个） -->
        <section v-if="views.length" class="my-media">
          <h2 class="row-title">
            <Library :size="18" />
            我的媒体
          </h2>
          <div class="lib-carousel" role="list" aria-label="媒体库分类">
            <RouterLink
              v-for="v in views"
              :key="v.Id"
              :to="{ path: `/library/${v.Id}`, query: { name: v.Name } }"
              class="lib-card au-anim-up"
              :class="{ 'is-empty': !(v.ChildCount || 0) }"
              role="listitem"
            >
              <div
                class="lib-card-bg"
                :style="viewBackdrop(v) ? { backgroundImage: `url(${viewBackdrop(v)})` } : {}"
              >
                <span v-if="!viewBackdrop(v)" class="lib-card-char">{{
                  (v.Name || '?').trim().charAt(0) || '?'
                }}</span>
                <div class="lib-card-shade"></div>
              </div>
              <div class="lib-card-body">
                <span class="lib-card-name">{{ v.Name }}</span>
                <span class="lib-card-count"><template v-if="viewTypeLabel(v)">{{ viewTypeLabel(v) }} · </template>{{ v.ChildCount || 0 }} 个条目</span>
              </div>
              <ChevronRight :size="20" class="lib-card-go" />
            </RouterLink>
          </div>
        </section>

        <!-- 按库分区：有内容的库出横滑海报轨（数据驱动）；加载中显示骨架 -->
        <section v-if="railsLoading && !Object.keys(libraryRails).length && viewsWithContent.length" class="rail-skeleton" aria-hidden="true">
          <div class="sk-title"></div>
          <div class="sk-row">
            <div v-for="i in 4" :key="i" class="sk-card"></div>
          </div>
        </section>
        <MediaRow
          v-for="v in viewsWithContent"
          :key="v.Id"
          :title="v.Name || '媒体库'"
          :items="libraryRails[v.Id] || []"
          :more-to="`/library/${v.Id}?name=${encodeURIComponent(v.Name || '')}`"
        />
      </template>
    </div>
    </template>

    <!-- 其余分段：直接嵌入各自的视图（只渲染当前分段） -->
    <div v-else class="segments">
      <!-- 其余分段内容由各自的视图自带页面骨架 -->
      <FavoritesView v-if="tab === 'favorites'" />
      <HistoryView v-else />
    </div>
  </div>
</template>

<style scoped>
.lib-home {
  min-height: 100vh;
  background: var(--au-bg);
  color: var(--au-text);
  padding-bottom: 3rem;
}

/* Hero */
.hero {
  position: relative;
  min-height: 340px;
  display: flex;
  align-items: flex-end;
  background-size: cover;
  background-position: center 20%;
  background-color: var(--au-bg-soft);
}

/* 遮罩用叠加层令牌，不再是页面里写死的 rgba(7, 11, 18, …)：
   换主题色时 Hero 会跟着变，而不是留在旧颜色上。 */
.hero-shade {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(to top, var(--au-bg) 8%, var(--au-overlay-mid) 45%, var(--au-overlay-soft) 100%),
    linear-gradient(100deg, var(--au-overlay-strong) 25%, transparent 65%);
}

.hero-content {
  position: relative;
  padding-top: 4rem;
  padding-bottom: 2rem;
  width: 100%;
}

.hero-tag {
  display: inline-block;
  padding: 0.3125rem 0.625rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-sm);
  color: var(--au-primary);
  font-size: 0.75rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.hero-title {
  margin: 0 0 0.875rem;
  font-size: 2rem;
  font-weight: 700;
  color: var(--au-text);
  text-shadow: var(--au-shadow-text);
}

.hero-progress {
  max-width: 320px;
  height: 4px;
  background: var(--au-on-image-strong);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 1rem;
}

.hero-progress-fill {
  height: 100%;
  background: var(--au-gradient);
}

.hero-actions {
  display: flex;
  gap: 0.75rem;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  height: 42px;
  padding: 0 1.25rem;
  border-radius: var(--au-r-md);
  font-size: 0.875rem;
  font-weight: 600;
  text-decoration: none;
  border: none;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.btn.primary {
  background: var(--au-gradient);
  color: var(--au-on-primary);
  box-shadow: 0 4px 16px var(--au-primary-glow);
}

.btn.primary:hover {
  box-shadow: 0 6px 20px var(--au-primary-glow);
}

.btn.ghost {
  background: var(--au-on-image);
  color: var(--au-text);
  backdrop-filter: blur(6px);
}

.btn.ghost:hover {
  background: var(--au-on-image-strong);
}

.main {
  padding-top: 2rem;
}

/* ===== 分段标签 ===== */
.tabs-bar {
  padding-top: 1.25rem;
}

.seg-tabs {
  display: inline-flex;
  gap: 0.25rem;
  padding: 0.25rem;
  border-radius: var(--au-r-full);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
}

.seg-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  height: 34px;
  padding: 0 0.9375rem;
  border: none;
  border-radius: var(--au-r-full);
  background: transparent;
  color: var(--au-text-3);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--au-fast) var(--au-ease), color var(--au-fast) var(--au-ease), box-shadow var(--au-fast) var(--au-ease);
}

.seg-tab:hover {
  color: var(--au-text);
  background: var(--au-surface);
}

.seg-tab.active {
  background: var(--au-gradient);
  color: var(--au-on-primary);
}

.seg-tab svg {
  flex-shrink: 0;
}

/* 分段内容：沿用各视图自己的页面骨架 */
.segments {
  padding-top: 0.5rem;
}

@media (max-width: 560px) {
  .seg-tabs { display: flex; width: 100%; }
  .seg-tab { flex: 1; justify-content: center; padding: 0 0.5rem; }
}

.row-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.75rem;
  font-size: 1.0625rem;
  font-weight: 600;
  color: var(--au-text);
}

.row-title svg {
  color: var(--au-primary);
}

/* 加载与空态 */
.loading,
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.625rem;
  padding: 4.5rem 1rem;
  text-align: center;
  color: var(--au-text-3);
}

.empty svg {
  color: var(--au-primary);
  opacity: 0.45;
}

.empty h2 {
  margin: 0.375rem 0 0;
  font-size: 1.0625rem;
  color: var(--au-text-2);
}

.empty p {
  margin: 0;
  max-width: 380px;
  font-size: 0.8125rem;
  line-height: 1.6;
}

/* 用全站共用的 au-spin，不再自己再定义一个同效果的 keyframes */
.spinning {
  animation: au-spin 0.9s linear infinite;
}

/* 搜索入口 */
.search-entry {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  height: 46px;
  padding: 0 1rem;
  margin-bottom: 1.5rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  color: var(--au-text-3);
  font-size: 0.875rem;
  text-decoration: none;
  transition: all var(--au-fast) var(--au-ease);
}

.search-entry:hover {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
  color: var(--au-text-2);
}

.search-entry svg { color: var(--au-primary); }

.search-kbd {
  margin-left: auto;
  padding: 0.125rem 0.5rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-full);
  color: var(--au-primary);
  font-size: 0.6875rem;
  font-weight: 600;
}

/* ===== 我的媒体：横向滑动的库卡片（宽卡 ~72% 屏宽，大圆角，深色） ===== */
.my-media {
  margin-bottom: 2rem;
}

.lib-carousel {
  display: flex;
  gap: 0.75rem;
  overflow-x: auto;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
  margin: 0 -1.25rem;
  padding: 0.25rem 1.25rem 0.5rem;
}

.lib-carousel::-webkit-scrollbar {
  display: none;
}

.lib-card {
  position: relative;
  flex: 0 0 72%;
  max-width: 400px;
  min-height: 132px;
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 1rem 1rem 1rem 1.25rem;
  border-radius: var(--au-r-xl);
  border: 1px solid var(--au-border);
  overflow: hidden;
  text-decoration: none;
  scroll-snap-align: center;
  background: linear-gradient(135deg, var(--au-primary-soft), var(--au-bg-soft));
  transition: transform var(--au-fast) var(--au-ease), border-color var(--au-fast) var(--au-ease), box-shadow var(--au-fast) var(--au-ease);
}

.lib-card:hover {
  transform: translateY(-2px);
  border-color: var(--au-primary-border);
  box-shadow: var(--au-shadow-2);
}

/* 0 条目的库：只出现在横滑卡里，置淡，点进去是空状态页 */
.lib-card.is-empty {
  opacity: 0.62;
}

.lib-card-bg {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  padding-left: 1.25rem;
  background-size: cover;
  background-position: center;
}

.lib-card-char {
  font-size: 4.5rem;
  font-weight: 800;
  line-height: 1;
  color: var(--au-primary);
  opacity: 0.35;
  user-select: none;
}

.lib-card-shade {
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, var(--au-overlay-strong) 25%, var(--au-overlay-mid) 60%, var(--au-overlay-soft));
  pointer-events: none;
}

.lib-card-body {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.lib-card-name {
  font-size: 1.25rem;
  font-weight: 800;
  color: var(--au-text);
  text-shadow: var(--au-shadow-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lib-card-count {
  font-size: 0.75rem;
  color: var(--au-text-3);
  text-shadow: var(--au-shadow-text);
}

.lib-card-go {
  position: relative;
  flex-shrink: 0;
  color: var(--au-text-3);
  transition: color var(--au-fast) var(--au-ease);
}

.lib-card:hover .lib-card-go {
  color: var(--au-primary);
}

/* 按库海报轨加载中的骨架（深色，无白块） */
.rail-skeleton {
  margin-bottom: 2rem;
}

.sk-title {
  width: 120px;
  height: 20px;
  border-radius: 6px;
  background: var(--au-surface-2);
  margin-bottom: 0.75rem;
  animation: au-pulse-soft 1.2s ease-in-out infinite;
}

.sk-row {
  display: flex;
  gap: 0.75rem;
}

.sk-card {
  flex: 0 0 132px;
  aspect-ratio: 2 / 3;
  border-radius: 12px;
  background: var(--au-surface-2);
  animation: au-pulse-soft 1.2s ease-in-out infinite;
}
</style>
