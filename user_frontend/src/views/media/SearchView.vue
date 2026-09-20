<script setup lang="ts">
/**
 * 全局搜索 — 跨整个媒体库检索（电影 / 剧集 / 单集）
 *
 * - 此前只能在进入某个媒体库后搜索，这里提供全局入口（顶栏搜索图标直达）
 * - 结果按类型分组展示；无结果时引导到「求片」
 * - 最近搜索本地保存（最多 8 条），点击即可复搜
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { embyApi, type EmbyItem } from '@/api/emby'
import MediaRow from '@/components/media/MediaRow.vue'
import {
  Search, X, History, Sparkles, Flame, MessageSquareDashed, TrendingUp,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()

const RECENT_KEY = 'aetrix.search.recent'
const PAGE_LIMIT = 60

const keyword = ref((route.query.q as string) || '')
const loading = ref(false)
const searched = ref(false)
const results = ref<EmbyItem[]>([])
const hot = ref<EmbyItem[]>([])
const recent = ref<string[]>([])

let timer: ReturnType<typeof setTimeout> | null = null

const groups = computed(() => {
  const bucket = (t: string) => results.value.filter((i) => i.Type === t)
  return [
    { title: '电影', items: bucket('Movie') },
    { title: '剧集', items: bucket('Series') },
    { title: '单集', items: bucket('Episode') },
  ].filter((g) => g.items.length > 0)
})

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    recent.value = raw ? (JSON.parse(raw) as string[]).slice(0, 8) : []
  } catch {
    recent.value = []
  }
}

function pushRecent(word: string) {
  const w = word.trim()
  if (!w) return
  recent.value = [w, ...recent.value.filter((r) => r !== w)].slice(0, 8)
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent.value))
  } catch {
    /* 存储不可用时忽略 */
  }
}

function clearRecent() {
  recent.value = []
  try {
    localStorage.removeItem(RECENT_KEY)
  } catch {
    /* 忽略 */
  }
}

async function runSearch(word: string) {
  const w = word.trim()
  if (!w) {
    results.value = []
    searched.value = false
    return
  }
  loading.value = true
  searched.value = true
  try {
    const res = await embyApi.getItems({
      searchTerm: w,
      limit: PAGE_LIMIT,
      recursive: true,
      sortBy: 'SortName',
      sortOrder: 'Ascending',
    })
    results.value = res.Items || []
    if (results.value.length) pushRecent(w)
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}

/** 输入防抖 + 地址栏同步，便于分享/回退 */
function onInput() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    router.replace({ path: '/search', query: keyword.value.trim() ? { q: keyword.value.trim() } : {} })
    runSearch(keyword.value)
  }, 350)
}

function useRecent(word: string) {
  keyword.value = word
  router.replace({ path: '/search', query: { q: word } })
  runSearch(word)
}

function reset() {
  keyword.value = ''
  results.value = []
  searched.value = false
  router.replace({ path: '/search' })
}

// 从其它页面跳入（如顶栏搜索、收藏页）时同步关键词
watch(
  () => route.query.q,
  (q) => {
    const val = (q as string) || ''
    if (val !== keyword.value) {
      keyword.value = val
      runSearch(val)
    }
  },
)

