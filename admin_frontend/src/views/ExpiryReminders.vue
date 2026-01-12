<script setup lang="ts">
import { ref, computed } from 'vue'
import { Clock, Bell, Send, Calendar, CheckCircle } from 'lucide-vue-next'

interface ExpiringUser {
  id: string
  username: string
  emby: string
  vipLevel: string
  expireDate: string
  daysLeft: number
  notified: boolean
}

const expiringUsers = ref<ExpiringUser[]>([
  { id: '1', username: 'user123', emby: 'user123', vipLevel: 'VIP月卡', expireDate: '2024-01-10', daysLeft: 5, notified: false },
  { id: '2', username: 'user456', emby: 'user456', vipLevel: 'VIP季卡', expireDate: '2024-01-08', daysLeft: 3, notified: true },
  { id: '3', username: 'user789', emby: 'user789', vipLevel: 'VIP年卡', expireDate: '2024-01-07', daysLeft: 2, notified: false },
  { id: '4', username: 'user321', emby: 'user321', vipLevel: 'VIP月卡', expireDate: '2024-01-06', daysLeft: 1, notified: false },
  { id: '5', username: 'user654', emby: 'user654', vipLevel: 'VIP季卡', expireDate: '2024-01-15', daysLeft: 10, notified: true },
])

const reminderDays = ref<number[]>([7, 3, 1])
const customMessage = ref('您的会员即将到期，请及时续费以继续享受服务。')

const stats = computed(() => ({
  total: expiringUsers.value.length,
  notNotified: expiringUsers.value.filter(u => !u.notified).length,
  urgent: expiringUsers.value.filter(u => u.daysLeft <= 3).length,
}))

const sendReminder = async (userId: string) => {
  const user = expiringUsers.value.find(u => u.id === userId)
  if (user) {
    user.notified = true
  }
}

const sendBatchReminders = () => {
  const pendingUsers = expiringUsers.value.filter(u => !u.notified)
  if (confirm(`将向 ${pendingUsers.length} 位用户发送到期提醒，确认？`)) {
    pendingUsers.forEach(u => u.notified = true)
  }
}

const getUrgencyClass = (days: number) => {
  if (days <= 1) return 'urgency-critical'
  if (days <= 3) return 'urgency-high'
  if (days <= 7) return 'urgency-medium'
  return 'urgency-normal'
}

const getUrgencyText = (days: number) => {
  if (days <= 1) return '紧急'
  if (days <= 3) return '重要'
  if (days <= 7) return '提醒'
  return '正常'
}
</script>

<template>
  <div class="expiry-page">
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card stat-total">
        <div class="stat-icon">
          <Calendar :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.total }}</p>
          <p class="stat-label">即将到期用户</p>
        </div>
      </div>

      <div class="stat-card stat-pending">
        <div class="stat-icon">
          <Bell :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.notNotified }}</p>
          <p class="stat-label">待通知</p>
        </div>
      </div>

      <div class="stat-card stat-urgent">
        <div class="stat-icon">
          <Clock :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.urgent }}</p>
          <p class="stat-label">3天内到期</p>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon">
          <Send :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.total - stats.notNotified }}</p>
          <p class="stat-label">已通知</p>
        </div>
      </div>
    </div>

    <!-- 提醒设置 -->
    <div class="settings-section">
      <h2 class="section-title">提醒设置</h2>
      <div class="settings-grid">
        <div class="setting-item">
          <label>自动提醒天数</label>
          <div class="days-selector">
            <button
              v-for="day in [1, 3, 7, 15]"
              :key="day"
              :class="['day-btn', { active: reminderDays.includes(day) }]"
              @click="
                reminderDays.includes(day)
                  ? (reminderDays = reminderDays.filter(d => d !== day))
                  : reminderDays.push(day)
              "
            >
              到期前{{ day }}天
            </button>
          </div>
        </div>

        <div class="setting-item">
          <label>提醒消息模板</label>
          <textarea v-model="customMessage" class="message-template"></textarea>
        </div>
      </div>
    </div>

    <!-- 用户列表 -->
    <div class="users-section">
      <div class="section-header">
        <h2 class="section-title">即将到期用户列表</h2>
        <button class="btn-batch" @click="sendBatchReminders" :disabled="stats.notNotified === 0">
          <Send :size="16" />
          批量发送 ({{ stats.notNotified }})
        </button>
      </div>

      <div class="users-list">
        <div
          v-for="user in expiringUsers"
          :key="user.id"
          class="user-card"
          :class="getUrgencyClass(user.daysLeft)"
        >
          <div class="user-info">
            <div class="user-name">{{ user.username }}</div>
            <div class="user-emby">{{ user.emby }}</div>
          </div>

          <div class="user-details">
            <span class="user-plan">{{ user.vipLevel }}</span>
            <span class="user-expire">{{ user.expireDate }}</span>
          </div>

          <div class="user-urgency">
            <span class="urgency-badge" :class="getUrgencyClass(user.daysLeft)">
              {{ getUrgencyText(user.daysLeft) }}
            </span>
            <span class="days-left">剩 {{ user.daysLeft }} 天</span>
          </div>

          <button
            class="btn-notify"
            :disabled="user.notified"
            @click="sendReminder(user.id)"
          >
            <CheckCircle v-if="user.notified" :size="16" />
            <Send v-else :size="16" />
            {{ user.notified ? '已发送' : '发送提醒' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.expiry-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}




/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}

