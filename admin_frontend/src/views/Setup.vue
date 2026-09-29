<script setup lang="ts">
/**
 * 首次运行向导：全新部署建第一个管理员。
 * 进 /admin/ 时路由守卫已确认 setup_completed 为 false 才放行到这里；
 * 页面加载时再向后端确认一次（已完成则直接去登录页）。
 * 成功后跳登录页（?initialized=1），向导入口永久关闭。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CheckCircle2, KeyRound, Loader2, ShieldCheck, User, Wand2 } from 'lucide-vue-next'
import { createFirstAdmin, setupStatus } from '@/api/admin'
import { branding, initBranding } from '@/composables/branding'

void initBranding()

const router = useRouter()

const form = reactive({ username: '', password: '', confirm: '' })
const checking = ref(true)
const submitting = ref(false)
const error = ref('')
const done = ref(false)

const USERNAME_RE = /^[a-zA-Z0-9_]{3,32}$/

const usernameHint = computed(() => {
  if (!form.username) return ''
  return USERNAME_RE.test(form.username) ? '' : '只允许字母 / 数字 / 下划线，长度 3–32'
})
const passwordHint = computed(() => {
  if (!form.password) return ''
  if (form.password.length < 6) return '密码至少 6 位'
  if (form.password.length < 12) return '建议 12 位以上，混用大小写、数字与符号'
  return ''
})
const confirmHint = computed(() => {
  if (!form.confirm) return ''
  return form.confirm === form.password ? '' : '两次输入的密码不一致'
})
const canSubmit = computed(
  () =>
    !submitting.value &&
    USERNAME_RE.test(form.username) &&
    form.password.length >= 6 &&
    form.confirm === form.password,
)

onMounted(async () => {
  try {
    const st = await setupStatus()
    if (st.setup_completed) {
      router.replace('/login')
      return
    }
  } catch {
    // 状态接口异常时不挡路：路由守卫已有缓存结论，POST 本身也会 403 兜底
  } finally {
    checking.value = false
  }
})

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    await createFirstAdmin({ username: form.username.trim(), password: form.password })
    done.value = true
    setTimeout(() => router.replace({ path: '/login', query: { initialized: '1' } }), 1200)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败，请重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="setup-page">
    <div class="setup-glow" aria-hidden="true" />

    <div class="setup-card">
      <div class="setup-brand">
        <span class="brand-mark">
          <img v-if="branding.logo_url" :src="branding.logo_url" :alt="branding.site_name" />
          <Wand2 v-else :size="18" />
        </span>
        <h1>{{ branding.site_name }} 初始化向导</h1>
        <p>第一次使用：先创建一个管理员账号，之后这个入口会永久关闭</p>
      </div>

      <!-- 步骤条 -->
      <ol class="setup-steps">
        <li class="active"><span class="dot">1</span>创建管理员</li>
        <li :class="{ active: done }"><span class="dot">2</span>完成</li>
      </ol>

      <div v-if="checking" class="setup-loading">
        <Loader2 :size="18" class="spinning" />
        <span>正在确认初始化状态…</span>
      </div>

      <div v-else-if="done" class="setup-done">
        <CheckCircle2 :size="40" class="done-icon" />
        <h2>初始化完成</h2>
        <p>管理员账号 <strong>{{ form.username }}</strong> 已创建，向导入口已永久关闭。<br />正在前往登录页…</p>
      </div>

      <form v-else @submit.prevent="submit">
        <label class="field">
          <span class="field-label"><User :size="14" /> 管理员用户名</span>
          <input v-model="form.username" type="text" autocomplete="username" placeholder="例如 admin" />
          <span v-if="usernameHint" class="field-hint warn">{{ usernameHint }}</span>
        </label>
        <label class="field">
          <span class="field-label"><KeyRound :size="14" /> 密码</span>
          <input v-model="form.password" type="password" autocomplete="new-password" placeholder="至少 6 位" />
          <span v-if="passwordHint" class="field-hint" :class="{ warn: form.password.length < 6 }">
            {{ passwordHint }}
          </span>
        </label>
        <label class="field">
          <span class="field-label"><KeyRound :size="14" /> 确认密码</span>
          <input v-model="form.confirm" type="password" autocomplete="new-password" placeholder="再输一次密码" />
          <span v-if="confirmHint" class="field-hint warn">{{ confirmHint }}</span>
        </label>

        <div v-if="error" class="setup-error">{{ error }}</div>

        <button class="setup-btn" type="submit" :disabled="!canSubmit">
          <Loader2 v-if="submitting" :size="16" class="spinning" />
          <span>{{ submitting ? '创建中…' : '创建管理员并完成初始化' }}</span>
        </button>
      </form>

      <p class="setup-foot">
        <ShieldCheck :size="13" /> 账号与门户共用同一套体系，密码即 Emby 播放密码
      </p>
    </div>
  </div>
</template>

<style scoped>
/* 与 Login.vue 同一套深色主题变量：--border-default / --text-secondary / --gradient-brand … */
.setup-page {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  overflow: hidden;
}

