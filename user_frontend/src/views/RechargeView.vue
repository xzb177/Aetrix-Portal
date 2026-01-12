<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { rechargeApi } from '@/api'
import { useToast } from '@/composables/useToast'
import { Coins, Loader2, History, Wallet, Plus, Minus, Shield, Clock, Headphones, Sparkles, Zap } from 'lucide-vue-next'

interface RechargeHistory {
  id: number
  amount: number
  status: 'pending' | 'completed' | 'failed'
  payment_method: string
  created_at: string
}

const router = useRouter()
const toast = useToast()

const history = ref<RechargeHistory[]>([])
const loading = ref(true)
const processing = ref(false)
const showHistory = ref(false)
const showConfirmModal = ref(false)

// 充值金额
const rechargeAmount = ref(100)
const quickAmounts = ref([
  { value: 10, label: '10', tag: '' },
  { value: 20, label: '20', tag: '' },
  { value: 50, label: '50', tag: '' },
  { value: 100, label: '100', tag: '热门' },
  { value: 200, label: '200', tag: '' },
  { value: 500, label: '500', tag: '超值' },
])

// 支付方式
const paymentMethods = [
  { id: 'alipay', name: '支付宝', icon: '💙', recommended: false },
  { id: 'wxpay', name: '微信支付', icon: '💚', recommended: true },
]
const selectedPaymentMethod = ref('wxpay')

// 计算可订阅套餐
const estimatedPlans = computed(() => {
  if (rechargeAmount.value >= 398) return '可订阅年卡套餐'
  if (rechargeAmount.value >= 98) return '可订阅季卡套餐'
  if (rechargeAmount.value >= 28) return '可订阅月卡套餐'
  return '余额可用于任意套餐'
})

onMounted(async () => {
  await fetchHistory()
})

async function fetchHistory() {
  loading.value = true
  try {
    const histRes = await rechargeApi.getHistory().catch(() => ({ data: [] as any[] }))
    history.value = histRes.data || []
  } catch (error) {
    console.error('Failed to fetch history:', error)
  } finally {
    loading.value = false
  }
}

function setAmount(amount: number) {
  rechargeAmount.value = amount
}

function adjustAmount(delta: number) {
  const newValue = rechargeAmount.value + delta
  if (newValue >= 1 && newValue <= 10000) {
    rechargeAmount.value = newValue
  }
}

function openConfirmModal() {
  if (rechargeAmount.value < 1) {
    toast.warning('充值金额不能小于 1 元')
    return
  }
  showConfirmModal.value = true
}

function closeConfirmModal() {
  showConfirmModal.value = false
}

async function handleRecharge() {
  processing.value = true
  try {
    const res = await rechargeApi.createOrder({
      amount: rechargeAmount.value,
      payment_method: selectedPaymentMethod.value,
    })

    if (res.data.payment_url) {
      closeConfirmModal()
      window.location.href = res.data.payment_url
    }
  } catch (error) {
    console.error('Recharge failed:', error)
    toast.error('创建订单失败，请稍后重试')
  } finally {
    processing.value = false
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const statusMap = {
  pending: { label: '待支付', color: '#f59e0b' },
  completed: { label: '已完成', color: '#10b981' },
  failed: { label: '失败', color: '#ef4444' },
}

// 生成订单号
const mockOrderNo = computed(() => {
  const now = new Date()
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '')
  const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, '')
  const random = Math.floor(Math.random() * 10000).toString().padStart(4, '0')
  return `${dateStr}${timeStr}${random}`
})
</script>

