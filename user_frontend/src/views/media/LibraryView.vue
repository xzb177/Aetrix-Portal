<script setup lang="ts">
/**
 * 媒体库浏览页 — 网格 + 搜索 + 类型/排序 + 高级筛选 + 无限滚动
 *
 * 后端其实一直把筛选做好了：`/Items/Filters` 给出全库的类型 / 标签 / 分级 / 年份取值，
 * `/Items` 也支持 `Genres` / `Years` / `OfficialRatings` / `Tags` 与「只看未看 / 收藏」，
 * `embyApi.getItems` 更是早就留了 `genres` / `years` 两个参数——但页面上从来没有任何
 * 入口用到它们，用户在这个页面里除了搜片名就只有「电影 / 剧集」一个下拉。
 * 这里把整份筛选菜单接上。
 *
 * 两个取舍：
 * - **筛选条件写进地址栏**（用 `replace`，不堆历史记录）：刷新、收藏、把链接发给别人，
 *   看到的都是同一批结果；同时因为不 push，点返回是离开本页而不是逐个撤销筛选。
 * - **筛选项拿不到不影响浏览**：`/Items/Filters` 失败时只是没有可选项，网格照常出内容，
 *   不会因为一个辅助接口把整个媒体库变成错误页。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { embyApi, posterUrl, progressPercent, type EmbyItem, type EmbyFilters } from '@/api/emby'
import MediaCard from '@/components/media/MediaCard.vue'
import {
  Search, X, ArrowUpDown, FolderOpen, SlidersHorizontal, Check, RotateCcw,
  LayoutGrid, List as ListIcon, ChevronRight,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()

const libId = computed(() => (route.params.id as string) || '')
const libName = ref((route.query.name as string) || '媒体库')

const items = ref<EmbyItem[]>([])
const total = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const search = ref('')
const typeFilter = ref('')
const DEFAULT_SORT = 'SortName:Ascending'
const sort = ref(DEFAULT_SORT)

// ==================== 网格 / 列表视图 ====================

type ViewMode = 'grid' | 'list'
const VIEW_KEY = 'aetrix-library-view'
const viewMode = ref<ViewMode>(
  ((): ViewMode => {
    try {
      return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'grid'
    } catch {
      return 'grid'
    }
  })(),
)

function setViewMode(m: ViewMode) {
  viewMode.value = m
  try {
    localStorage.setItem(VIEW_KEY, m)
  } catch {
    /* 无痕模式等写不进就下次再说 */
  }
}

/** 列表行点击：与 MediaCard 同口径（单集跳到所属剧集） */
function openItem(item: EmbyItem) {
  const target =
    item.Type === 'Episode' && item.SeriesId ? `/media/${item.SeriesId}` : `/media/${item.Id}`
  router.push(target)
}

// ==================== A-Z 快跳 ====================

const LETTERS = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '#']

/** 在已加载的卡片里找首个首字母匹配项并滚动定位（无限滚动只搜已加载部分） */
function jumpToLetter(letter: string) {
  const els = Array.from(document.querySelectorAll<HTMLElement>('[data-sortkey]'))
  for (const el of els) {
    const c = (el.dataset.sortkey || '').trim().charAt(0).toUpperCase()
    const key = c >= 'A' && c <= 'Z' ? c : '#'
    if (key === letter) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      break
    }
  }
}

// ==================== 高级筛选 ====================

const filters = ref<EmbyFilters>({ Genres: [], Tags: [], OfficialRatings: [], Years: [] })
const filtersLoading = ref(false)
const panelOpen = ref(false)

const genres = ref<string[]>([])
const years = ref<number[]>([])
const ratings = ref<string[]>([])
const tags = ref<string[]>([])
const watchState = ref('')

/** 观看状态 → 后端的 Filters 开关（这四个后端都已经实现，不是前端自己过滤） */
const STATE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'IsUnplayed', label: '未看' },
  { value: 'IsPlayed', label: '已看' },
  { value: 'IsResumable', label: '继续观看' },
  { value: 'IsFavorite', label: '收藏' },
]

const activeCount = computed(
  () =>
    genres.value.length +
    years.value.length +
    ratings.value.length +
    tags.value.length +
    (watchState.value ? 1 : 0)
)

/** 取值可能上百个（类型 / 标签尤其），先露一批，其余折起来 */
const CHIP_LIMIT = 14
const expanded = ref<Record<string, boolean>>({})

function visible(list: string[], key: string): string[] {
  return expanded.value[key] ? list : list.slice(0, CHIP_LIMIT)
}

