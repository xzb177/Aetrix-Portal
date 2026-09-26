<script setup lang="ts">
/**
 * 条目详情页 — 电影/剧集通用（季/单集唯一的停留页；顶层不出现）。
 *
 * 电影：海报 + 元数据 + 播放按钮。
 * 剧集：上次看到横条 + 季选择（底部弹窗） + 集列表
 *       （每集缩略图/简介/进度/播放入口，有数据的单集才显示简介）。
 * 顶层「继续观看」的剧集卡点进来会带 ?ep=单集Id，自动切到对应季并高亮滚动。
 */
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { embyApi, posterUrl, backdropUrl, progressPercent, ticksToSeconds, formatDuration, type EmbyItem } from '@/api/emby'
import { useToast } from '@/composables/useToast'
import { pageTitle } from '@/composables/useBranding'
import { useUserStore } from '@/stores/user'
import {
  Play, Star, Heart, Eye, EyeOff, Clock, Layers, ChevronLeft, ChevronDown, Film,
  Crown, Sparkles, Check,
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
/** 季选择底部弹窗 */
const sheetOpen = ref(false)
/** 从顶层续播卡点进来时高亮直达的单集 */
const highlightEpId = ref('')
let pendingScrollEp = ''

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
const runtime = computed(() => (item.value?.RunTimeTicks ? formatDuration(ticksToSeconds(item.value.RunTimeTicks)) : '—'))
/** 无海报时首字占位 */
const titleChar = computed(() => (item.value?.Name || '?').trim().charAt(0) || '?')
/** 画质徽标（与 MediaCard 同口径） */
const quality = computed(() => {
  const h = item.value?.Height || 0
  if (h >= 2160) return '4K'
  if (h >= 1080) return '1080p'
  if (h >= 720) return '720p'
  if (item.value?.IsHD) return 'HD'
  return ''
})

const currentSeasonName = computed(() => {
  const s = seasons.value.find(x => x.Id === selectedSeasonId.value)
  return s?.Name || '剧集列表'
})

/** 从 ?ep= 定位单集：切到它所在的季并高亮滚动 */
async function locateEpisode(epId: string) {
  if (item.value?.Type !== 'Series' || !epId) return
  try {
    const all = await embyApi.getEpisodes(itemId.value)
    const hit = all.find((e) => e.Id === epId)
    if (!hit) return
    const sid = seasons.value.find((x) => x.Id === hit.SeasonId)?.Id
    if (sid && sid !== selectedSeasonId.value) {
      // 切季：下面的 watcher 会加载该季并滚动到高亮集
      pendingScrollEp = epId
      selectedSeasonId.value = sid
    } else {
      // 已经在目标季（或季未知）：直接高亮滚动
      if (!sid) episodes.value = all
      pendingScrollEp = ''
      highlightEpId.value = epId
      await nextTick()
      document.getElementById(`ep-${epId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  } catch {
    /* 定位失败就停在默认季，不打扰用户 */
  }
}

/** 默认选中的季：优先集数最多的非第 0 季。
 * 第 0 季是特别篇/花絮，直接取 seasons[0] 会导致点进详情页只看到 1 集
 *（如《颤抖的真相》共 7 集，第 0 季只有 1 集，2026-09-26 用户反馈）。
 * 第 0 季仍可通过季选择器手动切换查看。 */
function defaultSeasonId(list: EmbyItem[]): string {
  const nonZero = list.filter((s) => (s.IndexNumber ?? 0) !== 0)
  const pool = nonZero.length ? nonZero : list
  let best = pool[0]
  for (const s of pool) {
    if ((s.ChildCount ?? 0) > (best.ChildCount ?? 0)) best = s
  }
  return best.Id
}

async function loadItem() {
  loading.value = true
  highlightEpId.value = ''
  pendingScrollEp = ''
  sheetOpen.value = false
  try {
    item.value = await embyApi.getItem(itemId.value)
    document.title = pageTitle(item.value.Name)
    if (item.value.Type === 'Series') {
      seasons.value = await embyApi.getSeasons(itemId.value)
      selectedSeasonId.value = ''
      const targetEp = route.query.ep as string | undefined
      if (targetEp && seasons.value.length) {
        await locateEpisode(targetEp)
      } else if (seasons.value.length) {
        selectedSeasonId.value = defaultSeasonId(seasons.value)
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
    if (!pendingScrollEp) highlightEpId.value = ''
    episodes.value = await embyApi.getEpisodes(itemId.value, sid)
    if (pendingScrollEp) {
      const id = pendingScrollEp
      pendingScrollEp = ''
      highlightEpId.value = id
      await nextTick()
      document.getElementById(`ep-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }
})

// 同一剧集内 ?ep= 变化（从顶层点另一集进来）也重新定位
watch(
  () => route.query.ep as string | undefined,
  (epId) => {
    if (epId && item.value?.Type === 'Series' && epId !== highlightEpId.value) locateEpisode(epId)
  },
)

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

/** 有实际播放进度的那集（用于「上次看到」横条；纯未看的第一集不算） */
const inProgressEp = computed(() => {
  if (item.value?.Type !== 'Series') return null
  return (
    episodes.value.find((e) => (e.UserData?.PlaybackPositionTicks || 0) > 0 && !e.UserData?.Played) ||
    null
  )
})
const inProgressLabel = computed(() => {
  const e = inProgressEp.value
  if (!e) return ''
  const pos =
    e.ParentIndexNumber != null && e.IndexNumber != null
      ? `第${e.ParentIndexNumber}季第${e.IndexNumber}集`
      : e.IndexNumber != null
        ? `第${e.IndexNumber}集`
        : ''
  return `${pos} · ${e.Name || ''}`.trim()
})
/** 单集缩略图（有图才显示）；长标题在 CSS 里截断 */
const epPoster = (ep: EmbyItem) => posterUrl(ep, 320)
const epTitle = (ep: EmbyItem) =>
  `${ep.IndexNumber != null ? `第${ep.IndexNumber}集 ` : ''}${ep.Name || ''}`.trim()
/** 季选择：底部弹窗 */
function pickSeason(sid: string) {
  sheetOpen.value = false
  if (sid !== selectedSeasonId.value) selectedSeasonId.value = sid
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
              <span class="placeholder-char">{{ titleChar }}</span>
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
              <span v-if="quality" class="quality">{{ quality }}</span>
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

            <!-- 上次看到：有实际播放进度时出现，一键续播 -->
            <div v-if="inProgressEp" class="resume-banner">
              <div class="resume-info">
                <p class="resume-kicker">上次看到</p>
                <p class="resume-title" :title="inProgressLabel">{{ inProgressLabel }}</p>
                <div class="resume-track">
                  <div
                    class="resume-fill"
                    :style="{ width: progressPercent(inProgressEp) + '%' }"
                  ></div>
                </div>
              </div>
              <RouterLink :to="`/watch/${inProgressEp.Id}`" class="btn primary sm">
                <Play :size="14" />
                继续播放
              </RouterLink>
            </div>
          </div>
        </div>

        <!-- 剧集：季切换 + 集列表 -->
        <section v-if="item.Type === 'Series'" class="episodes">
          <div class="episodes-head">
            <h2 class="section-title">剧集</h2>
            <div v-if="seasons.length > 1" class="season-picker">
              <button type="button" class="season-btn" @click="sheetOpen = true">
                <Layers :size="14" />
                {{ currentSeasonName }}
                <ChevronDown :size="14" />
              </button>
            </div>
            <span v-else-if="seasons.length === 1" class="season-name">{{ currentSeasonName }}</span>
          </div>

          <ul class="ep-list">
            <li
              v-for="ep in episodes"
              :key="ep.Id"
              :id="`ep-${ep.Id}`"
              class="ep-item"
              :class="{ highlight: ep.Id === highlightEpId }"
            >
              <RouterLink :to="`/watch/${ep.Id}`" class="ep-link">
                <div class="ep-thumb">
                  <img v-if="epPoster(ep)" :src="epPoster(ep)" :alt="ep.Name" loading="lazy" />
                  <span v-else class="ep-thumb-num">{{ ep.IndexNumber ?? '·' }}</span>
                </div>
                <div class="ep-body">
                  <span class="ep-name" :title="epTitle(ep)">{{ epTitle(ep) }}</span>
                  <span v-if="ep.Overview" class="ep-overview">{{ ep.Overview }}</span>
                  <span class="ep-meta">
                    {{ ep.RunTimeTicks ? formatDuration(ticksToSeconds(ep.RunTimeTicks)) : '' }}<template v-if="ep.RunTimeTicks"> · </template>{{ ep.UserData?.Played ? '已看' : '未看' }}
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

    <!-- 季选择：底部弹窗 -->
    <Teleport to="body">
      <Transition name="sheet">
        <div v-if="sheetOpen" class="sheet-mask" @click="sheetOpen = false">
          <div class="sheet" role="dialog" aria-label="选择季" @click.stop>
            <div class="sheet-handle"></div>
            <p class="sheet-title">选择季</p>
            <ul class="sheet-list">
              <li v-for="s in seasons" :key="s.Id">
                <button
                  type="button"
                  class="sheet-item"
                  :class="{ active: s.Id === selectedSeasonId }"
                  @click="pickSeason(s.Id)"
                >
                  <span class="sheet-item-name">{{ s.Name }}</span>
                  <span v-if="s.ChildCount" class="sheet-item-count">{{ s.ChildCount }} 集</span>
                  <Check v-if="s.Id === selectedSeasonId" :size="16" class="sheet-check" />
                </button>
              </li>
            </ul>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.detail-view {
  min-height: 100vh;
  background: var(--au-bg);
  color: var(--au-text);
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
  background-color: var(--au-bg-soft);
  pointer-events: none;
}

.backdrop-shade {
  position: absolute;
  inset: 0;
  background: linear-gradient(to bottom, var(--au-overlay-soft), var(--au-overlay-strong) 70%, var(--au-bg));
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
  background: var(--au-overlay-soft);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  color: var(--au-text-2);
  font-size: 0.8125rem;
  cursor: pointer;
  backdrop-filter: blur(6px);
  transition: all 0.15s ease;
}

.back-btn:hover {
  color: var(--au-text);
}

.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.625rem;
  padding: 5rem 0;
  color: var(--au-text-3);
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
  border: 1px solid var(--au-border);
  box-shadow: var(--au-shadow-2);
  display: block;
}

.poster.placeholder {
  aspect-ratio: 2 / 3;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, var(--au-primary-soft), var(--au-surface));
  color: var(--au-text-4);
}

.placeholder-char {
  font-size: 4.5rem;
  font-weight: 800;
  line-height: 1;
  color: var(--au-primary);
  opacity: 0.75;
  user-select: none;
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
  color: var(--au-text);
  line-height: 1.25;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  flex-wrap: wrap;
  font-size: 0.8125rem;
  color: var(--au-text-3);
  margin-bottom: 0.75rem;
}

/* Emby 风：元数据项之间用 · 分隔 */
.meta-row > span + span {
  position: relative;
}

.meta-row > span + span::before {
  content: '·';
  position: absolute;
  left: -0.5625rem;
  color: var(--au-text-4);
}

.meta-row .quality {
  color: #ffd75e;
  font-weight: 700;
  font-size: 0.75rem;
  letter-spacing: 0.03em;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.cert {
  padding: 0.125rem 0.4375rem;
  border: 1px solid var(--au-border-strong);
  border-radius: 5px;
  font-size: 0.6875rem;
  font-weight: 600;
}

.rating {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  color: var(--au-warning);
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
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: 8px;
  color: var(--au-success);
  font-size: 0.6875rem;
}

.overview {
  margin: 0 0 1.375rem;
  font-size: 0.875rem;
  line-height: 1.7;
  color: var(--au-text-2);
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
  background: linear-gradient(120deg, var(--au-primary-soft), var(--au-violet-soft));
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
  color: var(--au-on-primary);
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
  background: var(--au-gradient);
  color: var(--au-on-primary);
  box-shadow: 0 4px 16px var(--au-primary-glow);
}

.btn.primary:hover {
  box-shadow: 0 6px 20px var(--au-primary-glow);
}

.btn.primary.disabled {
  opacity: 0.45;
  pointer-events: none;
}

.btn.ghost {
  background: var(--au-surface);
  color: var(--au-text);
  border: 1px solid var(--au-border);
}

.btn.ghost:hover {
  background: var(--au-surface-3);
  color: var(--au-text);
}

.filled {
  fill: var(--au-danger);
  color: var(--au-danger);
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
  color: var(--au-text);
}

/* 季选择按钮（点开底部弹窗） */
.season-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  height: 34px;
  padding: 0 0.75rem;
  background: var(--au-overlay-soft);
  border: 1px solid var(--au-border);
  border-radius: 9px;
  color: var(--au-text);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.season-btn:hover {
  border-color: var(--au-border-strong);
}

.season-btn svg:last-child {
  color: var(--au-text-3);
}

/* 上次看到横条 */
.resume-banner {
  display: flex;
  align-items: center;
  gap: 1rem;
  max-width: 560px;
  margin: 1.25rem 0 0;
  padding: 0.875rem 1rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: 12px;
}

.resume-info {
  flex: 1;
  min-width: 0;
}

.resume-kicker {
  margin: 0;
  font-size: 0.6875rem;
  color: var(--au-text-3);
}

.resume-title {
  margin: 0.125rem 0 0.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-track {
  height: 4px;
  border-radius: 2px;
  background: var(--au-on-image-strong);
  overflow: hidden;
}

.resume-fill {
  height: 100%;
  background: var(--au-gradient);
}

.btn.sm {
  height: 34px;
  padding: 0 0.875rem;
  font-size: 0.8125rem;
  border-radius: 9px;
  flex-shrink: 0;
}

.season-name {
  font-size: 0.8125rem;
  color: var(--au-text-3);
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
  background: var(--au-surface);
  border: 1px solid var(--au-border);
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
  background: var(--au-surface);
}

.ep-thumb {
  flex-shrink: 0;
  width: 112px;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  overflow: hidden;
  background: var(--au-primary-soft);
  display: flex;
  align-items: center;
  justify-content: center;
}

.ep-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.ep-thumb-num {
  color: var(--au-primary);
  font-size: 0.9375rem;
  font-weight: 700;
}

.ep-overview {
  margin-top: 0.25rem;
  font-size: 0.75rem;
  line-height: 1.55;
  color: var(--au-text-3);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 从顶层续播卡直达的单集高亮 */
.ep-item.highlight {
  border-color: var(--au-primary);
  box-shadow: 0 0 0 1px var(--au-primary);
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
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ep-meta {
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.ep-state {
  flex-shrink: 0;
}

.play {
  color: var(--au-text-3);
}

.ep-link:hover .play {
  color: var(--au-primary);
}

.played {
  color: var(--au-primary);
}

.ep-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  background: var(--au-on-image-strong);
}

.ep-progress-fill {
  height: 100%;
  background: var(--au-primary);
}

.no-eps {
  text-align: center;
  padding: 2rem 0;
  font-size: 0.8125rem;
  color: var(--au-text-4);
}

/* 季选择底部弹窗 */
.sheet-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  backdrop-filter: blur(2px);
}

.sheet {
  width: 100%;
  max-width: 560px;
  max-height: 70vh;
  overflow-y: auto;
  background: var(--au-bg-soft);
  border: 1px solid var(--au-border);
  border-bottom: none;
  border-radius: 18px 18px 0 0;
  padding: 0.5rem 0.75rem 1.5rem;
}

.sheet-handle {
  width: 40px;
  height: 4px;
  border-radius: 2px;
  background: var(--au-border-strong);
  margin: 0.375rem auto 0.75rem;
}

.sheet-title {
  margin: 0 0 0.5rem;
  padding: 0 0.5rem;
  font-size: 0.9375rem;
  font-weight: 700;
  color: var(--au-text);
}

.sheet-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.sheet-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.75rem 0.875rem;
  background: transparent;
  border: none;
  border-radius: 10px;
  color: var(--au-text);
  font-size: 0.875rem;
  cursor: pointer;
  text-align: left;
}

.sheet-item:hover {
  background: var(--au-surface-2);
}

.sheet-item.active {
  background: var(--au-primary-soft);
  color: var(--au-primary);
  font-weight: 600;
}

.sheet-item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sheet-item-count {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.sheet-item.active .sheet-item-count {
  color: var(--au-primary);
}

.sheet-check {
  flex-shrink: 0;
}

.sheet-enter-active,
.sheet-leave-active {
  transition: opacity 0.2s ease;
}

.sheet-enter-from,
.sheet-leave-to {
  opacity: 0;
}

.sheet-enter-active .sheet,
.sheet-leave-active .sheet {
  transition: transform 0.25s ease;
}

.sheet-enter-from .sheet,
.sheet-leave-to .sheet {
  transform: translateY(48px);
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

  .ep-thumb {
    width: 84px;
  }

  .resume-banner {
    max-width: none;
  }
}
</style>
