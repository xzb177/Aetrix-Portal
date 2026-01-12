<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Eye, Crown, Shield, MoreVertical, ChevronRight, Check, X, Trash2 } from 'lucide-vue-next'

export interface UserCardData {
  id: number
  username: string
  email?: string
  telegram_id?: string
  is_active: boolean
  is_vip: boolean
  is_staff: boolean
  current_plan?: string
  emby_account_count?: number
  created_at: string
  vip_expires_at?: string
}

interface Props {
  user: UserCardData
}

const props = defineProps<Props>()

const emit = defineEmits<{
  click: [user: UserCardData]
  viewDetail: [user: UserCardData]
  toggleStatus: [user: UserCardData, type: 'active' | 'staff']
  delete: [user: UserCardData]
}>()

// 显示更多菜单
const showMenu = ref(false)
const menuBtnRef = ref<HTMLElement | null>(null)
const menuPosition = ref({ top: 0, left: 0 })

// 格式化时间
const formatTime = (dateStr: string) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days}天前`
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

// VIP 状态
const vipStatus = computed(() => {
  if (!props.user.is_vip) return { text: '普通', color: 'gray' }
  if (!props.user.vip_expires_at) return { text: 'VIP', color: 'warning' }
  const expiry = new Date(props.user.vip_expires_at)
  const now = new Date()
  const days = Math.ceil((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
  if (days <= 0) return { text: '已过期', color: 'danger' }
  if (days <= 7) return { text: `${days}天到期`, color: 'danger' }
  if (days <= 30) return { text: `${days}天到期`, color: 'warning' }
  return { text: 'VIP', color: 'warning' }
})

// 活跃状态
const activeStatus = computed(() => ({
  text: props.user.is_active ? '活跃' : '禁用',
  color: props.user.is_active ? 'success' : 'gray'
}))

// 快捷操作菜单
const menuItems = computed(() => [
  {
    icon: Eye,
    label: '查看详情',
    action: () => emit('viewDetail', props.user)
  },
  {
    icon: props.user.is_staff ? X : Check,
    label: props.user.is_staff ? '取消管理员' : '设为管理员',
    action: () => emit('toggleStatus', props.user, 'staff')
  },
  {
    icon: props.user.is_active ? X : Check,
    label: props.user.is_active ? '禁用用户' : '激活用户',
    action: () => emit('toggleStatus', props.user, 'active')
  },
  {
    icon: Trash2,
    label: '删除用户',
    action: () => emit('delete', props.user),
    danger: true
  }
])

// 计算菜单位置（用于 fixed 定位）
function updateMenuPosition() {
  if (!menuBtnRef.value) return

  const rect = menuBtnRef.value.getBoundingClientRect()
  const menuWidth = 140
  const menuHeight = 200 // 估算高度
  const safeMargin = 8

  let top = rect.bottom + safeMargin
  let left = rect.right - menuWidth

  // 检查是否超出底部
  if (top + menuHeight > window.innerHeight - safeMargin) {
    // 改为向上弹出
    top = rect.top - menuHeight - safeMargin
  }

  // 检查是否超出左边界
  if (left < safeMargin) {
    left = safeMargin
  }

  // 检查是否超出右边界
  if (left + menuWidth > window.innerWidth - safeMargin) {
    left = window.innerWidth - menuWidth - safeMargin
  }

  menuPosition.value = { top, left }
}

function handleCardClick() {
  emit('click', props.user)
}

function handleViewClick(e: Event) {
  e.stopPropagation()
  emit('viewDetail', props.user)
}

async function toggleMenu(e: Event) {
  e.stopPropagation()
  showMenu.value = !showMenu.value

  if (showMenu.value) {
    // 等待 DOM 更新后计算位置
    await nextTick()
    updateMenuPosition()
  }
}

function handleMenuItem(item: any) {
  showMenu.value = false
  item.action()
}

// 点击外部关闭菜单
function handleClickOutside(e: Event) {
  if (!showMenu.value) return
  const target = e.target as HTMLElement
  if (menuBtnRef.value && !menuBtnRef.value.contains(target)) {
    showMenu.value = false
  }
}

// 滚动时关闭菜单
function handleScroll() {
  if (showMenu.value) {
    showMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('scroll', handleScroll, true)
  window.addEventListener('resize', () => {
    if (showMenu.value) {
      showMenu.value = false
    }
  })
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('scroll', handleScroll, true)
})
</script>

<template>
  <div class="user-card" @click="handleCardClick">
    <!-- 左侧头像区域 -->
    <div class="user-avatar">
      <div class="avatar-text">{{ user.username.charAt(0).toUpperCase() }}</div>
      <div v-if="user.is_staff" class="staff-badge">
        <Shield :size="10" />
      </div>
    </div>

    <!-- 主要内容 -->
    <div class="user-content">
      <!-- 第一行：用户名 + 状态标签 -->
      <div class="user-primary">
        <span class="user-name">{{ user.username }}</span>
        <div class="user-tags">
          <span v-if="user.is_vip" class="tag tag-vip">
            <Crown :size="10" />
            <span>{{ vipStatus.text }}</span>
          </span>
          <span :class="['tag', `tag-${activeStatus.color}`]">
            {{ activeStatus.text }}
          </span>
        </div>
      </div>

      <!-- 第二行：邮箱 + ID -->
      <div class="user-secondary">
        <span class="user-email">{{ user.email || '未设置邮箱' }}</span>
        <span class="user-id">ID: {{ user.id }}</span>
      </div>

      <!-- 第三行：额外信息（套餐 + Emby 数量） -->
      <div v-if="user.current_plan || user.emby_account_count" class="user-meta">
        <span v-if="user.current_plan" class="meta-item">
          <Crown :size="12" />
          {{ user.current_plan }}
        </span>
        <span v-if="user.emby_account_count" class="meta-item">
          <Eye :size="12" />
          {{ user.emby_account_count }} 个账号
        </span>
        <span class="meta-item meta-time">
          {{ formatTime(user.created_at) }}
        </span>
      </div>
    </div>

    <!-- 右侧操作区 -->
    <div class="user-actions">
      <button class="view-btn" @click="handleViewClick">
        <Eye :size="18" />
      </button>
      <div class="menu-wrapper">
        <button
          ref="menuBtnRef"
          class="menu-btn"
          :class="{ 'menu-active': showMenu }"
          @click="toggleMenu"
        >
          <MoreVertical :size="18" />
        </button>
      </div>
    </div>
  </div>

  <!-- 使用 Teleport 将菜单传送到 body，避免定位问题 -->
  <Teleport to="body">
    <Transition name="menu">
      <div
        v-if="showMenu"
        class="menu-dropdown menu-dropdown-fixed"
        :style="{ top: `${menuPosition.top}px`, left: `${menuPosition.left}px` }"
        @click.stop
      >
        <div
          v-for="item in menuItems"
          :key="item.label"
          :class="['menu-item', { 'menu-item-danger': item.danger }]"
          @click="handleMenuItem(item)"
        >
          <component :is="item.icon" :size="16" />
          <span>{{ item.label }}</span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.user-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  background: rgba(20, 21, 26, 0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  cursor: pointer;
  transition: all 150ms ease;
}

.user-card:active {
  background: rgba(255, 255, 255, 0.05);
  transform: scale(0.99);
}

/* 头像 */
.user-avatar {
  position: relative;
  width: 44px;
  height: 44px;
  flex-shrink: 0;
}

.avatar-text {
  width: 100%;
  height: 100%;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 600;
}

.staff-badge {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #f59e0b;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--bg-surface);
}

/* 内容区 */
.user-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.user-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.user-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.user-tags {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
}

.tag-vip {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.tag-warning {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.tag-success {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.tag-gray {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-tertiary);
}

.tag-danger {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.user-secondary {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.user-email {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.user-id {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: monospace;
}

.user-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.meta-time {
  margin-left: auto;
}

/* 操作区 */
.user-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.view-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 150ms ease;
}

.view-btn:active {
  background: rgba(99, 102, 241, 0.2);
  transform: scale(0.95);
}

/* 菜单按钮容器 - 不再需要定位 */
.menu-wrapper {
  /* position: relative;  - 移除，不再需要 */
}

.menu-btn {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 150ms ease;
}

.menu-btn:active,
.menu-btn.menu-active {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

/* 下拉菜单 - 默认 absolute 定位（保留兼容性） */
.menu-dropdown {
  min-width: 140px;
  background: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: 12px;
  padding: 6px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
  z-index: 9999;
}

/* Fixed 定位（用于 Teleport 版本，解决 iOS Safari 定位问题） */
.menu-dropdown-fixed {
  position: fixed;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-primary);
  cursor: pointer;
  transition: background 100ms ease;
}

.menu-item:active {
  background: var(--bg-card-hover);
}

.menu-item-danger {
  color: #ef4444;
}

.menu-item-danger:active {
  background: rgba(239, 68, 68, 0.1);
}

/* 菜单动画 */
.menu-enter-active,
.menu-leave-active {
  transition: all 150ms ease;
}

.menu-enter-from,
.menu-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.95);
}

.menu-enter-to,
.menu-leave-from {
  opacity: 1;
  transform: translateY(0) scale(1);
}

/* 响应式 */
@media (max-width: 360px) {
  .user-email {
    max-width: 140px;
  }

  .user-meta {
    display: none;
  }
}
</style>
