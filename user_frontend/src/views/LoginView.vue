<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { User, Lock, AlertCircle, Gift, Play, ArrowRight, Eye, EyeOff } from 'lucide-vue-next'
import BrandIcon from '@/components/BrandIcon.vue'
import axios from 'axios'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const toast = useToast()

const isLogin = computed(() => route.query.mode !== 'register')
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const email = ref('')
const inviteCode = ref('')
const loading = ref(false)
const error = ref('')

// Telegram Bot 配置
const telegramConfig = ref({
  enabled: true,
  botUsername: '',
})

// 获取 Telegram 登录配置
const fetchTelegramConfig = async () => {
  try {
    const response = await axios.get('/api/settings/public/telegram-login')
    telegramConfig.value = {
      enabled: response.data.telegram_login_enabled ?? true,
      botUsername: response.data.telegram_login_bot_username || 'yunhaisese_bot',
    }
  } catch (err) {
    // 失败时使用默认值
    telegramConfig.value = {
      enabled: true,
      botUsername: 'yunhaisese_bot',
    }
  }
}

// 页面加载时检查邀请码和获取配置
onMounted(async () => {
  await fetchTelegramConfig()

  const invite = route.query.invite as string
  if (invite) {
    inviteCode.value = invite
    // 自动切换到注册模式
    if (isLogin.value) {
      toggleMode()
    }
  }
})

