<template>
  <div :class="['form-input', { 'form-input--error': error, 'form-input--disabled': disabled, 'form-input--focused': focused }]">
    <label v-if="label" :class="['form-input__label', { 'form-input__label--required': required }]">
      {{ label }}
    </label>

    <div class="form-input__wrapper">
      <span v-if="prefixIcon" class="form-input__icon form-input__icon--prefix">
        <component :is="prefixIcon" />
      </span>

      <input
        :id="id"
        ref="inputRef"
        v-model="modelValue"
        :type="type"
        :placeholder="placeholder"
        :disabled="disabled"
        :readonly="readonly"
        :maxlength="maxlength"
        :autocomplete="autocomplete"
        :class="['form-input__field', { 'form-input__field--has-icon': prefixIcon || suffixIcon }]"
        @focus="handleFocus"
        @blur="handleBlur"
      />

      <span v-if="suffixIcon" class="form-input__icon form-input__icon--suffix">
        <component :is="suffixIcon" />
      </span>

      <button
        v-if="clearable && modelValue && !disabled"
        type="button"
        class="form-input__clear"
        @click="handleClear"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <path d="M15 9l-6 6M9 9l6 6"/>
        </svg>
      </button>
    </div>

    <div v-if="error || hint" class="form-input__message">
      <span v-if="error" class="form-input__error">{{ error }}</span>
      <span v-else-if="hint" class="form-input__hint">{{ hint }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

export interface FormInputProps {
  id?: string
  type?: 'text' | 'password' | 'email' | 'number' | 'tel' | 'url'
  modelValue: string | number
  label?: string
  placeholder?: string
  error?: string
  hint?: string
  disabled?: boolean
  readonly?: boolean
  required?: boolean
  clearable?: boolean
  maxlength?: number
  autocomplete?: string
  prefixIcon?: any
  suffixIcon?: any
}

const props = withDefaults(defineProps<FormInputProps>(), {
  type: 'text',
  disabled: false,
  readonly: false,
  required: false,
  clearable: false
})

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  focus: [event: FocusEvent]
  blur: [event: FocusEvent]
  clear: []
}>()

const focused = ref(false)
const inputRef = ref<HTMLInputElement>()

const modelValue = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const handleFocus = (e: FocusEvent) => {
  focused.value = true
  emit('focus', e)
}

const handleBlur = (e: FocusEvent) => {
  focused.value = false
  emit('blur', e)
}

const handleClear = () => {
  modelValue.value = ''
  emit('clear')
}

defineExpose({
  focus: () => inputRef.value?.focus(),
  blur: () => inputRef.value?.blur()
})
</script>

<style scoped>
.form-input {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-input__label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.form-input__label--required::after {
  content: '*';
  color: var(--color-danger);
  margin-left: 0.25rem;
}

.form-input__wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.form-input__field {
  width: 100%;
  padding: 0.75rem 1rem;
  font-size: 0.875rem;
  color: var(--text-primary);
  background: var(--bg-glass);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  transition: all 0.2s ease;
  outline: none;
}

.form-input__field::placeholder {
  color: var(--text-tertiary);
}

.form-input__field--has-icon {
  padding-left: 2.75rem;
}

.form-input__field:hover:not(:disabled) {
  border-color: var(--border-strong);
}

.form-input--focused .form-input__field {
  border-color: var(--brand-primary);
  box-shadow: 0 0 0 3px var(--brand-primary-light);
}

.form-input--error .form-input__field {
  border-color: var(--color-danger);
}

.form-input--error.form-input--focused .form-input__field {
  box-shadow: 0 0 0 3px var(--color-danger-light);
}

.form-input--disabled .form-input__field {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--bg-tertiary);
}

.form-input__icon {
  position: absolute;
  width: 20px;
  height: 20px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.form-input__icon--prefix {
  left: 0.875rem;
}

.form-input__icon--suffix {
  right: 0.875rem;
}

.form-input__clear {
  position: absolute;
  right: 0.5rem;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-tertiary);
  border: none;
  border-radius: 50%;
  cursor: pointer;
  color: var(--text-tertiary);
  transition: all 0.2s ease;
}

.form-input__clear:hover {
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.form-input__clear svg {
  width: 14px;
  height: 14px;
}

.form-input__message {
  display: flex;
  align-items: center;
  min-height: 1.25rem;
}

.form-input__error,
.form-input__hint {
  font-size: 0.75rem;
  line-height: 1.25rem;
}

.form-input__error {
  color: var(--color-danger);
}

.form-input__hint {
  color: var(--text-tertiary);
}
</style>
