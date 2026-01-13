<script setup lang="ts">
/**
 * 分类筛选组件
 *
 * 用于筛选海报墙的求片请求
 */
import { computed } from 'vue'
import { ChevronDown, Flame, Clock, CheckCircle } from 'lucide-vue-next'

export interface FilterOptions {
  status: string
  type: string
  sort: string
}

interface Props {
  modelValue: FilterOptions
  stats?: {
    total: number
    pending: number
    approved: number
    completed: number
    by_type: Record<string, number>
  }
}

interface Emits {
  (e: 'update:modelValue', value: FilterOptions): void
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: () => ({ status: '', type: '', sort: 'hot' }),
  stats: () => ({ total: 0, pending: 0, approved: 0, completed: 0, by_type: {} }),
})

const emit = defineEmits<Emits>()

// 状态选项
const statusOptions = [
  { value: '', label: '全部', icon: null },
  { value: 'pending', label: '待处理', icon: Clock },
  { value: 'approved', label: '处理中', icon: null },
  { value: 'completed', label: '已完成', icon: CheckCircle },
]

const typeOptions = [
  { value: '', label: '全部类型' },
  { value: 'movie', label: '电影' },
  { value: 'series', label: '剧集' },
  { value: 'anime', label: '动漫' },
  { value: 'documentary', label: '纪录片' },
]

const sortOptions = [
  { value: 'hot', label: '热度优先', icon: Flame },
  { value: 'latest', label: '最新发布', icon: null },
]

// 当前选择的标签
const currentStatusLabel = computed(() => {
  return statusOptions.find(o => o.value === props.modelValue.status)?.label || '全部'
})

const currentTypeLabel = computed(() => {
  return typeOptions.find(o => o.value === props.modelValue.type)?.label || '全部类型'
})

const currentSortLabel = computed(() => {
  return sortOptions.find(o => o.value === props.modelValue.sort)?.label || '热度优先'
})

// 是否有激活的筛选
const hasActiveFilter = computed(() => {
  return props.modelValue.status !== '' || props.modelValue.type !== ''
})

// 更新筛选
const updateFilter = (key: keyof FilterOptions, value: string) => {
  emit('update:modelValue', {
    ...props.modelValue,
    [key]: value
  })
}

// 清除筛选
const clearFilters = () => {
  emit('update:modelValue', {
    status: '',
    type: '',
    sort: props.modelValue.sort
  })
}
</script>

<template>
  <div class="category-filter">
    <!-- 筛选标签栏 -->
    <div class="filter-tabs">
      <!-- 状态筛选 -->
      <div class="filter-group">
        <div class="filter-label">状态</div>
        <div class="filter-chips">
          <button
            v-for="option in statusOptions"
            :key="option.value"
            :class="['filter-chip', { active: modelValue.status === option.value }]"
            @click="updateFilter('status', option.value)"
          >
            <component v-if="option.icon" :is="option.icon" :size="12" />
            <span>{{ option.label }}</span>
            <span v-if="option.value && stats" class="chip-count">
              {{ stats[option.value as keyof typeof stats] || 0 }}
            </span>
          </button>
        </div>
      </div>

      <!-- 类型筛选 -->
      <div class="filter-group">
        <div class="filter-label">类型</div>
        <div class="filter-chips">
          <button
            v-for="option in typeOptions"
            :key="option.value"
            :class="['filter-chip', { active: modelValue.type === option.value }]"
            @click="updateFilter('type', option.value)"
          >
            <span>{{ option.label }}</span>
            <span v-if="option.value && stats?.by_type" class="chip-count">
              {{ stats.by_type[option.value] || 0 }}
            </span>
          </button>
        </div>
      </div>
    </div>

    <!-- 排序和清除 -->
    <div class="filter-actions">
      <!-- 排序选择 -->
      <button
        :class="['sort-btn', { active: modelValue.sort === 'hot' }]"
        @click="updateFilter('sort', modelValue.sort === 'hot' ? 'latest' : 'hot')"
      >
        <Flame :size="14" :class="{ 'text-amber-400': modelValue.sort === 'hot' }" />
        <span>{{ currentSortLabel }}</span>
      </button>

      <!-- 清除筛选 -->
      <button
        v-if="hasActiveFilter"
        class="clear-btn"
        @click="clearFilters"
      >
        清除筛选
      </button>
    </div>
  </div>
</template>

<style scoped>
.category-filter {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding-bottom: 0.75rem;
}

/* ==================== 筛选标签栏 ==================== */
.filter-tabs {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.filter-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.5);
  padding-left: 0.25rem;
}

.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.5rem;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.813rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.filter-chip:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.8);
}

.filter-chip.active {
  background: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.3);
  color: rgba(52, 211, 153, 0.9);
}

.chip-count {
  font-size: 0.688rem;
  padding: 0.125rem 0.375rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  color: rgba(255, 255, 255, 0.5);
}

.filter-chip.active .chip-count {
  background: rgba(16, 185, 129, 0.2);
  color: rgba(52, 211, 153, 0.8);
}

/* ==================== 筛选操作栏 ==================== */
.filter-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.sort-btn {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.5rem;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.813rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.sort-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.8);
}

.sort-btn.active {
  background: rgba(251, 146, 60, 0.1);
  border-color: rgba(251, 146, 60, 0.25);
  color: rgba(251, 146, 60, 0.9);
}

.clear-btn {
  padding: 0.5rem 0.75rem;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.5rem;
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.clear-btn:hover {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.25);
  color: rgba(248, 113, 113, 0.9);
}

/* ==================== 响应式 ==================== */
@media (max-width: 480px) {
  .filter-chips {
    gap: 0.25rem;
  }

  .filter-chip {
    padding: 0.375rem 0.5rem;
    font-size: 0.75rem;
  }

  .sort-btn {
    font-size: 0.75rem;
    padding: 0.375rem 0.625rem;
  }
}
</style>
