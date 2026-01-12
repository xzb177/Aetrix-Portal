<script setup lang="ts">
import { reactive, ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Eye, EyeOff, Mail, Lock, MessageCircle } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import { login } from '@/api'

const router = useRouter()
const authStore = useAuthStore()
const toast = useToast()

// 登录视图状态：'main' | 'password'
const viewState = ref<'main' | 'password'>('main')

// 账号密码表单
const form = reactive({
  account: '',
  password: '',
})

// UI 状态
const showPassword = ref(false)
const loading = ref(false)
const focusedField = ref<string | null>(null)

// 字段错误状态
const fieldErrors = reactive({
  account: '',
  password: '',
})

// 按钮禁用状态
const isLoginDisabled = computed(() => {
  return !form.account || !form.password || loading.value
})

// 验证表单
const validateForm = (): boolean => {
  // 清空之前的错误
  fieldErrors.account = ''
  fieldErrors.password = ''

  let isValid = true

  // 验证账号
  if (!form.account.trim()) {
    fieldErrors.account = '请输入账号或邮箱'
    isValid = false
  } else if (form.account.includes('@') && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.account)) {
    fieldErrors.account = '请输入有效的邮箱地址'
    isValid = false
  }

  // 验证密码
  if (!form.password) {
    fieldErrors.password = '请输入密码'
    isValid = false
  } else if (form.password.length < 6) {
    fieldErrors.password = '密码至少需要 6 位字符'
    isValid = false
  }

  return isValid
}

// 处理登录
const handleLogin = async () => {
  if (!validateForm()) {
    // 触发抖动动画
    const errorField = fieldErrors.account ? 'account' : 'password'
    triggerShake(errorField)
    return
  }

  loading.value = true

  try {
    const res = await login({
      username: form.account,
      password: form.password,
    })
    authStore.setAdminInfo(res.admin_info, res.csrf_token)
    toast.success('登录成功')
    router.replace('/')
  } catch (error: any) {
    const errorMsg = error?.response?.data?.detail || '登录失败'
    handleLoginError(errorMsg)
  } finally {
    loading.value = false
  }
}

// 处理登录错误
const handleLoginError = (errorMsg: string) => {
  // 根据错误消息设置字段级错误
  if (errorMsg.includes('用户') || errorMsg.includes('不存在')) {
    fieldErrors.account = '该账号尚未注册'
    triggerShake('account')
  } else if (errorMsg.includes('密码')) {
    fieldErrors.password = '密码错误'
    triggerShake('password')
  } else {
    fieldErrors.password = errorMsg
    triggerShake('password')
  }
}

// 抖动动画
const shakeStates = ref({
  account: false,
  password: false,
})

const triggerShake = (field: 'account' | 'password') => {
  shakeStates.value[field] = true
  setTimeout(() => {
    shakeStates.value[field] = false
  }, 300)
}

// Telegram 一键登录
const handleTelegramLogin = () => {
  toast.info('Telegram 登录功能开发中')
}

// 导航操作
const goBack = () => {
  if (viewState.value === 'password') {
    viewState.value = 'main'
  } else {
    router.back()
  }
}

const goToPasswordLogin = () => {
  viewState.value = 'password'
}

const goToRegister = () => {
  toast.info('注册功能开发中')
}

const goToForgotPassword = () => {
  toast.info('忘记密码功能开发中')
}

const contactSupport = () => {
  toast.info('客服功能开发中')
}

// 网络状态监听
const isOnline = ref(navigator.onLine)

const handleOnlineStatus = () => {
  isOnline.value = navigator.onLine
  if (!isOnline.value) {
    toast.warning('网络连接已断开')
  }
}

onMounted(() => {
  window.addEventListener('online', handleOnlineStatus)
  window.addEventListener('offline', handleOnlineStatus)
})

onUnmounted(() => {
  window.removeEventListener('online', handleOnlineStatus)
  window.removeEventListener('offline', handleOnlineStatus)
})
</script>

