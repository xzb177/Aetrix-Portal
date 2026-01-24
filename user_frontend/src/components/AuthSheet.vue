<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  User,
  Lock,
  Mail,
  Gift,
  Eye,
  EyeOff,
  MessageCircle,
  ArrowLeft,
  X,
} from 'lucide-vue-next'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { useAnalytics } from '@/composables/useAnalytics'
import axios from 'axios'
import BottomSheet from './ui/BottomSheet.vue'

interface Props {
  show?: boolean
}

interface Emits {
  (e: 'update:show', value: boolean): void
  (e: 'success'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const toast = useToast()
const analytics = useAnalytics()

// Telegram Widget 隐藏容器引用
const telegramWidgetHidden = ref<HTMLDivElement | null>(null)

// 视图状态：'select' | 'login' | 'register'
const viewState = ref<'select' | 'login' | 'register'>('select')

// Telegram 配置
const telegramConfig = ref({
  enabled: true,
  botUsername: '',
})

// 账号密码表单
const loginForm = reactive({
  account: '',
  password: '',
})

// 注册表单
const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  email: '',
  inviteCode: '',
})

// UI 状态
const showLoginPassword = ref(false)
const showRegisterPassword = ref(false)
const showConfirmPassword = ref(false)
const loading = ref(false)
const focusedField = ref<string | null>(null)

// 字段错误状态
const loginErrors = reactive({
  account: '',
  password: '',
})

const registerErrors = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  email: '',
})

// 抖动状态
const loginShakeStates = ref({
  account: false,
  password: false,
})

const registerShakeStates = ref({
  username: false,
  password: false,
  confirmPassword: false,
  email: false,
})

// 按钮禁用状态
const isLoginDisabled = computed(() => {
  return !loginForm.account || !loginForm.password || loading.value
})

const isRegisterDisabled = computed(() => {
  return (
    !registerForm.username ||
    !registerForm.password ||
    !registerForm.confirmPassword ||
    loading.value
  )
})

// 密码强度
const passwordStrength = computed(() => {
  const pwd = registerForm.password
  if (!pwd) return { level: 0, label: '', color: '' }

  let score = 0
  if (pwd.length >= 6) score++
  if (pwd.length >= 10) score++
  if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score++
  if (/\d/.test(pwd)) score++
  if (/[^a-zA-Z0-9]/.test(pwd)) score++

  if (score <= 2) return { level: 1, label: '弱', color: '#ef4444' }
  if (score === 3) return { level: 2, label: '中', color: '#f59e0b' }
  return { level: 3, label: '强', color: '#10b981' }
})

// 获取 Telegram 配置
const fetchTelegramConfig = async () => {
  try {
    const response = await axios.get('/api/settings/public/telegram-login')
    telegramConfig.value = {
      enabled: response.data.telegram_login_enabled ?? true,
      botUsername: response.data.telegram_login_bot_username || 'yunhaisese_bot',
    }
  } catch {
    // 失败时使用默认值
    telegramConfig.value = {
      enabled: true,
      botUsername: 'yunhaisese_bot',
    }
  }
}

// 埋点辅助函数
const trackEvent = (event: string, params: Record<string, any> = {}) => {
  analytics?.track(event, params)
}

// 切换视图
const switchView = (view: 'select' | 'login' | 'register') => {
  viewState.value = view
  trackEvent('auth_sheet_view_change', { view })
}

// 关闭 Sheet
const handleClose = (method: string) => {
  trackEvent('auth_sheet_close', { method, current_view: viewState.value })
  emit('update:show', false)
  // 重置视图
  setTimeout(() => {
    viewState.value = 'select'
    resetForms()
  }, 300)
}

// 打开 Sheet
const handleOpen = () => {
  trackEvent('auth_sheet_open', { source: 'home_page' })
}

