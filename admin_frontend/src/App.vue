<script setup lang="ts">
import { RouterView } from 'vue-router'
import Toast from '@/components/Toast.vue'
</script>

<template>
  <RouterView />
  <Toast />
</template>

<style>
html,
body {
  margin: 0;
  padding: 0;
  height: 100%;
  background: var(--color-bg-primary, #0a0a0a);
}

#app {
  height: 100%;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: var(--color-text-primary, #fff);
}
</style>
