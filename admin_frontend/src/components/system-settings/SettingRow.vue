<!--
  SettingRow.vue
  Apple TV 风格系统配置页面 - 单个配置项行

  功能：
  - 显示配置名称、key、描述
  - 根据类型渲染不同控件（Input/Switch/Select/Number）
  - 敏感字段支持显示/隐藏、复制
  - 已修改状态视觉反馈
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { SettingItem } from '@/types/settings'

interface Props {
  item: SettingItem
  currentValue?: string
  isDirty?: boolean
  showPassword?: boolean
  isSensitive?: boolean
}

interface Emits {
  (e: 'update', value: string): void
  (e: 'togglePassword'): void
  (e: 'copy'): void
}

const props = withDefaults(defineProps<Props>(), {
  currentValue: '',
  isDirty: false,
  showPassword: false,
  isSensitive: false
})

const emit = defineEmits<Emits>()

// 本地值（双向绑定）
const localValue = computed({
  get: () => props.currentValue,
  set: (val) => emit('update', val)
})

// 输入框类型
const inputType = computed(() => {
  if (props.item.type === 'password') {
    return props.showPassword ? 'text' : 'password'
  }
  if (props.item.type === 'url') return 'url'
  if (props.item.type === 'number') return 'number'
  return 'text'
})

// 是否为布尔类型
const isBoolean = computed(() => props.item.type === 'boolean')

// 是否为下拉选择类型
const isSelect = computed(() => props.item.type === 'select')

// 是否为数字类型
const isNumber = computed(() => props.item.type === 'number')

// 是否为密码类型
const isPassword = computed(() => props.item.type === 'password' || props.isSensitive)

// 处理数字输入
const handleNumberInput = (value: number | undefined) => {
  emit('update', value !== undefined ? String(value) : '')
}

// 切换密码显示
const handleTogglePassword = () => {
  emit('togglePassword')
}

// 复制值
const handleCopy = () => {
  emit('copy')
}

// 处理 Switch 变化
const handleSwitchChange = (val: boolean) => {
  emit('update', val ? 'true' : 'false')
}
</script>

<template>
  <div class="setting-row" :class="{ 'setting-row-dirty': isDirty }">
    <!-- 左侧信息区 -->
    <div class="setting-info">
      <div class="setting-label">
        {{ item.label }}
        <span v-if="item.required" class="required-mark">*</span>
      </div>
      <code class="setting-key">{{ item.key }}</code>
      <p v-if="item.description" class="setting-desc">{{ item.description }}</p>
    </div>

    <!-- 右侧控件区 -->
    <div class="setting-control">
      <!-- Switch 开关 -->
      <el-switch
        v-if="isBoolean"
        :model-value="localValue === 'true'"
        @update:model-value="handleSwitchChange"
        size="large"
        inline-prompt
        active-text="开"
        inactive-text="关"
        class="setting-switch"
      />

      <!-- Select 下拉 -->
      <el-select
        v-else-if="isSelect"
        :model-value="localValue"
        @update:model-value="localValue = $event"
        size="large"
        class="setting-select"
      >
        <el-option
          v-for="opt in item.options"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>

      <!-- InputNumber 数字输入 -->
      <el-input-number
        v-else-if="isNumber"
        :model-value="parseFloat(localValue) || 0"
        @update:model-value="handleNumberInput"
        size="large"
        :controls-position="'right'"
        class="setting-number"
      />

      <!-- Input 输入框 -->
      <el-input
        v-else
        :model-value="localValue"
        @update:model-value="localValue = $event"
        :type="inputType"
        :show-password="isPassword && !showPassword"
        size="large"
        :placeholder="item.type === 'password' ? '••••••••' : '请输入'"
        class="setting-input"
      />

      <!-- 敏感字段额外操作 -->
      <template v-if="isPassword">
        <button
          class="btn-icon"
          :class="{ 'btn-icon-active': showPassword }"
          @click="handleTogglePassword"
          :title="showPassword ? '隐藏' : '显示'"
        >
          <svg v-if="showPassword" width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 4c-3.33 0-6 2.67-6 6s2.67 6 6 6 6-2.67 6-6-2.67-6-6-6z" stroke="currentColor" stroke-width="1.5"/>
            <path d="M8 6.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z" stroke="currentColor" stroke-width="1.5"/>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2.5 8c1-2 3.5-4 5.5-4s4.5 2 5.5 4c-1 2-3.5 4-5.5 4s-4.5-2-5.5-4z" stroke="currentColor" stroke-width="1.5"/>
            <path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z" stroke="currentColor" stroke-width="1.5"/>
          </svg>
        </button>
        <button
          class="btn-icon"
          @click="handleCopy"
          title="复制"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="3" y="5" width="8" height="10" rx="1" stroke="currentColor" stroke-width="1.5"/>
            <path d="M5 5V3a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" stroke="currentColor" stroke-width="1.5"/>
          </svg>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.setting-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
  min-height: 56px;
  border-bottom: 1px solid var(--border-base);
  transition: background-color var(--transition-base) ease;
}

