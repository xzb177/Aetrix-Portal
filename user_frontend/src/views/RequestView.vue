<script setup lang="ts">
/**
 * 求片分类中心 - 海报墙
 *
 * 功能：
 * - 公共求片池海报墙展示
 * - TMDB 搜索提交
 * - 分类筛选
 * - 投票/订阅
 * - 我的求片记录
 */
import { ref, computed, onMounted, watch } from 'vue'
import { requestApi } from '@/api'
import MediaGallery, { type MediaItem } from '@/components/MediaGallery.vue'
import MediaSearchSheet, { type TmdbResult } from '@/components/MediaSearchSheet.vue'
import CategoryFilter from '@/components/CategoryFilter.vue'
import { Film, Plus, Search, ChevronDown, ChevronUp, Loader2 } from 'lucide-vue-next'

interface MyRequest {
  id: number
  movie_name: string
  year?: string
  type?: string
  note?: string
  status: string
  admin_note?: string
  tmdb_id?: string
  poster_url?: string
  subscriber_count: number
  created_at: string
}

// ==================== 状态 ====================
const viewMode = ref<'gallery' | 'my'>('gallery') // gallery=公共求片, my=我的求片
const isLoading = ref(true)
const isSubmitting = ref(false)
const galleryItems = ref<MediaItem[]>([])
const myRequests = ref<MyRequest[]>([])
const hasMore = ref(true)
const currentPage = ref(1)

// 筛选条件
const filters = ref({
  status: '',
  type: '',
  sort: 'hot'
})

// 统计数据
const stats = ref({
  total: 0,
  pending: 0,
  approved: 0,
  completed: 0,
  by_type: {} as Record<string, number>
})

// 搜索弹窗
const showSearch = ref(false)

// 我的求片展开状态
const showMyRequests = ref(false)

// ==================== 类型映射 ====================
const typeLabels: Record<string, string> = {
  movie: '电影',
  series: '剧集',
  anime: '动漫',
  documentary: '纪录片',
  other: '其他',
}

// 状态配置
const statusConfig = {
  pending: { label: '待处理', class: 'status-pending' },
  approved: { label: '处理中', class: 'status-approved' },
  rejected: { label: '已拒绝', class: 'status-rejected' },
  completed: { label: '已完成', class: 'status-completed' }
}

// ==================== 计算属性 ====================
const activeFilterCount = computed(() => {
  let count = 0
  if (filters.value.status) count++
  if (filters.value.type) count++
  return count
})

// ==================== 数据加载 ====================
// 加载公共求片池
async function loadGallery(reset = false) {
  if (reset) {
    currentPage.value = 1
    galleryItems.value = []
    hasMore.value = true
  }

  if (!hasMore.value) return

  try {
    const data = await requestApi.getGallery({
      status_filter: filters.value.status || undefined,
      type_filter: filters.value.type || undefined,
      sort_by: filters.value.sort as 'hot' | 'latest',
      page: currentPage.value,
      limit: 30
    })

    if (reset) {
      galleryItems.value = data || []
    } else {
      galleryItems.value.push(...(data || []))
    }

    hasMore.value = (data || []).length >= 30
    currentPage.value++
  } catch (error) {
    console.error('加载求片失败:', error)
  } finally {
    isLoading.value = false
  }
}

// 加载我的求片
async function loadMyRequests() {
  try {
    const data = await requestApi.getMyRequests()
    myRequests.value = data || []
  } catch (error) {
    console.error('加载我的求片失败:', error)
  }
}

// 加载统计数据
async function loadStats() {
  try {
    const data = await requestApi.getStats()
    stats.value = data
  } catch (error) {
    console.error('加载统计失败:', error)
  }
}

// 刷新数据
async function refresh() {
  isLoading.value = true
  await Promise.all([
    loadGallery(true),
    loadStats()
  ])
}