@media (max-width: 1024px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .page-title {
    font-size: 1.25rem;
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.stat-total .stat-icon { background: linear-gradient(135deg, #673AB7, #7B1FA2); }
.stat-pending .stat-icon { background: linear-gradient(135deg, #FF9800, #F57C00); }
.stat-urgent .stat-icon { background: linear-gradient(135deg, #F44336, #D32F2F); }
.stat-card:not(.stat-total):not(.stat-pending):not(.stat-urgent) .stat-icon {
  background: linear-gradient(135deg, #4CAF50, #43A047);
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1a1a2e;
}

.stat-label {
  font-size: 0.75rem;
  color: #64748b;
}

/* 设置区域 */
.settings-section,
.users-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 1rem 0;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}

.setting-item {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.setting-item label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}

.days-selector {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.day-btn {
  padding: 0.5rem 1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.day-btn.active {
  background: rgba(103, 58, 183, 0.15);
  border-color: #673AB7;
  color: #673AB7;
}

.message-template {
  width: 100%;
  min-height: 100px;
  padding: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  resize: vertical;
}

/* 用户列表 */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  gap: 1rem;
  flex-wrap: wrap;
}

.btn-batch {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: #673AB7;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  cursor: pointer;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .section-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .btn-batch {
    width: 100%;
    justify-content: center;
  }
}

.btn-batch:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.users-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 10px;
  border-left: 4px solid;
}

.urgency-critical {
  border-left-color: #F44336;
  background: rgba(244, 67, 54, 0.03);
}

.urgency-high {
  border-left-color: #FF9800;
  background: rgba(255, 152, 0, 0.03);
}

.urgency-medium {
  border-left-color: #FFC107;
}

.urgency-normal {
  border-left-color: #4CAF50;
}

.user-info {
  flex: 1;
}

.user-name {
  font-size: 0.95rem;
  font-weight: 500;
  color: #1a1a2e;
}

.user-emby {
  font-size: 0.75rem;
  color: #94a3b8;
}

.user-details {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.user-plan {
  font-size: 0.8rem;
  color: #673AB7;
}

.user-expire {
  font-size: 0.75rem;
  color: #94a3b8;
}

.user-urgency {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.25rem;
}

.urgency-badge {
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 500;
}

.urgency-critical .urgency-badge {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

.urgency-high .urgency-badge {
  background: rgba(255, 152, 0, 0.15);
  color: #FF9800;
}

.urgency-medium .urgency-badge {
  background: rgba(255, 193, 7, 0.15);
  color: #FFA000;
}

.urgency-normal .urgency-badge {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.days-left {
  font-size: 0.75rem;
  color: #64748b;
}

.btn-notify {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.8rem;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-notify:hover:not(:disabled) {
  border-color: #673AB7;
  color: #673AB7;
}

.btn-notify:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
