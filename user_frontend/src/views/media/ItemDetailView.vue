<script setup lang="ts">
/**
 * 条目详情页 — 电影/剧集通用
 *
 * 电影：海报 + 元数据 + 播放按钮。
 * 剧集：季选择 + 集列表（每集显示进度与播放入口）。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { embyApi, posterUrl, backdropUrl, progressPercent, ticksToSeconds, formatDuration, type EmbyItem } from '@/api/emby'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'
import {
  Play, Star, Heart, Eye, EyeOff, Clock, Layers, ChevronLeft, ChevronDown, Film,
  Crown, Sparkles,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const userStore = useUserStore()

const item = ref<EmbyItem | null>(null)
const loading = ref(true)
const seasons = ref<EmbyItem[]>([])
const episodes = ref<EmbyItem[]>([])
const selectedSeasonId = ref('')
const togglingFavorite = ref(false)

// 付费墙：开启且当前账号不是会员时，提前给出开通引导
const needsSubscription = computed(() => userStore.needsSubscription)
// 公益服（v2.7.0）：免费开放，不放开通入口，只把规则说清楚
const isFreeRealm = computed(() => userStore.isFreeRealm)
const realmNote = computed(
  () => userStore.realmNote || '本服为公益服 · 免费开放：无需开通会员即可观看全库内容。',
)

const itemId = computed(() => route.params.id as string)

const poster = computed(() => (item.value ? posterUrl(item.value, 480) : ''))
const backdrop = computed(() => (item.value ? backdropUrl(item.value) : ''))
const isFavorite = computed(() => !!item.value?.UserData?.IsFavorite)
const isPlayed = computed(() => !!item.value?.UserData?.Played)
const progress = computed(() => (item.value ? progressPercent(item.value) : 0))
const runtime = computed(() => (item.value?.RunTimeTicks ? formatDuration(ticksToSeconds(item.value.RunTimeTicks)) : ''))

const currentSeasonName = computed(() => {
  const s = seasons.value.find(x => x.Id === selectedSeasonId.value)
  return s?.Name || '剧集列表'
})

async function loadItem() {
  loading.value = true
  try {
    item.value = await embyApi.getItem(itemId.value)
    document.title = `${item.value.Name} - Aetrix`
    if (item.value.Type === 'Series') {
      seasons.value = await embyApi.getSeasons(itemId.value)
      if (seasons.value.length) {
        selectedSeasonId.value = seasons.value[0].Id
      } else {
        episodes.value = await embyApi.getEpisodes(itemId.value)
      }
    }
  } catch {
    toast.error('加载详情失败')
  } finally {
    loading.value = false
  }
}

watch(selectedSeasonId, async (sid) => {
  if (sid && item.value?.Type === 'Series') {
    episodes.value = await embyApi.getEpisodes(itemId.value, sid)
  }
})

watch(itemId, () => {
  if (itemId.value) loadItem()
})

async function toggleFavorite() {
  if (!item.value || togglingFavorite.value) return
  togglingFavorite.value = true
  try {
    const ud = await embyApi.setFavorite(item.value.Id, !isFavorite.value)
    item.value.UserData = { ...item.value.UserData, ...ud }
    toast.success(ud.IsFavorite ? '已加入收藏' : '已取消收藏')
  } catch {
    toast.error('操作失败')
  } finally {
    togglingFavorite.value = false
  }
}

async function togglePlayed() {
  if (!item.value) return
  try {
    const ud = await embyApi.setPlayed(item.value.Id, !isPlayed.value)
    item.value.UserData = { ...item.value.UserData, ...ud }
    toast.success(ud.Played ? '已标记为看过' : '已标记为未看')
  } catch {
    toast.error('操作失败')
  }
}

/** 剧集"继续播放"：找到第一个未看完的集 */
const resumeEpisode = computed(() => {
  if (item.value?.Type !== 'Series') return null
  return (
    episodes.value.find(e => (e.UserData?.PlaybackPositionTicks || 0) > 0 && !e.UserData?.Played) ||
    episodes.value.find(e => !e.UserData?.Played) ||
    null
  )
})

