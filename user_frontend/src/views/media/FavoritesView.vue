<script setup lang="ts">
/**
 * 我的收藏 — 收藏列表（此前收藏只能在详情页切换，没有列表页）
 *
 * 数据源：/emby/Users/me/FavoriteItems（与 Emby 客户端收藏互通）
 * 交互：类型筛选 / 一键取消收藏（乐观更新，失败回滚）/ 海报直达详情
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { embyApi, posterUrl, progressPercent, type EmbyItem } from '@/api/emby'
import { useToast } from '@/composables/useToast'
import { Heart, Play, Star, Layers, RefreshCw, Library } from 'lucide-vue-next'

const toast = useToast()

const loading = ref(true)
const items = ref<EmbyItem[]>([])
const typeFilter = ref('')
const removing = ref<Set<string>>(new Set())

const filters = [
  { value: '', label: '全部' },
  { value: 'Movie', label: '电影' },
  { value: 'Series', label: '剧集' },
]

const shown = computed(() =>
  typeFilter.value ? items.value.filter((i) => i.Type === typeFilter.value) : items.value,
)

const typeLabel = (t?: string) =>
  ({ Movie: '电影', Series: '剧集', Episode: '剧集' }[t || ''] || '影片')

function target(item: EmbyItem) {
  return item.Type === 'Episode' && item.SeriesId ? `/media/${item.SeriesId}` : `/media/${item.Id}`
}

async function load() {
  loading.value = true
  try {
    items.value = await embyApi.getFavorites()
  } catch {
    toast.error('收藏加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

/** 取消收藏：先本地移除，失败再放回原位 */
async function unfavorite(item: EmbyItem) {
  if (removing.value.has(item.Id)) return
  const index = items.value.findIndex((i) => i.Id === item.Id)
  if (index < 0) return

  removing.value.add(item.Id)
  const [removed] = items.value.splice(index, 1)
  try {
    const ud = await embyApi.setFavorite(item.Id, false)
    if (ud?.IsFavorite) throw new Error('服务端未取消')
    toast.success(`已取消收藏《${item.Name}》`)
  } catch {
    items.value.splice(index, 0, removed)
    toast.error('取消收藏失败，请重试')
  } finally {
    removing.value.delete(item.Id)
  }
}

onMounted(load)
</script>

