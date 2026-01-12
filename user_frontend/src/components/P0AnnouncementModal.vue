<template>
  <Teleport to="body">
    <Transition name="p0-modal">
      <div
        v-if="show"
        class="p0-modal-overlay"
        @click.self="handleMaskClick"
      >
        <div class="p0-modal-container">
          <!-- 顶部装饰条（amber 色表示重要） -->
          <div class="p0-modal-top-bar">
            <div class="p0-modal-top-bar-inner"></div>
          </div>

          <!-- 内容区 -->
          <div class="p0-modal-content">
            <!-- 标题区 -->
            <div class="p0-modal-header">
              <div class="p0-modal-badge">
                <AlertTriangle :size="14" />
                <span>重要公告</span>
              </div>
              <h2 class="p0-modal-title">{{ announcement?.title || '系统通知' }}</h2>
            </div>

            <!-- 内容文本（支持滚动） -->
            <div class="p0-modal-body">
              <div class="p0-modal-text" v-html="formattedContent"></div>
            </div>
          </div>

          <!-- 底部按钮区（固定，带安全区域） -->
          <div class="p0-modal-footer">
            <!-- 次要按钮：复制内容（可选） -->
            <button
              v-if="showCopyButton"
              class="p0-modal-btn p0-modal-btn-secondary"
              @click="handleCopy"
            >
              <Copy :size="18" />
              <span>复制内容</span>
            </button>

            <!-- 主按钮：我已知晓 -->
            <button
              class="p0-modal-btn p0-modal-btn-primary"
              :class="{ 'p0-modal-btn-full': !showCopyButton }"
              @click="handleAck"
            >
              <Check :size="18" />
              <span>我已知晓</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Ref } from 'vue'
import { AlertTriangle, Copy, Check } from 'lucide-vue-next'
import type { Announcement } from '@/composables/useP0Announcement'

interface Props {
  show: boolean | Ref<boolean>
  announcement: Announcement | null | Ref<Announcement | null>
  content: string | Ref<string>
  showCopyButton?: boolean
}

interface Emits {
  (e: 'close'): void
  (e: 'copy'): void
}

const props = withDefaults(defineProps<Props>(), {
  showCopyButton: true
})

const emit = defineEmits<Emits>()

// 解包可能的 Ref
const show = computed(() => typeof props.show === 'boolean' ? props.show : props.show.value)
const announcement = computed(() =>
  props.announcement === null || typeof props.announcement === 'object' && 'value' in props.announcement
    ? (props.announcement as Ref<Announcement | null>).value
    : props.announcement
)
const content = computed(() => typeof props.content === 'string' ? props.content : props.content.value)

// 格式化内容（支持换行）
const formattedContent = computed(() => {
  if (!content.value) return ''
  return content.value
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
})

// 禁止遮罩关闭（P0 必须"我已知晓"才能关闭）
const handleMaskClick = () => {
  // 不做任何事，禁止遮罩关闭
}

// 处理"我已知晓"
const handleAck = () => {
  emit('close')
}

// 处理复制
const handleCopy = () => {
  emit('copy')
}
</script>

<style scoped>
/* 遮罩 */
.p0-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: flex-end; /* 移动端从底部弹出 */
  justify-content: center;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  padding: 0;
  overflow: hidden;
}

/* 弹窗容器 */
.p0-modal-container {
  position: relative;
  width: 100%;
  max-width: 480px;
  max-height: 85vh;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 24px 24px 0 0;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow:
    0 -10px 40px rgba(0, 0, 0, 0.4),
    0 0 0 1px rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 顶部装饰条（amber 重要色） */
.p0-modal-top-bar {
  flex-shrink: 0;
  padding: 12px 16px 0;
}

.p0-modal-top-bar-inner {
  width: 40px;
  height: 4px;
  background: linear-gradient(90deg, #f59e0b, #fbbf24);
  border-radius: 2px;
  margin: 0 auto;
}

/* 内容区 */
.p0-modal-content {
  flex: 1;
  min-height: 0;
  padding: 16px 20px;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

/* 标题区 */
.p0-modal-header {
  margin-bottom: 16px;
}

.p0-modal-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 6px;
  color: #fbbf24;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 12px;
}

.p0-modal-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  line-height: 1.4;
}

/* 内容文本 */
.p0-modal-body {
  margin-bottom: 16px;
}

.p0-modal-text {
  font-size: 15px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.75);
  white-space: pre-wrap;
  word-break: break-word;
}

.p0-modal-text :deep(strong) {
  color: rgba(255, 255, 255, 0.95);
  font-weight: 600;
}

/* 底部按钮区（固定，带安全区域） */
.p0-modal-footer {
  flex-shrink: 0;
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  padding-bottom: max(16px, env(safe-area-inset-bottom) + 16px);
  background: rgba(0, 0, 0, 0.2);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

/* 按钮基础样式 */
.p0-modal-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 20px;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
  outline: none;
  -webkit-tap-highlight-color: transparent;
}

/* 次要按钮 */
.p0-modal-btn-secondary {
  flex: 0 0 auto;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.p0-modal-btn-secondary:active {
  background: rgba(255, 255, 255, 0.1);
  transform: scale(0.97);
}

/* 主按钮 */
.p0-modal-btn-primary {
  flex: 1;
  background: rgba(16, 185, 129, 0.16);
  color: rgba(52, 211, 153, 0.95);
  border: 1px solid rgba(52, 211, 153, 0.25);
}

.p0-modal-btn-primary:active {
  background: rgba(16, 185, 129, 0.24);
  transform: scale(0.98);
}

/* 全宽主按钮 */
.p0-modal-btn-full {
  flex: 1;
}

/* 桌面端适配 */
@media (min-width: 481px) {
  .p0-modal-overlay {
    align-items: center;
    padding: 20px;
  }

  .p0-modal-container {
    border-radius: 20px;
    max-height: 70vh;
  }

  .p0-modal-top-bar {
    display: none;
  }

  .p0-modal-content {
    padding: 24px 28px;
  }

  .p0-modal-footer {
    padding: 20px 28px;
    padding-bottom: 20px;
  }

  .p0-modal-title {
    font-size: 22px;
  }

  .p0-modal-text {
    font-size: 16px;
  }
}

/* 过渡动画 */
.p0-modal-enter-active,
.p0-modal-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.p0-modal-enter-from,
.p0-modal-leave-to {
  opacity: 0;
}

.p0-modal-enter-from .p0-modal-container,
.p0-modal-leave-to .p0-modal-container {
  transform: translateY(100%);
}

@media (min-width: 481px) {
  .p0-modal-enter-from .p0-modal-container,
  .p0-modal-leave-to .p0-modal-container {
    transform: translateY(20px) scale(0.95);
  }
}

/* 防止背景穿透滚动 */
.p0-modal-overlay {
  overscroll-behavior: contain;
}
</style>
