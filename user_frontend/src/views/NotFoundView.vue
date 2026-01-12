<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { Home, ArrowLeft } from 'lucide-vue-next'
</script>

<template>
  <div class="min-h-screen pt-20 flex items-center justify-center px-4">
    <div class="text-center">
      <h1 class="text-9xl font-bold text-primary-500 mb-4">404</h1>
      <h2 class="text-2xl font-semibold text-gray-900 dark:text-white mb-4">
        页面未找到
      </h2>
      <p class="text-gray-500 dark:text-gray-400 mb-8 max-w-md mx-auto">
        抱歉，您访问的页面不存在或已被移除
      </p>
      <div class="flex justify-center space-x-4">
        <button @click="$router.back()" class="btn btn-secondary flex items-center space-x-2">
          <ArrowLeft :size="18" />
          <span>返回</span>
        </button>
        <RouterLink to="/" class="btn btn-primary flex items-center space-x-2">
          <Home :size="18" />
          <span>首页</span>
        </RouterLink>
      </div>
    </div>
  </div>
</template>