<template>
  <div class="au-page fav-page">
    <!-- 头部 -->
    <header class="page-head au-anim-up">
      <div>
        <h1 class="page-title">
          <Heart :size="20" class="title-icon" />
          我的收藏
        </h1>
        <p class="page-sub">与手机/电视端播放器的收藏实时同步</p>
      </div>
      <RouterLink to="/media" class="au-btn au-btn-ghost au-btn-sm">
        <Library :size="15" />
        媒体库
      </RouterLink>
    </header>

    <!-- 类型筛选 + 计数 -->
    <div v-if="!loading && items.length" class="filter-bar au-anim-up">
      <div class="chips">
        <button
          v-for="f in filters"
          :key="f.value"
          class="chip"
          :class="{ 'chip-active': typeFilter === f.value }"
          @click="typeFilter = f.value"
        >
          {{ f.label }}
          <span class="chip-count">
            {{ f.value ? items.filter((i) => i.Type === f.value).length : items.length }}
          </span>
        </button>
      </div>
    </div>

    <!-- 加载 -->
    <div v-if="loading" class="au-empty">
      <RefreshCw :size="22" class="spinning" />
      <p>正在读取收藏…</p>
    </div>

    <!-- 空态 -->
    <div v-else-if="!items.length" class="au-empty au-anim-up">
      <Heart :size="34" />
      <h2>还没有收藏</h2>
      <p>在影片详情页点「收藏」，喜欢的内容会集中在这里，手机和电视端也能看到。</p>
      <RouterLink to="/media" class="au-btn au-btn-primary" style="margin-top: 0.75rem">
        <Library :size="16" />
        去媒体库逛逛
      </RouterLink>
    </div>

    <!-- 收藏网格 -->
    <template v-else>
      <div v-if="!shown.length" class="au-empty">
        <Layers :size="30" />
        <p>该分类下暂无收藏</p>
      </div>

      <div v-else class="fav-grid">
        <div
          v-for="item in shown"
          :key="item.Id"
          class="fav-card au-anim-up"
          :class="{ leaving: removing.has(item.Id) }"
        >
          <RouterLink :to="target(item)" class="poster-wrap">
            <img v-if="posterUrl(item, 342)" :src="posterUrl(item, 342)" :alt="item.Name" loading="lazy" />
            <div v-else class="poster-fallback">
              <Layers :size="26" />
            </div>

            <div class="hover-play">
              <Play :size="20" />
            </div>

            <div
              v-if="progressPercent(item) > 0 && progressPercent(item) < 96"
              class="progress-track"
            >
              <div class="progress-fill" :style="{ width: progressPercent(item) + '%' }"></div>
            </div>
          </RouterLink>

          <button
            class="unfav-btn"
            title="取消收藏"
            :disabled="removing.has(item.Id)"
            @click.stop="unfavorite(item)"
          >
            <Heart :size="14" fill="currentColor" />
          </button>

          <div class="card-body">
            <RouterLink :to="target(item)" class="card-title" :title="item.Name">
              {{ item.Name }}
            </RouterLink>
            <p class="card-meta">
              <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
              <span>{{ typeLabel(item.Type) }}</span>
              <span v-if="item.CommunityRating" class="rating">
                <Star :size="10" class="star" />
                {{ item.CommunityRating.toFixed(1) }}
              </span>
            </p>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.fav-page {
  max-width: 1080px;
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 1.375rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.title-icon {
  color: var(--au-danger);
}

.page-sub {
  margin: 0.3125rem 0 0;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.filter-bar {
  margin-bottom: 1rem;
}

.chips {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  height: 32px;
  padding: 0 0.75rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  color: var(--au-text-2);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.chip:hover {
  border-color: var(--au-border-strong);
  color: var(--au-text);
}

.chip-active {
  background: var(--au-primary-soft);
  border-color: var(--au-primary-border);
  color: var(--au-primary);
}

.chip-count {
  font-size: 0.6875rem;
  color: var(--au-text-4);
  font-variant-numeric: tabular-nums;
}

.chip-active .chip-count {
  color: var(--au-primary);
  opacity: 0.7;
}

.fav-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 1.125rem 0.875rem;
}

.fav-card {
  position: relative;
  min-width: 0;
  transition: opacity var(--au-med) var(--au-ease), transform var(--au-med) var(--au-ease);
}

.fav-card.leaving {
  opacity: 0.35;
  transform: scale(0.97);
}

.poster-wrap {
  position: relative;
  display: block;
  aspect-ratio: 2 / 3;
  border-radius: var(--au-r-md);
  overflow: hidden;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  transition: transform var(--au-fast) var(--au-ease), border-color var(--au-fast),
    box-shadow var(--au-fast);
}

.poster-wrap:hover {
  transform: translateY(-3px);
  border-color: var(--au-primary-border);
  box-shadow: var(--au-shadow-1);
}

.poster-wrap img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.poster-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--au-text-4);
}

.hover-play {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 7, 12, 0.45);
  color: var(--au-primary);
  opacity: 0;
  transition: opacity var(--au-fast);
}

.poster-wrap:hover .hover-play {
  opacity: 1;
}

.hover-play svg {
  width: 44px;
  height: 44px;
  padding: 12px;
  border-radius: 50%;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  backdrop-filter: blur(6px);
}

.progress-track {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  background: rgba(255, 255, 255, 0.18);
}

.progress-fill {
  height: 100%;
  background: var(--au-gradient);
}

.unfav-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 7, 12, 0.68);
  border: 1px solid rgba(251, 113, 133, 0.35);
  border-radius: 50%;
  color: var(--au-danger);
  cursor: pointer;
  backdrop-filter: blur(6px);
  transition: all var(--au-fast);
}

.unfav-btn:hover:not(:disabled) {
  background: var(--au-danger-soft);
  transform: scale(1.08);
}

.unfav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.card-body {
  padding: 0.5rem 0.125rem 0;
}

.card-title {
  display: block;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--au-text);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-title:hover {
  color: var(--au-primary);
}

.card-meta {
  margin: 0.1875rem 0 0;
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  font-size: 0.6875rem;
  color: var(--au-text-3);
}

.rating {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
  color: var(--au-warning);
}

.star {
  fill: currentColor;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 640px) {
  .page-head {
    align-items: flex-start;
  }
  .fav-grid {
    grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
    gap: 0.875rem 0.625rem;
  }
}
</style>
