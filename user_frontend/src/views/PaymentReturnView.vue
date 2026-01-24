<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Loader2 } from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()

const loading = ref(true)
const status = ref<'success' | 'fail' | 'unknown'>('unknown')

onMounted(async () => {
  // 从 URL 参数获取支付状态
  // 易支付返回参数包含: out_trade_no, trade_status, money 等
  const tradeStatus = route.query.trade_status || route.query.status
  const orderId = route.query.out_trade_no || route.query.order_id

  // 简单判断：TRADE_SUCCESS 或 SUCCESS 表示成功
  if (tradeStatus && (tradeStatus.toString().includes('SUCCESS') || tradeStatus.toString() === 'success')) {
    status.value = 'success'
  } else if (tradeStatus) {
    status.value = 'fail'
  } else {
    // 没有状态信息，通过轮询查询订单状态
    if (orderId) {
      await checkOrderStatus(String(orderId))
    } else {
      status.value = 'unknown'
    }
  }

  // 延迟跳转到结果页面
  setTimeout(() => {
    if (status.value === 'success') {
      // 获取金额并跳转到成功页面
      const amount = route.query.money || route.query.amount || 0
      router.replace({
        name: 'recharge-success',
        query: { amount: String(amount) }
      })
    } else if (status.value === 'fail') {
      router.replace({
        name: 'recharge-fail',
        query: { message: '支付未完成或已取消', code: 'PAYMENT_CANCELLED' }
      })
    } else {
      router.replace({ name: 'recharge' })
    }
  }, 1500)

  loading.value = false
})

async function checkOrderStatus(orderId: string) {
  try {
    // 这里可以调用后端 API 查询订单状态
    // 暂时跳过，因为返回页面通常很短时间就会跳转
    console.log('查询订单状态:', orderId)
  } catch (error) {
    console.error('查询订单状态失败:', error)
  }
}
</script>

<template>
  <div class="return-page">
    <div class="return-content">
      <!-- 加载中 -->
      <div v-if="loading" class="status-wrapper">
        <Loader2 class="spinner" :size="48" />
        <p class="status-text">正在确认支付状态...</p>
      </div>

      <!-- 支付成功 -->
      <div v-else-if="status === 'success'" class="status-wrapper">
        <div class="success-icon">✓</div>
        <p class="status-text">支付成功！</p>
        <p class="status-desc">即将跳转...</p>
      </div>

      <!-- 支付失败 -->
      <div v-else-if="status === 'fail'" class="status-wrapper">
        <div class="fail-icon">✕</div>
        <p class="status-text">支付未完成</p>
        <p class="status-desc">即将跳转...</p>
      </div>

      <!-- 未知状态 -->
      <div v-else class="status-wrapper">
        <Loader2 class="spinner" :size="48" />
        <p class="status-text">确认中...</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.return-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--neo-bg-canvas, #030303);
}

.return-content {
  text-align: center;
}

.status-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4, 16px);
}

.spinner {
  color: var(--neo-primary, #10b981);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.success-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--neo-success-bg, rgba(16, 185, 129, 0.15));
  border: 2px solid var(--neo-success, #10b981);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-success, #10b981);
  font-size: 32px;
  font-weight: bold;
}

.fail-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--neo-danger-bg, rgba(239, 68, 68, 0.15));
  border: 2px solid var(--neo-danger, #ef4444);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-danger, #ef4444);
  font-size: 32px;
  font-weight: bold;
}

.status-text {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary);
  margin: 0;
}

.status-desc {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0;
}
</style>
