<script setup lang="ts">
/**
 * AccountVault - 账号保险箱抽屉
 *
 * 特性：
 * - 抽屉式展开/收起
 * - Emby 账号卡片平铺展示
 * - 支持密码可见性切换、一键复制
 * - 三态：未订阅 | 已订阅待领取 | 已有账号
 * - 基于 BottomSheet 组件
 */
import { ref, computed } from 'vue'
import { Tv, Copy, Check, Eye, EyeOff, ExternalLink, ChevronDown, Lock } from 'lucide-vue-next'
import BottomSheet from '@/components/ui/BottomSheet.vue'

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
  embyAccounts: EmbyAccount[]
  vipExpiry?: string
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isVIP: false,
  embyAccounts: () => [],
  loading: false
})

const emit = defineEmits<{
  claimAccount: []
  copy: [text: string, type: string]
}>()

// 抽屉状态
const showVault = ref(false)
const expandedAccounts = ref<Set<number>>(new Set())
const visiblePasswords = ref<Set<number>>(new Set())
const copiedField = ref<string | null>(null)

// 三态判断
const accountState = computed(() => {
  if (props.embyAccounts.length > 0) return 'has-account'
  if (props.isVIP) return 'subscribed-no-account'
  return 'not-subscribed'
})

// 主要账号
const primaryAccount = computed(() => {
  return props.embyAccounts[0]
})

// 格式化日期
const formatDate = (dateStr?: string) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

// 计算剩余天数
const getDaysRemaining = (expiryDate?: string) => {
  if (!expiryDate) return 0
  const now = new Date()
  const expiry = new Date(expiryDate)
  const diff = expiry.getTime() - now.getTime()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
}

// 切换账号展开
const toggleExpand = (id: number) => {
  if (expandedAccounts.value.has(id)) {
    expandedAccounts.value.delete(id)
  } else {
    expandedAccounts.value.add(id)
  }
}

const isExpanded = (id: number) => {
  return expandedAccounts.value.has(id)
}

// 切换密码可见性
const togglePasswordVisibility = (id: number) => {
  if (visiblePasswords.value.has(id)) {
    visiblePasswords.value.delete(id)
  } else {
    visiblePasswords.value.add(id)
  }
}

const isPasswordVisible = (id: number) => {
  return visiblePasswords.value.has(id)
}

