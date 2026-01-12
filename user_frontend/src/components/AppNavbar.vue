<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { computed, ref } from 'vue'
import { Tv, Crown, Calendar, User, LogOut, Menu, X } from 'lucide-vue-next'
import BrandIcon from '@/components/BrandIcon.vue'
import { useAuthSheet } from '@/composables/useAuthSheet'

const userStore = useUserStore()
const route = useRoute()
const { openAuthSheet } = useAuthSheet()

const isLoggedIn = computed(() => userStore.isLoggedIn)
const isVIP = computed(() => userStore.isVIP)
const username = computed(() => userStore.user?.username || '')

const mobileMenuOpen = ref(false)

const navLinks = computed(() => {
  if (isLoggedIn.value) {
    return [
      { name: '控制台', path: '/dashboard', icon: Tv },
      { name: '订阅', path: '/subscription', icon: Crown },
      { name: '签到', path: '/checkin', icon: Calendar },
      { name: '个人中心', path: '/profile', icon: User, highlight: true },
    ]
  }
  return []
})

function handleLogin() {
  openAuthSheet()
  mobileMenuOpen.value = false
}

function handleLogout() {
  if (confirm('确定要退出登录吗？')) {
    userStore.logout()
    window.location.href = '/'
  }
}
</script>

<template>
  <nav class="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-gray-200">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-16">
        <!-- Logo -->
        <RouterLink to="/" class="flex items-center gap-3">
          <BrandIcon :size="40" />
          <span class="text-lg font-bold text-gray-900">Aetrix</span>
        </RouterLink>

        <!-- Desktop Navigation -->
        <div class="hidden md:flex items-center gap-4">
          <template v-if="isLoggedIn">
            <RouterLink
              v-for="link in navLinks"
              :key="link.path"
              :to="link.path"
              class="font-medium transition-all"
              :class="link.highlight
                ? 'px-4 py-2 bg-gradient-to-r from-emerald-500 to-purple-600 text-white rounded-full hover:shadow-lg'
                : 'text-gray-600 hover:text-gray-900'"
            >
              <span v-if="'icon' in link" class="inline-flex items-center gap-1">
                <component :is="link.icon" :size="16" />
                {{ link.name }}
              </span>
              <span v-else>{{ link.name }}</span>
            </RouterLink>
          </template>
          <template v-else>
            <button @click="handleLogin" class="text-gray-600 hover:text-gray-900 font-medium">登录</button>
            <button @click="handleLogin" class="px-4 py-2 bg-gradient-to-r from-emerald-500 to-purple-600 text-white rounded-full font-medium hover:shadow-lg transition-all">
              注册
            </button>
          </template>
        </div>

        <!-- Mobile Menu Button -->
        <button
          @click="mobileMenuOpen = !mobileMenuOpen"
          class="md:hidden p-2 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <Menu v-if="!mobileMenuOpen" :size="24" class="text-gray-600" />
          <X v-else :size="24" class="text-gray-600" />
        </button>
      </div>

      <!-- Mobile Menu -->
      <div
        v-if="mobileMenuOpen"
        class="md:hidden py-4 border-t border-gray-200"
      >
        <div class="flex flex-col gap-2">
          <template v-if="isLoggedIn">
            <RouterLink
              v-for="link in navLinks"
              :key="link.path"
              :to="link.path"
              @click="mobileMenuOpen = false"
              class="flex items-center gap-2 px-4 py-3 rounded-xl transition-all"
              :class="link.highlight
                ? 'bg-gradient-to-r from-emerald-500 to-purple-600 text-white'
                : 'text-gray-600 hover:bg-gray-100'"
            >
              <component v-if="'icon' in link" :is="link.icon" :size="18" />
              {{ link.name }}
            </RouterLink>
            <button
              @click="handleLogout"
              class="flex items-center gap-2 px-4 py-3 rounded-xl text-red-600 hover:bg-red-50 transition-all w-full text-left"
            >
              <LogOut :size="18" />
              退出登录
            </button>
          </template>
          <template v-else>
            <button
              @click="handleLogin"
              class="flex items-center gap-2 px-4 py-3 rounded-xl text-gray-600 hover:bg-gray-100"
            >
              登录
            </button>
            <button
              @click="handleLogin"
              class="flex items-center gap-2 px-4 py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-purple-600 text-white"
            >
              注册
            </button>
          </template>
        </div>
      </div>
    </div>
  </nav>
</template>
