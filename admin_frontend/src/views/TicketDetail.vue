<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Send, Check, X, Gift, LogOut, RefreshCw } from 'lucide-vue-next'

// ==================== 类型定义 ====================
interface TicketMessage {
  role: 'user' | 'admin' | 'system'
  userId?: number
  userName?: string
  time: string
  content: string
}

interface Ticket {
  id: number
  title: string
  requestUserId: number
  requestUserName: string
  replyUserId?: number
  replyUserName?: string
  type: number  // -1=已关闭, 1=待处理, 2=处理中
  message: string
  requestInfo: {
    title: string
    messageId?: string
  }
  created_at: string
  updated_at: string
}

// ==================== 状态 ====================
const route = useRoute()
const router = useRouter()

const ticket = ref<Ticket | null>(null)
const messages = ref<TicketMessage[]>([])
const loading = ref(false)
const sending = ref(false)

// 输入
const newMessage = ref('')
const rewardAmount = ref(0)
const showRewardModal = ref(false)

// 当前管理员ID
const currentAdminId = ref(1)

// ==================== 计算属性 ====================
const statusMap: Record<number, { text: string; class: string }> = {
  '-1': { text: '已关闭', class: 'status-closed' },
  '1': { text: '待处理', class: 'status-pending' },
  '2': { text: '处理中', class: 'status-processing' }
}

const ticketStatus = computed(() => {
  if (!ticket.value) return ''
  return statusMap[ticket.value.type]?.text || ''
})

const canReply = computed(() => {
  if (!ticket.value) return false
  return ticket.value.type !== -1
})

// ==================== 数据获取 ====================
const fetchTicket = async () => {
  loading.value = true
  try {
    const ticketId = Number(route.params.id)
    // TODO: API 调用
    // const response = await api.get(`/api/admin/tickets/${ticketId}`)
    // ticket.value = response.data.ticket
    // messages.value = response.data.messages

    // 模拟数据
    ticket.value = {
      id: ticketId,
      title: '账号登录问题',
      requestUserId: 123,
      requestUserName: 'user123',
      type: 1,
      message: JSON.stringify([
        { role: 'user', time: '2026-01-06 10:00:00', content: '我无法登录我的账号' }
      ]),
      requestInfo: { title: '账号登录问题' },
      created_at: '2026-01-06 10:00:00',
      updated_at: '2026-01-06 10:00:00'
    }
    messages.value = [
      { role: 'user', time: '2026-01-06 10:00:00', content: '我无法登录我的账号' }
    ]
  } catch (error) {
    console.error('获取工单失败:', error)
  } finally {
    loading.value = false
  }
}

// ==================== 工单操作 ====================
const sendMessage = async () => {
  if (!newMessage.value.trim() || !ticket.value) return

  sending.value = true
  const content = newMessage.value
  newMessage.value = ''

  try {
    // TODO: API 调用
    // const response = await api.post(`/api/admin/tickets/${ticket.value.id}/reply`, {
    //   content: content
    // })
    // messages.value = response.data.messages

    // 模拟添加消息
    messages.value.push({
      role: 'admin',
      userId: currentAdminId.value,
      time: new Date().toLocaleString('zh-CN'),
      content: content
    })

    // 如果是首次回复，更新工单状态
    if (!ticket.value.replyUserId) {
      ticket.value.replyUserId = currentAdminId.value
      ticket.value.type = 2
    }
  } catch (error) {
    console.error('发送回复失败:', error)
  } finally {
    sending.value = false
  }
}

const joinTicket = async () => {
  if (!ticket.value) return

  try {
    // TODO: API 调用
    // await api.post(`/api/admin/tickets/${ticket.value.id}/join`)

    messages.value.push({
      role: 'system',
      time: new Date().toLocaleString('zh-CN'),
      content: `管理员(#${currentAdminId.value})已加入对话`
    })

    ticket.value.replyUserId = currentAdminId.value
  } catch (error) {
    console.error('加入对话失败:', error)
  }
}

const closeTicket = async () => {
  if (!ticket.value || !canReply.value) return
  if (!confirm('确定要关闭此工单吗？')) return

  try {
    // TODO: API 调用
    // await api.post(`/api/admin/tickets/${ticket.value.id}/close`)

    messages.value.push({
      role: 'system',
      time: new Date().toLocaleString('zh-CN'),
      content: `管理员(#${currentAdminId.value})关闭该工单`
    })

    ticket.value.type = -1
  } catch (error) {
    console.error('关闭工单失败:', error)
  }
}

