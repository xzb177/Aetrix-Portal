<script setup lang="ts">
/**
 * 媒体库首页 — 浏览内置于后端的 Emby 媒体库
 *
 * 分区：继续观看 / 最新添加 / 接下来看（NextUp）/ 我的收藏 / 媒体库入口。
 * 数据来自 /emby/* 协议端点（JWT 鉴权），与 Infuse 等客户端共享同一套进度。
 */
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { embyApi, backdropUrl, ticksToSeconds, type EmbyItem } from '@/api/emby'
import { useToast } from '@/composables/useToast'
import MediaRow from '@/components/media/MediaRow.vue'
import {
  Play, Library, FolderOpen, RefreshCw, Info, Search,
} from 'lucide-vue-next'

const toast = useToast()

const loading = ref(true)
const views = ref<EmbyItem[]>([])
const resume = ref<EmbyItem[]>([])
const latest = ref<EmbyItem[]>([])
const nextUp = ref<EmbyItem[]>([])
const favorites = ref<EmbyItem[]>([])

// Hero：优先取续看第一条
const hero = computed(() => resume.value[0] || latest.value[0] || null)
const heroBackdrop = computed(() => (hero.value ? backdropUrl(hero.value) : ''))
const heroProgress = computed(() => {
  if (!hero.value?.RunTimeTicks) return 0
  const pos = hero.value.UserData?.PlaybackPositionTicks || 0
  return Math.min(100, Math.round((pos / hero.value.RunTimeTicks) * 100))
})
const heroLeft = computed(() => {
  if (!hero.value?.RunTimeTicks) return ''
  const remain = ticksToSeconds(hero.value.RunTimeTicks - (hero.value.UserData?.PlaybackPositionTicks || 0))
  const h = Math.floor(remain / 3600)
  const m = Math.round((remain % 3600) / 60)
  return h > 0 ? `还剩 ${h}小时${m}分钟` : `还剩 ${m}分钟`
})

const typeLabel = (t?: string) =>
  ({ Movie: '电影', Series: '剧集', Episode: '剧集' }[t || ''] || '影片')

async function loadAll() {
  loading.value = true
  try {
    const [v, r, l, n, f] = await Promise.all([
      embyApi.getViews().catch((): EmbyItem[] => []),
      embyApi.getResume().catch((): EmbyItem[] => []),
      embyApi.getLatest().catch((): EmbyItem[] => []),
      embyApi.getNextUp().catch((): EmbyItem[] => []),
      embyApi.getFavorites().catch((): EmbyItem[] => []),
    ])
    views.value = v
    resume.value = r
    latest.value = l
    nextUp.value = n
    favorites.value = f
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAll().catch(() => toast.error('媒体库加载失败'))
})
</script>

<template>
  <div class="lib-home">
    <!-- Hero -->
    <section v-if="hero" class="hero" :style="heroBackdrop ? { backgroundImage: `url(${heroBackdrop})` } : {}">
      <div class="hero-shade"></div>
      <div class="container hero-content">
        <span class="hero-tag">{{ typeLabel(hero.Type) }} · {{ heroLeft || '继续观看' }}</span>
        <h1 class="hero-title">{{ hero.Name }}</h1>
        <div v-if="heroProgress > 0" class="hero-progress">
          <div class="hero-progress-fill" :style="{ width: heroProgress + '%' }"></div>
        </div>
        <div class="hero-actions">
          <RouterLink class="btn primary" :to="`/media/${hero.Id}`">
            <Play :size="16" />
            {{ heroProgress > 0 ? '继续播放' : '立即播放' }}
          </RouterLink>
          <RouterLink class="btn ghost" :to="`/media/${hero.Id}`">
            <Info :size="16" />
            详情
          </RouterLink>
        </div>
      </div>
    </section>

    <div class="container main">
      <!-- 加载中 -->
      <div v-if="loading" class="loading">
        <RefreshCw :size="22" class="spinning" />
        <p>正在加载媒体库…</p>
      </div>

      <!-- 空库 -->
      <div v-else-if="!hero && views.length === 0" class="empty">
        <FolderOpen :size="36" />
        <h2>媒体库还是空的</h2>
        <p>请联系管理员添加媒体目录并扫描，扫描完成后即可在这里浏览和播放。</p>
      </div>

      <template v-else>
        <!-- 搜索入口：跨库检索 -->
        <RouterLink to="/search" class="search-entry au-anim-up">
          <Search :size="17" />
          <span>搜索电影、剧集、单集…</span>
          <span class="search-kbd">全局</span>
        </RouterLink>

        <MediaRow title="继续观看" :items="resume.slice(0, 12)" more-to="/history" />
        <MediaRow title="最新添加" :items="latest" />
        <MediaRow title="接下来看" :items="nextUp.slice(0, 12)" />
        <MediaRow title="我的收藏" :items="favorites.slice(0, 12)" more-to="/favorites" />

        <!-- 媒体库入口 -->
        <section v-if="views.length" class="views">
          <h2 class="row-title">
            <Library :size="18" />
            媒体库
          </h2>
          <div class="views-grid">
            <RouterLink v-for="v in views" :key="v.Id" :to="`/library/${v.Id}`" class="view-card">
              <div class="view-icon">
                <FolderOpen :size="20" />
              </div>
              <div class="view-body">
                <span class="view-name">{{ v.Name }}</span>
                <span class="view-count">{{ v.ChildCount || 0 }} 项</span>
              </div>
            </RouterLink>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.lib-home {
  min-height: 100vh;
  background: var(--au-bg);
  color: var(--au-text);
  padding-bottom: 3rem;
}

