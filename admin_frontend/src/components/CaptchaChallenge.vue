<script setup lang="ts">
/**
 * 人机验证挂件（能力：人机验证）—— 管理后台登录用
 *
 * 与用户端挂件同一套逻辑（用户端的在 `user_frontend/src/components/ui/CaptchaChallenge.vue`），
 * 差别只在样式与动作名：这里对应 `admin_login`，管理员在「系统设置 → 人机验证」里
 * 打开「保护管理后台登录」之后才会渲染——后台登录是整个站点最值钱的入口，
 * 此前恰好是唯一没有这道闸的登录路径。
 *
 * 未配置 / 未开保护 → 组件不渲染任何东西；脚本加载失败 → 明确提示并把令牌留空
 * （后端会拒绝，比静默失败好排查）；令牌一次性，登录失败后由父组件调 `reset()`。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, ShieldCheck } from 'lucide-vue-next'
import { siteApi, type CaptchaInfo } from '@/api/site'

const emit = defineEmits<{ (e: 'update:token', token: string): void }>()

const info = ref<CaptchaInfo | null>(null)
const boxRef = ref<HTMLElement | null>(null)
const failed = ref(false)
const widgetId = ref<string | number | null>(null)
let scriptEl: HTMLScriptElement | null = null

function providerGlobal(): any {
  const name = info.value?.provider
  if (name === 'turnstile') return (window as any).turnstile
  if (name === 'recaptcha') return (window as any).grecaptcha
  if (name === 'hcaptcha') return (window as any).hcaptcha
  return null
}

function loadScript(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${url}"]`)
    if (existing) {
      if (providerGlobal()) resolve()
      else {
        existing.addEventListener('load', () => resolve())
        existing.addEventListener('error', () => reject(new Error('script error')))
      }
      return
    }
    const el = document.createElement('script')
    el.src = url
    el.async = true
    el.defer = true
    el.onload = () => resolve()
    el.onerror = () => reject(new Error('script error'))
    scriptEl = el
    document.head.appendChild(el)
  })
}

async function waitForGlobal(timeoutMs = 6000): Promise<any> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const g = providerGlobal()
    if (g) return g
    await new Promise((r) => setTimeout(r, 80))
  }
  return null
}

function tokenOf(response: unknown): string {
  if (typeof response === 'string') return response
  if (response && typeof response === 'object' && 'token' in response) {
    return String((response as { token?: string }).token || '')
  }
  return ''
}

async function render() {
  const current = info.value
  if (!current?.enabled || !current.actions?.admin_login) return
  const global = await waitForGlobal()
  if (!global || !boxRef.value) {
    failed.value = true
    return
  }
  try {
    const options = {
      sitekey: current.site_key,
      theme: 'dark' as const,
      callback: (response: unknown) => emit('update:token', tokenOf(response)),
      'expired-callback': () => emit('update:token', ''),
      'error-callback': () => emit('update:token', ''),
    }
    if (current.provider === 'recaptcha' && typeof global.ready === 'function') {
      await new Promise<void>((resolve) => global.ready(() => resolve()))
    }
    widgetId.value = global.render(boxRef.value, options)
  } catch {
    failed.value = true
  }
}

function reset() {
  const global = providerGlobal()
  emit('update:token', '')
  if (global && widgetId.value !== null) {
    try {
      global.reset(widgetId.value)
    } catch {
      /* 提供方拒绝重置时忽略 */
    }
  }
}

defineExpose({ reset })

onMounted(async () => {
  try {
    info.value = await siteApi.captcha()
  } catch {
    return
  }
  if (!info.value.enabled || !info.value.actions?.admin_login) return
  try {
    await loadScript(info.value.script_url)
  } catch {
    failed.value = true
    return
  }
  await render()
})

onBeforeUnmount(() => {
  if (scriptEl && scriptEl.parentNode) scriptEl.parentNode.removeChild(scriptEl)
})
</script>

<template>
  <div v-if="info?.enabled && info.actions?.admin_login" class="captcha-block">
    <div ref="boxRef" class="captcha-box"></div>
    <p v-if="failed" class="captcha-note error">
      <AlertTriangle :size="13" />
      {{ info.label }} 脚本加载失败（可能是网络或域名未在提供方登记），请刷新重试
    </p>
    <p v-else class="captcha-note">
      <ShieldCheck :size="13" />
      本站开启了人机验证（{{ info.label }}）
    </p>
  </div>
</template>

<style scoped>
.captcha-block { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }

.captcha-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  line-height: 1.5;
}

.captcha-note.error { color: var(--danger); }
</style>
