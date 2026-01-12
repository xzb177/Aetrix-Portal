<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Search, X } from 'lucide-vue-next'

interface Props {
  modelValue?: string
  placeholder?: string
  clearable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: '搜索...',
  clearable: true,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'search', value: string): void
  (e: 'clear'): void
}>()

const localValue = ref(props.modelValue || '')

watch(() => props.modelValue, (newVal) => {
  localValue.value = newVal || ''
})

const handleInput = (e: Event) => {
  const value = (e.target as HTMLInputElement).value
  localValue.value = value
  emit('update:modelValue', value)
}

const handleClear = () => {
  localValue.value = ''
  emit('update:modelValue', '')
  emit('clear')
}

const showClear = computed(() => props.clearable && localValue.value.length > 0)
</script>

<template>
  <div class="search-bar">
    <Search :size="18" class="search-icon" />
    <input
      :value="localValue"
      :placeholder="placeholder"
      class="search-input"
      @input="handleInput"
      @keyup.enter="emit('search', localValue)"
    />
    <button
      v-if="showClear"
      class="search-clear"
      @click="handleClear"
    >
      <X :size="16" />
    </button>
  </div>
</template>

<style scoped>
.search-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 44px;
  padding: 0 var(--space-3);
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast) ease;
}

.search-bar:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--primary-bg);
}

.search-icon {
  flex-shrink: 0;
  color: var(--text-tertiary);
}

.search-input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.search-clear {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.search-clear:active {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}
</style>