<template>
  <div class="mobile-login-page">
    <!-- 网络异常提示 -->
    <Transition name="slide-down">
      <div v-if="!isOnline" class="offline-banner">
        <MessageCircle :size="16" />
        <span>网络连接失败，请检查网络后重试</span>
      </div>
    </Transition>

    <!-- 主登录视图 -->
    <div v-if="viewState === 'main'" class="login-view login-view-main">
      <!-- Logo 区域 -->
      <div class="logo-section">
        <div class="logo-container">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="logo-icon">
            <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h1 class="app-title">Aetrix 会员服务</h1>
        <p class="app-tagline">流畅观看，随时随地享受影院级体验</p>
      </div>

      <!-- 登录按钮区 -->
      <div class="login-actions">
        <!-- Telegram 一键登录（主按钮） -->
        <button
          class="login-btn login-btn-primary"
          @click="handleTelegramLogin"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" class="telegram-icon">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .37z"/>
          </svg>
          <span>Telegram 一键登录</span>
        </button>

        <!-- 分隔线 -->
        <div class="divider">
          <span class="divider-line"></span>
          <span class="divider-text">或</span>
          <span class="divider-line"></span>
        </div>

        <!-- 账号密码登录（次按钮） -->
        <button
          class="login-btn login-btn-secondary"
          @click="goToPasswordLogin"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="btn-icon">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
          <span>账号密码登录</span>
        </button>
      </div>

      <!-- 协议提示 -->
      <p class="agreement-text">
        登录即表示您同意《用户协议》和《隐私政策》
      </p>

      <!-- 底部链接 -->
      <div class="footer-links">
        <button class="link-btn" @click="contactSupport">
          <MessageCircle :size="16" />
          <span>遇到问题？联系客服</span>
        </button>
        <div class="register-link">
          <span>还没有账号？</span>
          <button class="link-text" @click="goToRegister">立即注册</button>
        </div>
      </div>
    </div>

    <!-- 账号密码登录视图 -->
    <Transition name="slide-left">
      <div v-if="viewState === 'password'" class="login-view login-view-password">
        <!-- 导航栏 -->
        <div class="nav-header">
          <button class="nav-back" @click="goBack">
            <ArrowLeft :size="24" />
          </button>
          <span class="nav-title">登录</span>
          <div class="nav-placeholder"></div>
        </div>

        <!-- 简化的标题 -->
        <div class="password-header">
          <h2 class="password-title">欢迎回来</h2>
        </div>

        <!-- 登录表单 -->
        <div class="password-form">
          <!-- 账号输入框 -->
          <div class="input-group">
            <div
              class="input-field"
              :class="{
                'input-focused': focusedField === 'account',
                'input-error': fieldErrors.account,
                'input-shake': shakeStates.account
              }"
            >
              <Mail :size="20" class="input-icon" />
              <input
                v-model="form.account"
                type="text"
                placeholder="账号/邮箱"
                @focus="focusedField = 'account'"
                @blur="focusedField = null"
              />
            </div>
            <Transition name="fade-slide">
              <div v-if="fieldErrors.account" class="error-message">
                {{ fieldErrors.account }}
              </div>
            </Transition>
          </div>

          <!-- 密码输入框 -->
          <div class="input-group">
            <div
              class="input-field"
              :class="{
                'input-focused': focusedField === 'password',
                'input-error': fieldErrors.password,
                'input-shake': shakeStates.password
              }"
            >
              <Lock :size="20" class="input-icon" />
              <input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="密码"
                @focus="focusedField = 'password'"
                @blur="focusedField = null"
                @keyup.enter="handleLogin"
              />
              <button
                type="button"
                class="toggle-password"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" :size="18" />
                <Eye v-else :size="18" />
              </button>
            </div>
            <div class="input-footer">
              <Transition name="fade-slide">
                <div v-if="fieldErrors.password" class="error-message">
                  {{ fieldErrors.password }}
                  <button v-if="fieldErrors.password.includes('密码')" class="error-action" @click="goToForgotPassword">
                    忘记密码？
                  </button>
                </div>
              </Transition>
            </div>
          </div>

          <!-- 登录按钮 -->
          <button
            class="submit-btn"
            :class="{ 'submit-btn-disabled': isLoginDisabled }"
            :disabled="isLoginDisabled"
            @click="handleLogin"
          >
            <span v-if="loading" class="loading-spinner"></span>
            <span>{{ loading ? '登录中...' : '登 录' }}</span>
          </button>
        </div>

        <!-- 底部链接 -->
        <div class="password-footer">
          <button class="link-btn" @click="contactSupport">
            <MessageCircle :size="16" />
            <span>遇到问题？联系客服</span>
          </button>
          <div class="register-link">
            <span>还没有账号？</span>
            <button class="link-text" @click="goToRegister">立即注册</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ==================== 页面容器 ==================== */
