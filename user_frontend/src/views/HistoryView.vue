<script setup lang="ts">
/**
 * 观看记录（现在是「媒体库 · 观看记录」分段）— 只讲「我看过什么」
 *
 * v2.5.0 新增：此前用户只能看到首页「继续观看」的一小段切片，看不到完整播放记录。
 * v2.10.0：收藏 / 观看记录降级为媒体库内的分段（方案 A），本页在 `/media?tab=history`
 * 下渲染，旧地址 `/history` 重定向过来。
 * 「正在播放」（设备 / IP / 结束播放）讲的是**控制**而不是历史，已移入个人中心 → 见
 * `components/media/PlaybackSessions.vue`。
 *
 * 数据源：GET /api/user/emby/history 观看历史（按条目去重，取最近一次播放的设备）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  History, RefreshCw, Play, Film, Tv,
  CircleCheck, Clock, ChevronRight, MonitorSmartphone, MonitorPlay,
} from 'lucide-vue-next'
import { embyApi, type WatchHistoryItem } from '@/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const PAGE_SIZE = 20

const items = ref<WatchHistoryItem[]>([])
const loading = ref(true)
const loadingMore = ref(false)
const uniqueTotal = ref(0)
const offset = ref(0)
const typeFilter = ref<'' | 'Movie' | 'Series'>('')

const hasMore = computed(() => items.value.length < uniqueTotal.value)

const typeTabs: { value: '' | 'Movie' | 'Series'; label: string; icon: unknown }[] = [
  { value: '', label: '全部', icon: History },
  { value: 'Movie', label: '电影', icon: Film },
  { value: 'Series', label: '剧集', icon: Tv },
]

function typeLabel(t?: string | null) {
  return ({ Movie: '电影', Series: '剧集', Episode: '剧集' } as Record<string, string>)[t || ''] || '影片'
}

/** 聚合行的单集副标题：看到第X季第X集 · 集名 */
function episodeLabel(item: WatchHistoryItem): string {
  const pos =
    item.season_number != null && item.episode_number != null
      ? `第${item.season_number}季第${item.episode_number}集`
      : item.episode_number != null
        ? `第${item.episode_number}集`
        : ''
  const name = (item.episode_name || '').trim()
  return [pos, name].filter(Boolean).join(' · ')
}

/** 聚合行点进剧集详情并定位到该集；电影照常进详情页 */
function itemTo(item: WatchHistoryItem): string {
  return item.episode_id ? `/media/${item.id}?ep=${item.episode_id}` : `/media/${item.id}`
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  const date = new Date(iso)
  const now = Date.now()
  const diff = now - date.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' })
}

/** 播放进度（0-100） */
function progressOf(item: WatchHistoryItem): number {
  if (item.played) return 100
  const pos = item.position_ticks || 0
  const dur = item.duration_ticks || 0
  if (!dur) return 0
  return Math.min(100, Math.round((pos / dur) * 100))
}

/** 剩余时间文案 */
function remainText(item: WatchHistoryItem, progress: number): string {
  if (item.played) return '已看完'
  if (progress <= 0) return '未开始'
  if (progress >= 95) return '即将看完'
  return `已看 ${progress}%`
}