// 重置表单
const resetForms = () => {
  loginForm.account = ''
  loginForm.password = ''
  registerForm.username = ''
  registerForm.password = ''
  registerForm.confirmPassword = ''
  registerForm.email = ''
  registerForm.inviteCode = ''

  Object.keys(loginErrors).forEach(key => {
    loginErrors[key as keyof typeof loginErrors] = ''
  })
  Object.keys(registerErrors).forEach(key => {
    registerErrors[key as keyof typeof registerErrors] = ''
  })
}

// 抖动动画
const triggerShake = (field: string, type: 'login' | 'register') => {
  if (type === 'login') {
    loginShakeStates.value[field as keyof typeof loginShakeStates.value] = true
    setTimeout(() => {
      loginShakeStates.value[field as keyof typeof loginShakeStates.value] = false
    }, 300)
  } else {
    registerShakeStates.value[field as keyof typeof registerShakeStates.value] = true
    setTimeout(() => {
      registerShakeStates.value[field as keyof typeof registerShakeStates.value] = false
    }, 300)
  }
}

// 账号密码登录
const validateLoginForm = (): boolean => {
  loginErrors.account = ''
  loginErrors.password = ''

  let isValid = true

  if (!loginForm.account.trim()) {
    loginErrors.account = '请输入用户名'
    isValid = false
  }

  if (!loginForm.password) {
    loginErrors.password = '请输入密码'
    isValid = false
  }

  return isValid
}

const handlePasswordLogin = async () => {
  if (!validateLoginForm()) {
    const errorField = loginErrors.account ? 'account' : 'password'
    triggerShake(errorField, 'login')
    return
  }

  loading.value = true
  trackEvent('password_login_submit', { method: 'password' })

  try {
    await userStore.login(loginForm.account, loginForm.password)
    toast.success('登录成功')
    trackEvent('auth_success', { method: 'password' })
    emit('success')
    emit('update:show', false)
  } catch (err: any) {
    const errorMsg = err.response?.data?.detail || '登录失败'
    handleLoginError(errorMsg)
    trackEvent('auth_error', {
      method: 'password',
      error_code: err.response?.status || 'unknown',
      error_message: errorMsg,
    })
  } finally {
    loading.value = false
  }
}

const handleLoginError = (errorMsg: string) => {
  // 更友好的错误提示
  let friendlyMsg = ''

  const errorMap: Record<string, string> = {
    '用户名或密码错误': '用户名或密码错误，请检查后重试',
    '账户已被禁用': '您的账户已被禁用，请联系客服',
    '不存在': '该用户不存在',
    'not found': '该用户不存在',
    'Network Error': '网络连接失败，请检查网络后重试',
    '500': '服务器繁忙，请稍后重试',
  }

  // 查找匹配的错误提示
  for (const [key, value] of Object.entries(errorMap)) {
    if (errorMsg.includes(key)) {
      friendlyMsg = value
      break
    }
  }

  // 默认错误消息
  if (!friendlyMsg) {
    friendlyMsg = errorMsg || '登录失败，请稍后重试'
  }

  // 根据错误类型显示在对应字段
  if (
    errorMsg.includes('用户') ||
    errorMsg.includes('不存在') ||
    errorMsg.includes('not found')
  ) {
    loginErrors.account = friendlyMsg
    triggerShake('account', 'login')
  } else if (errorMsg.includes('密码') || errorMsg.includes('密码错误')) {
    loginErrors.password = friendlyMsg
    triggerShake('password', 'login')
  } else {
    loginErrors.password = friendlyMsg
    triggerShake('password', 'login')
  }
}

