<script setup lang="ts">
/**
 * 通知中心组件 - 体验抛光版 v2
 *
 * 改进点：
 * - 筛选标签（全部/未读）
 * - 空状态设计（5套场景+引导按钮）
 * - Toast 反馈集成
 * - 删除按钮移动端常驻
 * - 清空确认弹窗（替换原生confirm）
 * - Loading skeleton
 * - 下拉刷新手势识别
 * - 滑动操作（左滑删除/标已读）
 * - 消息分组（按日期）
 * - 未读消息优先置顶
 */
import { ref, computed, onMounted, watch, Teleport, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  Bell,
  X,
  Check,
  Trash2,
  MessageSquare,
  Ticket,
  Megaphone,
  Gift,
  AlertCircle,
  Clock,
  ChevronDown,
  Mailbox,
  Sparkles,
  RefreshCw,
  ChevronRight
} from 'lucide-vue-next'
import { useWebSocket, type NotificationEvent } from '@/composables/useWebSocket'
import { messageApi } from '@/api'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const {
  unreadCount,
  notifications,
  markAsRead,
  clearNotifications
} = useWebSocket()

const { success, error: toastError, info } = useToast()

// 本地状态
const isOpen = ref(false)
const isLoading = ref(false)
const isRefreshing = ref(false)
const isLoadingFailed = ref(false)
const messages = ref<any[]>([])
const selectedMessage = ref<any | null>(null)
const showDetailModal = ref(false)
const showClearDialog = ref(false)
const filterType = ref<'all' | 'unread'>('all')

// 下拉刷新状态
const listContainer = ref<HTMLElement | null>(null)
const pullDistance = ref(0)
const isPulling = ref(false)
const pullThreshold = 80
const touchStartY = ref(0)
const isDragging = ref(false)

// 用户状态（用于空状态判断）
const hasSubscription = ref(false)
const hasEmbyAccount = ref(false)

// 通知类型图标映射
const typeIcons: Record<string, any> = {
  'station.system': AlertCircle,
  'station.ticket': Ticket,
  'station.announcement': Megaphone,
  'station.subscription': Gift,
  'station.media_seek': Clock,
  'station.exchange_code': Gift,
}

// 通知类型颜色映射
const typeColors: Record<string, string> = {
  'station.system': 'text-blue-400',
  'station.ticket': 'text-orange-400',
  'station.announcement': 'text-purple-400',
  'station.subscription': 'text-emerald-400',
  'station.media_seek': 'text-cyan-400',
  'station.exchange_code': 'text-yellow-400',
}

// 计算属性
const allItems = ref<any[]>([])
const unreadItems = ref<any[]>([])

// 消息合并与排序（未读优先）
const sortedItems = computed(() => {
  const realtimeNotifs = notifications.value.map(n => ({
    id: `rt-${n.createdAt.getTime()}`,
    title: n.title,
    content: n.message,
    message_type: n.type.replace('station.', ''),
    created_at: n.createdAt.toISOString(),
    is_read: n.read,
    is_realtime: true
  }))

  const combined = [...realtimeNotifs, ...messages.value]

  // 未读优先排序
  return combined.sort((a, b) => {
    if (a.is_read !== b.is_read) {
      return a.is_read ? 1 : -1
    }
    // 同状态按时间倒序
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })
})

allItems.value = sortedItems.value
unreadItems.value = sortedItems.value.filter((m: any) => !m.is_read)

const displayItems = computed(() => {
  if (filterType.value === 'unread') {
    return unreadItems.value
  }
  return allItems.value
})

// 消息分组（按日期）
const groupedMessages = computed(() => {
  const groups: Record<string, any[]> = {}
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = today - 86400000
  const thisWeek = today - 6 * 86400000

  displayItems.value.forEach(msg => {
    const msgTime = new Date(msg.created_at).getTime()
    let groupKey = ''

    if (msgTime >= today) {
      groupKey = 'today'
    } else if (msgTime >= yesterday) {
      groupKey = 'yesterday'
    } else if (msgTime >= thisWeek) {
      groupKey = 'week'
    } else {
      groupKey = 'older'
    }

    if (!groups[groupKey]) {
      groups[groupKey] = []
    }
    groups[groupKey].push(msg)
  })

  // 转换为数组格式，按顺序返回
  const groupLabels = {
    today: '今天',
    yesterday: '昨天',
    week: '本周',
    older: '更早'
  }

  return Object.entries(groups)
    .map(([key, items]) => ({
      key,
      label: groupLabels[key as keyof typeof groupLabels],
      items
    }))
    .sort((a, b) => {
      const order = ['today', 'yesterday', 'week', 'older']
      return order.indexOf(a.key) - order.indexOf(b.key)
    })
})

