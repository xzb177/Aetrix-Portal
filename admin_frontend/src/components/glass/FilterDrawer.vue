<script setup lang="ts">
import { ref, watch } from 'vue'

export interface FilterOption {
  label: string
  value: string | number | boolean
}

export interface FilterItem {
  key: string
  label: string
  type: 'input' | 'select' | 'date' | 'checkbox' | 'radio'
  placeholder?: string
  options?: FilterOption[]
  value?: any
}

interface Props {
  modelValue: boolean
  title?: string
  items: FilterItem[]
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: '筛选条件',
  loading: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'filter': [data: Record<string, any>]
  'reset': []
}>()

// 本地表单数据
const formData = ref<Record<string, any>>({})

// 监听抽屉打开，初始化表单数据
watch(() => props.modelValue, (open: boolean) => {
  if (open) {
    // 从 items 初始化表单数据
    formData.value = {}
    props.items.forEach(item => {
      if (item.value !== undefined) {
        formData.value[item.key] = item.value
      }
    })
  }
})

function handleClose() {
  emit('update:modelValue', false)
}

function handleReset() {
  formData.value = {}
  emit('reset')
}

function handleFilter() {
  emit('filter', { ...formData.value })
  handleClose()
}

function handleOverlayClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('drawer-overlay')) {
    handleClose()
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-300"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-300"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="modelValue"
        class="drawer-overlay"
        @click="handleOverlayClick"
      >
        <Transition
          enter-active-class="transition-transform duration-300"
          enter-from-class="translate-y-full"
          enter-to-class="translate-y-0"
          leave-active-class="transition-transform duration-300"
          leave-from-class="translate-y-0"
          leave-to-class="translate-y-full"
        >
          <div v-if="modelValue" class="drawer-content">
            <!-- 标题栏 -->
            <div class="drawer-header">
              <h3 class="drawer-title">{{ title }}</h3>
              <button class="drawer-close" @click="handleClose">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- 筛选项内容 -->
            <div class="drawer-body">
              <div v-for="item in items" :key="item.key" class="filter-item">
                <label class="filter-label">{{ item.label }}</label>

                <!-- 输入框 -->
                <input
                  v-if="item.type === 'input'"
                  v-model="formData[item.key as keyof typeof formData]"
                  type="text"
                  :placeholder="item.placeholder"
                  class="filter-input"
                />

                <!-- 下拉选择 -->
                <select v-else-if="item.type === 'select'" v-model="formData[item.key as keyof typeof formData]" class="filter-select">
                  <option value="">{{ item.placeholder || '全部' }}</option>
                  <option v-for="opt in item.options" :key="String(opt.value)" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </select>

                <!-- 日期选择 -->
                <input
                  v-else-if="item.type === 'date'"
                  v-model="formData[item.key as keyof typeof formData]"
                  type="date"
                  class="filter-input"
                />

                <!-- 复选框组 -->
                <div v-else-if="item.type === 'checkbox' && item.options" class="filter-checkbox-group">
                  <label
                    v-for="opt in item.options"
                    :key="String(opt.value)"
                    class="filter-checkbox"
                  >
                    <input
                      type="checkbox"
                      :value="opt.value"
                      v-model="formData[item.key as keyof typeof formData]"
                    />
                    <span>{{ opt.label }}</span>
                  </label>
                </div>

                <!-- 单选框组 -->
                <div v-else-if="item.type === 'radio' && item.options" class="filter-radio-group">
                  <label
                    v-for="opt in item.options"
                    :key="String(opt.value)"
                    class="filter-radio"
                  >
                    <input
                      type="radio"
                      :name="item.key"
                      :value="opt.value"
                      v-model="formData[item.key as keyof typeof formData]"
                    />
                    <span>{{ opt.label }}</span>
                  </label>
                </div>
              </div>
            </div>

            <!-- 底部操作栏 -->
            <div class="drawer-footer">
              <button class="drawer-btn drawer-btn-reset" @click="handleReset">
                重置
              </button>
              <button class="drawer-btn drawer-btn-submit" @click="handleFilter" :disabled="loading">
                <svg v-if="loading" class="drawer-spinner" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                应用筛选
              </button>
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(11, 12, 15, 0.85);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 1000;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.drawer-content {
  width: 100%;
  max-width: 480px;
  background: var(--bg-surface);
  border-top-left-radius: 20px;
  border-top-right-radius: 20px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.4);
}

/* 标题栏 */
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-base);
}

.drawer-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.drawer-close {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: var(--bg-input);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 150ms ease;
}

.drawer-close:active {
  background: var(--bg-card-hover);
  transform: scale(0.95);
}

/* 内容区 */
.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem;
}

.drawer-body::-webkit-scrollbar {
  width: 4px;
}

.drawer-body::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 2px;
}

.filter-item {
  margin-bottom: 1.25rem;
}

.filter-item:last-child {
  margin-bottom: 0;
}

.filter-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}

.filter-input,
.filter-select {
  width: 100%;
  padding: 0.75rem 1rem;
  font-size: 15px;
  color: var(--text-primary);
  background: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: 12px;
  outline: none;
  transition: all 150ms ease;
}

.filter-input::placeholder {
  color: var(--text-tertiary);
}

.filter-input:focus,
.filter-select:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

.filter-select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%239AA3AF'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 1rem center;
  background-size: 16px;
  padding-right: 2.5rem;
}

.filter-checkbox-group,
.filter-radio-group {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.filter-checkbox,
.filter-radio {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: var(--bg-input);
  border-radius: 10px;
  cursor: pointer;
  transition: all 150ms ease;
}

.filter-checkbox:active,
.filter-radio:active {
  background: var(--bg-card-hover);
}

.filter-checkbox input,
.filter-radio input {
  width: 18px;
  height: 18px;
  accent-color: var(--primary);
}

.filter-checkbox span,
.filter-radio span {
  font-size: 14px;
  color: var(--text-primary);
}

/* 底部操作栏 */
.drawer-footer {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid var(--border-base);
}

.drawer-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.875rem 1rem;
  font-size: 15px;
  font-weight: 500;
  border-radius: 12px;
  border: none;
  cursor: pointer;
  transition: all 150ms ease;
}

.drawer-btn-reset {
  background: var(--bg-input);
  color: var(--text-secondary);
}

.drawer-btn-reset:active {
  background: var(--bg-card-hover);
}

.drawer-btn-submit {
  background: var(--primary);
  color: white;
}

.drawer-btn-submit:active {
  background: var(--primary-active);
}

.drawer-btn-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.drawer-spinner {
  width: 18px;
  height: 18px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 桌面端适配 */
@media (min-width: 640px) {
  .drawer-content {
    margin: 1rem;
    border-radius: 20px;
    max-height: calc(100vh - 2rem);
  }
}
</style>
