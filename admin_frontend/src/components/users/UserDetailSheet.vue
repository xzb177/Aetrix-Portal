<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  X,
  User,
  Mail,
  Send,
  Shield,
  Crown,
  Calendar,
  CreditCard,
  Tv,
  Check,
  Ban,
  Trash2,
  Copy,
  RefreshCw,
} from 'lucide-vue-next'

export interface UserDetail {
  id: number
  username: string
  email?: string
  telegram_id?: string
  is_active: boolean
  is_staff: boolean
  is_vip: boolean
  current_plan?: string
  vip_expires_at?: string
  created_at: string
  last_login?: string
  subscriptions?: Array<{
    id: number
    plan_name: string
    status: string
    start_date: string
    end_date: string
  }>
  emby_accounts?: Array<{
    id: number
    server_name: string
    username: string
    password: string
    expires_at: string
  }>
}

interface Props {
  user?: UserDetail | null
  loading?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  close: []
  toggleStatus: [type: 'active' | 'staff']
  delete: []
  refreshEmby: [accountId: number]
}>()

// 用户引用（用于 emit）
const userRef = computed(() => props.user)

// 复制到剪贴板
const copyToClipboard = (text: string) => {
  navigator.clipboard.writeText(text)
}

// 格式化日期
const formatDate = (dateStr?: string) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 格式化剩余天数
const daysRemaining = (dateStr?: string) => {
  if (!dateStr) return null
  const date = new Date(dateStr)
  const now = new Date()
  const days = Math.ceil((date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
  if (days <= 0) return { text: '已过期', color: 'danger' }
  if (days <= 7) return { text: `${days}天`, color: 'danger' }
  if (days <= 30) return { text: `${days}天`, color: 'warning' }
  return { text: `${days}天`, color: 'success' }
}

// VIP 状态
const vipStatus = computed(() => {
  if (!props.user?.is_vip) return null
  const expiry = daysRemaining(props.user.vip_expires_at)
  return {
    text: expiry?.text || '永久',
    color: expiry?.color || 'success'
  }
})

// 显示删除确认
const showDeleteConfirm = ref(false)

const handleDelete = () => {
  showDeleteConfirm.value = true
}

const confirmDelete = () => {
  emit('delete')
  showDeleteConfirm.value = false
}

// 信息分组
const infoSections = computed(() => {
  if (!props.user) return []

  return [
    {
      title: '基本信息',
      icon: User,
      items: [
        { label: '用户 ID', value: props.user.id, mono: true },
        { label: '用户名', value: props.user.username },
        { label: '邮箱', value: props.user.email || '未设置', icon: Mail },
        { label: 'Telegram ID', value: props.user.telegram_id || '未绑定', icon: Send },
        { label: '注册时间', value: formatDate(props.user.created_at), icon: Calendar },
        { label: '最后登录', value: formatDate(props.user.last_login), icon: Calendar },
      ] as Array<{
        label: string
        value: string | number
        mono?: boolean
        icon?: any
        color?: string
      }>
    },
    {
      title: '账户状态',
      icon: Shield,
      items: [
        {
          label: '状态',
          value: props.user.is_active ? '活跃' : '禁用',
          color: props.user.is_active ? 'success' : 'danger',
          icon: props.user.is_active ? Check : Ban
        },
        {
          label: '管理员',
          value: props.user.is_staff ? '是' : '否',
          color: props.user.is_staff ? 'warning' : 'gray',
          icon: Shield
        },
        {
          label: 'VIP',
          value: props.user.is_vip ? vipStatus.value?.text || '是' : '否',
          color: props.user.is_vip ? vipStatus.value?.color || 'warning' : 'gray',
          icon: Crown
        },
        props.user.current_plan ? {
          label: '当前套餐',
          value: props.user.current_plan,
          icon: CreditCard
        } : null,
      ].filter((item): item is NonNullable<typeof item> => item !== null)
    }
  ]
})
</script>

<template>
  <Transition name="sheet">
    <div v-if="user" class="detail-sheet-overlay" @click.self="emit('close')">
      <div class="detail-sheet">
        <!-- 头部 -->
        <div class="detail-header">
          <div class="user-profile">
            <div class="user-avatar-large">
              {{ user.username.charAt(0).toUpperCase() }}
            </div>
            <div class="user-info">
              <h2 class="user-name">{{ user.username }}</h2>
              <p class="user-id-text">ID: {{ user.id }}</p>
            </div>
          </div>
          <button class="close-btn" @click="emit('close')">
            <X :size="24" />
          </button>
        </div>

        <!-- 内容区 -->
        <div class="detail-content">
          <!-- 加载状态 -->
          <div v-if="loading" class="detail-loading">
            <div class="loading-spinner"></div>
            <p>加载中...</p>
          </div>

          <template v-else>
            <!-- 信息分组 -->
            <div
              v-for="section in infoSections"
              :key="section.title"
              class="detail-section"
            >
              <div class="detail-section-header">
                <component :is="section.icon" :size="16" />
                <span>{{ section.title }}</span>
              </div>
              <div class="detail-section-body">
                <div
                  v-for="(item, idx) in section.items"
                  :key="idx"
                  class="detail-row"
                  :class="`detail-row-${(item as any).color || 'default'}`"
                >
                  <div class="detail-row-label">
                    <component v-if="item.icon" :is="item.icon" :size="14" />
                    <span>{{ item.label }}</span>
                  </div>
                  <div
                    class="detail-row-value"
                    :class="{ 'detail-row-mono': (item as any).mono }"
                  >
                    {{ item.value }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 订阅记录 -->
            <div class="detail-section">
              <div class="detail-section-header">
                <CreditCard :size="16" />
                <span>订阅记录</span>
              </div>
              <div class="detail-section-body">
                <div v-if="user.subscriptions && user.subscriptions.length > 0" class="subscription-list">
                  <div
                    v-for="sub in user.subscriptions"
                    :key="sub.id"
                    class="subscription-card"
                  >
                    <div class="sub-header">
                      <span class="sub-name">{{ sub.plan_name }}</span>
                      <span :class="['sub-status', sub.status === 'active' ? 'sub-active' : 'sub-expired']">
                        {{ sub.status === 'active' ? '有效' : '过期' }}
                      </span>
                    </div>
                    <div class="sub-dates">
                      <span>{{ formatDate(sub.start_date) }}</span>
                      <ChevronRight :size="12" />
                      <span>{{ formatDate(sub.end_date) }}</span>
                    </div>
                  </div>
                </div>
                <div v-else class="empty-state-small">
                  <CreditCard :size="20" />
                  <span>暂无订阅记录</span>
                </div>
              </div>
            </div>

            <!-- Emby 账号 -->
            <div class="detail-section">
              <div class="detail-section-header">
                <Tv :size="16" />
                <span>Emby 账号</span>
              </div>
              <div class="detail-section-body">
                <div v-if="user.emby_accounts && user.emby_accounts.length > 0" class="emby-list">
                  <div
                    v-for="acc in user.emby_accounts"
                    :key="acc.id"
                    class="emby-card"
                  >
                    <div class="emby-header">
                      <span class="emby-server">{{ acc.server_name }}</span>
                      <span
                        v-if="acc.expires_at"
                        :class="['emby-status', `emby-status-${daysRemaining(acc.expires_at)?.color || 'success'}`]"
                      >
                        {{ daysRemaining(acc.expires_at)?.text || '永久' }}
                      </span>
                    </div>
                    <div class="emby-credentials">
                      <div class="credential-item">
                        <span class="credential-label">用户名</span>
                        <div class="credential-value">
                          <code>{{ acc.username }}</code>
                          <button class="copy-btn" @click="copyToClipboard(acc.username)">
                            <Copy :size="12" />
                          </button>
                        </div>
                      </div>
                      <div class="credential-item">
                        <span class="credential-label">密码</span>
                        <div class="credential-value">
                          <code>{{ acc.password }}</code>
                          <button class="copy-btn" @click="copyToClipboard(acc.password)">
                            <Copy :size="12" />
                          </button>
                        </div>
                      </div>
                    </div>
                    <button
                      class="emby-refresh-btn"
                      @click="emit('refreshEmby', acc.id)"
                    >
                      <RefreshCw :size="12" />
                      刷新账号
                    </button>
                  </div>
                </div>
                <div v-else class="empty-state-small">
                  <Tv :size="20" />
                  <span>暂无 Emby 账号</span>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- 底部操作栏 -->
        <div class="detail-footer">
          <button
            :class="['footer-btn', user.is_active ? 'footer-btn-danger' : 'footer-btn-success']"
            @click="emit('toggleStatus', 'active')"
          >
            <Ban v-if="user.is_active" :size="18" />
            <Check v-else :size="18" />
            {{ user.is_active ? '禁用用户' : '激活用户' }}
          </button>
          <button
            :class="['footer-btn', user.is_staff ? 'footer-btn-warning' : 'footer-btn-default']"
            @click="emit('toggleStatus', 'staff')"
          >
            <Shield :size="18" />
            {{ user.is_staff ? '取消管理员' : '设为管理员' }}
          </button>
          <button class="footer-btn footer-btn-danger" @click="handleDelete">
            <Trash2 :size="18" />
            删除
          </button>
        </div>

        <!-- 删除确认 -->
        <Transition name="confirm">
          <div v-if="showDeleteConfirm" class="delete-confirm">
            <div class="confirm-content">
              <div class="confirm-icon">
                <Trash2 :size="24" />
              </div>
              <p class="confirm-text">确认删除此用户？</p>
              <div class="confirm-actions">
                <button class="confirm-btn confirm-btn-cancel" @click="showDeleteConfirm = false">
                  取消
                </button>
                <button class="confirm-btn confirm-btn-danger" @click="confirmDelete">
                  确认删除
                </button>
              </div>
            </div>
          </div>
        </Transition>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* Sheet 遮罩 */
.detail-sheet-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.detail-sheet {
  width: 100%;
  max-width: 500px;
  max-height: 90vh;
  background: var(--bg-surface);
  border-radius: 20px 20px 0 0;
  display: flex;
  flex-direction: column;
  box-shadow: 0 -4px 30px rgba(0, 0, 0, 0.4);
}

/* 头部 */
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-avatar-large {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 600;
}

.user-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-name {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.user-id-text {
  font-size: 13px;
  color: var(--text-tertiary);
  font-family: monospace;
}

.close-btn {
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
}

.close-btn:active {
  background: rgba(255, 255, 255, 0.1);
}

/* 内容区 */
.detail-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.detail-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 12px;
  color: var(--text-tertiary);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 信息分组 */
.detail-section {
  margin-bottom: 20px;
}

.detail-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 10px;
  margin-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.detail-section-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
}

.detail-row-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

.detail-row-value {
  font-size: 14px;
  color: var(--text-primary);
}

.detail-row-mono {
  font-family: monospace;
}

.detail-row-success .detail-row-value {
  color: #10b981;
}

.detail-row-danger .detail-row-value {
  color: #ef4444;
}

.detail-row-warning .detail-row-value {
  color: #f59e0b;
}

.detail-row-gray .detail-row-value {
  color: var(--text-tertiary);
}

/* 订阅记录 */
.subscription-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.subscription-card {
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.sub-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.sub-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.sub-status {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
}

.sub-active {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.sub-expired {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.sub-dates {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-tertiary);
}

/* Emby 账号 */
.emby-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.emby-card {
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.emby-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.emby-server {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.emby-status {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
}

.emby-status-success {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.emby-status-warning {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.emby-status-danger {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.emby-credentials {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

.credential-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.credential-label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.credential-value {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
}

.credential-value code {
  font-family: monospace;
  font-size: 13px;
  color: var(--text-primary);
}

.copy-btn {
  padding: 4px;
  border-radius: 6px;
  border: none;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  cursor: pointer;
}

.copy-btn:active {
  background: rgba(255, 255, 255, 0.15);
}

.emby-refresh-btn {
  width: 100%;
  padding: 8px;
  border-radius: 8px;
  border: none;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
}

.emby-refresh-btn:active {
  background: rgba(99, 102, 241, 0.2);
}

.empty-state-small {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  gap: 10px;
  color: var(--text-tertiary);
}

.empty-state-small span {
  font-size: 13px;
}

/* 底部操作栏 */
.detail-footer {
  display: flex;
  padding: 12px 16px;
  gap: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(20, 21, 26, 0.95);
}

.footer-btn {
  flex: 1;
  height: 44px;
  border-radius: 12px;
  border: none;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  transition: all 150ms ease;
}

.footer-btn-default {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.footer-btn-default:active {
  background: rgba(255, 255, 255, 0.12);
}

.footer-btn-success {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.footer-btn-success:active {
  background: rgba(16, 185, 129, 0.25);
}

.footer-btn-warning {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.footer-btn-warning:active {
  background: rgba(245, 158, 11, 0.25);
}

.footer-btn-danger {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.footer-btn-danger:active {
  background: rgba(239, 68, 68, 0.25);
}

/* 删除确认 */
.delete-confirm {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 20px 20px 0 0;
  z-index: 10;
}

.confirm-content {
  width: 80%;
  max-width: 280px;
  text-align: center;
}

.confirm-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto 16px;
  border-radius: 50%;
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  display: flex;
  align-items: center;
  justify-content: center;
}

.confirm-text {
  font-size: 15px;
  color: var(--text-primary);
  margin-bottom: 20px;
}

.confirm-actions {
  display: flex;
  gap: 10px;
}

.confirm-btn {
  flex: 1;
  height: 40px;
  border-radius: 10px;
  border: none;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.confirm-btn-cancel {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.confirm-btn-danger {
  background: #ef4444;
  color: white;
}

/* Sheet 动画 */
.sheet-enter-active,
.sheet-leave-active {
  transition: all 300ms ease;
}

.sheet-enter-from,
.sheet-leave-to {
  opacity: 0;
}

.sheet-enter-from .detail-sheet,
.sheet-leave-to .detail-sheet {
  transform: translateY(100%);
}

.sheet-enter-to .detail-sheet,
.sheet-leave-from .detail-sheet {
  transform: translateY(0);
}

.confirm-enter-active,
.confirm-leave-active {
  transition: all 200ms ease;
}

.confirm-enter-from,
.confirm-leave-to {
  opacity: 0;
}

.confirm-enter-to,
.confirm-leave-from {
  opacity: 1;
}
</style>