// 复制到剪贴板
const copyToClipboard = async (text: string, type: string) => {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = type
    emit('copy', text, type)
    setTimeout(() => {
      copiedField.value = null
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
    emit('copy', text, type)
  }
}

// 复制全部
const copyAll = (account: EmbyAccount) => {
  const text = `服务器: ${account.server_name}\n地址: ${account.server_url}\n用户名: ${account.username}\n密码: ${account.password}`
  copyToClipboard(text, 'all')
}

// 领取账号
const handleClaimAccount = () => {
  emit('claimAccount')
}

// 打开保险箱
const openVault = () => {
  showVault.value = true
}

// 关闭保险箱
const closeVault = () => {
  showVault.value = false
}

// 暴露方法
defineExpose({
  open: openVault,
  close: closeVault,
  isOpen: () => showVault.value
})
</script>

<template>
  <!-- 触发按钮区域 -->
  <div class="vault-trigger" @click="openVault">
    <div class="vault-preview" :class="`vault-${accountState}`">
      <!-- 未订阅 -->
      <template v-if="accountState === 'not-subscribed'">
        <div class="vault-icon locked">
          <Lock :size="20" />
        </div>
        <div class="vault-info">
          <span class="vault-title">Emby 影音服务</span>
          <span class="vault-subtitle">订阅后解锁 4K 影音库</span>
        </div>
        <ChevronDown :size="18" class="vault-arrow" />
      </template>

      <!-- 已订阅待领取 -->
      <template v-else-if="accountState === 'subscribed-no-account'">
        <div class="vault-icon pending">
          <Tv :size="20" />
        </div>
        <div class="vault-info">
          <span class="vault-title">已订阅，待领取</span>
          <span class="vault-subtitle">一键领取专属账号</span>
        </div>
        <ChevronDown :size="18" class="vault-arrow" />
      </template>

      <!-- 已有账号 -->
      <template v-else-if="accountState === 'has-account' && primaryAccount">
        <div class="vault-icon active">
          <Tv :size="20" />
        </div>
        <div class="vault-info">
          <span class="vault-title">{{ primaryAccount.server_name }}</span>
          <span class="vault-subtitle">剩余 {{ getDaysRemaining(primaryAccount.expires_at) }} 天</span>
        </div>
        <ChevronDown :size="18" class="vault-arrow" />
      </template>
    </div>
  </div>

  <!-- 账号保险箱抽屉 -->
  <BottomSheet
    :show="showVault"
    @update:show="closeVault"
    :max-height="'75vh'"
    close-on-mask-click
    close-on-swipe-down
  >
    <template #default>
      <!-- 头部 -->
      <div class="vault-header">
        <div class="header-icon">
          <Tv :size="20" />
        </div>
        <div class="header-text">
          <h3 class="header-title">账号保险箱</h3>
          <p class="header-subtitle">Emby 影影服务账号管理</p>
        </div>
      </div>

      <!-- 内容区域 -->
      <div class="vault-content">
        <!-- 未订阅 -->
        <div v-if="accountState === 'not-subscribed'" class="vault-empty">
          <div class="empty-icon">
            <Lock :size="32" />
          </div>
          <p class="empty-title">尚未订阅</p>
          <p class="empty-desc">订阅 VIP 即可解锁 Emby 4K 影音库</p>
          <RouterLink to="/subscription" class="vault-btn vault-btn-primary" @click="closeVault">
            查看套餐
          </RouterLink>
        </div>

        <!-- 已订阅待领取 -->
        <div v-else-if="accountState === 'subscribed-no-account'" class="vault-claim">
          <div class="claim-card">
            <div class="claim-icon">
              <Tv :size="24" />
            </div>
            <div class="claim-info">
              <h4 class="claim-title">待领取账号</h4>
              <p class="claim-desc">系统将自动为您分配专属 Emby 账号</p>
            </div>
          </div>
          <button @click="handleClaimAccount" class="vault-btn vault-btn-primary vault-btn-full">
            一键领取账号
          </button>
        </div>

        <!-- 已有账号列表 -->
        <div v-else class="vault-accounts">
          <div
            v-for="account in embyAccounts"
            :key="account.id"
            class="account-card"
            :class="{ 'is-expanded': isExpanded(account.id) }"
          >
            <!-- 卡片头部 -->
            <div class="account-header" @click="toggleExpand(account.id)">
              <div class="account-info">
                <span class="account-name">{{ account.server_name }}</span>
                <span class="account-expiry">有效期至 {{ formatDate(account.expires_at) }}</span>
              </div>
              <div class="account-actions">
                <span class="account-badge">
                  {{ getDaysRemaining(account.expires_at) }} 天
                </span>
                <ChevronDown
                  :size="16"
                  class="expand-icon"
                  :class="{ 'is-expanded': isExpanded(account.id) }"
                />
              </div>
            </div>

            <!-- 卡片详情 -->
            <div class="account-details">
              <div class="detail-row">
                <span class="detail-label">服务器地址</span>
                <div class="detail-value">
                  <code class="detail-code">{{ account.server_url }}</code>
                  <button
                    @click="copyToClipboard(account.server_url, `url-${account.id}`)"
                    class="detail-copy"
                  >
                    <Check v-if="copiedField === `url-${account.id}`" :size="14" class="copy-success" />
                    <Copy v-else :size="14" class="copy-icon" />
                  </button>
                </div>
              </div>

              <div class="detail-row">
                <span class="detail-label">用户名</span>
                <div class="detail-value">
                  <code class="detail-code">{{ account.username }}</code>
                  <button
                    @click="copyToClipboard(account.username, `username-${account.id}`)"
                    class="detail-copy"
                  >
                    <Check v-if="copiedField === `username-${account.id}`" :size="14" class="copy-success" />
                    <Copy v-else :size="14" class="copy-icon" />
                  </button>
                </div>
              </div>

              <div class="detail-row">
                <span class="detail-label">密码</span>
                <div class="detail-value">
                  <code class="detail-code">
                    {{ isPasswordVisible(account.id) ? account.password : '••••••••' }}
                  </code>
                  <button
                    @click="togglePasswordVisibility(account.id)"
                    class="detail-copy"
                  >
                    <Eye v-if="!isPasswordVisible(account.id)" :size="14" class="copy-icon" />
                    <EyeOff v-else :size="14" class="copy-icon" />
                  </button>
                  <button
                    @click="copyToClipboard(account.password, `password-${account.id}`)"
                    class="detail-copy"
                  >
                    <Check v-if="copiedField === `password-${account.id}`" :size="14" class="copy-success" />
                    <Copy v-else :size="14" class="copy-icon" />
                  </button>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="account-actions-row">
                <a
                  :href="account.server_url"
                  target="_blank"
                  rel="noopener"
                  class="vault-btn vault-btn-primary vault-btn-sm"
                >
                  进入 Emby
                  <ExternalLink :size="14" />
                </a>
                <button
                  @click="copyAll(account)"
                  class="vault-btn vault-btn-secondary vault-btn-sm"
                >
                  <Copy :size="14" />
                  复制全部
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </BottomSheet>
</template>

<style scoped>
/* ==================== 触发器 ==================== */
.vault-trigger {
  width: 100%;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.vault-preview {
  display: flex;
  align-items: center;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-3, 12px) var(--neo-space-4, 16px);
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-md, 14px);
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.vault-preview:active {
  background: var(--neo-bg-surface-active, rgba(255, 255, 255, 0.08));
  transform: scale(0.99);
}

.vault-preview.vault-has-account {
  border-color: rgba(16, 185, 129, 0.2);
  background: rgba(16, 185, 129, 0.04);
}

.vault-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--neo-radius-sm, 12px);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.vault-icon.locked {
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.vault-icon.pending {
  background: rgba(16, 185, 129, 0.12);
  color: var(--neo-primary, #10B981);
}

.vault-icon.active {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(5, 150, 105, 0.1));
  color: var(--neo-primary, #10B981);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.vault-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.vault-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
}

.vault-subtitle {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.vault-arrow {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  transition: transform var(--neo-duration-fast, 150ms) ease;
}

.vault-preview:active .vault-arrow {
  transform: translateY(2px);
}

/* ==================== 抽屉头部 ==================== */
.vault-header {
  display: flex;
  align-items: center;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-3, 12px) var(--neo-space-4, 16px);
  border-bottom: 1px solid var(--neo-divider, rgba(255, 255, 255, 0.06));
}

.header-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--neo-radius-sm, 12px);
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-primary, #10B981);
}

