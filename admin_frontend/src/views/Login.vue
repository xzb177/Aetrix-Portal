<script setup lang="ts">
/** 管理员登录页：JWT 登录 → 恢复 ?redirect 或进入概览 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loader2, Lock, ShieldCheck, User } from 'lucide-vue-next'
import { login } from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
// 人机验证（能力：人机验证）：管理员开了「保护管理后台登录」时才会渲染
import CaptchaChallenge from '@/components/CaptchaChallenge.vue'
// 站名与 Logo 来自「站点与品牌」能力（未配置时用默认值）
import { branding, initBranding } from '@/composables/branding'

void initBranding()

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const error = ref('')
const captchaToken = ref('')
const captchaRef = ref<InstanceType<typeof CaptchaChallenge> | null>(null)

async function submit() {
  if (!form.username || !form.password) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await login({
      username: form.username,
      password: form.password,
      captcha_token: captchaToken.value || undefined,
    })
    auth.setSession(res.access_token, res.user)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败'
    // 令牌一次性：失败后换一个新的，否则第二次点击会因「已使用」而失败
    captchaRef.value?.reset()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-glow" aria-hidden="true" />

    <div class="login-card">
      <div class="login-brand">
        <span class="brand-mark">
          <img v-if="branding.logo_url" :src="branding.logo_url" :alt="branding.site_name" />
        </span>
        <h1>{{ branding.site_name }} 控制台</h1>
        <p>运营管理后台 · 仅限管理员账号登录</p>
      </div>

      <!-- 门户（用户端）已登录时的免登结果：能自动进就直接进，不能进也要说明原因 -->
      <p v-if="auth.ssoNotice" class="login-hint">{{ auth.ssoNotice }}</p>

      <form @submit.prevent="submit">
        <label class="field">
          <span class="field-label"><User :size="14" /> 用户名</span>
          <input v-model="form.username" type="text" autocomplete="username" placeholder="管理员用户名" />
        </label>
        <label class="field">
          <span class="field-label"><Lock :size="14" /> 密码</span>
          <input v-model="form.password" type="password" autocomplete="current-password" placeholder="登录密码" />
        </label>

        <CaptchaChallenge ref="captchaRef" @update:token="captchaToken = $event" />

        <div v-if="error" class="login-error">{{ error }}</div>

        <button class="login-btn" type="submit" :disabled="loading">
          <Loader2 v-if="loading" :size="16" class="spinning" />
          <span>{{ loading ? '登录中…' : '登录' }}</span>
        </button>
      </form>

      <p class="login-foot"><ShieldCheck :size="13" /> 登录状态保存在本地，操作会记入管理日志</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  overflow: hidden;
}

.login-glow {
  position: absolute;
  inset: -20% -10% auto -10%;
  height: 70vh;
  background:
    radial-gradient(ellipse 50% 60% at 30% 0%, rgba(34, 211, 238, 0.16), transparent 65%),
    radial-gradient(ellipse 45% 55% at 78% 12%, rgba(167, 139, 250, 0.14), transparent 65%);
  pointer-events: none;
}

.login-card {
  position: relative;
  width: 100%;
  max-width: 390px;
  background: linear-gradient(180deg, rgba(16, 26, 40, 0.92), rgba(10, 16, 26, 0.92));
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 34px 28px 26px;
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(14px);
}

.login-hint {
  font-size: 12.5px;
  color: var(--text-secondary);
  background: var(--bg-input);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  margin: 0 0 16px;
}

.login-brand { text-align: center; margin-bottom: 26px; }
.login-brand h1 { font-size: 20px; margin: 14px 0 6px; letter-spacing: -0.01em; }
.login-brand p { font-size: 12.5px; color: var(--text-secondary); margin: 0; }

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 12px;
  background: var(--gradient-brand);
  box-shadow: var(--shadow-glow);
  overflow: hidden;
}

.brand-mark img { width: 100%; height: 100%; object-fit: contain; }

.field { display: block; margin-bottom: 16px; }

.field-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.field input {
  width: 100%;
  box-sizing: border-box;
  padding: 11px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 14px;
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.field input::placeholder { color: var(--text-muted); }

.field input:focus {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.12);
}

.login-error {
  display: flex;
  align-items: center;
  font-size: 13px;
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid rgba(251, 113, 133, 0.28);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  margin-bottom: 14px;
}

.login-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--gradient-brand);
  color: var(--primary-on);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: filter var(--transition-fast), transform var(--transition-fast);
}

.login-btn:hover:not(:disabled) { background: var(--gradient-brand-hover); }
.login-btn:active:not(:disabled) { transform: scale(0.99); }
.login-btn:disabled { opacity: 0.65; cursor: not-allowed; }

.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.login-foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-muted);
  margin: 18px 0 0;
}

/* 手机：卡片少一点内边距，键盘弹起时不被顶出屏幕 */
@media (max-width: 480px) {
  .login-page { padding: 14px; align-items: flex-start; padding-top: max(28px, env(safe-area-inset-top)); }
  .login-card { padding: 26px 20px 20px; }
  .login-brand h1 { font-size: 18px; }
}
</style>