async function handleSubmit() {
  error.value = ''
  loading.value = true

  try {
    if (isLogin.value) {
      await userStore.login(username.value, password.value)
      toast.success('登录成功')
    } else {
      await userStore.register(username.value, password.value, email.value, inviteCode.value)
      toast.success('注册成功')
    }

    const redirect = route.query.redirect as string || '/'
    router.push(redirect)
  } catch (err: any) {
    let errorMsg = err.response?.data?.detail
    if (Array.isArray(errorMsg)) {
      errorMsg = errorMsg[0]?.msg || errorMsg[0]?.detail || '请求参数错误'
    } else if (typeof errorMsg === 'object') {
      errorMsg = errorMsg.msg || errorMsg.detail || '请求失败'
    }
    error.value = errorMsg || (isLogin.value ? '登录失败，请检查用户名和密码' : '注册失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function toggleMode() {
  const query = { ...route.query }
  if (isLogin.value) {
    query.mode = 'register'
  } else {
    delete query.mode
  }
  router.push({ name: 'login', query })
}

function goToRegister() {
  router.push({ name: 'register' })
}

function handleTelegramLogin() {
  // 确保使用正确的 Bot 用户名
  const botUsername = telegramConfig.value.botUsername || 'yunhaisese_bot'

  // 调试：显示弹窗
  alert(`正在跳转到 Telegram Bot...\n\nBot: @${botUsername}`)

  const redirect = route.query.redirect as string
  if (redirect) {
    sessionStorage.setItem('telegram_redirect', redirect)
  }

  const authUrl = `https://t.me/${botUsername}?start=web_login`
  window.location.href = authUrl
}
</script>

<template>
  <div class="login-page">
    <div class="login-container">
      <!-- Logo & 服务说明 -->
      <div class="logo-section">
        <BrandIcon :size="40" />
        <h1 class="logo-title">Aetrix</h1>
        <p class="logo-subtitle">Emby 影视账号订阅服务 · 4K 超清 · 多设备共享</p>
      </div>

      <!-- 登录方式卡片（只在登录模式显示） -->
      <div v-if="isLogin && !route.query.mode" class="login-methods">
        <button @click="handleTelegramLogin" class="method-card telegram">
          <div class="method-icon telegram-icon">
            <svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.799-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.139-5.062 3.345-.479.329-.913.489-1.302.481-.428-.009-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.324-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.141.121.099.155.232.17.325.016.094.035.31.02.478z"/>
            </svg>
          </div>
          <div class="method-content">
            <span class="method-title">Telegram 登录</span>
            <span class="method-desc">快速安全，推荐使用</span>
          </div>
          <div class="method-badge">推荐</div>
        </button>

        <button @click="toggleMode" class="method-card account">
          <div class="method-icon account-icon">
            <User :size="24" />
          </div>
          <div class="method-content">
            <span class="method-title">账号登录</span>
            <span class="method-desc">使用用户名密码登录</span>
          </div>
        </button>

        <button @click="goToRegister" class="method-card register">
          <div class="method-icon register-icon">
            <svg xmlns="http://www.w3.org/2000/svg" :width="24" :height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
              <circle cx="8.5" cy="7" r="4"></circle>
              <line x1="20" y1="8" x2="20" y2="14"></line>
              <line x1="23" y1="11" x2="17" y2="11"></line>
            </svg>
          </div>
          <div class="method-content">
            <span class="method-title">账号注册</span>
            <span class="method-desc">创建新账号开始使用</span>
          </div>
        </button>
      </div>

      <!-- 表单卡片 -->
      <div v-else class="card glass-card form-card">
        <!-- 返回按钮 -->
        <button v-if="route.query.method" @click="router.replace({ query: {} })" class="btn-back">
          <ArrowRight :size="18" />
          返回
        </button>

        <h2 class="form-title">
          {{ isLogin ? '登录账号' : '创建账号' }}
        </h2>

        <!-- Error Message -->
        <div v-if="error" class="error-message">
          <AlertCircle :size="16" />
          <span>{{ error }}</span>
        </div>

        <!-- Form -->
        <form @submit.prevent="handleSubmit" class="form">
          <div class="form-group">
            <label class="form-label">用户名</label>
            <div class="input-wrapper">
              <User class="input-icon" :size="18" />
              <input
                v-model="username"
                type="text"
                required
                class="input"
                placeholder="请输入用户名"
                autocomplete="username"
              />
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">密码</label>
            <div class="input-wrapper">
              <Lock class="input-icon" :size="18" />
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                required
                class="input"
                placeholder="请输入密码"
                autocomplete="current-password"
              />
              <button
                type="button"
                @click="showPassword = !showPassword"
                class="input-action"
              >
                <Eye v-if="!showPassword" :size="16" />
                <EyeOff v-else :size="16" />
              </button>
            </div>
          </div>

          <div v-if="!isLogin" class="form-group">
            <label class="form-label">邮箱（可选）</label>
            <input
              v-model="email"
              type="email"
              class="input"
              placeholder="用于找回密码"
            />
          </div>

          <div v-if="!isLogin" class="form-group">
            <label class="form-label">
              <span class="flex items-center gap-1">
                <Gift :size="14" />
                邀请码（可选）
              </span>
            </label>
            <input
              v-model="inviteCode"
              type="text"
              class="input"
              placeholder="使用邀请码注册可获得奖励"
            />
          </div>

          <!-- 提交按钮 -->
          <button
            type="submit"
            :disabled="loading"
            class="btn btn-primary btn-submit"
          >
            <span v-if="loading" class="spinner"></span>
            {{ loading ? '处理中...' : (isLogin ? '登录' : '注册') }}
          </button>
        </form>

        <!-- 底部切换 -->
        <div class="form-footer">
          <span class="footer-text">
            {{ isLogin ? '还没有账号？' : '已有账号？' }}
          </span>
          <button type="button" @click="toggleMode" class="footer-link">
            {{ isLogin ? '立即注册' : '立即登录' }}
          </button>
        </div>

        <!-- Divider -->
        <div class="divider">
          <span class="divider-line"></span>
          <span class="divider-text">或</span>
          <span class="divider-line"></span>
        </div>

        <!-- Telegram 登录 -->
        <button
          type="button"
          @click="handleTelegramLogin"
          class="btn btn-telegram"
        >
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.799-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.139-5.062 3.345-.479.329-.913.489-1.302.481-.428-.009-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.324-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.141.121.099.155.232.17.325.016.094.035.31.02.478z"/>
          </svg>
          <span>使用 Telegram 登录</span>
        </button>
      </div>

      <!-- 服务说明 -->
      <div class="service-notice">
        <p>遇到问题？<a href="https://t.me/oceancloudembygroup" target="_blank">联系客服</a></p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: transparent;
}

.login-container {
  width: 100%;
  max-width: 400px;
}

/* Logo 区域 */
.logo-section {
  text-align: center;
  margin-bottom: 2rem;
}

.logo-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text-primary, #fafafa);
  margin-bottom: 0.5rem;
}

.logo-subtitle {
  font-size: 0.875rem;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
}