const visibleYears = computed(() =>
  expanded.value.years ? filters.value.Years : filters.value.Years.slice(0, CHIP_LIMIT)
)

/** 模板里 ref 会自动解包，所以这里直接收数组、原地增删（深度 watch 会跟着触发） */
function toggleStr(list: string[], value: string) {
  const i = list.indexOf(value)
  if (i >= 0) list.splice(i, 1)
  else list.push(value)
}

function toggleYear(value: number) {
  const i = years.value.indexOf(value)
  if (i >= 0) years.value.splice(i, 1)
  else years.value.push(value)
}

function clearFilters() {
  genres.value = []
  years.value = []
  ratings.value = []
  tags.value = []
  watchState.value = ''
}

// ==================== 地址栏同步 ====================

const qStr = (v: unknown): string =>
  typeof v === 'string' ? v : Array.isArray(v) ? String(v[0] ?? '') : ''

function applyFromQuery(q: Record<string, unknown>) {
  search.value = qStr(q.q)
  typeFilter.value = qStr(q.type)
  sort.value = qStr(q.sort) || DEFAULT_SORT
  const split = (raw: string, sep: string) => (raw ? raw.split(sep).filter(Boolean) : [])
  genres.value = split(qStr(q.genres), '|')
  ratings.value = split(qStr(q.ratings), ',')
  tags.value = split(qStr(q.tags), '|')
  years.value = split(qStr(q.years), ',').map(Number).filter((n) => Number.isFinite(n))
  watchState.value = STATE_OPTIONS.some((o) => o.value === qStr(q.state)) ? qStr(q.state) : ''
}

function queryFromState(): Record<string, string> {
  const out: Record<string, string> = {}
  if (search.value.trim()) out.q = search.value.trim()
  if (typeFilter.value) out.type = typeFilter.value
  if (sort.value !== DEFAULT_SORT) out.sort = sort.value
  if (genres.value.length) out.genres = genres.value.join('|')
  if (years.value.length) out.years = years.value.join(',')
  if (ratings.value.length) out.ratings = ratings.value.join(',')
  if (tags.value.length) out.tags = tags.value.join('|')
  if (watchState.value) out.state = watchState.value
  return out
}

/** 键序无关的比较：避免每次渲染都因为顺序不同而多走一次 router.replace */
function sameQuery(a: Record<string, string>, b: Record<string, string>): boolean {
  const ka = Object.keys(a).sort()
  const kb = Object.keys(b).sort()
  return ka.length === kb.length && ka.every((k, i) => k === kb[i] && a[k] === b[k])
}

function syncUrl() {
  const target = queryFromState()
  // 库名是只读参数（从媒体库页带过来），刷新后要能继续显示
  const name = qStr(route.query.name)
  if (name) target.name = name
  const cur: Record<string, string> = {}
  for (const [k, v] of Object.entries(route.query)) {
    const s = qStr(v)
    if (s) cur[k] = s
  }
  if (sameQuery(cur, target)) return
  router.replace({ query: target })
}

// ==================== 加载 ====================

const PAGE = 30
let searchTimer: ReturnType<typeof setTimeout> | null = null

const sortOptions = [
  { value: 'SortName:Ascending', label: '名称 A-Z' },
  { value: 'SortName:Descending', label: '名称 Z-A' },
  { value: 'DateCreated:Descending', label: '最新添加' },
  { value: 'ProductionYear:Descending', label: '年份 新→旧' },
  { value: 'CommunityRating:Descending', label: '评分最高' },
]

const typeOptions = [
  { value: '', label: '全部' },
  { value: 'Movie', label: '电影' },
  { value: 'Series', label: '剧集' },
]

async function loadFilters() {
  filtersLoading.value = true
  try {
    filters.value = await embyApi.getFilters()
  } catch {
    // 辅助接口挂了不该把媒体库变成错误页：只是没有可选项，网格照常
    filters.value = { Genres: [], Tags: [], OfficialRatings: [], Years: [] }
  } finally {
    filtersLoading.value = false
  }
}

