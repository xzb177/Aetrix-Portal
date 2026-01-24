<script setup lang="ts">
/**
 * 求片分类中心 - Neo-Noir 2.0 设计
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
import { SegmentedControl } from '@/components/ui'
import { Badge, Chip } from '@/components/ui'
import { IconButton } from '@/components/ui'
import { Film, Search, ChevronDown, ChevronUp, Loader2 } from 'lucide-vue-next'

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
const viewMode = ref<'gallery' | 'my'>('gallery')
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

// 状态配置 - 使用 variant 替代 class
const statusConfig: Record<string, { label: string; variant: 'success' | 'warning' | 'danger' | 'info' | 'default' }> = {
  pending: { label: '待处理', variant: 'warning' },
  approved: { label: '处理中', variant: 'info' },
  rejected: { label: '已拒绝', variant: 'danger' },
  completed: { label: '已完成', variant: 'success' }
}

// ==================== SegmentedControl 选项 ====================
const viewOptions = computed(() => [
  { label: '公共求片池', value: 'gallery' as const },
  { label: '我的求片', value: 'my' as const }
])

// ==================== 计算属性 ====================
const activeFilterCount = computed(() => {
  let count = 0
  if (filters.value.status) count++
  if (filters.value.type) count++
  return count
})

// ==================== 数据加载 ====================
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

async function loadMyRequests() {
  try {
    const data = await requestApi.getMyRequests()
    myRequests.value = data || []
  } catch (error) {
    console.error('加载我的求片失败:', error)
  }
}

async function loadStats() {
  try {
    const data = await requestApi.getStats()
    stats.value = data
  } catch (error) {
    console.error('加载统计失败:', error)
  }
}

async function refresh() {
  isLoading.value = true
  await Promise.all([
    loadGallery(true),
    loadStats()
  ])
}

// ==================== 交互操作 ====================
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

    await refresh()
  } catch (error: any) {
    console.error('提交求片失败:', error)
    const message = error?.response?.data?.detail || error?.message || '提交失败，请稍后重试'
    alert(message)
  } finally {
    isSubmitting.value = false
  }
}

async function handleVote(id: number) {
  try {
    await requestApi.subscribe(id)
    const item = galleryItems.value.find(i => i.id === id)
    if (item) {
      await loadGallery(true)
    }
  } catch (error) {
    console.error('投票失败:', error)
  }
}

function handleItemClick(item: MediaItem) {
  console.log('点击:', item)
}

function handleLoadMore() {
  loadGallery()
}

function switchView(mode: 'gallery' | 'my') {
  viewMode.value = mode
  if (mode === 'my' && myRequests.value.length === 0) {
    loadMyRequests()
  }
}

function toggleMyRequests() {
  showMyRequests.value = !showMyRequests.value
  if (showMyRequests.value && myRequests.value.length === 0) {
    loadMyRequests()
  }
}

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
      <!-- ==================== 顶部标题块 ==================== -->
      <header class="page-header">
        <div class="header-left">
          <div class="header-icon">
            <Film :size="20" />
          </div>
          <div class="header-text">
            <h1 class="page-title">影单广场</h1>
            <p class="page-subtitle">发现社群热门影视</p>
          </div>
        </div>
        <IconButton
          :icon="Search"
          :loading="isSubmitting"
          @click="showSearch = true"
        >
          <span v-if="!isSubmitting" class="icon-btn-label">搜索</span>
        </IconButton>
      </header>

      <!-- ==================== 视图切换 SegmentedControl ==================== -->
      <div class="view-switcher">
        <SegmentedControl
          v-model="viewMode"
          :options="viewOptions"
          size="md"
          @update:model-value="switchView"
        />
      </div>

      <!-- ==================== 公共求片池 ==================== -->
      <div v-show="viewMode === 'gallery'" class="gallery-view">
        <!-- 分类筛选 -->
        <CategoryFilter v-model="filters" :stats="stats" />

        <!-- 加载状态 -->
        <div v-if="isLoading && galleryItems.length === 0" class="loading-state">
          <Loader2 :size="28" class="spin" />
          <p class="loading-text">加载中</p>
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
          <div class="empty-icon">
            <Film :size="28" />
          </div>
          <h3 class="empty-title">暂无求片记录</h3>
          <p class="empty-desc">点击右上角搜索，提交您的第一个求片请求</p>
        </div>

        <!-- 求片列表 -->
        <div v-else class="my-requests-list">
          <div
            v-for="request in myRequests"
            :key="request.id"
            class="media-task-card"
          >
            <!-- 海报缩略图 -->
            <div class="task-poster">
              <img
                v-if="request.poster_url"
                :src="request.poster_url"
                :alt="request.movie_name"
              />
              <div v-else class="poster-placeholder">
                <Film :size="18" />
              </div>
            </div>

            <!-- 三行信息 -->
            <div class="task-info">
              <div class="task-row-primary">
                <h3 class="task-title">{{ request.movie_name }}</h3>
                <Badge :variant="statusConfig[request.status].variant" size="sm">
                  {{ statusConfig[request.status].label }}
                </Badge>
              </div>

              <div class="task-row-secondary">
                <span v-if="request.year" class="meta-text">{{ request.year }}</span>
                <span v-if="typeLabels[request.type]" class="meta-text">
                  {{ typeLabels[request.type] }}
                </span>
                <span class="meta-subscribers">{{ request.subscriber_count }} 人想要</span>
              </div>

              <div class="task-row-tertiary">
                <p v-if="request.note" class="task-note">{{ request.note }}</p>
                <p v-if="request.admin_note" class="task-reply">
                  <span class="reply-label">管理员</span>{{ request.admin_note }}
                </p>
                <span v-else class="task-date">{{ formatDate(request.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== 我的求片折叠面板（公共池模式下） ==================== -->
      <div v-if="viewMode === 'gallery'" class="requests-drawer">
        <button class="drawer-toggle" @click="toggleMyRequests">
          <span>我的求片 ({{ myRequests.length }})</span>
          <ChevronDown v-if="!showMyRequests" :size="16" />
          <ChevronUp v-else :size="16" />
        </button>

        <div v-if="showMyRequests" class="drawer-content">
          <div v-if="myRequests.length === 0" class="drawer-empty">
            <p class="drawer-empty-text">暂无求片记录</p>
          </div>
          <div v-else class="drawer-list">
            <div
              v-for="request in myRequests"
              :key="request.id"
              class="drawer-item"
            >
              <span class="drawer-item-title">{{ request.movie_name }}</span>
              <Chip :size="'sm'" :selected="request.status === 'completed'">
                {{ statusConfig[request.status].label }}
              </Chip>
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
  padding: var(--space-6, 24px) var(--space-5, 20px) var(--neo-safe-bottom);
  background: var(--neo-bg-base);
}

.request-bg {
  position: fixed;
  inset: 0;
  z-index: var(--neo-z-base);
  pointer-events: none;
  background:
    radial-gradient(ellipse at 15% 0%, rgba(16, 185, 129, 0.06) 0%, transparent 45%),
    radial-gradient(ellipse at 85% 100%, rgba(16, 185, 129, 0.04) 0%, transparent 45%),
    var(--neo-bg-base);
}

.request-container {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 16px);
  position: relative;
  z-index: var(--neo-z-base);
}

/* ==================== 顶部标题块 ==================== */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3, 12px);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
}

