<script setup lang="ts">
/**
 * ProfileSettingsSheet - 个人中心设置面板
 *
 * 特性：
 * - 显示/隐藏各个模块
 * - 本地存储用户偏好
 * - 开关样式切换
 */
import { ref, computed, onMounted, watch } from 'vue'
import { Settings, Eye, EyeOff, RotateCcw } from 'lucide-vue-next'
import BottomSheet from '@/components/ui/BottomSheet.vue'

interface Props {
  show: boolean
}

interface Emits {
  (e: 'update:show', value: boolean): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// 设置项定义
interface SettingItem {
  id: string
  label: string
  description: string
  defaultVisible: boolean
}

const settings: SettingItem[] = [
  { id: 'holoId', label: '全息身份卡', description: 'Holo-ID 卡片翻转效果', defaultVisible: true },
  { id: 'dashboard', label: '三联仪表盘', description: '余额、求片配额、VIP 状态', defaultVisible: true },
  { id: 'accountVault', label: '账号保险箱', description: 'Emby 账号抽屉', defaultVisible: true },
  { id: 'timeline', label: '活动时间线', description: '最近活动记录', defaultVisible: true },
]

// 可见性状态
const visibility = ref<Record<string, boolean>>({})

// 从 localStorage 加载设置
const loadSettings = () => {
  try {
    const stored = localStorage.getItem('profile_visibility')
    if (stored) {
      const saved = JSON.parse(stored)
      // 合并保存的设置和默认设置
      settings.forEach(item => {
        if (saved[item.id] !== undefined) {
          visibility.value[item.id] = saved[item.id]
        } else {
          visibility.value[item.id] = item.defaultVisible
        }
      })
    } else {
      // 使用默认值
      settings.forEach(item => {
        visibility.value[item.id] = item.defaultVisible
      })
    }
  } catch {
    // 出错则使用默认值
    settings.forEach(item => {
      visibility.value[item.id] = item.defaultVisible
    })
  }
}

// 保存设置到 localStorage
const saveSettings = () => {
  try {
    localStorage.setItem('profile_visibility', JSON.stringify(visibility.value))
  } catch {
    // 忽略错误
  }
}

// 切换可见性
const toggleVisibility = (id: string) => {
  visibility.value[id] = !visibility.value[id]
  saveSettings()
}

// 重置所有设置
const resetSettings = () => {
  settings.forEach(item => {
    visibility.value[item.id] = item.defaultVisible
  })
  saveSettings()
}

// 计算隐藏的数量
const hiddenCount = computed(() => {
  return Object.values(visibility.value).filter(v => !v).length
})

// 监听显示状态，每次打开时刷新
watch(() => props.show, (isShow) => {
  if (isShow) {
    loadSettings()
  }
})

// 关闭面板
const close = () => {
  emit('update:show', false)
}

onMounted(() => {
  loadSettings()
})

// 暴露方法供父组件使用
defineExpose({
  getVisibility: () => visibility.value,
  loadSettings
})
</script>

<template>
  <BottomSheet
    :show="show"
    @update:show="close"
    :max-height="'70vh'"
    close-on-mask-click
    close-on-swipe-down
  >
    <template #default>
      <!-- 头部 -->
      <div class="settings-header">
        <div class="header-icon">
          <Settings :size="20" />
        </div>
        <div class="header-text">
          <h3 class="header-title">个人中心设置</h3>
          <p class="header-subtitle">自定义显示内容</p>
        </div>
        <button
          v-if="hiddenCount > 0"
          @click="resetSettings"
          class="reset-btn"
        >
          <RotateCcw :size="14" />
          重置
        </button>
      </div>

      <!-- 设置列表 -->
      <div class="settings-list">
        <div
          v-for="item in settings"
          :key="item.id"
          class="setting-item"
          @click="toggleVisibility(item.id)"
        >
          <div class="setting-info">
            <span class="setting-label">{{ item.label }}</span>
            <span class="setting-desc">{{ item.description }}</span>
          </div>
          <div class="setting-toggle" :class="{ 'is-off': !visibility[item.id] }">
            <Eye v-if="visibility[item.id]" :size="16" class="toggle-icon" />
            <EyeOff v-else :size="16" class="toggle-icon off" />
          </div>
        </div>
      </div>

      <!-- 提示信息 -->
      <div class="settings-tip">
        <span v-if="hiddenCount === 0">当前显示所有模块</span>
        <span v-else>已隐藏 {{ hiddenCount }} 个模块</span>
      </div>
    </template>
  </BottomSheet>
</template>

<style scoped>
/* ==================== 头部 ==================== */
.settings-header {
  display: flex;
  align-items: center;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-3, 12px) var(--neo-space-4, 16px);
  padding-bottom: var(--neo-space-2, 8px);
  border-bottom: 1px solid var(--neo-divider, rgba(255, 255, 255, 0.06));
}

.header-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--neo-radius-sm, 12px);
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-primary, #10B981);
}

.header-text {
  flex: 1;
}

.header-title {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  margin: 0 0 2px 0;
}

.header-subtitle {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin: 0;
}

.reset-btn {
  display: flex;
  align-items: center;
  gap: var(--neo-space-1, 4px);
  padding: var(--neo-space-1, 4px) var(--neo-space-2, 8px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--neo-border-default, rgba(255, 255, 255, 0.08));
  border-radius: var(--neo-radius-xs, 8px);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
  font-size: var(--neo-font-size-xs, 11px);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.reset-btn:active {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.08));
}

/* ==================== 设置列表 ==================== */
.settings-list {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-1, 4px);
  padding: var(--neo-space-3, 12px) var(--neo-space-4, 16px);
}

.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-3, 12px);
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-sm, 12px);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.setting-item:active {
  background: var(--neo-bg-surface-active, rgba(255, 255, 255, 0.08));
}

.setting-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.setting-label {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
}

.setting-desc {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.setting-toggle {
  width: 32px;
  height: 32px;
  border-radius: var(--neo-radius-xs, 8px);
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.setting-toggle.is-off {
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border-color: var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
}

.toggle-icon {
  color: var(--neo-primary, #10B981);
}

.toggle-icon.off {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

/* ==================== 提示信息 ==================== */
.settings-tip {
  display: flex;
  justify-content: center;
  padding: var(--neo-space-3, 12px) var(--neo-space-4, 16px);
  padding-bottom: var(--neo-space-4, 16px);
}

.settings-tip span {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .setting-item:active {
    background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.05));
  }

  .setting-toggle {
    transition: none;
  }
}
</style>
