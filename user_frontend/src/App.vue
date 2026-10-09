<script setup lang="ts">
import { RouterView, useRoute, useRouter } from 'vue-router'
import { computed, onMounted, onUnmounted } from 'vue'
import Toast from '@/components/Toast.vue'
import AppHeader from '@/components/AppHeader.vue'
import AppDock from '@/components/AppDock.vue'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'
import { refreshEmbyBaseUrl } from '@/api/emby'

const { messages, remove, warning } = useToast()
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

/**
 * 三个主 Tab（首页 / 商店 / 钱包 / 我的）常驻缓存：切 tab 不再销毁重建，
 * 回来秒出上次的数据，各视图在 onActivated 里做静默刷新（不闪骨架屏）。
 *
 * 缓存 key = 路由 path + 用户 id + 登录会话序列：
 * - 同一 tab 内的实例复用，滚动位置、选项卡状态都保留；
 * - 登出 / 换号 / 重新登录后旧实例不再复用，不会看到上一个登录态的数据；
 * - 未列入 include 的页面（详情、播放、登录等）不受影响，照常每次重建。
 */
const KEEP_ALIVE_VIEWS = ['HomeView', 'StoreView', 'WalletView', 'ProfileView']
const viewCacheKey = computed(
  () => `${route.path}:${userStore.user?.id ?? 'guest'}#${userStore.sessionSeq}`,
)

const router = useRouter()

let lastTgNotify = 0
function onTgNotBound(e: Event) {
  // 节流：多接口同时 403 时只处理一次
  const now = Date.now()
  if (now - lastTgNotify < 3000) return
  lastTgNotify = now
  const message = (e as CustomEvent)?.detail?.message || '公益服功能需要绑定 Telegram，防小号，1 分钟搞定'
  warning(message + '，正在前往绑定…')
  setTimeout(() => router.push('/profile'), 600)
}

onMounted(() => {
  window.addEventListener('tg-not-bound', onTgNotBound)
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
onUnmounted(() => {
  window.removeEventListener('tg-not-bound', onTgNotBound)
})
</script>

<template>
  <div class="app-shell">
    <AppHeader v-if="showChrome" />
    <RouterView v-slot="{ Component }">
      <!-- max=12：key 按登录会话隔离，登出/换号后旧实例不再命中，攒多了自动淘汰最旧的 -->
      <KeepAlive :include="KEEP_ALIVE_VIEWS" :max="12">
        <component :is="Component" :key="viewCacheKey" />
      </KeepAlive>
    </RouterView>
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
