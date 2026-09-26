<script setup lang="ts">
/**
 * MediaCard — 媒体海报卡片（首页行 / 库浏览 / 收藏共用）
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Play, Star, Eye } from 'lucide-vue-next'
import { posterUrl, progressPercent, type EmbyItem } from '@/api/emby'

/**
 * 剧集卡的续播信息：顶层「继续观看」用剧集卡承载断点续播，
 * 不再把单集卡片平铺到顶层（单集只活在剧集详情页内）。
 */
export interface ResumeInfo {
  episodeId: string
  seasonNumber?: number | null
  episodeNumber?: number | null
  /** 0-100；>0 表示「看到一半」，=0 表示「下一集」 */
  progress: number
  totalEpisodes?: number | null
}

const props = defineProps<{ item: EmbyItem; resume?: ResumeInfo | null }>()
const router = useRouter()

const poster = computed(() => posterUrl(props.item, 342))
const hasResume = computed(() => props.item.Type === 'Series' && !!props.resume)
const progress = computed(() =>
  hasResume.value && props.resume ? props.resume.progress : progressPercent(props.item),
)
/** 续播副标题：看到第X季第X集 · 共Y集 / 下一集：第X季第X集 */
const resumeLabel = computed(() => {
  const r = props.resume
  if (!r) return ''
  const ep = r.seasonNumber != null && r.episodeNumber != null
    ? `第${r.seasonNumber}季第${r.episodeNumber}集`
    : r.episodeNumber != null
      ? `第${r.episodeNumber}集`
      : ''
  const total = r.totalEpisodes ? ` · 共${r.totalEpisodes}集` : ''
  return r.progress > 0 ? `看到${ep}${total}` : `下一集：${ep}${total}`
})
/** 画质徽标：Emby 风右上/左上小徽章，高度来自后端 Width/Height */
const quality = computed(() => {
  const h = props.item.Height || 0
  if (h >= 2160) return '4K'
  if (h >= 1080) return '1080p'
  if (h >= 720) return '720p'
  if (props.item.IsHD) return 'HD'
  return ''
})
/** 剧集未看集数（后端批量算好，非剧集恒为 0） */
const unplayed = computed(() =>
  props.item.Type === 'Series' ? props.item.UserData?.UnplayedItemCount || 0 : 0,
)
/** 无海报时用片名首字做文字海报（Emby 风），替代空图标 */
const firstChar = computed(() => (props.item.Name || '?').trim().charAt(0) || '?')
const typeLabel = computed(() =>
  ({ Movie: '电影', Series: '剧集', Episode: '剧集', Season: '季' }[props.item.Type] || '影片'),
)
const targetRoute = computed(() =>
  // 续播剧集卡：点进详情页并直达该集（详情页读 ?ep= 自动定位）
  hasResume.value && props.resume
    ? `/media/${props.item.Id}?ep=${props.resume.episodeId}`
    : props.item.Type === 'Episode' && props.item.SeriesId
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
        <span class="fallback-char">{{ firstChar }}</span>
      </div>

      <!-- 播放按钮悬浮 -->
      <div class="hover-play">
        <Play :size="22" />
      </div>

      <!-- 画质徽标（左上） -->
      <span v-if="quality" class="quality-badge">{{ quality }}</span>

      <!-- 未看集数（剧集右上，优先于已看眼标） -->
      <span v-if="unplayed > 0" class="unplayed-badge">{{ unplayed }}集未看</span>
      <span v-else-if="item.UserData?.Played" class="played-badge">
        <Eye :size="11" />
      </span>

      <!-- 进度条 -->
      <div v-if="progress > 0 && progress < 96" class="progress-track">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
      </div>
    </div>

    <div class="card-body">
      <p class="card-title" :title="item.Name">{{ item.Name }}</p>
      <p class="card-meta">
        <span v-if="hasResume" class="resume-text">{{ resumeLabel }}</span>
        <template v-else>
        <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
        <span v-if="item.Type === 'Episode' && item.IndexNumber != null">第 {{ item.IndexNumber }} 集</span>
        <span v-else-if="item.Type !== 'Episode'">{{ typeLabel }}</span>
        <span v-if="item.CommunityRating" class="rating">
          <Star :size="10" class="star" />
          {{ item.CommunityRating.toFixed(1) }}
        </span>
        </template>
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

.fallback-char {
  font-size: 3.5rem;
  font-weight: 800;
  line-height: 1;
  color: var(--au-primary);
  opacity: 0.75;
  user-select: none;
}

/* 画质徽标（左上，Emby 风） */
.quality-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.62);
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 6px;
  color: #ffd75e;
  font-size: 0.625rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  backdrop-filter: blur(4px);
  pointer-events: none;
}

/* 未看集数（剧集右上） */
.unplayed-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 2px 7px;
  background: var(--au-primary);
  border-radius: 10px;
  color: #04121a;
  font-size: 0.625rem;
  font-weight: 700;
  pointer-events: none;
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

/* 续播副标题：单行截断，不把卡片撑高 */
.resume-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--au-primary);
  font-weight: 600;
}

.star {
  fill: currentColor;
}
</style>