const filteredCount = computed(() => {
  if (filterType.value === 'unread') {
    return unreadItems.value.length
  }
  return allItems.value.length
})

// 空状态场景判断
const emptyStateType = computed(() => {
  if (isLoadingFailed.value) return 'error'
  if (!hasSubscription.value) return 'no-subscription'
  if (hasSubscription.value && !hasEmbyAccount.value) return 'no-account'
  if (showClearDialog.value && messages.value.length === 0) return 'cleared'
  return 'empty'
})

const emptyStateConfig = computed(() => {
  const configs: Record<string, { icon: any; title: string; desc: string; btnText: string; btnAction: () => void }> = {
    'no-subscription': {
      icon: Gift,
      title: '还没有收到任何通知',
      desc: '先去订阅获取专属福利吧',
      btnText: '去查看套餐',
      btnAction: () => { router.push('/subscription'); isOpen.value = false }
    },
    'no-account': {
      icon: MessageSquare,
      title: '暂无消息通知',
      desc: '先去领取您的 Emby 账号',
      btnText: '去领取账号',
      btnAction: () => { router.push('/home'); isOpen.value = false }
    },
    'cleared': {
      icon: Sparkles,
      title: '通知已全部清空',
      desc: '享受清净时光',
      btnText: '我知道了',
      btnAction: () => { isOpen.value = false }
    },
    'empty': {
      icon: Mailbox,
      title: '暂时没有消息',
      desc: '一切都正常运行',
      btnText: '去订阅',
      btnAction: () => { router.push('/subscription'); isOpen.value = false }
    },
    'error': {
      icon: RefreshCw,
      title: '加载失败',
      desc: '请检查网络连接',
      btnText: '重新加载',
      btnAction: () => { loadMessages() }
    }
  }
  return configs[emptyStateType.value] || configs.empty
})

// 下拉刷新相关
const pullProgress = computed(() => {
  return Math.min(pullDistance.value / pullThreshold, 1)
})

const canRefresh = computed(() => {
  return pullDistance.value >= pullThreshold
})

// 触摸事件处理
function handleTouchStart(e: TouchEvent) {
  if (!listContainer.value) return
  const scrollTop = listContainer.value.scrollTop
  // 只在顶部时才能下拉刷新
  if (scrollTop === 0) {
    touchStartY.value = e.touches[0].clientY
    isDragging.value = true
  }
}

function handleTouchMove(e: TouchEvent) {
  if (!isDragging.value) return

  const currentY = e.touches[0].clientY
  const deltaY = currentY - touchStartY.value

  // 只能向下拉
  if (deltaY > 0) {
    // 增加阻尼效果
    pullDistance.value = deltaY * 0.5
    isPulling.value = true
  }
}

function handleTouchEnd() {
  if (!isDragging.value) return
  isDragging.value = false

  if (canRefresh.value && !isRefreshing.value) {
    performRefresh()
  }

  // 重置状态
  pullDistance.value = 0
  isPulling.value = false
}

async function performRefresh() {
  isRefreshing.value = true
  pullDistance.value = 0
  isPulling.value = false

  try {
    const response = await messageApi.getMessages({ limit: 20 })
    const newMessages = response.data?.data || []
    const oldLength = messages.value.length

    messages.value = newMessages
    isLoadingFailed.value = false

    const newCount = newMessages.length - oldLength
    if (newCount > 0) {
      info(`已更新 ${newCount} 条新消息`)
    } else {
      info('暂无新消息')
    }
  } catch (err) {
    isLoadingFailed.value = true
    toastError('刷新失败，请重试')
  } finally {
    isRefreshing.value = false
  }
}

