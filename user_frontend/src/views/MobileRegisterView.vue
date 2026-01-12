<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Eye, EyeOff, User, Lock, Mail, Gift } from 'lucide-vue-next'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const toast = useToast()

// 注册表单
const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  email: '',
  inviteCode: '',
})

// UI 状态
const showPassword = ref(false)
const showConfirmPassword = ref(false)
const loading = ref(false)
const focusedField = ref<string | null>(null)

// 字段错误状态
const fieldErrors = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  email: '',
})

// 按钮禁用状态
const isRegisterDisabled = computed(() => {
  return !form.username || !form.password || !form.confirmPassword || loading.value
})

// 页面加载时检查邀请码
onMounted(() => {
  const invite = route.query.invite as string
  if (invite) {
    form.inviteCode = invite
  }
})

// 验证表单
const validateForm = (): boolean => {
  // 清空之前的错误
  Object.keys(fieldErrors).forEach(key => {
    fieldErrors[key as keyof typeof fieldErrors] = ''
  })

  let isValid = true

  // 验证用户名
  if (!form.username.trim()) {
    fieldErrors.username = '请输入用户名'
    isValid = false
  } else if (form.username.length < 3) {
    fieldErrors.username = '用户名至少需要 3 个字符'
    isValid = false
  } else if (!/^[a-zA-Z0-9_]+$/.test(form.username)) {
    fieldErrors.username = '用户名只能包含字母、数字和下划线'
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

  // 验证确认密码
  if (!form.confirmPassword) {
    fieldErrors.confirmPassword = '请确认密码'
    isValid = false
  } else if (form.password !== form.confirmPassword) {
    fieldErrors.confirmPassword = '两次输入的密码不一致'
    isValid = false
  }

  // 验证邮箱（可选）
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    fieldErrors.email = '请输入有效的邮箱地址'
    isValid = false
  }

  return isValid
}

// 处理注册
const handleRegister = async () => {
  if (!validateForm()) {
    const errorField = fieldErrors.username ? 'username' :
                      fieldErrors.password ? 'password' :
                      fieldErrors.confirmPassword ? 'confirmPassword' : 'email'
    triggerShake(errorField)
    return
  }

  loading.value = true

  try {
    await userStore.register(
      form.username,
      form.password,
      form.email || undefined,
      form.inviteCode || undefined
    )
    toast.success('注册成功')
    const redirect = route.query.redirect as string || '/'
    router.replace(redirect)
  } catch (err: any) {
    const errorMsg = err.response?.data?.detail || '注册失败'
    handleRegisterError(errorMsg)
  } finally {
    loading.value = false
  }
}

// 处理注册错误
const handleRegisterError = (errorMsg: string) => {
  if (errorMsg.includes('用户名') || errorMsg.includes('已存在')) {
    fieldErrors.username = '该用户名已被注册'
    triggerShake('username')
  } else if (errorMsg.includes('邀请码') || errorMsg.includes('无效')) {
    fieldErrors.username = '邀请码无效'
    triggerShake('username')
  } else {
    fieldErrors.password = errorMsg
    triggerShake('password')
  }
}

// 抖动动画
const shakeStates = ref({
  username: false,
  password: false,
  confirmPassword: false,
  email: false,
})

const triggerShake = (field: 'username' | 'password' | 'confirmPassword' | 'email') => {
  shakeStates.value[field] = true
  setTimeout(() => {
    shakeStates.value[field] = false
  }, 300)
}

// 导航操作
const goBack = () => {
  router.back()
}

const goToLogin = () => {
  router.push({ name: 'home', query: route.query })
}

// 密码强度指示
const passwordStrength = computed(() => {
  const pwd = form.password
  if (!pwd) return { level: 0, label: '', color: '' }

  let score = 0
  if (pwd.length >= 6) score++
  if (pwd.length >= 10) score++
  if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score++
  if (/\d/.test(pwd)) score++
  if (/[^a-zA-Z0-9]/.test(pwd)) score++

  if (score <= 2) return { level: 1, label: '弱', color: '#EF4444' }
  if (score === 3) return { level: 2, label: '中', color: '#F59E0B' }
  return { level: 3, label: '强', color: '#10b981' }
})
</script>