// ==================== 交互操作 ====================
// TMDB 搜索选择
async function handleTmdbSelect(result: TmdbResult) {
  isSubmitting.value = true
  try {
    const typeMap: Record<string, string> = {
      movie: 'movie',
      series: 'series'
    }

    await requestApi.submit({
      movie_name: result.title,
      year: result.year?.toString(),
      type: typeMap[result.media_type] || 'movie',
      tmdb_id: result.tmdb_id.toString(),
      poster_url: result.poster_url_large || result.poster_url
    })

    // 刷新数据
    await refresh()
  } catch (error: any) {
    console.error('提交求片失败:', error)
    const message = error?.response?.data?.detail || error?.message || '提交失败，请稍后重试'
    alert(message)
  } finally {
    isSubmitting.value = false
  }
}

// 投票/订阅
async function handleVote(id: number) {
  try {
    await requestApi.subscribe(id)

    // 更新本地数据
    const item = galleryItems.value.find(i => i.id === id)
    if (item) {
      // 重新加载以获取正确数据
      await loadGallery(true)
    }
  } catch (error) {
    console.error('投票失败:', error)
  }
}

// 点击海报
function handleItemClick(item: MediaItem) {
  // 可以打开详情弹窗
  console.log('点击:', item)
}

// 加载更多
function handleLoadMore() {
  loadGallery()
}

// 切换视图模式
function switchView(mode: 'gallery' | 'my') {
  viewMode.value = mode
  if (mode === 'my' && myRequests.value.length === 0) {
    loadMyRequests()
  }
}

// 切换我的求片展开
function toggleMyRequests() {
  showMyRequests.value = !showMyRequests.value
  if (showMyRequests.value && myRequests.value.length === 0) {
    loadMyRequests()
  }
}

// 格式化日期
function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// ==================== 监听筛选变化 ====================
watch(filters, () => {
  loadGallery(true)
}, { deep: true })

// ==================== 生命周期 ====================
onMounted(async () => {
  await Promise.all([
    loadGallery(true),
    loadStats()
  ])
})
</script>