const leaveTicket = async () => {
  if (!ticket.value || ticket.value.type === -1) return

  try {
    // TODO: API 调用
    // await api.post(`/api/admin/tickets/${ticket.value.id}/leave`)

    messages.value.push({
      role: 'system',
      time: new Date().toLocaleString('zh-CN'),
      content: `管理员(#${currentAdminId.value})已离开对话`
    })

    ticket.value.replyUserId = undefined
  } catch (error) {
    console.error('离开对话失败:', error)
  }
}

const sendReward = async () => {
  if (!ticket.value || !ticket.value.type) return
  if (rewardAmount.value <= 0) {
    alert('请输入有效的奖励数量')
    return
  }

  try {
    // TODO: API 调用
    // await api.post(`/api/admin/tickets/${ticket.value.id}/reward`, {
    //   reward: rewardAmount.value
    // })

    messages.value.push({
      role: 'system',
      time: new Date().toLocaleString('zh-CN'),
      content: `管理员(#${currentAdminId.value})奖励给您了${rewardAmount.value}R币`
    })

    showRewardModal.value = false
    rewardAmount.value = 0
  } catch (error) {
    console.error('发送奖励失败:', error)
  }
}

// ==================== 返回 ====================
const goBack = () => {
  router.push('/tickets')
}

// ==================== 生命周期 ====================
onMounted(() => {
  fetchTicket()
})
</script>

<template>
  <div class="ticket-detail">
    <!-- 头部 -->
    <div class="detail-header">
      <div class="header-left">
        <button class="icon-btn" @click="goBack">
          <ArrowLeft :size="20" />
        </button>
        <div>
          <h1 class="ticket-title">{{ ticket?.title || '工单详情' }}</h1>
          <div class="ticket-meta">
            <span>ID: #{{ ticket?.id }}</span>
            <span>{{ ticket?.requestUserName }}</span>
            <span :class="['status-badge', statusMap[ticket?.type || 1]?.class]">
              {{ ticketStatus }}
            </span>
          </div>
        </div>
      </div>
      <div class="header-right">
        <button v-if="ticket && !ticket.replyUserId && ticket.type > 0" class="btn btn-primary" @click="joinTicket">
          加入对话
        </button>
        <button v-if="ticket && ticket.replyUserId === currentAdminId && ticket.type > 0" class="btn btn-secondary" @click="leaveTicket">
          <LogOut :size="16" />
          <span>离开</span>
        </button>
        <button v-if="ticket && ticket.replyUserId === currentAdminId && ticket.type > 0" class="btn btn-success" @click="closeTicket">
          <Check :size="16" />
          <span>关闭工单</span>
        </button>
        <button v-if="ticket && ticket.type > 0" class="btn btn-warning" @click="showRewardModal = true">
          <Gift :size="16" />
          <span>奖励</span>
        </button>
        <button class="btn btn-secondary" @click="fetchTicket">
          <RefreshCw :size="16" />
        </button>
      </div>
    </div>

    <!-- 消息区域 -->
    <div class="messages-container">
      <div v-if="loading" class="loading">加载中...</div>
      <div v-else class="messages-list">
        <div
          v-for="(msg, index) in messages"
          :key="index"
          :class="['message-item', `msg-${msg.role}`, { own: msg.role === 'admin' && msg.userId === currentAdminId }]"
        >
          <!-- 用户消息 -->
          <template v-if="msg.role === 'user'">
            <div class="message-avatar user-avatar">
              {{ ticket?.requestUserName?.charAt(0).toUpperCase() || 'U' }}
            </div>
            <div class="message-content">
              <div class="message-bubble">
                {{ msg.content }}
              </div>
              <span class="message-time">{{ msg.time }}</span>
            </div>
          </template>

          <!-- 管理员消息 -->
          <template v-else-if="msg.role === 'admin'">
            <div class="message-bubble admin-bubble">
              {{ msg.content }}
              <span class="message-time">{{ msg.time }}</span>
            </div>
            <div class="message-avatar admin-avatar">
              {{ (msg.userName || '管理员').charAt(0) }}
            </div>
          </template>

          <!-- 系统消息 -->
          <template v-else-if="msg.role === 'system'">
            <div class="system-message">
              {{ msg.content }}
              <span class="message-time">{{ msg.time }}</span>
            </div>
          </template>
        </div>
      </div>

      <!-- 输入区域 -->
      <div v-if="ticket && canReply" class="input-area">
        <input
          v-model="newMessage"
          type="text"
          placeholder="输入回复内容..."
          class="message-input"
          @keyup.enter="sendMessage"
          :disabled="sending || !ticket.replyUserId"
        />
        <button
          class="send-btn"
          @click="sendMessage"
          :disabled="!newMessage.trim() || sending || !ticket.replyUserId"
        >
          <Send :size="18" />
        </button>
      </div>
      <div v-else-if="ticket && ticket.type === -1" class="input-disabled">
        工单已关闭，无法继续回复
      </div>
    </div>

    <!-- 奖励弹窗 -->
    <div v-if="showRewardModal" class="modal-overlay" @click.self="showRewardModal = false">
      <div class="modal modal-small">
        <div class="modal-header">
          <h2>奖励R币</h2>
          <button class="icon-btn" @click="showRewardModal = false">
            <X :size="20" />
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>奖励数量</label>
            <input v-model.number="rewardAmount" type="number" min="1" class="input" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showRewardModal = false">取消</button>
          <button class="btn btn-primary" @click="sendReward">确定</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ticket-detail {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 140px);
}

