<script setup lang="ts">
/**
 * 消息列表页面
 * 展示所有来自后台管理员的站内消息
 * 前后台联动核心页面
 */
import { ref, computed, onMounted } from 'vue'
import {
  Bell,
  Check,
  CheckCheck,
  Trash2,
  MessageSquare,
  Ticket,
  Megaphone,
  Gift,
  AlertCircle,
  Clock,
  RefreshCw,
  Search,
  Filter,
  X,
  ExternalLink
} from 'lucide-vue-next'
import { messageApi } from '@/api'

// 消息类型
interface Message {
  id: number
  title: string
  content: string
  message_type: string
  related_id?: number
  is_read: boolean
  created_at: string
  from_user?: string
}

// 状态
const messages = ref<Message[]>([])
const loading = ref(false)
const refreshing = ref(false)
const filterUnreadOnly = ref(false)
const searchQuery = ref('')
const selectedType = ref<string>('all')
const selectedMessage = ref<Message | null>(null)
const showDetailModal = ref(false)

// 通知类型配置
const typeConfigs: Record<string, { label: string; icon: any; color: string }> = {
  all: { label: '全部', icon: MessageSquare, color: 'text-gray-400' },
  system: { label: '系统通知', icon: AlertCircle, color: 'text-blue-400' },
  ticket: { label: '工单消息', icon: Ticket, color: 'text-orange-400' },
  announcement: { label: '公告', icon: Megaphone, color: 'text-purple-400' },
  subscription: { label: '订阅', icon: Gift, color: 'text-green-400' },
  media_seek: { label: '求片', icon: Clock, color: 'text-cyan-400' },
  exchange_code: { label: '兑换', icon: Gift, color: 'text-yellow-400' },
}

// 计算属性
const filteredMessages = computed(() => {
  let result = messages.value

  // 类型过滤
  if (selectedType.value !== 'all') {
    result = result.filter(m => m.message_type === selectedType.value)
  }

  // 未读过滤
  if (filterUnreadOnly.value) {
    result = result.filter(m => !m.is_read)
  }

  // 搜索过滤
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(m =>
      m.title.toLowerCase().includes(query) ||
      m.content.toLowerCase().includes(query)
    )
  }

  return result
})

const unreadCount = computed(() => {
  return messages.value.filter(m => !m.is_read).length
})

// 加载消息
async function loadMessages() {
  loading.value = true
  try {
    const response = await messageApi.getMessages({
      unread_only: false,
      limit: 100
    })
    // API 返回格式: { data: [...], total: number, unread_count: number }
    messages.value = response.data?.data || response.data || []
  } catch (error) {
    console.error('加载消息失败:', error)
  } finally {
    loading.value = false
  }
}

// 刷新消息
async function refreshMessages() {
  refreshing.value = true
  try {
    const response = await messageApi.getMessages({
      unread_only: false,
      limit: 100
    })
    // API 返回格式: { data: [...], total: number, unread_count: number }
    messages.value = response.data?.data || response.data || []
  } catch (error) {
    console.error('刷新消息失败:', error)
  } finally {
    refreshing.value = false
  }
}

// 打开消息详情
async function openDetail(message: Message) {
  selectedMessage.value = message
  showDetailModal.value = true

  // 如果未读，标记为已读
  if (!message.is_read) {
    try {
      await messageApi.markAsRead(message.id)
      message.is_read = true
    } catch (error) {
      console.error('标记已读失败:', error)
    }
  }
}

// 关闭详情弹窗
function closeDetail() {
  showDetailModal.value = false
  selectedMessage.value = null
}

// 删除消息
async function deleteMessage(message: Message) {
  if (!confirm(`确定要删除消息"${message.title}"吗？`)) {
    return
  }

  try {
    await messageApi.delete(message.id)
    // 从列表中移除
    messages.value = messages.value.filter(m => m.id !== message.id)
    // 如果删除的是当前打开的消息，关闭弹窗
    if (selectedMessage.value?.id === message.id) {
      closeDetail()
    }
  } catch (error) {
    console.error('删除消息失败:', error)
    alert('删除失败，请稍后重试')
  }
}

// 标记为已读
async function markAsRead(message: Message) {
  if (message.is_read) return

  try {
    await messageApi.markAsRead(message.id)
    message.is_read = true
  } catch (error) {
    console.error('标记已读失败:', error)
  }
}

// 标记所有为已读
async function markAllAsRead() {
  try {
    await messageApi.markAllRead()
    messages.value.forEach(m => m.is_read = true)
  } catch (error) {
    console.error('标记全部已读失败:', error)
  }
}

