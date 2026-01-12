<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Bell, CheckCircle, XCircle, Clock, Search, Filter } from 'lucide-vue-next'

interface Notification {
  id: number
  type: 'announcement' | 'alert' | 'reminder' | 'system'
  title: string
  content: string
  recipients: number
  sent: number
  failed: number
  status: 'sent' | 'pending' | 'failed' | 'sending'
  time: string
}

const loading = ref(false)
const notifications = ref<Notification[]>([])
const searchQuery = ref('')
const statusFilter = ref<string>('all')
const typeFilter = ref<string>('all')

const mockNotifications: Notification[] = [
  {
    id: 1,
    type: 'announcement',
    title: '系统维护通知',
    content: '系统将于今晚 02:00-04:00 进行维护升级',
    recipients: 1234,
    sent: 1230,
    failed: 4,
    status: 'sent',
    time: '2024-01-05 14:30',
  },
  {
    id: 2,
    type: 'alert',
    title: '服务器离线告警',
    content: '缓存服务器 cache.example.com 已离线',
    recipients: 3,
    sent: 3,
    failed: 0,
    status: 'sent',
    time: '2024-01-05 12:15',
  },
  {
    id: 3,
    type: 'reminder',
    title: '会员到期提醒',
    content: '您有 156 位用户的会员即将在7天内到期',
    recipients: 156,
    sent: 0,
    failed: 0,
    status: 'pending',
    time: '2024-01-05 10:00',
  },
  {
    id: 4,
    type: 'system',
    title: '存储空间警告',
    content: '主服务器存储使用率已达到 75%',
    recipients: 5,
    sent: 5,
    failed: 0,
    status: 'sent',
    time: '2024-01-05 08:00',
  },
  {
    id: 5,
    type: 'announcement',
    title: '新功能上线通知',
    content: '新增播放热力图和用户行为分析功能',
    recipients: 1234,
    sent: 1234,
    failed: 0,
    status: 'sent',
    time: '2024-01-04 18:00',
  },
]

const filteredNotifications = ref<Notification[]>([])

const loadNotifications = async () => {
  loading.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 500))
    notifications.value = mockNotifications
    filteredNotifications.value = mockNotifications
  } finally {
    loading.value = false
  }
}

const applyFilters = () => {
  let result = [...notifications.value]

  if (searchQuery.value) {
    result = result.filter(n =>
      n.title.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      n.content.toLowerCase().includes(searchQuery.value.toLowerCase())
    )
  }

  if (statusFilter.value !== 'all') {
    result = result.filter(n => n.status === statusFilter.value)
  }

  if (typeFilter.value !== 'all') {
    result = result.filter(n => n.type === typeFilter.value)
  }

  filteredNotifications.value = result
}

const getStatusClass = (status: string) => {
  switch (status) {
    case 'sent': return 'status-sent'
    case 'pending': return 'status-pending'
    case 'sending': return 'status-sending'
    case 'failed': return 'status-failed'
    default: return ''
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'sent': return '已发送'
    case 'pending': return '待发送'
    case 'sending': return '发送中'
    case 'failed': return '发送失败'
    default: return status
  }
}

const getTypeText = (type: string) => {
  switch (type) {
    case 'announcement': return '公告'
    case 'alert': return '告警'
    case 'reminder': return '提醒'
    case 'system': return '系统'
    default: return type
  }
}

const getTypeClass = (type: string) => {
  switch (type) {
    case 'announcement': return 'type-announcement'
    case 'alert': return 'type-alert'
    case 'reminder': return 'type-reminder'
    case 'system': return 'type-system'
    default: return ''
  }
}

const getSuccessRate = (n: Notification) => {
  if (n.status === 'pending') return '-'
  if (n.recipients === 0) return '0%'
  return `${Math.round((n.sent / n.recipients) * 100)}%`
}

onMounted(() => {
  loadNotifications()
})
</script>