function playTarget(): string {
  if (item.value?.Type === 'Series') {
    return resumeEpisode.value ? `/watch/${resumeEpisode.value.Id}` : ''
  }
  return `/watch/${item.value?.Id}`
}

onMounted(loadItem)
</script>

<template>
  <div class="detail-view">
    <!-- 背景大图 -->
    <div class="backdrop" :style="backdrop ? { backgroundImage: `url(${backdrop})` } : {}">
      <div class="backdrop-shade"></div>
    </div>

    <div class="container content">
      <button class="back-btn" @click="router.back()">
        <ChevronLeft :size="18" />
        返回
      </button>

      <div v-if="loading" class="loading">
        <Film :size="24" class="pulse" />
        <p>加载中…</p>
      </div>

      <template v-else-if="item">
        <div class="head-grid">
          <div class="poster-col">
            <img v-if="poster" :src="poster" :alt="item.Name" class="poster" />
            <div v-else class="poster placeholder">
              <Film :size="36" />
            </div>
          </div>

          <div class="info-col">
            <h1 class="title">{{ item.Name }}</h1>
            <div class="meta-row">
              <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
              <span v-if="runtime" class="meta-item">
                <Clock :size="12" />
                {{ runtime }}
              </span>
              <span v-if="item.OfficialRating" class="cert">{{ item.OfficialRating }}</span>
              <span v-if="item.CommunityRating" class="rating">
                <Star :size="12" class="star" />
                {{ item.CommunityRating.toFixed(1) }}
              </span>
              <span v-if="item.Type === 'Series' && item.ChildCount" class="meta-item">
                <Layers :size="12" />
                {{ item.ChildCount }} 集
              </span>
            </div>

            <div v-if="item.Genres?.length" class="genres">
              <span v-for="g in item.Genres" :key="g" class="genre">{{ g }}</span>
            </div>

            <p v-if="item.Overview" class="overview">{{ item.Overview }}</p>

            <!-- 会员提示：付费墙开启且未订阅 -->
            <RouterLink v-if="needsSubscription" to="/wallet?tab=plans" class="member-notice">
              <Crown :size="16" class="notice-icon" />
              <span class="notice-body">
                <strong>会员专享</strong>
                <em>当前账号没有生效中的订阅，开通后即可播放全库内容</em>
              </span>
              <span class="notice-cta">开通会员</span>
            </RouterLink>

            <!-- 公益服：这里不是营销位，只告诉用户“不用买也能看” -->
            <div v-else-if="isFreeRealm" class="free-notice">
              <Sparkles :size="15" class="notice-icon" />
              <span class="notice-body">
                <strong>公益服 · 免费开放</strong>
                <em>{{ realmNote }}</em>
              </span>
            </div>

            <!-- 操作区 -->
            <div class="actions">
              <RouterLink :to="playTarget()" class="btn primary" :class="{ disabled: playTarget() === '' }">
                <Play :size="16" />
                {{ progress > 0 ? '继续播放' : (item.Type === 'Series' ? '播放第一集' : '立即播放') }}
              </RouterLink>
              <button class="btn ghost" :disabled="togglingFavorite" @click="toggleFavorite">
                <Heart :size="16" :class="{ filled: isFavorite }" />
                {{ isFavorite ? '已收藏' : '收藏' }}
              </button>
              <button class="btn ghost" @click="togglePlayed">
                <EyeOff v-if="isPlayed" :size="16" />
                <Eye v-else :size="16" />
                {{ isPlayed ? '标记未看' : '看过' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 剧集：季切换 + 集列表 -->
        <section v-if="item.Type === 'Series'" class="episodes">
          <div class="episodes-head">
            <h2 class="section-title">剧集</h2>
            <div v-if="seasons.length > 1" class="season-select">
              <select v-model="selectedSeasonId">
                <option v-for="s in seasons" :key="s.Id" :value="s.Id">{{ s.Name }}</option>
              </select>
              <ChevronDown :size="14" class="select-arrow" />
            </div>
            <span v-else-if="seasons.length === 1" class="season-name">{{ currentSeasonName }}</span>
          </div>

          <ul class="ep-list">
            <li v-for="ep in episodes" :key="ep.Id" class="ep-item">
              <RouterLink :to="`/watch/${ep.Id}`" class="ep-link">
                <span class="ep-number">{{ ep.IndexNumber ?? '·' }}</span>
                <div class="ep-body">
                  <span class="ep-name">{{ ep.Name }}</span>
                  <span class="ep-meta">
                    {{ ep.RunTimeTicks ? formatDuration(ticksToSeconds(ep.RunTimeTicks)) : '' }}
                  </span>
                </div>
                <div class="ep-state">
                  <Eye v-if="ep.UserData?.Played" :size="14" class="played" />
                  <Play v-else :size="14" class="play" />
                </div>
                <div v-if="progressPercent(ep) > 0 && progressPercent(ep) < 96" class="ep-progress">
                  <div class="ep-progress-fill" :style="{ width: progressPercent(ep) + '%' }"></div>
                </div>
              </RouterLink>
            </li>
          </ul>
          <p v-if="episodes.length === 0" class="no-eps">该季暂无剧集数据</p>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.detail-view {
  min-height: 100vh;
  background: #070b12;
  color: #e5e7eb;
  padding-bottom: 3rem;
}

.backdrop {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 380px;
  background-size: cover;
  background-position: center 20%;
  background-color: #0a1210;
  pointer-events: none;
}

.backdrop-shade {
  position: absolute;
  inset: 0;
  background: linear-gradient(to bottom, rgba(7, 11, 18, 0.35), rgba(7, 11, 18, 0.88) 70%, #070b12);
}

.content {
  position: relative;
  padding-top: 1.5rem;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 0.75rem;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.75);
  font-size: 0.8125rem;
  cursor: pointer;
  backdrop-filter: blur(6px);
  transition: all 0.15s ease;
}

.back-btn:hover {
  color: #fff;
}

.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.625rem;
  padding: 5rem 0;
  color: rgba(255, 255, 255, 0.4);
}

.pulse {
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse {
  50% { opacity: 0.4; }
}

.head-grid {
  display: flex;
  gap: 1.75rem;
  padding-top: 1.25rem;
  margin-bottom: 2rem;
}

.poster-col {
  flex-shrink: 0;
  width: 200px;
}

.poster {
  width: 100%;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55);
  display: block;
}

.poster.placeholder {
  aspect-ratio: 2 / 3;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.15);
}

