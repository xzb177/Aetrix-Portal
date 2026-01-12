<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { Loader2 } from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

onMounted(async () => {
  try {
    // 从 URL hash 中获取 Telegram 回调参数
    const hash = route.hash || window.location.hash
    const queryString = hash.substring(1) // 移除 #

    if (queryString) {
      await userStore.telegramCallback(queryString)
      // 获取保存的重定向地址
      const redirect = sessionStorage.getItem('telegram_redirect')
      sessionStorage.removeItem('telegram_redirect')
      router.push(redirect || '/')
    } else {
      // 如果没有 hash，检查 query 参数
      const queryStr = new URLSearchParams(route.query as Record<string, string>).toString()
      if (queryStr) {
        await userStore.telegramCallback(queryStr)
        const redirect = sessionStorage.getItem('telegram_redirect')
        sessionStorage.removeItem('telegram_redirect')
        router.push(redirect || '/')
      } else {
        router.push('/login?error=no_callback_params')
      }
    }
  } catch (err) {
    console.error('Telegram callback failed:', err)
    router.push('/login?error=telegram_callback_failed')
  }
})
</script>

<template>
  <div class="min-h-screen pt-24 flex items-center justify-center bg-gray-50">
    <div class="text-center">
      <Loader2 class="w-12 h-12 animate-spin text-emerald-500 mx-auto mb-4" :size="48" />
      <p class="text-gray-600">正在处理 Telegram 登录...</p>
    </div>
  </div>
</template>
