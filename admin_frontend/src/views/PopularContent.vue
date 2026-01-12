<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { TrendingUp, Film, Clock, Star, Eye, MoreVertical, ChevronDown } from 'lucide-vue-next'
import { getPopularContent } from '@/api/stats'

interface PopularItem {
  id: string
  name: string
  type: string
  year: number
  community_rating: number
  play_count: number
  user_count: number
}

const period = ref<'day' | 'week' | 'month' | 'all'>('week') as any
const category = ref<'all' | 'movie' | 'tv' | 'anime'>('all')
const loading = ref(false)
const popularItems = ref<PopularItem[]>([])
const showMoreMenu = ref(false)

const filteredItems = computed(() => {
  let result = popularItems.value

  if (category.value !== 'all') {
    result = result.filter(item => {
      const itemType = item.type.toLowerCase()
      if (category.value === 'movie') return itemType === 'movie'
      if (category.value === 'tv') return itemType === 'series' || itemType === 'episode'
      if (category.value === 'anime') return itemType === 'anime' || item.name.toLowerCase().includes('anime')
      return true
    })
  }

  return result.sort((a, b) => b.play_count - a.play_count)
})

const loadPopularContent = async () => {
  loading.value = true
  try {
    const response = await getPopularContent({ limit: 50 }) as any
    popularItems.value = response.items || []
  } catch (error) {
    console.error('加载热门内容失败:', error)
  } finally {
    loading.value = false
  }
}

const getTypeText = (type: string) => {
  const itemType = type.toLowerCase()
  if (itemType === 'movie') return '电影'
  if (itemType === 'series' || itemType === 'episode') return '剧集'
  if (itemType === 'anime') return '动漫'
  return type
}

const getTypeColor = (type: string) => {
  const itemType = type.toLowerCase()
  if (itemType === 'movie') return 'var(--primary)'
  if (itemType === 'series' || itemType === 'episode') return 'var(--success)'
  if (itemType === 'anime') return 'var(--warning)'
  return 'var(--primary)'
}

const getTypeBg = (type: string) => {
  const itemType = type.toLowerCase()
  if (itemType === 'movie') return 'var(--primary-bg)'
  if (itemType === 'series' || itemType === 'episode') return 'var(--success-bg)'
  if (itemType === 'anime') return 'var(--warning-bg)'
  return 'var(--primary-bg)'
}

const getTypeIcon = (type: string) => {
  const itemType = type.toLowerCase()
  if (itemType === 'movie') return '🎬'
  if (itemType === 'series' || itemType === 'episode') return '📺'
  return '🎬'
}

const getRankColor = (index: number) => {
  if (index === 0) return 'linear-gradient(135deg, #FFD700, #FFA500)'
  if (index === 1) return 'linear-gradient(135deg, #C0C0C0, #9E9E9E)'
  if (index === 2) return 'linear-gradient(135deg, #CD7F32, #A0522D)'
  return 'var(--bg-surface)'
}

onMounted(() => {
  loadPopularContent()
})
</script>

<template>
  <div class="popular-page page-container">
    <!-- 顶部栏 -->
    <div class="top-bar">
      <div class="top-bar-left">
        <TrendingUp :size="22" class="top-icon" />
        <div class="top-titles">
          <h1 class="page-title">热门排行</h1>
          <p class="page-subtitle">用户最喜爱的内容</p>
        </div>
      </div>
      <div class="top-bar-right">
        <button class="icon-btn" @click="loadPopularContent" :class="{ spinning: loading }">
          <component :is="loading ? null : TrendingUp" :size="20" />
        </button>
        <button class="icon-btn" @click="showMoreMenu = !showMoreMenu">
          <MoreVertical :size="20" />
        </button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-section mobile-card-sm">
      <div class="filter-row">
        <div class="period-pills">
          <button
            v-for="p in [
              { key: 'day', label: '今日' },
              { key: 'week', label: '本周' },
              { key: 'month', label: '本月' },
              { key: 'all', label: '全部' }
            ]"
            :key="p.key"
            :class="['period-pill', { active: period === p.key }]"
            @click="period = p.key"
          >
            {{ p.label }}
          </button>
        </div>
      </div>
      <div class="filter-row">
        <div class="type-tabs">
          <button
            v-for="cat in [
              { key: 'all', label: '全部', icon: '📋' },
              { key: 'movie', label: '电影', icon: '🎬' },
              { key: 'tv', label: '剧集', icon: '📺' },
              { key: 'anime', label: '动漫', icon: '🎌' }
            ]"
            :key="cat.key"
            :class="['type-tab', { active: category === cat.key }]"
            @click="category = cat.key as any"
          >
            <span class="tab-icon">{{ cat.icon }}</span>
            <span>{{ cat.label }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- TOP 3 精选卡片 -->
    <div v-if="filteredItems.length >= 3" class="top-3-grid">
      <div
        v-for="(item, index) in filteredItems.slice(0, 3)"
        :key="item.id"
        class="top-card glass-card-lg"
        :class="`rank-${index + 1}`"
      >
        <div class="top-rank" :style="{ background: getRankColor(index) }">
          {{ index + 1 }}
        </div>
        <div class="top-poster">{{ getTypeIcon(item.type) }}</div>
        <div class="top-content">
          <h3 class="top-title">{{ item.name }}</h3>
          <div class="top-meta">
            <span class="top-type" :style="{ color: getTypeColor(item.type), background: getTypeBg(item.type) }">
              {{ getTypeText(item.type) }}
            </span>
            <span class="top-year">{{ item.year }}</span>
          </div>
          <div class="top-rating">
            <Star :size="12" class="star-icon" />
            <span>{{ item.community_rating?.toFixed(1) || 'N/A' }}</span>
          </div>
          <div class="top-stats">
            <div class="stat">
              <Eye :size="14" />
              <span>{{ item.user_count }} 人</span>
            </div>
            <div class="stat">
              <Film :size="14" />
              <span>{{ item.play_count }} 次</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 完整榜单 -->
    <div class="rank-section">
      <div class="rank-header">
        <h3 class="rank-title">完整榜单</h3>
        <span class="rank-count">共 {{ filteredItems.length }} 部</span>
      </div>
      <div class="rank-list">
        <div
          v-for="(item, index) in filteredItems"
          :key="item.id"
          class="rank-item mobile-card-sm"
        >
          <span class="rank-num" :style="{ background: getRankColor(index) }">
            {{ index + 1 }}
          </span>
          <div class="rank-poster">{{ getTypeIcon(item.type) }}</div>
          <div class="rank-info">
            <h4 class="rank-name">{{ item.name }}</h4>
            <span class="rank-meta" :style="{ color: getTypeColor(item.type) }">
              {{ getTypeText(item.type) }} · {{ item.year }}
            </span>
          </div>
          <div class="rank-stats">
            <div class="rank-rating">
              <Star :size="12" class="star-icon" />
              <span>{{ item.community_rating?.toFixed(1) || 'N/A' }}</span>
            </div>
            <div class="rank-plays">
              <span class="play-num">{{ item.play_count }}</span>
              <span class="play-label">播放</span>
            </div>
          </div>
          <div class="rank-progress">
            <div
              class="progress-fill"
              :style="{
                width: `${(item.play_count / (filteredItems[0]?.play_count || 1)) * 100}%`,
                background: getRankColor(index)
              }"
            ></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && filteredItems.length === 0" class="empty-state">
      <div class="empty-icon">📊</div>
      <p class="empty-text">暂无热门内容数据</p>
    </div>
  </div>
