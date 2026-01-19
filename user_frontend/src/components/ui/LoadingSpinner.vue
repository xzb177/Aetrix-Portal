<template>
  <div :class="['loading-spinner', `loading-spinner--${size}`, { 'loading-spinner--brand': brand }]">
    <svg class="loading-spinner__svg" viewBox="0 0 50 50">
      <circle
        class="loading-spinner__track"
        cx="25"
        cy="25"
        r="20"
        fill="none"
        stroke-width="4"
      />
      <circle
        class="loading-spinner__indicator"
        cx="25"
        cy="25"
        r="20"
        fill="none"
        stroke-width="4"
        stroke-linecap="round"
      />
    </svg>
  </div>
</template>

<script setup lang="ts">
export type LoadingSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

export interface LoadingSpinnerProps {
  size?: LoadingSize
  brand?: boolean
}

withDefaults(defineProps<LoadingSpinnerProps>(), {
  size: 'md',
  brand: false
})
</script>

<style scoped>
.loading-spinner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.loading-spinner--xs { width: 16px; height: 16px; }
.loading-spinner--sm { width: 20px; height: 20px; }
.loading-spinner--md { width: 28px; height: 28px; }
.loading-spinner--lg { width: 40px; height: 40px; }
.loading-spinner--xl { width: 56px; height: 56px; }

.loading-spinner__svg {
  width: 100%;
  height: 100%;
  animation: spin 0.8s linear infinite;
}

.loading-spinner__track {
  stroke: var(--border-default);
}

.loading-spinner__indicator {
  stroke: var(--color-info, #3b82f6);
  stroke-dasharray: 90 150;
  stroke-dashoffset: 0;
  animation: spinner-dash 1.5s ease-in-out infinite;
}

.loading-spinner--brand .loading-spinner__indicator {
  stroke: var(--brand-primary);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes spinner-dash {
  0% {
    stroke-dasharray: 1 150;
    stroke-dashoffset: 0;
  }
  50% {
    stroke-dasharray: 90 150;
    stroke-dashoffset: -35;
  }
  100% {
    stroke-dasharray: 90 150;
    stroke-dashoffset: -124;
  }
}
</style>
