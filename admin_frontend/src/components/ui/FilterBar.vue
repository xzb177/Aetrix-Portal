<script setup lang="ts">
import { ref, computed } from 'vue'

interface FilterChip {
  id: string
  label: string
  count?: number
}

interface Props {
  chips: FilterChip[]
  searchPlaceholder?: string
  showCount?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  searchPlaceholder: '搜索...',
  showCount: true,
})

const emit = defineEmits<{
  filter: [id: string]
  search: [value: string]
}>()

const selectedFilter = ref<string>('all')
const searchValue = ref('')

const displayChips = computed(() => {
  return props.chips.map(chip => ({
    ...chip,
    isActive: selectedFilter.value === chip.id,
  }))
})

function selectFilter(id: string) {
  selectedFilter.value = id
  emit('filter', id)
}

function handleSearch() {
  emit('search', searchValue.value)
}
</script>

<template>
  <div class="space-y-3">
    <!-- 搜索框 -->
    <div class="relative">
      <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <input
        v-model="searchValue"
        @keyup.enter="handleSearch"
        type="search"
        :placeholder="searchPlaceholder"
        class="w-full h-11 pl-11 pr-4 bg-bg-input rounded-xl border border-white/8 text-sm text-text-primary placeholder-text-tertiary focus:outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/20 transition-all"
      />
      <button
        v-if="searchValue"
        @click="searchValue = ''; emit('search', '')"
        class="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full bg-white/10 hover:bg-white/15 touch-feedback"
      >
        <svg class="w-4 h-4 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- 筛选 Chips -->
    <div class="flex gap-2 overflow-x-auto scrollbar-hide -mx-4 px-4">
      <button
        v-for="chip in displayChips"
        :key="chip.id"
        @click="selectFilter(chip.id)"
        class="px-4 py-2 rounded-full text-sm font-medium touch-feedback transition-all whitespace-nowrap"
        :class="chip.isActive
          ? 'bg-primary text-primary-on shadow-lg shadow-primary/25'
          : 'bg-bg-card text-text-secondary hover:bg-white/5'
        "
      >
        {{ chip.label }}
        <span v-if="showCount && chip.count !== undefined" class="ml-1.5 px-1.5 py-0.5 rounded text-xs"
          :class="chip.isActive ? 'bg-white/20' : 'bg-white/10'"
        >
          {{ chip.count }}
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
</style>
