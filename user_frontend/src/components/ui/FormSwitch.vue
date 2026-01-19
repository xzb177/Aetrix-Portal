<template>
  <label
    :class="[
      'form-switch',
      {
        'form-switch--checked': modelValue,
        'form-switch--disabled': disabled,
        'form-switch--error': error
      }
    ]"
  >
    <input
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      class="form-switch__input"
      @change="handleChange"
    />

    <span class="form-switch__track">
      <span class="form-switch__thumb">
        <svg v-if="modelValue" class="form-switch__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </span>
    </span>

    <span v-if="label" class="form-switch__label">{{ label }}</span>
  </label>
</template>

<script setup lang="ts">
export interface FormSwitchProps {
  modelValue: boolean
  label?: string
  disabled?: boolean
  error?: boolean
}

const props = withDefaults(defineProps<FormSwitchProps>(), {
  disabled: false,
  error: false
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
.form-switch {
  display: inline-flex;
  align-items: center;
  gap: 0.75rem;
  cursor: pointer;
  user-select: none;
}

.form-switch--disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.form-switch__input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.form-switch__track {
  position: relative;
  width: 44px;
  height: 24px;
  flex-shrink: 0;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.form-switch:hover:not(.form-switch--disabled) .form-switch__track {
  background: var(--bg-elevated);
}

.form-switch--checked .form-switch__track {
  background: var(--brand-primary);
  border-color: var(--brand-primary);
}

.form-switch--error .form-switch__track {
  border-color: var(--color-danger);
}

.form-switch--error.form-switch--checked .form-switch__track {
  background: var(--color-danger);
  border-color: var(--color-danger);
}

.form-switch__thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  background: white;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.form-switch--checked .form-switch__thumb {
  transform: translateX(20px);
}

.form-switch__icon {
  width: 12px;
  height: 12px;
  color: var(--brand-primary);
}

.form-switch--error.form-switch--checked .form-switch__icon {
  color: var(--color-danger);
}

.form-switch__label {
  font-size: 0.875rem;
  color: var(--text-primary);
}
</style>