// 获取类型配置
function getTypeConfig(type: string) {
  return typeConfigs[type] || typeConfigs.all
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

  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
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

onMounted(() => {
  loadMessages()
})
</script>

<template>
  <div class="messages-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="header-left">
          <div class="header-icon">
            <MessageSquare :size="24" />
          </div>
          <div>
            <h1>消息中心</h1>
            <p class="header-subtitle">来自管理后台的通知和公告</p>
          </div>
        </div>
        <div class="header-actions">
          <button
            class="action-btn"
            @click="refreshMessages"
            :disabled="refreshing"
            title="刷新"
          >
            <RefreshCw :size="18" :class="{ spinning: refreshing }" />
          </button>
          <button
            v-if="unreadCount > 0"
            class="action-btn primary"
            @click="markAllAsRead"
            title="全部标为已读"
          >
            <CheckCheck :size="18" />
            <span>全部已读</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="search-box">
        <Search :size="18" class="search-icon" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索消息..."
          class="search-input"
        />
      </div>

      <div class="filter-actions">
        <button
          class="filter-toggle"
          :class="{ active: filterUnreadOnly }"
          @click="filterUnreadOnly = !filterUnreadOnly"
        >
          <Filter :size="16" />
          <span>只看未读</span>
          <span v-if="unreadCount > 0" class="unread-badge">{{ unreadCount }}</span>
        </button>
      </div>

      <!-- 类型标签单独一行 -->
      <div class="type-tabs">
        <button
          v-for="(config, key) in typeConfigs"
          :key="key"
          class="type-tab"
          :class="{ active: selectedType === key }"
          @click="selectedType = key"
        >
          <component :is="config.icon" :size="15" />
          <span>{{ config.label }}</span>
        </button>
      </div>
    </div>

    <!-- 消息列表 -->
    <div class="messages-container">
      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <p>加载中...</p>
      </div>

      <div v-else-if="filteredMessages.length === 0" class="empty-state">
        <MessageSquare :size="48" />
        <h3>暂无消息</h3>
        <p>{{ searchQuery || filterUnreadOnly || selectedType !== 'all' ? '没有符合条件的消息' : '您的消息列表为空' }}</p>
      </div>

      <div v-else class="messages-list">
        <div
          v-for="message in filteredMessages"
          :key="message.id"
          class="message-card"
          :class="{ unread: !message.is_read }"
          @click="openDetail(message)"
        >
          <div class="message-icon">
            <component
              :is="getTypeConfig(message.message_type)!.icon"
              :size="20"
              :class="getTypeConfig(message.message_type)!.color"
            />
          </div>

          <div class="message-content">
            <div class="message-header">
              <div class="message-title-row">
                <span class="message-type-badge">
                  {{ getTypeConfig(message.message_type)!.label }}
                </span>
                <span class="message-time">{{ formatTime(message.created_at) }}</span>
              </div>
              <h3 class="message-title">
                <span v-if="!message.is_read" class="unread-indicator"></span>
                {{ message.title }}
              </h3>
            </div>
            <p class="message-text">{{ message.content }}</p>

            <div v-if="message.from_user" class="message-sender">
              来自：{{ message.from_user }}
            </div>
          </div>

          <!-- 删除按钮 -->
          <button
            class="delete-btn"
            @click.stop="deleteMessage(message)"
            title="删除消息"
          >
            <Trash2 :size="16" />
          </button>
        </div>
      </div>
    </div>

    <!-- 消息详情弹窗 -->
    <Transition name="modal">
      <div v-if="showDetailModal && selectedMessage" class="modal-overlay" @click="closeDetail">
        <div class="modal-content" @click.stop>
          <div class="modal-header">
            <div class="modal-title-row">
              <div class="modal-icon">
                <component
                  :is="getTypeConfig(selectedMessage.message_type)!.icon"
                  :size="24"
                  :class="getTypeConfig(selectedMessage.message_type)!.color"
                />
              </div>
              <div>
                <span class="modal-type-badge">
                  {{ getTypeConfig(selectedMessage.message_type)!.label }}
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
            <button class="btn btn-secondary" @click="closeDetail">
              关闭
            </button>
            <button class="btn btn-danger" @click="deleteMessage(selectedMessage)">
              <Trash2 :size="16" />
              删除
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.messages-page {
  min-height: 100vh;
  background: #0a0a0a;
  padding-bottom: 2rem;
}

/* 页面头部 */
.page-header {
  padding: 1.5rem 1.5rem 1rem;
  background: rgba(20, 20, 20, 0.8);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 900px;
  margin: 0 auto;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.header-icon {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.2) 0%, rgba(5, 150, 105, 0.15) 100%);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #10b981;
}

.header-left h1 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #ffffff;
  margin: 0 0 0.25rem 0;
}

.header-subtitle {
  font-size: 0.875rem;
  color: #737373;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.action-btn.primary {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border-color: transparent;
  color: white;
}