async function load(reset = true) {
  if (reset) {
    loading.value = true
    items.value = []
  } else {
    loadingMore.value = true
  }
  try {
    const [sortBy, sortOrder] = sort.value.split(':')
    const res = await embyApi.getItems({
      parentId: libId.value || undefined,
      includeTypes: typeFilter.value ? [typeFilter.value] : undefined,
      searchTerm: search.value || undefined,
      genres: genres.value.length ? genres.value : undefined,
      years: years.value.length ? years.value : undefined,
      officialRatings: ratings.value.length ? ratings.value : undefined,
      tags: tags.value.length ? tags.value : undefined,
      filters: watchState.value ? [watchState.value] : undefined,
      sortBy,
      sortOrder: sortOrder as 'Ascending' | 'Descending',
      startIndex: reset ? 0 : items.value.length,
      limit: PAGE,
    })
    if (reset) {
      items.value = res.Items
    } else {
      items.value.push(...res.Items)
    }
    total.value = res.TotalRecordCount
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function hasMore() {
  return items.value.length < total.value
}

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    syncUrl()
    load(true)
  }, 350)
}

/** 任何筛选/排序变化：先写地址栏，再重新拉第一页 */
function onFilterChange() {
  syncUrl()
  load(true)
}

// 无限滚动
function onScroll() {
  if (loading.value || loadingMore.value || !hasMore()) return
  const nearBottom = window.innerHeight + window.scrollY >= document.body.offsetHeight - 600
  if (nearBottom) load(false)
}

// 初始条件来自地址栏。必须在注册 watch **之前**套用：否则挂载时会被当成
// 一次「筛选变化」再拉一遍列表，白白多一个请求。
applyFromQuery(route.query as Record<string, unknown>)

watch([typeFilter, sort], onFilterChange)
watch([genres, years, ratings, tags, watchState], onFilterChange, { deep: true })
watch(libId, () => load(true))

onMounted(() => {
  window.addEventListener('scroll', onScroll)
  loadFilters()
  load(true)
})

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
  window.removeEventListener('scroll', onScroll)
})
</script>

