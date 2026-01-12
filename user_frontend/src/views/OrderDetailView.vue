<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { paymentApi } from '@/api'
import { Loader2, CheckCircle, XCircle, Clock } from 'lucide-vue-next'

const route = useRoute()
const orderId = route.params.id as string

interface Order {
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'
  item_name: string
  amount: number
  payment_method: string
  created_at: string
  paid_at?: string
  payment_url?: string
}

const order = ref<Order | null>(null)
const loading = ref(true)
const polling = ref<number | null>(null)

onMounted(async () => {
  await fetchOrder()
  // 开始轮询订单状态
  polling.value = window.setInterval(async () => {
    await fetchOrder()
    // 如果订单已完成或失败，停止轮询
    if (order.value && ['completed', 'failed', 'cancelled'].includes(order.value.status)) {
      if (polling.value) {
        clearInterval(polling.value)
        polling.value = null
      }
    }
  }, 3000)
})

async function fetchOrder() {
  try {
    const res = await paymentApi.getStatus(orderId)
    order.value = res.data
  } catch (error) {
    console.error('Failed to fetch order:', error)
  } finally {
    loading.value = false
  }
}

// 组件卸载时清除轮询
onUnmounted(() => {
  if (polling.value) {
    clearInterval(polling.value)
  }
})

type StatusInfo = { label: string; icon: any; color: string }

const statusMap: Record<string, StatusInfo> = {
  pending: { label: '待支付', icon: Clock, color: 'text-amber-500 bg-amber-500/10' },
  processing: { label: '处理中', icon: Clock, color: 'text-blue-500 bg-blue-500/10' },
  completed: { label: '已完成', icon: CheckCircle, color: 'text-green-500 bg-green-500/10' },
  failed: { label: '失败', icon: XCircle, color: 'text-red-500 bg-red-500/10' },
  cancelled: { label: '已取消', icon: XCircle, color: 'text-gray-500 bg-gray-500/10' },
}

function getStatus(status: string = 'pending'): StatusInfo {
  return statusMap[status] ?? statusMap.pending!
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

function goToPayment(url: string) {
  window.location.href = url
}
</script>

<template>
  <div class="pt-20 pb-16 px-4">
    <div class="max-w-2xl mx-auto">
      <!-- Loading -->
      <div v-if="loading" class="flex justify-center py-12">
        <Loader2 class="animate-spin text-blue-500" :size="32" />
      </div>

      <!-- Order Detail -->
      <div v-else-if="order" class="card p-6">
        <div class="flex items-center justify-between mb-6">
          <h1 class="text-2xl font-bold text-gray-900 dark:text-white">
            订单详情
          </h1>
          <span
            :class="`px-3 py-1 rounded-full text-sm font-medium ${getStatus(order?.status || 'pending').color}`"
          >
            <component :is="getStatus(order?.status || 'pending').icon" :size="16" class="inline mr-1" />
            {{ getStatus(order?.status || 'pending').label }}
          </span>
        </div>

        <!-- Order Info -->
        <div class="space-y-4">
          <div class="flex justify-between py-3 border-b border-gray-200 dark:border-gray-800">
            <span class="text-gray-500 dark:text-gray-400">订单号</span>
            <span class="font-mono text-gray-900 dark:text-white">{{ orderId }}</span>
          </div>

          <div class="flex justify-between py-3 border-b border-gray-200 dark:border-gray-800">
            <span class="text-gray-500 dark:text-gray-400">商品</span>
            <span class="text-gray-900 dark:text-white">{{ order.item_name }}</span>
          </div>

          <div class="flex justify-between py-3 border-b border-gray-200 dark:border-gray-800">
            <span class="text-gray-500 dark:text-gray-400">金额</span>
            <span class="font-bold text-xl text-gray-900 dark:text-white">
              ¥{{ order.amount }}
            </span>
          </div>

          <div class="flex justify-between py-3 border-b border-gray-200 dark:border-gray-800">
            <span class="text-gray-500 dark:text-gray-400">支付方式</span>
            <span class="text-gray-900 dark:text-white">{{ order.payment_method }}</span>
          </div>

          <div class="flex justify-between py-3 border-b border-gray-200 dark:border-gray-800">
            <span class="text-gray-500 dark:text-gray-400">创建时间</span>
            <span class="text-gray-900 dark:text-white">{{ formatDate(order.created_at) }}</span>
          </div>

          <div v-if="order.paid_at" class="flex justify-between py-3">
            <span class="text-gray-500 dark:text-gray-400">支付时间</span>
            <span class="text-gray-900 dark:text-white">{{ formatDate(order.paid_at) }}</span>
          </div>
        </div>

        <!-- Pending Status Action -->
        <div v-if="order.status === 'pending'" class="mt-6 p-4 rounded-lg bg-blue-50 dark:bg-blue-900/20">
          <p class="text-sm text-blue-700 dark:text-blue-300 mb-3">
            等待支付中... 请完成支付后刷新页面
          </p>
          <button
            v-if="order.payment_url"
            @click="goToPayment(order.payment_url)"
            class="btn btn-primary text-sm"
          >
            继续支付
          </button>
        </div>

        <!-- Back Button -->
        <div class="mt-6">
          <button @click="$router.back()" class="btn btn-secondary">
            返回
          </button>
        </div>
      </div>

      <!-- Not Found -->
      <div v-else class="card p-12 text-center">
        <p class="text-gray-500">订单不存在</p>
      </div>
    </div>
  </div>
</template>
