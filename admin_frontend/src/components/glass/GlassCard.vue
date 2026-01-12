<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  padding?: 'none' | 'sm' | 'md' | 'lg'
  radius?: 'sm' | 'md' | 'lg'
  shadow?: 'none' | 'sm' | 'md' | 'lg'
  blur?: boolean
  clickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  padding: 'md',
  radius: 'md',
  shadow: 'sm',
  blur: true,
  clickable: false,
})

const emit = defineEmits<{
  click: []
}>()

const paddingClass = computed(() => {
  const paddingMap = {
    none: 'p-0',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6',
  }
  return paddingMap[props.padding]
})

const radiusClass = computed(() => {
  const radiusMap = {
    sm: 'rounded-xl',
    md: 'rounded-2xl',
    lg: 'rounded-3xl',
  }
  return radiusMap[props.radius]
})

const shadowClass = computed(() => {
  const shadowMap = {
    none: '',
    sm: 'shadow-sm',
    md: 'shadow-md',
    lg: 'shadow-lg',
  }
  return shadowMap[props.shadow]
})

const blurClass = computed(() => {
  return props.blur ? 'backdrop-blur-xl' : ''
})

const clickableClass = computed(() => {
  return props.clickable
    ? 'cursor-pointer active:scale-[0.99] hover:border-white/12'
    : ''
})

function handleClick() {
  if (props.clickable) {
    emit('click')
  }
}
</script>

<template>
  <div
    class="glass-card-base"
    :class="[
      paddingClass,
      radiusClass,
      shadowClass,
      blurClass,
      clickableClass,
    ]"
    @click="handleClick"
  >
    <slot />
  </div>
</template>

<style scoped>
.glass-card-base {
  background: rgba(20, 21, 26, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition: all 250ms ease;
}
</style>