<template>
  <div class="request-page">
    <!-- 背景层 -->
    <div class="request-bg"></div>

    <div class="request-container">
      <!-- ==================== 顶部导航 ==================== -->
      <header class="page-header">
        <div class="header-left">
          <div class="app-icon-tile">
            <Film :size="20" class="text-white/80" />
          </div>
          <div class="header-text">
            <h1 class="page-title">求片分类中心</h1>
            <p class="page-subtitle">发现大家都在看什么</p>
          </div>
        </div>
        <button
          class="search-btn"
          :class="{ loading: isSubmitting }"
          :disabled="isSubmitting"
          @click="showSearch = true"
        >
          <Loader2 v-if="isSubmitting" class="spin" :size="18" />
          <Search v-else :size="18" />
          <span v-if="!isSubmitting">搜索求片</span>
        </button>
      </header>

      <!-- ==================== 视图切换 ==================== -->
      <div class="view-tabs">
        <button
          :class="['view-tab', { active: viewMode === 'gallery' }]"
          @click="switchView('gallery')"
        >
          <span>公共求片池</span>
          <span class="tab-count">{{ stats.total }}</span>
        </button>
        <button
          :class="['view-tab', { active: viewMode === 'my' }]"
          @click="switchView('my')"
        >
          <span>我的求片</span>
          <span class="tab-count">{{ myRequests.length }}</span>
        </button>
      </div>

      <!-- ==================== 公共求片池 ==================== -->
      <div v-show="viewMode === 'gallery'" class="gallery-view">
        <!-- 分类筛选 -->
        <CategoryFilter v-model="filters" :stats="stats" />

        <!-- 加载状态 -->
        <div v-if="isLoading && galleryItems.length === 0" class="loading-state">
          <div class="loading-spinner">
            <Loader2 :size="32" class="spin text-white/40" />
          </div>
          <p class="text-white/40 text-sm">加载中...</p>
        </div>

        <!-- 海报墙 -->
        <MediaGallery
          v-else
          :items="galleryItems"
          :loading="isLoading"
          :has-more="hasMore"
          @vote="handleVote"
          @click="handleItemClick"
          @load-more="handleLoadMore"
        />
      </div>

      <!-- ==================== 我的求片 ==================== -->
      <div v-show="viewMode === 'my'" class="my-requests-view">
        <!-- 空状态 -->
        <div v-if="myRequests.length === 0 && !isLoading" class="empty-state">
          <div class="empty-icon-wrapper">
            <Film :size="32" class="text-white/20" />
          </div>
          <h3 class="empty-title">还没有求片记录</h3>
          <p class="empty-desc">点击上方搜索按钮，提交您的第一个求片</p>
        </div>

        <!-- 求片列表 -->
        <div v-else class="my-requests-list">
          <div
            v-for="request in myRequests"
            :key="request.id"
            class="request-card"
          >
            <!-- 海报缩略图 -->
            <div class="request-poster">
              <img
                v-if="request.poster_url"
                :src="request.poster_url"
                :alt="request.movie_name"
              />
              <div v-else class="poster-placeholder">
                <Film :size="20" class="text-white/20" />
              </div>
            </div>

            <!-- 信息 -->
            <div class="request-info">
              <div class="request-header">
                <h3 class="request-title">{{ request.movie_name }}</h3>
                <span :class="['status-badge', statusConfig[request.status].class]">
                  {{ statusConfig[request.status].label }}
                </span>
              </div>
              <div class="request-meta">
                <span v-if="request.year" class="meta-tag">{{ request.year }}</span>
                <span v-if="typeLabels[request.type]" class="meta-tag">
                  {{ typeLabels[request.type] }}
                </span>
                <span class="meta-subscribers">{{ request.subscriber_count }} 人想要</span>
              </div>
              <p v-if="request.note" class="request-note">{{ request.note }}</p>
              <p v-if="request.admin_note" class="request-reply">
                <span class="reply-label">管理员：</span>{{ request.admin_note }}
              </p>
              <p class="request-date">{{ formatDate(request.created_at) }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== 我的求片折叠面板（公共池模式下） ==================== -->
      <div v-if="viewMode === 'gallery'" class="my-requests-drawer">
        <button class="drawer-toggle" @click="toggleMyRequests">
          <span>我的求片 ({{ myRequests.length }})</span>
          <ChevronDown v-if="!showMyRequests" :size="18" />
          <ChevronUp v-else :size="18" />
        </button>

        <div v-if="showMyRequests" class="drawer-content">
          <div v-if="myRequests.length === 0" class="drawer-empty">
            <p class="text-white/40 text-sm">暂无求片记录</p>
          </div>
          <div v-else class="drawer-list">
            <div
              v-for="request in myRequests"
              :key="request.id"
              class="drawer-item"
            >
              <span class="drawer-item-title">{{ request.movie_name }}</span>
              <span :class="['drawer-item-status', statusConfig[request.status].class]">
                {{ statusConfig[request.status].label }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== TMDB 搜索弹窗 ==================== -->
    <MediaSearchSheet
      v-model:is-open="showSearch"
      @select="handleTmdbSelect"
    />
  </div>
</template>

<style scoped>
/* ==================== 容器与背景 ==================== */
.request-page {
  min-height: 100vh;
  min-height: 100dvh;
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 1.5rem 1rem 2rem;
}

.request-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(ellipse at 20% 0%, rgba(16, 185, 129, 0.08) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 100%, rgba(16, 185, 129, 0.05) 0%, transparent 50%),
    linear-gradient(180deg, #0a0a0a 0%, #0a0a0a 100%);
}

.request-container {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* ==================== 顶部导航 ==================== */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.app-icon-tile {
  height: 40px;
  width: 40px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(12px);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.header-text {
  display: flex;
  flex-direction: column;
}

.page-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin: 0;
  line-height: 1.3;
}

.page-subtitle {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
}

.search-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(52, 211, 153, 0.25);
  border-radius: 0.75rem;
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.search-btn:hover {
  background: rgba(16, 185, 129, 0.22);
}

.search-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ==================== 视图切换 ==================== */
.view-tabs {
  display: flex;
  gap: 0.5rem;
  padding: 0.25rem;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 0.75rem;
}

.view-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: transparent;
  border: none;
  border-radius: 0.625rem;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.view-tab:hover {
  color: rgba(255, 255, 255, 0.8);
}

.view-tab.active {
  background: rgba(16, 185, 129, 0.15);
  color: rgba(52, 211, 153, 0.9);
}

.tab-count {
  font-size: 0.75rem;
  padding: 0.125rem 0.5rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.6);
}

.view-tab.active .tab-count {
  background: rgba(16, 185, 129, 0.2);
  color: rgba(52, 211, 153, 0.8);
}

/* ==================== 加载状态 ==================== */
.loading-state {
  text-align: center;
  padding: 4rem 1rem;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  margin: 0 auto 1rem;
}

/* ==================== 空状态 ==================== */
.empty-state {
  text-align: center;
  padding: 4rem 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.empty-icon-wrapper {
  width: 64px;
  height: 64px;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}

.empty-title {
  font-size: 1rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.7);
  margin: 0 0 0.375rem 0;
}

.empty-desc {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
}

/* ==================== 我的求片列表 ==================== */
.my-requests-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.request-card {
  display: flex;
  gap: 0.875rem;
  padding: 0.875rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.75rem;
}

.request-poster {
  width: 56px;
  height: 84px;
  flex-shrink: 0;
  border-radius: 0.5rem;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.03);
}

.request-poster img {
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

.request-info {
  flex: 1;
  min-width: 0;
}

.request-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
}

.request-title {
  font-size: 0.938rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  margin: 0;
  line-height: 1.4;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.688rem;
  font-weight: 500;
  flex-shrink: 0;
}

.status-pending {
  background: rgba(251, 191, 36, 0.12);
  color: rgba(251, 191, 36, 0.9);
}

.status-approved {
  background: rgba(59, 130, 246, 0.12);
  color: rgba(96, 165, 250, 0.9);
}

.status-completed {
  background: rgba(16, 185, 129, 0.12);
  color: rgba(52, 211, 153, 0.9);
}

.status-rejected {
  background: rgba(239, 68, 68, 0.12);
  color: rgba(248, 113, 113, 0.9);
}

.request-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 0.688rem;
  color: rgba(255, 255, 255, 0.6);
  padding: 0.125rem 0.375rem;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
}

