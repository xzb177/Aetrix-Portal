<script setup lang="ts">
import { Wallet, Users, Ticket, MessageCircle } from 'lucide-vue-next'

interface QuickAction {
  id: string
  label: string
  icon: any
  to: string
  color: string
}

const actions: QuickAction[] = [
  { id: 'recharge', label: '余额充值', icon: Wallet, to: '/recharge', color: 'text-accent' },
  { id: 'invite', label: '邀请好友', icon: Users, to: '/invite', color: 'text-blue-400' },
  { id: 'exchange', label: '兑换码', icon: Ticket, to: '/exchange-code', color: 'text-amber-400' },
  { id: 'support', label: '联系客服', icon: MessageCircle, to: '/tickets', color: 'text-purple-400' },
]
</script>

<template>
  <div class="quick-grid">
    <h3 class="text-white/60 text-sm font-medium px-1 mb-3">快捷操作</h3>
    <div class="grid grid-cols-2 gap-3">
      <RouterLink
        v-for="action in actions"
        :key="action.id"
        :to="action.to"
        class="quick-item flex flex-col items-center justify-center gap-2 p-4 bg-card rounded-xl active:scale-[0.98] active:bg-elevated transition-all duration-150"
      >
        <component :is="action.icon" :size="24" :class="action.color" />
        <span class="text-white/90 text-sm font-medium">{{ action.label }}</span>
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.quick-grid {
  margin-bottom: 1rem;
}

.bg-card {
  background: var(--bg-card);
}

.bg-elevated {
  background: var(--bg-elevated);
}

.text-white\/90 {
  color: rgba(255, 255, 255, 0.9);
}

.text-white\/60 {
  color: rgba(255, 255, 255, 0.6);
}

/* Icon color classes */
.text-accent {
  color: var(--accent);
}

.text-blue-400 {
  color: #60a5fa;
}

.text-amber-400 {
  color: #fbbf24;
}

.text-purple-400 {
  color: #c084fc;
}
</style>