<template>
  <div class="recharge-page">
    <div class="recharge-container">
      <!-- Page Header -->
      <div class="page-header">
        <div class="header-content">
          <div class="header-icon">
            <Coins :size="24" />
          </div>
          <div>
            <h1 class="page-title">充值中心</h1>
            <p class="page-subtitle">充值余额，享受更多服务</p>
          </div>
        </div>
        <button
          @click="showHistory = !showHistory"
          class="btn btn-secondary"
        >
          <History :size="16" />
          <span>{{ showHistory ? '返回充值' : '充值记录' }}</span>
        </button>
      </div>

      <!-- Recharge History -->
      <div v-if="showHistory" class="card glass-card">
        <h2 class="card-title">
          <History :size="18" />
          充值记录
        </h2>
        <div v-if="history.length === 0" class="empty-state">
          <div class="empty-icon">
            <Wallet :size="24" />
          </div>
          <p>暂无充值记录</p>
        </div>
        <div v-else class="history-list">
          <div
            v-for="item in history"
            :key="item.id"
            class="history-item glass-card"
          >
            <div class="history-info">
              <p class="history-amount">充值 {{ item.amount }} 元</p>
              <p class="history-date">{{ formatDate(item.created_at) }}</p>
            </div>
            <div class="history-result">
              <p class="history-value">+{{ item.amount }}</p>
              <p class="history-status" :style="{ color: statusMap[item.status].color }">
                {{ statusMap[item.status].label }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- Recharge Form -->
      <div v-else class="recharge-content">
        <!-- 金额选择 -->
        <div class="card glass-card">
          <h2 class="card-title">
            <Coins :size="18" />
            充值金额
          </h2>

          <!-- 快捷金额 -->
          <div class="amount-grid">
            <button
              v-for="amount in quickAmounts"
              :key="amount.value"
              @click="setAmount(amount.value)"
              class="amount-btn"
              :class="{ 'active': rechargeAmount === amount.value }"
            >
              <span class="amount-value">¥{{ amount.label }}</span>
              <span v-if="amount.tag" class="amount-tag" :class="amount.tag === '超值' ? 'tag-super' : 'tag-hot'">
                <Sparkles v-if="amount.tag === '超值'" :size="10" />
                <Zap v-else :size="10" />
                {{ amount.tag }}
              </span>
            </button>
          </div>

          <!-- 自定义金额 -->
          <div class="amount-control">
            <button
              @click="adjustAmount(-10)"
              class="control-btn"
            >
              <Minus :size="18" />
            </button>
            <div class="amount-display">
              <span class="amount-symbol">¥</span>
              <input
                v-model.number="rechargeAmount"
                type="number"
                min="1"
                max="10000"
                class="amount-input"
              />
            </div>
            <button
              @click="adjustAmount(10)"
              class="control-btn"
            >
              <Plus :size="18" />
            </button>
          </div>
          <p class="amount-hint">
            充值金额: <span class="highlight">¥{{ rechargeAmount }}</span> = <span class="highlight">¥{{ rechargeAmount }}</span> 余额
          </p>
          <p class="amount-estimate">
            {{ estimatedPlans }}
          </p>
        </div>

        <!-- 支付方式 -->
        <div class="card glass-card">
          <h2 class="card-title">支付方式</h2>
          <div class="payment-methods">
            <button
              v-for="method in paymentMethods"
              :key="method.id"
              @click="selectedPaymentMethod = method.id"
              class="payment-btn glass-card"
              :class="{ 'active': selectedPaymentMethod === method.id }"
            >
              <span class="payment-icon">{{ method.icon }}</span>
              <span class="payment-name">{{ method.name }}</span>
              <span v-if="method.recommended" class="payment-recommend">推荐</span>
            </button>
          </div>
        </div>

        <!-- 信任标识（新增） -->
        <div class="trust-section">
          <div class="trust-item">
            <Shield :size="16" class="trust-icon" />
            <span>5 分钟内到账</span>
          </div>
          <div class="trust-item">
            <Clock :size="16" class="trust-icon" />
            <span>订单保留 30 分钟</span>
          </div>
          <div class="trust-item">
            <Headphones :size="16" class="trust-icon" />
            <span>客服 10 分钟响应</span>
          </div>
        </div>

        <!-- 确认按钮 -->
        <button
          @click="openConfirmModal"
          :disabled="processing || rechargeAmount < 1"
          class="btn btn-primary btn-large"
        >
          <Loader2 v-if="processing" class="spin" :size="18" />
          <span>{{ processing ? '处理中...' : `确认充值 ¥${rechargeAmount}` }}</span>
        </button>

        <!-- 说明 -->
        <div class="info-card glass-card">
          <div class="info-header">
            <Wallet :size="16" />
            <span>充值说明</span>
          </div>
          <ul class="info-list">
            <li>充值金额将 1:1 到账为余额</li>
            <li>充值成功后余额将立即到账</li>
            <li>余额可用于购买订阅套餐</li>
            <li>如有疑问请联系客服</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- 支付确认弹窗（新增） -->
    <Teleport to="body">
      <div
        v-if="showConfirmModal"
        class="modal-overlay"
        @click.self="closeConfirmModal"
      >
        <div class="confirm-modal glass-card">
          <div class="confirm-header">
            <h3>确认充值</h3>
            <p class="confirm-subtitle">请确认充值信息</p>
          </div>

          <div class="confirm-body">
            <div class="confirm-amount">
              <span class="confirm-symbol">¥</span>
              <span class="confirm-value">{{ rechargeAmount }}</span>
            </div>

            <div class="confirm-details">
              <div class="detail-row">
                <span class="detail-label">充值类型</span>
                <span class="detail-value">账户余额</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">支付方式</span>
                <span class="detail-value">
                  {{ paymentMethods.find(m => m.id === selectedPaymentMethod)?.name }}
                </span>
              </div>
              <div class="detail-row">
                <span class="detail-label">订单编号</span>
                <span class="detail-value">{{ mockOrderNo }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">预计到账</span>
                <span class="detail-value highlight">5 分钟内</span>
              </div>
            </div>

            <div class="confirm-notice">
              <Shield :size="14" />
              <span>支付成功后余额将自动到账，如有问题请联系客服</span>
            </div>
          </div>

          <div class="confirm-actions">
            <button @click="closeConfirmModal" class="btn btn-secondary">
              取消
            </button>
            <button
              @click="handleRecharge"
              :disabled="processing"
              class="btn btn-primary"
            >
              <Loader2 v-if="processing" class="spin" :size="16" />
              <span v-else>确认支付 ¥{{ rechargeAmount }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.recharge-page {
  min-height: 100vh;
  background: transparent;
  padding: 1.5rem 1rem;
}

.recharge-container {
  max-width: 600px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 页面头部 */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #10b981, #059669);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.page-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: #fafafa;
  margin: 0 0 0.25rem 0;
}

.page-subtitle {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
  margin: 0;
}

/* 卡片标题 */
.card-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: #fafafa;
  margin: 0 0 1rem 0;
}

/* 历史记录 */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
}

.history-amount {
  font-weight: 500;
  color: #fafafa;
  margin: 0 0 0.25rem 0;
}

.history-date {
  font-size: 0.8125rem;
  color: rgba(250, 250, 250, 0.5);
  margin: 0;
}

.history-result {
  text-align: right;
}

.history-value {
  font-weight: 700;
  font-size: 1.125rem;
  color: #10b981;
  margin: 0 0 0.25rem 0;
}

.history-status {
  font-size: 0.8125rem;
  margin: 0;
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 2rem;
}

.empty-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(250, 250, 250, 0.4);
  margin: 0 auto 1rem;
}