.setup-glow {
  position: absolute;
  inset: -20% -10% auto -10%;
  height: 70vh;
  background:
    radial-gradient(ellipse 50% 60% at 30% 0%, rgba(34, 211, 238, 0.16), transparent 65%),
    radial-gradient(ellipse 45% 55% at 78% 12%, rgba(167, 139, 250, 0.14), transparent 65%);
  pointer-events: none;
}

.setup-card {
  position: relative;
  width: 100%;
  max-width: 420px;
  background: linear-gradient(180deg, rgba(16, 26, 40, 0.92), rgba(10, 16, 26, 0.92));
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 34px 28px 26px;
  box-shadow: var(--shadow-lg);
  backdrop-filter: blur(14px);
}

.setup-brand { text-align: center; margin-bottom: 22px; }
.setup-brand h1 { font-size: 20px; margin: 14px 0 6px; letter-spacing: -0.01em; }
.setup-brand p { font-size: 12.5px; color: var(--text-secondary); margin: 0; }

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: var(--gradient-brand);
  box-shadow: var(--shadow-glow);
  overflow: hidden;
  color: var(--primary-on);
}

.brand-mark img { width: 100%; height: 100%; object-fit: contain; }

.setup-steps {
  display: flex;
  gap: 8px;
  list-style: none;
  margin: 0 0 22px;
  padding: 0;
}

.setup-steps li {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-muted);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: var(--bg-input);
}

.setup-steps li.active {
  color: var(--text-primary);
  border-color: var(--border-focus);
}

.setup-steps .dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--gradient-brand);
  color: var(--primary-on);
  font-size: 11px;
  font-weight: 700;
  flex: none;
}

.setup-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 0;
  color: var(--text-secondary);
  font-size: 13.5px;
}

.setup-done { text-align: center; padding: 18px 0 8px; }
.setup-done .done-icon { color: var(--success, #34d399); }
.setup-done h2 { font-size: 18px; margin: 12px 0 8px; }
.setup-done p { font-size: 13px; color: var(--text-secondary); line-height: 1.7; margin: 0; }
.setup-done strong { color: var(--text-primary); }

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

.field-hint { display: block; margin-top: 6px; font-size: 12px; color: var(--text-secondary); }
.field-hint.warn { color: var(--warning, #fbbf24); }

.setup-error {
  font-size: 13px;
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid rgba(251, 113, 133, 0.28);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  margin-bottom: 14px;
}

.setup-btn {
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

.setup-btn:hover:not(:disabled) { background: var(--gradient-brand-hover); }
.setup-btn:active:not(:disabled) { transform: scale(0.99); }
.setup-btn:disabled { opacity: 0.65; cursor: not-allowed; }

.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.setup-foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-muted);
  margin: 18px 0 0;
}

@media (max-width: 480px) {
  .setup-page { padding: 14px; align-items: flex-start; padding-top: max(28px, env(safe-area-inset-top)); }
  .setup-card { padding: 26px 20px 20px; }
  .setup-brand h1 { font-size: 18px; }
}
</style>
