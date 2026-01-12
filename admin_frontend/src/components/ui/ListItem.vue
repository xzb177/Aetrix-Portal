<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  title: string
  subtitle?: string
  icon?: string
  status?: string
  statusType?: 'success' | 'warning' | 'danger' | 'info'
  showArrow?: boolean
  clickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showArrow: true,
  clickable: true,
})

const emit = defineEmits<{
  click: []
}>()

const statusClass = computed(() => {
  if (!props.status) return ''
  const type = props.statusType || 'info'
  const classes = {
    success: 'px-2.5 py-1 rounded-md text-xs font-medium bg-success-bg text-success',
    warning: 'px-2.5 py-1 rounded-md text-xs font-medium bg-warning-bg text-warning',
    danger: 'px-2.5 py-1 rounded-md text-xs font-medium bg-danger-bg text-danger',
    info: 'px-2.5 py-1 rounded-md text-xs font-medium bg-info-bg text-info',
  }
  return classes[type]
})

function handleClick() {
  if (props.clickable) {
    emit('click')
  }
}
</script>

<template>
  <div
    class="bg-bg-card rounded-xl border border-white/8 p-3 flex items-center gap-3 min-h-[52px] transition-colors touch-feedback"
    :class="[
      clickable ? 'cursor-pointer hover:bg-bg-card-hover' : '',
      clickable ? 'active:scale-[0.99]' : ''
    ]"
    @click="handleClick"
  >
    <!-- 左图标 -->
    <div v-if="icon" class="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0">
      <svg class="w-5 h-5 text-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <use :xlink:href="`#${icon}`" />
      </svg>
    </div>

    <!-- 插槽图标 -->
    <div v-else-if="$slots.icon" class="w-10 h-10 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0">
      <slot name="icon" />
    </div>

    <!-- 内容区 -->
    <div class="flex-1 min-w-0">
      <h4 class="text-sm font-medium text-text-primary truncate">{{ title }}</h4>
      <p v-if="subtitle" class="text-xs text-text-secondary truncate">{{ subtitle }}</p>
      <slot name="content" />
    </div>

    <!-- 右侧插槽 -->
    <div v-if="$slots.right" class="flex items-center gap-2 flex-shrink-0">
      <slot name="right" />
    </div>

    <!-- 右侧状态/箭头 -->
    <div v-else class="flex items-center gap-2 flex-shrink-0">
      <span v-if="status" :class="statusClass">{{ status }}</span>
      <svg v-if="showArrow" class="w-5 h-5 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
      </svg>
    </div>
  </div>
</template>