// 注册
const validateRegisterForm = (): boolean => {
  Object.keys(registerErrors).forEach(key => {
    registerErrors[key as keyof typeof registerErrors] = ''
  })

  let isValid = true

  if (!registerForm.username.trim()) {
    registerErrors.username = '请输入用户名'
    isValid = false
  } else if (registerForm.username.length < 3) {
    registerErrors.username = '用户名至少需要 3 个字符'
    isValid = false
  } else if (!/^[a-zA-Z0-9_]+$/.test(registerForm.username)) {
    registerErrors.username = '用户名只能包含字母、数字和下划线'
    isValid = false
  }

  if (!registerForm.password) {
    registerErrors.password = '请输入密码'
    isValid = false
  } else if (registerForm.password.length < 6) {
    registerErrors.password = '密码至少需要 6 位字符'
    isValid = false
  }

  if (!registerForm.confirmPassword) {
    registerErrors.confirmPassword = '请确认密码'
    isValid = false
  } else if (registerForm.password !== registerForm.confirmPassword) {
    registerErrors.confirmPassword = '两次输入的密码不一致'
    isValid = false
  }

  if (registerForm.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(registerForm.email)) {
    registerErrors.email = '请输入有效的邮箱地址'
    isValid = false
  }

  return isValid
}

const handleRegister = async () => {
  if (!validateRegisterForm()) {
    const errorField = registerErrors.username
      ? 'username'
      : registerErrors.password
        ? 'password'
        : registerErrors.confirmPassword
          ? 'confirmPassword'
          : 'email'
    triggerShake(errorField, 'register')
    return
  }

  loading.value = true
  trackEvent('register_submit', { method: 'register' })

  try {
    await userStore.register(
      registerForm.username,
      registerForm.password,
      registerForm.email || undefined,
      registerForm.inviteCode || undefined
    )
    toast.success('注册成功')
    trackEvent('auth_success', { method: 'register' })
    emit('success')
    emit('update:show', false)
  } catch (err: any) {
    const errorMsg = err.response?.data?.detail || '注册失败'
    handleRegisterError(errorMsg)
    trackEvent('auth_error', {
      method: 'register',
      error_code: err.response?.status || 'unknown',
      error_message: errorMsg,
    })
  } finally {
    loading.value = false
  }
}

const handleRegisterError = (errorMsg: string) => {
  // 更友好的错误提示
  let friendlyMsg = ''

  const errorMap: Record<string, string> = {
    '用户名已存在': '该用户名已被注册，请更换',
    '已存在': '该用户名已被注册',
    'exists': '该用户名已被注册',
    '邀请码不存在': '邀请码无效，请检查后重试',
    '无效': '邀请码无效',
    'Network Error': '网络连接失败，请检查网络后重试',
  }

  // 查找匹配的错误提示
  for (const [key, value] of Object.entries(errorMap)) {
    if (errorMsg.includes(key)) {
      friendlyMsg = value
      break
    }
  }

  // 默认错误消息
  if (!friendlyMsg) {
    friendlyMsg = errorMsg || '注册失败，请稍后重试'
  }

  // 根据错误类型显示在对应字段
  if (errorMsg.includes('用户名') || errorMsg.includes('已存在') || errorMsg.includes('exists')) {
    registerErrors.username = friendlyMsg
    triggerShake('username', 'register')
  } else if (errorMsg.includes('邀请码') || errorMsg.includes('无效')) {
    registerErrors.username = friendlyMsg
    triggerShake('username', 'register')
  } else {
    registerErrors.password = friendlyMsg
    triggerShake('password', 'register')
  }
}

// 页面加载时
onMounted(() => {
  fetchTelegramConfig()

  // 检查 URL 中是否有邀请码
  const invite = route.query.invite as string
  if (invite) {
    registerForm.inviteCode = invite
  }
})

// Telegram 登录 - 直接跳转到 Telegram Bot
const handleTelegramLogin = () => {
  trackEvent('telegram_login_start', {
    bot_username: telegramConfig.value.botUsername,
  })

  if (!telegramConfig.value.botUsername) {
    console.error('[Telegram Login] Missing botUsername')
    toast.info('Telegram 登录暂不可用，请使用其他方式登录')
    return
  }

  // 保存重定向地址
  const redirect = route.query.redirect as string
  if (redirect) {
    sessionStorage.setItem('telegram_redirect', redirect)
  }

  // 直接跳转到 Telegram Bot
  const authUrl = `https://t.me/${telegramConfig.value.botUsername}?start=web_login`

  console.log('[Telegram Login] Redirecting to bot:', authUrl)

  // 关闭 Sheet 并跳转
  emit('update:show', false)
  window.location.href = authUrl
}

