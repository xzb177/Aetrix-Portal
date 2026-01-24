<script setup lang="ts">
/**
 * Neo-Glass CTA 按钮 - 深海极光签名瞬间
 *
 * 动效说明：
 * - 常态：深海玻璃按钮（暗色透明+细描边+轻微内阴影）
 * - 交互：按下时极光薄雾从左扫过 + 点击点波纹扩散
 * - 克制：低亮度、大模糊、短时长
 *
 * @props
 * - size: 尺寸 ('md' | 'sm' | 'lg')
 * - block: 是否块级
 * - disabled: 是否禁用
 * - glow: 是否增强发光（谨慎使用）
 */

interface Props {
  size?: 'sm' | 'md' | 'lg'
  block?: boolean
  disabled?: boolean
  glow?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  block: false,
  disabled: false,
  glow: false
})
</script>

<template>
  <button
    type="button"
    :class="[
      'neo-cta',
      `neo-cta--${size}`,
      {
        'neo-cta--block': block,
        'neo-cta--glow': glow
      }
    ]"
    :disabled="disabled"
  >
    <slot />
  </button>
</template>

<style scoped>
/* 组件使用外部 neo-cta-aurora.css 的样式 */
/* 这里可以添加组件特定的覆盖样式 */

/* 确保禁用状态下文字也有正确的颜色 */
.neo-cta:disabled {
  color: rgba(255, 255, 255, 0.5);
}

/* 加载状态（可选扩展） */
.neo-cta.loading {
  pointer-events: none;
}

.neo-cta.loading::before {
  animation: neo-cta-pulse 1.5s ease-in-out infinite;
}

@keyframes neo-cta-pulse {
  0%, 100% {
    opacity: 0;
  }
  50% {
    opacity: 0.3;
  }
}
</style>
