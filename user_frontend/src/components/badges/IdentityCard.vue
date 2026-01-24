<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Copy, Share2, X, Download } from 'lucide-vue-next'
import { badgesApi } from '@/api'

interface Badge {
  code: string
  name: string
  icon: string
  color: string
  rarity: string
  unlocked_at?: string
}

interface IdentityCardData {
  username: string
  user_id: number
  joined_at: string
  level: number
  badges: Badge[]
  total_requests: number
  completed_requests: number
  emby_servers: string[]
  is_vip: boolean
}

interface Props {
  userId?: number
  show?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  userId: 0,
  show: false
})

const emit = defineEmits<{
  close: []
}>()

const loading = ref(true)
const cardData = ref<IdentityCardData | null>(null)
const copied = ref(false)

// 格式化日期
const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

// 格式化签名文案
const getSignatureText = computed(() => {
  if (!cardData.value) return ''
  const d = cardData.value
  const badgeText = d.badges.length > 0 ? d.badges.map(b => b.icon).join(' ') : ''
  return `🚀 ${d.username} | Lv.${d.level} | ${d.total_requests}次求片 ${badgeText}`
})

// 加载身份卡数据
const loadIdentityCard = async () => {
  loading.value = true
  try {
    const response = await badgesApi.getIdentityCard() as any
    cardData.value = response
  } catch (error) {
    console.error('加载身份卡失败:', error)
  } finally {
    loading.value = false
  }
}

// 复制签名
const copySignature = async () => {
  const text = getSignatureText.value
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (error) {
    console.error('复制失败:', error)
  }
}

// 导出图片
const exportImage = () => {
  // TODO: 实现 canvas 截图导出
  alert('导出功能开发中...')
}

// 关闭
const close = () => {
  emit('close')
}

// 暴露方法
defineExpose({
  refresh: loadIdentityCard
})

onMounted(() => {
  if (props.show) {
    loadIdentityCard()
  }
})

// 监听 show 变化
import { watch } from 'vue'
watch(() => props.show, (newVal) => {
  if (newVal && !cardData.value) {
    loadIdentityCard()
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="show" class="identity-card-overlay" @click.self="close">
        <div class="identity-card-container" @click.stop>
          <!-- 关闭按钮 -->
          <button class="close-btn" @click="close">
            <X :size="20" />
          </button>

          <!-- 加载状态 -->
          <div v-if="loading" class="card-loading">
            <div class="spinner"></div>
          </div>

          <!-- 身份卡内容 -->
          <div v-else-if="cardData" class="identity-card" ref="cardRef">
            <!-- 扫光效果 -->
            <div class="card-shine"></div>
            <!-- 网格背景 -->
            <div class="card-grid"></div>

            <!-- 卡片头部 -->
            <div class="card-header">
              <div class="card-avatar">
                <span class="avatar-text">{{ cardData.username.charAt(0).toUpperCase() }}</span>
                <div class="avatar-glow"></div>
              </div>
              <div class="card-user-info">
                <h3 class="user-name">{{ cardData.username }}</h3>
                <p class="user-id">ID: {{ cardData.user_id.toString().slice(-6) }}</p>
              </div>
              <div class="card-level">
                <span class="level-badge">Lv.{{ cardData.level }}</span>
              </div>
            </div>

            <!-- 卡片统计 -->
            <div class="card-stats">
              <div class="stat-item">
                <span class="stat-value">{{ cardData.total_requests }}</span>
                <span class="stat-label">求片</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ cardData.badges.length }}</span>
                <span class="stat-label">徽章</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ formatDate(cardData.joined_at) }}</span>
                <span class="stat-label">加入</span>
              </div>
            </div>

            <!-- 徽章展示 -->
            <div v-if="cardData.badges.length > 0" class="card-badges">
              <div
                v-for="badge in cardData.badges.slice(0, 6)"
                :key="badge.code"
                class="mini-badge"
                :style="{ borderColor: badge.color }"
                :title="badge.name"
              >
                {{ badge.icon }}
              </div>
              <div v-if="cardData.badges.length > 6" class="mini-badge more">
                +{{ cardData.badges.length - 6 }}
              </div>
            </div>

            <!-- Emby 服务器 -->
            <div v-if="cardData.emby_servers.length > 0" class="card-servers">
              <span class="server-label">已连接:</span>
              <span class="server-names">{{ cardData.emby_servers.join(', ') }}</span>
            </div>

            <!-- 底部签名 -->
            <div class="card-footer">
              <p class="signature-text">{{ getSignatureText }}</p>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="card-actions">
            <button class="action-btn" @click="copySignature" :class="{ active: copied }">
              <Copy :size="18" />
              {{ copied ? '已复制' : '复制签名' }}
            </button>
            <button class="action-btn" @click="exportImage">
              <Download :size="18" />
              导出图片
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.identity-card-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(10px);
}

