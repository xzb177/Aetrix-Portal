<script setup lang="ts">
/**
 * 媒体海报墙组件
 *
 * 用于展示求片请求的海报墙，支持响应式布局、投票、筛选
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { requestApi } from '@/api'
import { Film, Star, Clock, CheckCircle, Loader2 } from 'lucide-vue-next'

export interface MediaItem {
  id: number
  movie_name: string
  year?: string
  type?: string
  poster_url?: string
  backdrop_url?: string
  subscriber_count: number
  priority: number
  status: string
  tmdb_id?: string
  overview?: string
  vote_average?: number
  created_at: string
}

interface Props {
  items?: MediaItem[]
  statusFilter?: string
  typeFilter?: string
  sortBy?: 'hot' | 'latest'
  loading?: boolean
  hasMore?: boolean
}

interface Emits {
  (e: 'vote', id: number): void
  (e: 'click', item: MediaItem): void
  (e: 'loadMore'): void
  (e: 'filter', filter: { status?: string; type?: string; sort?: string }): void
}

const props = withDefaults(defineProps<Props>(), {
  items: () => [],
  statusFilter: '',
  typeFilter: '',
  sortBy: 'hot',
  loading: false,
  hasMore: true,
})

const emit = defineEmits<Emits>()

// 状态
const containerRef = ref<HTMLElement>()
const isNearBottom = ref(false)

// 类型映射
const typeLabels: Record<string, string> = {
  movie: '电影',
  series: '剧集',
  anime: '动漫',
  documentary: '纪录片',
  other: '其他',
}

// 状态配置
const statusConfig = {
  pending: {
    label: '待处理',
    icon: Clock,
    color: 'text-amber-400',
    bgClass: 'bg-amber-500/10',
    borderClass: 'border-amber-500/20',
  },
  approved: {
    label: '处理中',
    icon: Loader2,
    color: 'text-blue-400',
    bgClass: 'bg-blue-500/10',
    borderClass: 'border-blue-500/20',
  },
  completed: {
    label: '已完成',
    icon: CheckCircle,
    color: 'text-emerald-400',
    bgClass: 'bg-emerald-500/10',
    borderClass: 'border-emerald-500/20',
  },
  rejected: {
    label: '已拒绝',
    icon: null,
    color: 'text-red-400',
    bgClass: 'bg-red-500/10',
    borderClass: 'border-red-500/20',
  },
}

// 计算热度
const getHeatLevel = (item: MediaItem) => {
  const heat = item.subscriber_count + item.priority
  if (heat >= 50) return { level: 'high', label: '🔥 爆款' }
  if (heat >= 20) return { level: 'medium', label: '⭐ 热门' }
  if (heat >= 5) return { level: 'normal', label: `${heat} 人想要` }
  return { level: 'low', label: `${heat} 人想要` }
}

// 处理点击
const handleClick = (item: MediaItem) => {
  emit('click', item)
}

// 处理投票（阻止冒泡）
const handleVote = (event: Event, item: MediaItem) => {
  event.stopPropagation()
  emit('vote', item.id)
}

// 滚动加载更多
const handleScroll = () => {
  if (!containerRef.value || props.loading || !props.hasMore) return

  const { scrollTop, scrollHeight, clientHeight } = containerRef.value
  const threshold = 200 // 距离底部 200px 时触发

  if (scrollHeight - scrollTop - clientHeight < threshold) {
    emit('loadMore')
  }
}

// 挂载时监听滚动
onMounted(() => {
  if (containerRef.value) {
    containerRef.value.addEventListener('scroll', handleScroll)
  }
})

onUnmounted(() => {
  if (containerRef.value) {
    containerRef.value.removeEventListener('scroll', handleScroll)
  }
})
</script>

<template>
  <div ref="containerRef" class="media-gallery">
    <!-- 空状态 -->
    <div v-if="!loading && items.length === 0" class="empty-state">
      <div class="empty-icon-wrapper">
        <Film :size="28" class="text-white/20" />
      </div>
      <h3 class="empty-title">暂无求片</h3>
      <p class="empty-desc">成为第一个求片的人吧</p>
    </div>

    <!-- 海报网格 -->
    <div v-else class="poster-grid">
      <div
        v-for="item in items"
        :key="item.id"
        class="poster-card"
        @click="handleClick(item)"
      >
        <!-- 海报图片 -->
        <div class="poster-image">
          <img
            v-if="item.poster_url"
            :src="item.poster_url"
            :alt="item.movie_name"
            loading="lazy"
            class="poster-img"
          />
          <div v-else class="poster-placeholder">
            <Film :size="40" class="text-white/20" />
          </div>

          <!-- 渐变遮罩 -->
          <div class="poster-overlay"></div>

          <!-- 状态标签 -->
          <div
            v-if="statusConfig[item.status]"
            :class="['status-badge', statusConfig[item.status].bgClass]"
          >
            <component
              :is="statusConfig[item.status].icon"
              v-if="statusConfig[item.status].icon"
              :size="10"
              :class="statusConfig[item.status].color"
            />
            <span :class="statusConfig[item.status].color">
              {{ statusConfig[item.status].label }}
            </span>
          </div>

          <!-- 热度标签 -->
          <div
            :class="[
              'heat-badge',
              getHeatLevel(item).level === 'high' ? 'heat-high' : ''
            ]"
          >
            <Star :size="10" class="text-amber-400" />
            <span>{{ getHeatLevel(item).label }}</span>
          </div>
        </div>

        <!-- 卡片信息 -->
        <div class="poster-info">
          <h3 class="poster-title">{{ item.movie_name }}</h3>
          <div class="poster-meta">
            <span v-if="item.year" class="meta-year">{{ item.year }}</span>
            <span v-if="typeLabels[item.type]" class="meta-type">
              {{ typeLabels[item.type] }}
            </span>
          </div>
        </div>

        <!-- 投票按钮（悬停显示） -->
        <button
          class="vote-btn"
          @click="handleVote($event, item)"
          title="我也想要"
        >
          <Star :size="14" />
          <span>想要</span>
        </button>
      </div>
    </div>

    <!-- 加载更多 -->
    <div v-if="loading" class="loading-more">
      <Loader2 :size="20" class="spin text-white/40" />
      <span class="text-white/40 text-sm">加载中...</span>
    </div>

    <!-- 没有更多 -->
    <div v-else-if="!hasMore && items.length > 0" class="no-more">
      <span class="text-white/30 text-xs">没有更多了</span>
    </div>
  </div>
</template>

<style scoped>
.media-gallery {
  width: 100%;
  overflow-y: auto;
  max-height: calc(100vh - 280px);
  padding-bottom: 1rem;
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
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
}

/* ==================== 海报网格 ==================== */
.poster-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

