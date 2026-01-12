<script setup lang="ts">
import { ref, onMounted } from 'vue'

const isTelegramBrowser = ref(false)
const dismissed = ref(false)
const currentUrl = ref('')

onMounted(() => {
  // 检测是否在 Telegram in-app browser 中
  const userAgent = navigator.userAgent || ''
  const isTelegram = userAgent.includes('Telegram') || userAgent.includes('FB_IAB') || userAgent.includes('Twitter')

  // 也检查是否从 t.me 跳转过来
  const referrer = document.referrer || ''
  const fromTelegram = referrer.includes('t.me')

  isTelegramBrowser.value = isTelegram || fromTelegram
  currentUrl.value = window.location.href

  // 保存到 sessionStorage，避免每次都显示
  const dismissedTime = sessionStorage.getItem('telegram_browser_dismissed')
  if (dismissedTime) {
    const oneHour = 60 * 60 * 1000
    if (Date.now() - parseInt(dismissedTime) < oneHour) {
      isTelegramBrowser.value = false
    }
  }
})

const copyUrl = () => {
  navigator.clipboard.writeText(currentUrl.value)
  const btn = document.querySelector('.btn-copy') as HTMLButtonElement
  if (btn) {
    btn.textContent = '已复制！'
    setTimeout(() => {
      btn.textContent = '复制链接'
    }, 2000)
  }
}

const openInExternalBrowser = () => {
  // 尝试使用 Telegram 的 API 在外部浏览器打开
  const url = window.location.href

  // 移动端：尝试用原生方式打开
  if ((window as any).Telegram && (window as any).Telegram.WebApp) {
    try {
      (window as any).Telegram.WebApp.openLink(url)
    } catch {
      // 如果 API 失败，使用备用方案
      window.open(url, '_blank')
    }
  } else {
    // iOS Safari 特殊处理
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !(window as any).MSStream
    if (isIOS) {
      // 尝试使用 Safari 打开
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.target = '_blank'
      anchor.rel = 'noopener noreferrer'
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
    } else {
      // Android 或其他
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }
}

const dismiss = () => {
  sessionStorage.setItem('telegram_browser_dismissed', String(Date.now()))
  dismissed.value = true
}
</script>

<template>
  <div v-if="isTelegramBrowser && !dismissed" class="telegram-browser-banner">
    <div class="banner-content">
      <div class="banner-icon">
        <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24">
          <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18 1.897-.962 6.502-1.359 8.627-.168.9-.5 1.201-.82 1.23-.697.064-1.226-.461-1.901-.903-1.056-.692-1.653-1.123-2.678-1.799-1.185-.781-.417-1.21.258-1.911.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.139-5.062 3.345-.479.329-.913.489-1.302.481-.428-.009-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.324-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635.099-.002.321.023.465.141.121.099.155.232.17.325.016.094.035.31.02.478z"/>
        </svg>
      </div>
      <div class="banner-text">
        <p class="banner-title">检测到您正在使用 Telegram 内置浏览器</p>
        <p class="banner-desc">本网站在 Telegram 内置浏览器中可能显示异常，建议使用外部浏览器打开</p>
      </div>
    </div>
    <div class="banner-actions">
      <button @click="openInExternalBrowser" class="btn-open">
        在外部浏览器打开
      </button>
      <button @click="copyUrl" class="btn-copy">
        复制链接
      </button>
      <button @click="dismiss" class="btn-dismiss">
        继续使用
      </button>
    </div>
  </div>
</template>

<style scoped>
.telegram-browser-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.95);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  z-index: 9999;
}

.banner-content {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 2rem;
  text-align: center;
}

.banner-icon {
  width: 60px;
  height: 60px;
  background: linear-gradient(135deg, #2AABEE 0%, #229ED9 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.banner-icon svg {
  color: white;
}

.banner-text {
  text-align: left;
}

.banner-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 0.5rem;
}

.banner-desc {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.7);
  margin: 0;
  max-width: 280px;
}

.banner-actions {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  width: 100%;
  max-width: 280px;
}

.btn-open {
  padding: 0.875rem 1.5rem;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-open:active {
  transform: scale(0.98);
  opacity: 0.9;
}

.btn-copy {
  padding: 0.75rem 1.5rem;
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 12px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-copy:active {
  background: rgba(16, 185, 129, 0.3);
}

.btn-dismiss {
  padding: 0.75rem 1.5rem;
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  border: none;
  border-radius: 12px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: color 0.2s ease;
}

.btn-dismiss:active {
  color: rgba(255, 255, 255, 0.9);
}

@media (min-width: 768px) {
  .banner-content {
    flex-direction: column;
    text-align: center;
  }

  .banner-text {
    text-align: center;
  }

  .banner-actions {
    flex-direction: row;
  }
}
</style>