.header-icon {
  width: var(--neo-icon-btn-md, 40px);
  height: var(--neo-icon-btn-md, 40px);
  border-radius: var(--neo-radius-sm, 12px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-default);
  display: grid;
  place-items: center;
  color: var(--neo-text-primary);
  flex-shrink: 0;
}

.header-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-title {
  font-size: var(--neo-font-size-xl, 18px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
  margin: 0;
  line-height: var(--neo-line-height-tight, 1.25);
}

.page-subtitle {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0;
  font-weight: var(--neo-font-weight-normal, 400);
}

.icon-btn-label {
  font-size: var(--neo-font-size-sm, 12px);
  margin-left: 4px;
}

/* ==================== 视图切换 ==================== */
.view-switcher {
  width: 100%;
}

/* ==================== 加载状态 ==================== */
.loading-state {
  text-align: center;
  padding: var(--space-12, 48px) var(--space-4, 16px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3, 12px);
}

.loading-text {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0;
}

.spin {
  animation: spin 0.8s linear infinite;
  color: var(--neo-text-tertiary);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 空状态 ==================== */
.empty-state {
  text-align: center;
  padding: var(--space-12, 48px) var(--space-4, 16px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3, 12px);
}

.empty-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--neo-radius-md, 14px);
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-text-tertiary);
}

