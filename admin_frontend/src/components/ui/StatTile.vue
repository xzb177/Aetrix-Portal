<script setup lang="ts">
interface Props {
  value: string | number
  label: string
  icon?: string
  iconColor?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  trend?: string
  trendUp?: boolean
  loading?: boolean
}

withDefaults(defineProps<Props>(), {
  iconColor: 'primary',
  trendUp: true,
  loading: false,
})
</script>

<template>
  <div class="bg-bg-card rounded-2xl border border-white/8 p-4 transition-all hover:bg-bg-card-hover">
    <div class="flex items-center gap-3">
      <!-- 图标 -->
      <div
        v-if="icon"
        class="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0"
        :class="{
          'bg-primary/10 text-primary': iconColor === 'primary',
          'bg-success-bg text-success': iconColor === 'success',
          'bg-warning-bg text-warning': iconColor === 'warning',
          'bg-danger-bg text-danger': iconColor === 'danger',
          'bg-info-bg text-info': iconColor === 'info',
        }"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <use :xlink:href="`#${icon}`" />
        </svg>
      </div>

      <!-- 插槽图标 -->
      <div
        v-else-if="$slots.icon"
        class="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 bg-white/5"
      >
        <slot name="icon" />
      </div>

      <!-- 数据 -->
      <div class="flex-1">
        <p v-if="loading" class="text-2xl font-semibold text-text-primary animate-pulse">--</p>
        <p v-else class="text-2xl font-semibold text-text-primary">{{ value }}</p>
        <p class="text-xs text-text-secondary">{{ label }}</p>
      </div>

      <!-- 趋势 -->
      <div
        v-if="trend && !loading"
        class="flex items-center gap-1 text-xs"
        :class="{
          'text-success': trendUp,
          'text-danger': !trendUp,
        }"
      >
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path v-if="trendUp" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
          <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
        <span>{{ trend }}</span>
      </div>
    </div>

    <!-- 底部插槽 -->
    <div v-if="$slots.footer" class="mt-3 pt-3 border-t border-white/8">
      <slot name="footer" />
    </div>
  </div>
</template>