/* 登录方式卡片 */
.login-methods {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.method-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: var(--bg-elevated, #141414);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  border-radius: var(--radius-md, 10px);
  cursor: pointer;
  transition: all var(--duration-normal, 200ms) ease;
  text-align: left;
}

.method-card:active {
  transform: scale(0.98);
  background: var(--bg-elevated-hover, #1a1a1a);
}

.method-card.telegram {
  border-color: rgba(16, 185, 129, 0.3);
}

.method-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm, 6px);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.telegram-icon {
  background: rgba(16, 185, 129, 0.15);
  color: var(--brand-500, #10b981);
}

.account-icon {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-secondary, rgba(250, 250, 250, 0.7));
}

.register-icon {
  background: rgba(16, 185, 129, 0.15);
  color: var(--brand-500, #10b981);
}

.method-card.register {
  border-color: rgba(16, 185, 129, 0.2);
}

.method-content {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.method-title {
  font-weight: 500;
  color: var(--text-primary, #fafafa);
  font-size: 0.9375rem;
}

.method-desc {
  font-size: 0.75rem;
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
}

.method-badge {
  padding: 0.25rem 0.5rem;
  background: var(--brand-500, #10b981);
  color: white;
  font-size: 0.6875rem;
  font-weight: 500;
  border-radius: var(--radius-full, 9999px);
}

/* 表单卡片 */
.form-card {
  position: relative;
  padding: 1.5rem;
}

.btn-back {
  position: absolute;
  top: 1rem;
  left: 1rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.5rem;
  background: transparent;
  border: none;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
  cursor: pointer;
  font-size: 0.875rem;
}

.btn-back:active {
  color: var(--text-primary, #fafafa);
}

.form-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary, #fafafa);
  text-align: center;
  margin-bottom: 1.5rem;
}

/* 错误消息 */
.error-message {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  color: var(--color-danger, #ef4444);
  font-size: 0.875rem;
  background: var(--color-danger-bg, rgba(239, 68, 68, 0.1));
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: var(--radius-sm, 6px);
}

/* 表单 */
.form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary, rgba(250, 250, 250, 0.7));
}

.input-wrapper {
  position: relative;
}

.input-icon {
  position: absolute;
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
  pointer-events: none;
}

.input-action {
  position: absolute;
  right: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  padding: 0.25rem;
  background: transparent;
  border: none;
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
  cursor: pointer;
  display: flex;
  align-items: center;
}

.input-action:active {
  color: var(--text-primary, #fafafa);
}

.input {
  width: 100%;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  border-radius: var(--radius-sm, 6px);
  color: var(--text-primary, #fafafa);
  font-size: 0.9375rem;
  transition: all 0.2s ease;
  outline: none;
}

.input::placeholder {
  color: var(--text-quaternary, rgba(250, 250, 250, 0.3));
}

.input:focus {
  border-color: var(--brand-500, #10b981);
  box-shadow: 0 0 0 2px var(--brand-primary-light, rgba(16, 185, 129, 0.15));
}

.input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-wrapper .input {
  padding-left: 2.75rem;
}

/* 按钮 */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  border-radius: var(--radius-sm, 6px);
  font-size: 0.9375rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
  width: 100%;
}

.btn-primary {
  background: var(--brand-500, #10b981);
  color: white;
}

.btn-primary:hover {
  background: var(--brand-600, #059669);
}

.btn-primary:active {
  transform: scale(0.96);
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-submit {
  margin-top: 0.5rem;
  height: 48px;
}

.btn-telegram {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary, #fafafa);
}

.btn-telegram:active {
  background: rgba(255, 255, 255, 0.15);
  transform: scale(0.98);
}

.spinner {
  display: inline-block;
  width: 1rem;
  height: 1rem;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 底部 */
.form-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 0.25rem;
  margin-top: 1rem;
  font-size: 0.875rem;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.footer-text {
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
}

.footer-link {
  background: none;
  border: none;
  color: var(--brand-500, #10b981);
  font-weight: 500;
  cursor: pointer;
  padding: 0;
  white-space: nowrap;
}

.footer-link:active {
  opacity: 0.8;
}

/* Divider */
.divider {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin: 1.5rem 0;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: var(--border-default, rgba(255, 255, 255, 0.12));
}

.divider-text {
  font-size: 0.875rem;
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
}

/* 服务说明 */
.service-notice {
  text-align: center;
  margin-top: 1.5rem;
}

.service-notice p {
  font-size: 0.8125rem;
  color: var(--text-tertiary, rgba(250, 250, 250, 0.5));
}

.service-notice a {
  color: var(--brand-500, #10b981);
  text-decoration: none;
}

.service-notice a:active {
  opacity: 0.8;
}
</style>