// 监听 show 变化，重置视图
watch(() => props.show, (newVal) => {
  if (newVal) {
    viewState.value = 'select'
    resetForms()
  }
})
</script>

<template>
  <BottomSheet
    :show="show"
    :show-close="false"
    :max-height="'90vh'"
    @update:show="emit('update:show', $event)"
    @close="handleClose($event)"
    @open="handleOpen"
  >
    <!-- ==================== 方式选择视图 ==================== -->
    <div v-if="viewState === 'select'" class="auth-select-view">
      <div class="select-header">
        <h2 class="select-title">选择登录方式</h2>
        <p class="select-subtitle">快速登录，开启观影之旅</p>
      </div>

      <div class="auth-buttons">
        <!-- Telegram 一键登录 -->
        <button
          v-if="telegramConfig.enabled"
          class="auth-btn auth-btn-telegram"
          @click="handleTelegramLogin"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" class="telegram-icon">
            <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.799-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.139-5.062 3.345-.479.329-.913.489-1.302.481-.428-.009-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.324-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.141.121.099.155.232.17.325.016.094.035.31.02.478z"/>
          </svg>
          <span>Telegram 一键登录</span>
          <span class="recommended-tag">推荐</span>
        </button>

        <!-- 隐藏的 Telegram Widget 用于获取回调 -->
        <div ref="telegramWidgetHidden" class="telegram-widget-hidden"></div>

        <!-- 辅助文案 -->
        <p v-if="telegramConfig.enabled" class="auth-hint">
          快速更安全，授权后自动创建/绑定账号
        </p>

        <!-- 分隔线 -->
        <div v-if="telegramConfig.enabled" class="auth-divider">
          <span class="divider-line"></span>
          <span class="divider-text">或</span>
          <span class="divider-line"></span>
        </div>

        <!-- 账号密码登录 -->
        <button class="auth-btn auth-btn-password" @click="switchView('login')">
          <User :size="18" class="btn-icon" />
          <span>账号密码登录</span>
        </button>

        <!-- 注册入口 -->
        <button class="auth-btn auth-btn-register" @click="switchView('register')">
          <User :size="18" class="btn-icon" />
          <span>注册新账号</span>
        </button>
      </div>

      <!-- 底部客服链接 -->
      <button class="support-link" @click="toast.info('请联系 Telegram 客服')">
        <MessageCircle :size="13" />
        <span>遇到问题？联系客服</span>
      </button>
    </div>

    <!-- ==================== 密码登录视图 ==================== -->
    <div v-else-if="viewState === 'login'" class="auth-form-view">
      <div class="auth-header">
        <div class="auth-header__side">
          <button class="auth-icon-btn" aria-label="Back" @click="switchView('select')">
            <ArrowLeft :size="20" />
          </button>
        </div>
        <h2 class="auth-header__title">账号密码登录</h2>
        <div class="auth-header__side">
          <button class="auth-icon-btn" aria-label="Close" @click="handleClose('button')">
            <X :size="20" />
          </button>
        </div>
      </div>

      <div class="form-content">
        <!-- 账号输入 -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'login-account',
              'input-error': loginErrors.account,
              'input-shake': loginShakeStates.account
            }"
          >
            <User :size="16" class="input-icon" />
            <input
              v-model="loginForm.account"
              type="text"
              placeholder="用户名"
              @focus="focusedField = 'login-account'"
              @blur="focusedField = null"
              @keyup.enter="handlePasswordLogin"
            />
          </div>
          <Transition name="fade-slide">
            <div v-if="loginErrors.account" class="error-message">
              {{ loginErrors.account }}
            </div>
          </Transition>
        </div>

        <!-- 密码输入 -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'login-password',
              'input-error': loginErrors.password,
              'input-shake': loginShakeStates.password
            }"
          >
            <Lock :size="16" class="input-icon" />
            <input
              v-model="loginForm.password"
              :type="showLoginPassword ? 'text' : 'password'"
              placeholder="密码"
              @focus="focusedField = 'login-password'"
              @blur="focusedField = null"
              @keyup.enter="handlePasswordLogin"
            />
            <button
              type="button"
              class="toggle-password"
              @click="showLoginPassword = !showLoginPassword"
            >
              <EyeOff v-if="showLoginPassword" :size="14" />
              <Eye v-else :size="14" />
            </button>
          </div>
        </div>

        <!-- 登录按钮 -->
        <button
          class="submit-btn"
          :class="{ 'submit-btn-disabled': isLoginDisabled }"
          :disabled="isLoginDisabled"
          @click="handlePasswordLogin"
        >
          <span v-if="loading" class="loading-spinner"></span>
          <span>{{ loading ? '登录中...' : '登 录' }}</span>
        </button>
      </div>
    </div>

    <!-- ==================== 注册视图 ==================== -->
    <div v-else-if="viewState === 'register'" class="auth-form-view">
      <div class="auth-header">
        <div class="auth-header__side">
          <button class="auth-icon-btn" aria-label="Back" @click="switchView('select')">
            <ArrowLeft :size="20" />
          </button>
        </div>
        <h2 class="auth-header__title">注册新账号</h2>
        <div class="auth-header__side">
          <button class="auth-icon-btn" aria-label="Close" @click="handleClose('button')">
            <X :size="20" />
          </button>
        </div>
      </div>

      <div class="form-content">
        <!-- 用户名 -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'reg-username',
              'input-error': registerErrors.username,
              'input-shake': registerShakeStates.username
            }"
          >
            <User :size="16" class="input-icon" />
            <input
              v-model="registerForm.username"
              type="text"
              placeholder="用户名"
              @focus="focusedField = 'reg-username'"
              @blur="focusedField = null"
            />
          </div>
          <Transition name="fade-slide">
            <div v-if="registerErrors.username" class="error-message">
              {{ registerErrors.username }}
            </div>
          </Transition>
        </div>

        <!-- 密码 -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'reg-password',
              'input-error': registerErrors.password,
              'input-shake': registerShakeStates.password
            }"
          >
            <Lock :size="16" class="input-icon" />
            <input
              v-model="registerForm.password"
              :type="showRegisterPassword ? 'text' : 'password'"
              placeholder="密码"
              @focus="focusedField = 'reg-password'"
              @blur="focusedField = null"
            />
            <button
              type="button"
              class="toggle-password"
              @click="showRegisterPassword = !showRegisterPassword"
            >
              <EyeOff v-if="showRegisterPassword" :size="14" />
              <Eye v-else :size="14" />
            </button>
          </div>
          <!-- 密码强度 -->
          <Transition name="fade-slide">
            <div v-if="registerForm.password && passwordStrength.level" class="password-strength">
              <div class="strength-bar">
                <div
                  class="strength-fill"
                  :class="`strength-${passwordStrength.level}`"
                  :style="{ width: passwordStrength.level * 33 + '%' }"
                ></div>
              </div>
              <span class="strength-label" :style="{ color: passwordStrength.color }">
                密码强度: {{ passwordStrength.label }}
              </span>
            </div>
          </Transition>
          <Transition name="fade-slide">
            <div v-if="registerErrors.password" class="error-message">
              {{ registerErrors.password }}
            </div>
          </Transition>
        </div>

        <!-- 确认密码 -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'reg-confirm',
              'input-error': registerErrors.confirmPassword,
              'input-shake': registerShakeStates.confirmPassword
            }"
          >
            <Lock :size="16" class="input-icon" />
            <input
              v-model="registerForm.confirmPassword"
              :type="showConfirmPassword ? 'text' : 'password'"
              placeholder="确认密码"
              @focus="focusedField = 'reg-confirm'"
              @blur="focusedField = null"
              @keyup.enter="handleRegister"
            />
            <button
              type="button"
              class="toggle-password"
              @click="showConfirmPassword = !showConfirmPassword"
            >
              <EyeOff v-if="showConfirmPassword" :size="14" />
              <Eye v-else :size="14" />
            </button>
          </div>
          <Transition name="fade-slide">
            <div v-if="registerErrors.confirmPassword" class="error-message">
              {{ registerErrors.confirmPassword }}
            </div>
          </Transition>
        </div>

        <!-- 邮箱（可选） -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'reg-email',
              'input-error': registerErrors.email,
              'input-shake': registerShakeStates.email
            }"
          >
            <Mail :size="16" class="input-icon" />
            <input
              v-model="registerForm.email"
              type="email"
              placeholder="邮箱（可选，用于找回密码）"
              @focus="focusedField = 'reg-email'"
              @blur="focusedField = null"
            />
          </div>
          <Transition name="fade-slide">
            <div v-if="registerErrors.email" class="error-message">
              {{ registerErrors.email }}
            </div>
          </Transition>
        </div>

        <!-- 邀请码（可选） -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{ 'input-focused': focusedField === 'reg-invite' }"
          >
            <Gift :size="16" class="input-icon" />
            <input
              v-model="registerForm.inviteCode"
              type="text"
              placeholder="邀请码（可选，可获得奖励）"
              @focus="focusedField = 'reg-invite'"
              @blur="focusedField = null"
            />
          </div>
        </div>

        <!-- 注册按钮 -->
        <button
          class="submit-btn"
          :class="{ 'submit-btn-disabled': isRegisterDisabled }"
          :disabled="isRegisterDisabled"
          @click="handleRegister"
        >
          <span v-if="loading" class="loading-spinner"></span>
          <span>{{ loading ? '注册中...' : '注 册' }}</span>
        </button>
      </div>
    </div>
  </BottomSheet>