.mobile-login-page {
  min-height: 100vh;
  min-height: 100dvh;
  background: linear-gradient(180deg, #0F0F1A 0%, #1A1A2E 100%);
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.mobile-login-page::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(
    circle at 30% 10%,
    rgba(139, 92, 246, 0.15) 0%,
    transparent 50%
  );
  pointer-events: none;
}

.mobile-login-page::after {
  content: '';
  position: absolute;
  bottom: -30%;
  right: -30%;
  width: 150%;
  height: 150%;
  background: radial-gradient(
    circle at 70% 90%,
    rgba(42, 171, 238, 0.1) 0%,
    transparent 50%
  );
  pointer-events: none;
}

/* ==================== 网络异常横幅 ==================== */
.offline-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  padding: 12px 20px;
  padding-top: max(12px, env(safe-area-inset-top));
  background: rgba(245, 158, 11, 0.95);
  backdrop-filter: blur(10px);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #ffffff;
  font-size: 13px;
  font-weight: 500;
  z-index: 100;
}

/* ==================== 登录视图容器 ==================== */
.login-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 20px;
  padding-top: max(20px, env(safe-area-inset-top));
  padding-bottom: max(20px, env(safe-area-inset-bottom));
  position: relative;
  z-index: 1;
}

/* ==================== 主登录视图 ==================== */
.login-view-main {
  justify-content: center;
  align-items: center;
}

/* Logo 区域 */
.logo-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 32px;
}

.logo-container {
  width: 64px;
  height: 64px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.3), rgba(42, 171, 238, 0.2));
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 8px 32px rgba(139, 92, 246, 0.2);
}

.logo-icon {
  width: 32px;
  height: 32px;
  color: #8B5CF6;
}

.app-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
  text-align: center;
}

.app-tagline {
  font-size: 14px;
  color: var(--text-secondary);
  text-align: center;
  max-width: 260px;
  line-height: 1.5;
}

/* 登录按钮区 */
.login-actions {
  width: 100%;
  max-width: 320px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 主按钮 - Telegram */
.login-btn-primary {
  height: 48px;
  background: #2AABEE;
  border: none;
  border-radius: 14px;
  color: #ffffff;
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(42, 171, 238, 0.3);
}

.login-btn-primary:active {
  transform: scale(0.97);
  box-shadow: 0 2px 8px rgba(42, 171, 238, 0.3);
}

.telegram-icon {
  width: 22px;
  height: 22px;
}

/* 分隔线 */
.divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 0;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: rgba(255, 255, 255, 0.1);
}

.divider-text {
  font-size: 13px;
  color: var(--text-tertiary);
  font-weight: 500;
}

/* 次按钮 - 账号密码 */
.login-btn-secondary {
  height: 48px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.login-btn-secondary:active {
  transform: scale(0.97);
  background: rgba(255, 255, 255, 0.12);
}

.btn-icon {
  width: 20px;
  height: 20px;
  color: var(--text-secondary);
}

/* 协议提示 */
.agreement-text {
  font-size: 12px;
  color: var(--text-tertiary);
  text-align: center;
  margin-top: 24px;
  line-height: 1.6;
}

/* 底部链接 */
.footer-links {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  margin-top: auto;
  padding-top: 24px;
}

.link-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.link-btn:active {
  background: rgba(255, 255, 255, 0.05);
}

.register-link {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  color: var(--text-secondary);
}

.link-text {
  background: transparent;
  border: none;
  color: #8B5CF6;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
}

.link-text:active {
  opacity: 0.7;
}

/* ==================== 账号密码登录视图 ==================== */
.login-view-password {
  padding: 0;
}

/* 导航栏 */
.nav-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: max(44px, env(safe-area-inset-top) + 44px);
  padding: 0 20px;
  padding-top: env(safe-area-inset-top);
}

