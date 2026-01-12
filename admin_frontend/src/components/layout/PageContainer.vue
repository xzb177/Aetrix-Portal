<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  padding?: 'none' | 'sm' | 'md' | 'lg'
  fullscreen?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  padding: 'md',
  fullscreen: false,
})

const paddingClass = computed(() => {
  const paddingMap = {
    none: 'p-0',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6',
  }
  return paddingMap[props.padding]
})
</script>

<template>
  <div
    class="page-container"
    :class="[
      paddingClass,
      { 'page-container-fullscreen': fullscreen },
    ]"
  >
    <slot />
  </div>
</template>

<style scoped>
.page-container {
  min-height: 100%;
  width: 100%;
  max-width: 100%;
  background: var(--bg-base);
}

.page-container-fullscreen {
  height: 100vh;
  overflow-y: auto;
}
</style>
