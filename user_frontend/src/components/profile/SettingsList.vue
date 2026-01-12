<script setup lang="ts">
import { ref } from 'vue'
import { Copy, LogOut } from 'lucide-vue-next'

interface SettingItem {
  label: string
  value: string
  copyable?: boolean
  copyValue?: string
}

interface Props {
  items: SettingItem[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
  logout: []
  copy: [text: string, type: string]
}>()

const copiedItem = ref<string | null>(null)

async function copyToClipboard(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedItem.value = label
    emit('copy', text, label)
    setTimeout(() => {
      copiedItem.value = null
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
    emit('copy', text, label)
  }
}

function handleLogout() {
  emit('logout')
}
</script>

<template>
  <div class="settings-list">
    <h3 class="text-white/60 text-sm font-medium px-1 mb-3">账号信息</h3>

    <div class="bg-card rounded-xl overflow-hidden">
      <div
        v-for="(item, index) in items"
        :key="item.label"
        class="setting-item flex items-center justify-between px-4 py-3.5"
        :class="{ 'border-b border-white/6': index < items.length - 1 }"
      >
        <span class="text-white/60 text-sm">{{ item.label }}</span>
        <div class="flex items-center gap-2">
          <span class="text-white/80 text-sm font-medium">{{ item.value }}</span>
          <button
            v-if="item.copyable"
            @click="copyToClipboard(item.copyValue || item.value, item.label)"
            class="p-1.5 rounded hover:bg-white/5 active:bg-white/10 transition-colors"
            :title="'复制 ' + item.label"
          >
            <Copy v-if="copiedItem !== item.label" :size="14" class="text-white/30" />
            <span v-else class="text-accent text-xs">已复制</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Logout Button -->
    <button
      @click="handleLogout"
      class="logout-btn w-full py-4 mt-4 text-danger/70 hover:text-danger text-sm font-medium active:bg-danger/5 transition-all flex items-center justify-center gap-2"
    >
      <LogOut :size="16" />
      退出登录
    </button>
  </div>
</template>

<style scoped>
.settings-list {
  margin-bottom: 1rem;
}

.bg-card {
  background: var(--bg-card);
}

.border-white\/6 {
  border-color: rgba(255, 255, 255, 0.06);
}

.text-white\/80 {
  color: rgba(255, 255, 255, 0.8);
}

.text-white\/60 {
  color: rgba(255, 255, 255, 0.6);
}

.text-white\/30 {
  color: rgba(255, 255, 255, 0.3);
}

.text-accent {
  color: var(--accent);
}

.text-danger\/70 {
  color: rgba(239, 68, 68, 0.7);
}

.text-danger {
  color: var(--color-danger);
}

.bg-danger\/5 {
  background: rgba(239, 68, 68, 0.05);
}

.bg-white\/5 {
  background: rgba(255, 255, 255, 0.05);
}

.bg-white\/10 {
  background: rgba(255, 255, 255, 0.1);
}
</style>
