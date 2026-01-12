<!--
  ImportDialog.vue
  iOS 风格系统配置页面 - 导入配置弹窗

  功能：
  - 粘贴 JSON 格式配置
  - 校验格式
  - 显示错误信息
-->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { SettingImportItem } from '@/types/settings'

interface Props {
  modelValue: boolean
}

interface Emits {
  (e: 'update:modelValue', value: boolean): void
  (e: 'import', items: SettingImportItem[]): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 导入文本
const importText = ref('')

// 错误信息
const errorMessage = ref('')

// JSON 格式示例
const jsonExample = `[
  {
    "key": "moviepilot_url",
    "value": "http://localhost:3000"
  },
  {
    "key": "telegram_bot_token",
    "value": "your_bot_token_here"
  }
]`

// 监听弹窗打开，重置状态
watch(() => props.modelValue, (isOpen) => {
  if (isOpen) {
    importText.value = ''
    errorMessage.value = ''
    nextTick(() => {
      // 聚焦到 textarea
      const textarea = document.querySelector('.import-textarea textarea') as HTMLTextAreaElement
      textarea?.focus()
    })
  }
})

// 处理导入
const handleImport = () => {
  errorMessage.value = ''

  if (!importText.value.trim()) {
    errorMessage.value = '请输入配置 JSON'
    return
  }

  try {
    const items = JSON.parse(importText.value)

    // 校验格式
    if (!Array.isArray(items)) {
      errorMessage.value = '格式错误：根节点必须是数组'
      return
    }

    if (items.length === 0) {
      errorMessage.value = '配置列表不能为空'
      return
    }

    // 校验每个配置项
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (!item.key || typeof item.key !== 'string') {
        errorMessage.value = `第 ${i + 1} 项缺少 key 或 key 不是字符串`
        return
      }
      if (item.value === undefined || typeof item.value !== 'string') {
        errorMessage.value = `第 ${i + 1} 项缺少 value 或 value 不是字符串`
        return
      }
    }

    // 触发导入事件
    emit('import', items as SettingImportItem[])
    emit('update:modelValue', false)

  } catch (e: any) {
    errorMessage.value = `JSON 格式错误：${e.message}`
  }
}

// 关闭弹窗
const handleClose = () => {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="handleClose"
    title="导入配置"
    width="500px"
    :draggable="true"
    :close-on-click-modal="false"
    class="import-dialog"
  >
    <div class="import-content">
      <!-- 提示信息 -->
      <div class="import-hint">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/>
          <path d="M8 5V8M8 11H8.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <span>粘贴之前导出的配置 JSON，将覆盖现有配置</span>
      </div>

      <!-- 文本输入区 -->
      <el-input
        v-model="importText"
        type="textarea"
        :rows="10"
        placeholder="粘贴 JSON 配置..."
        class="import-textarea"
      />

      <!-- 错误提示 -->
      <transition name="error-fade">
        <div v-if="errorMessage" class="error-message">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="6" fill="#EF4444" fill-opacity="0.2"/>
            <path d="M8 5V8M8 11H8.01" stroke="#EF4444" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          {{ errorMessage }}
        </div>
      </transition>

      <!-- 格式示例（可折叠） -->
      <details class="format-example">
        <summary>查看格式示例</summary>
        <pre class="example-code">{{ jsonExample }}</pre>
      </details>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <button class="btn-cancel" @click="handleClose">取消</button>
        <button class="btn-import" @click="handleImport">导入</button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.import-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 提示信息 */
.import-hint {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px;
  font-size: 14px;
  color: #9AA3AF;
  background-color: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 12px;
}

.import-hint svg {
  flex-shrink: 0;
  margin-top: 2px;
  color: #3B82F6;
}

/* Textarea 样式覆盖 */
:deep(.import-textarea .el-textarea__inner) {
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  color: #E7ECF2;
  background-color: #171C23;
  border: 1px solid #232A33;
  border-radius: 12px;
}

:deep(.import-textarea .el-textarea__inner::placeholder) {
  color: #9AA3AF;
}

:deep(.import-textarea .el-textarea__inner:focus) {
  border-color: #10B981;
  box-shadow: 0 0 0 1px #10B981;
}

/* 错误提示 */
.error-message {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  font-size: 14px;
  color: #EF4444;
  background-color: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
}

.error-fade-enter-active,
.error-fade-leave-active {
  transition: all 0.2s ease;
}

.error-fade-enter-from,
.error-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* 格式示例 */
.format-example {
  cursor: pointer;
}

.format-example summary {
  font-size: 13px;
  color: #9AA3AF;
  user-select: none;
  outline: none;
}

.format-example summary:hover {
  color: #E7ECF2;
}

.format-example[open] summary {
  margin-bottom: 8px;
}

.example-code {
  margin: 0;
  padding: 12px;
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: #9AA3AF;
  background-color: #0B0D10;
  border: 1px solid #232A33;
  border-radius: 8px;
  overflow-x: auto;
}

/* 底部按钮 */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel {
  padding: 0 20px;
  height: 40px;
  font-size: 15px;
  color: #9AA3AF;
  background: transparent;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-cancel:hover {
  color: #E7ECF2;
  background-color: rgba(255, 255, 255, 0.05);
}

.btn-import {
  padding: 0 24px;
  height: 40px;
  font-size: 15px;
  font-weight: 500;
  color: #FFFFFF;
  background-color: #10B981;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-import:hover {
  background-color: #059669;
}

.btn-import:active {
  transform: scale(0.96);
}

/* 移动端适配 */
@media (max-width: 768px) {
  :deep(.el-dialog) {
    width: 90vw !important;
    margin: 0 auto;
  }

  :deep(.import-textarea .el-textarea__inner) {
    font-size: 12px;
  }
}
</style>
