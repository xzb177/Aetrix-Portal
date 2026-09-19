<script setup lang="ts">
/**
 * MediaRow — 横向滚动媒体行（续看/最新/NextUp/收藏等分区共用）
 */
import { ref } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import MediaCard from './MediaCard.vue'
import type { EmbyItem } from '@/api/emby'

defineProps<{ title: string; items: EmbyItem[] }>()

const scroller = ref<HTMLElement | null>(null)

function scrollBy(dir: 1 | -1) {
  scroller.value?.scrollBy({ left: dir * 560, behavior: 'smooth' })
}
</script>

<template>
  <section v-if="items.length" class="media-row">
    <header class="row-head">
      <h2 class="row-title">{{ title }}</h2>
      <div class="row-nav">
        <button class="nav-btn" @click="scrollBy(-1)">
          <ChevronLeft :size="16" />
        </button>
        <button class="nav-btn" @click="scrollBy(1)">
          <ChevronRight :size="16" />
        </button>
      </div>
    </header>
    <div ref="scroller" class="row-scroller">
      <MediaCard v-for="item in items" :key="item.Id" :item="item" class="row-card" />
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
  color: #fafafa;
}

.row-nav {
  display: flex;
  gap: 0.375rem;
}

.nav-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.15s ease;
}

.nav-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.09);
}

.row-scroller {
  display: flex;
  gap: 0.75rem;
  overflow-x: auto;
  scroll-behavior: smooth;
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
}

@media (min-width: 768px) {
  .row-card {
    flex: 0 0 152px;
  }
}
</style>
