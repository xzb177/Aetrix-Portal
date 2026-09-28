<script setup lang="ts">
/**
 * MediaRow — 横向滚动媒体行（续看/最新/NextUp/收藏等分区共用）
 */
import { ref, onMounted, watch } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import MediaCard, { type ResumeInfo } from './MediaCard.vue'
import type { EmbyItem } from '@/api/emby'

/** moreTo：右上角「查看全部」跳转目标（不传则不显示）
 *  resumeMap：剧集卡的续播信息（key 为条目 Id），「继续观看」行使用 */
const props = defineProps<{ title: string; items: EmbyItem[]; moreTo?: string; resumeMap?: Record<string, ResumeInfo> }>()

const scroller = ref<HTMLElement | null>(null)
// 横滑指示器：0~100 的滚动进度；不可横滑时隐藏
const scrollPct = ref(0)
const canScroll = ref(false)

function updateScrollState() {
  const el = scroller.value
  if (!el) return
  const max = el.scrollWidth - el.clientWidth
  canScroll.value = max > 8
  scrollPct.value = max > 0 ? Math.min(100, Math.max(0, (el.scrollLeft / max) * 100)) : 0
}

function scrollBy(dir: 1 | -1) {
  const el = scroller.value
  if (!el) return
  // 按可视宽度的 0.8 倍滚动：固定 560px 在小屏手机上一次滑过一屏半
  el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: 'smooth' })
}

onMounted(() => {
  updateScrollState()
})

watch(() => props.items, () => {
  // 内容变化后重新测量（下一帧等 DOM 更新完）
  requestAnimationFrame(updateScrollState)
})
</script>

<template>
  <section v-if="items.length" class="media-row">
    <header class="row-head">
      <h2 class="row-title">{{ title }}</h2>
      <div class="row-nav">
        <RouterLink v-if="moreTo" class="more-link" :to="moreTo">
          查看全部
          <ChevronRight :size="13" />
        </RouterLink>
        <button class="nav-btn" @click="scrollBy(-1)">
          <ChevronLeft :size="16" />
        </button>
        <button class="nav-btn" @click="scrollBy(1)">
          <ChevronRight :size="16" />
        </button>
      </div>
    </header>
    <div ref="scroller" class="row-scroller" @scroll="updateScrollState">
      <MediaCard v-for="item in items" :key="item.Id" :item="item" :resume="resumeMap?.[item.Id]" class="row-card" />
    </div>
    <!-- 横滑指示器：细进度条，暗示这行可以横滑；内容不足一屏时隐藏 -->
    <div v-if="canScroll" class="row-progress" aria-hidden="true">
      <div class="row-progress-fill" :style="{ width: Math.max(8, scrollPct) + '%' }"></div>
    </div>
  </section>
</template>

<style scoped>
.media-row {
  margin-bottom: 2rem;
}

.row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.row-title {
  margin: 0;
  font-size: 1.0625rem;
  font-weight: 600;
  color: var(--au-text);
}

.row-nav {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.more-link {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  margin-right: 0.25rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  text-decoration: none;
  transition: color var(--au-fast) ease;
}

.more-link:hover { color: var(--au-primary); }

.nav-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 8px;
  color: var(--au-text-2);
  cursor: pointer;
  transition: all 0.15s ease;
}

.nav-btn:hover {
  color: var(--au-text);
  background: var(--au-surface-2);
  border-color: var(--au-border-strong);
}

.row-scroller {
  display: flex;
  gap: 0.75rem;
  overflow-x: auto;
  scroll-behavior: smooth;
  /* 横滑贴合：松手不停在半张卡上 */
  scroll-snap-type: x proximity;
  overscroll-behavior-x: contain;
  padding-bottom: 0.375rem;
  margin: 0 -1.25rem;
  padding-left: 1.25rem;
  padding-right: 1.25rem;
  scrollbar-width: none;
}

.row-scroller::-webkit-scrollbar {
  display: none;
}

.row-card {
  flex: 0 0 132px;
  scroll-snap-align: start;
}

/* 横滑指示器 */
.row-progress {
  height: 3px;
  margin: 0.5rem 1.25rem 0;
  border-radius: 2px;
  background: var(--au-track);
  overflow: hidden;
}

.row-progress-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--au-primary);
  opacity: 0.55;
  transition: width 0.15s ease;
}

/* 移动端靠手势横滑，隐藏桌面思维的左右箭头 */
@media (max-width: 768px) {
  .nav-btn {
    display: none;
  }
}

@media (min-width: 768px) {
  .row-card {
    flex: 0 0 152px;
  }
}
</style>
