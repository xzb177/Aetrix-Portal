<script setup lang="ts">
/** 管理员登录页：JWT 登录 → 恢复 ?redirect 或进入概览 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from 'lucide-vue-next'
import { login } from '@/api/admin'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const error = ref('')

async function submit() {
  if (!form.username || !form.password) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await login({ username: form.username, password: form.password })
    auth.setSession(res.access_token, res.user)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <span class="brand-dot" />
        <h1>RoyalBot 管理后台</h1>
        <p>仅限管理员账号登录</p>
      </div>

      <form @submit.prevent="submit">
        <label class="field">
          <span class="field-label"><User :size="14" /> 用户名</span>
          <input v-model="form.username" type="text" autocomplete="username" placeholder="管理员用户名" />
        </label>
        <label class="field">
          <span class="field-label"><Lock :size="14" /> 密码</span>
          <input v-model="form.password" type="password" autocomplete="current-password" placeholder="登录密码" />
        </label>

        <div v-if="error" class="login-error">{{ error }}</div>

        <button class="login-btn" type="submit" :disabled="loading">
          {{ loading ? '登录中…' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(ellipse 60% 40% at 50% 0%, rgba(16, 185, 129, 0.08), transparent),
    var(--color-bg-primary, #0a0a0a);
  padding: 20px;
}

.login-card {
  width: 100%;
  max-width: 380px;
  background: var(--color-bg-card, #1a1a1a);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 20px;
  padding: 32px 28px;
}

.login-brand { text-align: center; margin-bottom: 28px; }
.login-brand h1 { font-size: 20px; margin: 12px 0 4px; }
.login-brand p { font-size: 13px; color: var(--color-text-secondary, #a3a3a3); margin: 0; }

.brand-dot {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 16px rgba(16, 185, 129, 0.7);
}

.field { display: block; margin-bottom: 16px; }
.field-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-secondary, #a3a3a3);
  margin-bottom: 6px;
}

.field input {
  width: 100%;
  box-sizing: border-box;
  padding: 11px 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #fff;
  font-size: 14px;
  outline: none;
  transition: border-color 0.15s ease;
}

.field input:focus { border-color: rgba(16, 185, 129, 0.5); }

.login-error {
  font-size: 13px;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 14px;
}

.login-btn {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.login-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
