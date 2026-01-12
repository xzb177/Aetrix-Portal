<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { X } from 'lucide-vue-next'

interface Props {
  show?: boolean
  title?: string
  showClose?: boolean
  closeOnMaskClick?: boolean
  closeOnSwipeDown?: boolean
  maxHeight?: string
}

interface Emits {
  (e: 'update:show', value: boolean): void
  (e: 'close', method: 'mask' | 'button' | 'swipe' | 'escape'): void
  (e: 'open'): void
}

const props = withDefaults(defineProps<Props>(), {
  show: false,
  title: '',
  showClose: true,
  closeOnMaskClick: true,
  closeOnSwipeDown: true,
  maxHeight: '85vh',
})

const emit = defineEmits<Emits>()

// DOM 引用
const sheetRef = ref<HTMLElement>()
const contentRef = ref<HTMLElement>()

// 手势状态
const isDragging = ref(false)
const startY = ref(0)
const currentY = ref(0)
const dragOffset = ref(0)

// 动画状态
const isVisible = ref(false)
const isAnimating = ref(false)

// 计算样式
const transformStyle = computed(() => {
  if (dragOffset.value > 0) {
    return `translateY(${dragOffset.value}px)`
  }
  return ''
})

const sheetStyle = computed(() => ({
  maxHeight: props.maxHeight,
  transform: transformStyle.value,
}))

// 判断是否应该关闭（拖拽超过阈值）
const shouldClose = computed(() => {
  return dragOffset.value > 100
})

// 锁定/解锁背景滚动
const lockScroll = () => {
  document.body.style.overflow = 'hidden'
  document.body.style.position = 'fixed'
  document.body.style.width = '100%'
}

const unlockScroll = () => {
  document.body.style.overflow = ''
  document.body.style.position = ''
  document.body.style.width = ''
}

// 关闭 Sheet
const close = (method: 'mask' | 'button' | 'swipe' | 'escape' = 'button') => {
  isAnimating.value = true
  isVisible.value = false

  setTimeout(() => {
    emit('update:show', false)
    emit('close', method)
    unlockScroll()
    isAnimating.value = false
    dragOffset.value = 0
  }, 280)
}

// 打开 Sheet
const open = () => {
  isVisible.value = true
  isAnimating.value = true
  lockScroll()

  setTimeout(() => {
    isAnimating.value = false
    emit('open')
  }, 280)
}

// 手势处理
const handleTouchStart = (e: TouchEvent) => {
  if (!props.closeOnSwipeDown) return

  const touch = e.touches[0]
  const target = e.target as HTMLElement

  // 只在拖拽条或 Sheet 顶部区域开始拖拽
  const isDragHandle = target.closest('.sheet-drag-handle')
  const isHeaderArea = target.closest('.sheet-header')

  if (isDragHandle || (isHeaderArea && contentRef.value && contentRef.value.scrollTop === 0)) {
    isDragging.value = true
    startY.value = touch.clientY
    currentY.value = touch.clientY
  }
}

const handleTouchMove = (e: TouchEvent) => {
  if (!isDragging.value) return

  const touch = e.touches[0]
  currentY.value = touch.clientY
  const deltaY = currentY.value - startY.value

  // 只允许向下拖拽
  if (deltaY > 0) {
    dragOffset.value = deltaY
    e.preventDefault()
  }
}

const handleTouchEnd = () => {
  if (!isDragging.value) return

  if (shouldClose.value) {
    close('swipe')
  } else {
    // 回弹动画
    dragOffset.value = 0
  }

  isDragging.value = false
}

// 鼠标事件（桌面端支持）
const handleMouseDown = (e: MouseEvent) => {
  if (!props.closeOnSwipeDown) return

  const target = e.target as HTMLElement
  const isDragHandle = target.closest('.sheet-drag-handle')
  const isHeaderArea = target.closest('.sheet-header')

  if (isDragHandle || isHeaderArea) {
    isDragging.value = true
    startY.value = e.clientY
    currentY.value = e.clientY

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }
}

const handleMouseMove = (e: MouseEvent) => {
  if (!isDragging.value) return

  currentY.value = e.clientY
  const deltaY = currentY.value - startY.value

  if (deltaY > 0) {
    dragOffset.value = deltaY
  }
}

const handleMouseUp = () => {
  if (!isDragging.value) return

  if (shouldClose.value) {
    close('swipe')
  } else {
    dragOffset.value = 0
  }

  isDragging.value = false
  document.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('mouseup', handleMouseUp)
}

// ESC 键关闭
const handleEscapeKey = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.show) {
    close('escape')
  }
}

// 监听 show 变化
watch(() => props.show, (newVal) => {
  if (newVal) {
    nextTick(() => open())
  } else if (isVisible.value && !isAnimating.value) {
    close()
  }
})

