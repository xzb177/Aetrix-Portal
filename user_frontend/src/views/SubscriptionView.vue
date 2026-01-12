<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { paymentApi, subscriptionApi, authApi } from '@/api'
import {
  Crown,
  Check,
  ChevronRight,
  ChevronDown,
  Loader2,
  Wallet,
  Tv,
  Zap,
  Shield,
  Gift,
  Users,
  Sparkles,
  HelpCircle,
  X,
} from 'lucide-vue-next'

const router = useRouter()
const userStore = useUserStore()
const toast = useToast()

// 状态
const pageLoaded = ref(false)
const hoveredPlan = ref<number | null>(null)
const showPaymentModal = ref(false)
const selectedPlanId = ref<number | null>(null)
const selectedPlan = ref<any>(null)
const paymentMethods = ref<any[]>([])
const selectedPaymentMethod = ref('balance')
const loadingPayment = ref(false)
const paymentError = ref('')
const userBalance = ref(0)
const plans = ref<any[]>([])
const mySubscription = ref<any>(null)
const purchasing = ref<number | null>(null)
const expandedFaq = ref<number | null>(null)

// V3: 套餐展开状态（推荐套餐默认展开，其他默认折叠）
const expandedPlans = ref<Set<number>>(new Set())

// V3: 初始化套餐展开状态
function initPlanExpansion() {
  plans.value.forEach((plan: any) => {
    if (plan.is_popular) {
      expandedPlans.value.add(plan.id)
    }
  })
}

// V3: 切换套餐展开状态
function togglePlanExpansion(planId: number) {
  if (expandedPlans.value.has(planId)) {
    expandedPlans.value.delete(planId)
  } else {
    expandedPlans.value.add(planId)
  }
}

// V3: 检查套餐是否展开
function isPlanExpanded(plan: any) {
  return plan.is_popular || expandedPlans.value.has(plan.id)
}

const isLoggedIn = computed(() => userStore.isLoggedIn)

// VIP 权益
const vipBenefits = [
  { icon: Tv, title: '4K 超清', desc: '蓝光 HDR 画质' },
  { icon: Zap, title: '极速播放', desc: '流畅不卡顿' },
  { icon: Shield, title: '多设备', desc: '4 台设备同时看' },
  { icon: Gift, title: '专属资源', desc: '优先获取新片' },
]

// FAQ 列表
const faqList = [
  {
    id: 1,
    question: '支持退款吗？',
    answer: '虚拟物品不支持退款，请根据需求选择合适的套餐。'
  },
  {
    id: 2,
    question: '可以更换设备吗？',
    answer: '支持，可在最多 4 台设备上同时登录使用。'
  },
  {
    id: 3,
    question: '到期后会自动续费吗？',
    answer: '不会，所有套餐均为单次购买，到期后需要手动续费。'
  },
  {
    id: 4,
    question: '支持哪些支付方式？',
    answer: '支持余额支付、微信支付、支付宝支付。'
  },
]

onMounted(() => {
  setTimeout(() => pageLoaded.value = true, 100)
  fetchPlans()
  fetchPaymentMethods()
  fetchUserBalance()
})

// 获取套餐列表
async function fetchPlans() {
  try {
    const response = await subscriptionApi.getPlans()
    // 响应可能是数组或 { data: [] } 格式
    const data = Array.isArray(response) ? response : (response.data || [])
    plans.value = data
    // V3: 初始化套餐展开状态
    initPlanExpansion()
  } catch (error) {
    console.error('获取套餐列表失败:', error)
  }
}

// 获取支付方式
async function fetchPaymentMethods() {
  try {
    const response = await paymentApi.getMethods()
    const data = response.data || response
    paymentMethods.value = data.methods?.filter((m: any) => m.enabled) || []
  } catch (error) {
    console.error('获取支付方式失败:', error)
  }
}

// 获取用户余额（balance 字段单位是分，需要转为元）
async function fetchUserBalance() {
  try {
    const response = await authApi.getCurrentUser()
    const data = response.data || response
    // balance 单位是分，points 是旧的（已废弃）
    userBalance.value = (data.balance || 0) / 100
  } catch (error) {
    console.error('获取用户余额失败:', error)
  }
}

// 计算月均单价（仅用于超过1个月的套餐）
function monthlyPrice(price: number, days: number) {
  // 计算这个套餐折算成月均价格
  const months = Math.round(days / 30)
  const avgMonthly = Math.round(price / months)
  return `月均约 ¥${avgMonthly}`
}