// 滑动操作状态
const swipedItem = ref<string | null>(null)
const swipeX = ref(0)
const swipeStartX = ref(0)
const isSwiping = ref(false)

function handleSwipeStart(id: string, e: TouchEvent | MouseEvent) {
  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
  swipeStartX.value = clientX
  isSwiping.value = true
  swipedItem.value = id
}

function handleSwipeMove(e: TouchEvent | MouseEvent) {
  if (!isSwiping.value || swipedItem.value === null) return

  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
  const deltaX = clientX - swipeStartX.value

  // 只允许向左滑动
  if (deltaX < 0) {
    swipeX.value = Math.max(deltaX, -120) // 最大滑动距离
  } else {
    swipeX.value = 0
  }
}

function handleSwipeEnd(id: string) {
  if (!isSwiping.value) return

  // 如果滑动超过阈值，执行删除
  if (swipeX.value < -80) {
    const item = displayItems.value.find(m => m.id === id)
    if (item) {
      deleteMessage(item)
    }
  }

  // 重置
  swipeX.value = 0
  isSwiping.value = false
  swipedItem.value = null
}

function resetSwipe() {
  swipeX.value = 0
  isSwiping.value = false
  swipedItem.value = null
}

// 切换通知面板
function togglePanel() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    loadMessages()
  }
}

// 加载消息列表
async function loadMessages() {
  isLoading.value = true
  isLoadingFailed.value = false
  try {
    const response = await messageApi.getMessages({ limit: 20 })
    messages.value = response.data?.data || []
  } catch (err) {
    console.error('加载消息失败:', err)
    isLoadingFailed.value = true
    toastError('加载失败，请检查网络')
  } finally {
    isLoading.value = false
  }
}

// 打开消息详情
async function openMessageDetail(msg: any) {
  // 如果正在滑动，不打开详情
  if (isSwiping.value && Math.abs(swipeX.value) > 10) {
    resetSwipe()
    return
  }

  selectedMessage.value = msg
  showDetailModal.value = true

  // 如果未读，标记为已读
  if (!msg.is_read) {
    try {
      if (msg.is_realtime) {
        markAsRead(msg.id.replace('rt-', ''))
      } else {
        await messageApi.markAsRead(msg.id)
      }
      msg.is_read = true
      success('已标记为已读')
    } catch (err) {
      toastError('标记失败，请重试')
    }
  }
}

// 关闭详情弹窗
function closeDetail() {
  showDetailModal.value = false
  selectedMessage.value = null
}

// 删除消息（带确认）
async function deleteMessage(msg: any) {
  if (msg.is_realtime) {
    const idx = notifications.value.findIndex(n =>
      n.createdAt.getTime() === parseInt(msg.id.replace('rt-', ''))
    )
    if (idx > -1) {
      notifications.value.splice(idx, 1)
      success('消息已删除')
    }
    return
  }

  try {
    await messageApi.delete(msg.id)
    messages.value = messages.value.filter(m => m.id !== msg.id)

    if (selectedMessage.value?.id === msg.id) {
      closeDetail()
    }

    success('消息已删除')
  } catch (err) {
    toastError('删除失败，请重试')
  }
}

// 标记单个为已读
async function handleMarkAsRead(msg: any) {
  if (msg.is_read) return

  try {
    if (msg.is_realtime) {
      markAsRead(msg.id.replace('rt-', ''))
    } else {
      await messageApi.markAsRead(msg.id)
    }
    msg.is_read = true
    success('已标记为已读')
  } catch (err) {
    toastError('操作失败，请重试')
  }
}

// 标记所有为已读
async function handleMarkAllRead() {
  try {
    await messageApi.markAllRead()
    messages.value.forEach(m => m.is_read = true)
    notifications.value.forEach(n => n.read = true)

    const unread = unreadItems.value.length
    success(unread > 0 ? `已将 ${unread} 条消息标记为已读` : '已全部标记为已读')
  } catch (err) {
    toastError('操作失败，请重试')
  }
}

// 清空所有通知（显示确认弹窗）
function handleClearAllClick() {
  showClearDialog.value = true
}