// 生命周期
onMounted(() => {
  document.addEventListener('keydown', handleEscapeKey)
  if (props.show) {
    open()
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleEscapeKey)
  unlockScroll()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div
        v-if="show || isVisible"
        class="sheet-overlay"
        @click="closeOnMaskClick ? close('mask') : null"
      >
        <Transition :name="isVisible ? 'sheet-slide' : ''">
          <div
            v-if="show || isVisible"
            ref="sheetRef"
            class="bottom-sheet"
            :style="sheetStyle"
            @touchstart="handleTouchStart"
            @touchmove="handleTouchMove"
            @touchend="handleTouchEnd"
            @mousedown="handleMouseDown"
            @click.stop
          >
            <!-- 拖拽条和关闭按钮 -->
            <div class="sheet-header">
              <div class="sheet-drag-handle"></div>
              <h3 v-if="title" class="sheet-title">{{ title }}</h3>
              <button
                v-if="showClose"
                class="sheet-close"
                @click="close('button')"
              >
                <X :size="18" />
              </button>
            </div>

            <!-- 内容区域 -->
            <div ref="contentRef" class="sheet-content">
              <slot></slot>
            </div>

            <!-- 安全区域适配 -->
            <div class="sheet-safe-area"></div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ==================== 遮罩层 ==================== */
.sheet-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-sheet, 200);
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 0;
}

/* ==================== Bottom Sheet ==================== */
.bottom-sheet {
  width: 100%;
  max-width: 480px;
  background: linear-gradient(180deg, #1a1a1a 0%, #141414 100%);
  border-radius: var(--radius-lg, 16px) var(--radius-lg, 16px) 0 0;
  box-shadow:
    0 -4px 24px rgba(0, 0, 0, 0.5),
    0 0 0 1px rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  max-height: v-bind(maxHeight);
  will-change: transform;
}

@media (min-width: 481px) {
  .bottom-sheet {
    border-radius: var(--radius-lg, 16px);
    margin-bottom: env(safe-area-inset-bottom, 0);
  }
}

/* ==================== 头部 ==================== */
.sheet-header {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px var(--space-md, 16px) 8px;
  flex-shrink: 0;
}

/* 拖拽条 */
.sheet-drag-handle {
  width: 36px;
  height: 4px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: var(--radius-sm, 8px);
  margin-bottom: 8px;
  cursor: grab;
  transition: background var(--duration-fast, 150ms) ease;
}

.sheet-drag-handle:active {
  cursor: grabbing;
  background: rgba(255, 255, 255, 0.3);
}

/* 标题 */
.sheet-title {
  font-size: var(--text-subtitle-size, 16px);
  font-weight: var(--font-weight-semibold, 600);
  color: var(--text-subtitle-color, #ffffff);
  text-align: center;
  margin: 0;
  flex: 1;
}

/* 关闭按钮 */
.sheet-close {
  position: absolute;
  top: 6px;
  right: var(--space-md, 16px);
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.08);
  border: none;
  border-radius: var(--radius-sm, 8px);
  color: var(--text-quaternary, rgba(255, 255, 255, 0.5));
  cursor: pointer;
  transition: all var(--duration-fast, 150ms) ease;
}

.sheet-close:active {
  background: rgba(255, 255, 255, 0.15);
  color: var(--text-secondary, rgba(255, 255, 255, 0.7));
}

/* ==================== 内容区域 ==================== */
.sheet-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px var(--space-md, 16px) var(--space-md, 16px);
  -webkit-overflow-scrolling: touch;
}

/* 隐藏滚动条但保留功能 */
.sheet-content::-webkit-scrollbar {
  display: none;
}

.sheet-content {
  scrollbar-width: none;
}

/* ==================== 安全区域 ==================== */
.sheet-safe-area {
  flex-shrink: 0;
  height: env(safe-area-inset-bottom, 0);
  min-height: var(--space-sm, 12px);
}

/* ==================== 动画 ==================== */

/* 遮罩淡入淡出 */
.sheet-fade-enter-active,
.sheet-fade-leave-active {
  transition: opacity 0.28s ease;
}

.sheet-fade-enter-from,
.sheet-fade-leave-to {
  opacity: 0;
}

/* Sheet 上滑动画 */
.sheet-slide-enter-active {
  transition: transform 0.32s cubic-bezier(0.32, 0.72, 0, 1);
}

.sheet-slide-leave-active {
  transition: transform 0.28s cubic-bezier(0.4, 0, 1, 1);
}

.sheet-slide-enter-from {
  transform: translateY(100%);
}

.sheet-slide-leave-to {
  transform: translateY(100%);
}

/* ==================== 顶部高光边框 ==================== */
.bottom-sheet::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.15) 50%,
    transparent 100%
  );
}
</style>