.meta-subscribers {
  font-size: 0.688rem;
  color: rgba(16, 185, 129, 0.8);
}

.request-note {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0.25rem 0;
  line-height: 1.5;
}

.request-reply {
  font-size: 0.813rem;
  color: rgba(251, 191, 36, 0.85);
  margin: 0.25rem 0;
  line-height: 1.5;
}

.reply-label {
  font-weight: 500;
  color: rgba(251, 191, 36, 0.95);
}

.request-date {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 0.25rem 0 0;
}

/* ==================== 我的求片折叠面板 ==================== */
.my-requests-drawer {
  margin-top: auto;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.75rem;
  overflow: hidden;
}

.drawer-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem 1rem;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease;
}

.drawer-toggle:hover {
  background: rgba(255, 255, 255, 0.04);
}

.drawer-content {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding: 0.75rem 1rem 1rem;
}

.drawer-empty {
  text-align: center;
  padding: 1rem 0;
}

.drawer-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.drawer-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 0.5rem;
}

.drawer-item-title {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.8);
}

.drawer-item-status {
  font-size: 0.688rem;
  padding: 0.125rem 0.375rem;
  border-radius: 3px;
}

/* ==================== 动画 ==================== */
.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 响应式 ==================== */
@media (max-width: 480px) {
  .request-page {
    padding: 1.25rem 0.875rem 2rem;
  }

  .page-title {
    font-size: 1rem;
  }

  .page-subtitle {
    font-size: 0.75rem;
  }

  .search-btn span {
    display: none;
  }
}
</style>
