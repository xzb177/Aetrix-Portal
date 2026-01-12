<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RefreshCw, Send, Bell, Info } from 'lucide-vue-next'
import { http } from '@/utils/request'

interface PushConfig {
  high_quality_push_hour: number
  high_quality_rating_threshold: number
  high_quality_bitrate_threshold: number
  high_quality_min_width: number
  check_interval_minutes: number
  notification_chats: string
}

const loading = ref(false)
const config = ref<PushConfig | null>(null)
const testing = ref(false)
const toastMessage = ref('')
const showToast = ref(false)

const loadConfig = async () => {
  loading.value = true
  try {
    config.value = await http.get<PushConfig>('/push/config')
  } catch (error) {
    console.error('加载推送配置失败:', error)
  } finally {
    loading.value = false
  }
}

const showToastMessage = (message: string) => {
  toastMessage.value = message
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

const handleTestPush = async () => {
  testing.value = true
  try {
    await http.post('/push/test')
    showToastMessage('测试推送已发送')
  } catch (error) {
    console.error('发送测试推送失败:', error)
    showToastMessage('发送失败，请稍后重试')
  } finally {
    testing.value = false
  }
}

const itemId = ref('')

const handleManualPush = async () => {
  if (!itemId.value) {
    showToastMessage('请输入媒体 ID')
    return
  }
  testing.value = true
  try {
    await http.post(`/push/send?item_id=${itemId.value}`)
    showToastMessage('推送发送成功')
    itemId.value = ''
  } catch (error) {
    console.error('发送推送失败:', error)
    showToastMessage('发送失败，请稍后重试')
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="push-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="btn-secondary btn-icon" @click="loadConfig" :disabled="loading">
        <RefreshCw :size="18" :class="{ 'animate-spin': loading }" />
        刷新
      </button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="space-y-6">
      <div class="card p-6">
        <div class="shimmer-line w-1/4 mb-4"></div>
        <div class="space-y-3">
          <div class="shimmer-line"></div>
          <div class="shimmer-line"></div>
          <div class="shimmer-line w-2/3"></div>
        </div>
      </div>
    </div>

    <!-- 推送配置 -->
    <template v-else-if="config">
      <div class="card config-card">
        <div class="card-header">
          <Bell :size="18" class="card-icon" />
          <span class="card-title">推送配置</span>
        </div>
        <div class="config-grid">
          <div class="config-item">
            <p class="config-label">推送时间</p>
            <p class="config-value">{{ config.high_quality_push_hour }}:00</p>
          </div>
          <div class="config-item">
            <p class="config-label">评分阈值</p>
            <p class="config-value">{{ config.high_quality_rating_threshold }} 分</p>
          </div>
          <div class="config-item">
            <p class="config-label">码率阈值</p>
            <p class="config-value">{{ (config.high_quality_bitrate_threshold / 1000000).toFixed(1) }} Mbps</p>
          </div>
          <div class="config-item">
            <p class="config-label">最低分辨率</p>
            <p class="config-value">{{ config.high_quality_min_width }}p</p>
          </div>
          <div class="config-item">
            <p class="config-label">检查间隔</p>
            <p class="config-value">{{ config.check_interval_minutes }} 分钟</p>
          </div>
          <div class="config-item">
            <p class="config-label">通知群组</p>
            <p class="config-value">{{ config.notification_chats || '未设置' }}</p>
          </div>
        </div>
      </div>

      <!-- 测试推送 -->
      <div class="card action-card">
        <div class="card-header">
          <Send :size="18" class="card-icon" />
          <span class="card-title">测试推送</span>
        </div>
        <div class="action-content">
          <button class="btn-primary" @click="handleTestPush" :disabled="testing">
            <Send :size="18" v-if="!testing" />
            <span v-else class="loading-spinner mr-2"></span>
            发送测试消息
          </button>
          <p class="action-desc">发送一条测试消息到所有配置的通知群组</p>
        </div>
      </div>

      <!-- 手动推送 -->
      <div class="card action-card">
        <div class="card-header">
          <Bell :size="18" class="card-icon" />
          <span class="card-title">手动推送</span>
        </div>
        <div class="manual-push-content">
          <div class="input-group">
            <input
              v-model="itemId"
              type="text"
              placeholder="请输入 Emby 媒体 ID"
              class="input"
            />
            <button class="btn-primary" @click="handleManualPush" :disabled="testing">
              <Bell :size="18" v-if="!testing" />
              <span v-else class="loading-spinner mr-2"></span>
              立即推送
            </button>
          </div>
          <p class="action-desc">手动推送指定影片到所有配置的通知群组</p>
        </div>
      </div>

      <!-- 使用说明 -->
      <div class="card info-card">
        <div class="card-header">
          <Info :size="18" class="card-icon-blue" />
          <span class="card-title">使用说明</span>
        </div>
        <ol class="info-list">
          <li class="info-item">
            <span class="step-number">1</span>
            <span>配置环境变量 <code class="code-inline">EMBY_NOTIFY_CHATS</code> 设置接收推送的群组 ID（多个用逗号分隔）</span>
          </li>
          <li class="info-item">
            <span class="step-number">2</span>
            <span>系统会自动定期检查新入库的高质量影片并推送</span>
          </li>
          <li class="info-item">
            <span class="step-number">3</span>
            <span>可以通过"测试推送"按钮验证推送功能是否正常</span>
          </li>
          <li class="info-item">
            <span class="step-number">4</span>
            <span>可以通过"手动推送"功能指定影片进行推送</span>
          </li>
        </ol>
      </div>
    </template>

    <!-- Toast 提示 -->
    <Transition
      enter-active-class="transition-all duration-300"
      enter-from-class="opacity-0 translate-x-4"
      enter-to-class="opacity-100 translate-x-0"
      leave-active-class="transition-all duration-300"
      leave-from-class="opacity-100 translate-x-0"
      leave-to-class="opacity-0 translate-x-4"
    >
      <div v-if="showToast" class="toast toast-info">
        <span class="text-xl">ℹ</span>
        <span>{{ toastMessage }}</span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ==================== Page Layout ==================== */
.push-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}





.btn-icon {
  gap: 0.5rem;
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

/* ==================== Config Card ==================== */
.config-card {
  padding: 1.5rem;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.config-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.config-value {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
}

/* ==================== Action Card ==================== */
.action-card {
  padding: 1.5rem;
}

.action-content {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.action-desc {
  font-size: 0.875rem;
  color: var(--text-muted);
}

/* ==================== Manual Push ==================== */
.manual-push-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.input-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
}

.input-group .input {
  flex: 1;
  min-width: 200px;
  max-width: 400px;
}

/* ==================== Info Card ==================== */
.info-card {
  padding: 1.5rem;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.info-item {
  display: flex;
  gap: 0.75rem;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.step-number {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-secondary) 100%);
  color: #fff;
  font-size: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.code-inline {
  padding: 0.125rem 0.5rem;
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 0.8125rem;
}

/* ==================== Shimmer Loading ==================== */
.shimmer-line {
  height: 12px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
}

/* ==================== Mobile Responsive ==================== */
@media (max-width: 768px) {

@media (max-width: 480px) {
  .config-grid {
    grid-template-columns: 1fr;
  }

  .card {
    padding: 1.25rem;
  }
}
</style>
