<script setup lang="ts">
import { RouterView } from 'vue-router'
import Toast from '@/components/Toast.vue'
</script>

<template>
  <RouterView />
  <Toast />
</template>

<style>
html, body {
  margin: 0;
  padding: 0;
  height: 100%;
}

#app {
  height: 100%;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
</style>
