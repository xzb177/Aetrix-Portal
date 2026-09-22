<script setup lang="ts">
/**
 * 登录 / 注册 — 全页认证视图
 *
 * 统一后端 JWT 认证：
 * - POST /api/user/auth/login     登录（access + refresh token）
 * - POST /api/user/auth/register  注册（自动生成自建 Emby 凭据）
 *
 * 登录成功后自动跳转 ?redirect= 指定的受保护页面。
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { User, Lock, Mail, Eye, EyeOff, Clapperboard, Ticket, Gift } from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const toast = useToast()

const mode = ref<'login' | 'register'>('login')

const loginForm = reactive({ username: '', password: '' })
// 注册码 / 邀请码：此前只有从带参链接进来（?code= / ?invite=）才拿得到，表单里
// 根本没有输入框——站点开成「卡码注册」时，从首页点进来的用户只会看到
// 「当前注册需要注册码」却无处可填。现在两个都能手填，链接进来自动预填。
const registerForm = reactive({
  username: '', password: '', confirmPassword: '', email: '',
  registrationCode: '', inviteCode: '',
})

const showLoginPassword = ref(false)
const showRegisterPassword = ref(false)
const loading = ref(false)
const error = ref('')

const passwordStrength = computed(() => {
  const pwd = registerForm.password
  if (!pwd) return 0
  let score = 0
  if (pwd.length >= 6) score++
  if (pwd.length >= 10) score++
  if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score++
  if (/\d/.test(pwd)) score++
  if (/[^a-zA-Z0-9]/.test(pwd)) score++
  return Math.min(score, 3)
})

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}

function friendlyError(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail || err?.message || ''
  if (typeof detail === 'string' && detail) return detail
  return fallback
}

async function handleLogin() {
  if (!loginForm.username || !loginForm.password) {
    error.value = '请输入用户名和密码'
    return
  }
  error.value = ''
  loading.value = true
  try {
    await userStore.login(loginForm.username.trim(), loginForm.password)
    toast.success('登录成功')
    router.push((route.query.redirect as string) || '/')
  } catch (err) {
    error.value = friendlyError(err, '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  const f = registerForm
  if (!f.username || !f.password || !f.confirmPassword) {
    error.value = '请完整填写注册信息'
    return
  }
  if (f.username.length < 3 || f.username.length > 32 || !/^[a-zA-Z0-9_]+$/.test(f.username)) {
    error.value = '用户名需 3-32 位，仅限字母、数字、下划线'
    return
  }
  if (f.password.length < 6) {
    error.value = '密码至少 6 位'
    return
  }
  if (f.password !== f.confirmPassword) {
    error.value = '两次输入的密码不一致'
    return
  }
  error.value = ''
  loading.value = true
  try {
    // 表单里填的优先；没填时沿用链接带来的
    const inviteCode = f.inviteCode.trim() || (route.query.invite as string) || ''
    const regCode = f.registrationCode.trim() || (route.query.code as string) || ''
    await userStore.register(
      f.username.trim(), f.password, f.email || undefined,
      inviteCode || undefined, regCode || undefined,
    )
    toast.success('注册成功，已自动开通观影账号')
    router.push((route.query.redirect as string) || '/')
  } catch (err) {
    error.value = friendlyError(err, '注册失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (route.query.mode === 'register') mode.value = 'register'
  // 邀请链接 ?invite=CODE：自动切到注册页、预填邀请码并提示
  if (route.query.invite) {
    mode.value = 'register'
    registerForm.inviteCode = String(route.query.invite)
    toast.info(`已收到好友邀请码，注册成功后双方都得积分奖励`, 5000)
  }
  // 卡码链接 ?code=XXX：同样预填，用户不用再手抄一遍
  if (route.query.code) {
    mode.value = 'register'
    registerForm.registrationCode = String(route.query.code)
  }
})
</script>

<template>
  <div class="auth-page">
    <!-- 背景装饰 -->
    <div class="auth-glow" aria-hidden="true"></div>
    <div class="auth-grid" aria-hidden="true"></div>

    <div class="auth-card">
      <div class="auth-brand">
        <div class="brand-mark">
          <Clapperboard :size="22" />
        </div>
        <h1 class="brand-title">Aetrix 私藏影诺</h1>
        <p class="brand-subtitle">自建 Emby 影视服务 · 一个账号畅享所有设备</p>
      </div>

      <!-- 模式切换 -->
      <div class="mode-switch" role="tablist">
        <button
          class="mode-btn"
          :class="{ active: mode === 'login' }"
          role="tab"
          :aria-selected="mode === 'login'"
          @click="mode = 'login'"
        >
          登录
        </button>
        <button
          class="mode-btn"
          :class="{ active: mode === 'register' }"
          role="tab"
          :aria-selected="mode === 'register'"
          @click="mode = 'register'"
        >
          注册
        </button>
        <div class="mode-indicator" :class="{ right: mode === 'register' }"></div>
      </div>

      <!-- 登录表单 -->
      <form v-if="mode === 'login'" class="auth-form" @submit.prevent="handleLogin">
        <label class="field">
          <span class="field-label">用户名</span>
          <div class="field-box">
            <User :size="16" class="field-icon" />
            <input
              v-model="loginForm.username"
              type="text"
              name="username"
              autocomplete="username"
              placeholder="输入用户名"
              @keyup.enter="handleLogin"
            />
          </div>
        </label>

        <label class="field">
          <span class="field-label">密码</span>
          <div class="field-box">
            <Lock :size="16" class="field-icon" />
            <input
              v-model="loginForm.password"
              :type="showLoginPassword ? 'text' : 'password'"
              name="password"
              autocomplete="current-password"
              placeholder="输入密码"
              @keyup.enter="handleLogin"
            />
            <button type="button" class="eye-btn" @click="showLoginPassword = !showLoginPassword">
              <EyeOff v-if="showLoginPassword" :size="15" />
              <Eye v-else :size="15" />
            </button>
          </div>
        </label>

        <p v-if="error" class="form-error">{{ error }}</p>

        <button type="submit" class="submit-btn" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '登录中…' : '登 录' }}
        </button>
      </form>

      <!-- 注册表单 -->
      <form v-else class="auth-form" @submit.prevent="handleRegister">
        <label class="field">
          <span class="field-label">用户名</span>
          <div class="field-box">
            <User :size="16" class="field-icon" />
            <input
              v-model="registerForm.username"
              type="text"
              name="username"
              autocomplete="username"
              placeholder="3-32 位字母、数字、下划线"
              @keyup.enter="handleRegister"
            />
          </div>
        </label>

        <label class="field">
          <span class="field-label">密码</span>
          <div class="field-box">
            <Lock :size="16" class="field-icon" />
            <input
              v-model="registerForm.password"
              :type="showRegisterPassword ? 'text' : 'password'"
              name="new-password"
              autocomplete="new-password"
              placeholder="至少 6 位"
              @keyup.enter="handleRegister"
            />
            <button type="button" class="eye-btn" @click="showRegisterPassword = !showRegisterPassword">
              <EyeOff v-if="showRegisterPassword" :size="15" />
              <Eye v-else :size="15" />
            </button>
          </div>
          <div v-if="registerForm.password" class="strength">
            <div class="strength-track">
              <div class="strength-fill" :class="`lv-${passwordStrength}`"></div>
            </div>
            <span class="strength-text">{{ ['弱', '中', '强'][passwordStrength - 1] || '' }}</span>
          </div>
        </label>

        <label class="field">
          <span class="field-label">确认密码</span>
          <div class="field-box">
            <Lock :size="16" class="field-icon" />
            <input
              v-model="registerForm.confirmPassword"
              type="password"
              name="confirm-password"
              autocomplete="new-password"
              placeholder="再次输入密码"
              @keyup.enter="handleRegister"
            />
          </div>
        </label>

        <label class="field">
          <span class="field-label">邮箱 <em class="optional">选填</em></span>
          <div class="field-box">
            <Mail :size="16" class="field-icon" />
            <input
              v-model="registerForm.email"
              type="email"
              name="email"
              autocomplete="email"
              placeholder="用于找回密码"
              @keyup.enter="handleRegister"
            />
          </div>
        </label>

        <label class="field">
          <span class="field-label">注册码 <em class="optional">站点要求时填写</em></span>
          <div class="field-box">
            <Ticket :size="16" class="field-icon" />
            <input
              v-model="registerForm.registrationCode"
              type="text"
              name="registration-code"
              placeholder="开放注册时可留空"
              @keyup.enter="handleRegister"
            />
          </div>
        </label>

        <label class="field">
          <span class="field-label">邀请码 <em class="optional">选填，双方得积分</em></span>
          <div class="field-box">
            <Gift :size="16" class="field-icon" />
            <input
              v-model="registerForm.inviteCode"
              type="text"
              name="invite-code"
              placeholder="好友的邀请码"
              @keyup.enter="handleRegister"
            />
          </div>
        </label>

        <p v-if="error" class="form-error">{{ error }}</p>

        <button type="submit" class="submit-btn" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '注册中…' : '注 册' }}
        </button>
      </form>

      <p class="auth-footnote">
        注册即代表同意服务条款 · 密码经 bcrypt 加密存储
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  position: relative;
  overflow: hidden;
  background: var(--au-bg);
}

.auth-glow {
  position: absolute;
  top: -20%;
  left: 50%;
  transform: translateX(-50%);
  width: 640px;
  height: 480px;
  background: radial-gradient(ellipse at center, var(--au-primary-soft) 0%, transparent 65%);
  filter: blur(40px);
  pointer-events: none;
}

.auth-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(var(--au-grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--au-grid-line) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse 70% 60% at 50% 40%, black 30%, transparent 75%);
  pointer-events: none;
}

.auth-card {
  position: relative;
  width: 100%;
  max-width: 400px;
  background: var(--au-overlay-menu);
  border: 1px solid var(--au-border);
  border-radius: 20px;
  padding: 2rem 1.75rem 1.5rem;
  box-shadow: var(--au-shadow-2);
  animation: cardIn 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes cardIn {
  from { opacity: 0; transform: translateY(16px) scale(0.98); }
  to { opacity: 1; transform: none; }
}

.auth-brand {
  text-align: center;
  margin-bottom: 1.5rem;
}

.brand-mark {
  width: 46px;
  height: 46px;
  margin: 0 auto 0.875rem;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--au-primary);
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  box-shadow: var(--au-shadow-glow);
}

.brand-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--au-text);
  margin: 0 0 0.375rem;
}

.brand-subtitle {
  font-size: 0.8125rem;
  color: var(--au-text-3);
  margin: 0;
  line-height: 1.5;
}

/* 模式切换 */
.mode-switch {
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 12px;
  padding: 4px;
  margin-bottom: 1.25rem;
}