<template>
  <div class="library-view">
    <div class="container">
      <!-- 头部 -->
      <header class="page-head">
        <div class="head-left">
          <RouterLink to="/media" class="back-btn">
            <X :size="16" />
          </RouterLink>
          <div>
            <h1 class="page-title">{{ libName }}</h1>
            <p class="page-sub">
              {{ total }} 个条目<template v-if="activeCount"> · 已筛选 {{ activeCount }} 项</template>
            </p>
          </div>
        </div>
      </header>

      <!-- 工具栏 -->
      <div class="toolbar">
        <div class="search-box">
          <Search :size="15" class="search-icon" />
          <input
            v-model="search"
            type="text"
            placeholder="搜索片名…"
            @input="onSearchInput"
          />
        </div>
        <select v-model="typeFilter" class="toolbar-select">
          <option v-for="o in typeOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <select v-model="sort" class="toolbar-select">
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <div class="view-toggle" role="group" aria-label="视图切换">
          <button
            type="button"
            class="vt-btn"
            :class="{ on: viewMode === 'grid' }"
            title="网格视图"
            @click="setViewMode('grid')"
          >
            <LayoutGrid :size="15" />
          </button>
          <button
            type="button"
            class="vt-btn"
            :class="{ on: viewMode === 'list' }"
            title="列表视图"
            @click="setViewMode('list')"
          >
            <ListIcon :size="15" />
          </button>
        </div>
        <button
          type="button"
          class="filter-toggle"
          :class="{ on: panelOpen || activeCount > 0 }"
          @click="panelOpen = !panelOpen"
        >
          <SlidersHorizontal :size="15" />
          筛选
          <span v-if="activeCount" class="filter-badge">{{ activeCount }}</span>
        </button>
      </div>

      <!-- 已选条件 -->
      <div v-if="activeCount" class="active-filters">
        <span class="af-label">已选</span>
        <button
          v-for="g in genres"
          :key="`g-${g}`"
          type="button"
          class="af-chip"
          @click="toggleStr(genres, g)"
        >
          {{ g }}<X :size="12" />
        </button>
        <button
          v-for="y in years"
          :key="`y-${y}`"
          type="button"
          class="af-chip"
          @click="toggleYear(y)"
        >
          {{ y }}<X :size="12" />
        </button>
        <button
          v-for="r in ratings"
          :key="`r-${r}`"
          type="button"
          class="af-chip"
          @click="toggleStr(ratings, r)"
        >
          {{ r }}<X :size="12" />
        </button>
        <button
          v-for="t in tags"
          :key="`t-${t}`"
          type="button"
          class="af-chip"
          @click="toggleStr(tags, t)"
        >
          {{ t }}<X :size="12" />
        </button>
        <button
          v-if="watchState"
          type="button"
          class="af-chip"
          @click="watchState = ''"
        >
          {{ STATE_OPTIONS.find((o) => o.value === watchState)?.label }}<X :size="12" />
        </button>
        <button type="button" class="af-clear" @click="clearFilters">
          <RotateCcw :size="12" /> 清除全部
        </button>
      </div>

      <!-- 筛选面板 -->
      <div v-if="panelOpen" class="filter-panel">
        <p v-if="filtersLoading" class="fp-loading">正在读取筛选项…</p>
        <template v-else>
          <div class="fp-group">
            <div class="fp-title">观看状态</div>
            <div class="fp-chips">
              <button
                v-for="o in STATE_OPTIONS"
                :key="o.value"
                type="button"
                class="fp-chip"
                :class="{ on: watchState === o.value }"
                @click="watchState = o.value"
              >
                <Check v-if="watchState === o.value" :size="12" />{{ o.label }}
              </button>
            </div>
          </div>

          <div v-if="filters.Genres.length" class="fp-group">
            <div class="fp-title">类型</div>
            <div class="fp-chips">
              <button
                v-for="g in visible(filters.Genres, 'genres')"
                :key="g"
                type="button"
                class="fp-chip"
                :class="{ on: genres.includes(g) }"
                @click="toggleStr(genres, g)"
              >
                <Check v-if="genres.includes(g)" :size="12" />{{ g }}
              </button>
              <button
                v-if="filters.Genres.length > CHIP_LIMIT"
                type="button"
                class="fp-more"
                @click="expanded.genres = !expanded.genres"
              >
                {{ expanded.genres ? '收起' : `更多（${filters.Genres.length}）` }}
              </button>
            </div>
          </div>

          <div v-if="filters.Years.length" class="fp-group">
            <div class="fp-title">年份</div>
            <div class="fp-chips">
              <button
                v-for="y in visibleYears"
                :key="y"
                type="button"
                class="fp-chip"
                :class="{ on: years.includes(y) }"
                @click="toggleYear(y)"
              >
                <Check v-if="years.includes(y)" :size="12" />{{ y }}
              </button>
              <button
                v-if="filters.Years.length > CHIP_LIMIT"
                type="button"
                class="fp-more"
                @click="expanded.years = !expanded.years"
              >
                {{ expanded.years ? '收起' : `更多（${filters.Years.length}）` }}
              </button>
            </div>
          </div>

          <div v-if="filters.OfficialRatings.length" class="fp-group">
            <div class="fp-title">分级</div>
            <div class="fp-chips">
              <button
                v-for="r in filters.OfficialRatings"
                :key="r"
                type="button"
                class="fp-chip"
                :class="{ on: ratings.includes(r) }"
                @click="toggleStr(ratings, r)"
              >
                <Check v-if="ratings.includes(r)" :size="12" />{{ r }}
              </button>
            </div>
          </div>

          <div v-if="filters.Tags.length" class="fp-group">
            <div class="fp-title">标签</div>
            <div class="fp-chips">
              <button
                v-for="t in visible(filters.Tags, 'tags')"
                :key="t"
                type="button"
                class="fp-chip"
                :class="{ on: tags.includes(t) }"
                @click="toggleStr(tags, t)"
              >
                <Check v-if="tags.includes(t)" :size="12" />{{ t }}
              </button>
              <button
                v-if="filters.Tags.length > CHIP_LIMIT"
                type="button"
                class="fp-more"
                @click="expanded.tags = !expanded.tags"
              >
                {{ expanded.tags ? '收起' : `更多（${filters.Tags.length}）` }}
              </button>
            </div>
          </div>

          <p
            v-if="!filters.Genres.length && !filters.Years.length && !filters.OfficialRatings.length && !filters.Tags.length"
            class="fp-loading"
          >
            这个库里还没有可供筛选的分类信息（扫一次媒体库让分类入库后就会出现）。
          </p>
        </template>
      </div>

      <!-- 加载 -->
      <div v-if="loading" class="grid">
        <div v-for="i in 12" :key="i" class="skeleton"></div>
      </div>

      <!-- 空态 -->
      <div v-else-if="items.length === 0" class="empty">
        <FolderOpen :size="32" />
        <p>{{ activeCount ? '没有符合当前筛选的影片' : '没有找到匹配的影片' }}</p>
        <button v-if="activeCount" type="button" class="af-clear" @click="clearFilters">
          <RotateCcw :size="12" /> 清除筛选条件
        </button>
      </div>

      <!-- 网格 -->
      <div v-else-if="viewMode === 'grid'" class="grid">
        <div v-for="item in items" :key="item.Id" class="grid-cell" :data-sortkey="item.Name">
          <MediaCard :item="item" />
        </div>
      </div>

      <!-- 列表（Emby 风：小海报 + 标题 + 元数据 + 进度） -->
      <div v-else class="list">
        <button
          v-for="item in items"
          :key="item.Id"
          type="button"
          class="list-row"
          :data-sortkey="item.Name"
          @click="openItem(item)"
        >
          <div class="lr-poster">
            <img v-if="posterUrl(item, 160)" :src="posterUrl(item, 160)" :alt="item.Name" loading="lazy" />
            <span v-else class="lr-char">{{ (item.Name || '?').trim().charAt(0) || '?' }}</span>
          </div>
          <div class="lr-body">
            <p class="lr-title">{{ item.Name }}</p>
            <p class="lr-meta">
              <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
              <span>{{ item.Type === 'Movie' ? '电影' : item.Type === 'Series' ? '剧集' : '影片' }}</span>
              <span v-if="item.CommunityRating" class="lr-rating">
                ★ {{ item.CommunityRating.toFixed(1) }}
              </span>
              <span v-if="item.Type === 'Series' && (item.UserData?.UnplayedItemCount || 0) > 0" class="lr-unplayed">
                {{ item.UserData.UnplayedItemCount }}集未看
              </span>
            </p>
            <div v-if="progressPercent(item) > 0 && progressPercent(item) < 96" class="lr-progress">
              <div class="lr-progress-fill" :style="{ width: progressPercent(item) + '%' }"></div>
            </div>
          </div>
          <ChevronRight :size="16" class="lr-go" />
        </button>
      </div>

      <!-- A-Z 快跳 -->
      <nav v-if="items.length" class="az-rail" aria-label="按字母跳转">
        <button
          v-for="L in LETTERS"
          :key="L"
          type="button"
          class="az-key"
          @click="jumpToLetter(L)"
        >
          {{ L }}
        </button>
      </nav>

      <!-- 加载更多 -->
      <div v-if="loadingMore" class="more-loading">
        <ArrowUpDown :size="14" class="spinning" />
        加载中…
      </div>
    </div>
  </div>
