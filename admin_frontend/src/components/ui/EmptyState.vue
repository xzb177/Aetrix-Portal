<script setup lang="ts">
/**
 * 空状态（暗房影院 .au-empty）：淡色图标 + 衬线一句话 + 灰色说明 + 可选操作。
 * compact：嵌在卡片 / 表格里用（上下留白收小）。用法见 ./README.md。
 */
withDefaults(
  defineProps<{
    title: string
    description?: string
    /** lucide 组件本身；不传就不显示图标 */
    icon?: unknown
    compact?: boolean
  }>(),
  { description: '', icon: undefined, compact: false },
)
</script>

<template>
  <div class="au-empty-state" :class="{ 'is-compact': compact }" role="status">
    <span v-if="icon" class="au-empty-state__icon">
      <component :is="icon" :size="compact ? 20 : 26" />
    </span>
    <p class="au-empty-state__title">{{ title }}</p>
    <p v-if="description || $slots.description" class="au-empty-state__desc">
      <slot name="description">{{ description }}</slot>
    </p>
    <div v-if="$slots.actions" class="au-empty-state__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.au-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 48px 16px;
  text-align: center;
  color: var(--au-text-3);
}

.au-empty-state.is-compact { padding: 22px 12px; }

.au-empty-state__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  margin-bottom: 6px;
  border-radius: var(--au-r-full);
  border: 1px solid var(--au-border);
  background: var(--au-surface-2);
  color: var(--au-text-4);
}

.is-compact .au-empty-state__icon { width: 40px; height: 40px; margin-bottom: 2px; }

.au-empty-state__title {
  margin: 0;
  font-family: var(--au-font-serif);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--au-text-2);
}

.is-compact .au-empty-state__title { font-size: 13.5px; }

.au-empty-state__desc {
  margin: 0;
  max-width: 46ch;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--au-text-3);
}

.au-empty-state__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 10px;
}
</style>
