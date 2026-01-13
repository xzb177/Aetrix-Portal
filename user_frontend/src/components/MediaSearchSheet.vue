<script setup lang="ts">
/**
 * TMDB 媒体搜索组件
 *
 * 底部弹窗形式，用于搜索并选择 TMDB 影片
 */
import { ref, computed, watch } from 'vue'
import { requestApi } from '@/api'
import { Search, X, Film, Tv, Loader2, Star } from 'lucide-vue-next'

export interface TmdbResult {
  id: number
  tmdb_id: number
  media_type: string  // movie, series
  title: string
  original_title?: string
  year?: number
  overview?: string
  poster_url?: string
  poster_url_large?: string
  backdrop_url?: string
  vote_average?: number
  vote_count?: number
  genre_ids: number[]
}

interface Props {
  isOpen: boolean
  defaultType?: string
}

interface Emits {
  (e: 'update:isOpen', value: boolean): void
  (e: 'select', result: TmdbResult): void
}

const props = withDefaults(defineProps<Props>(), {
  isOpen: false,
  defaultType: '',
})

const emit = defineEmits<Emits>()

// 状态
const searchQuery = ref('')
const searchInputRef = ref<HTMLInputElement | null>(null)
const selectedType = ref(props.defaultType || 'all')
const isSearching = ref(false)
const searchResults = ref<TmdbResult[]>([])
const hasSearched = ref(false)

// 类型选项
const typeOptions = [
  { value: 'all', label: '全部', icon: Search },
  { value: 'movie', label: '电影', icon: Film },
  { value: 'series', label: '剧集', icon: Tv },
]

// 防抖搜索
let searchTimer: ReturnType<typeof setTimeout> | null = null

const doSearch = async () => {
  const query = searchQuery.value.trim()
  if (query.length < 2) {
    searchResults.value = []
    hasSearched.value = false
    return
  }

  isSearching.value = true
  hasSearched.value = true

  try {
    const mediaType = selectedType.value === 'all' ? undefined : selectedType.value
    const results = await requestApi.searchTmdb(query, mediaType)
    searchResults.value = results || []
  } catch (error) {
    console.error('搜索失败:', error)
    searchResults.value = []
  } finally {
    isSearching.value = false
  }
}

watch(searchQuery, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(doSearch, 500)
})

watch(selectedType, () => {
  if (searchQuery.value.length >= 2) {
    doSearch()
  }
})

// 选择结果
const handleSelect = (result: TmdbResult) => {
  // 收起手机端键盘
  if (searchInputRef.value) {
    searchInputRef.value.blur()
  }
  emit('select', result)
  handleClose()
}

// 关闭弹窗
const handleClose = () => {
  emit('update:isOpen', false)
  // 重置状态
  setTimeout(() => {
    searchQuery.value = ''
    searchResults.value = []
    hasSearched.value = false
  }, 300)
}

// 获取类型标签
const getTypeLabel = (type: string) => {
  const option = typeOptions.find(o => o.value === type)
  return option?.label || type
}

// 格式化评分
const formatRating = (rating?: number) => {
  if (!rating) return 'N/A'
  return (rating * 10).toFixed(0)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="isOpen" class="sheet-overlay" @click.self="handleClose">
        <div class="sheet-container">
          <!-- 头部 -->
          <div class="sheet-header">
            <h2 class="sheet-title">搜索 TMDB 影片</h2>
            <button class="close-btn" @click="handleClose">
              <X :size="20" />
            </button>
          </div>

          <!-- 搜索栏 -->
          <div class="search-bar">
            <div class="search-input-wrapper">
              <Search :size="18" class="search-icon" />
              <input
                ref="searchInputRef"
                v-model="searchQuery"
                type="text"
                class="search-input"
                placeholder="输入影片名称..."
                autofocus
              />
              <Loader2 v-if="isSearching" :size="16" class="search-loading spin" />
            </div>

            <!-- 类型筛选 -->
            <div class="type-filter">
              <button
                v-for="option in typeOptions"
                :key="option.value"
                :class="['type-btn', { active: selectedType === option.value }]"
                @click="selectedType = option.value"
              >
                <component :is="option.icon" :size="14" />
                <span>{{ option.label }}</span>
              </button>
            </div>
          </div>

          <!-- 搜索结果 -->
          <div class="search-results">
            <!-- 初始提示 -->
            <div v-if="!hasSearched && !isSearching" class="search-prompt">
              <div class="prompt-icon">
                <Search :size="32" class="text-white/20" />
              </div>
              <p class="prompt-text">输入影片名称搜索 TMDB</p>
              <p class="prompt-hint">支持搜索电影和剧集</p>
            </div>

            <!-- 无结果 -->
            <div v-else-if="!isSearching && searchResults.length === 0" class="no-results">
              <Film :size="28" class="text-white/20" />
              <p>未找到匹配的影片</p>
            </div>

            <!-- 结果列表 -->
            <div v-else class="results-grid">
              <div
                v-for="result in searchResults"
                :key="result.tmdb_id"
                class="result-card"
                @click="handleSelect(result)"
              >
                <!-- 海报 -->
                <div class="result-poster">
                  <img
                    v-if="result.poster_url"
                    :src="result.poster_url"
                    :alt="result.title"
                    loading="lazy"
                  />
                  <div v-else class="poster-placeholder">
                    <Film :size="24" class="text-white/20" />
                  </div>

                  <!-- 类型标签 -->
                  <div class="result-type">
                    <component
                      :is="result.media_type === 'movie' ? Film : Tv"
                      :size="10"
                    />
                  </div>

                  <!-- 评分 -->
                  <div v-if="result.vote_average" class="result-rating">
                    <Star :size="10" class="text-amber-400" />
                    <span>{{ formatRating(result.vote_average) }}</span>
                  </div>
                </div>

                <!-- 信息 -->
                <div class="result-info">
                  <h3 class="result-title">{{ result.title }}</h3>
                  <p v-if="result.year" class="result-year">{{ result.year }}</p>
                  <p v-if="result.overview" class="result-overview">
                    {{ result.overview.slice(0, 80) }}{{ result.overview.length > 80 ? '...' : '' }}
                  </p>
                </div>
              </div>
            </div>

            <!-- 加载中 -->
            <div v-if="isSearching" class="search-loading-state">
              <Loader2 :size="24" class="spin text-white/40" />
              <span class="text-white/40 text-sm">搜索中...</span>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ==================== 遮罩层 ==================== */
.sheet-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

/* ==================== 弹窗容器 ==================== */
.sheet-container {
  width: 100%;
  max-width: 640px;
  max-height: 90vh;
  background: #141414;
  border-radius: 1.5rem 1.5rem 0 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.4);
}

