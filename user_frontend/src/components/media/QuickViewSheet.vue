<script setup lang="ts">
/**
 * QuickViewSheet —— 媒体库"轻量快线"：点海报先弹底部 sheet（/watch/ 式体验），
 * 再点播放即播；要看完整信息再进详情整页。
 *
 * 设计来源：web_player/index.html 的 sheet 交互 + ItemDetailView 的数据口径。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { X, Play, ChevronRight } from 'lucide-vue-next'
import { embyApi, posterUrl, backdropUrl, type EmbyItem, type EmbyItemVersion } from '@/api/emby'
import Skeleton from '@/components/ui/Skeleton.vue'

const props = defineProps<{ itemId: string | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const item = ref<EmbyItem | null>(null)
const loading = ref(false)
const loadError = ref('')
const versions = ref<EmbyItemVersion[]>([])
const selectedVersionId = ref('')
const seasons = ref<EmbyItem[]>([])
const selectedSeasonId = ref('')
const episodes = ref<EmbyItem[]>([])
const episodesLoading = ref(false)
const imgOk = ref({ backdrop: true, poster: true })

const open = computed(() => !!props.itemId)
const isSeries = computed(() => item.value?.Type === 'Series')
const hasVersions = computed(() => versions.value.length > 1)
const poster = computed(() => (item.value ? posterUrl(item.value, 342) : ''))
const backdrop = computed(() => (item.value ? backdropUrl(item.value, 1280) : ''))
const metaLine = computed(() => {
  const it = item.value
  if (!it) return ''
  const parts: string[] = []
  if (it.ProductionYear) parts.push(String(it.ProductionYear))
  parts.push(it.Type === 'Movie' ? '电影' : it.Type === 'Series' ? '剧集' : '影片')
  if (it.CommunityRating) parts.push(`★ ${it.CommunityRating.toFixed(1)}`)
  if (it.Type === 'Series' && (it.ChildCount || 0) > 0) parts.push(`共 ${it.ChildCount} 集`)
  if (it.RunTimeTicks && it.Type === 'Movie') {
    const min = Math.round(it.RunTimeTicks / 600000000)
    if (min > 0) parts.push(`${min} 分钟`)
  }
  return parts.join(' · ')
})

/** 默认季：非第 0 季里集数最多的（与 ItemDetailView 同口径） */
function defaultSeasonId(list: EmbyItem[]): string {
  const nonZero = list.filter((s) => (s.IndexNumber ?? 0) !== 0)
  const pool = nonZero.length ? nonZero : list
  let best = pool[0]
  for (const s of pool) {
    if ((s.ChildCount ?? 0) > (best.ChildCount ?? 0)) best = s
  }
  return best?.Id ?? ''
}