// 计算节省百分比
function savingsPercentage(price: number, days: number) {
  const monthPrice = plans.value.find(p => p.duration_days <= 31)?.price || price
  const yearlyEquivalent = monthPrice * 12
  if (days >= 365) {
    return Math.round((1 - price / yearlyEquivalent) * 100)
  }
  return 0
}

// 打开支付选择弹窗
function openPaymentModal(planId: number) {
  if (!isLoggedIn.value) {
    router.push('/login?redirect=' + encodeURIComponent('/subscription'))
    return
  }
  selectedPlanId.value = planId
  selectedPlan.value = plans.value.find(p => p.id === planId)
  showPaymentModal.value = true
  paymentError.value = ''
}

// 关闭支付弹窗
function closePaymentModal() {
  showPaymentModal.value = false
  selectedPlanId.value = null
  selectedPlan.value = null
  paymentError.value = ''
}

// 确认支付
async function confirmPayment() {
  if (!selectedPlanId.value || !selectedPlan.value) return

  // 余额支付
  if (selectedPaymentMethod.value === 'balance') {
    if (userBalance.value < selectedPlan.value.price) {
      paymentError.value = `余额 ¥${userBalance.value}，还需 ¥${(selectedPlan.value.price - userBalance.value).toFixed(2)}，请先充值`
      return
    }

    loadingPayment.value = true
    paymentError.value = ''
    try {
      const { data } = await paymentApi.balancePay({
        plan_id: selectedPlanId.value
      })
      closePaymentModal()
      toast.success(`订阅成功！有效期至 ${new Date(data.end_date).toLocaleDateString('zh-CN')}`)
      window.location.reload()
    } catch (error: any) {
      console.error('余额支付失败:', error)
      paymentError.value = error.response?.data?.detail || '余额支付失败，请稍后重试'
    } finally {
      loadingPayment.value = false
    }
    return
  }

  // 第三方支付
  loadingPayment.value = true
  paymentError.value = ''
  try {
    const { data } = await paymentApi.createPayment({
      plan_id: selectedPlanId.value,
      payment_method: selectedPaymentMethod.value
    })
    window.location.href = data.payment_url
  } catch (error: any) {
    console.error('创建支付订单失败:', error)
    paymentError.value = error.response?.data?.detail || '创建支付订单失败，请稍后重试'
  } finally {
    loadingPayment.value = false
  }
}

// 切换 FAQ 展开
function toggleFaq(id: number) {
  expandedFaq.value = expandedFaq.value === id ? null : id
}

// 获取支付方式图标
function getPaymentIcon(methodId: string) {
  return Wallet
}

async function handlePurchase(planId: number) {
  if (!isLoggedIn.value) {
    router.push('/login?redirect=' + encodeURIComponent('/subscription'))
    return
  }
  openPaymentModal(planId)
}
</script>