/* 头部 */
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 1rem;
  border-bottom: 1px solid #f1f5f9;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.ticket-title {
  font-size: 1.125rem;
  font-weight: 600;
  margin: 0;
}

.ticket-meta {
  display: flex;
  gap: 0.75rem;
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}

.header-right {
  display: flex;
  gap: 0.5rem;
}

/* 状态徽章 */
.status-badge {
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-pending {
  background: rgba(255, 152, 0, 0.15);
  color: #FF9800;
}

.status-processing {
  background: rgba(33, 150, 243, 0.15);
  color: #2196F3;
}

.status-closed {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}

/* 消息区域 */
.messages-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  overflow: hidden;
}

.messages-list {
  flex: 1;
  padding: 1.25rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.message-item {
  display: flex;
  gap: 0.75rem;
  max-width: 80%;
}

.message-item.own {
  align-self: flex-end;
  flex-direction: row-reverse;
}

/* 消息气泡 */
.message-content {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.message-bubble {
  padding: 0.75rem 1rem;
  border-radius: 16px;
  font-size: 0.9rem;
  line-height: 1.4;
}

.message-item:not(.own) .message-bubble {
  background: #f1f5f9;
  color: var(--text-primary);
  border-bottom-left-radius: 4px;
}

.admin-bubble {
  background: linear-gradient(135deg, #4CAF50, #673AB7);
  color: white;
  border-bottom-right-radius: 4px;
}

.message-time {
  font-size: 0.7rem;
  color: var(--text-muted);
}

.message-item.own .message-time {
  text-align: right;
}

/* 头像 */
.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 600;
  color: white;
  flex-shrink: 0;
}

.user-avatar {
  background: linear-gradient(135deg, #2196F3, #1976D2);
}

.admin-avatar {
  background: linear-gradient(135deg, #4CAF50, #673AB7);
}

/* 系统消息 */
.system-message {
  align-self: center;
  padding: 0.5rem 1rem;
  background: #f8fafc;
  border-radius: 20px;
  font-size: 0.8rem;
  color: var(--text-muted);
  text-align: center;
}

/* 输入区域 */
.input-area {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid #f1f5f9;
}

.message-input {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 0.9rem;
}

.message-input:focus {
  outline: none;
  border-color: #4CAF50;
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: linear-gradient(135deg, #4CAF50, #673AB7);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-disabled {
  padding: 1rem 1.25rem;
  text-align: center;
  color: var(--text-muted);
  border-top: 1px solid #f1f5f9;
}

/* 按钮 */
.btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  border-radius: 8px;
  border: none;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-primary {
  background: var(--gradient-brand);
  color: white;
}

.btn-secondary {
  background: #f1f5f9;
  color: var(--text-secondary);
}

.btn-success {
  background: #4CAF50;
  color: white;
}

.btn-warning {
  background: #FF9800;
  color: white;
}

.icon-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* 模态框 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 400px;
}

.modal-small {
  max-width: 360px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #f1f5f9;
}

.modal-header h2 {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

.modal-body {
  padding: 1.25rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid #f1f5f9;
}

/* 表单 */
.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.input {
  padding: 0.625rem 0.875rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 0.875rem;
}

.input:focus {
  outline: none;
  border-color: #4CAF50;
}

.loading {
  text-align: center;
  padding: 2rem;
  color: var(--text-muted);
}
</style>
