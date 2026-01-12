<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Search, SlidersHorizontal, X, ChevronDown } from 'lucide-vue-next'

export interface FilterOptions {
  keyword: string
  is_vip_only: boolean
  status?: 'all' | 'active' | 'inactive'
  time_range?: 'all' | 'today' | 'week' | 'month'
}

interface Props {
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
})

const emit = defineEmits<{
  search: [filters: FilterOptions]
  reset: []
}>()

// 筛选条件
const filters = ref<FilterOptions>({
  keyword: '',
  is_vip_only: false,
  status: 'all',
  time_range: 'all',
})

// 是否展开筛选面板
const expanded = ref(false)

// 是否有生效的筛选条件
const hasActiveFilters = computed(() => {
  return filters.value.keyword ||
         filters.value.is_vip_only ||
         filters.value.status !== 'all' ||
         filters.value.time_range !== 'all'
})

// 当前激活的筛选 chips
const activeChips = computed(() => {
  const chips: Array<{ key: string; label: string; value: any }> = []

  if (filters.value.keyword) {
    chips.push({ key: 'keyword', label: `搜索: ${filters.value.keyword}`, value: filters.value.keyword })
  }
  if (filters.value.is_vip_only) {
    chips.push({ key: 'vip', label: '仅 VIP', value: true })
  }
  if (filters.value.status === 'active') {
    chips.push({ key: 'status', label: '活跃', value: 'active' })
  } else if (filters.value.status === 'inactive') {
    chips.push({ key: 'status', label: '禁用', value: 'inactive' })
  }
  if (filters.value.time_range === 'today') {
    chips.push({ key: 'time', label: '今天', value: 'today' })
  } else if (filters.value.time_range === 'week') {
    chips.push({ key: 'time', label: '近7天', value: 'week' })
  } else if (filters.value.time_range === 'month') {
    chips.push({ key: 'time', label: '近30天', value: 'month' })
  }

  return chips
})

// 状态选项
const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'active', label: '活跃' },
  { value: 'inactive', label: '禁用' },
]

// 时间范围选项
const timeOptions = [
  { value: 'all', label: '全部时间' },
  { value: 'today', label: '今天' },
  { value: 'week', label: '近7天' },
  { value: 'month', label: '近30天' },
]

// 执行搜索
const handleSearch = () => {
  emit('search', { ...filters.value })
  expanded.value = false
}

// 重置筛选
const handleReset = () => {
  filters.value = {
    keyword: '',
    is_vip_only: false,
    status: 'all',
    time_range: 'all',
  }
  emit('reset')
}

// 删除单个 chip
const removeChip = (key: string) => {
  switch (key) {
    case 'keyword':
      filters.value.keyword = ''
      break
    case 'vip':
      filters.value.is_vip_only = false
      break
    case 'status':
      filters.value.status = 'all'
      break
    case 'time':
      filters.value.time_range = 'all'
      break
  }
  emit('search', { ...filters.value })
}

// 切换展开状态
const toggleExpand = () => {
  expanded.value = !expanded.value
}

// 监听回车键
const handleKeyup = (e: KeyboardEvent) => {
  if (e.key === 'Enter') {
    handleSearch()
  }
}
</script>

