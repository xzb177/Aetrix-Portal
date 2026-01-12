<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock, Eye, EyeOff } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { login } from '@/api'
import type { LoginForm } from '@/types/auth'

const router = useRouter()
const authStore = useAuthStore()

const form = reactive<LoginForm>({
  username: 'admin',
  password: '',
})

const loading = ref(false)
const showPassword = ref(false)
const errorMsg = ref('')
const focusedField = ref<string | null>(null)

const handleLogin = async () => {
  if (!form.username || !form.password) {
    errorMsg.value = '请输入用户名和密码'
    return
  }

  loading.value = true
  errorMsg.value = ''

  try {
    const res = await login(form)
    // 安全改进: 使用 httpOnly Cookie 存储 Token，不再手动设置 token
    // 只保存 admin_info 和 csrf_token
    authStore.setAdminInfo(res.admin_info, res.csrf_token)
    router.push('/')
  } catch (error: any) {
    errorMsg.value = error?.response?.data?.detail || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <!-- 左侧品牌区 -->
    <div class="brand-section">
      <!-- 背景图形装饰 -->
      <div class="brand-bg">
        <div class="gradient-orb gradient-orb-1"></div>
        <div class="gradient-orb gradient-orb-2"></div>
        <div class="gradient-orb gradient-orb-3"></div>
        <div class="grid-pattern"></div>
      </div>

      <!-- 品牌内容 -->
      <div class="brand-content">
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h1 class="brand-title">Aetrix</h1>
        <p class="brand-subtitle">Emby 媒体服务器管理平台</p>

        <!-- 特性列表 -->
        <div class="feature-list">
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
            </div>
            <span>多服务器管理</span>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
            </div>
            <span>用户权限管理</span>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <span>安全认证系统</span>
          </div>
        </div>
      </div>

      <!-- 底部波浪 -->
      <div class="wave-divider">
        <svg viewBox="0 0 1200 120" preserveAspectRatio="none">
          <path d="M321.39,56.44c58-10.79,114.16-30.13,172-41.86,82.39-16.72,168.19-17.73,250.45-.39C823.78,31,906.67,72,985.66,92.83c70.05,18.48,146.53,26.09,214.34,3V0H0V27.35A600.21,600.21,0,0,0,321.39,56.44Z"></path>
        </svg>
      </div>
    </div>

    <!-- 右侧登录区 -->
    <div class="login-section">
      <div class="login-container">
        <div class="login-header">
          <h2>欢迎回来</h2>
          <p>请登录您的管理员账号以继续</p>
        </div>

        <form @submit.prevent="handleLogin" class="login-form">
          <!-- 用户名 -->
          <div class="form-field">
            <label>用户名</label>
            <div class="input-box" :class="{ 'input-box-focused': focusedField === 'username', 'input-box-error': errorMsg }">
              <User :size="20" class="input-icon" />
              <input
                v-model="form.username"
                type="text"
                placeholder="请输入用户名"
                @focus="focusedField = 'username'"
                @blur="focusedField = null"
              />
            </div>
          </div>

          <!-- 密码 -->
          <div class="form-field">
            <label>密码</label>
            <div class="input-box" :class="{ 'input-box-focused': focusedField === 'password', 'input-box-error': errorMsg }">
              <Lock :size="20" class="input-icon" />
              <input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="请输入密码"
                @focus="focusedField = 'password'"
                @blur="focusedField = null"
                @keyup.enter="handleLogin"
              />
              <button type="button" class="toggle-password" @click="showPassword = !showPassword">
                <EyeOff v-if="showPassword" :size="18" />
                <Eye v-else :size="18" />
              </button>
            </div>
          </div>

          <!-- 错误提示 -->
          <Transition name="slide-down">
            <div v-if="errorMsg" class="error-box">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
              {{ errorMsg }}
            </div>
          </Transition>

          <!-- 登录按钮 -->
          <button type="submit" class="login-btn" :disabled="loading">
            <span v-if="loading" class="spinner"></span>
            <span>{{ loading ? '登录中...' : '登录' }}</span>
          </button>
        </form>

        <!-- 底部信息 -->
        <div class="login-footer">
          <p>© 2026 Aetrix. All rights reserved.</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 布局 - 统一暗色玻璃态 ==================== */
.login-page {
  min-height: 100vh;
  display: flex;
  background: #0a0a0a;
}

/* ==================== 左侧品牌区 ==================== */
.brand-section {
  position: relative;
  width: 55%;
  max-width: 800px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 3rem;
  overflow: hidden;
}

.brand-bg {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, #4CAF50 0%, #45a049 50%, #673AB7 100%);
  overflow: hidden;
}

/* 渐变光球 */
.gradient-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.6;
}

.gradient-orb-1 {
  width: 400px;
  height: 400px;
  top: -100px;
  left: -100px;
  background: radial-gradient(circle, rgba(255,255,255,0.3) 0%, transparent 70%);
}

.gradient-orb-2 {
  width: 300px;
  height: 300px;
  bottom: 20%;
  right: -50px;
  background: radial-gradient(circle, rgba(103, 58, 183, 0.5) 0%, transparent 70%);
}

.gradient-orb-3 {
  width: 250px;
  height: 250px;
  top: 40%;
  left: 30%;
  background: radial-gradient(circle, rgba(76, 175, 80, 0.4) 0%, transparent 70%);
}

/* 网格图案 */
.grid-pattern {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px);
  background-size: 40px 40px;
}