.action-btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 筛选栏 */
.filter-bar {
  padding: 1rem 1.5rem;
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.filter-bar > .search-box {
  width: 100%;
  max-width: 100%;
}

.search-box {
  position: relative;
}

.search-icon {
  position: absolute;
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  color: #737373;
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 0.625rem 0.75rem 0.625rem 2.25rem;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
  color: #ffffff;
  font-size: 0.875rem;
  outline: none;
  transition: all 0.2s ease;
}

.search-input:focus {
  border-color: #10b981;
  background: rgba(26, 26, 26, 0.8);
}

.search-input::placeholder {
  color: #737373;
}

.filter-actions {
  display: flex;
  justify-content: flex-end;
}

.type-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.type-tab {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.875rem;
  border-radius: 9999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
  color: #737373;
  font-size: 0.8rem;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.type-tab:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #a3a3a3;
  border-color: rgba(255, 255, 255, 0.15);
}

.type-tab.active {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(5, 150, 105, 0.1) 100%);
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.1);
}

.filter-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.875rem;
  border-radius: 9999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
  color: #737373;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-toggle:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #a3a3a3;
}

.filter-toggle.active {
  background: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.unread-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  background: #10b981;
  border-radius: 9px;
  font-size: 0.7rem;
  font-weight: 600;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 消息列表 */
.messages-container {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  color: #525252;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.empty-state h3 {
  font-size: 1rem;
  font-weight: 500;
  color: #a3a3a3;
  margin: 0.75rem 0 0.25rem;
}

.empty-state p {
  font-size: 0.875rem;
  color: #525252;
  margin: 0;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.message-card {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: rgba(26, 26, 26, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.message-card:hover {
  background: rgba(38, 38, 38, 0.8);
  border-color: rgba(16, 185, 129, 0.2);
}

.message-card.unread {
  background: rgba(16, 185, 129, 0.04);
  border-color: rgba(16, 185, 129, 0.15);
}

.message-card.unread::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 60%;
  background: linear-gradient(180deg, #10b981 0%, #059669 100%);
  border-radius: 0 2px 2px 0;
}

.message-icon {
  width: 40px;
  height: 40px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  margin-bottom: 0.5rem;
}

.message-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
  flex-wrap: wrap;
}

.message-type-badge {
  display: inline-flex;
  padding: 0.125rem 0.5rem;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.05);
  color: #737373;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  flex-shrink: 0;
}

.message-time {
  font-size: 0.75rem;
  color: #525252;
  flex-shrink: 0;
  margin-left: auto;
}

.message-title {
  font-size: 1rem;
  font-weight: 500;
  color: #ffffff;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
}

.unread-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
  flex-shrink: 0;
}

.message-text {
  font-size: 0.875rem;
  color: #a3a3a3;
  line-height: 1.5;
  margin: 0 0 0.5rem 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.message-sender {
  font-size: 0.75rem;
  color: #525252;
}

.delete-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: transparent;
  color: #737373;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.delete-btn:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.3);
  color: #ef4444;
}

/* 模态框 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal-content {
  background: #1a1a1a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  width: 100%;
  max-width: 500px;
  max-height: 80vh;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
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
  font-size: 0.7rem;
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

.btn {
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

.btn-secondary {
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.btn-danger {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.25);
}

/* 模态框过渡 */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.95);
}

.modal-enter-active .modal-content,
.modal-leave-active .modal-content {
  transition: transform 0.2s ease;
}

/* 响应式 */
@media (max-width: 640px) {
  .page-header {
    padding: 1rem 1rem 0.75rem;
  }

  .header-content {
    flex-direction: row;
    align-items: center;
    gap: 0.75rem;
  }

  .header-left h1 {
    font-size: 1.125rem;
  }

  .header-subtitle {
    font-size: 0.75rem;
  }

  .header-icon {
    width: 40px;
    height: 40px;
  }

  .header-actions .action-btn span {
    display: none;
  }

  .filter-bar {
    padding: 0.75rem 1rem;
  }

  .type-tab {
    padding: 0.375rem 0.625rem;
    font-size: 0.75rem;
    flex-grow: 0;
  }

  .type-tab span {
    display: none;
  }

  .type-tab.active span {
    display: inline;
  }

  .filter-toggle span {
    font-size: 0.75rem;
  }

  .message-card {
    padding: 0.75rem 0.875rem;
  }

  .message-icon {
    width: 32px;
    height: 32px;
  }

  .message-title {
    font-size: 0.9rem;
  }

  .message-text {
    font-size: 0.8rem;
    -webkit-line-clamp: 2;
  }

  .modal-content {
    max-width: 100%;
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

  .modal-footer .btn {
    width: 100%;
    justify-content: center;
  }
}
</style>
