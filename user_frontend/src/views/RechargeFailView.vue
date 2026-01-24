<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { XCircle, RefreshCw, ArrowLeft, Headphones, Home } from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()

const errorMessage = ref('')
const errorCode = ref('')

onMounted(() => {
  // 从 URL 参数获取错误信息
  const msg = route.query.message
  const code = route.query.code
  if (msg) {
    errorMessage.value = String(msg)
  }
  if (code) {
    errorCode.value = String(code)
  }
})

function goBack() {
  router.push('/recharge')
}

function retry() {
  router.push('/recharge')
}

function goHome() {
  router.push('/')
}

// 联系客服
function contactSupport() {
  // 这里可以打开客服链接或者显示客服信息
  window.open('https://t.me/your_support_bot', '_blank')
}
</script>

<template>
  <div class="fail-page">
    <!-- 头部返回 -->
    <header class="fail-header">
      <button @click="goBack" class="back-btn">
        <ArrowLeft :size="20" />
        返回
      </button>
    </header>

    <!-- 主内容 -->
    <div class="fail-content">
      <!-- 失败图标 -->
      <div class="fail-icon-wrapper">
        <div class="fail-icon">
          <XCircle :size="48" />
        </div>
      </div>

      <!-- 标题 -->
      <h1 class="fail-title">充值失败</h1>
      <p class="fail-desc">很抱歉，充值未能完成</p>

      <!-- 错误信息卡片 -->
      <div class="error-card">
        <div v-if="errorMessage" class="error-message">
          {{ errorMessage }}
        </div>
        <div v-else class="error-message">
          支付过程中出现异常，请稍后重试
        </div>
        <div v-if="errorCode" class="error-code">
          错误代码: {{ errorCode }}
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="actions">
        <button @click="retry" class="action-btn action-btn--primary">
          <RefreshCw :size="18" />
          重新充值
        </button>
        <button @click="contactSupport" class="action-btn action-btn--secondary">
          <Headphones :size="18" />
          联系客服
        </button>
        <button @click="goHome" class="action-btn action-btn--tertiary">
          <Home :size="18" />
          返回首页
        </button>
      </div>

      <!-- 提示信息 -->
      <div class="tips">
        <p class="tips-title">常见问题</p>
        <ul class="tips-list">
          <li>支付超时：请在 30 分钟内完成支付</li>
          <li>余额不足：请确保账户有足够余额</li>
          <li>网络问题：请检查网络连接后重试</li>
          <li>如持续失败，请联系客服处理</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fail-page {
  min-height: 100vh;
  background: var(--neo-bg-canvas, #030303);
  padding: var(--space-5, 20px);
}

.fail-header {
  padding: var(--space-4, 16px) 0;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary);
  font-size: var(--neo-font-size-sm, 12px);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms);
}

.back-btn:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(0.98);
}

.fail-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: var(--space-8, 32px);
}

/* 失败图标 */
.fail-icon-wrapper {
  margin-bottom: var(--space-5, 20px);
}

.fail-icon {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: var(--neo-danger-bg, rgba(239, 68, 68, 0.15));
  border: 2px solid var(--neo-danger, #ef4444);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-danger, #ef4444);
}

.fail-title {
  font-size: var(--neo-font-size-2xl, 20px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary);
  margin: 0 0 var(--space-2, 8px) 0;
}

.fail-desc {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-tertiary);
  margin: 0 0 var(--space-6, 24px) 0;
}

/* 错误信息卡片 */
.error-card {
  width: 100%;
  max-width: 320px;
  background: var(--neo-danger-bg, rgba(239, 68, 68, 0.1));
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--space-4, 16px);
  margin-bottom: var(--space-6, 24px);
}

.error-message {
  font-size: var(--neo-font-size-md, 14px);
  color: var(--neo-danger, #ef4444);
  margin-bottom: var(--space-2, 8px);
}

.error-code {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
  font-family: ui-monospace, monospace;
}

/* 操作按钮 */
.actions {
  width: 100%;
  max-width: 320px;
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  margin-bottom: var(--space-6, 24px);
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px) var(--space-4, 16px);
  border-radius: var(--neo-radius-sm, 12px);
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms);
  border: none;
}

.action-btn--primary {
  background: var(--neo-primary, #10b981);
  color: var(--neo-text-inverse, #fff);
}

.action-btn--primary:active {
  background: var(--neo-primary-hover, #059669);
  transform: scale(0.98);
}

.action-btn--secondary {
  background: var(--neo-bg-surface-2);
  border: 1px solid var(--neo-border-default);
  color: var(--neo-text-primary);
}

.action-btn--secondary:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(0.98);
}

.action-btn--tertiary {
  background: transparent;
  border: 1px solid var(--neo-border-subtle);
  color: var(--neo-text-tertiary);
}

.action-btn--tertiary:active {
  background: var(--neo-bg-surface-hover);
  transform: scale(0.98);
}

/* 提示信息 */
.tips {
  width: 100%;
  max-width: 320px;
  background: var(--neo-bg-surface-1);
  border: 1px solid var(--neo-border-subtle);
  border-radius: var(--neo-radius-md, 14px);
  padding: var(--space-4, 16px);
}

.tips-title {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-secondary);
  margin: 0 0 var(--space-3, 12px) 0;
}

.tips-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.tips-list li {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary);
  padding: var(--space-1, 4px) 0;
  padding-left: var(--space-3, 12px);
  position: relative;
}

.tips-list li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--neo-text-tertiary);
}
</style>
