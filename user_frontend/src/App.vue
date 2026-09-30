<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed, onMounted } from 'vue'
import Toast from '@/components/Toast.vue'
import AppHeader from '@/components/AppHeader.vue'
import AppDock from '@/components/AppDock.vue'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'
import { refreshEmbyBaseUrl } from '@/api/emby'

const { messages, remove } = useToast()
const userStore = useUserStore()
const route = useRoute()

/**
 * 全局导航壳：同一份导航定义（src/config/navigation.ts），两种断点形态：
 *
 *   ≥769px  顶栏：品牌 + 主导航（≥900px 横排、769~900px 顶栏第二行滑动选项卡）
 *   ≤768px  顶栏退成单行（品牌 + 资产 pill + 账号），主导航交给底部坞（AppDock）——
 *           拇指区常驻 Tab 栏是移动端的肌肉记忆，条目与顶栏完全同源、不增不减。
 *
 * 页面底部留白用 --au-dock-space 跟着坞的高度走：≥769px 为 0，≤768px 给坞让位。
 */
const showChrome = computed(
  () => route.name !== 'login' && !route.path.startsWith('/watch'),
)

onMounted(() => {
  userStore.init()
  // P0#1：后台重新校验 EA 地址（8001→8002 这类变更 1 小时内自动纠正，不阻塞首屏）
  refreshEmbyBaseUrl()
  // 有登录 token 时后台刷新一次用户信息：购买订阅后 localStorage 里缓存的
  // is_vip 会过期，不刷新则媒体库详情页一直显示"没有生效中的订阅"
  //（2026-09-26 线上实测）。401 时拦截器会自动用 refresh token 续期。
  if (userStore.isLoggedIn) {
    userStore.fetchUser().catch(() => {})
  }
})
</script>

<template>
  <div class="app-shell">
    <AppHeader v-if="showChrome" />
    <RouterView />
    <AppDock v-if="showChrome" />
    <Toast :messages="messages" @remove="remove" />
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  min-height: 100dvh;   /* 移动端地址栏收放时高度不跳 */
  background: var(--au-bg);
}

/* 顶栏是 sticky 的，占文档流；登录页全屏居中、播放页全黑无栏，两者已由 showChrome 排除 */
</style>