@media (min-width: 480px) {
  .poster-grid {
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
  }
}

@media (min-width: 768px) {
  .poster-grid {
    grid-template-columns: repeat(5, 1fr);
  }
}

@media (min-width: 1024px) {
  .poster-grid {
    grid-template-columns: repeat(6, 1fr);
  }
}

/* ==================== 海报卡片 ==================== */
.poster-card {
  position: relative;
  aspect-ratio: 2 / 3;
  border-radius: 0.75rem;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.poster-card:hover {
  transform: scale(1.03);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  border-color: rgba(16, 185, 129, 0.3);
  z-index: 10;
}

.poster-card:hover .vote-btn {
  opacity: 1;
  transform: translateY(0);
}

.poster-card:hover .poster-overlay {
  background: linear-gradient(
    to top,
    rgba(0, 0, 0, 0.9) 0%,
    rgba(0, 0, 0, 0.4) 40%,
    transparent 100%
  );
}

/* ==================== 海报图片 ==================== */
.poster-image {
  position: relative;
  width: 100%;
  height: 100%;
}

.poster-img {
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
  background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
}

.poster-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    to top,
    rgba(0, 0, 0, 0.8) 0%,
    rgba(0, 0, 0, 0.3) 50%,
    transparent 100%
  );
  transition: background 0.2s ease;
  pointer-events: none;
}

/* ==================== 状态标签 ==================== */
.status-badge {
  position: absolute;
  top: 0.5rem;
  left: 0.5rem;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.625rem;
  font-weight: 500;
  backdrop-filter: blur(8px);
}

/* ==================== 热度标签 ==================== */
.heat-badge {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.625rem;
  font-weight: 500;
  background: rgba(0, 0, 0, 0.6);
  color: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(8px);
}

.heat-badge.heat-high {
  background: linear-gradient(135deg, rgba(251, 146, 60, 0.9) 0%, rgba(234, 88, 12, 0.9) 100%);
  color: white;
  box-shadow: 0 2px 8px rgba(234, 88, 12, 0.4);
}

/* ==================== 卡片信息 ==================== */
.poster-info {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 0.75rem 0.5rem 0.5rem;
  pointer-events: none;
}

.poster-title {
  font-size: 0.813rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin: 0 0 0.25rem 0;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.poster-meta {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.688rem;
  color: rgba(255, 255, 255, 0.6);
}

.meta-year {
  padding: 0.125rem 0.375rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}

.meta-type {
  padding: 0.125rem 0.375rem;
  background: rgba(16, 185, 129, 0.2);
  color: rgba(52, 211, 153, 0.9);
  border-radius: 3px;
}

/* ==================== 投票按钮 ==================== */
.vote-btn {
  position: absolute;
  bottom: 0.5rem;
  right: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  background: rgba(16, 185, 129, 0.9);
  border: none;
  border-radius: 0.5rem;
  color: white;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  opacity: 0;
  transform: translateY(4px);
  transition: all 0.2s ease;
}

.vote-btn:hover {
  background: rgba(16, 185, 129, 1);
  transform: translateY(0) scale(1.05);
}

.vote-btn:active {
  transform: scale(0.95);
}

/* ==================== 加载状态 ==================== */
.loading-more,
.no-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1.5rem;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
