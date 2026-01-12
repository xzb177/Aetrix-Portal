<template>
  <Transition name="summary-bar">
    <div
      v-if="show && announcement"
      class="announcement-summary-bar"
      @click="handleClick"
    >
      <!-- 左侧：标签 + 标题 -->
      <div class="summary-bar-left">
        <div class="summary-bar-badge">
          <AlertTriangle :size="12" />
        </div>
        <span class="summary-bar-title">{{ truncatedTitle }}</span>
      </div>

      <!-- 右侧：箭头 -->
      <ChevronRight :size="16" class="summary-bar-arrow" />
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Ref } from 'vue'
import { AlertTriangle, ChevronRight } from 'lucide-vue-next'
import type { Announcement } from '@/composables/useP0Announcement'

interface Props {
  show: boolean | Ref<boolean>
  announcement: Announcement | null | Ref<Announcement | null>
  maxLength?: number
}

interface Emits {
  (e: 'click'): void
}

const props = withDefaults(defineProps<Props>(), {
  maxLength: 20
})

// 解包可能的 Ref
const show = computed(() => typeof props.show === 'boolean' ? props.show : props.show.value)
const announcement = computed(() =>
  props.announcement === null || typeof props.announcement === 'object' && 'value' in props.announcement
    ? (props.announcement as Ref<Announcement | null>).value
    : props.announcement
)

const emit = defineEmits<Emits>()

// 截断标题
const truncatedTitle = computed(() => {
  if (!announcement.value?.title) return ''
  const title = announcement.value.title
  return title.length > props.maxLength
    ? title.slice(0, props.maxLength) + '...'
    : title
})

const handleClick = () => {
  emit('click')
}
</script>

<style scoped>
.announcement-summary-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  margin: 12px 0;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  -webkit-tap-highlight-color: transparent;
}

.announcement-summary-bar:active {
  transform: scale(0.98);
  background: rgba(245, 158, 11, 0.12);
}

.summary-bar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.summary-bar-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(245, 158, 11, 0.2);
  border-radius: 6px;
  color: #fbbf24;
  flex-shrink: 0;
}

.summary-bar-title {
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.summary-bar-arrow {
  flex-shrink: 0;
  color: rgba(255, 255, 255, 0.4);
}

/* 过渡动画 */
.summary-bar-enter-active,
.summary-bar-leave-active {
  transition: all 0.3s ease;
}

.summary-bar-enter-from,
.summary-bar-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
