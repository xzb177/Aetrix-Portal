<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import Toast from '@/components/Toast.vue'
import DebugOverlay from '@/components/DebugOverlay.vue'

const router = useRouter()

// 检查是否启用调试模式
const isDebugEnabled = computed(() => {
  const params = new URLSearchParams(window.location.search)
  return params.has('debug') && params.get('debug') !== '0'
})

// 组件挂载时记录日志
onMounted(() => {
  console.log('[App] App.vue mounted')
  if (isDebugEnabled.value && (window as any).__addDebugLog) {
    ;(window as any).__addDebugLog('App.vue mounted ✓')
  }

  // 记录路由器配置
  console.log('[App] Router base:', (router.options.history as any).base)
  if (isDebugEnabled.value && (window as any).__addDebugLog) {
    ;(window as any).__addDebugLog(`Router base: ${(router.options.history as any).base}`)
  }
})
</script>

<template>
  <RouterView />
  <Toast />
  <DebugOverlay v-if="isDebugEnabled" />
</template>

<style>
html, body {
  margin: 0;
  padding: 0;
  height: 100%;
}

#app {
  height: 100%;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
</style>
