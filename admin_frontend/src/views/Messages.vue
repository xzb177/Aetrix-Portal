<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { MessageCircle, Send, MoreVertical, Trash2, Check } from 'lucide-vue-next'

// ==================== 类型定义 ====================
interface Conversation {
  userId: number
  userName: string
  nickName: string
  lastMessage: string
  unreadCount: number
  updatedAt: string
}

interface Message {
  id: number
  fromUserId: number
  toUserId: number
  message: string
  readStatus: number
  createdAt: string
}

// ==================== 状态 ====================
const conversations = ref<Conversation[]>([])
const messages = ref<Message[]>([])
const currentChat = ref<number | null>(null)
const loading = ref(false)

// WebSocket
let ws: WebSocket | null = null

// 新消息输入
const newMessage = ref('')
const sending = ref(false)

// ==================== 计算属性 ====================
const currentUserName = computed(() => {
  if (!currentChat.value) return ''
  const conv = conversations.value.find(c => c.userId === currentChat.value)
  return conv?.nickName || conv?.userName || ''
})

const unreadTotal = computed(() =>
  conversations.value.reduce((sum, c) => sum + c.unreadCount, 0)
)

// ==================== WebSocket 连接 ====================
const connectWebSocket = () => {
  // TODO: 替换为实际的 WebSocket 地址
  const wsUrl = `ws://localhost:8000/ws/${getAdminId()}`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    console.log('WebSocket 已连接')
  }

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    handleWebSocketMessage(data)
  }

  ws.onerror = (error) => {
    console.error('WebSocket 错误:', error)
  }

  ws.onclose = () => {
    console.log('WebSocket 已断开，5秒后重连...')
    setTimeout(connectWebSocket, 5000)
  }
}

const handleWebSocketMessage = (data: any) => {
  switch (data.type) {
    case 'new_message':
      // 新消息
      if (data.toUserId === getAdminId()) {
        if (currentChat.value === data.fromUserId) {
          messages.value.push({
            id: data.notificationId,
            fromUserId: data.fromUserId,
            toUserId: data.toUserId,
            message: data.message,
            readStatus: 0,
            createdAt: data.createdAt
          })
          markAsRead(data.notificationId)
        }
        updateConversation(data)
      }
      break
    case 'unread_count':
      // 更新未读数
      updateUnreadCount(data.count)
      break
  }
}

const getAdminId = () => {
  // TODO: 从 store 获取管理员ID
  return 1
}

// ==================== 数据获取 ====================
const fetchConversations = async () => {
  loading.value = true
  try {
    // TODO: API 调用
    // const response = await api.get('/api/admin/messages/conversations')
    // conversations.value = response.data

    // 模拟数据
    conversations.value = []
  } catch (error) {
    console.error('获取会话列表失败:', error)
  } finally {
    loading.value = false
  }
}

const fetchMessages = async (userId: number) => {
  currentChat.value = userId
  try {
    // TODO: API 调用
    // const response = await api.get(`/api/admin/messages/${userId}`)
    // messages.value = response.data

    // 模拟数据
    messages.value = []
  } catch (error) {
    console.error('获取消息失败:', error)
  }
}

const markAsRead = async (messageId: number) => {
  try {
    // TODO: API 调用标记已读
    // await api.put(`/api/admin/messages/${messageId}/read`)
  } catch (error) {
    console.error('标记已读失败:', error)
  }
}

// ==================== 消息操作 ====================
const sendMessage = async () => {
  if (!newMessage.value.trim() || !currentChat.value) return

  sending.value = true
  const content = newMessage.value
  newMessage.value = ''

  try {
    // TODO: API 调用
    // await api.post('/api/admin/messages/send', {
    //   toUserId: currentChat.value,
    //   message: content
    // })

    // 本地添加消息
    messages.value.push({
      id: Date.now(),
      fromUserId: getAdminId(),
      toUserId: currentChat.value,
      message: content,
      readStatus: 0,
      createdAt: new Date().toISOString()
    })
  } catch (error) {
    console.error('发送消息失败:', error)
    newMessage.value = content
  } finally {
    sending.value = false
  }
}

const deleteConversation = async (userId: number) => {
  if (!confirm('确定要删除此对话吗？')) return

  try {
    // TODO: API 调用
    // await api.delete(`/api/admin/messages/${userId}`)

    conversations.value = conversations.value.filter(c => c.userId !== userId)
    if (currentChat.value === userId) {
      currentChat.value = null
      messages.value = []
    }
  } catch (error) {
    console.error('删除对话失败:', error)
  }
}

// ==================== 辅助函数 ====================
const updateConversation = (data: any) => {
  const existing = conversations.value.find(c => c.userId === data.fromUserId)
  if (existing) {
    existing.lastMessage = data.message
    existing.updatedAt = data.createdAt
    if (currentChat.value !== data.fromUserId) {
      existing.unreadCount++
    }
  } else {
    conversations.value.unshift({
      userId: data.fromUserId,
      userName: data.fromUserName || '',
      nickName: data.fromNickName || '',
      lastMessage: data.message,
      unreadCount: 1,
      updatedAt: data.createdAt
    })
  }
}

const updateUnreadCount = (count: number) => {
  // 可以在这里更新全局未读数
}