.header-text {
  flex: 1;
}

.header-title {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  margin: 0 0 2px 0;
}

.header-subtitle {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin: 0;
}

/* ==================== 内容区域 ==================== */
.vault-content {
  padding: var(--neo-space-4, 16px);
}

/* 未订阅空状态 */
.vault-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--neo-space-6, 24px) var(--neo-space-4, 16px);
  text-align: center;
}

.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin-bottom: var(--neo-space-4, 16px);
}

.empty-title {
  font-size: var(--neo-font-size-lg, 16px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  margin: 0 0 var(--neo-space-1, 4px) 0;
}

.empty-desc {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin: 0 0 var(--neo-space-4, 16px) 0;
}

/* 待领取状态 */
.vault-claim {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-3, 12px);
}

.claim-card {
  display: flex;
  align-items: center;
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-3, 12px);
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: var(--neo-radius-sm, 12px);
}

.claim-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--neo-radius-xs, 8px);
  background: rgba(16, 185, 129, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-primary, #10B981);
}

.claim-info {
  flex: 1;
}

.claim-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  margin: 0 0 2px 0;
}

.claim-desc {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  margin: 0;
}

/* 账号列表 */
.vault-accounts {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-2, 8px);
}

.account-card {
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-md, 14px);
  overflow: hidden;
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.account-card:active {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.08));
}

/* 账号头部 */
.account-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--neo-space-3, 12px);
  cursor: pointer;
  user-select: none;
}

.account-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.account-name {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
}

.account-expiry {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.account-actions {
  display: flex;
  align-items: center;
  gap: var(--neo-space-2, 8px);
}

.account-badge {
  font-size: 10px;
  font-weight: var(--neo-font-weight-semibold, 600);
  padding: 2px 8px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: var(--neo-radius-xs, 8px);
  color: var(--neo-primary, #10B981);
}

.expand-icon {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  transition: transform var(--neo-duration-fast, 150ms) ease;
}

.expand-icon.is-expanded {
  transform: rotate(180deg);
}

/* 账号详情 */
.account-details {
  max-height: 0;
  overflow: hidden;
  transition: max-height var(--neo-duration-normal, 200ms) ease;
  padding: 0 var(--neo-space-3, 12px);
}

.account-card.is-expanded .account-details {
  max-height: 300px;
  padding-bottom: var(--neo-space-3, 12px);
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--neo-space-2, 8px) 0;
  border-bottom: 1px solid var(--neo-divider, rgba(255, 255, 255, 0.06));
}

.detail-row:last-of-type {
  border-bottom: none;
  margin-bottom: var(--neo-space-2, 8px);
}

.detail-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
}

.detail-value {
  display: flex;
  align-items: center;
  gap: var(--neo-space-1, 4px);
}

.detail-code {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
  font-family: ui-monospace, monospace;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-copy {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--neo-radius-xs, 6px);
  background: transparent;
  border: none;
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) ease;
}

.detail-copy:active {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.08));
}

.copy-success {
  color: var(--neo-primary, #10B981);
}

/* 操作按钮行 */
.account-actions-row {
  display: flex;
  gap: var(--neo-space-2, 8px);
}

/* ==================== 按钮样式 ==================== */
.vault-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--neo-space-1, 4px);
  padding: var(--neo-space-2, 8px) var(--neo-space-3, 12px);
  border-radius: var(--neo-radius-sm, 12px);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) ease;
  border: none;
  text-decoration: none;
}

.vault-btn-primary {
  background: var(--neo-primary, #10B981);
  color: white;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.25);
}

.vault-btn-primary:active {
  background: var(--neo-primary-hover, #059669);
  box-shadow: 0 1px 4px rgba(16, 185, 129, 0.2);
}

.vault-btn-secondary {
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.08));
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
  border: 1px solid var(--neo-border-default, rgba(255, 255, 255, 0.08));
}

.vault-btn-secondary:active {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.12));
}

.vault-btn-full {
  width: 100%;
}

.vault-btn-sm {
  padding: var(--neo-space-2, 8px) var(--neo-space-3, 12px);
  font-size: var(--neo-font-size-xs, 11px);
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .vault-preview:active {
    transform: none;
  }

  .expand-icon {
    transition: none;
  }

  .account-details {
    transition: none;
  }
}
</style>
