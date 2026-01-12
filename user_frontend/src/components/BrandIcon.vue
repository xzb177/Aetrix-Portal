<script setup lang="ts">
import { computed } from 'vue'

/**
 * BrandIcon - 统一品牌图标组件
 *
 * 设计风格：Apple TV 风格灰玻璃质感
 * - bg-white/6 + border border-white/10 + backdrop-blur-md
 * - ring-1 ring-emerald-400/20 (绿色弱点缀)
 * - text-white/85 (柔和白色图标)
 *
 * @example
 * <BrandIcon />                    // 默认 size=40
 * <BrandIcon :size="32" />          // 小尺寸
 * <BrandIcon :size="24" />          // 迷你尺寸
 */

interface Props {
  /** 图标尺寸：24/32/40，默认 40 */
  size?: 24 | 32 | 40
  /** 样式变体（预留扩展） */
  variant?: 'glass'
}

const props = withDefaults(defineProps<Props>(), {
  size: 40,
  variant: 'glass',
})

// 计算容器类名
const containerClass = computed(() => {
  const sizeClasses = {
    24: 'w-6 h-6 rounded-lg',
    32: 'w-8 h-8 rounded-xl',
    40: 'w-10 h-10 rounded-xl',
  }
  return `${sizeClasses[props.size]}`
})

// 计算图标尺寸（62.% 占比，更像 Apple TV 系统图标）
const iconSize = computed(() => {
  const iconSizes = {
    24: 15,
    32: 20,
    40: 25,
  }
  return iconSizes[props.size]
})
</script>

<template>
  <div
    class="brand-icon"
    :class="containerClass"
  >
    <!-- 品牌 SVG 图标：简洁的播放/品牌符号 -->
    <svg
      :width="iconSize"
      :height="iconSize"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="brand-icon-svg"
    >
      <!-- 播放三角形 + 圆角矩形组合（类似 Apple TV 风格） -->
      <path d="M5 3l14 9-14 9V3z" />
      <rect x="2" y="2" width="20" height="20" rx="4" opacity="0.15" />
    </svg>
  </div>
</template>

<style scoped>
.brand-icon {
  /* Apple TV 风格灰玻璃质感 */
  background-color: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);

  /* 绿色弱点缀（ring 效果） */
  box-shadow:
    0 1px 3px rgba(0, 0, 0, 0.12),
    0 0 0 1px rgba(16, 185, 129, 0.15);

  /* 居中显示图标 */
  display: flex;
  align-items: center;
  justify-content: center;

  /* 过渡效果 */
  transition: all 0.15s ease;
}

.brand-icon:active {
  transform: scale(0.96);
  background-color: rgba(255, 255, 255, 0.1);
}

.brand-icon-svg {
  color: rgba(255, 255, 255, 0.85);
  flex-shrink: 0;
}
</style>
