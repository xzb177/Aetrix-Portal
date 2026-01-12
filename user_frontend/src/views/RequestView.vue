<script setup lang="ts">
/**
 * 资源申请 - Apple TV 风格
 *
 * 设计原则：
 * - 暗黑玻璃体：所有卡片使用玻璃质感
 * - 弱绿点缀：状态标签不再用彩色块
 * - 单一主 CTA：同屏只有一个主按钮
 * - 克制高级：移除所有蓝/紫实心按钮与彩色 icon 块
 */
import { ref, onMounted } from 'vue'
import { requestApi } from '@/api'
import { Film, Plus, Clock, ChevronRight, Loader2, X } from 'lucide-vue-next'
import BrandIcon from '@/components/BrandIcon.vue'

interface Request {
  id: number
  movie_name: string
  year?: string
  type?: string
  note?: string
  status: 'pending' | 'approved' | 'rejected' | 'completed'
  created_at: string
  admin_note?: string
  emby_item_id?: string
}

const requests = ref<Request[]>([])
const loading = ref(true)
const submitting = ref(false)

// 表单数据
const formData = ref({
  movie_name: '',
  year: '',
  type: 'movie',
  note: '',
})

const typeOptions = [
  { value: 'movie', label: '电影' },
  { value: 'series', label: '剧集' },
  { value: 'anime', label: '动漫' },
  { value: 'documentary', label: '纪录片' },
  { value: 'other', label: '其他' },
]

// 状态映射 - 统一弱绿点缀风格
const statusConfig = {
  pending: {
    label: '待处理',
    class: 'status-pending'
  },
  approved: {
    label: '已通过',
    class: 'status-approved'
  },
  rejected: {
    label: '已拒绝',
    class: 'status-rejected'
  },
  completed: {
    label: '已完成',
    class: 'status-completed'
  }
}

onMounted(async () => {
  await fetchRequests()
})

