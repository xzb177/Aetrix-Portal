<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const status = ref<'loading' | 'success' | 'error'>('loading')
const message = ref('正在登录...')
const debugInfo = ref('')

onMounted(async () => {
  try {
    debugInfo.value = '页面已加载，正在解析参数...'

    // 从 URL query 参数获取 token 和用户信息
    const token = route.query.token as string
    const userStr = route.query.user as string

    debugInfo.value = `token: ${token ? '存在' : '不存在'}, user: ${userStr ? '存在' : '不存在'}`

    if (token && userStr) {
      debugInfo.value = '正在解析用户数据...'

      // 设置用户信息 - 只保留需要的字段
      let userData: any
      try {
        userData = JSON.parse(decodeURIComponent(userStr))
      } catch (e) {
        debugInfo.value = 'JSON 解析失败: ' + String(e)
        throw new Error('用户数据解析失败')
      }

      // 只保留前端需要的字段
      const cleanUser = {
        id: userData.id,
        username: userData.username,
        email: userData.email,
        telegram_id: userData.telegram_id,
        is_vip: userData.is_vip || false,
        emby_account: userData.emby_account,
        points: userData.points || 0
      }

      debugInfo.value = `用户: ${cleanUser.username}`

      // 设置到 store
      userStore.token = token
      userStore.user = cleanUser

      // 保存到 localStorage
      localStorage.setItem('access_token', token)
      localStorage.setItem('user', JSON.stringify(cleanUser))

      status.value = 'success'
      message.value = '登录成功！'

      debugInfo.value = '准备跳转...'

      // 获取保存的重定向地址
      let redirect = sessionStorage.getItem('telegram_redirect')
      sessionStorage.removeItem('telegram_redirect')

      // 如果没有重定向地址，默认跳转到首页
      if (!redirect) {
        redirect = '/'
      }

      // 延迟跳转
      setTimeout(() => {
        debugInfo.value = `正在跳转到: ${redirect}`
        window.location.href = redirect
      }, 1500)
    } else {
      status.value = 'error'
      message.value = '登录失败，缺少必要参数'
      debugInfo.value = 'token 或 user 参数缺失'
      setTimeout(() => {
        window.location.href = '/'
      }, 3000)
    }
  } catch (err) {
    console.error('Telegram auth success handler error:', err)
    status.value = 'error'
    message.value = '登录处理失败'
    debugInfo.value = '错误: ' + String(err)
    setTimeout(() => {
      window.location.href = '/'
    }, 3000)
  }
})
</script>

<template>
  <div class="auth-success-page">
    <div class="success-card">
      <!-- 加载状态 -->
      <div v-if="status === 'loading'" class="status-icon loading">
        <svg class="spinner" viewBox="0 0 50 50">
          <circle class="path" cx="25" cy="25" r="20" fill="none" stroke-width="5"></circle>
        </svg>
      </div>

      <!-- 成功状态 -->
      <div v-else-if="status === 'success'" class="status-icon success">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
          <path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>

      <!-- 错误状态 -->
      <div v-else class="status-icon error">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
          <path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>

      <h2 class="title">{{ message }}</h2>
      <p class="subtitle">正在返回网站...</p>

      <!-- 调试信息 -->
      <p v-if="debugInfo" class="debug-info">{{ debugInfo }}</p>

      <!-- 手动跳转按钮 -->
      <a v-if="status === 'success'" href="/" class="manual-link">
        如果没有自动跳转，请点击这里
      </a>
    </div>
  </div>
</template>

<style scoped>
.auth-success-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a1a 0%, #0a0a0a 100%);
  padding: 1rem;
}

.success-card {
  text-align: center;
  padding: 2rem;
  max-width: 400px;
}

.status-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto 1.5rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-icon svg {
  width: 40px;
  height: 40px;
}

/* 加载状态 */
.status-icon.loading {
  background: rgba(16, 185, 129, 0.1);
}

.spinner {
  animation: spin 1s linear infinite;
}

.spinner .path {
  stroke: #10b981;
  stroke-linecap: round;
  animation: dash 1.5s ease-in-out infinite;
}

@keyframes spin {
  100% {
    transform: rotate(360deg);
  }
}

@keyframes dash {
  0% {
    stroke-dasharray: 1, 150;
    stroke-dashoffset: 0;
  }
  50% {
    stroke-dasharray: 90, 150;
    stroke-dashoffset: -35;
  }
  100% {
    stroke-dasharray: 90, 150;
    stroke-dashoffset: -124;
  }
}

/* 成功状态 */
.status-icon.success {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  animation: scaleIn 0.3s ease-out;
}

.status-icon.success svg {
  color: white;
}

@keyframes scaleIn {
  0% {
    transform: scale(0);
  }
  50% {
    transform: scale(1.1);
  }
  100% {
    transform: scale(1);
  }
}

/* 错误状态 */
.status-icon.error {
  background: rgba(239, 68, 68, 0.2);
}

.status-icon.error svg {
  color: #ef4444;
}

.title {
  font-size: 1.5rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 0.5rem;
}

.subtitle {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 1rem;
}

.debug-info {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 1rem 0;
  word-break: break-all;
}

.manual-link {
  display: inline-block;
  margin-top: 1rem;
  padding: 0.75rem 1.5rem;
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  text-decoration: none;
  border-radius: 8px;
  font-size: 0.875rem;
}

.manual-link:hover {
  background: rgba(16, 185, 129, 0.3);
}
</style>