.mode-btn {
  position: relative;
  z-index: 1;
  padding: 0.5rem;
  border: none;
  background: transparent;
  border-radius: 9px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--au-text-3);
  cursor: pointer;
  transition: color 0.2s ease;
}

.mode-btn.active {
  color: var(--au-on-primary);
  font-weight: 600;
}

.mode-indicator {
  position: absolute;
  top: 4px;
  left: 4px;
  width: calc(50% - 4px);
  height: calc(100% - 8px);
  border-radius: 9px;
  background: var(--au-primary);
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.mode-indicator.right {
  transform: translateX(100%);
}

/* 表单 */
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.field-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--au-text-3);
}

.optional {
  font-style: normal;
  color: var(--au-text-4);
}

.field-box {
  display: flex;
  align-items: center;
  height: 44px;
  background: var(--au-overlay-soft);
  border: 1px solid var(--au-border);
  border-radius: 11px;
  padding: 0 0.75rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.field-box:focus-within {
  border-color: var(--au-border-focus);
  box-shadow: 0 0 0 3px var(--au-primary-soft);
}

.field-icon {
  color: var(--au-text-4);
  margin-right: 0.5rem;
  flex-shrink: 0;
}

.field-box:focus-within .field-icon {
  color: var(--au-primary);
}

.field-box input {
  flex: 1;
  min-width: 0;
  height: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: var(--au-text);
  font-size: 0.875rem;
}

.field-box input::placeholder {
  color: var(--au-text-4);
}

.eye-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--au-text-4);
  cursor: pointer;
  border-radius: 7px;
}