@media (min-width: 640px) {
  .sheet-container {
    border-radius: 1.5rem;
    max-height: 80vh;
    margin: 2rem;
  }

  .sheet-overlay {
    align-items: center;
  }
}

/* ==================== 头部 ==================== */
.sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.sheet-title {
  font-size: 1.063rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin: 0;
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 0.5rem;
  background: rgba(255, 255, 255, 0.06);
  border: none;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
}

/* ==================== 搜索栏 ==================== */
.search-bar {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  gap: 0.75rem;
  display: flex;
  flex-direction: column;
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 0.875rem;
  color: rgba(255, 255, 255, 0.4);
}

.search-input {
  width: 100%;
  padding: 0.75rem 2.5rem 0.75rem 2.5rem;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 0.75rem;
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.938rem;
  outline: none;
  transition: all 0.2s ease;
}

.search-input:focus {
  border-color: rgba(16, 185, 129, 0.4);
  background: rgba(255, 255, 255, 0.08);
}

.search-input::placeholder {
  color: rgba(255, 255, 255, 0.4);
}

.search-loading {
  position: absolute;
  right: 0.875rem;
  color: rgba(255, 255, 255, 0.4);
}

/* 类型筛选 */
.type-filter {
  display: flex;
  gap: 0.5rem;
}

.type-btn {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.875rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.5rem;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.813rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.type-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.8);
}

.type-btn.active {
  background: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.3);
  color: rgba(52, 211, 153, 0.9);
}

/* ==================== 搜索结果 ==================== */
.search-results {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.25rem;
}

/* 初始提示 */
.search-prompt {
  text-align: center;
  padding: 3rem 1rem;
}

.prompt-icon {
  width: 56px;
  height: 56px;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1rem;
}

.prompt-text {
  font-size: 0.938rem;
  color: rgba(255, 255, 255, 0.7);
  margin: 0 0 0.375rem 0;
}

.prompt-hint {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
}

/* 无结果 */
.no-results {
  text-align: center;
  padding: 3rem 1rem;
  color: rgba(255, 255, 255, 0.5);
}

.no-results svg {
  margin: 0 auto 0.75rem;
}

.no-results p {
  margin: 0;
  font-size: 0.875rem;
}

/* 结果网格 */
.results-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

@media (min-width: 480px) {
  .results-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

/* 结果卡片 */
.result-card {
  cursor: pointer;
  transition: transform 0.15s ease;
}

.result-card:hover {
  transform: scale(1.03);
}

.result-card:hover .result-poster {
  border-color: rgba(16, 185, 129, 0.4);
}

.result-poster {
  position: relative;
  aspect-ratio: 2 / 3;
  border-radius: 0.625rem;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition: border-color 0.15s ease;
}

.result-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.poster-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.result-type {
  position: absolute;
  top: 0.375rem;
  left: 0.375rem;
  padding: 0.25rem 0.5rem;
  background: rgba(0, 0, 0, 0.7);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.625rem;
  display: flex;
  align-items: center;
}

.result-rating {
  position: absolute;
  top: 0.375rem;
  right: 0.375rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background: rgba(0, 0, 0, 0.7);
  border-radius: 4px;
  font-size: 0.688rem;
  color: rgba(255, 255, 255, 0.9);
}

.result-info {
  padding: 0.5rem 0.25rem 0;
}

.result-title {
  font-size: 0.75rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  margin: 0 0 0.25rem 0;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-year {
  font-size: 0.688rem;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 0.25rem 0;
}

.result-overview {
  font-size: 0.688rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ==================== 加载状态 ==================== */
.search-loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1rem;
  gap: 0.75rem;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 过渡动画 ==================== */
.sheet-enter-active,
.sheet-leave-active {
  transition: all 0.3s ease;
}

.sheet-enter-from,
.sheet-leave-to {
  opacity: 0;
}

.sheet-enter-from .sheet-container,
.sheet-leave-to .sheet-container {
  transform: translateY(100%);
}

@media (min-width: 640px) {
  .sheet-enter-from .sheet-container,
  .sheet-leave-to .sheet-container {
    transform: translateY(20px) scale(0.95);
    opacity: 0;
  }
}
</style>
