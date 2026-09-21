<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed, onMounted, onBeforeUnmount, watch } from 'vue'
import Toast from '@/components/Toast.vue'
import AppDock from '@/components/AppDock.vue'
import AppHeader from '@/components/AppHeader.vue'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'

const { messages, remove } = useToast()
const userStore = useUserStore()
const route = useRoute()

/**
 * 全局导航壳：一个导航、两种形态（定义见 src/config/navigation.ts）。
 *
 *   ≥900px  顶栏把主导航横向铺开（品牌 + 导航 + 搜索 / 积分 / 消息 / 账号）
 *   ≤900px  顶栏只留品牌与账号操作，主导航落到拇指够得着的底部导航坞
 *
 * 两边用的是同一份 primaryNav：同名、同序、同图标，用户不会觉得「有两个导航」。
 * 登录页与全屏播放页没有导航壳。
 */
const showChrome = computed(
  () => route.name !== 'login' && !route.path.startsWith('/watch'),
)

// 底部导航坞：已登录且非登录页 / 全屏播放页时显示
const showDock = computed(() => userStore.isLoggedIn && showChrome.value)

/**
 * 导航坞在页面上时才给 body 留底部空间。
 * 以前是无条件留白：登录页、全屏播放页没有导航坞，底部却永远空一条。
 */
function syncDockSpacing(visible: boolean) {
  document.body.classList.toggle('has-dock', visible)
}

watch(showDock, syncDockSpacing, { immediate: true })

onMounted(() => {
  userStore.init()
})

onBeforeUnmount(() => {
  document.body.classList.remove('has-dock')
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