<template>
  <div class="subscription-page">
    <!-- Hero 区 -->
    <section class="hero">
      <div class="hero-content">
        <Crown :size="32" class="hero-icon" />
        <h1 class="hero-title">订阅会员</h1>
        <p class="hero-subtitle">单次购买，不会自动续费，虚拟物品不支持退款</p>
      </div>
    </section>

    <!-- 会员权益 -->
    <section class="benefits">
      <div class="benefits-grid">
        <div v-for="benefit in vipBenefits" :key="benefit.title" class="benefit-item glass-card">
          <component :is="benefit.icon" :size="24" class="benefit-icon" />
          <div>
            <div class="benefit-title">{{ benefit.title }}</div>
            <div class="benefit-desc">{{ benefit.desc }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 套餐列表 -->
    <section class="plans">
      <div class="section-header">
        <h2 class="section-title">选择订阅计划</h2>
        <p class="section-subtitle">单次购买，到期自动停止，随时可续费</p>
      </div>

      <div class="plans-grid" v-if="plans.length > 0">
        <div
          v-for="(plan, index) in plans"
          :key="plan.id"
          @mouseenter="hoveredPlan = plan.id"
          @mouseleave="hoveredPlan = null"
          class="plan-card-outer glass-card"
          :class="{ 'featured': plan.is_popular, 'expanded': isPlanExpanded(plan) }"
        >
          <!-- 推荐标签（V3 增强） -->
          <div v-if="plan.is_popular" class="featured-bar">
            <Sparkles :size="14" />
            超值推荐
            <span v-if="savingsPercentage(plan.price, plan.duration_days) > 0" class="savings">
              省 {{ savingsPercentage(plan.price, plan.duration_days) }}%
            </span>
          </div>

          <div class="plan-content">
            <h3 class="plan-name">{{ plan.name }}</h3>
            <p class="plan-desc">{{ plan.description }}</p>
            <div class="plan-price">
              <span class="price-amount">¥{{ plan.price }}</span>
              <span class="price-unit">/{{ plan.duration_days >= 365 ? '年' : plan.duration_days >= 90 ? '季' : '月' }}</span>
            </div>
            <!-- 月单价 -->
            <div v-if="plan.duration_days > 31" class="plan-unit">
              {{ monthlyPrice(plan.price, plan.duration_days) }}
            </div>

            <!-- V3: 展开/折叠按钮（非推荐套餐） -->
            <button
              v-if="!plan.is_popular"
              @click="togglePlanExpansion(plan.id)"
              class="expand-toggle-btn"
            >
              {{ isPlanExpanded(plan) ? '收起' : '查看权益' }}
              <ChevronDown :size="14" :class="{ 'rotate-180': isPlanExpanded(plan) }" />
            </button>

            <!-- V3: 权益标签（展开时显示，推荐套餐默认展开） -->
            <div v-show="isPlanExpanded(plan)" class="plan-benefits">
              <div class="benefit-tag">
                <Check :size="14" />
                <span>4K HDR 画质</span>
              </div>
              <div class="benefit-tag">
                <Check :size="14" />
                <span>4 台设备</span>
              </div>
              <div class="benefit-tag">
                <Check :size="14" />
                <span>硬件转码</span>
              </div>
              <div class="benefit-tag">
                <Check :size="14" />
                <span>全片库无限制</span>
              </div>
            </div>

            <!-- 原有特性列表 -->
            <ul v-show="isPlanExpanded(plan)" class="plan-features" v-if="plan.features && plan.features.length > 0">
              <li v-for="feature in plan.features" :key="feature">
                <Check :size="14" />
                {{ feature }}
              </li>
            </ul>

            <button
              @click="handlePurchase(plan.id)"
              :disabled="purchasing === plan.id"
              class="btn"
              :class="plan.is_popular ? 'btn-primary' : 'btn-secondary'"
            >
              <Loader2 v-if="purchasing === plan.id" class="spin" :size="16" />
              <span v-else>选择此套餐</span>
            </button>

            <!-- V3: 信任文案（推荐套餐） -->
            <div v-if="plan.is_popular" class="plan-trust-badges">
              <div class="trust-badge-item">
                <Shield :size="12" />
                <span>不自动续费</span>
              </div>
              <div class="trust-badge-item">
                <Check :size="12" />
                <span>订单可查</span>
              </div>
              <div class="trust-badge-item">
                <Zap :size="12" />
                <span>支付成功即生效</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Loading -->
      <div v-else class="loading-state">
        <div class="spinner spinner-lg"></div>
        <p>加载中...</p>
      </div>
    </section>

    <!-- FAQ（新增） -->
    <section class="faq-section">
      <div class="section-header">
        <h2 class="section-title">常见问题</h2>
      </div>
      <div class="faq-list">
        <div
          v-for="faq in faqList"
          :key="faq.id"
          class="faq-item glass-card"
          @click="toggleFaq(faq.id)"
        >
          <div class="faq-header">
            <div class="faq-question">
              <HelpCircle :size="16" />
              <span>{{ faq.question }}</span>
            </div>
            <ChevronDown
              :size="18"
              class="faq-chevron"
              :class="{ 'expanded': expandedFaq === faq.id }"
            />
          </div>
          <div v-show="expandedFaq === faq.id" class="faq-answer">
            {{ faq.answer }}
          </div>
        </div>
      </div>
    </section>

    <!-- 支付弹窗 -->
    <Teleport to="body">
      <div
        v-if="showPaymentModal"
        class="modal-overlay"
        @click.self="closePaymentModal"
      >
        <div class="modal glass-card">
          <!-- 标题 -->
          <div class="modal-header">
            <div>
              <h3 class="modal-title">选择支付方式</h3>
              <p class="modal-subtitle">{{ selectedPlan?.name }} - ¥{{ selectedPlan?.price }}</p>
            </div>
            <button @click="closePaymentModal" class="btn-close">
              <X :size="20" />
            </button>
          </div>

          <!-- 支付方式列表 -->
          <div class="modal-body">
            <div class="payment-list">
              <!-- 余额支付 -->
              <button
                @click="selectedPaymentMethod = 'balance'"
                class="payment-option glass-card"
                :class="{ 'active': selectedPaymentMethod === 'balance' }"
              >
                <div class="payment-icon">
                  <Wallet :size="24" />
                </div>
                <div class="payment-info">
                  <div class="payment-name">余额支付</div>
                  <div class="payment-desc">当前余额 ¥{{ userBalance.toFixed(2) }}</div>
                </div>
                <div v-if="selectedPaymentMethod === 'balance'" class="payment-check">
                  <Check :size="16" />
                </div>
              </button>

              <!-- 第三方支付 -->
              <button
                v-for="method in paymentMethods"
                :key="method.id"
                @click="selectedPaymentMethod = method.id"
                class="payment-option glass-card"
                :class="{ 'active': selectedPaymentMethod === method.id }"
              >
                <div class="payment-icon">
                  <component :is="getPaymentIcon(method.id)" :size="24" />
                </div>
                <div class="payment-info">
                  <div class="payment-name">{{ method.name }}</div>
                  <div class="payment-desc">{{ method.id === 'alipay' ? '支付宝扫码支付' : '微信扫码支付' }}</div>
                </div>
                <div v-if="selectedPaymentMethod === method.id" class="payment-check">
                  <Check :size="16" />
                </div>
              </button>
            </div>

            <!-- 错误提示 -->
            <div v-if="paymentError" class="error-message glass-card">
              {{ paymentError }}
            </div>

            <!-- 信任标识（新增） -->
            <div class="trust-badges">
              <div class="trust-badge">
                <Shield :size="14" />
                <span>虚拟物品不支持退款</span>
              </div>
              <div class="trust-badge">
                <Zap :size="14" />
                <span>5 分钟内到账</span>
              </div>
            </div>
          </div>

          <!-- 确认按钮 -->
          <div class="modal-footer">
            <button
              @click="confirmPayment"
              :disabled="loadingPayment"
              class="btn btn-primary btn-block"
            >
              <Loader2 v-if="loadingPayment" class="spin" :size="18" />
              <span v-else>确认支付 ¥{{ selectedPlan?.price }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* ==================== 基础样式 ==================== */
.subscription-page {
  min-height: 100vh;
  background: transparent;
  padding-bottom: 2rem;
}

/* ==================== Hero ==================== */
.hero {
  text-align: center;
  padding: 3rem 1.5rem 2rem;
}

.hero-icon {
  color: var(--brand-500, #10b981);
  margin-bottom: 1rem;
}

.hero-title {
  font-size: 2rem;
  font-weight: 700;
  color: #fafafa;
  margin-bottom: 0.5rem;
}

.hero-subtitle {
  font-size: 1rem;
  color: rgba(250, 250, 250, 0.6);
}

/* ==================== 权益 ==================== */
.benefits {
  padding: 2rem 1.5rem;
  max-width: 800px;
  margin: 0 auto;
}

.benefits-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.benefit-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
}

.benefit-icon {
  color: var(--brand-500, #10b981);
  flex-shrink: 0;
}

.benefit-title {
  font-weight: 600;
  color: #fafafa;
  font-size: 0.9375rem;
}

.benefit-desc {
  font-size: 0.8125rem;
  color: rgba(250, 250, 250, 0.6);
}

/* ==================== 套餐 ==================== */
.plans {
  padding: 2rem 1.5rem;
}

.section-header {
  text-align: center;
  margin-bottom: 2rem;
}

.section-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: #fafafa;
  margin-bottom: 0.5rem;
}

.section-subtitle {
  font-size: 0.9375rem;
  color: rgba(250, 250, 250, 0.6);
}

.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1rem;
  max-width: 900px;
  margin: 0 auto;
}

.plan-card-outer {
  position: relative;
  transition: all 0.2s ease;
}

.plan-card-outer:hover {
  border-color: var(--brand-500, #10b981);
}

.plan-card-outer.featured {
  border-color: var(--brand-500, #10b981);
}

/* 新版推荐标签 */
.featured-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.5rem;
  background: var(--brand-500, #10b981);
  color: white;
  font-size: 0.8125rem;
  font-weight: 500;
}

.featured-bar .savings {
  padding: 0.125rem 0.375rem;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}

.plan-content {
  padding: 1.5rem;
}

.plan-name {
  font-size: 1.125rem;
  font-weight: 600;
  color: #fafafa;
  margin-bottom: 0.25rem;
}

.plan-desc {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
  margin-bottom: 1rem;
}

.plan-price {
  margin-bottom: 0.25rem;
}

.price-amount {
  font-size: 1.75rem;
  font-weight: 700;
  color: #fafafa;
}

.price-unit {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
}

.plan-unit {
  font-size: 0.8125rem;
  color: var(--brand-500, #10b981);
  margin-bottom: 1rem;
}

/* 新增：权益标签 */
.plan-benefits {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.benefit-tag {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
  color: rgba(250, 250, 250, 0.7);
}

.benefit-tag svg {
  color: var(--brand-500, #10b981);
  flex-shrink: 0;
}

.plan-features {
  list-style: none;
  padding: 0;
  margin: 0 0 1.5rem 0;
}

.plan-features li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0;
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.8);
}

.plan-features li svg {
  color: var(--brand-500, #10b981);
  flex-shrink: 0;
}

/* ==================== V3: 展开/折叠按钮 ==================== */
.expand-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.5rem;
  margin-bottom: 0.75rem;
  background: transparent;
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: 0.5rem;
  color: #737373;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.expand-toggle-btn:hover {
  background: rgba(255, 255, 255, 0.03);
  color: #a3a3a3;
  border-color: rgba(255, 255, 255, 0.25);
}

.expand-toggle-btn svg {
  transition: transform 0.2s ease;
}

.expand-toggle-btn .rotate-180 {
  transform: rotate(180deg);
}

/* ==================== V3: 信任徽章 ==================== */
.plan-trust-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.trust-badge-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.688rem;
  color: #737373;
}

.trust-badge-item svg {
  color: #10b981;
}

/* ==================== 按钮 ==================== */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  border-radius: var(--radius-sm, 6px);
  font-size: 0.9375rem;
  font-weight: 600;
  text-decoration: none;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  width: 100%;
}

.btn-primary {
  background: var(--brand-500, #10b981);
  color: white;
}

.btn-primary:hover {
  background: var(--brand-600, #059669);
}

.btn-primary:active {
  transform: scale(0.96);
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fafafa;
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.15);
}

.btn-secondary:active {
  transform: scale(0.96);
}

.btn-block {
  width: 100%;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 弹窗 ==================== */
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

.modal {
  width: 100%;
  max-width: 400px;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 1.25rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #fafafa;
}

.modal-subtitle {
  font-size: 0.875rem;
  color: rgba(250, 250, 250, 0.6);
  margin-top: 0.25rem;
}

.btn-close {
  padding: 0.25rem;
  background: transparent;
  border: none;
  color: rgba(250, 250, 250, 0.5);
  cursor: pointer;
  transition: color 0.2s ease;
}

.btn-close:active {
  color: rgba(250, 250, 250, 0.8);
}

.modal-body {
  padding: 1.25rem;
}

.payment-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.payment-option {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
  width: 100%;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.payment-option:active {
  transform: scale(0.98);
}

.payment-option.active {
  border-color: var(--brand-500, #10b981);
  background: var(--brand-primary-light, rgba(16, 185, 129, 0.15));
}

.payment-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.1);
  color: var(--brand-500, #10b981);
}

.payment-info {
  flex: 1;
}

.payment-name {
  font-weight: 500;
  color: #fafafa;
  font-size: 0.9375rem;
}

.payment-desc {
  font-size: 0.8125rem;
  color: rgba(250, 250, 250, 0.6);
}

.payment-check {
  color: var(--brand-500, #10b981);
}

.error-message {
  margin-top: 0.75rem;
  padding: 0.75rem;
  color: var(--color-danger, #ef4444);
  font-size: 0.875rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
}

/* 信任标识 */
.trust-badges {
  display: flex;
  gap: 1rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.trust-badge {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: rgba(250, 250, 250, 0.6);
}

.modal-footer {
  padding: 1rem 1.25rem 1.25rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

/* ==================== FAQ ==================== */
.faq-section {
  padding: 2rem 1.5rem;
  max-width: 600px;
  margin: 0 auto;
}

.faq-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.faq-item {
  padding: 1rem;
  cursor: pointer;
  transition: background 0.2s ease;
}

.faq-item:active {
  background: var(--bg-elevated-hover, #1a1a1a);
}

.faq-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.faq-question {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
  color: var(--text-primary, #fafafa);
  font-size: 0.9375rem);
}

.faq-question svg {
  color: var(--brand-500, #10b981);
}

.faq-chevron {
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
  transition: transform 0.2s ease;
}

.faq-chevron.expanded {
  transform: rotate(180deg);
}

.faq-answer {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  color: var(--text-secondary, rgba(250, 250, 250, 0.7));
  font-size: 0.875rem;
  line-height: 1.6;
}

/* ==================== Loading ==================== */
.loading-state {
  text-align: center;
  padding: 3rem;
  color: rgba(250, 250, 250, 0.6);
}

/* ==================== 响应式 ==================== */
@media (max-width: 640px) {
  .benefits-grid {
    grid-template-columns: 1fr;
  }

  .hero-title {
    font-size: 1.5rem;
  }

  .trust-badges {
    flex-direction: column;
    gap: 0.5rem;
  }
}
</style>
