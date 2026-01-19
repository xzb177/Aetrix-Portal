<template>
  <div
    :class="['form-select', { 'form-select--open': isOpen, 'form-select--error': error, 'form-select--disabled': disabled }]"
    ref="selectRef"
  >
    <label v-if="label" :class="['form-select__label', { 'form-select__label--required': required }]">
      {{ label }}
    </label>

    <div
      :class="['form-select__trigger', { 'form-select__trigger--placeholder': !selectedLabel }]"
      tabindex="0"
      @click="toggleDropdown"
      @keydown="handleKeydown"
    >
      <span class="form-select__value">{{ selectedLabel || placeholder }}</span>
      <span class="form-select__arrow">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </span>
    </div>

    <Transition name="form-select-dropdown">
      <div v-if="isOpen" class="form-select__dropdown">
        <div class="form-select__options">
          <div
            v-for="option in options"
            :key="option.value"
            :class="['form-select__option', { 'form-select__option--selected': option.value === modelValue, 'form-select__option--disabled': option.disabled }]"
            @click="selectOption(option.value)"
          >
            <span v-if="option.value === modelValue" class="form-select__check">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </span>
            <span class="form-select__option-label">{{ option.label }}</span>
          </div>
        </div>
      </div>
    </Transition>

    <div v-if="error || hint" class="form-select__message">
      <span v-if="error" class="form-select__error">{{ error }}</span>
      <span v-else-if="hint" class="form-select__hint">{{ hint }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

export interface SelectOption {
  label: string
  value: string | number
  disabled?: boolean
}

export interface FormSelectProps {
  modelValue: string | number
  options: SelectOption[]
  label?: string
  placeholder?: string
  error?: string
  hint?: string
  disabled?: boolean
  required?: boolean
}

const props = withDefaults(defineProps<FormSelectProps>(), {
  placeholder: '请选择',
  disabled: false,
  required: false
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement>()

const selectedLabel = computed(() => {
  const option = props.options.find(o => o.value === props.modelValue)
  return option?.label || ''
})

const toggleDropdown = () => {
  if (!props.disabled) {
    isOpen.value = !isOpen.value
  }
}

const selectOption = (value: string | number) => {
  const option = props.options.find(o => o.value === value)
  if (option && !option.disabled) {
    emit('update:modelValue', value)
    isOpen.value = false
  }
}

const handleKeydown = (e: KeyboardEvent) => {
  switch (e.key) {
    case 'Enter':
    case ' ':
      e.preventDefault()
      toggleDropdown()
      break
    case 'Escape':
      isOpen.value = false
      break
    case 'ArrowDown':
    case 'ArrowUp':
      e.preventDefault()
      if (!isOpen.value) {
        isOpen.value = true
      }
      // 可以添加键盘导航逻辑
      break
  }
}

const handleClickOutside = (e: MouseEvent) => {
  if (selectRef.value && !selectRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
.form-select {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-select__label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.form-select__label--required::after {
  content: '*';
  color: var(--color-danger);
  margin-left: 0.25rem;
}

.form-select__trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  font-size: 0.875rem;
  color: var(--text-primary);
  background: var(--bg-glass);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}

.form-select__trigger--placeholder {
  color: var(--text-tertiary);
}

.form-select__trigger:hover {
  border-color: var(--border-strong);
}

.form-select--open .form-select__trigger,
.form-select__trigger:focus {
  outline: none;
  border-color: var(--brand-primary);
  box-shadow: 0 0 0 3px var(--brand-primary-light);
}

.form-select--error .form-select__trigger {
  border-color: var(--color-danger);
}

.form-select--error.form-select--open .form-select__trigger {
  box-shadow: 0 0 0 3px var(--color-danger-light);
}

.form-select--disabled .form-select__trigger {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--bg-tertiary);
}

.form-select__arrow {
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
  transition: transform 0.2s ease;
  flex-shrink: 0;
}

.form-select--open .form-select__arrow {
  transform: rotate(180deg);
}

.form-select__dropdown {
  position: absolute;
  top: calc(100% + 0.25rem);
  left: 0;
  right: 0;
  z-index: var(--z-dropdown);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  max-height: 250px;
  overflow-y: auto;
}

.form-select__options {
  padding: 0.25rem;
}

.form-select__option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.75rem;
  font-size: 0.875rem;
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s ease;
}

.form-select__option:hover:not(.form-select__option--disabled) {
  background: var(--bg-elevated-hover);
}

.form-select__option--selected {
  color: var(--brand-primary);
  background: var(--brand-primary-lighter);
}

.form-select__option--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-select__check {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.form-select__option-label {
  flex: 1;
}

.form-select__message {
  display: flex;
  align-items: center;
  min-height: 1.25rem;
}

.form-select__error,
.form-select__hint {
  font-size: 0.75rem;
  line-height: 1.25rem;
}

.form-select__error {
  color: var(--color-danger);
}

.form-select__hint {
  color: var(--text-tertiary);
}

/* 下拉动画 */
.form-select-dropdown-enter-active,
.form-select-dropdown-leave-active {
  transition: all 0.2s ease;
}

.form-select-dropdown-enter-from,
.form-select-dropdown-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
