<template>
  <Transition :name="transitionName" :mode="mode">
    <slot />
  </Transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export type TransitionName =
  | 'fade'
  | 'slide-up'
  | 'slide-down'
  | 'slide-left'
  | 'slide-right'
  | 'scale'
  | 'none'

export interface PageTransitionProps {
  name?: TransitionName
  mode?: 'default' | 'out-in' | 'in-out' | null
}

const props = withDefaults(defineProps<PageTransitionProps>(), {
  name: 'fade',
  mode: 'out-in'
})

const transitionName = computed(() => `page-${props.name}`)
</script>

<style scoped>
/* 淡入淡出 */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.2s ease;
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
}

/* 向上滑动 */
.page-slide-up-enter-active,
.page-slide-up-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.page-slide-up-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.page-slide-up-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}

/* 向下滑动 */
.page-slide-down-enter-active,
.page-slide-down-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.page-slide-down-enter-from {
  opacity: 0;
  transform: translateY(-20px);
}

.page-slide-down-leave-to {
  opacity: 0;
  transform: translateY(20px);
}

/* 向左滑动 */
.page-slide-left-enter-active,
.page-slide-left-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.page-slide-left-enter-from {
  opacity: 0;
  transform: translateX(30px);
}

.page-slide-left-leave-to {
  opacity: 0;
  transform: translateX(-30px);
}

/* 向右滑动 */
.page-slide-right-enter-active,
.page-slide-right-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.page-slide-right-enter-from {
  opacity: 0;
  transform: translateX(-30px);
}

.page-slide-right-leave-to {
  opacity: 0;
  transform: translateX(30px);
}

/* 缩放 */
.page-scale-enter-active,
.page-scale-leave-active {
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.page-scale-enter-from,
.page-scale-leave-to {
  opacity: 0;
  transform: scale(0.9);
}

/* 无动画 */
.page-none-enter-active,
.page-none-leave-active {
  transition: none;
}

.page-none-enter-from,
.page-none-leave-to {
  opacity: 1;
}
</style>