.brand-content {
  position: relative;
  z-index: 1;
  color: white;
  max-width: 420px;
}

.brand-logo {
  width: 80px;
  height: 80px;
  background: rgba(255,255,255,0.15);
  backdrop-filter: blur(20px);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1.5rem;
  border: 1px solid rgba(255,255,255,0.2);
}

.brand-logo svg {
  width: 40px;
  height: 40px;
}

.brand-title {
  font-size: 3rem;
  font-weight: 800;
  margin-bottom: 0.5rem;
  letter-spacing: -0.02em;
}

.brand-subtitle {
  font-size: 1.125rem;
  opacity: 0.9;
  margin-bottom: 3rem;
  font-weight: 300;
}

/* 特性列表 */
.feature-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: rgba(255,255,255,0.1);
  backdrop-filter: blur(10px);
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.15);
}

.feature-icon {
  width: 40px;
  height: 40px;
  background: rgba(255,255,255,0.15);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.feature-item span {
  font-size: 0.95rem;
  font-weight: 500;
}

/* 波浪分隔 */
.wave-divider {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  line-height: 0;
}

.wave-divider svg {
  width: 100%;
  height: 60px;
  fill: #0a0a0a;
}

/* ==================== 右侧登录区 - 暗色玻璃态 ==================== */
.login-section {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3rem;
  background: #0a0a0a;
}

.login-container {
  width: 100%;
  max-width: 400px;
}

.login-header {
  margin-bottom: 2.5rem;
}

.login-header h2 {
  font-size: 2rem;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 0.5rem;
}

.login-header p {
  color: #737373;
  font-size: 0.95rem;
}

/* 表单 */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-field label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #ffffff;
}

.input-box {
  position: relative;
  display: flex;
  align-items: center;
  padding: 0 1rem;
  height: 50px;
  background: rgba(38, 38, 38, 0.8);
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  transition: all 0.2s ease;
}

.input-box:focus-within,
.input-box-focused {
  border-color: #4CAF50;
  background: rgba(26, 26, 26, 0.8);
  box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.15);
}

.input-box-error {
  border-color: #ef4444;
}

.input-icon {
  color: #737373;
  flex-shrink: 0;
}

.input-box input {
  flex: 1;
  height: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: #ffffff;
  font-size: 0.95rem;
  padding: 0 0.75rem;
}

.input-box input::placeholder {
  color: #737373;
}

.toggle-password {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #737373;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.toggle-password:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #ffffff;
}

/* 错误提示 */
.error-box {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 10px;
  color: #ef4444;
  font-size: 0.875rem;
}

.error-box svg {
  flex-shrink: 0;
  color: #ef4444;
}

/* 登录按钮 */
.login-btn {
  position: relative;
  height: 52px;
  background: linear-gradient(135deg, #4CAF50 0%, #673AB7 100%);
  border: none;
  border-radius: 12px;
  color: white;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  box-shadow: 0 4px 15px rgba(76, 175, 80, 0.3);
}

.login-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(76, 175, 80, 0.4);
}

.login-btn:active:not(:disabled) {
  transform: translateY(0);
}

.login-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 底部 */
.login-footer {
  margin-top: 2.5rem;
  text-align: center;
}

.login-footer p {
  font-size: 0.8rem;
  color: #737373;
}

/* 过渡动画 */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* ==================== 响应式 ==================== */
@media (max-width: 1024px) {
  .brand-section {
    display: none;
  }

  .login-section {
    padding: 2rem;
  }
}

@media (max-width: 640px) {
  .login-section {
    padding: 1.5rem;
  }

  .brand-title {
    font-size: 2rem;
  }

  .login-header h2 {
    font-size: 1.5rem;
  }
}
</style>