.nav-back {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-primary);
  cursor: pointer;
  border-radius: 12px;
  transition: all 0.2s ease;
}

.nav-back:active {
  background: rgba(255, 255, 255, 0.05);
}

.nav-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}

.nav-placeholder {
  width: 44px;
}

/* 密码登录标题 */
.password-header {
  padding: 20px;
}

.password-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 表单区域 */
.password-form {
  flex: 1;
  padding: 0 20px;
  display: flex;
  flex-direction: column;
}

/* 输入组 */
.input-group {
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
}

.input-field {
  position: relative;
  display: flex;
  align-items: center;
  height: 48px;
  background: rgba(0, 0, 0, 0.3);
  border: 1.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 0 16px;
  transition: all 0.2s ease;
}

.input-field.input-focused {
  border-color: #2AABEE;
  background: rgba(0, 0, 0, 0.3);
  box-shadow: 0 0 0 3px rgba(42, 171, 238, 0.15);
}

.input-field.input-error {
  border-color: #EF4444;
  background: rgba(239, 68, 68, 0.1);
}

.input-icon {
  color: var(--text-tertiary);
  margin-right: 12px;
  flex-shrink: 0;
  transition: color 0.2s ease;
}

.input-field.input-focused .input-icon {
  color: #2AABEE;
}

.input-field.input-error .input-icon {
  color: #EF4444;
}

.input-field input {
  flex: 1;
  height: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 16px;
}

.input-field input::placeholder {
  color: var(--text-tertiary);
}

/* 切换密码按钮 */
.toggle-password {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 8px;
  margin: -6px -8px -6px 0;
  transition: all 0.2s ease;
}

.toggle-password:active {
  background: rgba(255, 255, 255, 0.05);
}

/* 错误提示 */
.error-message {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 4px;
  color: #EF4444;
  font-size: 13px;
  line-height: 1.4;
}

.error-action {
  background: transparent;
  border: none;
  color: #2AABEE;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
  margin-left: 4px;
  text-decoration: underline;
}

.input-footer {
  min-height: 32px;
}

/* 提交按钮 */
.submit-btn {
  margin-top: 20px;
  height: 48px;
  background: linear-gradient(135deg, #8B5CF6 0%, #6366F1 100%);
  border: none;
  border-radius: 14px;
  color: #ffffff;
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(139, 92, 246, 0.3);
}

.submit-btn:active:not(.submit-btn-disabled) {
  transform: scale(0.97);
  box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
}

.submit-btn-disabled {
  opacity: 0.4;
  cursor: not-allowed;
  background: rgba(255, 255, 255, 0.05);
  box-shadow: none;
}

/* Loading Spinner */
.loading-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 密码登录底部 */
.password-footer {
  padding: 20px;
  padding-bottom: max(20px, env(safe-area-inset-bottom));
}

/* ==================== 动画 ==================== */

/* 页面切换动画 */
.slide-left-enter-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.slide-left-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 1, 1);
}

.slide-left-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.slide-left-leave-to {
  opacity: 0;
  transform: translateX(-30%);
}

/* 下滑进入 */
.slide-down-enter-active {
  transition: all 0.3s ease;
}

.slide-down-leave-active {
  transition: all 0.2s ease;
}

.slide-down-enter-from {
  opacity: 0;
  transform: translateY(-100%);
}

.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-100%);
}

/* 淡入上滑 */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.2s ease;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* 抖动动画 */
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-6px); }
  75% { transform: translateX(6px); }
}

.input-shake {
  animation: shake 0.3s ease-in-out;
}

/* ==================== 安全区域适配 ==================== */
@supports (padding: max(0px)) {
  .login-view {
    padding-left: max(20px, env(safe-area-inset-left));
    padding-right: max(20px, env(safe-area-inset-right));
  }
}
</style>
