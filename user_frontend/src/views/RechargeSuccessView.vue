<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Check, ChevronRight, Crown, Film, Home, ArrowLeft } from 'lucide-vue-next'
import { authApi } from '@/api'

const router = useRouter()
const route = useRoute()

const amount = ref(0)
const balanceAfter = ref(0)
const loading = ref(true)

// 推荐操作
const actions = [
  {
    title: '订阅会员',
    desc: '解锁 4K 超清画质',
    icon: Crown,
    to: '/subscription',
    color: '#10b981'
  },
  {
    title: '求片中心',
    desc: '点播你想看的影片',
    icon: Film,
    to: '/request',
    color: '#f59e0b'
  },
  {
    title: '返回首页',
    desc: '浏览更多内容',
    icon: Home,
    to: '/',
    color: '#6366f1'
  }
]

onMounted(async () => {
  // 从 URL 参数获取金额
  const urlAmount = route.query.amount
  if (urlAmount) {
    amount.value = Number(urlAmount)
  }

  // 获取用户余额
  try {
    const res = await authApi.getCurrentUser()
    const data = res.data || res
    balanceAfter.value = (data.balance || 0) / 100
  } catch (error) {
    console.error('获取用户信息失败:', error)
  } finally {
    loading.value = false
  }
})

function goBack() {
  router.push('/profile')
}
</script>

<template>
  <div class="success-page">
    <!-- 头部返回 -->
    <header class="success-header">
      <button @click="goBack" class="back-btn">
        <ArrowLeft :size="20" />
        返回
      </button>
    </header>

    <!-- 主内容 -->
    <div class="success-content">
      <!-- 成功图标 -->
      <div class="success-icon-wrapper">
        <div class="success-icon">
          <Check :size="48" />
        </div>
      </div>

      <!-- 标题 -->
      <h1 class="success-title">充值成功</h1>
      <p class="success-desc">充值已到账，祝您使用愉快</p>

      <!-- 金额卡片 -->
      <div class="amount-card">
        <div class="amount-row">
          <span class="amount-label">充值金额</span>
          <span class="amount-value">+¥{{ amount }}</span>
        </div>
        <div class="amount-divider"></div>
        <div class="amount-row">
          <span class="amount-label">当前余额</span>
          <span class="amount-value balance">¥{{ balanceAfter.toFixed(2) }}</span>
        </div>
      </div>

      <!-- 推荐操作 -->
      <div class="actions-section">
        <h2 class="actions-title">接下来可以</h2>
        <div class="actions-list">
          <RouterLink
            v-for="action in actions"
            :key="action.to"
            :to="action.to"
            class="action-card"
            :style="{ '--action-color': action.color }"
          >
            <div class="action-icon" :style="{ background: `${action.color}20`, color: action.color }">
              <component :is="action.icon" :size="24" />
            </div>
            <div class="action-info">
              <span class="action-title">{{ action.title }}</span>
              <span class="action-desc">{{ action.desc }}</span>
            </div>
            <ChevronRight :size="18" class="action-arrow" />
          </RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.success-page {
  min-height: 100vh;
  background: var(--neo-bg-canvas, #030303);
  padding: var(--space-5, 20px);
}

.success-header {
  padding: var(--space-4, 16px) 0;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm, 12px);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms);
}

.back-btn:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(0.98);
}

.success-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: var(--space-8, 32px);
}

/* 成功图标 */
.success-icon-wrapper {
  margin-bottom: var(--space-5, 20px);
}

.success-icon {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: var(--neo-success-bg, rgba(16, 185, 129, 0.15));
  border: 2px solid var(--neo-success, #10b981);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-success, #10b981);
  animation: successPop 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55);
}

@keyframes successPop {
  0% {
    transform: scale(0) rotate(-180deg);
    opacity: 0;
  }
  50% {
    transform: scale(1.2) rotate(10deg);
  }
  100% {
    transform: scale(1) rotate(0deg);
    opacity: 1;
  }
}

.success-title {
  font-size: var(--neo-font-size-2xl, 20px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
  margin: 0 0 var(--space-2, 8px) 0;
}

.success-desc {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0 0 var(--space-6, 24px) 0;
}

/* 金额卡片 */
.amount-card {
  width: 100%;
  max-width: 320px;
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-lg, 18px);
  padding: var(--space-4, 16px);
  margin-bottom: var(--space-6, 24px);
}

.amount-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2, 8px) 0;
}

.amount-label {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-secondary);
}

.amount-value {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
}

.amount-value.balance {
  color: var(--neo-primary, #10b981);
  font-size: var(--neo-font-size-xl, 18px);
}

.amount-divider {
  height: 1px;
  background: var(--neo-border-subtle);
  margin: var(--space-2, 8px) 0;
}

/* 推荐操作 */
.actions-section {
  width: 100%;
  max-width: 400px;
}

.actions-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-secondary);
  margin: 0 0 var(--space-4, 16px) 0;
}

.actions-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
}

.action-card {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
  padding: var(--space-4, 16px);
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-default);
  border-radius: var(--neo-radius-md, 14px);
  text-decoration: none;
  transition: all var(--neo-duration-fast, 150ms);
}

.action-card:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(0.98);
  border-color: var(--action-color, var(--neo-primary));
}

.action-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--neo-radius-sm, 12px);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.action-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.action-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary);
}

.action-desc {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
}

.action-arrow {
  color: var(--neo-text-tertiary);
  flex-shrink: 0;
}
</style>
