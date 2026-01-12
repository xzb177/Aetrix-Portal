<script setup lang="ts">
/**
 * 工单页面
 * 用户可以创建工单、查看工单列表、回复工单
 */
import { ref, onMounted } from 'vue'
import {
  Ticket,
  Plus,
  MessageSquare,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Send,
  X,
  ChevronRight
} from 'lucide-vue-next'
import { ticketApi } from '@/api'

interface Ticket {
  id: number
  title: string
  category: string
  priority: string
  status: string
  created_at: string
  updated_at: string
}

interface TicketMessage {
  id: number
  message: string
  is_admin: boolean
  created_at: string
}

// 状态
const tickets = ref<Ticket[]>([])
const loading = ref(false)
const selectedTicket = ref<Ticket | null>(null)
const messages = ref<TicketMessage[]>([])
const messagesLoading = ref(false)
const showCreateModal = ref(false)
const showDetailModal = ref(false)

// 创建工单表单
const createForm = ref({
  title: '',
  category: 'other',
  message: ''
})
const creating = ref(false)

// 回复工单
const replyMessage = ref('')
const replying = ref(false)

// 状态配置
const statusConfig: Record<string, { label: string; color: string; icon: any }> = {
  open: { label: '待处理', color: 'text-orange-400', icon: Clock },
  pending: { label: '处理中', color: 'text-blue-400', icon: AlertCircle },
  resolved: { label: '已解决', color: 'text-green-400', icon: CheckCircle },
  closed: { label: '已关闭', color: 'text-gray-400', icon: XCircle },
}

const categoryOptions = [
  { value: 'account', label: '账号问题' },
  { value: 'subscription', label: '订阅问题' },
  { value: 'payment', label: '支付问题' },
  { value: 'emby', label: 'Emby问题' },
  { value: 'other', label: '其他问题' },
]

// 获取工单列表
async function fetchTickets() {
  loading.value = true
  try {
    const res = await ticketApi.getMyTickets()
    tickets.value = res.data || []
  } catch (error) {
    console.error('获取工单列表失败:', error)
  } finally {
    loading.value = false
  }
}

// 打开创建工单弹窗
function openCreateModal() {
  createForm.value = {
    title: '',
    category: 'other',
    message: ''
  }
  showCreateModal.value = true
}

// 创建工单
async function createTicket() {
  if (!createForm.value.title.trim() || !createForm.value.message.trim()) {
    return
  }

  creating.value = true
  try {
    await ticketApi.create({
      title: createForm.value.title,
      category: createForm.value.category,
      message: createForm.value.message
    })
    showCreateModal.value = false
    fetchTickets()
  } catch (error) {
    console.error('创建工单失败:', error)
    alert('创建工单失败，请稍后重试')
  } finally {
    creating.value = false
  }
}

// 打开工单详情
async function openTicketDetail(ticket: Ticket) {
  selectedTicket.value = ticket
  showDetailModal.value = true
  await fetchMessages(ticket.id)
}

// 获取工单消息
async function fetchMessages(ticketId: number) {
  messagesLoading.value = true
  try {
    const res = await ticketApi.getMessages(ticketId)
    messages.value = res.data || []
  } catch (error) {
    console.error('获取消息失败:', error)
  } finally {
    messagesLoading.value = false
  }
}

// 回复工单
async function replyTicket() {
  if (!replyMessage.value.trim() || !selectedTicket.value) return

  replying.value = true
  try {
    await ticketApi.reply(selectedTicket.value.id, {
      message: replyMessage.value
    })
    replyMessage.value = ''
    await fetchMessages(selectedTicket.value.id)
    await fetchTickets()
  } catch (error) {
    console.error('回复失败:', error)
    alert('回复失败，请稍后重试')
  } finally {
    replying.value = false
  }
}

// 关闭工单
async function closeTicket() {
  if (!selectedTicket.value) return
  if (!confirm('确定要关闭此工单吗？')) return

  try {
    await ticketApi.close(selectedTicket.value.id)
    showDetailModal.value = false
    fetchTickets()
  } catch (error) {
    console.error('关闭工单失败:', error)
  }
}

