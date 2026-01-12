<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { inviteApi } from '@/api'
import {
  Users,
  Copy,
  Check,
  Calendar,
  Gift,
  Crown,
  ChevronRight,
  Sparkles,
  RefreshCw,
  AlertCircle
} from 'lucide-vue-next'

const userStore = useUserStore()

// 邀请数据
const inviteData = ref({
  code: '',
  useCount: 0,
  totalInvitations: 0,
  totalRewards: 0
})

const inviteRecords = ref<any[]>([])
const loading = ref(false)
const copying = ref(false)
const copied = ref(false)
const generatingCode = ref(false)

// 错误状态 - 新增
const error = ref<{
  message: string
  code?: string
  requestId?: string
} | null>(null)

const isRetrying = ref(false)

// 生成请求 ID 用于日志追踪
const generateRequestId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`

// 奖励规则 - 从系统配置获取
const rewardRules = ref([
  { title: '邀请好友', reward: '', desc: '好友使用您的邀请码注册' },
  { title: '好友注册', reward: '', desc: '好友注册成功自动发放' }
])

// 获取邀请数据和配置 - 重构，添加完整错误处理
async function fetchInviteData() {
  const requestId = generateRequestId()
  console.log(`[invite/${requestId}] 开始获取邀请数据`)

  loading.value = true
  error.value = null

  try {
    // 使用超时控制
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('请求超时')), 15000)
    )

    // 分别请求，避免一个失败导致全部失败
    let stats: any = {}
    let records: any[] = []
    let config: any = {}

    // 1. 获取统计（核心，含邀请码）
    try {
      const statsPromise = inviteApi.getStats()
      const statsRes = await Promise.race([statsPromise, timeoutPromise]) as any
      console.log(`[invite/${requestId}] stats响应:`, { status: statsRes.status, data: statsRes.data })
      stats = statsRes.data || statsRes || {}
    } catch (err: any) {
      console.error(`[invite/${requestId}] 获取统计失败:`, err)
      const statusCode = err.response?.status
      const errorMessage = err.response?.data?.detail || err.message

      if (statusCode === 401) {
        error.value = { message: '请先登录后使用邀请功能', code: '401', requestId }
        // 401 会被拦截器处理，直接返回
        return
      } else if (statusCode === 403) {
        // 检查是否是邀请功能未启用
        if (errorMessage?.includes('未启用') || errorMessage?.includes('enabled')) {
          error.value = { message: '邀请功能暂未开放，请联系管理员', code: '403', requestId }
        } else {
          error.value = { message: '权限不足：' + (errorMessage || '无法访问邀请功能'), code: '403', requestId }
        }
      } else if (statusCode === 500) {
        error.value = { message: '服务异常，请稍后重试', code: '500', requestId }
      } else if (err.message === '请求超时') {
        error.value = { message: '网络请求超时，请检查网络后重试', code: 'TIMEOUT', requestId }
      } else if (!statusCode) {
        // 网络错误
        error.value = { message: '网络连接失败，请检查网络', code: 'NETWORK', requestId }
      } else {
        error.value = { message: `获取邀请码失败 (${statusCode})：${errorMessage || '未知错误'}`, code: String(statusCode), requestId }
      }
    }

    // 2. 获取记录（非核心，失败不影响邀请码显示）
    if (!error.value) {
      try {
        const recordsRes = await inviteApi.getRecords({ limit: 10 }) as any
        records = recordsRes.data || recordsRes || []
      } catch (err) {
        console.warn(`[invite/${requestId}] 获取记录失败（非致命）:`, err)
      }
    }

    // 3. 获取配置（非核心）
    try {
      const configRes = await fetch('/api/user/invitation/config')
      config = await configRes.json()
    } catch (err) {
      console.warn(`[invite/${requestId}] 获取配置失败（非致命）:`, err)
    }

    // 如果有错误，不更新数据但允许重试
    if (error.value) {
      return
    }

    // 更新数据
    inviteData.value = {
      code: stats.my_code || '',
      useCount: stats.use_count || 0,
      totalInvitations: stats.total_invitations || 0,
      totalRewards: stats.total_rewards || 0
    }
    inviteRecords.value = records

    // 更新奖励配置
    if (config?.invitation_reward_points) {
      rewardRules.value[0].reward = `¥${config.invitation_reward_points}`
    }
    if (config?.invitation_invitee_reward_points) {
      rewardRules.value[1].reward = `¥${config.invitation_invitee_reward_points}`
    }

    console.log(`[invite/${requestId}] 数据加载成功`, {
      hasCode: !!inviteData.value.code,
      totalInvitations: inviteData.value.totalInvitations
    })

  } catch (err: any) {
    console.error(`[invite/${requestId}] 未预期的错误:`, err)
    error.value = {
      message: err.message || '加载失败',
      code: 'UNKNOWN',
      requestId
    }
  } finally {
    loading.value = false
    isRetrying.value = false
  }
}

// 复制邀请链接
async function copyLink() {
  if (!inviteData.value.code) return

  copying.value = true
  try {
    const url = `${window.location.origin}/?invite=${inviteData.value.code}`
    await navigator.clipboard.writeText(url)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (error) {
    console.error('复制失败:', error)
  } finally {
    copying.value = false
  }
}

// 生成新邀请码
async function generateNewCode() {
  if (generatingCode.value) return

  generatingCode.value = true
  try {
    const res = await inviteApi.generateCode()
    const data = res.data || res || {}
    inviteData.value.code = data.code || ''
    inviteData.value.useCount = data.use_count || 0
  } catch (error) {
    console.error('生成邀请码失败:', error)
  } finally {
    generatingCode.value = false
  }
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

onMounted(() => {
  fetchInviteData()
})
</script>

<template>
  <div class="invite-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">
          <Users :size="24" />
          邀请好友
        </h1>
        <p class="page-subtitle">邀请好友加入，双方都可获得余额奖励</p>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="invite-content">
      <!-- 邀请码卡片 -->
      <div class="card glass-card invite-card">
        <div class="invite-header">
          <div class="invite-icon">
            <Sparkles :size="24" />
          </div>
          <div class="invite-info">
            <span class="invite-label">我的邀请码</span>
            <!-- 加载中 -->
            <span v-if="loading && !inviteData.code" class="invite-code invite-code-loading">
              <span class="spinner-small"></span>
              加载中...
            </span>
            <!-- 错误态 -->
            <span v-else-if="error && !inviteData.code" class="invite-code invite-code-error">
              <AlertCircle :size="18" />
              {{ error.message || '加载失败' }}
            </span>
            <!-- 正常显示 -->
            <span v-else class="invite-code">{{ inviteData.code || '暂无邀请码' }}</span>
          </div>
          <!-- 加载中或错误时显示操作按钮 -->
          <div v-if="!loading && (!inviteData.code || error)" class="action-buttons">
            <button
              @click="fetchInviteData"
              :disabled="isRetrying"
              class="btn-copy btn-retry"
            >
              <RefreshCw :size="16" :class="{ spinning: isRetrying }" />
              {{ isRetrying ? '重试中...' : '重新获取' }}
            </button>
            <button
              @click="generateNewCode"
              :disabled="generatingCode"
              class="btn-copy btn-generate-code"
            >
              <Sparkles :size="16" />
              {{ generatingCode ? '生成中...' : '生成新码' }}
            </button>
          </div>
          <!-- 正常时显示复制按钮 -->
          <button
            v-else
            @click="copyLink"
            :disabled="copying || !inviteData.code"
            class="btn-copy"
          >
            <Check v-if="copied" :size="16" />
            <Copy v-else :size="16" />
            {{ copied ? '已复制' : '复制' }}
          </button>
        </div>

        <!-- 统计数据 -->
        <div class="invite-stats">
          <div class="stat-item">
            <Users :size="18" />
            <span>已邀请 <strong>{{ inviteData.totalInvitations }}</strong> 人</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <Crown :size="18" />
            <span>累计获得 <strong>¥{{ inviteData.totalRewards }}</strong></span>
          </div>
        </div>

        <!-- 生成新码按钮 -->
        <div class="generate-section">
          <button
            @click="generateNewCode"
            :disabled="generatingCode"
            class="btn-generate"
          >
            <Sparkles :size="14" />
            {{ generatingCode ? '生成中...' : '生成新邀请码' }}
          </button>
        </div>
      </div>

      <!-- 奖励规则 -->
      <div class="card glass-card rules-card">
        <h2 class="section-title">
          <Gift :size="18" />
          奖励规则
        </h2>
        <div class="rules-list">
          <div
            v-for="(rule, index) in rewardRules"
            :key="index"
            class="rule-item glass-card"
          >
            <div class="rule-info">
              <span class="rule-title">{{ rule.title }}</span>
              <span class="rule-desc">{{ rule.desc }}</span>
            </div>
            <span class="rule-reward">{{ rule.reward || '-' }}</span>
          </div>
        </div>
      </div>

      <!-- 邀请记录 -->
      <div class="card glass-card records-card">
        <h2 class="section-title">
          <Calendar :size="18" />
          邀请记录
        </h2>

        <div v-if="loading" class="loading-state">
          <div class="spinner"></div>
          <p>加载中...</p>
        </div>

        <div v-else-if="inviteRecords.length === 0" class="empty-state">
          <div class="empty-icon">
            <Users :size="32" />
          </div>
          <p>暂无邀请记录</p>
          <p class="empty-hint">分享邀请链接给好友后即可看到记录</p>
        </div>

        <div v-else class="records-list">
          <div
            v-for="record in inviteRecords"
            :key="record.id"
            class="record-item glass-card"
          >
            <div class="record-avatar">
              {{ record.invitee_username?.[0]?.toUpperCase() || '?' }}
            </div>
            <div class="record-info">
              <span class="record-name">{{ record.invitee_username }}</span>
              <span class="record-date">{{ formatDate(record.created_at) }}</span>
            </div>
            <span class="record-reward">+¥{{ record.reward_points }}</span>
          </div>
        </div>
      </div>

      <!-- 分享按钮 -->
      <div class="card glass-card share-card">
        <h2 class="section-title">
          <Share :size="18" />
          分享给好友
        </h2>
        <div class="share-buttons">
          <button
            @click="copyLink"
            :disabled="copying || !inviteData.code"
            class="btn btn-primary"
          >
            <Copy :size="16" />
            复制邀请链接
          </button>
          <RouterLink to="/subscription" class="btn btn-secondary">
            <Gift :size="16" />
            查看订阅套餐
          </RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { Share } from 'lucide-vue-next'

export default {
  components: {
    Share
  }
}
</script>

<style scoped>
.invite-page {
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
  flex-direction: column;
  gap: 0.5rem;
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

.page-subtitle {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
  margin: 0;
}

/* 主内容区 */
.invite-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 卡片基础样式 */
.card {
  border-radius: 0.75rem;
  padding: 1.25rem;
}

/* 邀请码卡片 */
.invite-card {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(59, 130, 246, 0.1) 100%);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.invite-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.invite-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, #10b981, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.invite-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.invite-label {
  font-size: 0.75rem;
  color: rgba(250, 250, 250, 0.6);
}

.invite-code {
  font-size: 1.25rem;
  font-weight: 600;
  font-family: ui-monospace, monospace;
  color: #fafafa;
  letter-spacing: 0.1em;
}

.btn-copy {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.625rem 1rem;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 0.5rem;
  color: #fafafa;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-copy:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
}

.btn-copy:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-copy.copied {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.3);
}

/* 统计数据 */
.invite-stats {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  padding: 1rem 0;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.7);
}

.stat-item strong {
  color: #10b981;
  font-weight: 600;
}

.stat-divider {
  width: 1px;
  height: 16px;
  background: rgba(255, 255, 255, 0.1);
}

/* 生成新码 */
.generate-section {
  display: flex;
  justify-content: center;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.btn-generate {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: transparent;
  border: none;
  color: rgba(16, 185, 129, 0.8);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-generate:hover:not(:disabled) {
  color: #10b981;
}

.btn-generate:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 章节标题 */
.section-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: #fafafa;
  margin: 0 0 1rem 0;
}

/* 邀请码状态样式 */
.invite-code-loading {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: rgba(250, 250, 250, 0.6) !important;
}

.invite-code-error {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  color: #f87171 !important;
  font-size: 1rem !important;
}

.spinner-small {
  width: 14px;
  height: 14px;
  border: 1.5px solid rgba(255, 255, 255, 0.2);
  border-top-color: #10b981;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.btn-retry {
  background: rgba(239, 68, 68, 0.15) !important;
  border-color: rgba(239, 68, 68, 0.3) !important;
  color: #f87171 !important;
}

.btn-retry:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.25) !important;
}

.spinning {
  animation: spin 0.8s linear infinite;
}

/* 操作按钮组 */
.action-buttons {
  display: flex;
  gap: 0.5rem;
}

.action-buttons .btn-copy {
  flex: 1;
  justify-content: center;
}

.btn-generate-code {
  background: rgba(16, 185, 129, 0.15) !important;
  border-color: rgba(16, 185, 129, 0.3) !important;
  color: #10b981 !important;
}

.btn-generate-code:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.25) !important;
}

/* 奖励规则 */
.rules-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.rule-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.03);
  transition: all 0.2s ease;
}

.rule-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.rule-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.rule-title {
  font-weight: 500;
  color: #fafafa;
  font-size: 0.9375rem;
}

.rule-desc {
  font-size: 0.8125rem;
  color: rgba(250, 250, 250, 0.5);
}

.rule-reward {
  padding: 0.375rem 0.875rem;
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  border-radius: 0.5rem;
  font-size: 0.8125rem;
  font-weight: 600;
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
  margin-top: 0.5rem;
}

/* 邀请记录列表 */
.records-list {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.record-item {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.03);
  transition: all 0.2s ease;
}

.record-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.record-avatar {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, #10b981, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 600;
  font-size: 0.9375rem;
}

.record-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.record-name {
  font-weight: 500;
  color: #fafafa;
  font-size: 0.9375rem;
}

.record-date {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: rgba(250, 250, 250, 0.4);
}

.record-reward {
  padding: 0.3125rem 0.625rem;
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border-radius: 0.5rem;
  font-size: 0.8125rem;
  font-weight: 600;
}

/* 分享按钮 */
.share-buttons {
  display: flex;
  gap: 0.75rem;
}

.share-buttons .btn {
  flex: 1;
}

/* 按钮样式 */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}

.btn-primary {
  background: #10b981;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #059669;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
  .invite-page {
    padding: 1rem 0.75rem;
  }

  .invite-stats {
    flex-direction: column;
    gap: 0.5rem;
  }

  .stat-divider {
    display: none;
  }

  .share-buttons {
    flex-direction: column;
  }
}
</style>
