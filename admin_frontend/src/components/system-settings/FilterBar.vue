<!--
  FilterBar.vue
  Apple TV 风格系统配置页面 - 搜索和过滤栏

  功能：
  - 搜索框：支持按中文名/key/描述模糊搜索
  - 开关：仅显示已修改的配置
-->
<script setup lang="ts">
interface Props {
  modelValue: string
  showModified: boolean
}

interface Emits {
  (e: 'update:modelValue', value: string): void
  (e: 'update:showModified', value: boolean): void
}

defineProps<Props>()
const emit = defineEmits<Emits>()

const handleInput = (e: Event) => {
  emit('update:modelValue', (e.target as HTMLInputElement).value)
}
</script>

<template>
  <div class="filter-bar">
    <!-- 搜索框 -->
    <div class="search-wrapper">
      <svg class="search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <input
        :value="modelValue"
        @input="handleInput"
        type="text"
        placeholder="搜索配置项（名称 / key / 描述）"
        class="search-input"
      />
      <button
        v-if="modelValue"
        @click="$emit('update:modelValue', '')"
        class="search-clear touch-feedback"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M10.5 3.5L3.5 10.5M3.5 3.5L10.5 10.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </button>
    </div>

    <!-- 仅显示已修改开关 -->
    <button
      class="filter-toggle"
      :class="{ active: showModified }"
      @click="emit('update:showModified', !showModified)"
    >
      <span class="toggle-dot" :class="{ active: showModified }"></span>
      仅显示已修改
    </button>
  </div>
</template>

<style scoped>
.filter-bar {
  position: sticky;
  top: 56px;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background-color: var(--bg-base);
  border-bottom: 1px solid var(--border-base);
}

/* 搜索框容器 */
.search-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}

/* 搜索图标 */
.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 18px;
  height: 18px;
  color: var(--text-tertiary);
  pointer-events: none;
  flex-shrink: 0;
}

/* 搜索输入框 */
.search-input {
  width: 100%;
  height: 44px;
  padding: 0 40px 0 40px;
  font-size: 15px;
  color: var(--text-primary);
  background-color: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  outline: none;
  transition: all var(--transition-base) ease;
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.search-input:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

/* 清除按钮 */
.search-clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.search-clear:hover {
  color: var(--text-primary);
  background-color: var(--bg-card-hover);
}

/* 过滤开关 */
.filter-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  height: 44px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-tertiary);
  background-color: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--transition-base) ease;
}

.filter-toggle:hover {
  border-color: var(--border-strong);
  color: var(--text-secondary);
}

.filter-toggle.active {
  color: var(--warning);
  border-color: var(--warning);
  background-color: var(--warning-bg);
}

/* 开关指示点 */
.toggle-dot {
  width: 8px;
  height: 8px;
  background-color: var(--bg-card-hover);
  border-radius: 50%;
  transition: all var(--transition-base) ease;
}

.toggle-dot.active {
  background-color: var(--warning);
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.5);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .filter-bar {
    top: 50px;
    flex-wrap: wrap;
    padding: 8px 12px;
  }

  .search-wrapper {
    width: 100%;
    order: 1;
  }

  .search-input {
    height: 40px;
    font-size: 14px;
  }

  .filter-toggle {
    order: 2;
    height: 36px;
    padding: 0 12px;
    font-size: 13px;
  }
}
</style>