</template>

<style scoped>
/* ==================== 方式选择视图 ==================== */
.auth-select-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-bottom: var(--space-sm, 12px);
}

.select-header {
  text-align: center;
  margin-bottom: var(--space-lg, 24px);
}

.select-title {
  font-size: var(--text-title-size, 20px);
  font-weight: var(--font-weight-semibold, 600);
  color: var(--text-title-color, #ffffff);
  margin: 0 0 var(--space-xs, 8px);
}

.select-subtitle {
  font-size: var(--text-caption-size, 12px);
  color: var(--text-caption-color, rgba(255, 255, 255, 0.5));
  margin: 0;
}

.auth-buttons {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-sm, 12px);
}

.auth-btn {
  width: 100%;
  height: var(--btn-height, 44px);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs, 8px);
  border: none;
  border-radius: var(--btn-radius, 12px);
  font-size: var(--text-body-size, 14px);
  font-weight: var(--font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--duration-fast, 150ms) ease;
  position: relative;
}

/* Telegram 按钮 */
.auth-btn-telegram {
  background: var(--btn-primary-bg, #10b981);
  color: var(--btn-primary-text, #ffffff);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

.auth-btn-telegram:active {
  transform: scale(0.98);
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3);
}

.telegram-icon {
  width: 20px;
  height: 20px;
}

.recommended-tag {
  position: absolute;
  right: var(--space-md, 16px);
  padding: 2px var(--space-xs, 8px);
  background: rgba(255, 255, 255, 0.2);
  border-radius: var(--radius-sm, 8px);
  font-size: var(--text-caption-size, 12px);
  font-weight: var(--font-weight-normal, 400);
}

/* 隐藏的 Telegram Widget */
.telegram-widget-hidden {
  display: none;
}

/* Telegram 登录按钮 */
.auth-btn-telegram {
  background: linear-gradient(135deg, #2AABEE 0%, #229ED9 100%);
  border: none;
  color: #ffffff;
  position: relative;
}

.auth-btn-telegram .telegram-icon {
  width: 20px;
  height: 20px;
}

.auth-btn-telegram:active {
  transform: scale(0.98);
  background: linear-gradient(135deg, #229ED9 0%, #1E8BC2 100%);
}

/* 辅助文案 */
.auth-hint {
  font-size: var(--text-caption-size, 12px);
  color: var(--text-caption-color, rgba(255, 255, 255, 0.4));
  text-align: center;
  margin: -var(--space-xs, 8px) 0 0;
}

/* 分隔线 */
.auth-divider {
  display: flex;
  align-items: center;
  gap: var(--space-xs, 8px);
  margin: var(--space-xs, 8px) 0 var(--space-xs, 4px);
}

.divider-line {
  flex: 1;
  height: 1px;
  background: var(--divider-color, rgba(255, 255, 255, 0.08));
}

.divider-text {
  font-size: var(--text-caption-size, 12px);
  color: var(--text-caption-color, rgba(255, 255, 255, 0.4));
  font-weight: var(--font-weight-normal, 400);
}

/* 密码登录按钮 */
.auth-btn-password {
  background: var(--btn-secondary-bg, rgba(255, 255, 255, 0.1));
  border: 1px solid var(--card-border, rgba(255, 255, 255, 0.1));
  color: var(--btn-secondary-text, #ffffff);
}

.auth-btn-password:active {
  transform: scale(0.98);
  background: var(--btn-secondary-bg-hover, rgba(255, 255, 255, 0.15));
}

.auth-btn-password .btn-icon {
  color: var(--text-tertiary, rgba(255, 255, 255, 0.5));
}

/* 注册按钮 */
.auth-btn-register {
  background: transparent;
  border: 1px dashed var(--card-border, rgba(255, 255, 255, 0.15));
  color: var(--text-secondary, rgba(255, 255, 255, 0.7));
  font-weight: var(--font-weight-normal, 400);
}

.auth-btn-register:active {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.25);
}

.auth-btn-register .btn-icon {
  color: var(--text-tertiary, rgba(255, 255, 255, 0.3));
}

/* 客服链接 */
.support-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs, 8px);
  margin-top: var(--space-lg, 24px);
  padding: var(--space-xs, 8px) var(--space-sm, 12px);
  background: transparent;
  border: none;
  color: var(--text-tertiary, rgba(255, 255, 255, 0.4));
  font-size: var(--text-caption-size, 12px);
  cursor: pointer;
  border-radius: var(--radius-sm, 8px);
  transition: all var(--duration-fast, 150ms) ease;
}

.support-link:active {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary, rgba(255, 255, 255, 0.6));
}

/* ==================== 表单视图 ==================== */
.auth-form-view {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* ==================== Auth Header ==================== */
.auth-header {
  /* 顶部安全区（iOS） */
  padding-top: env(safe-area-inset-top);
  height: calc(56px + env(safe-area-inset-top));
  display: flex;
  align-items: center;
  padding-left: 16px;
  padding-right: 16px;
  box-sizing: border-box;
}

/* 左右两侧等宽占位：避免标题被挤偏 */
.auth-header__side {
  width: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 标题区域：真正居中 */
.auth-header__title {
  flex: 1;
  text-align: center;
  font-size: var(--text-subtitle-size, 16px);
  font-weight: var(--font-weight-semibold, 600);
  color: var(--text-subtitle-color, #ffffff);
  margin: 0;
}

/* 统一按钮容器和点击热区 */
.auth-icon-btn {
  width: 44px;
  height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md, 12px);
  background: transparent;
  border: none;
  color: var(--text-secondary, rgba(255, 255, 255, 0.6));
  cursor: pointer;
  transition: all var(--duration-fast, 150ms) ease;
}

.auth-icon-btn:active {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary, #fafafa);
}

/* 图标统一尺寸 */
.auth-icon-btn svg {
  width: 20px;
  height: 20px;
  display: block;
}

.form-content {
  flex: 1;
  display: flex;
  flex-direction: column;
}

/* 输入组 */
.input-group {
  display: flex;
  flex-direction: column;
  margin-bottom: var(--space-sm, 12px);
}

.input-field {
  display: flex;
  align-items: center;
  height: var(--btn-height, 44px);
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  border-radius: var(--radius-md, 12px);
  padding: 0 var(--space-sm, 12px);
  transition: all var(--duration-normal, 200ms) ease;
}

.input-field.input-focused {
  border-color: var(--border-focus, #10b981);
  background: rgba(0, 0, 0, 0.3);
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.15);
}

.input-field.input-error {
  border-color: var(--border-error, #ef4444);
  background: rgba(239, 68, 68, 0.1);
}

.input-icon {
  color: var(--text-quaternary, rgba(255, 255, 255, 0.3));
  margin-right: var(--space-xs, 8px);
  flex-shrink: 0;
  transition: color var(--duration-fast, 150ms) ease;
}

.input-field.input-focused .input-icon {
  color: var(--border-focus, #10b981);
}

.input-field.input-error .input-icon {
  color: var(--border-error, #ef4444);
}

.input-field input {
  flex: 1;
  height: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary, #fafafa);
  font-size: var(--text-body-size, 14px);
}

.input-field input::placeholder {
  color: var(--text-quaternary, rgba(255, 255, 255, 0.3));
}

.toggle-password {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-quaternary, rgba(255, 255, 255, 0.3));
  cursor: pointer;
  border-radius: var(--radius-sm, 6px);
  margin: -6px -6px -6px 0;
  transition: all var(--duration-fast, 150ms) ease;
}

.toggle-password:active {
  background: rgba(255, 255, 255, 0.05);
}

/* 错误提示 */
.error-message {
  display: flex;
  align-items: center;
  padding: var(--space-xs, 8px) 0;
  color: #ef4444;
  font-size: var(--text-caption-size, 12px);
  line-height: 1.4;
}

/* 密码强度 */
.password-strength {
  display: flex;
  align-items: center;
  gap: var(--space-xs, 8px);
  padding: var(--space-xs, 8px) 0;
}

.strength-bar {
  flex: 1;
  height: 3px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.strength-fill {
  height: 100%;
  border-radius: 2px;
  transition: all 0.3s ease;
}

.strength-fill.strength-1 {
  background: #ef4444;
}

.strength-fill.strength-2 {
  background: #f59e0b;
}

.strength-fill.strength-3 {
  background: #10b981;
}

.strength-label {
  font-size: var(--text-caption-size, 12px);
  font-weight: var(--font-weight-medium, 500);
  white-space: nowrap;
}

/* 提交按钮 */
.submit-btn {
  margin-top: var(--space-sm, 12px);
  height: var(--btn-height, 44px);
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border: none;
  border-radius: var(--btn-radius, 12px);
  color: #ffffff;
  font-size: var(--text-body-size, 14px);
  font-weight: var(--font-weight-medium, 500);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs, 8px);
  cursor: pointer;
  transition: all var(--duration-normal, 200ms) ease;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

.submit-btn:active:not(.submit-btn-disabled) {
  transform: scale(0.98);
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3);
}

.submit-btn-disabled {
  opacity: 0.4;
  cursor: not-allowed;
  background: rgba(255, 255, 255, 0.05);
  box-shadow: none;
}

/* Loading Spinner */
.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 动画 ==================== */
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
</style>
