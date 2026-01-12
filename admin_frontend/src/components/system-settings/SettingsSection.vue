<!--
  SettingsSection.vue
  Apple TV 风格系统配置页面 - 分组卡片（可折叠）

  功能：
  - 显示分组标题和配置项数量
  - 可折叠/展开内容区
  - 过滤不匹配搜索的配置项
-->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import type { SettingItem } from '@/types/settings'
import SettingRow from './SettingRow.vue'

interface Props {
  /** 分组名称 */
  name: string
  /** 该分组下的所有配置项 */
  items: SettingItem[]
  /** 搜索关键词（用于过滤） */
  searchQuery?: string
  /** 是否默认展开 */
  defaultExpanded?: boolean
  /** Dirty State 检查函数 */
  isDirty?: (key: string) => boolean
  /** 当前编辑值获取函数 */
  getCurrentValue?: (key: string) => string
  /** 敏感字段检查函数 */
  isSensitive?: (key: string) => boolean
}

interface Emits {
  (e: 'update', key: string, value: string): void
}

const props = withDefaults(defineProps<Props>(), {
  searchQuery: '',
  defaultExpanded: false
})

const emit = defineEmits<Emits>()

// 折叠状态
const isExpanded = ref(props.defaultExpanded)

// 密码显示状态
const showPassword = ref<Record<string, boolean>>({})

// 过滤后的配置项
const filteredItems = computed(() => {
  if (!props.searchQuery) return props.items

  const query = props.searchQuery.toLowerCase()
  return props.items.filter(item =>
    item.label?.toLowerCase().includes(query) ||
    item.key?.toLowerCase().includes(query) ||
    item.description?.toLowerCase().includes(query)
  )
})

// 配置项数量（包括隐藏的）
const itemCount = computed(() => props.items.length)

// 可见配置项数量
const visibleCount = computed(() => filteredItems.value.length)

// 切换折叠
const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
}

// 切换密码显示
const togglePassword = (key: string) => {
  showPassword.value[key] = !showPassword.value[key]
}

// 处理值更新
const handleUpdate = (key: string, value: string) => {
  emit('update', key, value)
}

// 检查配置项是否已修改
const checkDirty = (key: string): boolean => {
  return props.isDirty?.(key) ?? false
}

// 获取当前编辑值
const getValue = (key: string): string => {
  return props.getCurrentValue?.(key) ?? ''
}

// 检查是否为敏感字段
const checkSensitive = (key: string): boolean => {
  return props.isSensitive?.(key) ?? false
}

// 复制值
const copyValue = async (key: string) => {
  const value = getValue(key)
  try {
    await navigator.clipboard.writeText(value)
    const isHidden = !showPassword.value[key] && checkSensitive(key)
    // 使用 ElMessage 显示提示
    const { ElMessage } = await import('element-plus')
    ElMessage.success(isHidden ? '已复制（已隐藏）' : '已复制')
  } catch {
    const { ElMessage } = await import('element-plus')
    ElMessage.error('复制失败')
  }
}

// 动画钩子
function onEnter(el: Element) {
  const htmlEl = el as HTMLElement
  htmlEl.style.height = '0'
}

function onAfterEnter(el: Element) {
  const htmlEl = el as HTMLElement
  htmlEl.style.height = ''
}

function onLeave(el: Element) {
  const htmlEl = el as HTMLElement
  htmlEl.style.height = htmlEl.offsetHeight + 'px'
  // 强制重绘
  htmlEl.offsetHeight
}
</script>

<template>
  <div class="settings-section">
    <!-- 分组 Header -->
    <div
      class="section-header touch-feedback"
      :class="{ 'section-header-expanded': isExpanded }"
      @click="toggleExpand"
    >
      <h2 class="section-title">
        {{ name }}
        <span class="section-count">({{ visibleCount }}{{ itemCount !== visibleCount ? `/${itemCount}` : '' }})</span>
      </h2>
      <component
        :is="isExpanded ? ArrowDown : ArrowRight"
        class="section-arrow"
        :size="18"
      />
    </div>

    <!-- 分组内容 -->
    <transition
      name="section-expand"
      @enter="onEnter"
      @after-enter="onAfterEnter"
      @leave="onLeave"
    >
      <div v-show="isExpanded" class="section-content">
        <SettingRow
          v-for="item in filteredItems"
          :key="item.key"
          :item="item"
          :current-value="getValue(item.key)"
          :is-dirty="checkDirty(item.key)"
          :show-password="showPassword[item.key]"
          :is-sensitive="checkSensitive(item.key)"
          @update="handleUpdate(item.key, $event)"
          @toggle-password="togglePassword(item.key)"
          @copy="copyValue(item.key)"
        />

        <!-- 空状态（被搜索过滤后） -->
        <div v-if="filteredItems.length === 0 && items.length > 0" class="section-empty">
          <p class="empty-text">无匹配的配置项</p>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.settings-section {
  margin-bottom: 16px;
  background-color: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-xl);
  overflow: hidden;
}

/* 分组 Header */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  cursor: pointer;
  user-select: none;
  transition: background-color var(--transition-base) ease;
}

.section-header:hover {
  background-color: var(--bg-card-hover);
}

.section-header:active {
  background-color: var(--bg-input);
}

.section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.section-count {
  margin-left: 6px;
  font-size: 14px;
  font-weight: 400;
  color: var(--text-tertiary);
}

.section-arrow {
  color: var(--text-tertiary);
  transition: transform var(--transition-base) ease;
}

.section-header-expanded .section-arrow {
  transform: rotate(0deg);
}

/* 分组内容 */
.section-content {
  border-top: 1px solid var(--border-base);
}

/* 展开/折叠动画 */
.section-expand-enter-active,
.section-expand-leave-active {
  transition: height var(--transition-base) ease, opacity var(--transition-base) ease;
  overflow: hidden;
}

.section-expand-enter-from,
.section-expand-leave-to {
  height: 0 !important;
  opacity: 0;
}

/* 空状态 */
.section-empty {
  padding: 32px 16px;
  text-align: center;
}

.empty-text {
  margin: 0;
  font-size: 14px;
  color: var(--text-tertiary);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .settings-section {
    margin-bottom: 12px;
    border-radius: var(--radius-lg);
  }

  .section-header {
    padding: 12px 14px;
  }

  .section-title {
    font-size: 15px;
  }
}
</style>
