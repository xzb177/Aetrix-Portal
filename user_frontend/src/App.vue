<script setup lang="ts">
import { RouterView } from 'vue-router'
import { onMounted } from 'vue'
import Toast from '@/components/Toast.vue'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'

const { messages, remove } = useToast()
const userStore = useUserStore()

onMounted(() => {
  userStore.init()
})
</script>

<template>
  <div class="app-shell">
    <RouterView />
    <Toast :messages="messages" @remove="remove" />
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: #05070a;
}
</style>