.empty-state p {
  color: rgba(250, 250, 250, 0.6);
  margin: 0;
}

/* 充值表单 */
.recharge-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 金额选择 */
.amount-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.amount-btn {
  position: relative;
  padding: 1rem;
  border-radius: var(--radius-md, 10px);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  background: rgba(255, 255, 255, 0.05);
  color: #fafafa;
  cursor: pointer;
  transition: all 0.2s ease;
}

.amount-btn:active {
  transform: scale(0.98);
}

.amount-btn.active {
  border-color: #10b981;
  background: var(--brand-primary-light, rgba(16, 185, 129, 0.15));
}

.amount-value {
  display: block;
  font-size: 1rem;
  font-weight: 600;
}

.amount-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin-top: 0.25rem;
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
  font-size: 0.6875rem;
  font-weight: 500;
}

.amount-tag.tag-hot {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}

.amount-tag.tag-super {
  background: var(--brand-primary-light, rgba(16, 185, 129, 0.2));
  color: #10b981;
}

/* 金额控制器 */
.amount-control {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.control-btn {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  color: #fafafa;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.control-btn:active {
  background: rgba(255, 255, 255, 0.15);
}

.amount-display {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.amount-symbol {
  position: absolute;
  left: 1rem;
  font-size: 1.5rem;
  font-weight: 700;
  color: rgba(250, 250, 250, 0.4);
}

.amount-input {
  width: 100%;
  padding: 1rem 1rem 1rem 2.5rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  border-radius: 10px;
  color: #fafafa;
  font-size: 2rem;
  font-weight: 700;
  text-align: center;
  outline: none;
}

.amount-input:focus {
  border-color: #10b981;
}

.amount-hint {
  text-align: center;
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
  margin: 0 0 0.25rem 0;
}

.amount-hint .highlight {
  color: #10b981;
  font-weight: 600;
}

.amount-estimate {
  text-align: center;
  font-size: 0.8125rem;
  color: var(--brand-500, #10b981);
  margin: 0;
}

/* 支付方式 */
.payment-methods {
  display: flex;
  gap: 0.75rem;
}

.payment-btn {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1rem;
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  background: rgba(255, 255, 255, 0.05);
  color: #fafafa;
  cursor: pointer;
  transition: all 0.2s ease;
}

.payment-btn:active {
  transform: scale(0.98);
}

.payment-btn.active {
  border-color: #10b981;
  background: var(--brand-primary-light, rgba(16, 185, 129, 0.15));
}

.payment-icon {
  font-size: 1.5rem;
}

.payment-name {
  font-size: 0.875rem;
  font-weight: 500;
}

.payment-recommend {
  position: absolute;
  top: 0.25rem;
  right: 0.25rem;
  padding: 0.125rem 0.375rem;
  background: #10b981;
  color: white;
  font-size: 0.625rem;
  border-radius: 4px;
}

/* 信任标识 */
.trust-section {
  display: flex;
  justify-content: center;
  gap: 1.5rem;
  padding: 0.75rem;
}

.trust-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: rgba(250, 250, 250, 0.6);
}

.trust-icon {
  color: var(--brand-500, #10b981);
}

/* 说明卡片 */
.info-card {
  padding: 1rem;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.info-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
  color: #10b981;
  margin-bottom: 0.75rem;
}

.info-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.info-list li {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.7);
  padding: 0.375rem 0;
}

/* 按钮 */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius-sm, 6px);
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
  text-decoration: none;
}

