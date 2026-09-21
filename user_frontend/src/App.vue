<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed, onMounted } from 'vue'
import Toast from '@/components/Toast.vue'
import AppDock from '@/components/AppDock.vue'
import AppHeader from '@/components/AppHeader.vue'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'

const { messages, remove } = useToast()
const userStore = useUserStore()
const route = useRoute()

/**
 * 全局导航壳：顶栏（桌面主导航 + 移动端抽屉）与底部导航坞。
 *
 * AppHeader 此前处于「写好了但没挂载」的状态：它是唯一的邀请返利 / 消息 / 积分
 * 全局入口，却不被任何页面引用，实际渲染不出来——用户「在用户端找不到邀请」
 * 的直接原因就在这里。现在挂回 App 层，登录页与全屏播放页除外。
 */
const showChrome = computed(
  () => route.name !== 'login' && !route.path.startsWith('/watch'),
)

// 底部导航坞：已登录且非登录页 / 全屏播放页时显示
const showDock = computed(() => userStore.isLoggedIn && showChrome.value)

onMounted(() => {
  userStore.init()
})
</script>

<template>
  <div class="app-shell">
    <AppHeader v-if="showChrome" />
    <RouterView />
    <AppDock v-if="showDock" />
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
