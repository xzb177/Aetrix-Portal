<script setup lang="ts">
interface Props {
  count?: number
  saving?: boolean
}

withDefaults(defineProps<Props>(), {
  saving: false,
})

const emit = defineEmits<{
  save: []
  discard: []
  export: []
}>()
</script>

<template>
  <!-- Sticky 保存条 -->
  <Transition name="slide-up">
    <div
      class="fixed bottom-16 left-0 right-0 z-30 px-4 py-3 bg-bg-card/95 backdrop-blur-md border-t border-white/8 safe-area-bottom-shadow"
    >
      <div class="flex items-center justify-between max-w-lg mx-auto">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-warning animate-pulse" />
          <span class="text-sm text-text-secondary">
            已修改 <span class="font-semibold text-warning">{{ count }}</span> 项
          </span>
        </div>
        <div class="flex items-center gap-2">
          <button
            @click="emit('discard')"
            class="px-4 py-2.5 text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-white/5 rounded-xl touch-feedback transition-colors"
          >
            放弃
          </button>
          <button
            @click="emit('export')"
            class="px-4 py-2.5 text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-white/5 rounded-xl touch-feedback transition-colors"
          >
            导出
          </button>
          <button
            @click="emit('save')"
            :disabled="saving"
            class="px-5 py-2.5 text-sm font-medium text-white bg-primary hover:bg-primary-hover active:bg-primary-active rounded-xl touch-feedback shadow-lg shadow-primary/25 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span v-if="saving" class="flex items-center gap-2">
              <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              保存中
            </span>
            <span v-else>保存更改</span>
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.safe-area-bottom-shadow {
  padding-bottom: calc(12px + max(env(safe-area-inset-bottom), 8px));
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.4);
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.3s ease, opacity 0.3s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}
</style>