.info-col {
  flex: 1;
  min-width: 0;
  padding-top: 1rem;
}

.title {
  margin: 0 0 0.625rem;
  font-size: 1.75rem;
  font-weight: 700;
  color: #fafafa;
  line-height: 1.25;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  flex-wrap: wrap;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.55);
  margin-bottom: 0.75rem;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.cert {
  padding: 0.125rem 0.4375rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 5px;
  font-size: 0.6875rem;
  font-weight: 600;
}

.rating {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  color: #f59e0b;
  font-weight: 600;
}

.star {
  fill: currentColor;
}

.genres {
  display: flex;
  gap: 0.375rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.genre {
  padding: 0.25rem 0.5625rem;
  background: rgba(34, 211, 238, 0.08);
  border: 1px solid rgba(34, 211, 238, 0.18);
  border-radius: 8px;
  color: rgba(52, 211, 153, 0.9);
  font-size: 0.6875rem;
}

.overview {
  margin: 0 0 1.375rem;
  font-size: 0.875rem;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.6);
  max-width: 560px;
}

/* 会员提示条（付费墙） */
.member-notice {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  max-width: 560px;
  padding: 0.75rem 0.875rem;
  margin-bottom: 1rem;
  background: linear-gradient(120deg, rgba(34, 211, 238, 0.12), rgba(167, 139, 250, 0.12));
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-md);
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.member-notice:hover {
  border-color: var(--au-primary);
  transform: translateY(-1px);
}

