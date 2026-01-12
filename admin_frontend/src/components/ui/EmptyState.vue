<script setup lang="ts">
interface Props {
  icon?: string
  title?: string
  description?: string
  actionLabel?: string
}

withDefaults(defineProps<Props>(), {
  title: '暂无数据',
  description: '没有找到相关内容',
})

const emit = defineEmits<{
  action: []
}>()
</script>

<template>
  <div class="py-16 flex flex-col items-center justify-center">
    <!-- 图标 -->
    <div class="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mb-4">
      <svg v-if="icon" class="w-8 h-8 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <use :xlink:href="`#${icon}`" />
      </svg>
      <svg v-else class="w-8 h-8 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
      </svg>
    </div>

    <!-- 标题 -->
    <p class="text-text-primary text-sm font-medium mb-1">{{ title }}</p>
    <p v-if="description" class="text-text-secondary text-sm mb-4">{{ description }}</p>

    <!-- 操作按钮 -->
    <button
      v-if="actionLabel"
      @click="emit('action')"
      class="px-4 py-2 text-sm text-primary hover:bg-primary/10 rounded-lg touch-feedback transition-colors"
    >
      {{ actionLabel }}
    </button>

    <!-- 插槽 -->
    <slot />
  </div>
</template>