onMounted(async () => {
  loadRecent()
  embyApi.getLatest(12).then((items) => (hot.value = items)).catch(() => {})
  if (keyword.value) runSearch(keyword.value)
})

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="au-page search-page">
    <!-- 搜索框 -->
    <div class="search-head au-anim-up">
      <div class="search-box">
        <Search :size="18" class="search-icon" />
        <input
          v-model="keyword"
          class="search-input"
          type="search"
          placeholder="搜索电影、剧集、单集…"
          autocomplete="off"
          @input="onInput"
          @keyup.enter="onInput"
        />
        <button v-if="keyword" class="clear-btn" title="清空" @click="reset">
          <X :size="16" />
        </button>
      </div>
      <p v-if="searched && !loading" class="result-count">
        <template v-if="results.length">
          找到 <strong>{{ results.length }}</strong> 个结果
        </template>
        <template v-else>没有匹配的内容</template>
      </p>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="au-empty">
      <span class="au-spinner"></span>
      <p>正在检索媒体库…</p>
    </div>

    <template v-else>
      <!-- 结果分组 -->
      <template v-if="results.length">
        <MediaRow
          v-for="group in groups"
          :key="group.title"
          :title="`${group.title} · ${group.items.length}`"
          :items="group.items"
        />
      </template>

      <!-- 无结果：引导求片 -->
      <div v-else-if="searched" class="au-empty au-anim-up">
        <MessageSquareDashed :size="34" />
        <h2>「{{ keyword }}」没有找到</h2>
        <p>媒体库暂时没有这部片，可以提交求片，上线后会在消息中心通知你。</p>
        <RouterLink
          class="au-btn au-btn-primary"
          style="margin-top: 0.75rem"
          :to="{ path: '/request', query: { name: keyword } }"
        >
          <MessageSquareDashed :size="16" />
          提交求片
        </RouterLink>
      </div>

      <!-- 初始态：最近搜索 + 热门推荐 -->
      <template v-else>
        <section v-if="recent.length" class="recent au-anim-up">
          <header class="block-head">
            <h2 class="block-title">
              <History :size="16" />
              最近搜索
            </h2>
            <button class="text-btn" @click="clearRecent">清空</button>
          </header>
          <div class="chips">
            <button v-for="word in recent" :key="word" class="chip" @click="useRecent(word)">
              {{ word }}
            </button>
          </div>
        </section>

        <MediaRow v-if="hot.length" title="热门推荐" :items="hot" more-to="/media" />

        <div v-else class="au-empty">
          <Sparkles :size="30" />
          <p>输入片名开始搜索</p>
        </div>

        <section class="tips">
          <h2 class="block-title">
            <TrendingUp :size="16" />
            小提示
          </h2>
          <ul class="tip-list">
            <li><Flame :size="13" /> 支持中英文片名、剧集单集名</li>
            <li><Flame :size="13" /> 搜不到不代表没有，试试点「求片」</li>
          </ul>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.search-page {
  max-width: 1080px;
}

.search-head {
  margin-bottom: 1.5rem;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 0.9375rem;
  color: var(--au-text-4);
  pointer-events: none;
}

.search-input {
  width: 100%;
  height: 50px;
  padding: 0 2.75rem 0 2.75rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  color: var(--au-text);
  font-size: 0.9375rem;
  outline: none;
  transition: border-color var(--au-fast), box-shadow var(--au-fast);
  box-sizing: border-box;
}

.search-input::placeholder {
  color: var(--au-text-4);
}

.search-input:focus {
  border-color: var(--au-border-focus);
  box-shadow: 0 0 0 3px var(--au-primary-soft);
}

.search-input::-webkit-search-cancel-button {
  display: none;
}

.clear-btn {
  position: absolute;
  right: 0.75rem;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-surface-2);
  border: none;
  border-radius: 50%;
  color: var(--au-text-3);
  cursor: pointer;
}

.clear-btn:hover {
  color: var(--au-text);
  background: var(--au-surface-3);
}

.result-count {
  margin: 0.625rem 0 0;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.result-count strong {
  color: var(--au-primary);
  font-variant-numeric: tabular-nums;
}

.recent {
  margin-bottom: 1.75rem;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.block-title {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--au-text);
}

.block-title svg {
  color: var(--au-primary);
}

.text-btn {
  background: none;
  border: none;
  color: var(--au-text-3);
  font-size: 0.75rem;
  cursor: pointer;
}

.text-btn:hover {
  color: var(--au-danger);
}

.chips {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.chip {
  height: 32px;
  padding: 0 0.8125rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  color: var(--au-text-2);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.chip:hover {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.tips {
  margin-top: 1rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--au-border);
}

.tip-list {
  margin: 0.75rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.5rem;
}

.tip-list li {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.tip-list svg {
  color: var(--au-warning);
  flex-shrink: 0;
}
</style>