async function loadHistory(reset = true) {
  if (reset) {
    loading.value = true
    offset.value = 0
  } else {
    loadingMore.value = true
  }
  try {
    const res = await embyApi.getHistory({
      limit: PAGE_SIZE,
      offset: reset ? 0 : offset.value,
      item_type: typeFilter.value || undefined,
    })
    items.value = reset ? res.items : [...items.value, ...res.items]
    uniqueTotal.value = res.unique_total
    offset.value = items.value.length
  } catch {
    if (reset) items.value = []
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function refreshAll() {
  loadHistory(true)
}

watch(typeFilter, () => loadHistory(true))

onMounted(refreshAll)
</script>

<template>
  <div class="history-view">
    <div class="au-page">
      <!-- 头部 -->
      <header class="page-head au-anim-up">
        <div class="head-main">
          <h1 class="page-title">
            <History :size="20" />
            观看记录
          </h1>
          <p class="page-sub">
            <template v-if="uniqueTotal">共 {{ uniqueTotal }} 部作品有播放记录</template>
            <template v-else>你的播放进度会在所有设备间同步</template>
          </p>
        </div>
        <button class="au-btn au-btn-ghost au-btn-sm" @click="refreshAll">
          <RefreshCw :size="14" :class="{ spinning: loading }" />
          刷新
        </button>
      </header>

      <!-- 正在播放已移到个人中心：这块是「控制」不是「历史」 -->
      <section class="pointer-bar au-card au-anim-up">
        <MonitorPlay :size="15" />
        <span>在其他设备上播放、或想远程结束播放？</span>
        <RouterLink class="pointer-link" to="/profile">
          个人中心 → 正在播放
          <ChevronRight :size="13" />
        </RouterLink>
      </section>

      <!-- 历史列表 -->
      <section class="block au-anim-up">
        <div class="block-head history-head">
          <h2 class="block-title">
            <Clock :size="16" />
            历史记录
          </h2>
          <div class="type-tabs">
            <button
              v-for="t in typeTabs"
              :key="t.value"
              class="type-tab"
              :class="{ active: typeFilter === t.value }"
              @click="typeFilter = t.value"
            >
              <component :is="t.icon" :size="13" />
              {{ t.label }}
            </button>
          </div>
        </div>

        <div v-if="loading" class="skeleton-list">
          <div v-for="i in 4" :key="i" class="au-skeleton skel-card" />
        </div>

        <div v-else-if="items.length === 0" class="au-empty">
          <History :size="30" />
          <h3>还没有观看记录</h3>
          <p>去媒体库挑一部开始播放吧，进度会自动记录</p>
          <RouterLink class="au-btn au-btn-primary" to="/media">
            <Play :size="15" />
            进入媒体库
          </RouterLink>
        </div>

        <div v-else class="history-list">
          <RouterLink
            v-for="item in items"
            :key="item.id + (item.watched_at || '')"
            class="history-item au-card"
            :to="itemTo(item)"
          >
            <div class="poster">
              <img v-if="item.poster_url" :src="item.poster_url" :alt="item.name" loading="lazy" />
              <div v-else class="poster-fallback"><Film :size="18" /></div>
              <div v-if="progressOf(item) > 0 && !item.played" class="poster-progress">
                <div :style="{ width: progressOf(item) + '%' }" />
              </div>
            </div>

            <div class="item-main">
              <div class="item-title-row">
                <span class="item-name">{{ item.name }}</span>
                <span v-if="item.played" class="au-badge au-badge-green">
                  <CircleCheck :size="11" />已看完
                </span>
              </div>
              <div class="item-meta">
                <span>{{ typeLabel(item.type) }}</span>
                <template v-if="item.episode_id">
                  <span class="meta-sep">·</span><span class="ep-label">{{ episodeLabel(item) }}</span>
                </template>
                <template v-if="item.year"><span class="meta-sep">·</span><span>{{ item.year }}</span></template>
                <span class="meta-sep">·</span>
                <span>{{ remainText(item, progressOf(item)) }}</span>
                <template v-if="item.play_count > 1">
                  <span class="meta-sep">·</span><span>看过 {{ item.play_count }} 次</span>
                </template>
              </div>
              <div class="item-device">
                <MonitorSmartphone :size="12" />
                <span>{{ item.device || '未知设备' }}</span>
                <span v-if="item.client">· {{ item.client }}</span>
                <span class="item-time">{{ fmtTime(item.watched_at) }}</span>
              </div>
            </div>

            <ChevronRight :size="16" class="item-arrow" />
          </RouterLink>

          <button v-if="hasMore" class="au-btn au-btn-ghost load-more" :disabled="loadingMore" @click="loadHistory(false)">
            {{ loadingMore ? '加载中…' : `加载更多（还有 ${uniqueTotal - items.length} 部）` }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* 页头与页面骨架见 styles/aurora.css「页面骨架」一节（原先这里写了一份同样的） */

.block { margin-bottom: 1.25rem; }

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.875rem;
  flex-wrap: wrap;
  margin-bottom: 0.875rem;
}

.history-head { margin-bottom: 1rem; }

.block-title {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--au-text);
}

.block-title svg { color: var(--au-primary); }

.live { gap: 0.3125rem; }
.live .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--au-success);
  box-shadow: 0 0 8px var(--au-success);
  animation: au-pulse-soft 1.6s ease-in-out infinite;
}

/* 正在播放的指针条（会话卡片本身在个人中心 → PlaybackSessions） */
.pointer-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 0.9375rem;
  margin-bottom: 1.25rem;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.pointer-bar svg { color: var(--au-primary); flex-shrink: 0; }

.pointer-link {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  margin-left: auto;
  color: var(--au-primary);
  text-decoration: none;
  font-weight: 600;
}

.pointer-link:hover { text-decoration: underline; }

/* ===== 类型筛选 ===== */
.type-tabs { display: flex; gap: 0.375rem; }

.type-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  height: 30px;
  padding: 0 0.6875rem;
  border-radius: var(--au-r-full);
  border: 1px solid var(--au-border);
  background: transparent;
  color: var(--au-text-3);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.type-tab:hover { color: var(--au-text); border-color: var(--au-border-strong); }
.type-tab.active {
  color: var(--au-primary);
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
}

/* ===== 历史列表 ===== */
.history-list { display: flex; flex-direction: column; gap: 0.5rem; }

.history-item {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.625rem 0.875rem 0.625rem 0.625rem;
  text-decoration: none;
  transition: all var(--au-fast) var(--au-ease);
}

.ep-label {
  color: var(--au-primary);
  font-weight: 600;
}

.history-item:hover {
  border-color: var(--au-primary-border);
  transform: translateX(2px);
}

.poster {
  position: relative;
  width: 46px;
  height: 64px;
  flex-shrink: 0;
  border-radius: var(--au-r-sm);
  overflow: hidden;
  background: var(--au-surface-3);
}

.poster img { width: 100%; height: 100%; object-fit: cover; display: block; }

.poster-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--au-text-4);
}

.poster-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  /* 封面上的进度槽：用叠加层令牌，不再写死 rgba(0,0,0,.5) */
  background: var(--au-track);
}

.poster-progress > div { height: 100%; background: var(--au-primary); }

.item-main { flex: 1; min-width: 0; }

.item-title-row { display: flex; align-items: center; gap: 0.4375rem; }

.item-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  margin-top: 0.1875rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  flex-wrap: wrap;
}

.item-device {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  margin-top: 0.3125rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  flex-wrap: wrap;
}

.item-time { margin-left: auto; }
.item-arrow { color: var(--au-text-4); flex-shrink: 0; }

.load-more { align-self: center; margin-top: 0.5rem; }

/* ===== 骨架 ===== */
.skeleton-list { display: flex; flex-direction: column; gap: 0.5rem; }
.skel-row { height: 62px; }
.skel-card { height: 84px; }

.spinning { animation: au-spin 0.9s linear infinite; }
</style>
