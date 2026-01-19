<template>
  <label
    :class="[
      'form-checkbox',
      {
        'form-checkbox--checked': modelValue,
        'form-checkbox--disabled': disabled,
        'form-checkbox--error': error
      }
    ]"
  >
    <input
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      class="form-checkbox__input"
      @change="handleChange"
    />

    <span class="form-checkbox__box">
      <svg class="form-checkbox__check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
    </span>

    <span v-if="label || $slots.default" class="form-checkbox__label">
      <slot>{{ label }}</slot>
    </span>
  </label>
</template>

<script setup lang="ts">
export interface FormCheckboxProps {
  modelValue: boolean
  label?: string
  disabled?: boolean
  error?: boolean
  indeterminate?: boolean
}

const props = withDefaults(defineProps<FormCheckboxProps>(), {
  disabled: false,
  error: false,
  indeterminate: false
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  change: [value: boolean]
}>()

const handleChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  emit('update:modelValue', target.checked)
  emit('change', target.checked)
}
</script>

<style scoped>
.form-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 0.625rem;
  cursor: pointer;
  user-select: none;
}

.form-checkbox--disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.form-checkbox__input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.form-checkbox__box {
  position: relative;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  background: var(--bg-glass);
  border: 2px solid var(--border-default);
  border-radius: var(--radius-sm);
  transition: all 0.2s ease;
}

.form-checkbox:hover:not(.form-checkbox--disabled) .form-checkbox__box {
  border-color: var(--brand-primary);
}

.form-checkbox--error .form-checkbox__box {
  border-color: var(--color-danger);
}

.form-checkbox--checked .form-checkbox__box {
  background: var(--brand-primary);
  border-color: var(--brand-primary);
}

.form-checkbox__check {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 12px;
  height: 12px;
  color: white;
  transform: translate(-50%, -50%) scale(0);
  transition: transform 0.2s ease;
}

.form-checkbox--checked .form-checkbox__check {
  transform: translate(-50%, -50%) scale(1);
}

.form-checkbox__label {
  font-size: 0.875rem;
  color: var(--text-primary);
  line-height: 1.4;
}
</style>