</template>

<style scoped>
.library-view {
  min-height: 100vh;
  background: var(--au-bg);
  color: var(--au-text);
  padding-bottom: 3rem;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2rem 0 1.25rem;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.back-btn {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  color: var(--au-text-2);
  text-decoration: none;
  transition: all 0.15s ease;
}

.back-btn:hover {
  color: var(--au-text);
}

.page-title {
  margin: 0;
  font-size: 1.375rem;
  font-weight: 700;
  color: var(--au-text);
}

.page-sub {
  margin: 0.1875rem 0 0;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

/* 工具栏 */
.toolbar {
  display: flex;
  gap: 0.625rem;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}

.search-box {
  flex: 1 1 220px;
  display: flex;
  align-items: center;
  height: 38px;
  padding: 0 0.75rem;
  background: var(--au-overlay-soft);
  border: 1px solid var(--au-border);
  border-radius: 10px;
}

.search-box:focus-within {
  border-color: var(--au-border-focus);
}

.search-icon {
  color: var(--au-text-4);
  margin-right: 0.5rem;
}

.search-box input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--au-text);
  font-size: 0.875rem;
}

.search-box input::placeholder {
  color: var(--au-text-4);
}

.toolbar-select {
  height: 38px;
  padding: 0 0.625rem;
  background: var(--au-overlay-soft);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  color: var(--au-text);
  font-size: 0.8125rem;
  outline: none;
  cursor: pointer;
}

.toolbar-select option {
  background: var(--au-bg-soft);
}

/* 筛选按钮 */
.filter-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  height: 38px;
  padding: 0 0.75rem;
  background: var(--au-overlay-soft);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  color: var(--au-text-2);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-toggle:hover {
  color: var(--au-text);
  border-color: var(--au-border-strong);
}

.filter-toggle.on {
  color: var(--au-primary);
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
}

.filter-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: var(--au-primary);
  color: #04121a;
  font-size: 0.6875rem;
  font-weight: 700;
}

/* 已选条件 */
.active-filters {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-wrap: wrap;
  margin: -0.75rem 0 1.25rem;
}

.af-label {
  font-size: 0.75rem;
  color: var(--au-text-3);
  margin-right: 0.125rem;
}