// 格式化日期
function formatDate(dateStr: string) {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) {
    const hours = Math.floor(diff / (1000 * 60 * 60))
    if (hours === 0) {
      const minutes = Math.floor(diff / (1000 * 60))
      return minutes === 0 ? '刚刚' : `${minutes}分钟前`
    }
    return `${hours}小时前`
  } else if (days === 1) {
    return '昨天'
  } else if (days < 7) {
    return `${days}天前`
  }
  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric'
  })
}

function getCategoryLabel(category: string) {
  const option = categoryOptions.find(c => c.value === category)
  return option ? option.label : '其他问题'
}

onMounted(() => {
  fetchTickets()
})
</script>

<template>
  <div class="tickets-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">
          <Ticket :size="24" />
          工单中心
        </h1>
        <button @click="openCreateModal" class="btn-create">
          <Plus :size="18" />
          新建工单
        </button>
      </div>
    </div>

    <!-- 工单列表 -->
    <div class="tickets-content">
      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <p>加载中...</p>
      </div>

      <div v-else-if="tickets.length === 0" class="empty-state">
        <div class="empty-icon">
          <Ticket :size="32" />
        </div>
        <p>暂无工单</p>
        <p class="empty-hint">遇到问题可以创建工单联系客服</p>
        <button @click="openCreateModal" class="btn btn-primary">
          <Plus :size="16" />
          创建工单
        </button>
      </div>

      <div v-else class="tickets-list">
        <div
          v-for="ticket in tickets"
          :key="ticket.id"
          @click="openTicketDetail(ticket)"
          class="ticket-item glass-card"
        >
          <div class="ticket-header">
            <div class="ticket-info">
              <span class="ticket-title">{{ ticket.title }}</span>
              <span class="ticket-category">{{ getCategoryLabel(ticket.category) }}</span>
            </div>
            <component :is="statusConfig[ticket.status]?.icon || Clock" :size="16" />
          </div>
          <div class="ticket-footer">
            <span class="ticket-status" :class="statusConfig[ticket.status]?.color">
              {{ statusConfig[ticket.status]?.label || '未知' }}
            </span>
            <span class="ticket-time">{{ formatDate(ticket.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建工单弹窗 -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal glass-card">
        <div class="modal-header">
          <h3>创建工单</h3>
          <button @click="showCreateModal = false" class="btn-close">
            <X :size="18" />
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>问题标题</label>
            <input
              v-model="createForm.title"
              type="text"
              placeholder="简要描述您遇到的问题"
              maxlength="100"
            />
          </div>
          <div class="form-group">
            <label>问题类型</label>
            <select v-model="createForm.category">
              <option
                v-for="option in categoryOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
          </div>
          <div class="form-group">
            <label>详细描述</label>
            <textarea
              v-model="createForm.message"
              placeholder="请详细描述您的问题，我们会尽快为您处理"
              rows="5"
              maxlength="1000"
            ></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showCreateModal = false" class="btn btn-secondary">取消</button>
          <button @click="createTicket" :disabled="creating" class="btn btn-primary">
            {{ creating ? '创建中...' : '提交工单' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 工单详情弹窗 -->
    <div v-if="showDetailModal" class="modal-overlay" @click.self="showDetailModal = false">
      <div class="modal modal-large glass-card">
        <div class="modal-header">
          <h3>{{ selectedTicket?.title }}</h3>
          <button @click="showDetailModal = false" class="btn-close">
            <X :size="18" />
          </button>
        </div>
        <div class="modal-body modal-body-messages">
          <div v-if="messagesLoading" class="loading-state">
            <div class="spinner"></div>
            <p>加载中...</p>
          </div>
          <div v-else class="messages-list">
            <div
              v-for="msg in messages"
              :key="msg.id"
              class="message-item"
              :class="{ 'message-admin': msg.is_admin }"
            >
              <div class="message-avatar">
                <MessageSquare :size="16" />
              </div>
              <div class="message-content">
                <span class="message-text">{{ msg.message }}</span>
                <span class="message-time">{{ formatDate(msg.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <div v-if="selectedTicket?.status !== 'closed'" class="reply-box">
            <input
              v-model="replyMessage"
              type="text"
              placeholder="输入回复内容..."
              @keyup.enter="replyTicket"
            />
            <button @click="replyTicket" :disabled="replying || !replyMessage.trim()" class="btn-send">
              <Send :size="16" />
            </button>
          </div>
          <button v-if="selectedTicket?.status !== 'closed'" @click="closeTicket" class="btn btn-secondary">
            关闭工单
          </button>
          <button @click="showDetailModal = false" class="btn btn-secondary">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tickets-page {
  max-width: 600px;
  margin: 0 auto;
  padding: 1.5rem 1rem;
}

/* 页面头部 */
.page-header {
  margin-bottom: 1.5rem;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.5rem;
  font-weight: 600;
  color: #fafafa;
  margin: 0;
}

.btn-create {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: #10b981;
  border: none;
  border-radius: 0.5rem;
  color: white;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-create:hover {
  background: #059669;
}

/* 工单列表 */
.tickets-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.ticket-item {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.ticket-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.ticket-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ticket-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
}

.ticket-title {
  font-weight: 500;
  color: #fafafa;
  font-size: 0.9375rem;
}

.ticket-category {
  padding: 0.125rem 0.5rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  font-size: 0.75rem;
  color: rgba(250, 250, 250, 0.6);
}

.ticket-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.8125rem;
}

.ticket-status {
  font-weight: 500;
}

.ticket-time {
  color: rgba(250, 250, 250, 0.5);
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1rem;
  color: rgba(250, 250, 250, 0.6);
}

.spinner {
  width: 32px;
  height: 32px;
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-top-color: #10b981;
  border-radius: 50%;
  margin-bottom: 0.75rem;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1rem;
  text-align: center;
}

.empty-icon {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(250, 250, 250, 0.3);
  margin-bottom: 1rem;
}

.empty-state p {
  color: rgba(250, 250, 250, 0.5);
  margin: 0;
}

.empty-hint {
  font-size: 0.8125rem;
  margin: 0.5rem 0 1rem;
}

/* 弹窗 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.modal {
  width: 100%;
  max-width: 450px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  border-radius: 1rem;
  padding: 1.25rem;
  overflow: hidden;
}

.modal-large {
  max-width: 500px;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.modal-header h3 {
  font-size: 1.125rem;
  font-weight: 600;
  color: #fafafa;
  margin: 0;
}

.btn-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: rgba(250, 250, 250, 0.5);
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-close:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(250, 250, 250, 0.8);
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 1rem;
}

.modal-body-messages {
  max-height: 400px;
}

.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.7);
  margin-bottom: 0.5rem;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 0.5rem;
  color: #fafafa;
  font-size: 0.875rem;
  transition: all 0.2s ease;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #10b981;
  background: rgba(255, 255, 255, 0.08);
}

.form-group textarea {
  resize: vertical;
  min-height: 100px;
}

/* 消息列表 */
.messages-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.message-item {
  display: flex;
  gap: 0.75rem;
  padding: 0.75rem;
  border-radius: 0.5rem;
  background: rgba(255, 255, 255, 0.05);
}

.message-item.message-admin {
  background: rgba(16, 185, 129, 0.1);
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(250, 250, 250, 0.6);
  flex-shrink: 0;
}

.message-admin .message-avatar {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
}

.message-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.message-text {
  color: rgba(250, 250, 250, 0.9);
  font-size: 0.875rem;
  line-height: 1.5;
  word-break: break-word;
}

.message-time {
  font-size: 0.75rem;
  color: rgba(250, 250, 250, 0.4);
}

.modal-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.reply-box {
  flex: 1;
  display: flex;
  gap: 0.5rem;
  min-width: 200px;
}

.reply-box input {
  flex: 1;
  padding: 0.625rem 0.875rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 0.5rem;
  color: #fafafa;
  font-size: 0.875rem;
}

.reply-box input:focus {
  outline: none;
  border-color: #10b981;
}

.btn-send {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 0.5rem;
  border: none;
  background: #10b981;
  color: white;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-send:hover:not(:disabled) {
  background: #059669;
}

.btn-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 按钮样式 */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}

.btn-primary {
  background: #10b981;
  color: white;
}

.btn-primary:hover {
  background: #059669;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fafafa;
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.15);
}

/* 响应式 */
@media (max-width: 480px) {
  .tickets-page {
    padding: 1rem 0.75rem;
  }

  .header-content {
    flex-direction: column;
    align-items: stretch;
  }

  .btn-create {
    width: 100%;
    justify-content: center;
  }

  .modal-footer {
    flex-direction: column;
  }

  .reply-box {
    width: 100%;
  }

  .btn {
    width: 100%;
  }
}
</style>