.btn-primary {
  background: #10b981;
  color: white;
}

.btn-primary:active:not(:disabled) {
  transform: scale(0.96);
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-large {
  padding: 1rem;
  font-size: 1rem;
  font-weight: 600;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  color: #fafafa;
}

.btn-secondary:active {
  background: rgba(255, 255, 255, 0.15);
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 确认弹窗 ==================== */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(4px);
}

.confirm-modal {
  width: 100%;
  max-width: 380px;
  overflow: hidden;
}

.confirm-header {
  text-align: center;
  padding: 1.5rem 1.5rem 1rem;
}

.confirm-header h3 {
  font-size: 1.25rem;
  font-weight: 600;
  color: #fafafa;
  margin: 0 0 0.25rem 0;
}

.confirm-subtitle {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
  margin: 0;
}

.confirm-body {
  padding: 0 1.5rem 1rem;
}

.confirm-amount {
  text-align: center;
  padding: 1.5rem 0;
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--divider-color, rgba(255, 255, 255, 0.08));
}

.confirm-symbol {
  font-size: 1rem;
  color: rgba(250, 250, 250, 0.6);
}

.confirm-value {
  font-size: 2.5rem;
  font-weight: 700;
  color: #fafafa;
}

.confirm-details {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.detail-label {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
}

.detail-value {
  font-size: 0.875rem;
  color: #fafafa;
}

.detail-value.highlight {
  color: #10b981;
  font-weight: 500;
}

.confirm-notice {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.75rem;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: var(--radius-sm, 6px);
  font-size: 0.8125rem;
  color: rgba(250, 250, 250, 0.7);
}

.confirm-notice svg {
  flex-shrink: 0;
  color: #10b981;
  margin-top: 0.125rem;
}

.confirm-actions {
  display: flex;
  gap: 0.75rem;
  padding: 0 1.5rem 1.5rem;
}

.confirm-actions .btn {
  flex: 1;
  padding: 0.875rem;
}
</style>