.eye-btn:hover {
  color: var(--au-text-2);
}

/* 密码强度 */
.strength {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.125rem;
}

.strength-track {
  flex: 1;
  height: 3px;
  background: var(--au-surface-2);
  border-radius: 2px;
  overflow: hidden;
}

.strength-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease, background 0.3s ease;
  width: 0;
}

.strength-fill.lv-1 { width: 33%; background: var(--au-danger); }
.strength-fill.lv-2 { width: 66%; background: var(--au-warning); }
.strength-fill.lv-3 { width: 100%; background: var(--au-primary); }

.strength-text {
  font-size: 0.6875rem;
  color: var(--au-text-3);
  min-width: 16px;
}

/* 错误提示 */
.form-error {
  margin: 0;
  padding: 0.5rem 0.75rem;
  border-radius: 9px;
  background: var(--au-danger-soft);
  border: 1px solid var(--au-danger-border);
  color: var(--au-danger);
  font-size: 0.8125rem;
  line-height: 1.4;
}

/* 提交按钮 */
.submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  height: 46px;
  margin-top: 0.25rem;
  background: var(--au-gradient);
  border: none;
  border-radius: 12px;
  color: var(--au-on-primary);
  font-size: 0.9375rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.2s ease, opacity 0.2s ease;
  box-shadow: 0 4px 16px var(--au-primary-glow);
}

.submit-btn:hover:not(:disabled) {
  box-shadow: 0 6px 20px var(--au-primary-glow);
}

.submit-btn:active:not(:disabled) {
  transform: scale(0.98);
}

.submit-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.spinner {
  width: 15px;
  height: 15px;
  border: 2px solid var(--au-on-image-strong);
  border-top-color: var(--au-text);
  border-radius: 50%;
  animation: au-spin 0.8s linear infinite;
}

.auth-footnote {
  margin: 1.25rem 0 0;
  text-align: center;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  line-height: 1.5;
}

@media (max-width: 480px) {
  .auth-card {
    padding: 1.5rem 1.25rem 1.25rem;
    border-radius: 16px;
  }
}
</style>