// 确认清空
async function confirmClearAll() {
  try {
    clearNotifications()
    messages.value = []

    const total = allItems.value.length
    success(total > 0 ? '已清空所有通知' : '通知已清空')
  } catch (err) {
    toastError('操作失败，请重试')
  } finally {
    showClearDialog.value = false
  }
}

// 点击通知跳转
function handleNotificationClick(notification: NotificationEvent) {
  markAsRead(notification)

  const type = notification.type
  const relatedId = notification.data?.related_id

  if (type === 'station.ticket' && relatedId) {
    router.push(`/tickets/${relatedId}`)
  } else if (type === 'station.announcement') {
    router.push('/announcements')
  } else if (type === 'station.subscription') {
    router.push('/subscription')
  } else if (type === 'station.media_seek') {
    router.push('/request')
  }

  isOpen.value = false
}

// 获取通知图标
function getIcon(type: string) {
  return typeIcons['station.' + type] || Bell
}

// 获取通知颜色
function getColor(type: string) {
  return typeColors['station.' + type] || 'text-zinc-400'
}

// 格式化时间
function formatTime(timestamp: string) {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`

  return date.toLocaleDateString('zh-CN')
}

// 格式化完整时间
function formatFullTime(timestamp: string) {
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

// 获取消息类型文本
function getTypeText(type: string): string {
  const map: Record<string, string> = {
    'station.system': '系统通知',
    'station.ticket': '工单消息',
    'station.announcement': '公告',
    'station.subscription': '订阅',
    'station.media_seek': '求片',
    'station.exchange_code': '兑换',
    'system': '系统',
    'ticket': '工单',
    'announcement': '公告',
    'subscription': '订阅',
    'media_seek': '求片',
    'exchange_code': '兑换',
  }
  return map['station.' + type] || map[type] || '通知'
}

// 防止事件冒泡（避免点击列表项时关闭面板）
function stopPropagation(e: Event) {
  e.stopPropagation()
}

onMounted(() => {
  messageApi.getUnreadCount().then(res => {
    unreadCount.value = res?.data?.unread_count || 0
  }).catch(() => {
    unreadCount.value = 0
  })

  hasSubscription.value = true
  hasEmbyAccount.value = true
})

// 锁定/解锁 body scroll
watch(isOpen, (newValue) => {
  if (newValue) {
    if (window.innerWidth <= 768) {
      document.body.style.overflow = 'hidden'
      document.body.style.position = 'fixed'
      document.body.style.width = '100%'
    }
  } else {
    document.body.style.overflow = ''
    document.body.style.position = ''
    document.body.style.width = ''
  }
})
</script>

<template>
  <div class="notification-center">
    <!-- 通知按钮 -->
    <button
      class="notification-btn"
      @click="togglePanel"
      :class="{ 'has-unread': unreadCount > 0 }"
    >
      <Bell :size="20" />
      <span
        v-if="unreadCount > 0"
        class="badge"
      >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
    </button>

    <!-- Teleport 到 body -->
    <Teleport to="body">
      <!-- 移动端遮罩层 -->
      <Transition name="overlay">
        <div v-if="isOpen" class="panel-overlay" @click="isOpen = false"></div>
      </Transition>

      <!-- 通知面板 -->
      <Transition name="dropdown">
        <div v-if="isOpen" class="notification-panel" @click="stopPropagation">
          <!-- 面板头部 -->
          <div class="panel-header">
            <h3>通知中心</h3>
            <div class="header-actions">
              <button
                v-if="unreadCount > 0"
                class="icon-btn"
                @click="handleMarkAllRead"
                title="全部标为已读"
              >
                <Check :size="16" />
              </button>
              <button
                class="icon-btn"
                @click="handleClearAllClick"
                title="清空通知"
              >
                <Trash2 :size="16" />
              </button>
              <button
                class="icon-btn"
                @click="isOpen = false"
                title="关闭"
              >
                <X :size="16" />
              </button>
            </div>
          </div>

          <!-- 筛选标签 -->
          <div class="filter-tabs">
            <button
              class="filter-tab"
              :class="{ active: filterType === 'all' }"
              @click="filterType = 'all'"
            >
              <span class="tab-text">全部</span>
              <span class="tab-count">{{ allItems.length }}</span>
            </button>
            <button
              class="filter-tab"
              :class="{ active: filterType === 'unread' }"
              @click="filterType = 'unread'"
            >
              <span class="tab-text">未读</span>
              <span class="tab-count unread-badge">{{ unreadItems.length }}</span>
            </button>
          </div>

          <!-- 下拉刷新指示器 -->
          <div class="pull-indicator" :style="{ transform: `translateY(${pullDistance}px)` }">
            <Transition name="refresh-icon">
              <RefreshCw
                v-if="canRefresh || isRefreshing"
                :size="18"
                :class="{ 'animate-spin': isRefreshing }"
              />
            </Transition>
          </div>

          <!-- 列表区域 -->
          <div
            ref="listContainer"
            class="list-container"
            :class="{ 'is-loading': isLoading || isRefreshing }"
            @touchstart="handleTouchStart"
            @touchmove="handleTouchMove"
            @touchend="handleTouchEnd"
          >
            <!-- Loading Skeleton -->
            <div v-if="isLoading && !isLoadingFailed" class="skeleton-list">
              <div v-for="i in 3" :key="i" class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                  <div class="skeleton-type"></div>
                  <div class="skeleton-title"></div>
                  <div class="skeleton-desc"></div>
                </div>
                <div class="skeleton-dot"></div>
              </div>
            </div>

            <!-- 空状态 -->
            <div
              v-else-if="displayItems.length === 0"
              class="empty-state"
            >
              <div class="empty-icon">
                <component :is="emptyStateConfig.icon" :size="32" />
              </div>
              <h4 class="empty-title">{{ emptyStateConfig.title }}</h4>
              <p class="empty-desc">{{ emptyStateConfig.desc }}</p>
              <button
                class="empty-btn"
                @click="emptyStateConfig.btnAction"
              >
                {{ emptyStateConfig.btnText }}
              </button>
            </div>

            <!-- 分组消息列表 -->
            <div v-else class="grouped-list">
              <div
                v-for="group in groupedMessages"
                :key="group.key"
                class="message-group"
              >
                <!-- 分组标题 -->
                <div class="group-label">{{ group.label }}</div>

                <!-- 消息列表 -->
                <div class="notification-list">
                  <div
                    v-for="msg in group.items"
                    :key="msg.id"
                    class="notification-item"
                    :class="{
                      unread: !msg.is_read,
                      realtime: msg.is_realtime,
                      swiped: swipedItem === msg.id
                    }"
                    :style="{ transform: swipedItem === msg.id ? `translateX(${swipeX}px)` : '' }"
                    @click="openMessageDetail(msg)"
                    @touchstart.passive="handleSwipeStart(msg.id, $event)"
                    @touchmove.passive="handleSwipeMove"
                    @touchend="handleSwipeEnd(msg.id)"
                    @mousedown="handleSwipeStart(msg.id, $event as any)"
                    @mousemove="handleSwipeMove"
                    @mouseup="handleSwipeEnd(msg.id)"
                    @mouseleave="resetSwipe"
                  >
                    <div class="swipe-actions">
                      <button class="swipe-btn delete" @click.stop="deleteMessage(msg)">
                        <Trash2 :size="16" />
                        删除
                      </button>
                    </div>

                    <div class="item-content">
                      <component
                        :is="getIcon(msg.message_type)"
                        :size="18"
                        :class="['notification-icon', getColor(msg.message_type)]"
                      />
                      <div class="notification-content">
                        <div class="notification-header">
                          <span class="notification-type">{{ getTypeText(msg.message_type) }}</span>
                          <span class="notification-time">{{ formatTime(msg.created_at) }}</span>
                        </div>
                        <div class="notification-title">{{ msg.title }}</div>
                        <div class="notification-message">{{ msg.content }}</div>
                      </div>
                      <div v-if="!msg.is_read" class="unread-dot"></div>

                      <!-- 右侧箭头（提示可滑动） -->
                      <ChevronRight :size="16" class="swipe-hint" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 面板底部 -->
          <div class="panel-footer">
            <router-link to="/messages" @click="isOpen = false" class="footer-link">
              <span>查看所有消息</span>
              <ChevronDown :size="14" />
            </router-link>
          </div>
        </div>
      </Transition>

      <!-- 清空确认弹窗 -->
      <Transition name="modal">
        <div v-if="showClearDialog" class="modal-overlay" @click="showClearDialog = false">
          <div class="confirm-dialog" @click.stop>
            <div class="confirm-icon">
              <Trash2 :size="24" />
            </div>
            <h3 class="confirm-title">清空通知</h3>
            <p class="confirm-desc">确定要清空所有通知吗？此操作不可撤销</p>
            <div class="confirm-actions">
              <button class="confirm-btn cancel" @click="showClearDialog = false">
                取消
              </button>
              <button class="confirm-btn danger" @click="confirmClearAll">
                确认清空
              </button>
            </div>
          </div>
        </div>
      </Transition>

      <!-- 消息详情弹窗 -->
      <Transition name="modal">
        <div v-if="showDetailModal && selectedMessage" class="modal-overlay" @click="closeDetail">
          <div class="modal-content" @click.stop>
            <div class="modal-header">
              <div class="modal-title-row">
                <div class="modal-icon">
                  <component
                    :is="getIcon(selectedMessage.message_type)"
                    :size="24"
                    :class="getColor(selectedMessage.message_type)"
                  />
                </div>
                <div>
                  <span class="modal-type-badge">
                    {{ getTypeText(selectedMessage.message_type) }}
                  </span>
                  <h2 class="modal-title">{{ selectedMessage.title }}</h2>
                </div>
              </div>
              <button class="modal-close" @click="closeDetail">
                <X :size="20" />
              </button>
            </div>

            <div class="modal-body">
              <div class="modal-meta">
                <span class="modal-time">
                  <Clock :size="14" />
                  {{ formatFullTime(selectedMessage.created_at) }}
                </span>
                <span v-if="selectedMessage.from_user" class="modal-sender">
                  来自：{{ selectedMessage.from_user }}
                </span>
              </div>

              <div class="modal-message">
                {{ selectedMessage.content }}
              </div>
            </div>

            <div class="modal-footer">
              <button class="modal-btn secondary" @click="closeDetail">
                关闭
              </button>
              <button class="modal-btn danger" @click="deleteMessage(selectedMessage)">
                <Trash2 :size="16" />
                删除
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.notification-center {
  position: relative;
}

/* ===== 通知按钮 ===== */
.notification-btn {
  position: relative;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.notification-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.notification-btn.has-unread {
  color: #10b981;
}

.notification-btn:active {
  transform: scale(0.95);
}

.badge {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border-radius: 8px;
  font-size: 10px;
  font-weight: 600;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.4);
}

/* ===== 遮罩层 ===== */
.panel-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 99;
  padding: env(safe-area-inset-top) env(safe-area-inset-right)
          env(safe-area-inset-bottom) env(safe-area-inset-left);
}

.overlay-enter-active,
.overlay-leave-active {
  transition: opacity 0.2s ease;
}

.overlay-enter-from,
.overlay-leave-to {
  opacity: 0;
}

/* ===== 通知面板 ===== */
.notification-panel {
  width: 380px;
  max-width: min(380px, calc(100vw - 32px));
  max-height: 560px;
  background: rgba(26, 26, 26, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  z-index: 100;
  overflow: hidden;
}

/* 桌面端定位 */
@media (min-width: 769px) {
  .notification-panel {
    position: fixed;
    top: calc(64px + 8px);
    right: max(1.5rem, calc((100vw - 1400px) / 2 + 1.5rem));
  }
}

/* 移动端定位 */
@media (max-width: 768px) {
  .notification-panel {
    position: fixed !important;
    top: calc(64px + env(safe-area-inset-top) + 12px) !important;
    left: 50% !important;
    transform: translateX(-50%) !important;
    width: min(92vw, 420px);
    max-width: 420px;
    max-height: min(80vh, calc(100vh - 64px - env(safe-area-inset-top) - 24px));
    right: auto !important;
    margin-left: calc(env(safe-area-inset-left) * -0.5);
    margin-right: calc(env(safe-area-inset-right) * -0.5);
  }
}

/* 面板动画 */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.25s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.98);
}

@media (max-width: 768px) {
  .dropdown-enter-from,
  .dropdown-leave-to {
    transform: scale(0.95);
  }
}

/* ===== 面板头部 ===== */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.panel-header h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #737373;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #ffffff;
}

.icon-btn:active {
  transform: scale(0.95);
}

/* ===== 筛选标签 ===== */
.filter-tabs {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.filter-tab {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #737373;
  font-size: 0.813rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-tab:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
}

.filter-tab.active {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.tab-count {
  font-size: 0.75rem;
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.1);
}

.filter-tab.active .tab-count {
  background: rgba(16, 185, 129, 0.25);
}

/* ===== 下拉刷新指示器 ===== */
.pull-indicator {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #10b981;
  z-index: 10;
  pointer-events: none;
}

.refresh-icon-enter-active,
.refresh-icon-leave-active {
  transition: all 0.2s ease;
}

.refresh-icon-enter-from,
.refresh-icon-leave-to {
  opacity: 0;
  transform: scale(0.5);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ===== 列表容器 ===== */
.list-container {
  flex: 1;
  overflow-y: auto;
  min-height: 200px;
  position: relative;
}

.list-container::-webkit-scrollbar {
  width: 4px;
}

.list-container::-webkit-scrollbar-track {
  background: transparent;
}

.list-container::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
}

.list-container::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}

/* ===== Loading Skeleton ===== */
.skeleton-list {
  padding: 0.75rem 1rem;
}

.skeleton-item {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.875rem;
  border-radius: 12px;
  margin-bottom: 0.5rem;
}

.skeleton-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  flex-shrink: 0;
}

.skeleton-content {
  flex: 1;
}

.skeleton-type {
  height: 12px;
  width: 50px;
  border-radius: 4px;
  background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  margin-bottom: 0.5rem;
}

.skeleton-title {
  height: 14px;
  width: 80%;
  border-radius: 4px;
  background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  margin-bottom: 0.375rem;
}

.skeleton-desc {
  height: 12px;
  width: 60%;
  border-radius: 4px;
  background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
}

.skeleton-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  flex-shrink: 0;
  margin-top: 4px;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ===== 空状态 ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2.5rem 1.5rem;
  text-align: center;
}

.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #525252;
  margin-bottom: 1rem;
}

.empty-title {
  font-size: 1rem;
  font-weight: 500;
  color: #d4d4d4;
  margin: 0 0 0.5rem;
}

.empty-desc {
  font-size: 0.813rem;
  color: #737373;
  margin: 0 0 1.5rem;
  line-height: 1.5;
}

.empty-btn {
  padding: 0.625rem 1.25rem;
  border-radius: 10px;
  border: none;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.empty-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

.empty-btn:active {
  transform: scale(0.97);
}

/* ===== 分组列表 ===== */
.grouped-list {
  padding: 0.5rem 0;
}

.message-group {
  margin-bottom: 0.5rem;
}

.group-label {
  padding: 0.5rem 1.25rem 0.25rem;
  font-size: 0.688rem;
  font-weight: 600;
  color: #525252;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ===== 通知列表 ===== */
.notification-list {
  padding: 0 0.75rem;
}

.notification-item {
  position: relative;
  overflow: hidden;
}

.item-content {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.875rem;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
  border-left: 2px solid transparent;
  background: transparent;
}

.notification-item.unread .item-content {
  background: rgba(255, 255, 255, 0.02);
}

.notification-item.unread .item-content:hover {
  background: rgba(255, 255, 255, 0.04);
  border-left-color: #10b981;
}

.notification-item.realtime .item-content {
  background: rgba(16, 185, 129, 0.05);
}

.notification-item.realtime .item-content:hover {
  background: rgba(16, 185, 129, 0.08);
}

.item-content:active {
  transform: scale(0.98);
}

/* 滑动操作按钮 */
.swipe-actions {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 0;
  overflow: hidden;
  transition: width 0.2s ease;
}

.notification-item.swiped .swipe-actions {
  width: 100px;
}

.swipe-btn {
  width: 100%;
  height: 100%;
  border: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
}

.swipe-btn.delete {
  background: rgba(239, 68, 68, 0.9);
  color: white;
}

.notification-icon {
  flex-shrink: 0;
  margin-top: 2px;
  z-index: 1;
}

.notification-content {
  flex: 1;
  min-width: 0;
  z-index: 1;
}

.notification-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.notification-type {
  font-size: 0.688rem;
  font-weight: 600;
  color: #737373;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.05);
}

.notification-time {
  font-size: 0.688rem;
  color: #525252;
}

.notification-title {
  font-size: 0.875rem;
  font-weight: 500;
  color: #ffffff;
  line-height: 1.3;
  margin-bottom: 0.25rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notification-message {
  font-size: 0.8rem;
  color: #a3a3a3;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.unread-dot {
  position: absolute;
  top: 0.875rem;
  right: 0.875rem;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  flex-shrink: 0;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.5);
  z-index: 1;
}

/* 滑动提示箭头 */
.swipe-hint {
  position: absolute;
  right: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  color: #404040;
  opacity: 0.5;
  z-index: 1;
}

/* 移动端优化滑动 */
@media (max-width: 768px) {
  .notification-item {
    touch-action: pan-y;
  }

  .swipe-hint {
    display: block;
  }
}

@media (min-width: 769px) {
  .swipe-hint {
    display: none;
  }
}

/* ===== 面板底部 ===== */
.panel-footer {
  padding: 0.75rem 1.25rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.footer-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem;
  border-radius: 10px;
  font-size: 0.875rem;
  color: #10b981;
  text-decoration: none;
  transition: all 0.2s ease;
}

.footer-link:hover {
  background: rgba(16, 185, 129, 0.1);
}

/* ===== 确认清空弹窗 ===== */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .confirm-dialog,
.modal-leave-to .confirm-dialog,
.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.95);
}

.confirm-dialog {
  background: #1a1a1a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 1.5rem;
  width: 100%;
  max-width: 320px;
  text-align: center;
  transition: transform 0.2s ease;
}

.confirm-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: rgba(239, 68, 68, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ef4444;
  margin: 0 auto 1rem;
}

.confirm-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 0.5rem;
}

.confirm-desc {
  font-size: 0.875rem;
  color: #a3a3a3;
  margin: 0 0 1.5rem;
  line-height: 1.5;
}

.confirm-actions {
  display: flex;
  gap: 0.75rem;
}

.confirm-btn {
  flex: 1;
  padding: 0.625rem 1rem;
  border-radius: 10px;
  border: none;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.confirm-btn.cancel {
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
}

.confirm-btn.cancel:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.confirm-btn.danger {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.confirm-btn.danger:hover {
  background: rgba(239, 68, 68, 0.25);
}

.confirm-btn:active {
  transform: scale(0.97);
}

/* ===== 详情弹窗 ===== */
.modal-content {
  background: #1a1a1a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  width: 100%;
  max-width: 500px;
  max-height: 80vh;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  transition: transform 0.2s ease;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.modal-title-row {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.modal-icon {
  width: 48px;
  height: 48px;
  background: rgba(16, 185, 129, 0.1);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-type-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
  font-size: 0.688rem;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.05);
  color: #737373;
  text-transform: uppercase;
  margin-bottom: 0.25rem;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
}

.modal-close {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.modal-close:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
  max-height: calc(80vh - 180px);
}

.modal-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1rem;
  font-size: 0.8rem;
  color: #737373;
}

.modal-time,
.modal-sender {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.modal-message {
  font-size: 1rem;
  line-height: 1.8;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-word;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.modal-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}

.modal-btn.secondary {
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
}

.modal-btn.secondary:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.modal-btn.danger {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.modal-btn.danger:hover {
  background: rgba(239, 68, 68, 0.25);
}

.modal-btn:active {
  transform: scale(0.97);
}

/* ===== 响应式 ===== */
@media (max-width: 480px) {
  .notification-panel {
    max-height: 70vh;
  }

  .confirm-dialog,
  .modal-content {
    max-width: calc(100vw - 2rem);
    margin: 1rem;
  }

  .modal-header,
  .modal-body,
  .modal-footer {
    padding: 1rem;
  }

  .modal-title {
    font-size: 1rem;
  }

  .modal-footer {
    flex-direction: column-reverse;
  }

  .modal-btn {
    width: 100%;
    justify-content: center;
  }

  .confirm-actions {
    flex-direction: column-reverse;
  }

  .confirm-btn {
    width: 100%;
  }
}
</style>