<template>
  <div class="filter-bar">
    <!-- 默认状态：搜索框 + 筛选按钮 -->
    <div class="filter-main">
      <div class="search-input-wrapper">
        <Search :size="18" class="search-icon" />
        <input
          v-model="filters.keyword"
          type="text"
          placeholder="搜索用户名或邮箱..."
          class="search-input"
          @keyup.enter="handleSearch"
        />
        <button
          v-if="filters.keyword"
          class="clear-btn"
          @click="filters.keyword = ''"
        >
          <X :size="16" />
        </button>
      </div>

      <button
        :class="['filter-toggle', { 'filter-active': hasActiveFilters }]"
        @click="toggleExpand"
      >
        <SlidersHorizontal :size="18" />
        <span v-if="hasActiveFilters" class="filter-badge">{{ activeChips.length }}</span>
      </button>

      <button
        :class="['search-btn', { 'search-btn-loading': loading }]"
        :disabled="loading"
        @click="handleSearch"
      >
        <Search :size="18" />
      </button>
    </div>

    <!-- 展开的筛选面板 -->
    <Transition name="expand">
      <div v-show="expanded" class="filter-panel">
        <div class="filter-row">
          <!-- VIP 筛选 -->
          <div class="filter-option">
            <label class="checkbox-label">
              <input
                v-model="filters.is_vip_only"
                type="checkbox"
                class="checkbox"
              />
              <span class="checkbox-text">仅 VIP 用户</span>
            </label>
          </div>

          <!-- 状态筛选 -->
          <div class="filter-option">
            <select v-model="filters.status" class="filter-select">
              <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <!-- 时间范围 -->
          <div class="filter-option">
            <select v-model="filters.time_range" class="filter-select">
              <option v-for="opt in timeOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>

        <div class="filter-actions">
          <button class="action-btn action-btn-reset" @click="handleReset">
            <X :size="16" />
            重置
          </button>
          <button class="action-btn action-btn-submit" @click="handleSearch">
            <Search :size="16" />
            应用筛选
          </button>
        </div>
      </div>
    </Transition>

    <!-- 激活的筛选 chips -->
    <Transition name="chips">
      <div v-if="activeChips.length > 0" class="filter-chips">
        <div
          v-for="chip in activeChips"
          :key="chip.key"
          class="filter-chip"
          @click="removeChip(chip.key)"
        >
          <span>{{ chip.label }}</span>
          <X :size="12" />
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 主搜索栏 */
.filter-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input-wrapper {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 14px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.search-input {
  width: 100%;
  height: 44px;
  padding: 0 44px 0 44px;
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  font-size: 15px;
  color: var(--text-primary);
  outline: none;
  transition: all 150ms ease;
}

.search-input:focus {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.clear-btn {
  position: absolute;
  right: 10px;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: none;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 150ms ease;
}

.clear-btn:active {
  background: rgba(255, 255, 255, 0.15);
  transform: scale(0.9);
}

.filter-toggle {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  border: none;
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 150ms ease;
}

.filter-toggle:active {
  background: rgba(255, 255, 255, 0.05);
  transform: scale(0.95);
}

.filter-toggle.filter-active {
  border-color: rgba(99, 102, 241, 0.5);
  color: #6366f1;
}

.filter-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #6366f1;
  color: white;
  font-size: 10px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.search-btn {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  border: none;
  background: #6366f1;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 150ms ease;
}

.search-btn:active {
  background: #4f46e5;
  transform: scale(0.95);
}

.search-btn.search-btn-loading svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 筛选面板 */
.filter-panel {
  padding: 16px;
  background: rgba(20, 21, 26, 0.5);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
}

.filter-option {
  flex: 1;
  min-width: 120px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  transition: background 150ms ease;
}

.checkbox-label:active {
  background: rgba(255, 255, 255, 0.06);
}

.checkbox {
  appearance: none;
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  position: relative;
  transition: all 150ms ease;
}

.checkbox:checked {
  background: #6366f1;
  border-color: #6366f1;
}

.checkbox:checked::after {
  content: '';
  position: absolute;
  left: 5px;
  top: 2px;
  width: 6px;
  height: 10px;
  border: solid white;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

.checkbox-text {
  font-size: 14px;
  color: var(--text-primary);
}

.filter-select {
  width: 100%;
  height: 44px;
  padding: 0 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  font-size: 14px;
  color: var(--text-primary);
  cursor: pointer;
  outline: none;
  transition: all 150ms ease;
}

.filter-select:focus {
  border-color: rgba(99, 102, 241, 0.5);
}

.filter-actions {
  display: flex;
  gap: 10px;
}

.action-btn {
  flex: 1;
  height: 40px;
  border-radius: 10px;
  border: none;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: all 150ms ease;
}

.action-btn-reset {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
}

.action-btn-reset:active {
  background: rgba(255, 255, 255, 0.08);
}

.action-btn-submit {
  background: #6366f1;
  color: white;
}

.action-btn-submit:active {
  background: #4f46e5;
}

/* Chips */
.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 8px;
  font-size: 13px;
  color: #6366f1;
  cursor: pointer;
  transition: all 150ms ease;
}

.filter-chip:active {
  background: rgba(99, 102, 241, 0.2);
  transform: scale(0.95);
}

.filter-chip svg {
  flex-shrink: 0;
}

/* 展开/折叠动画 */
.expand-enter-active,
.expand-leave-active {
  overflow: hidden;
  transition: all 250ms ease;
}

.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
  margin-top: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 300px;
  opacity: 1;
  margin-top: 0;
}

.chips-enter-active,
.chips-leave-active {
  transition: all 200ms ease;
}

.chips-enter-from,
.chips-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.chips-enter-to,
.chips-leave-from {
  opacity: 1;
  transform: translateY(0);
}
</style>
