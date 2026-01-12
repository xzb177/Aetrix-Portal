<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Tv, Copy, Check, Eye, EyeOff, ExternalLink, Loader2 } from 'lucide-vue-next'

interface EmbyAccount {
  id: number
  server_name: string
  server_url: string
  username: string
  password: string
  expires_at: string
}

interface Props {
  isVIP?: boolean
  /** @deprecated use isVIP instead */
  isVIP_v2?: boolean
  embyAccounts: EmbyAccount[]
  vipExpiry?: string
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isVIP: false,
  embyAccounts: () => [],
  loading: false
})

// 兼容两种 prop 名称
const effectiveIsVIP = computed(() => props.isVIP ?? props.isVIP_v2 ?? false)

const emit = defineEmits<{
  claimAccount: []
  copy: [text: string, type: string]
}>()

const router = useRouter()
const visiblePasswords = ref<Set<number>>(new Set())
const copiedField = ref<string | null>(null)

// 三态判断
const accountState = computed(() => {
  if (props.embyAccounts.length > 0) return 'has-account'
  if (effectiveIsVIP.value) return 'subscribed-no-account'
  return 'not-subscribed'
})

const primaryAccount = computed(() => {
  return props.embyAccounts[0]
})

function getDaysRemaining(expiryDate?: string) {
  if (!expiryDate) return 0
  const now = new Date()
  const expiry = new Date(expiryDate)
  const diff = expiry.getTime() - now.getTime()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function togglePasswordVisibility(id: number) {
  if (visiblePasswords.value.has(id)) {
    visiblePasswords.value.delete(id)
  } else {
    visiblePasswords.value.add(id)
  }
}

function isPasswordVisible(id: number) {
  return visiblePasswords.value.has(id)
}

async function copyToClipboard(text: string, type: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = type
    emit('copy', text, type)
    setTimeout(() => {
      copiedField.value = null
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
    emit('copy', text, type) // Still emit for error handling
  }
}

function copyAll(account: EmbyAccount) {
  const text = `服务器: ${account.server_name}\n地址: ${account.server_url}\n用户名: ${account.username}\n密码: ${account.password}`
  copyToClipboard(text, 'all')
}

function handleClaimAccount() {
  emit('claimAccount')
}
</script>

<template>
  <!-- Loading Skeleton -->
  <div v-if="loading" class="emby-card p-5 bg-card rounded-xl">
    <div class="flex items-center gap-3 mb-4">
      <div class="w-10 h-10 rounded-full bg-elevated animate-pulse"></div>
      <div class="flex-1">
        <div class="h-4 w-32 bg-elevated rounded animate-pulse mb-2"></div>
        <div class="h-3 w-40 bg-elevated/50 rounded animate-pulse"></div>
      </div>
    </div>
    <div class="h-12 bg-elevated rounded-xl animate-pulse"></div>
  </div>

  <!-- ====== 状态1: 未订阅 ====== -->
  <div v-else-if="accountState === 'not-subscribed'" class="emby-card p-5 bg-card rounded-xl">
    <div class="flex items-center gap-3 mb-4">
      <div class="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center">
        <Tv :size="18" class="text-white/60" />
      </div>
      <div class="flex-1">
        <div class="text-white font-medium">Emby 影音服务</div>
        <div class="text-white/50 text-sm">订阅后解锁 4K 影音库</div>
      </div>
    </div>

    <RouterLink to="/subscription"
      class="btn-primary w-full py-3.5 rounded-xl text-white font-medium text-center flex items-center justify-center gap-2 active:scale-[0.98] active:opacity-90 transition-all">
      查看套餐
    </RouterLink>
    <p class="text-white/40 text-xs text-center mt-3">支付前确认，订单可查</p>
  </div>

  <!-- ====== 状态2: 已订阅未领取 ====== -->
  <div v-else-if="accountState === 'subscribed-no-account'" class="emby-card p-5 bg-card rounded-xl border border-accent/20">
    <div class="flex items-center gap-3 mb-4">
      <div class="w-10 h-10 rounded-full bg-accent/10 flex items-center justify-center">
        <Tv :size="18" class="text-accent" />
      </div>
      <div class="flex-1">
        <div class="text-white font-medium">已订阅，待领取</div>
        <div class="text-white/50 text-sm">系统将自动为您分配专属账号</div>
      </div>
    </div>

    <button @click="handleClaimAccount"
      class="btn-primary w-full py-3.5 rounded-xl text-white font-medium text-center flex items-center justify-center gap-2 active:scale-[0.98] active:opacity-90 transition-all">
      一键领取账号
    </button>
  </div>

  <!-- ====== 状态3: 已有账号 ====== -->
  <div v-else-if="accountState === 'has-account' && primaryAccount" class="emby-card p-5 bg-card rounded-xl">
    <!-- Account Header -->
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-full bg-accent/10 flex items-center justify-center">
          <Tv :size="18" class="text-accent" />
        </div>
        <div>
          <div class="text-white font-medium">{{ primaryAccount.server_name }}</div>
          <div class="text-accent text-sm">有效期至 {{ formatDate(primaryAccount.expires_at) }}</div>
        </div>
      </div>
      <span class="px-2 py-1 rounded text-xs bg-accent/10 text-accent whitespace-nowrap">
        剩余 {{ getDaysRemaining(primaryAccount.expires_at) }}天
      </span>
    </div>

    <!-- Account Details (Expandable) -->
    <div class="account-details mb-4 space-y-2">
      <!-- Server URL -->
      <div class="flex items-center justify-between py-2 px-3 bg-elevated rounded-lg">
        <span class="text-white/50 text-xs">服务器地址</span>
        <div class="flex items-center gap-2">
          <code class="text-white/80 text-xs max-w-[180px] truncate">{{ primaryAccount.server_url }}</code>
          <button @click="copyToClipboard(primaryAccount.server_url, 'url')"
            class="p-1.5 rounded hover:bg-white/5 active:bg-white/10 transition-colors">
            <Check v-if="copiedField === 'url'" :size="14" class="text-accent" />
            <Copy v-else :size="14" class="text-white/40" />
          </button>
        </div>
      </div>

      <!-- Username -->
      <div class="flex items-center justify-between py-2 px-3 bg-elevated rounded-lg">
        <span class="text-white/50 text-xs">用户名</span>
        <div class="flex items-center gap-2">
          <code class="text-white/80 text-xs">{{ primaryAccount.username }}</code>
          <button @click="copyToClipboard(primaryAccount.username, 'username')"
            class="p-1.5 rounded hover:bg-white/5 active:bg-white/10 transition-colors">
            <Check v-if="copiedField === 'username'" :size="14" class="text-accent" />
            <Copy v-else :size="14" class="text-white/40" />
          </button>
        </div>
      </div>

      <!-- Password -->
      <div class="flex items-center justify-between py-2 px-3 bg-elevated rounded-lg">
        <span class="text-white/50 text-xs">密码</span>
        <div class="flex items-center gap-2">
          <code class="text-white/80 text-xs">{{ isPasswordVisible(primaryAccount.id) ? primaryAccount.password : '••••••••' }}</code>
          <button @click="togglePasswordVisibility(primaryAccount.id)"
            class="p-1.5 rounded hover:bg-white/5 active:bg-white/10 transition-colors">
            <Eye v-if="!isPasswordVisible(primaryAccount.id)" :size="14" class="text-white/40" />
            <EyeOff v-else :size="14" class="text-white/40" />
          </button>
          <button @click="copyToClipboard(primaryAccount.password, 'password')"
            class="p-1.5 rounded hover:bg-white/5 active:bg-white/10 transition-colors">
            <Check v-if="copiedField === 'password'" :size="14" class="text-accent" />
            <Copy v-else :size="14" class="text-white/40" />
          </button>
        </div>
      </div>
    </div>

    <!-- Action Buttons -->
    <div class="flex gap-2">
      <a :href="primaryAccount.server_url" target="_blank" rel="noopener"
        class="btn-primary flex-1 py-3 rounded-xl text-white font-medium text-center flex items-center justify-center gap-2 active:scale-[0.98] active:opacity-90 transition-all">
        进入 Emby
        <ExternalLink :size="16" />
      </a>
      <button @click="copyAll(primaryAccount)"
        class="px-4 py-3 rounded-xl border border-white/10 text-white/70 hover:text-white hover:bg-white/5 active:scale-[0.98] transition-all"
        title="复制全部信息">
        <Copy :size="18" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.emby-card {
  background: var(--bg-card);
  border: 1px solid transparent;
}

.bg-card {
  background: var(--bg-card);
}

.bg-elevated {
  background: var(--bg-elevated);
}

.bg-accent\/10 {
  background: rgba(16, 185, 129, 0.1);
}

.bg-white\/5 {
  background: rgba(255, 255, 255, 0.05);
}

.bg-white\/10 {
  background: rgba(255, 255, 255, 0.1);
}

.border-accent\/20 {
  border-color: rgba(16, 185, 129, 0.2);
}

.border-white\/10 {
  border-color: rgba(255, 255, 255, 0.1);
}

.text-accent {
  color: var(--accent);
}

.text-white\/80 {
  color: rgba(255, 255, 255, 0.8);
}

.text-white\/70 {
  color: rgba(255, 255, 255, 0.7);
}

.text-white\/60 {
  color: rgba(255, 255, 255, 0.6);
}

.text-white\/50 {
  color: rgba(255, 255, 255, 0.5);
}

.text-white\/40 {
  color: rgba(255, 255, 255, 0.4);
}

.btn-primary {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.3);
}

.btn-primary:hover {
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.5);
}

code {
  font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.animate-pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
</style>