async function load(id: string) {
  loading.value = true
  loadError.value = ''
  item.value = null
  versions.value = []
  seasons.value = []
  episodes.value = []
  selectedVersionId.value = ''
  selectedSeasonId.value = ''
  imgOk.value = { backdrop: true, poster: true }
  try {
    // P0#2：getItem 与 getSeasons 并行，不再串行等 3 个请求。
    // 电影调 getSeasons 会多一次空返回（后端直接 []），换来剧集少一次 RTT，划算。
    const [it, seasonsList] = await Promise.all([
      embyApi.getItem(id),
      embyApi.getSeasons(id).catch((): EmbyItem[] => []),
    ])
    item.value = it
    // Versions 含主版本在内（IsPrimary 标记），与 ItemDetailView 同口径
    versions.value = it.Versions || []
    selectedVersionId.value = versions.value.find((v) => v.IsPrimary)?.Id || versions.value[0]?.Id || ''
    if (it.Type === 'Series') {
      seasons.value = seasonsList
      if (seasons.value.length) {
        // 只赋值即可：下面 watch(selectedSeasonId) 会统一触发 loadEpisodes。
        // 这里再显式 await 一次会让默认季的剧集被并发请求两遍——数据一样但白扔
        // 一个请求，大剧集（Limit=500）下明显拖慢首屏，且两次响应乱序到达会互相覆盖。
        selectedSeasonId.value = defaultSeasonId(seasons.value)
      } else {
        episodes.value = await embyApi.getEpisodes(id)
      }
    }
  } catch {
    loadError.value = '加载失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

async function loadEpisodes(seasonId: string) {
  if (!props.itemId) return
  episodesLoading.value = true
  try {
    episodes.value = await embyApi.getEpisodes(props.itemId, seasonId)
  } catch {
    episodes.value = []
  } finally {
    episodesLoading.value = false
  }
}

watch(
  () => props.itemId,
  (id) => {
    if (id) {
      document.body.style.overflow = 'hidden'
      load(id)
    } else {
      document.body.style.overflow = ''
    }
  },
  { immediate: true },
)

watch(selectedSeasonId, (sid) => {
  if (sid) loadEpisodes(sid)
})

function close() {
  emit('close')
}

function playMovie() {
  const target = hasVersions.value && selectedVersionId.value ? selectedVersionId.value : props.itemId
  if (target) router.push(`/watch/${target}`)
}

function playEpisode(epId: string) {
  router.push(`/watch/${epId}`)
}

function goDetail() {
  if (props.itemId) router.push(`/media/${props.itemId}`)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}
watch(open, (v) => {
  if (v) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
})
// 播放/详情会路由跳转导致卸载：必须解锁 body，否则页面滚不动
onBeforeUnmount(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="qv-mask" @click.self="close">
      <div class="qv-sheet" role="dialog" aria-modal="true" aria-label="快速预览">
        <button class="qv-close" @click="close" aria-label="关闭"><X :size="20" /></button>

        <div v-if="loading" class="qv-skeleton" aria-hidden="true">
          <Skeleton variant="rect" class="sk-backdrop" />
          <div class="sk-body">
            <div class="sk-head">
              <Skeleton variant="rounded" class="sk-poster" />
              <div class="sk-info">
                <Skeleton variant="text" class="sk-title" />
                <Skeleton variant="text" class="sk-meta" />
                <Skeleton variant="rounded" class="sk-btn" />
              </div>
            </div>
            <Skeleton variant="text" class="sk-ov" />
            <Skeleton variant="text" class="sk-ov sk-ov2" />
            <div class="sk-eps">
              <Skeleton v-for="i in 8" :key="i" variant="rounded" class="sk-ep" />
            </div>
          </div>
        </div>
        <div v-else-if="loadError" class="qv-error">{{ loadError }}</div>
        <template v-else-if="item">
          <!-- 背景 -->
          <div class="qv-backdrop">
            <img decoding="async"
              v-if="backdrop && imgOk.backdrop"
              :src="backdrop"
              alt=""
              loading="lazy"
              @error="imgOk.backdrop = false"
            />
            <div class="qv-shade"></div>
          </div>

          <div class="qv-body">
            <div class="qv-head">
              <div class="qv-poster">
                <img decoding="async"
                  v-if="poster && imgOk.poster"
                  :src="poster"
                  :alt="item.Name"
                  loading="lazy"
                  @error="imgOk.poster = false"
                />
                <span v-else class="qv-char">{{ (item.Name || '?').trim().charAt(0) || '?' }}</span>
              </div>
              <div class="qv-info">
                <h2 class="qv-title">{{ item.Name }}</h2>
                <p v-if="metaLine" class="qv-meta">{{ metaLine }}</p>
                <!-- 电影多版本 -->
                <label v-if="!isSeries && hasVersions" class="qv-ver">
                  <span>版本</span>
                  <select v-model="selectedVersionId">
                    <option v-for="v in versions" :key="v.Id" :value="v.Id">
                      {{ v.Name || '版本' }}
                    </option>
                  </select>
                </label>
                <div class="qv-actions">
                  <button v-if="!isSeries" class="qv-play" @click="playMovie">
                    <Play :size="16" /> 播放
                  </button>
                  <button class="qv-detail" @click="goDetail">
                    详情 <ChevronRight :size="14" />
                  </button>
                </div>
              </div>
            </div>

            <p v-if="item.Overview" class="qv-overview">{{ item.Overview }}</p>

            <!-- 剧集选集 -->
            <div v-if="isSeries" class="qv-eps">
              <div v-if="seasons.length > 1" class="qv-seasons">
                <button
                  v-for="s in seasons"
                  :key="s.Id"
                  class="qv-season"
                  :class="{ active: s.Id === selectedSeasonId }"
                  @click="selectedSeasonId = s.Id"
                >
                  {{ s.Name }}
                </button>
              </div>
              <div v-if="episodesLoading" class="qv-eps-loading">剧集加载中…</div>
              <div v-else class="qv-ep-grid">
                <button
                  v-for="ep in episodes"
                  :key="ep.Id"
                  class="qv-ep"
                  :class="{ watched: !!ep.UserData?.Played }"
                  @click="playEpisode(ep.Id)"
                >
                  {{ ep.IndexNumber ?? '·' }}
                </button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.qv-mask {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0, 0, 0, 0.6);
  display: flex; align-items: flex-end; justify-content: center;
  animation: qv-fade 0.18s ease-out;
}
.qv-sheet {
  position: relative;
  width: 100%; max-width: 640px;
  max-height: 88vh; overflow-y: auto;
  background: #14141c; color: #f2f2f5;
  border-radius: 18px 18px 0 0;
  animation: qv-up 0.22s ease-out;
  padding-bottom: calc(20px + env(safe-area-inset-bottom));
}
@keyframes qv-fade { from { opacity: 0 } }
@keyframes qv-up { from { transform: translateY(40px); opacity: 0.6 } }
.qv-close {
  position: absolute; top: 10px; right: 10px; z-index: 3;
  width: 32px; height: 32px; border-radius: 50%;
  background: rgba(0,0,0,0.55); border: 0; color: #fff;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
}
.qv-loading, .qv-error { padding: 48px 20px; text-align: center; color: #9a9aa5; }
.qv-skeleton { padding-bottom: 20px; }
.qv-skeleton .sk-backdrop { display: block; width: 100%; height: 170px; border-radius: 0; }
.qv-skeleton .sk-body { padding: 0 16px; margin-top: -44px; position: relative; }
.qv-skeleton .sk-head { display: flex; gap: 14px; }
.qv-skeleton .sk-poster { width: 92px; height: 138px; flex: none; border-radius: 10px; }
.qv-skeleton .sk-info { flex: 1; min-width: 0; padding-top: 44px; }
.qv-skeleton .sk-title { height: 20px; width: 70%; margin-bottom: 8px; }
.qv-skeleton .sk-meta { height: 14px; width: 45%; margin-bottom: 12px; }
.qv-skeleton .sk-btn { height: 40px; width: 100%; border-radius: 10px; }
.qv-skeleton .sk-ov { height: 14px; width: 100%; margin-top: 12px; }
.qv-skeleton .sk-ov2 { width: 82%; }
.qv-skeleton .sk-eps { display: grid; grid-template-columns: repeat(8, 1fr); gap: 8px; margin-top: 12px; }
.qv-skeleton .sk-ep { aspect-ratio: 1; border-radius: 8px; }
.qv-backdrop { position: relative; height: 170px; overflow: hidden; background: #0b0b10; }
.qv-backdrop img { width: 100%; height: 100%; object-fit: cover; }
.qv-shade {
  position: absolute; inset: 0;
  background: linear-gradient(to bottom, rgba(20,20,28,0.1), #14141c);
}
.qv-body { padding: 0 16px; margin-top: -44px; position: relative; }
.qv-head { display: flex; gap: 14px; }
.qv-poster {
  width: 92px; height: 138px; flex: none;
  border-radius: 10px; overflow: hidden; background: #26262f;
  box-shadow: 0 4px 16px rgba(0,0,0,0.5);
}
.qv-poster img { width: 100%; height: 100%; object-fit: cover; }
.qv-char { display: flex; width: 100%; height: 100%; align-items: center; justify-content: center; font-size: 36px; color: #9a9aa5; }
.qv-info { flex: 1; min-width: 0; padding-top: 44px; }
.qv-title { margin: 0 0 4px; font-size: 18px; font-weight: 700; line-height: 1.3; }
.qv-meta { margin: 0 0 10px; font-size: 12.5px; color: #9a9aa5; }
.qv-ver { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #9a9aa5; margin-bottom: 10px; }
.qv-ver select {
  flex: 1; background: #0e0e14; color: #f2f2f5;
  border: 1px solid #26262f; border-radius: 8px; padding: 7px 8px; font-size: 13px;
}
.qv-actions { display: flex; gap: 10px; }
.qv-play {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
  background: #3b82f6; color: #fff; border: 0; border-radius: 10px;
  padding: 11px; font-size: 15px; font-weight: 600; cursor: pointer;
}
.qv-detail {
  display: flex; align-items: center; gap: 2px;
  background: #26262f; color: #f2f2f5; border: 0; border-radius: 10px;
  padding: 11px 14px; font-size: 14px; cursor: pointer;
}
.qv-overview {
  margin: 12px 0 0; font-size: 13.5px; color: #c9c9d2; line-height: 1.55;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.qv-eps { margin-top: 12px; }
.qv-seasons { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 8px; }
.qv-season {
  flex: none; background: #26262f; color: #c9c9d2; border: 0; border-radius: 8px;
  padding: 7px 12px; font-size: 13px; cursor: pointer;
}
.qv-season.active { background: #3b82f6; color: #fff; }
.qv-eps-loading { padding: 16px; text-align: center; color: #9a9aa5; font-size: 13px; }
.qv-ep-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(44px, 1fr)); gap: 8px;
  padding-bottom: 4px;
}
.qv-ep {
  aspect-ratio: 1; border-radius: 8px; border: 1px solid #26262f;
  background: #0e0e14; color: #f2f2f5; font-size: 14px; cursor: pointer;
}
.qv-ep.watched { opacity: 0.45; }
.qv-ep:active { background: #3b82f6; }
</style>