<template>
  <div class="notification-history-page">
    <!-- 过滤器 -->
    <div class="filters-bar">
      <div class="search-box">
        <Search :size="18" />
        <input
          v-model="searchQuery"
          @input="applyFilters"
          type="text"
          placeholder="搜索通知标题或内容..."
        />
      </div>

      <div class="filter-selects">
        <select v-model="statusFilter" @change="applyFilters" class="filter-select">
          <option value="all">全部状态</option>
          <option value="sent">已发送</option>
          <option value="pending">待发送</option>
          <option value="sending">发送中</option>
          <option value="failed">发送失败</option>
        </select>

        <select v-model="typeFilter" @change="applyFilters" class="filter-select">
          <option value="all">全部类型</option>
          <option value="announcement">公告</option>
          <option value="alert">告警</option>
          <option value="reminder">提醒</option>
          <option value="system">系统</option>
        </select>
      </div>

      <div class="result-count">
        共 {{ filteredNotifications.length }} 条记录
      </div>
    </div>

    <!-- 通知列表 -->
    <div class="notifications-list">
      <div v-for="notif in filteredNotifications" :key="notif.id" class="notification-card">
        <div class="notif-header">
          <div class="notif-type" :class="getTypeClass(notif.type)">
            <Bell :size="16" />
            <span>{{ getTypeText(notif.type) }}</span>
          </div>
          <div class="notif-status" :class="getStatusClass(notif.status)">
            <CheckCircle v-if="notif.status === 'sent'" :size="14" />
            <Clock v-else-if="notif.status === 'pending'" :size="14" />
            <XCircle v-else-if="notif.status === 'failed'" :size="14" />
            <span>{{ getStatusText(notif.status) }}</span>
          </div>
          <span class="notif-time">{{ notif.time }}</span>
        </div>

        <div class="notif-content">
          <h3 class="notif-title">{{ notif.title }}</h3>
          <p class="notif-text">{{ notif.content }}</p>
        </div>

        <div class="notif-stats">
          <div class="stat-item">
            <span class="stat-label">目标用户</span>
            <span class="stat-value">{{ notif.recipients.toLocaleString() }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">已送达</span>
            <span class="stat-value success">{{ notif.sent.toLocaleString() }}</span>
          </div>
          <div class="stat-item" v-if="notif.failed > 0">
            <span class="stat-label">失败</span>
            <span class="stat-value error">{{ notif.failed }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">送达率</span>
            <span class="stat-rate" :class="{ good: getSuccessRate(notif) === '100%', bad: getSuccessRate(notif) !== '-' && getSuccessRate(notif) !== '100%' }">
              {{ getSuccessRate(notif) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!filteredNotifications.length && !loading" class="empty-state">
        <Bell :size="48" />
        <p>没有找到相关通知记录</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.notification-history-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 过滤栏 */
.filters-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: white;
  border-radius: 10px;
  border: 1px solid #e8edf3;
  flex-wrap: wrap;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  flex: 1;
  max-width: 400px;
  min-width: 200px;
}

.search-box input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 0.875rem;
  color: #1a1a2e;
  flex: 1;
}

.filter-selects {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.filter-select {
  padding: 0.5rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #475569;
  background: white;
}

.result-count {
  margin-left: auto;
  font-size: 0.875rem;
  color: #94a3b8;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .page-title {
    font-size: 1.25rem;
  }

  .filters-bar {
    gap: 0.75rem;
    padding: 0.75rem;
  }

  .search-box {
    max-width: none;
    width: 100%;
    order: -1;
  }

  .filter-selects {
    width: 100%;
  }

  .filter-select {
    flex: 1;
    min-width: 120px;
  }

  .result-count {
    width: 100%;
    margin-left: 0;
    text-align: center;
  }
}

/* 通知列表 */
.notifications-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.notification-card {
  background: white;
  border-radius: 12px;
  padding: 1.25rem;
  border: 1px solid #e8edf3;
  transition: all 0.2s ease;
}

.notification-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.notif-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.notif-type {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.type-announcement { background: rgba(103, 58, 183, 0.15); color: #673AB7; }
.type-alert { background: rgba(244, 67, 54, 0.15); color: #F44336; }
.type-reminder { background: rgba(255, 152, 0, 0.15); color: #FF9800; }
.type-system { background: rgba(76, 175, 80, 0.15); color: #4CAF50; }

.notif-status {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-sent { background: rgba(76, 175, 80, 0.15); color: #4CAF50; }
.status-pending { background: rgba(255, 152, 0, 0.15); color: #FF9800; }
.status-sending { background: rgba(103, 58, 183, 0.15); color: #673AB7; }
.status-failed { background: rgba(244, 67, 54, 0.15); color: #F44336; }

.notif-time {
  margin-left: auto;
  font-size: 0.8rem;
  color: #94a3b8;
}

.notif-content {
  margin-bottom: 1rem;
}

.notif-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 0.25rem 0;
}

.notif-text {
  font-size: 0.875rem;
  color: #64748b;
  margin: 0;
}

.notif-stats {
  display: flex;
  gap: 2rem;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.stat-label {
  font-size: 0.7rem;
  color: #94a3b8;
}

.stat-value {
  font-size: 0.9rem;
  font-weight: 500;
  color: #1a1a2e;
}

.stat-value.success { color: #4CAF50; }
.stat-value.error { color: #F44336; }

.stat-rate {
  font-size: 0.9rem;
  font-weight: 500;
  color: #64748b;
}

.stat-rate.good { color: #4CAF50; }
.stat-rate.bad { color: #FF9800; }

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  color: #94a3b8;
}

.empty-state svg {
  margin-bottom: 1rem;
  opacity: 0.5;
}
</style>
