<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  status: 'success' | 'warning' | 'danger' | 'info' | 'disabled'
  label?: string
  size?: 'sm' | 'md'
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
})

const statusConfig = {
  success: { label: '启用', class: 'bg-success-bg text-success' },
  warning: { label: '警告', class: 'bg-warning-bg text-warning' },
  danger: { label: '禁用', class: 'bg-danger-bg text-danger' },
  info: { label: '信息', class: 'bg-info-bg text-info' },
  disabled: { label: '禁用', class: 'bg-white/5 text-text-tertiary' },
}

const config = computed(() => statusConfig[props.status])
const displayLabel = computed(() => props.label || config.value.label)
</script>

<template>
  <span
    class="inline-flex items-center justify-center font-medium rounded-md transition-colors"
    :class="[
      config.class,
      size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs'
    ]"
  >
    {{ displayLabel }}
  </span>
</template>
