<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { onMounted, computed, watch } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import AnnouncementBanner from '@/components/AnnouncementBanner.vue'
import TelegramBrowserBanner from '@/components/TelegramBrowserBanner.vue'
import Toast from '@/components/Toast.vue'
import AuthSheet from '@/components/AuthSheet.vue'
import { useToast } from '@/composables/useToast'
import { useAuthSheet } from '@/composables/useAuthSheet'

const userStore = useUserStore()
const route = useRoute()
const { messages, remove } = useToast()
const { showAuthSheet, closeAuthSheet } = useAuthSheet()

// AuthSheet 成功回调 - 刷新用户信息
const handleAuthSuccess = () => {
  userStore.fetchUser()
}

// 这些页面有自己的导航栏，不显示全局 AppHeader
const pagesWithOwnNavbar = [
  '/checkin',       // CheckInView
]

// 首页和某些内置页面有自己设计的导航栏，其他页面使用全局 AppHeader
const showHeader = computed(() => !pagesWithOwnNavbar.some(path => route.path === path || route.path.startsWith(path + '/')))

// 有公告横幅时，页面内容需要更多顶部边距
// AnnouncementBanner 组件会自动处理显示/隐藏逻辑
// 这里始终返回 true，保持布局一致
const hasBanner = computed(() => true)

onMounted(() => {
  userStore.init()
})

// 监听登录状态变化，连接/断开 WebSocket
watch(() => userStore.isLoggedIn, (isLoggedIn) => {
  if (isLoggedIn) {
    // WebSocket 会在 NotificationCenter 组件中自动连接
  }
})
</script>

<template>
  <!-- Telegram in-app browser 检测和提示 -->
  <TelegramBrowserBanner />

  <div class="min-h-screen bg-primary">
    <AppHeader v-if="showHeader" />
    <AnnouncementBanner />
    <main class="min-h-screen router-view-container" :class="{ 'pt-16': showHeader, 'pt-safe': showHeader && hasBanner }">
      <RouterView v-slot="{ Component, route }">
        <template v-if="Component">
          <Transition
            :name="(route.meta.transition as string) || 'fade'"
            :css="!route.meta.noTransition"
          >
            <component :is="Component" :key="route.meta.cacheKey || false" />
          </Transition>
        </template>
      </RouterView>
    </main>
    <Toast :messages="messages" @remove="remove" />
    <!-- 全局登录/注册弹窗 -->
    <AuthSheet
      :show="(showAuthSheet as boolean)"
      @update:show="closeAuthSheet"
      @success="handleAuthSuccess"
    />
  </div>
</template>

<style scoped>
.bg-primary {
  background: #030303;
}

/* Router View 容器 - 确保背景色一致 */
.router-view-container {
  background: #030303;
  position: relative;
  min-height: 100vh;
}

/* 有公告横幅时的额外顶部间距 */
.pt-safe {
  padding-top: 7rem; /* 64px 导航栏 + 44px 公告横幅 */
}

@media (max-width: 768px) {
  .pt-safe {
    padding-top: 6rem; /* 56px 导航栏 + 40px 公告横幅 */
  }
}

/* ==================== 页面转场动画 ==================== */
/* 修复闪屏：使用绝对定位确保新页面覆盖旧页面 */
:deep(.v-enter-active),
:deep(.v-leave-active) {
  transition: opacity 0.15s ease;
}

:deep(.v-enter-from) {
  opacity: 0;
}

:deep(.v-leave-to) {
  opacity: 0;
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
}

/* 淡入淡出动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.fade-leave-to {
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
}

/* 滑动动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.25s ease;
}

.slide-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.slide-leave-to {
  opacity: 0;
  transform: translateX(-20px);
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
}

/* 缩放淡入动画 */
.zoom-enter-active,
.zoom-leave-active {
  transition: all 0.2s ease;
}

.zoom-enter-from,
.zoom-leave-to {
  opacity: 0;
  transform: scale(0.98);
}

.zoom-leave-to {
  position: absolute;
  width: 100%;
  top: 0;
  left: 0;
}

/* 移动端滑动动画 */
@media (max-width: 768px) {
  .slide-enter-from {
    transform: translateX(30px);
  }

  .slide-leave-to {
    transform: translateX(-30px);
  }
}

/* 减少动画模式 */
@media (prefers-reduced-motion: reduce) {
  .fade-enter-active,
  .fade-leave-active,
  .slide-enter-active,
  .slide-leave-active,
  .zoom-enter-active,
  .zoom-leave-active {
    transition-duration: 0.01ms;
  }
}
</style>