.empty-title {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-secondary);
  margin: 0;
}

.empty-desc {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0;
  max-width: 200px;
}

/* ==================== 影视任务卡 ==================== */
.my-requests-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
}

.media-task-card {
  display: flex;
  gap: var(--space-3, 12px);
  padding: var(--space-3, 12px);
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-md, 14px);
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.media-task-card:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(var(--neo-scale-press, 0.98));
}

/* 海报缩略图 */
.task-poster {
  width: 52px;
  height: 78px;
  flex-shrink: 0;
  border-radius: var(--neo-radius-xs, 8px);
  overflow: hidden;
  background: var(--neo-bg-surface-2);
}

.task-poster img {
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
  color: var(--neo-text-tertiary);
}

/* 三行信息 */
.task-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1, 4px);
}

/* 第一行：标题 + 状态 */
.task-row-primary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2, 8px);
}

.task-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary);
  margin: 0;
  line-height: var(--neo-line-height-tight, 1.25);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 第二行：年份 + 类型 + 想要人数 */
.task-row-secondary {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  flex-wrap: wrap;
}

.meta-text {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
  padding: 2px 6px;
  background: var(--neo-bg-surface-2);
  border-radius: var(--neo-radius-xs, 8px);
}

.meta-subscribers {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-primary);
  margin-left: auto;
}

/* 第三行：备注/回复/时间 */
.task-row-tertiary {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task-note {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-secondary);
  margin: 0;
  line-height: var(--neo-line-height-normal, 1.5);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.task-reply {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-warning);
  margin: 0;
  line-height: var(--neo-line-height-normal, 1.5);
}

.reply-label {
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-warning);
}

.task-date {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

/* ==================== 我的求片折叠面板 ==================== */
.requests-drawer {
  margin-top: auto;
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-md, 14px);
  overflow: hidden;
}

.drawer-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3, 12px) var(--space-4, 16px);
  background: transparent;
  border: none;
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: background var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.drawer-toggle:active {
  background: var(--neo-bg-surface-hover);
}

.drawer-content {
  border-top: 1px solid var(--neo-border-subtle);
  padding: var(--space-2, 8px) var(--space-4, 16px) var(--space-4, 16px);
}

.drawer-empty {
  text-align: center;
  padding: var(--space-4, 16px) 0;
}

.drawer-empty-text {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0;
}

.drawer-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1, 4px);
}

.drawer-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2, 8px) var(--space-3, 12px);
  background: var(--neo-bg-surface-1);
  border-radius: var(--neo-radius-xs, 8px);
  gap: var(--space-2, 8px);
}

.drawer-item-title {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ==================== 响应式 ==================== */
@media (max-width: 480px) {
  .request-page {
    padding: var(--space-5, 20px) var(--space-4, 16px) var(--neo-safe-bottom);
  }

  .icon-btn-label {
    display: none;
  }

  .task-poster {
    width: 48px;
    height: 72px;
  }
}

/* ==================== 减少动画 ==================== */
@media (prefers-reduced-motion: reduce) {
  .spin {
    animation: none;
  }

  .media-task-card:active {
    transform: none;
  }

  .drawer-toggle:active {
    transform: none;
  }
}
</style>
