<script setup lang="ts">
/**
 * 观看记录 — 正在播放 + 观看历史
 *
 * v2.5.0 新增：此前用户只能看到首页「继续观看」的一小段切片，看不到完整播放记录，
 * 也无法查看/结束自己在其他设备上的播放会话。
 *
 * 数据源（均读本地播放记录与会话表，不触发媒体库扫描）：
 * - GET /api/user/emby/sessions  我的正在播放会话（设备 / 客户端 / IP / 进度）
 * - GET /api/user/emby/history   观看历史（按条目去重，取最近一次播放的设备）
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  History, MonitorPlay, RefreshCw, Play, CircleStop, Film, Tv, MonitorSmartphone,
  CircleCheck, Clock, ChevronRight, Wifi,
} from 'lucide-vue-next'
import { embyApi, type MyPlaybackSession, type WatchHistoryItem } from '@/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const PAGE_SIZE = 20

const sessions = ref<MyPlaybackSession[]>([])
const sessionsLoading = ref(true)
const stopping = ref<string | null>(null)

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

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const res = await embyApi.getSessions()
    sessions.value = res.sessions || []
  } catch {
    sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
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

async function stopSession(session: MyPlaybackSession) {
  stopping.value = session.session_key
  try {
    await embyApi.stopSession(session.session_key)
    toast.success(`已结束「${session.device || '未知设备'}」上的播放`)
    sessions.value = sessions.value.filter((s) => s.session_key !== session.session_key)
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '结束播放失败')
  } finally {
    stopping.value = null
  }
}

function refreshAll() {
  loadSessions()
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
          <RefreshCw :size="14" :class="{ spinning: loading || sessionsLoading }" />
          刷新
        </button>
      </header>

      <!-- 正在播放 -->
      <section v-if="sessionsLoading || sessions.length" class="au-card au-card-pad block au-anim-up">
        <div class="block-head">
          <h2 class="block-title">
            <MonitorPlay :size="16" />
            正在播放
            <span v-if="sessions.length" class="au-badge au-badge-green live">
              <span class="dot" />{{ sessions.length }} 个会话
            </span>
          </h2>
        </div>

        <div v-if="sessionsLoading" class="skeleton-list">
          <div class="au-skeleton skel-row" />
        </div>

        <div v-else class="session-list">
          <div v-for="s in sessions" :key="s.session_key" class="session-row">
            <div class="session-icon">
              <MonitorSmartphone :size="17" />
            </div>

            <div class="session-main">
              <div class="session-title">
                <RouterLink class="session-name" :to="`/media/${s.item_id}`">{{ s.item }}</RouterLink>
                <span class="au-badge au-badge-cyan">{{ typeLabel(s.item_type) }}</span>
                <span v-if="s.is_paused" class="au-badge au-badge-amber">已暂停</span>
              </div>
              <div class="session-meta">
                <span>{{ s.device || '未知设备' }}</span>
                <span v-if="s.client" class="meta-sep">·</span>
                <span v-if="s.client">{{ s.client }}</span>
                <span v-if="s.play_method" class="meta-sep">·</span>
                <span v-if="s.play_method" class="method">{{ s.play_method === 'Transcode' ? '转码' : '直连' }}</span>
                <span v-if="s.remote_addr" class="meta-sep">·</span>
                <span v-if="s.remote_addr" class="addr"><Wifi :size="11" />{{ s.remote_addr }}</span>
              </div>
              <div class="session-progress">
                <div class="bar"><div class="bar-fill" :style="{ width: s.progress + '%' }" /></div>
                <span class="bar-text">{{ s.progress }}% · {{ fmtTime(s.updated_at) }}</span>
              </div>
            </div>

            <button
              class="au-btn au-btn-danger au-btn-sm stop-btn"
              :disabled="stopping === s.session_key"
              @click="stopSession(s)"
            >
              <CircleStop :size="13" />
              {{ stopping === s.session_key ? '结束中' : '结束' }}
            </button>
          </div>
        </div>
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
            :to="`/media/${item.id}`"
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

/* ===== 正在播放 ===== */
.session-list { display: flex; flex-direction: column; gap: 0.5rem; }

.session-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.75rem 0.875rem;
  border-radius: var(--au-r-md);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
}

.session-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-sm);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.session-main { flex: 1; min-width: 0; }

.session-title {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  flex-wrap: wrap;
}

.session-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.session-name:hover { color: var(--au-primary); }

.session-meta {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  margin-top: 0.1875rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  flex-wrap: wrap;
}

.session-meta .addr { display: inline-flex; align-items: center; gap: 0.1875rem; }
.session-meta .method { color: var(--au-violet); }
.meta-sep { opacity: 0.5; }

.session-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.375rem;
}

.bar {
  flex: 1;
  max-width: 260px;
  height: 4px;
  border-radius: 2px;
  background: var(--au-border-strong);
  overflow: hidden;
}

.bar-fill { height: 100%; background: var(--au-gradient); }
.bar-text { font-size: 0.6875rem; color: var(--au-text-4); white-space: nowrap; }

.stop-btn { flex-shrink: 0; }

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
  background: rgba(0, 0, 0, 0.5);
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
