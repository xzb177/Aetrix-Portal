<script setup lang="ts">
/**
 * MediaCard — 媒体海报卡片（首页行 / 库浏览 / 收藏共用）
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Play, Star, Eye, Layers } from 'lucide-vue-next'
import { posterUrl, progressPercent, type EmbyItem } from '@/api/emby'

const props = defineProps<{ item: EmbyItem }>()
const router = useRouter()

const poster = computed(() => posterUrl(props.item, 342))
const progress = computed(() => progressPercent(props.item))
const typeLabel = computed(() =>
  ({ Movie: '电影', Series: '剧集', Episode: '剧集', Season: '季' }[props.item.Type] || '影片'),
)
const targetRoute = computed(() =>
  props.item.Type === 'Episode' && props.item.SeriesId
    ? `/media/${props.item.SeriesId}`
    : `/media/${props.item.Id}`,
)

function open() {
  router.push(targetRoute.value)
}
</script>

<template>
  <div class="media-card" @click="open">
    <div class="poster-wrap">
      <img v-if="poster" :src="poster" :alt="item.Name" loading="lazy" />
      <div v-else class="poster-fallback">
        <Layers :size="28" />
      </div>

      <!-- 播放按钮悬浮 -->
      <div class="hover-play">
        <Play :size="22" />
      </div>

      <!-- 进度条 -->
      <div v-if="progress > 0 && progress < 96" class="progress-track">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
      </div>

      <!-- 已看标记 -->
      <span v-if="item.UserData?.Played" class="played-badge">
        <Eye :size="11" />
      </span>
    </div>

    <div class="card-body">
      <p class="card-title" :title="item.Name">{{ item.Name }}</p>
      <p class="card-meta">
        <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
        <span v-if="item.Type === 'Episode' && item.IndexNumber != null">第 {{ item.IndexNumber }} 集</span>
        <span v-else-if="item.Type !== 'Episode'">{{ typeLabel }}</span>
        <span v-if="item.CommunityRating" class="rating">
          <Star :size="10" class="star" />
          {{ item.CommunityRating.toFixed(1) }}
        </span>
      </p>
    </div>
  </div>
</template>

<style scoped>
.media-card {
  cursor: pointer;
  min-width: 0;
}

.poster-wrap {
  position: relative;
  aspect-ratio: 2 / 3;
  border-radius: 12px;
  overflow: hidden;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
}

.media-card:hover .poster-wrap {
  transform: translateY(-4px);
  border-color: var(--au-primary-border);
  box-shadow: var(--au-shadow-2);
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
  background: linear-gradient(160deg, var(--au-primary-soft), var(--au-overlay-soft));
}

.hover-play {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-overlay-soft);
  color: var(--au-text);
  opacity: 0;
  transition: opacity 0.2s ease;
}

.media-card:hover .hover-play {
  opacity: 1;
}

.hover-play svg {
  width: 52px;
  height: 52px;
  padding: 14px;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: 50%;
  color: var(--au-primary);
  backdrop-filter: blur(6px);
  filter: drop-shadow(0 4px 12px var(--au-shadow-color));
}

.progress-track {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 4px;
  background: var(--au-on-image-strong);
}

.progress-fill {
  height: 100%;
  background: var(--au-gradient);
}

.played-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-success);
  border-radius: 50%;
  color: var(--au-on-primary);
}

.card-body {
  padding: 0.5rem 0.125rem 0;
}

.card-title {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-meta {
  margin: 0.1875rem 0 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
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
</style>