async function fetchRequests() {
  loading.value = true
  try {
    const res = await requestApi.getMyRequests()
    requests.value = res.data || []
  } catch (error) {
    console.error('Failed to fetch requests:', error)
    requests.value = []
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  if (!formData.value.movie_name.trim()) {
    return
  }

  submitting.value = true
  try {
    await requestApi.submit({
      movie_name: formData.value.movie_name,
      year: formData.value.year || undefined,
      type: formData.value.type,
      note: formData.value.note || undefined,
    })

    // Reset form
    formData.value = { movie_name: '', year: '', type: 'movie', note: '' }

    await fetchRequests()
  } catch (error) {
    console.error('Failed to submit request:', error)
    alert('提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getTypeLabel(type: string) {
  return typeOptions.find(o => o.value === type)?.label || type
}
</script>

<template>
  <div class="request-page">
    <!-- 背景层 -->
    <div class="request-bg"></div>

    <div class="request-container">
      <!-- A) 顶部模块：AppIconTile + 标题 + 说明 -->
      <header class="page-header">
        <div class="header-left">
          <!-- AppIconTile (40px) -->
          <div class="app-icon-tile">
            <Film :size="20" class="text-white/80" />
          </div>
          <div class="header-text">
            <h1 class="page-title">资源申请</h1>
            <p class="page-subtitle">找不到想看的内容？提交申请，为您添加</p>
          </div>
        </div>
        <!-- 右侧隐藏新建按钮，只保留中间主 CTA -->
      </header>

      <!-- B) 表单模块 - 始终展示（避免弹窗） -->
      <div class="app-card form-card">
        <h2 class="card-title">提交资源申请</h2>

        <div class="form-group">
          <label class="form-label">内容名称 *</label>
          <input
            v-model="formData.movie_name"
            type="text"
            class="app-input"
            placeholder="例如：星际穿越"
          />
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">年份（可选）</label>
            <input
              v-model="formData.year"
              type="text"
              class="app-input"
              placeholder="例如：2014"
            />
          </div>
          <div class="form-group">
            <label class="form-label">类型</label>
            <select v-model="formData.type" class="app-input">
              <option v-for="opt in typeOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">备注（可选）</label>
          <textarea
            v-model="formData.note"
            class="app-input app-textarea"
            rows="3"
            placeholder="可以提供更多信息，如导演、主演等"
          ></textarea>
        </div>

        <!-- 唯一主 CTA：Primary 提交按钮 -->
        <button
          @click="handleSubmit"
          :disabled="submitting || !formData.movie_name.trim()"
          class="app-btn-primary"
        >
          <Loader2 v-if="submitting" class="spin" :size="18" />
          <span v-else>提交申请</span>
        </button>
      </div>

      <!-- C) 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="app-spinner">
          <Loader2 :size="28" class="spin" />
        </div>
        <p class="loading-text">加载中...</p>
      </div>

      <!-- D) 空状态 - 玻璃 Empty 样式 -->
      <div v-else-if="requests.length === 0" class="empty-state">
        <div class="empty-icon-wrapper">
          <Film :size="32" class="text-white/30" />
        </div>
        <h3 class="empty-title">暂无申请记录</h3>
        <p class="empty-desc">提交上方表单，创建您的第一个申请</p>
      </div>

      <!-- E) 列表状态 - ListItem 整行可点 -->
      <div v-else class="requests-list">
        <div
          v-for="request in requests"
          :key="request.id"
          class="list-item"
        >
          <div class="list-item-main">
            <div class="list-item-header">
              <h3 class="list-item-title">{{ request.movie_name }}</h3>
              <span :class="['status-badge', statusConfig[request.status].class]">
                {{ statusConfig[request.status].label }}
              </span>
            </div>
            <p class="list-item-date">{{ formatDate(request.created_at) }}</p>

            <div class="list-item-details">
              <div class="list-item-meta">
                <span v-if="request.year" class="meta-tag">{{ request.year }}</span>
                <span v-if="request.type" class="meta-tag">{{ getTypeLabel(request.type) }}</span>
              </div>
              <p v-if="request.note" class="list-item-note">
                <span class="note-label">备注：</span>{{ request.note }}
              </p>
              <p v-if="request.admin_note" class="list-item-reply">
                <span class="reply-label">管理员回复：</span>{{ request.admin_note }}
              </p>
            </div>
          </div>

          <!-- 右侧箭头 -->
          <ChevronRight :size="18" class="text-white/35" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 容器与背景 ==================== */
.request-page {
  min-height: 100vh;
  min-height: 100dvh;
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 1.5rem 1rem 2rem;
}

.request-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(ellipse at 20% 0%, rgba(60, 60, 60, 0.15) 0%, transparent 60%),
    radial-gradient(ellipse at 80% 100%, rgba(50, 50, 50, 0.1) 0%, transparent 50%),
    linear-gradient(180deg, #1a1a1a 0%, #0a0a0a 100%);
}

.request-container {
  max-width: 640px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* ==================== 顶部模块 ==================== */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

/* AppIconTile (40px) */
.app-icon-tile {
  height: 40px;
  width: 40px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(12px);
  ring: 1px solid rgba(16, 185, 129, 0.2);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.5);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.header-text {
  display: flex;
  flex-direction: column;
}

.page-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin: 0;
  line-height: 1.3;
  letter-spacing: -0.01em;
}

.page-subtitle {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
  font-weight: 400;
  line-height: 1.4;
}

/* ==================== AppCard（玻璃卡片） ==================== */
.app-card {
  border-radius: 1.5rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.55);
}

.form-card {
  padding: 1.5rem;
}

.card-title {
  font-size: 1.063rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
  margin: 0 0 1.25rem 0;
  letter-spacing: -0.01em;
}

/* ==================== 表单 ==================== */
.form-group {
  margin-bottom: 1rem;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.form-label {
  display: block;
  font-size: 0.813rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.65);
  margin-bottom: 0.5rem;
  letter-spacing: 0.01em;
}

.app-input {
  width: 100%;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 0.75rem;
  color: rgba(255, 255, 255, 0.92);
  font-size: 0.938rem;
  outline: none;
  transition: all 0.2s ease;
}

