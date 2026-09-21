<script setup lang="ts">
/**
 * 媒体库浏览页 — 网格 + 搜索 + 类型/排序筛选 + 无限滚动
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { embyApi, type EmbyItem } from '@/api/emby'
import MediaCard from '@/components/media/MediaCard.vue'
import { Search, X, ArrowUpDown, FolderOpen } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()

const libId = computed(() => (route.params.id as string) || '')
const libName = ref(route.query.name as string || '媒体库')

const items = ref<EmbyItem[]>([])
const total = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const search = ref('')
const typeFilter = ref('')
const sort = ref('SortName:Ascending')

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

const typeLabel = (t?: string) =>
  ({ Movie: '电影', Series: '剧集', Episode: '剧集' }[t || ''] || '影片')

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
  searchTimer = setTimeout(() => load(true), 350)
}

// 无限滚动
function onScroll() {
  if (loading.value || loadingMore.value || !hasMore()) return
  const nearBottom =
    window.innerHeight + window.scrollY >= document.body.offsetHeight - 600
  if (nearBottom) load(false)
}

watch([typeFilter, sort], () => load(true))
watch(libId, () => load(true))

onMounted(() => {
  window.addEventListener('scroll', onScroll)
  load(true)
})

onBeforeUnmount(() => window.removeEventListener('scroll', onScroll))
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
            <p class="page-sub">{{ total }} 个条目</p>
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
      </div>

      <!-- 加载 -->
      <div v-if="loading" class="grid">
        <div v-for="i in 12" :key="i" class="skeleton"></div>
      </div>

      <!-- 空态 -->
      <div v-else-if="items.length === 0" class="empty">
        <FolderOpen :size="32" />
        <p>没有找到匹配的影片</p>
      </div>

      <!-- 网格 -->
      <div v-else class="grid">
        <MediaCard v-for="item in items" :key="item.Id" :item="item" />
      </div>

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
  background: #070b12;
  color: #e5e7eb;
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
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.7);
  text-decoration: none;
  transition: all 0.15s ease;
}

.back-btn:hover {
  color: #fff;
}

.page-title {
  margin: 0;
  font-size: 1.375rem;
  font-weight: 700;
  color: #fafafa;
}

.page-sub {
  margin: 0.1875rem 0 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.4);
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
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
}

.search-box:focus-within {
  border-color: rgba(34, 211, 238, 0.5);
}

.search-icon {
  color: rgba(255, 255, 255, 0.35);
  margin-right: 0.5rem;
}

.search-box input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: #fafafa;
  font-size: 0.875rem;
}

.search-box input::placeholder {
  color: rgba(255, 255, 255, 0.25);
}

.toolbar-select {
  height: 38px;
  padding: 0 0.625rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.8125rem;
  outline: none;
  cursor: pointer;
}

.toolbar-select option {
  background: #10161d;
}

/* 网格 */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 0.875rem;
}

@media (min-width: 768px) {
  .grid {
    grid-template-columns: repeat(auto-fill, minmax(152px, 1fr));
  }
}

.skeleton {
  aspect-ratio: 2 / 3.4;
  border-radius: 12px;
  background: linear-gradient(100deg, rgba(255, 255, 255, 0.04) 40%, rgba(255, 255, 255, 0.08) 50%, rgba(255, 255, 255, 0.04) 60%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}

@keyframes shimmer {
  to { background-position: -200% 0; }
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 4rem 1rem;
  color: rgba(255, 255, 255, 0.35);
}

.empty svg {
  color: rgba(34, 211, 238, 0.4);
}

.more-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1.5rem 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.4);
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
