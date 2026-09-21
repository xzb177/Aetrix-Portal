<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { computed, onMounted } from 'vue'
import Toast from '@/components/Toast.vue'
import AppDock from '@/components/AppDock.vue'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'

const { messages, remove } = useToast()
const userStore = useUserStore()
const route = useRoute()

// 底部导航坞：已登录且非登录页 / 全屏播放页时显示
const showDock = computed(
  () => userStore.isLoggedIn && route.name !== 'login' && !route.path.startsWith('/watch'),
)

onMounted(() => {
  userStore.init()
})
</script>

<template>
  <div class="app-shell">
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
</style>