.setting-row:last-child {
  border-bottom: none;
}

.setting-row:hover {
  background-color: var(--bg-card-hover);
}

/* 已修改状态 */
.setting-row-dirty {
  background-color: var(--warning-bg);
}

.setting-row-dirty::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background-color: var(--warning);
}

/* 左侧信息区 */
.setting-info {
  flex: 1;
  min-width: 0;
}

.setting-label {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-primary);
}

.required-mark {
  color: var(--danger);
  margin-left: 2px;
}

.setting-key {
  display: block;
  margin-top: 2px;
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.setting-desc {
  margin: 4px 0 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.4;
}

/* 右侧控件区 */
.setting-control {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* Element Plus 组件样式覆盖 */
:deep(.el-input__wrapper) {
  height: 44px;
  background-color: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  box-shadow: none;
  transition: all var(--transition-base) ease;
}

:deep(.el-input__wrapper:hover) {
  border-color: var(--border-strong);
}

:deep(.el-input__wrapper.is-focus) {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

:deep(.el-input__inner) {
  color: var(--text-primary);
  font-size: 14px;
}

:deep(.el-input__inner::placeholder) {
  color: var(--text-tertiary);
}

/* Input Number */
:deep(.el-input-number) {
  width: 140px;
}

:deep(.el-input-number .el-input__wrapper) {
  width: 100%;
}

:deep(.el-input-number__decrease),
:deep(.el-input-number__increase) {
  background-color: transparent;
  border-left: 1px solid var(--border-base);
  color: var(--text-tertiary);
}

:deep(.el-input-number__decrease:hover),
:deep(.el-input-number__increase:hover) {
  color: var(--text-primary);
}

/* Select */
.setting-select {
  width: 180px;
}

:deep(.el-select__wrapper) {
  height: 44px;
  background-color: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  box-shadow: none;
}

:deep(.el-select__wrapper:hover) {
  border-color: var(--border-strong);
}

:deep(.el-select__wrapper.is-focus) {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

:deep(.el-select__input) {
  color: var(--text-primary);
}

:deep(.el-select__placeholder) {
  color: var(--text-tertiary);
}

/* Switch */
:deep(.el-switch) {
  height: 28px;
}

:deep(.el-switch__core) {
  background-color: var(--bg-card-hover);
  border: 2px solid var(--border-strong);
}

:deep(.el-switch.is-checked .el-switch__core) {
  background-color: var(--primary);
  border-color: var(--primary);
}

:deep(.el-switch__action) {
  background-color: var(--text-primary);
}

/* 图标按钮 */
.btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-icon:hover {
  color: var(--text-primary);
  background-color: var(--bg-card-hover);
}

.btn-icon:active {
  transform: scale(0.92);
}

.btn-icon-active {
  color: var(--primary);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .setting-row {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
    padding: 12px 14px;
    min-height: auto;
  }

  .setting-row-dirty::before {
    width: 2px;
  }

  .setting-desc {
    margin-bottom: 8px;
  }

  .setting-control {
    justify-content: flex-end;
  }

  :deep(.el-input__wrapper),
  :deep(.el-select__wrapper) {
    height: 40px;
  }

  .setting-number,
  .setting-select {
    width: 100%;
    max-width: 200px;
  }
}
</style>
