<script setup lang="ts">
/**
 * AdaptiveDock - 自适应快捷入口 Dock
 *
 * 特性：
 * - macOS Dock 风格
 * - 根据使用频次自动排序
 * - 图标放大动画
 * - LocalStorage 存储点击频次
 * - 支持自定义配置
 */
import { ref, computed, onMounted } from 'vue'
import { Wallet, Users, Ticket, MessageCircle, Settings, LogOut, ChevronRight } from 'lucide-vue-next'
import { useRouter } from 'vue-router'

interface DockItem {
  id: string
  label: string
  icon: any
  to?: string
  action?: () => void
  color: string
  defaultIndex?: number
}

interface Props {
  showLogout?: boolean
  showSettings?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showLogout: true,
  showSettings: true
})

const emit = defineEmits<{
  logout: []
  settings: []
}>()

const router = useRouter()

// Dock 配置
const dockConfig: DockItem[] = [
  { id: 'recharge', label: '余额充值', icon: Wallet, to: '/recharge', color: 'text-emerald-400', defaultIndex: 0 },
  { id: 'invite', label: '邀请好友', icon: Users, to: '/invite', color: 'text-blue-400', defaultIndex: 1 },
  { id: 'exchange', label: '兑换码', icon: Ticket, to: '/exchange-code', color: 'text-amber-400', defaultIndex: 2 },
  { id: 'support', label: '联系客服', icon: MessageCircle, to: '/tickets', color: 'text-purple-400', defaultIndex: 3 },
]

// 点击频次
const clickCounts = ref<Record<string, number>>({})

// 排序后的 Dock 项目
const sortedDockItems = computed(() => {
  const items = [...dockConfig].map(item => ({
    ...item,
    count: clickCounts.value[item.id] || 0
  }))

  // 按点击频次排序，频次相同则按默认顺序
  items.sort((a, b) => {
    if (a.count !== b.count) {
      return b.count - a.count
    }
    return (a.defaultIndex || 0) - (b.defaultIndex || 0)
  })

  return items
})

// 处理点击
const handleClick = (item: DockItem) => {
  // 增加点击计数
  clickCounts.value[item.id] = (clickCounts.value[item.id] || 0) + 1
  saveClickCounts()

  // 执行跳转或动作
  if (item.to) {
    router.push(item.to)
  } else if (item.action) {
    item.action()
  }
}

// 处理登出
const handleLogout = () => {
  emit('logout')
}

// 处理设置
const handleSettings = () => {
  emit('settings')
}

// 从 localStorage 加载点击计数
const loadClickCounts = () => {
  try {
    const stored = localStorage.getItem('dock_click_counts')
    if (stored) {
      clickCounts.value = JSON.parse(stored)
    }
  } catch {
    // 忽略错误
  }
}

// 保存点击计数到 localStorage
const saveClickCounts = () => {
  try {
    localStorage.setItem('dock_click_counts', JSON.stringify(clickCounts.value))
  } catch {
    // 忽略错误
  }
}

// 重置排序（调试用）
const resetSort = () => {
  clickCounts.value = {}
  saveClickCounts()
}

onMounted(() => {
  loadClickCounts()
})

defineExpose({
  resetSort
})
</script>

<template>
  <div class="adaptive-dock">
    <h3 class="dock-title">快捷入口</h3>

    <!-- Dock 容器 -->
    <div class="dock-container">
      <!-- Dock 项目 -->
      <div
        v-for="item in sortedDockItems"
        :key="item.id"
        class="dock-item"
        @click="handleClick(item)"
      >
        <div class="dock-icon" :class="item.color">
          <component :is="item.icon" :size="22" />
        </div>
        <span class="dock-label">{{ item.label }}</span>
        <ChevronRight :size="14" class="dock-arrow" />
      </div>

      <!-- 登出按钮（可选） -->
      <button
        v-if="showLogout"
        class="dock-item dock-logout"
        @click="handleLogout"
      >
        <div class="dock-icon text-rose-400">
          <LogOut :size="22" />
        </div>
        <span class="dock-label">退出登录</span>
      </button>

      <!-- 设置按钮 -->
      <button
        v-if="showSettings"
        class="dock-item dock-settings"
        @click="handleSettings"
      >
        <div class="dock-icon text-gray-400">
          <Settings :size="22" />
        </div>
        <span class="dock-label">显示设置</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 容器 ==================== */
.adaptive-dock {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-2, 8px);
  width: 100%;
}

.dock-title {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  padding: 0 var(--neo-space-1, 4px);
}

/* ==================== Dock 容器 ==================== */
.dock-container {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-1, 4px);
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--neo-space-1, 4px);
  overflow: hidden;
}

/* ==================== Dock 项目 ==================== */
.dock-item {
  display: flex;
  align-items: center;
  gap: var(--neo-space-2, 8px);
  padding: var(--neo-space-2, 8px) var(--neo-space-3, 12px);
  background: transparent;
  border: none;
  border-radius: var(--neo-radius-sm, 12px);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) ease;
  -webkit-tap-highlight-color: transparent;
  width: 100%;
  text-align: left;
}

.dock-item:hover {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.05));
}

.dock-item:active {
  background: var(--neo-bg-surface-active, rgba(255, 255, 255, 0.08));
  transform: scale(0.99);
}

/* Dock 图标 */
.dock-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--neo-radius-xs, 8px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform var(--neo-duration-fast, 150ms) ease;
}

.dock-item:hover .dock-icon {
  transform: scale(1.1);
}

.dock-item:active .dock-icon {
  transform: scale(1.05);
}

/* 图标颜色 */
.text-emerald-400 {
  color: #34d399;
}

.text-blue-400 {
  color: #60a5fa;
}

.text-amber-400 {
  color: #fbbf24;
}

.text-purple-400 {
  color: #c084fc;
}

.text-rose-400 {
  color: #fb7185;
}

.text-gray-400 {
  color: #9ca3af;
}

/* Dock 标签 */
.dock-label {
  flex: 1;
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
}

/* Dock 箭头 */
.dock-arrow {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  transition: transform var(--neo-duration-fast, 150ms) ease;
  flex-shrink: 0;
}

.dock-item:hover .dock-arrow {
  transform: translateX(2px);
}

/* 登出按钮特殊样式 */
.dock-logout {
  margin-top: var(--neo-space-1, 4px);
  border-top: 1px solid var(--neo-divider, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-xs, 8px);
}

.dock-logout:hover {
  background: rgba(239, 68, 68, 0.05);
}

.dock-logout .dock-label {
  color: var(--neo-danger, #EF4444);
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .dock-item:active {
    transform: none;
  }

  .dock-item:hover .dock-icon,
  .dock-item:active .dock-icon {
    transform: none;
  }

  .dock-arrow {
    transition: none;
  }
}
</style>
