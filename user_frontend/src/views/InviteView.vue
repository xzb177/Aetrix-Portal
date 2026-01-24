<script setup lang="ts">
/**
 * 邀请好友 - Neo-Noir 2.0 设计
 *
 * 功能：
 * - 邀请码展示与复制
 * - 邀请统计仪表盘
 * - 奖励规则说明
 * - 邀请记录
 * - 分享链接（含二维码）
 */
import { ref, onMounted, computed, nextTick } from 'vue'
import { RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { inviteApi } from '@/api'
import { Button } from '@/components/ui'
import { Badge } from '@/components/ui'
import QRCode from 'qrcode'
import {
  Users,
  Copy,
  Check,
  Calendar,
  Gift,
  Crown,
  Sparkles,
  RefreshCw,
  AlertCircle,
  Share,
  X,
  QrCode
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

// 错误状态
const error = ref<{
  message: string
  code?: string
  requestId?: string
} | null>(null)

const isRetrying = ref(false)

// 二维码相关
const showQRCode = ref(false)
const qrCodeDataUrl = ref('')
const qrCodeCanvas = ref<HTMLCanvasElement | null>(null)

// 生成请求 ID
const generateRequestId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`

// 奖励规则
const rewardRules = ref([
  { title: '邀请好友', reward: '', desc: '好友使用您的邀请码注册' },
  { title: '好友注册', reward: '', desc: '好友注册成功自动发放' }
])

// 计算属性 - 邀请码是否存在
const hasInviteCode = computed(() => !!inviteData.value.code && !error.value)

// 计算属性 - 是否在错误状态
const hasError = computed(() => !loading.value && !inviteData.value.code && error.value)

// 获取邀请数据和配置
async function fetchInviteData() {
  const requestId = generateRequestId()

  loading.value = true
  error.value = null

  try {
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('请求超时')), 15000)
    )

    let stats: any = {}
    let records: any[] = []
    let config: any = {}

    // 1. 获取统计
    try {
      const statsPromise = inviteApi.getStats()
      const statsRes = await Promise.race([statsPromise, timeoutPromise]) as any
      stats = statsRes.data || statsRes || {}
    } catch (err: any) {
      const statusCode = err.response?.status
      const errorMessage = err.response?.data?.detail || err.message

      if (statusCode === 401) {
        error.value = { message: '请先登录后使用邀请功能', code: '401', requestId }
        return
      } else if (statusCode === 403) {
        if (errorMessage?.includes('未启用') || errorMessage?.includes('enabled')) {
          error.value = { message: '邀请功能暂未开放', code: '403', requestId }
        } else {
          error.value = { message: '权限不足', code: '403', requestId }
        }
      } else if (err.message === '请求超时') {
        error.value = { message: '请求超时，请重试', code: 'TIMEOUT', requestId }
      } else if (!statusCode) {
        error.value = { message: '网络连接失败', code: 'NETWORK', requestId }
      } else {
        error.value = { message: `获取失败 (${statusCode})`, code: String(statusCode), requestId }
      }
    }

    // 2. 获取记录
    if (!error.value) {
      try {
        const recordsRes = await inviteApi.getRecords({ limit: 10 }) as any
        records = recordsRes.data || recordsRes || []
      } catch (err) {
        console.warn('获取记录失败:', err)
      }
    }

    // 3. 获取配置
    try {
      const configRes = await fetch('/api/user/invitation/config')
      config = await configRes.json()
    } catch (err) {
      console.warn('获取配置失败:', err)
    }

    if (error.value) return

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
      rewardRules.value[0].reward = config.invitation_reward_points
    }
    if (config?.invitation_invitee_reward_points) {
      rewardRules.value[1].reward = config.invitation_invitee_reward_points
    }

  } catch (err: any) {
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

// 显示二维码
async function showQRCodeModal() {
  if (!inviteData.value.code) return

  showQRCode.value = true

  // 等待 DOM 更新
  await nextTick()

  // 生成二维码
  try {
    const url = `${window.location.origin}/?invite=${inviteData.value.code}`
    qrCodeDataUrl.value = await QRCode.toDataURL(url, {
      width: 240,
      margin: 2,
      color: {
        dark: '#10b981',
        light: '#ffffff'
      }
    })
  } catch (error) {
    console.error('生成二维码失败:', error)
  }
}

// 关闭二维码弹窗
function closeQRCodeModal() {
  showQRCode.value = false
  qrCodeDataUrl.value = ''
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
    <!-- ==================== 顶部标题块 ==================== -->
    <header class="page-header">
      <div class="header-content">
        <h1 class="page-title">
          <Users :size="22" />
          邀请好友
        </h1>
        <p class="page-subtitle">邀请好友加入，双方都可获得奖励</p>
      </div>
    </header>

    <!-- ==================== 主内容区 ==================== -->
    <div class="invite-content">

      <!-- 邀请码主视觉卡片 -->
      <div class="invite-hero-card">
        <div class="invite-hero-header">
          <div class="hero-icon">
            <Sparkles :size="20" />
          </div>
          <span class="hero-label">我的邀请码</span>
        </div>

        <!-- 加载中 -->
        <div v-if="loading && !inviteData.code" class="hero-loading">
          <span class="spinner"></span>
          <span>加载中</span>
        </div>

        <!-- 错误态 -->
        <div v-else-if="hasError" class="hero-error">
          <AlertCircle :size="16" />
          <span>{{ error?.message || '加载失败' }}</span>
          <button @click="fetchInviteData" :disabled="isRetrying" class="hero-retry">
            <RefreshCw :size="14" :class="{ spinning: isRetrying }" />
          </button>
        </div>

        <!-- 邀请码展示 -->
        <div v-else class="hero-code-section">
          <div class="code-display">
            <span class="code-text">{{ inviteData.code || '暂无邀请码' }}</span>
          </div>
          <button
            @click="copyLink"
            :disabled="copying || !inviteData.code"
            class="hero-copy-btn"
            :class="{ 'hero-copy-btn--copied': copied }"
          >
            <Check v-if="copied" :size="14" />
            <Copy v-else :size="14" />
            {{ copied ? '已复制' : '复制' }}
          </button>
        </div>

        <!-- 两格仪表 -->
        <div class="hero-metrics">
          <div class="metric-item">
            <div class="metric-icon">
              <Users :size="16" />
            </div>
            <div class="metric-info">
              <span class="metric-value">{{ inviteData.totalInvitations }}</span>
              <span class="metric-label">已邀请</span>
            </div>
          </div>
          <div class="metric-divider"></div>
          <div class="metric-item">
            <div class="metric-icon metric-icon--reward">
              <Crown :size="16" />
            </div>
            <div class="metric-info">
              <span class="metric-value">¥{{ inviteData.totalRewards }}</span>
              <span class="metric-label">累计获得</span>
            </div>
          </div>
        </div>

        <!-- 生成新码 -->
        <button
          v-if="!loading && hasInviteCode"
          @click="generateNewCode"
          :disabled="generatingCode"
          class="hero-generate-btn"
        >
          <Sparkles :size="12" />
          {{ generatingCode ? '生成中...' : '生成新邀请码' }}
        </button>
      </div>

      <!-- 奖励规则卡片列表 -->
      <div class="rules-section">
        <h2 class="section-title">
          <Gift :size="16" />
          奖励规则
        </h2>
        <div class="rules-list">
          <div
            v-for="(rule, index) in rewardRules"
            :key="index"
            class="rule-card"
          >
            <div class="rule-info">
              <span class="rule-title">{{ rule.title }}</span>
              <span class="rule-desc">{{ rule.desc }}</span>
            </div>
            <span class="rule-reward">
              <span v-if="rule.reward" class="reward-amount">¥{{ rule.reward }}</span>
              <span v-else class="reward-empty">-</span>
            </span>
          </div>
        </div>
      </div>

      <!-- 邀请记录 -->
      <div class="records-section">
        <h2 class="section-title">
          <Calendar :size="16" />
          邀请记录
        </h2>

        <div v-if="loading" class="loading-state">
          <span class="spinner"></span>
          <span>加载中</span>
        </div>

        <div v-else-if="inviteRecords.length === 0" class="empty-state">
          <div class="empty-icon">
            <Users :size="24" />
          </div>
          <p class="empty-title">暂无邀请记录</p>
          <p class="empty-desc">分享邀请链接给好友后即可看到记录</p>
          <button @click="copyLink" :disabled="copying || !inviteData.code" class="empty-action">
            <Share :size="14" />
            去分享
          </button>
        </div>

        <div v-else class="records-list">
          <div
            v-for="record in inviteRecords"
            :key="record.id"
            class="record-card"
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

      <!-- 分享按钮区 -->
      <div class="share-section">
        <div class="share-actions">
          <Button
            variant="primary"
            :block="true"
            :loading="copying"
            @click="copyLink"
          >
            <Copy :size="15" />
            复制邀请链接
          </Button>
          <button
            @click="showQRCodeModal"
            :disabled="!inviteData.code"
            class="share-secondary"
          >
            <QrCode :size="15" />
            二维码分享
          </button>
          <RouterLink to="/subscription" class="share-secondary">
            <Gift :size="15" />
            查看订阅套餐
          </RouterLink>
        </div>
      </div>
    </div>

    <!-- 二维码弹窗 -->
    <Teleport to="body">
      <Transition name="qrcode-modal">
        <div v-if="showQRCode" class="qrcode-modal-overlay" @click.self="closeQRCodeModal">
          <div class="qrcode-modal" @click.stop>
            <!-- 关闭按钮 -->
            <button @click="closeQRCodeModal" class="qrcode-close-btn">
              <X :size="20" />
            </button>

            <!-- 标题 -->
            <div class="qrcode-header">
              <QrCode :size="24" class="qrcode-icon" />
              <h3>扫码邀请好友</h3>
            </div>

            <!-- 二维码 -->
            <div class="qrcode-content">
              <div class="qrcode-image-wrapper">
                <img
                  v-if="qrCodeDataUrl"
                  :src="qrCodeDataUrl"
                  alt="邀请二维码"
                  class="qrcode-image"
                />
                <div v-else class="qrcode-loading">
                  <span class="spinner"></span>
                  <span>生成中...</span>
                </div>
              </div>

              <!-- 邀请码 -->
              <div class="qrcode-code">
                <span class="qrcode-code-label">邀请码</span>
                <span class="qrcode-code-value">{{ inviteData.code }}</span>
              </div>

              <!-- 提示 -->
              <p class="qrcode-hint">扫描二维码即可注册，双方都可获得奖励</p>
            </div>

            <!-- 底部操作 -->
            <div class="qrcode-footer">
              <button
                @click="copyLink"
                :disabled="copying || !inviteData.code"
                class="qrcode-action-btn"
              >
                <Check v-if="copied" :size="16" />
                <Copy v-else :size="16" />
                {{ copied ? '已复制链接' : '复制链接' }}
              </button>
              <button
                @click="closeQRCodeModal"
                class="qrcode-action-btn qrcode-action-btn--primary"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
/* ==================== 容器 ==================== */
.invite-page {
  max-width: 480px;
  margin: 0 auto;
  padding: var(--space-6, 24px) var(--space-5, 20px) var(--neo-safe-bottom);
  min-height: 100vh;
}

/* ==================== 顶部标题 ==================== */
.page-header {
  margin-bottom: var(--space-5, 20px);
}

.header-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-1, 4px);
}

.page-title {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  font-size: var(--neo-font-size-2xl, 20px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0;
  font-weight: var(--neo-font-weight-normal, 400);
}

/* ==================== 主内容区 ==================== */
.invite-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-4, 16px);
}

/* ==================== 邀请码主视觉卡片 ==================== */
.invite-hero-card {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(16, 185, 129, 0.04) 100%);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: var(--neo-radius-lg, 18px);
  padding: var(--space-4, 16px);
  position: relative;
  overflow: hidden;
}

.invite-hero-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(16, 185, 129, 0.3) 50%,
    transparent 100%
  );
}

.invite-hero-header {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  margin-bottom: var(--space-3, 12px);
}

.hero-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--neo-radius-sm, 12px);
  background: var(--neo-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-text-inverse);
}

.hero-label {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-secondary);
  font-weight: var(--neo-font-weight-medium, 500);
}

/* 加载中 */
.hero-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  padding: var(--space-4, 16px) 0;
  color: var(--neo-text-tertiary);
  font-size: var(--neo-font-size-sm, 12px);
}

/* 错误态 */
.hero-error {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px);
  background: var(--neo-danger-bg);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-danger);
  font-size: var(--neo-font-size-sm, 12px);
}

.hero-retry {
  margin-left: auto;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  border-radius: var(--neo-radius-xs, 8px);
}

.hero-retry:active {
  background: rgba(239, 68, 68, 0.2);
}

/* 邀请码展示 */
.hero-code-section {
  display: flex;
  gap: var(--space-2, 8px);
  margin-bottom: var(--space-4, 16px);
}

.code-display {
  flex: 1;
  padding: var(--space-3, 12px) var(--space-4, 16px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-sm, 12px);
  display: flex;
  align-items: center;
}

.code-text {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  font-family: ui-monospace, monospace;
  color: var(--neo-text-primary);
  letter-spacing: 0.1em;
}

.hero-copy-btn {
  display: flex;
  align-items: center;
  gap: var(--space-1, 4px);
  padding: 0 var(--space-4, 16px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-strong);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.hero-copy-btn:hover:not(:disabled) {
  background: var(--neo-bg-surface-hover);
  border-color: var(--neo-border-default);
  color: var(--neo-text-primary);
}

.hero-copy-btn:active:not(:disabled) {
  transform: scale(var(--neo-scale-press, 0.98));
}

.hero-copy-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.hero-copy-btn--copied {
  background: var(--neo-success-bg);
  border-color: var(--neo-success);
  color: var(--neo-success);
}

/* 两格仪表 */
.hero-metrics {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4, 16px);
  padding: var(--space-3, 12px) 0;
}

.metric-item {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
}

.metric-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--neo-radius-sm, 12px);
  background: var(--neo-bg-surface-2);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-text-secondary);
}

.metric-icon--reward {
  color: var(--neo-primary);
}

.metric-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-value {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
}

.metric-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

.metric-divider {
  width: 1px;
  height: 24px;
  background: var(--neo-border-subtle);
}

/* 生成新码按钮 */
.hero-generate-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  background: transparent;
  border: none;
  color: var(--neo-text-tertiary);
  font-size: var(--neo-font-size-xs, 11px);
  cursor: pointer;
  border-radius: var(--neo-radius-xs, 8px);
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.hero-generate-btn:hover:not(:disabled) {
  background: var(--neo-bg-surface-hover);
  color: var(--neo-text-secondary);
}

.hero-generate-btn:active:not(:disabled) {
  background: var(--neo-bg-surface-active);
}

.hero-generate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ==================== 章节标题 ==================== */
.section-title {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
  margin: 0;
}

/* ==================== 奖励规则 ==================== */
.rules-section {
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--space-4, 16px);
}

.rules-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
}

.rule-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3, 12px);
  padding: var(--space-3, 12px);
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-sm, 12px);
  transition: background var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.rule-card:active {
  background: var(--neo-bg-surface-hover);
}

.rule-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rule-title {
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary);
  font-size: var(--neo-font-size-sm, 12px);
}

.rule-desc {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

.rule-reward {
  flex-shrink: 0;
}

.reward-amount {
  display: inline-flex;
  align-items: center;
  padding: var(--space-1, 4px) var(--space-2, 8px);
  background: var(--neo-primary-dim);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: var(--neo-radius-full, 9999px);
  color: var(--neo-primary);
  font-size: var(--neo-font-size-xs, 11px);
  font-weight: var(--neo-font-weight-semibold, 600);
}

.reward-empty {
  padding: var(--space-1, 4px) var(--space-2, 8px);
  color: var(--neo-text-tertiary);
  font-size: var(--neo-font-size-xs, 11px);
}

/* ==================== 邀请记录 ==================== */
.records-section {
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--space-4, 16px);
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  padding: var(--space-8, 32px) 0;
  color: var(--neo-text-tertiary);
  font-size: var(--neo-font-size-sm, 12px);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-8, 32px) var(--space-4, 16px);
  text-align: center;
}

.empty-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--neo-radius-md, 14px);
  background: var(--neo-bg-surface-2);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-text-tertiary);
  margin-bottom: var(--space-3, 12px);
}

.empty-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-secondary);
  margin: 0 0 var(--space-1, 4px) 0;
}

.empty-desc {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0 0 var(--space-4, 16px) 0;
}

.empty-action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1, 4px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.empty-action:active:not(:disabled) {
  background: var(--neo-bg-surface-hover);
  transform: scale(var(--neo-scale-press, 0.98));
}

/* 记录列表 */
.records-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
}

.record-card {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
  padding: var(--space-2, 8px);
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-sm, 12px);
  transition: background var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.record-card:active {
  background: var(--neo-bg-surface-hover);
}

.record-avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--neo-radius-sm, 12px);
  background: linear-gradient(135deg, var(--neo-primary), var(--neo-primary-hover));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-text-inverse);
  font-weight: var(--neo-font-weight-semibold, 600);
  font-size: var(--neo-font-size-sm, 12px);
  flex-shrink: 0;
}

.record-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.record-name {
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary);
  font-size: var(--neo-font-size-sm, 12px);
}

.record-date {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

.record-reward {
  padding: var(--space-1, 4px) var(--space-2, 8px);
  background: var(--neo-primary-dim);
  color: var(--neo-primary);
  border-radius: var(--neo-radius-full, 9999px);
  font-size: var(--neo-font-size-xs, 11px);
  font-weight: var(--neo-font-weight-semibold, 600);
}

/* ==================== 分享按钮区 ==================== */
.share-section {
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--space-4, 16px);
}

.share-actions {
  display: flex;
  gap: var(--space-3, 12px);
}

.share-secondary {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px) var(--space-4, 16px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  text-decoration: none;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.share-secondary:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(var(--neo-scale-press, 0.98));
}

/* ==================== 动画 ==================== */
.spinner {
  width: 16px;
  height: 16px;
  border: 1.5px solid var(--neo-border-subtle);
  border-top-color: var(--neo-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 响应式 ==================== */
@media (max-width: 480px) {
  .invite-page {
    padding: var(--space-5, 20px) var(--space-4, 16px) var(--neo-safe-bottom);
  }

  .hero-metrics {
    flex-direction: row;
  }

  .metric-divider {
    display: block;
  }

  .share-actions {
    flex-direction: column;
  }
}

/* ==================== 减少动画 ==================== */
@media (prefers-reduced-motion: reduce) {
  .spinner,
  .spinning {
    animation: none;
  }

  .hero-copy-btn:active:not(:disabled),
  .hero-generate-btn:active:not(:disabled),
  .rule-card:active,
  .record-card:active,
  .empty-action:active:not(:disabled),
  .share-secondary:active {
    transform: none;
  }
}

/* ==================== 二维码弹窗 ==================== */
.qrcode-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4, 16px);
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(8px);
}

.qrcode-modal {
  width: 100%;
  max-width: 320px;
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-lg, 18px);
  padding: var(--space-5, 20px);
  position: relative;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
}

.qrcode-close-btn {
  position: absolute;
  top: var(--space-3, 12px);
  right: var(--space-3, 12px);
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-tertiary);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.qrcode-close-btn:active {
  background: var(--neo-bg-surface-hover);
  color: var(--neo-text-secondary);
}

.qrcode-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  margin-bottom: var(--space-4, 16px);
}

.qrcode-icon {
  color: var(--neo-primary);
}

.qrcode-header h3 {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
  margin: 0;
}

.qrcode-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4, 16px);
}

.qrcode-image-wrapper {
  width: 200px;
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--space-3, 12px);
}

.qrcode-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.qrcode-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2, 8px);
  color: var(--neo-text-tertiary);
  font-size: var(--neo-font-size-sm, 12px);
}

.qrcode-code {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1, 4px);
}

.qrcode-code-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

.qrcode-code-value {
  font-size: var(--neo-font-size-xl, 18px);
  font-weight: var(--neo-font-weight-semibold, 600);
  font-family: ui-monospace, monospace;
  color: var(--neo-primary);
  letter-spacing: 0.1em;
}

.qrcode-hint {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  text-align: center;
  margin: 0;
}

.qrcode-footer {
  display: flex;
  gap: var(--space-3, 12px);
  margin-top: var(--space-4, 16px);
}

.qrcode-action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default);
}

.qrcode-action-btn:active:not(:disabled) {
  background: var(--neo-bg-surface-hover);
  transform: scale(var(--neo-scale-press, 0.98));
}

.qrcode-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.qrcode-action-btn--primary {
  background: var(--neo-primary);
  border-color: var(--neo-primary);
  color: var(--neo-text-inverse);
}

.qrcode-action-btn--primary:active:not(:disabled) {
  background: var(--neo-primary-hover);
}

/* 二维码弹窗动画 */
.qrcode-modal-enter-active,
.qrcode-modal-leave-active {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.qrcode-modal-enter-from,
.qrcode-modal-leave-to {
  opacity: 0;
}

.qrcode-modal-enter-from .qrcode-modal,
.qrcode-modal-leave-to .qrcode-modal {
  transform: scale(0.8) translateY(20px);
}
</style>