.notice-icon {
  flex-shrink: 0;
  color: var(--au-primary);
}

/* 公益服（v2.7.0）：静态说明，不做成可点的营销位 */
.free-notice {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  max-width: 560px;
  padding: 0.6875rem 0.875rem;
  margin-bottom: 1rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-md);
}

.free-notice .notice-body em { white-space: normal; line-height: 1.6; }

.notice-body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
  flex: 1;
}

.notice-body strong {
  font-size: 0.8125rem;
  font-weight: 700;
  color: var(--au-text);
}

.notice-body em {
  font-style: normal;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.notice-cta {
  flex-shrink: 0;
  height: 30px;
  display: inline-flex;
  align-items: center;
  padding: 0 0.75rem;
  background: var(--au-gradient);
  border-radius: var(--au-r-full);
  color: #05141c;
  font-size: 0.75rem;
  font-weight: 700;
}

.actions {
  display: flex;
  gap: 0.625rem;
  flex-wrap: wrap;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  height: 42px;
  padding: 0 1.125rem;
  border-radius: 11px;
  font-size: 0.875rem;
  font-weight: 600;
  text-decoration: none;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn.primary {
  background: linear-gradient(135deg, #22d3ee, #06b6d4);
  color: #fff;
  box-shadow: 0 4px 16px rgba(34, 211, 238, 0.3);
}

.btn.primary:hover {
  box-shadow: 0 6px 20px rgba(34, 211, 238, 0.4);
}

.btn.primary.disabled {
  opacity: 0.45;
  pointer-events: none;
}

.btn.ghost {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.btn.ghost:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.filled {
  fill: #f87171;
  color: #f87171;
}

/* 剧集 */
.episodes-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.section-title {
  margin: 0;
  font-size: 1.0625rem;
  font-weight: 600;
  color: #fafafa;
}

.season-select {
  position: relative;
}

.season-select select {
  appearance: none;
  height: 34px;
  padding: 0 2rem 0 0.75rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  color: #e5e7eb;
  font-size: 0.8125rem;
  outline: none;
  cursor: pointer;
}

.season-select select option {
  background: #10161d;
}

.select-arrow {
  position: absolute;
  right: 0.625rem;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(255, 255, 255, 0.4);
  pointer-events: none;
}

.season-name {
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.5);
}

.ep-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.ep-item {
  background: rgba(13, 18, 24, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 12px;
  overflow: hidden;
}

.ep-link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.875rem 1rem;
  text-decoration: none;
  transition: background 0.15s ease;
}

.ep-link:hover {
  background: rgba(255, 255, 255, 0.03);
}

.ep-number {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(34, 211, 238, 0.1);
  border-radius: 9px;
  color: #22d3ee;
  font-size: 0.8125rem;
  font-weight: 700;
}

.ep-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.ep-name {
  font-size: 0.875rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.88);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ep-meta {
  font-size: 0.6875rem;
  color: rgba(255, 255, 255, 0.35);
}

.ep-state {
  flex-shrink: 0;
}

.play {
  color: rgba(255, 255, 255, 0.4);
}

.ep-link:hover .play {
  color: #22d3ee;
}

.played {
  color: #22d3ee;
}

.ep-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  background: rgba(255, 255, 255, 0.12);
}

.ep-progress-fill {
  height: 100%;
  background: #22d3ee;
}

.no-eps {
  text-align: center;
  padding: 2rem 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.35);
}

@media (max-width: 640px) {
  .head-grid {
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 1.25rem;
  }

  .poster-col {
    width: 160px;
  }

  .genres,
  .actions,
  .meta-row {
    justify-content: center;
  }

  .overview {
    margin-left: auto;
    margin-right: auto;
  }
}
</style>