.identity-card-container {
  position: relative;
  width: 100%;
  max-width: 380px;
}

.close-btn {
  position: absolute;
  top: -40px;
  right: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 50%;
  color: var(--text-primary, rgba(255, 255, 255, 0.92));
  cursor: pointer;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.card-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3rem 0;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top-color: #673AB7;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.identity-card {
  position: relative;
  background: linear-gradient(135deg, rgba(30, 20, 40, 0.95) 0%, rgba(20, 10, 30, 0.98) 100%);
  border-radius: 20px;
  padding: 1.5rem;
  overflow: hidden;
  border: 1px solid rgba(103, 58, 183, 0.3);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

/* 网格背景 */
.card-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(103, 58, 183, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(103, 58, 183, 0.05) 1px, transparent 1px);
  background-size: 20px 20px;
  opacity: 0.5;
  pointer-events: none;
}

/* 扫光效果 */
.card-shine {
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(
    45deg,
    transparent 40%,
    rgba(103, 58, 183, 0.1) 50%,
    transparent 60%
  );
  animation: shine 6s ease-in-out infinite;
  pointer-events: none;
}

@keyframes shine {
  0% { transform: translateX(-100%) translateY(-100%) rotate(45deg); }
  100% { transform: translateX(100%) translateY(100%) rotate(45deg); }
}

.card-header {
  position: relative;
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.card-avatar {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: linear-gradient(135deg, #673AB7, #7B1FA2);
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-text {
  font-size: 1.5rem;
  font-weight: 700;
  color: white;
}

.avatar-glow {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: linear-gradient(135deg, #673AB7, #7B1FA2);
  filter: blur(12px);
  opacity: 0.5;
  z-index: -1;
}

.card-user-info {
  flex: 1;
}

.user-name {
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--text-primary, rgba(255, 255, 255, 0.92));
  margin: 0 0 0.25rem 0;
}

.user-id {
  font-size: 0.75rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
  margin: 0;
  font-family: 'Courier New', monospace;
}

.level-badge {
  display: inline-block;
  padding: 0.375rem 0.75rem;
  background: linear-gradient(135deg, #FFD700, #FFA500);
  color: #000;
  font-size: 0.75rem;
  font-weight: 700;
  border-radius: 20px;
}

.card-stats {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 12px;
  margin-bottom: 1rem;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
}

.stat-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary, rgba(255, 255, 255, 0.92));
}

.stat-label {
  font-size: 0.625rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.card-badges {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.mini-badge {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  font-size: 1rem;
  transition: all 0.2s ease;
}

.mini-badge:hover {
  transform: scale(1.1);
  background: rgba(255, 255, 255, 0.1);
}

.mini-badge.more {
  font-size: 0.625rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
}

.card-servers {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.server-label {
  font-size: 0.625rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
}

.server-names {
  font-size: 0.75rem;
  color: var(--text-primary, rgba(255, 255, 255, 0.92));
}

.card-footer {
  position: relative;
  padding-top: 1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.signature-text {
  font-size: 0.75rem;
  color: var(--text-muted, rgba(255, 255, 255, 0.5));
  margin: 0;
  text-align: center;
  font-family: 'Courier New', monospace;
}

.card-actions {
  display: flex;
  gap: 0.75rem;
  margin-top: 1rem;
}

.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: var(--text-primary, rgba(255, 255, 255, 0.92));
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.action-btn.active {
  background: rgba(76, 175, 80, 0.2);
  border-color: rgba(76, 175, 80, 0.5);
  color: #4CAF50;
}

/* Modal 过渡 */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .identity-card-container,
.modal-leave-to .identity-card-container {
  transform: scale(0.9) translateY(20px);
}

.modal-enter-to .identity-card-container,
.modal-leave-from .identity-card-container {
  transform: scale(1) translateY(0);
}

/* iOS Safari 兼容 */
@supports (-webkit-touch-callout: none) {
  .card-shine {
    animation: none;
  }

  .avatar-glow {
    animation: none;
  }
}

/* reduced-motion 支持 */
@media (prefers-reduced-motion: reduce) {
  .card-shine {
    animation: none;
  }

  .mini-badge:hover {
    transform: none;
  }
}
</style>