const formatTime = (time: string) => {
  const date = new Date(time)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)} 天前`

  return date.toLocaleDateString()
}

// ==================== 生命周期 ====================
onMounted(() => {
  fetchConversations()
  connectWebSocket()
})

onUnmounted(() => {
  if (ws) {
    ws.close()
  }
})
</script>

<template>
  <div class="messages-page">
    <!-- 聊天界面 -->
    <div class="chat-container">
      <!-- 会话列表 -->
      <div class="conversation-list">
        <div class="list-header">
          <h3>消息列表</h3>
        </div>
        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="conversations.length === 0" class="empty">暂无消息</div>
        <div
          v-for="conv in conversations"
          :key="conv.userId"
          :class="['conversation-item', { active: currentChat === conv.userId }]"
          @click="fetchMessages(conv.userId)"
        >
          <div class="conv-avatar">
            {{ (conv.nickName || conv.userName).charAt(0).toUpperCase() }}
          </div>
          <div class="conv-info">
            <div class="conv-header">
              <span class="conv-name">{{ conv.nickName || conv.userName }}</span>
              <span class="conv-time">{{ formatTime(conv.updatedAt) }}</span>
            </div>
            <div class="conv-preview">
              {{ conv.lastMessage }}
            </div>
          </div>
          <div v-if="conv.unreadCount > 0" class="conv-badge">
            {{ conv.unreadCount > 99 ? '99+' : conv.unreadCount }}
          </div>
        </div>
      </div>

      <!-- 聊天区域 -->
      <div class="chat-area">
        <template v-if="currentChat">
          <!-- 聊天头部 -->
          <div class="chat-header">
            <div class="chat-user">
              <div class="chat-avatar">
                {{ currentUserName.charAt(0).toUpperCase() }}
              </div>
              <span class="chat-name">{{ currentUserName }}</span>
            </div>
            <button class="icon-btn" @click="deleteConversation(currentChat)" title="删除对话">
              <Trash2 :size="16" />
            </button>
          </div>

          <!-- 消息列表 -->
          <div class="message-list" ref="messageListRef">
            <div
              v-for="msg in messages"
              :key="msg.id"
              :class="['message-item', { own: msg.fromUserId === getAdminId() }]"
            >
              <div v-if="msg.fromUserId !== getAdminId()" class="message-avatar">
                {{ currentUserName.charAt(0).toUpperCase() }}
              </div>
              <div :class="['message-bubble', { own: msg.fromUserId === getAdminId() }]">
                {{ msg.message }}
                <span class="message-time">{{ formatTime(msg.createdAt) }}</span>
              </div>
              <div v-if="msg.fromUserId === getAdminId()" class="message-status">
                <Check v-if="msg.readStatus" :size="12" />
              </div>
            </div>
          </div>

          <!-- 输入区域 -->
          <div class="chat-input">
            <input
              v-model="newMessage"
              type="text"
              placeholder="输入消息..."
              class="input-field"
              @keyup.enter="sendMessage"
              :disabled="sending"
            />
            <button
              class="send-btn"
              @click="sendMessage"
              :disabled="!newMessage.trim() || sending"
            >
              <Send :size="18" />
            </button>
          </div>
        </template>

        <!-- 空状态 -->
        <div v-else class="chat-empty">
          <MessageCircle :size="48" />
          <p>选择一个对话开始聊天</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.messages-page {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  height: calc(100vh - 180px);
}

.unread-badge {
  padding: 0.375rem 0.75rem;
  background: var(--danger);
  color: white;
  border-radius: 20px;
  font-size: 0.875rem;
  font-weight: 500;
}

/* 聊天容器 */
.chat-container {
  display: flex;
  background: var(--bg-card);
  border-radius: 12px;
  border: 1px solid var(--border-base);
  height: 100%;
  overflow: hidden;
}

/* 会话列表 */
.conversation-list {
  width: 320px;
  border-right: 1px solid var(--border-base);
  display: flex;
  flex-direction: column;
}

.list-header {
  padding: 1rem;
  border-bottom: 1px solid var(--border-base);
}

.list-header h3 {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  cursor: pointer;
  transition: background 0.2s ease;
  position: relative;
}

.conversation-item:hover {
  background: var(--bg-hover);
}

.conversation-item.active {
  background: var(--primary-bg);
}

.conv-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--primary-gradient);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  flex-shrink: 0;
}

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.25rem;
}

.conv-name {
  font-weight: 500;
  color: var(--text-primary);
}

.conv-time {
  font-size: 0.75rem;
  color: var(--text-tertiary);
}

.conv-preview {
  font-size: 0.8rem;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-badge {
  padding: 0.125rem 0.5rem;
  background: var(--danger);
  color: white;
  border-radius: 10px;
  font-size: 0.7rem;
  font-weight: 500;
}

/* 聊天区域 */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-base);
}

.chat-user {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.chat-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--primary-gradient);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
}

.chat-name {
  font-weight: 500;
}

/* 消息列表 */
.message-list {
  flex: 1;
  padding: 1.25rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.message-item {
  display: flex;
  gap: 0.5rem;
  max-width: 70%;
}

.message-item.own {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--primary-gradient);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
}

.message-bubble {
  padding: 0.75rem 1rem;
  border-radius: 16px;
  font-size: 0.9rem;
  line-height: 1.4;
  position: relative;
}

.message-bubble:not(.own) {
  background: var(--bg-elevated);
  color: var(--text-primary);
  border-bottom-left-radius: 4px;
}

.message-bubble.own {
  background: var(--primary-gradient);
  color: white;
  border-bottom-right-radius: 4px;
}

.message-time {
  font-size: 0.7rem;
  opacity: 0.7;
  margin-top: 0.25rem;
  display: block;
}

.message-status {
  display: flex;
  align-items: flex-end;
  color: var(--text-tertiary);
}

/* 输入区域 */
.chat-input {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid var(--border-base);
}

.input-field {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 0.9rem;
}

.input-field:focus {
  outline: none;
  border-color: var(--primary);
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: var(--primary-gradient);
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

/* 空状态 */
.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  gap: 1rem;
}

.icon-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: #ef4444;
}

.loading, .empty {
  text-align: center;
  padding: 2rem;
  color: var(--text-tertiary);
}
</style>
