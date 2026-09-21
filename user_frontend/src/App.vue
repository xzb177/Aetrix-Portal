<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed, onMounted } from 'vue'
import Toast from '@/components/Toast.vue'
import AppHeader from '@/components/AppHeader.vue'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'

const { messages, remove } = useToast()
const userStore = useUserStore()
const route = useRoute()

/**
 * 全局导航壳：只有一套导航，全部在顶栏（定义见 src/config/navigation.ts）。
 *
 *   ≥900px  顶栏一行：品牌 + 主导航横向铺开 + 搜索 / 积分 / 消息 / 账号
 *   ≤900px  顶栏两行：第一行品牌与账号操作，第二行是**可横向滑动的主导航选项卡**
 *
 * 底部导航坞（AppDock）已移除：同一批入口在窄屏换一套形态、在页面上再多占一条，
 * 是「一个 App 底部栏 + 一个网页顶栏」的来源。现在窄屏也不再另起一套，
 * 主导航只是换成了能左右滑动的选项卡，条目不增不减。
 */
const showChrome = computed(
  () => route.name !== 'login' && !route.path.startsWith('/watch'),
)

onMounted(() => {
  userStore.init()
})
</script>

<template>
  <div class="app-shell">
    <AppHeader v-if="showChrome" />
    <RouterView />
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