</template>

<style scoped>
.popular-page {
  background: var(--bg-primary);
}

/* ===== 顶部栏 ===== */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
}

.top-bar-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.top-icon {
  color: var(--primary);
}

.top-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
  line-height: var(--line-height-tight);
}

.page-subtitle {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin: 0;
}

.top-bar-right {
  display: flex;
  gap: var(--space-2);
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: var(--glass-gradient);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.icon-btn:active {
  transform: scale(0.95);
  background: var(--bg-card-hover);
}

.icon-btn.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ===== 筛选栏 ===== */
.filter-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.filter-row {
  display: flex;
  align-items: center;
}

.period-pills {
  display: flex;
  gap: var(--space-1);
  width: 100%;
}

.period-pill {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-subtle);
  background: transparent;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
  white-space: nowrap;
}

.period-pill:active {
  transform: scale(0.97);
}

.period-pill.active {
  background: var(--primary-bg);
  border-color: var(--primary);
  color: var(--primary);
}

.type-tabs {
  display: flex;
  gap: var(--space-2);
  width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}

.type-tabs::-webkit-scrollbar {
  display: none;
}

.type-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: transparent;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
  white-space: nowrap;
  min-width: 60px;
}

.type-tab:active {
  transform: scale(0.95);
}

.type-tab.active {
  background: var(--glass-gradient-strong);
  border-color: var(--border-default);
  color: var(--text-primary);
}

.tab-icon {
  font-size: 20px;
}

/* ===== TOP 3 ===== */
.top-3-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-3);
}

@media (min-width: 640px) {
  .top-3-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

.top-card {
  position: relative;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  overflow: hidden;
}

.top-rank {
  position: absolute;
  top: var(--space-3);
  right: var(--space-3);
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-bold);
  color: white;
  box-shadow: var(--shadow-sm);
}

.top-poster {
  font-size: 48px;
  width: 80px;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--glass-gradient);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
}

.top-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
}

.top-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-meta {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
}

.top-type {
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.top-year {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.top-rating {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--warning);
}

.star-icon {
  fill: currentColor;
}

.top-stats {
  display: flex;
  justify-content: center;
  gap: var(--space-4);
}

.stat {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

/* ===== 榜单 ===== */
.rank-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.rank-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rank-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
}

.rank-count {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.rank-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.rank-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  overflow: hidden;
}

.rank-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: rgba(255, 255, 255, 0.05);
}

.progress-fill {
  height: 100%;
  border-radius: 1px;
  transition: width 0.3s ease;
}

.rank-num {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: white;
  flex-shrink: 0;
}

.rank-poster {
  font-size: 24px;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--glass-gradient);
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

.rank-info {
  flex: 1;
  min-width: 0;
}

.rank-name {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rank-meta {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.rank-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
}

.rank-rating {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--warning);
}

.rank-plays {
  text-align: right;
}

.play-num {
  display: block;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.play-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

/* ===== 空状态 ===== */
.empty-state {
  text-align: center;
  padding: var(--space-6) var(--space-4);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--space-3);
  opacity: 0.5;
}

.empty-text {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  margin: 0;
}
</style>
