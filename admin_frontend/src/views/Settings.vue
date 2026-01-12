<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { LogOut, Lock, Shield, Info, Key, Eye, EyeOff } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const apiUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080'

const passwordForm = ref({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const showPassword = ref({
  old: false,
  new: false,
  confirm: false,
})

const submitting = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error' | 'warning' | 'info'>('success')
const showToast = ref(false)

const showToastMessage = (message: string, type: 'success' | 'error' | 'warning' | 'info' = 'success') => {
  toastMessage.value = message
  toastType.value = type
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

const handleChangePassword = async () => {
  if (passwordForm.value.new_password !== passwordForm.value.confirm_password) {
    showToastMessage('两次输入的密码不一致', 'error')
    return
  }

  if (passwordForm.value.new_password.length < 6) {
    showToastMessage('新密码长度不能少于6位', 'error')
    return
  }

  submitting.value = true
  try {
    const { changePassword } = await import('@/api')
    await changePassword({
      old_password: passwordForm.value.old_password,
      new_password: passwordForm.value.new_password,
    })
    showToastMessage('密码修改成功，请重新登录', 'success')
    setTimeout(() => {
      authStore.logout()
      router.push('/login')
    }, 1500)
  } catch (error: any) {
    console.error('修改密码失败:', error)
    showToastMessage(error?.response?.data?.detail || '修改失败，请检查原密码', 'error')
  } finally {
    submitting.value = false
  }
}

const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="settings-page">
    <div class="settings-grid">
      <!-- 修改密码 -->
      <div class="card password-card">
        <div class="card-header">
          <Key :size="18" class="card-icon" />
          <span class="card-title">修改密码</span>
        </div>

        <div class="password-form">
          <div class="form-group">
            <label class="form-label">当前密码</label>
            <div class="input-wrapper">
              <Lock :size="18" class="input-icon" />
              <input
                v-model="passwordForm.old_password"
                :type="showPassword.old ? 'text' : 'password'"
                placeholder="请输入当前密码"
                class="input input-with-icon input-with-icon-right"
              />
              <button
                type="button"
                class="input-icon-right"
                @click="showPassword.old = !showPassword.old"
              >
                <EyeOff v-if="showPassword.old" :size="18" />
                <Eye v-else :size="18" />
              </button>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">新密码</label>
            <div class="input-wrapper">
              <Lock :size="18" class="input-icon" />
              <input
                v-model="passwordForm.new_password"
                :type="showPassword.new ? 'text' : 'password'"
                placeholder="请输入新密码（至少6位）"
                class="input input-with-icon input-with-icon-right"
              />
              <button
                type="button"
                class="input-icon-right"
                @click="showPassword.new = !showPassword.new"
              >
                <EyeOff v-if="showPassword.new" :size="18" />
                <Eye v-else :size="18" />
              </button>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">确认密码</label>
            <div class="input-wrapper">
              <Shield :size="18" class="input-icon" />
              <input
                v-model="passwordForm.confirm_password"
                :type="showPassword.confirm ? 'text' : 'password'"
                placeholder="请再次输入新密码"
                class="input input-with-icon input-with-icon-right"
              />
              <button
                type="button"
                class="input-icon-right"
                @click="showPassword.confirm = !showPassword.confirm"
              >
                <EyeOff v-if="showPassword.confirm" :size="18" />
                <Eye v-else :size="18" />
              </button>
            </div>
          </div>

          <button
            class="btn-primary submit-btn"
            @click="handleChangePassword"
            :disabled="submitting"
          >
            <span v-if="submitting" class="loading-spinner mr-2"></span>
            <Lock :size="18" v-else class="mr-2" />
            修改密码
          </button>
        </div>
      </div>

      <!-- 右侧卡片组 -->
      <div class="settings-sidebar">
        <!-- 账号信息 -->
        <div class="card info-card">
          <div class="card-header">
            <Shield :size="18" class="card-icon" />
            <span class="card-title">账号信息</span>
          </div>

          <div class="info-list">
            <div class="info-row">
              <span class="info-label">用户名</span>
              <span class="info-value">{{ authStore.adminInfo?.username }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">角色</span>
              <span class="tag tag-success">{{ authStore.adminInfo?.role_display }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">权限数量</span>
              <span class="info-value">{{ authStore.adminInfo?.permissions.length }} 项</span>
            </div>
            <div class="info-row">
              <span class="info-label">最后登录</span>
              <span class="info-value-last">{{ authStore.adminInfo?.last_login || '首次登录' }}</span>
            </div>
          </div>

          <button class="btn-secondary logout-btn" @click="handleLogout">
            <LogOut :size="18" class="mr-2" />
            退出登录
          </button>
        </div>

        <!-- 系统信息 -->
        <div class="card info-card">
          <div class="card-header">
            <Info :size="18" class="card-icon-blue" />
            <span class="card-title">系统信息</span>
          </div>

          <div class="info-list">
            <div class="info-row">
              <span class="info-label">系统名称</span>
              <span class="info-value">Aetrix Emby 管理系统</span>
            </div>
            <div class="info-row">
              <span class="info-label">版本</span>
              <span class="info-value">v5.2.0</span>
            </div>
            <div class="info-row">
              <span class="info-label">后端API</span>
              <span class="info-value-api">{{ apiUrl }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Toast 提示 -->
    <Transition
      enter-active-class="transition-all duration-300"
      enter-from-class="opacity-0 translate-x-4"
      enter-to-class="opacity-100 translate-x-0"
      leave-active-class="transition-all duration-300"
      leave-from-class="opacity-100 translate-x-0"
      leave-to-class="opacity-0 translate-x-4"
    >
      <div
        v-if="showToast"
        :class="['toast', `toast-${toastType}`]"
      >
        <span class="text-xl">{{ toastType === 'success' ? '✓' : toastType === 'error' ? '✕' : 'ℹ' }}</span>
        <span>{{ toastMessage }}</span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ==================== Page Layout ==================== */
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* ==================== Settings Grid ==================== */
.settings-grid {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 1.5rem;
}

@media (max-width: 1024px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}

/* ==================== Card Styles ==================== */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  padding: 1.5rem;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.card-icon {
  color: var(--text-muted);
}

.card-icon-blue {
  color: #3b82f6;
}

.card-title {
  font-weight: 600;
  color: var(--text-primary);
}

/* ==================== Password Card ==================== */
.password-card {
  height: fit-content;
}

.password-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.input-wrapper {
  position: relative;
}

.input-with-icon {
  padding-left: 2.75rem;
}

.input-with-icon-right {
  padding-right: 2.75rem;
}

.input-icon {
  position: absolute;
  left: 1rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
}

.input-icon-right {
  position: absolute;
  right: 1rem;
  top: 50%;
  transform: translateY(-50%);
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.input-icon-right:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.submit-btn {
  width: 100%;
  margin-top: 0.5rem;
}

.mr-2 {
  margin-right: 0.5rem;
}

/* ==================== Info Card ==================== */
.settings-sidebar {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.info-card {
  display: flex;
  flex-direction: column;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  flex: 1;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--border-color);
}

.info-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.info-label {
  font-size: 0.875rem;
  color: var(--text-muted);
}

.info-value {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.info-value-last {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.info-value-api {
  font-size: 0.8125rem;
  font-family: 'Courier New', monospace;
  color: var(--text-secondary);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.logout-btn {
  width: 100%;
  margin-top: 1.5rem;
}

/* ==================== Mobile Responsive ==================== */
@media (max-width: 640px) {
  .page-title {
    font-size: 1.25rem;
  }

  .card {
    padding: 1.25rem;
  }

  .info-value-api {
    max-width: 150px;
  }
}
</style>