.container {
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 1.25rem;
}

/* Hero */
.hero {
  position: relative;
  min-height: 340px;
  display: flex;
  align-items: flex-end;
  background-size: cover;
  background-position: center 20%;
  background-color: #0a101a;
}

.hero-shade {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(to top, #070b12 8%, rgba(7, 11, 18, 0.55) 45%, rgba(7, 11, 18, 0.35) 100%),
    linear-gradient(100deg, rgba(7, 11, 18, 0.75) 25%, transparent 65%);
}

.hero-content {
  position: relative;
  padding-top: 4rem;
  padding-bottom: 2rem;
  width: 100%;
}

.hero-tag {
  display: inline-block;
  padding: 0.3125rem 0.625rem;
  background: rgba(34, 211, 238, 0.15);
  border: 1px solid rgba(34, 211, 238, 0.3);
  border-radius: 8px;
  color: var(--au-primary);
  font-size: 0.75rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.hero-title {
  margin: 0 0 0.875rem;
  font-size: 2rem;
  font-weight: 700;
  color: var(--au-text);
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.6);
}

.hero-progress {
  max-width: 320px;
  height: 4px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 1rem;
}

.hero-progress-fill {
  height: 100%;
  background: var(--au-gradient);
}

.hero-actions {
  display: flex;
  gap: 0.75rem;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  height: 42px;
  padding: 0 1.25rem;
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
  color: #05141c;
  box-shadow: 0 4px 16px rgba(34, 211, 238, 0.3);
}

.btn.primary:hover {
  box-shadow: 0 6px 20px rgba(34, 211, 238, 0.4);
}

.btn.ghost {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  backdrop-filter: blur(6px);
}

.btn.ghost:hover {
  background: rgba(255, 255, 255, 0.2);
}

.main {
  padding-top: 2rem;
}

.row-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.75rem;
  font-size: 1.0625rem;
  font-weight: 600;
  color: var(--au-text);
}

.row-title svg {
  color: var(--au-primary);
}

/* 加载与空态 */
.loading,
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.625rem;
  padding: 4.5rem 1rem;
  text-align: center;
  color: rgba(255, 255, 255, 0.4);
}

.empty svg {
  color: rgba(34, 211, 238, 0.4);
}

.empty h2 {
  margin: 0.375rem 0 0;
  font-size: 1.0625rem;
  color: var(--au-text-2);
}

.empty p {
  margin: 0;
  max-width: 380px;
  font-size: 0.8125rem;
  line-height: 1.6;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 搜索入口 */
.search-entry {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  height: 46px;
  padding: 0 1rem;
  margin-bottom: 1.5rem;
  background: rgba(148, 180, 220, 0.05);
  border: 1px solid var(--au-border);
  border-radius: 14px;
  color: rgba(234, 242, 251, 0.45);
  font-size: 0.875rem;
  text-decoration: none;
  transition: all 0.18s ease;
}

.search-entry:hover {
  border-color: var(--au-primary-border);
  background: rgba(34, 211, 238, 0.06);
  color: rgba(234, 242, 251, 0.7);
}

.search-entry svg { color: var(--au-primary); }

.search-kbd {
  margin-left: auto;
  padding: 0.125rem 0.5rem;
  background: rgba(34, 211, 238, 0.12);
  border: 1px solid rgba(34, 211, 238, 0.28);
  border-radius: 999px;
  color: var(--au-primary);
  font-size: 0.6875rem;
  font-weight: 600;
}

/* 媒体库入口 */
.views {
  margin-bottom: 2rem;
}

.views-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 0.75rem;
}

.view-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  background: rgba(10, 16, 26, 0.7);
  border: 1px solid var(--au-border);
  border-radius: 14px;
  text-decoration: none;
  transition: all 0.2s ease;
}

.view-card:hover {
  border-color: var(--au-primary-border);
  transform: translateY(-2px);
}

.view-icon {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(34, 211, 238, 0.1);
  border: 1px solid rgba(34, 211, 238, 0.2);
  border-radius: 12px;
  color: var(--au-primary);
}

.view-body {
  display: flex;
  flex-direction: column;
}

.view-name {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--au-text);
}

.view-count {
  font-size: 0.75rem;
  color: var(--au-text-3);
}
</style>