.app-input:focus {
  border-color: rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.08);
}

.app-input::placeholder {
  color: rgba(255, 255, 255, 0.35);
}

.app-textarea {
  resize: vertical;
  min-height: 80px;
  line-height: 1.5;
}

select.app-input {
  cursor: pointer;
}

select.app-input option {
  background: #1a1a1a;
  color: rgba(255, 255, 255, 0.92);
}

/* ==================== 按钮 ==================== */
/* AppButton Primary - 唯一主 CTA */
.app-btn-primary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  height: 56px;
  width: 100%;
  border-radius: 1rem;
  background: rgba(16, 185, 129, 0.16);
  border: 1px solid rgba(52, 211, 153, 0.25);
  color: rgba(255, 255, 255, 0.92);
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  margin-top: 0.5rem;
  letter-spacing: 0.01em;
}

.app-btn-primary:active:not(:disabled) {
  transform: scale(0.98);
  background: rgba(16, 185, 129, 0.22);
}

.app-btn-primary:focus-visible {
  outline: none;
  ring: 2px solid rgba(52, 211, 153, 0.35);
}

.app-btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 加载状态 ==================== */
.loading-state {
  text-align: center;
  padding: 3rem 1.5rem;
}

.app-spinner {
  width: 28px;
  height: 28px;
  margin: 0 auto 1rem;
  color: rgba(255, 255, 255, 0.4);
}

.loading-text {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
}

/* ==================== 空状态（玻璃 Empty） ==================== */
.empty-state {
  text-align: center;
  padding: 3rem 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.empty-icon-wrapper {
  height: 56px;
  width: 56px;
  border-radius: 1.25rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}

.empty-title {
  font-size: 1.063rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  margin: 0 0 0.375rem 0;
  letter-spacing: -0.01em;
}

.empty-desc {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.45);
  margin: 0;
  line-height: 1.5;
}

/* ==================== 列表状态（ListItem） ==================== */
.requests-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.list-item {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1rem;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition: all 0.15s ease;
  cursor: pointer;
}

.list-item:active {
  background: rgba(255, 255, 255, 0.08);
  transform: scale(0.99);
}

.list-item-main {
  flex: 1;
  min-width: 0;
}

.list-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.list-item-title {
  font-size: 1rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
  margin: 0;
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 状态徽章 - 弱绿点缀风格，无彩色块 */
.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
  flex-shrink: 0;
  letter-spacing: 0.02em;
}

.status-pending {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.7);
}

.status-approved {
  background: rgba(16, 185, 129, 0.12);
  color: rgba(52, 211, 153, 0.85);
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.status-rejected {
  background: rgba(239, 68, 68, 0.12);
  color: rgba(248, 113, 113, 0.85);
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.status-completed {
  background: rgba(16, 185, 129, 0.16);
  color: rgba(52, 211, 153, 0.9);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.list-item-date {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 0;
  letter-spacing: 0.01em;
}

.list-item-details {
  padding-top: 0.625rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  margin-top: 0.5rem;
}

.list-item-meta {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.55);
  padding: 0.125rem 0.5rem;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
  letter-spacing: 0.01em;
}

.list-item-note {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.65);
  margin: 0.25rem 0 0 0;
  line-height: 1.5;
}

.list-item-reply {
  font-size: 0.813rem;
  color: rgba(251, 191, 36, 0.85);
  margin: 0.25rem 0 0 0;
  line-height: 1.5;
}

.note-label {
  font-weight: 500;
  color: rgba(255, 255, 255, 0.75);
}

.reply-label {
  font-weight: 500;
  color: rgba(251, 191, 36, 0.95);
}

/* ==================== 响应式 ==================== */
@media (max-width: 480px) {
  .request-page {
    padding: 1.25rem 0.875rem 2rem;
  }

  .form-row {
    grid-template-columns: 1fr;
  }

  .page-title {
    font-size: 1rem;
  }

  .page-subtitle {
    font-size: 0.75rem;
  }

  .list-item-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .status-badge {
    align-self: flex-start;
  }
}
</style>