<template>
  <div class="mobile-register-page">
    <!-- 导航栏 -->
    <div class="nav-header">
      <button class="nav-back" @click="goBack">
        <ArrowLeft :size="24" />
      </button>
      <span class="nav-title">注册账号</span>
      <div class="nav-placeholder"></div>
    </div>

    <!-- 注册表单 -->
    <div class="register-content">
      <!-- 欢迎标题 -->
      <div class="register-header">
        <h2 class="register-title">创建新账号</h2>
        <p class="register-subtitle">加入 Aetrix，开启 4K 影视之旅</p>
      </div>

      <!-- 表单 -->
      <div class="register-form">
        <!-- 用户名 -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'username',
              'input-error': fieldErrors.username,
              'input-shake': shakeStates.username
            }"
          >
            <User :size="20" class="input-icon" />
            <input
              v-model="form.username"
              type="text"
              placeholder="用户名"
              @focus="focusedField = 'username'"
              @blur="focusedField = null"
            />
          </div>
          <Transition name="fade-slide">
            <div v-if="fieldErrors.username" class="error-message">
              {{ fieldErrors.username }}
            </div>
          </Transition>
        </div>

        <!-- 密码 -->
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
          <!-- 密码强度指示 -->
          <Transition name="fade-slide">
            <div v-if="form.password && passwordStrength.level" class="password-strength">
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
            <div v-if="fieldErrors.password" class="error-message">
              {{ fieldErrors.password }}
            </div>
          </Transition>
        </div>

        <!-- 确认密码 -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'confirmPassword',
              'input-error': fieldErrors.confirmPassword,
              'input-shake': shakeStates.confirmPassword
            }"
          >
            <Lock :size="20" class="input-icon" />
            <input
              v-model="form.confirmPassword"
              :type="showConfirmPassword ? 'text' : 'password'"
              placeholder="确认密码"
              @focus="focusedField = 'confirmPassword'"
              @blur="focusedField = null"
              @keyup.enter="handleRegister"
            />
            <button
              type="button"
              class="toggle-password"
              @click="showConfirmPassword = !showConfirmPassword"
            >
              <EyeOff v-if="showConfirmPassword" :size="18" />
              <Eye v-else :size="18" />
            </button>
          </div>
          <Transition name="fade-slide">
            <div v-if="fieldErrors.confirmPassword" class="error-message">
              {{ fieldErrors.confirmPassword }}
            </div>
          </Transition>
        </div>

        <!-- 邮箱（可选） -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{
              'input-focused': focusedField === 'email',
              'input-error': fieldErrors.email,
              'input-shake': shakeStates.email
            }"
          >
            <Mail :size="20" class="input-icon" />
            <input
              v-model="form.email"
              type="email"
              placeholder="邮箱（可选，用于找回密码）"
              @focus="focusedField = 'email'"
              @blur="focusedField = null"
            />
          </div>
          <Transition name="fade-slide">
            <div v-if="fieldErrors.email" class="error-message">
              {{ fieldErrors.email }}
            </div>
          </Transition>
        </div>

        <!-- 邀请码（可选） -->
        <div class="input-group">
          <div
            class="input-field"
            :class="{ 'input-focused': focusedField === 'inviteCode' }"
          >
            <Gift :size="20" class="input-icon" />
            <input
              v-model="form.inviteCode"
              type="text"
              placeholder="邀请码（可选，可获得奖励）"
              @focus="focusedField = 'inviteCode'"
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

      <!-- 底部链接 -->
      <div class="register-footer">
        <span class="footer-text">已有账号？</span>
        <button class="footer-link" @click="goToLogin">立即登录</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 页面容器 ==================== */
.mobile-register-page {
  min-height: 100vh;
  min-height: 100dvh;
  background: linear-gradient(180deg, #0F0F1A 0%, #1A1A2E 100%);
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.mobile-register-page::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(
    circle at 30% 10%,
    rgba(16, 185, 129, 0.1) 0%,
    transparent 50%
  );
  pointer-events: none;
}

/* ==================== 导航栏 ==================== */
.nav-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: max(44px, env(safe-area-inset-top) + 44px);
  padding: 0 20px;
  padding-top: env(safe-area-inset-top));
  position: relative;
  z-index: 1;
}

.nav-back {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-primary, #fafafa);
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
  color: var(--text-primary, #fafafa);
}

.nav-placeholder {
  width: 44px;
}

/* ==================== 注册内容 ==================== */
.register-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 20px;
  padding-bottom: max(20px, env(safe-area-inset-bottom));
  position: relative;
  z-index: 1;
  overflow-y: auto;
}

/* 注册头部 */
.register-header {
  margin-bottom: 24px;
}

.register-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary, #fafafa);
  margin-bottom: 8px;
}

.register-subtitle {
  font-size: 14px;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
}

/* 表单 */
.register-form {
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
  border-color: #10b981;
  background: rgba(0, 0, 0, 0.3);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.15);
}

.input-field.input-error {
  border-color: #EF4444;
  background: rgba(239, 68, 68, 0.1);
}

.input-icon {
  color: var(--text-tertiary, rgba(250, 250, 250, 0.4));
  margin-right: 12px;
  flex-shrink: 0;
  transition: color 0.2s ease;
}

.input-field.input-focused .input-icon {
  color: #10b981;
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
  color: var(--text-primary, #fafafa);
  font-size: 16px;
}

.input-field input::placeholder {
  color: var(--text-tertiary, rgba(250, 250, 250, 0.4));
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
  color: var(--text-tertiary, rgba(250, 250, 250, 0.4));
  cursor: pointer;
  border-radius: 8px;
  margin: -6px -8px -6px 0;
  transition: all 0.2s ease;
}

.toggle-password:active {
  background: rgba(255, 255, 255, 0.05);
}

/* 密码强度指示 */
.password-strength {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 4px;
}

.strength-bar {
  flex: 1;
  height: 4px;
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
  background: #EF4444;
}

.strength-fill.strength-2 {
  background: #F59E0B;
}

.strength-fill.strength-3 {
  background: #10b981;
}

.strength-label {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

/* 错误提示 */
.error-message {
  display: flex;
  align-items: center;
  padding: 6px 4px;
  color: #EF4444;
  font-size: 13px;
  line-height: 1.4;
}

/* 提交按钮 */
.submit-btn {
  margin-top: 12px;
  height: 48px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
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
  box-shadow: 0 4px 16px rgba(16, 185, 129, 0.3);
}

.submit-btn:active:not(.submit-btn-disabled) {
  transform: scale(0.97);
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
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

/* 底部链接 */
.register-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
  margin-top: 24px;
  padding-top: 24px;
}

.footer-text {
  font-size: 14px;
  color: var(--text-secondary, rgba(250, 250, 250, 0.6));
}

.footer-link {
  background: transparent;
  border: none;
  color: #10b981;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
}

.footer-link:active {
  opacity: 0.7;
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

/* ==================== 安全区域适配 ==================== */
@supports (padding: max(0px)) {
  .register-content {
    padding-left: max(20px, env(safe-area-inset-left));
    padding-right: max(20px, env(safe-area-inset-right));
  }
}
</style>