.af-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  height: 26px;
  padding: 0 0.5rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: 13px;
  color: var(--au-primary);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.af-chip:hover {
  background: var(--au-primary-mid);
}

.af-clear {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  height: 26px;
  padding: 0 0.625rem;
  margin-left: 0.125rem;
  background: transparent;
  border: 1px solid var(--au-border);
  border-radius: 13px;
  color: var(--au-text-3);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.af-clear:hover {
  color: var(--au-text);
  border-color: var(--au-border-strong);
}

/* 筛选面板 */
.filter-panel {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
  padding: 1rem 1.125rem;
  margin-bottom: 1.5rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 14px;
}

.fp-loading {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.fp-group {
  display: flex;
  flex-direction: column;
  gap: 0.4375rem;
}

.fp-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--au-text-3);
  letter-spacing: 0.02em;
}

.fp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.fp-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  height: 28px;
  padding: 0 0.625rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 14px;
  color: var(--au-text-2);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.fp-chip:hover {
  color: var(--au-text);
  border-color: var(--au-border-strong);
}

.fp-chip.on {
  color: var(--au-primary);
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
}

.fp-more {
  height: 28px;
  padding: 0 0.625rem;
  background: transparent;
  border: 1px dashed var(--au-border-strong);
  border-radius: 14px;
  color: var(--au-text-4);
  font-size: 0.75rem;
  cursor: pointer;
}

.fp-more:hover {
  color: var(--au-text-2);
}

/* 视图切换 */
.view-toggle {
  display: inline-flex;
  padding: 3px;
  gap: 2px;
  background: var(--au-overlay-soft);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  height: 38px;
  align-items: center;
}

.vt-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 30px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--au-text-3);
  cursor: pointer;
  transition: all 0.15s ease;
}

.vt-btn:hover {
  color: var(--au-text);
}

.vt-btn.on {
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

/* 网格 */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 0.875rem;
}

.grid-cell {
  min-width: 0;
}

/* 列表视图 */
.list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.list-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.5rem 0.75rem 0.5rem 0.5rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 12px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.list-row:hover {
  border-color: var(--au-primary-border);
  transform: translateX(2px);
}

.lr-poster {
  width: 46px;
  height: 69px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  overflow: hidden;
  background: linear-gradient(160deg, var(--au-primary-soft), var(--au-overlay-soft));
}

.lr-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.lr-char {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--au-primary);
  opacity: 0.75;
}

.lr-body {
  flex: 1;
  min-width: 0;
}

.lr-title {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lr-meta {
  margin: 0.25rem 0 0;
  display: flex;
  align-items: center;
  gap: 0.625rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.lr-rating {
  color: var(--au-warning);
}

.lr-unplayed {
  color: var(--au-primary);
  font-weight: 600;
}

.lr-progress {
  margin-top: 0.375rem;
  height: 3px;
  border-radius: 2px;
  overflow: hidden;
  background: var(--au-surface-2);
}

.lr-progress-fill {
  height: 100%;
  background: var(--au-gradient);
}

.lr-go {
  flex-shrink: 0;
  color: var(--au-text-4);
}

/* A-Z 快跳 */
.az-rail {
  position: fixed;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 1px;
  z-index: 30;
}

.az-key {
  width: 22px;
  height: 19px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--au-text-3);
  font-size: 0.625rem;
  font-weight: 600;
  cursor: pointer;
  border-radius: 4px;
  transition: color 0.12s ease;
}

.az-key:hover {
  color: var(--au-primary);
}

@media (max-width: 640px) {
  .az-rail {
    right: 2px;
  }
  .az-key {
    width: 15px;
    height: 17px;
    font-size: 0.5625rem;
  }
}

@media (min-width: 768px) {
  .grid {
    grid-template-columns: repeat(auto-fill, minmax(152px, 1fr));
  }
}

.skeleton {
  aspect-ratio: 2 / 3.4;
  border-radius: 12px;
  background: linear-gradient(100deg, var(--au-surface) 40%, var(--au-surface-2) 50%, var(--au-surface) 60%);
  background-size: 200% 100%;
  animation: au-shimmer 1.4s infinite;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 4rem 1rem;
  color: var(--au-text-4);
}

.empty svg {
  color: var(--au-primary);
  opacity: 0.45;
}

.more-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1.5rem 0;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

/* 用全站共用的 au-spin / au-shimmer，页面里不再各定义一份同效果的 keyframes */
.spinning {
  animation: au-spin 0.9s linear infinite;
}
</style>
