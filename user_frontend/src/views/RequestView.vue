<script setup lang="ts">
/**
 * 求片页 — 简化版
 *
 * 功能：提交求片请求（片名/年份/类型/备注）+ 我的求片列表（含管理员回复）。
 */
import { ref, computed, onMounted } from 'vue'
import { mediaSeekApi, type MediaSeekRequest } from '@/api'
import { useToast } from '@/composables/useToast'
import { Film, Plus, Send, RefreshCw, CheckCircle2, Clock, XCircle } from 'lucide-vue-next'

const toast = useToast()

// ===== 状态 =====
const loading = ref(true)
const submitting = ref(false)
const requests = ref<MediaSeekRequest[]>([])
const showForm = ref(false)

// 表单
const form = ref({ movie_name: '', year: '', type: 'movie', note: '' })

const typeOptions = [
  { value: 'movie', label: '电影' },
  { value: 'series', label: '剧集' },
  { value: 'anime', label: '动漫' },
  { value: 'documentary', label: '纪录片' },
  { value: 'other', label: '其他' },
]

const typeLabels: Record<string, string> = {
  movie: '电影', series: '剧集', anime: '动漫', documentary: '纪录片', other: '其他',
}

const statusConfig: Record<string, { label: string; cls: string }> = {
  pending: { label: '待处理', cls: 'pending' },
  approved: { label: '处理中', cls: 'approved' },
  rejected: { label: '已拒绝', cls: 'rejected' },
  completed: { label: '已完成', cls: 'completed' },
}

const statusIcon = (s: string) => {
  if (s === 'completed') return CheckCircle2
  if (s === 'rejected') return XCircle
  return Clock
}

const pendingCount = computed(() => requests.value.filter(r => r.status === 'pending').length)

// ===== 数据加载 =====
async function loadRequests() {
  loading.value = true
  try {
    requests.value = (await mediaSeekApi.getMyRequests()) || []
  } catch {
    // 401 已由拦截器处理
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  if (!form.value.movie_name.trim()) {
    toast.error('请填写片名')
    return
  }
  submitting.value = true
  try {
    await mediaSeekApi.create({
      movie_name: form.value.movie_name.trim(),
      year: form.value.year || undefined,
      type: form.value.type,
      note: form.value.note || undefined,
    })
    toast.success('求片请求已提交，管理员会尽快处理')
    form.value = { movie_name: '', year: '', type: 'movie', note: '' }
    showForm.value = false
    await loadRequests()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

onMounted(loadRequests)
</script>

<template>
  <div class="request-view">
    <div class="container">
      <!-- 头部 -->
      <header class="page-head">
        <div>
          <h1 class="page-title">
            <Film :size="20" />
            求片
          </h1>
          <p class="page-sub">
            <template v-if="requests.length">
              共 {{ requests.length }} 条 · {{ pendingCount }} 条待处理
            </template>
            <template v-else>告诉我们你想看的影视作品</template>
          </p>
        </div>
        <div class="head-actions">
          <button class="icon-btn" title="刷新" @click="loadRequests">
            <RefreshCw :size="15" :class="{ spinning: loading }" />
          </button>
          <button class="btn primary" @click="showForm = !showForm">
            <Plus :size="15" />
            求片
          </button>
        </div>
      </header>

      <!-- 提交表单 -->
      <section v-if="showForm" class="card form-card">
        <div class="form-row">
          <div class="field grow">
            <label class="field-label">片名 *</label>
            <input v-model="form.movie_name" type="text" placeholder="影视作品名称" @keyup.enter="handleSubmit" />
          </div>
          <div class="field year-field">
            <label class="field-label">年份</label>
            <input v-model="form.year" type="text" placeholder="如 2024" @keyup.enter="handleSubmit" />
          </div>
          <div class="field type-field">
            <label class="field-label">类型</label>
            <select v-model="form.type">
              <option v-for="opt in typeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label class="field-label">备注</label>
          <textarea v-model="form.note" rows="2" placeholder="补充说明（选填）：季数、字幕偏好等"></textarea>
        </div>
        <div class="form-actions">
          <button class="btn ghost" @click="showForm = false">取消</button>
          <button class="btn primary" :disabled="submitting || !form.movie_name.trim()" @click="handleSubmit">
            <Send :size="14" />
            {{ submitting ? '提交中…' : '提交' }}
          </button>
        </div>
      </section>

      <!-- 加载中 -->
      <div v-if="loading && requests.length === 0" class="loading-state">
        <RefreshCw :size="22" class="spinning" />
        <p>加载中…</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="requests.length === 0" class="empty-state">
        <Film :size="32" />
        <h3>还没有求片记录</h3>
        <p>点击右上角「求片」按钮提交第一个请求</p>
      </div>

      <!-- 求片列表 -->
      <ul v-else class="request-list">
        <li v-for="req in requests" :key="req.id" class="request-item">
          <div class="item-head">
            <div class="item-title-wrap">
              <h3 class="item-title">{{ req.movie_name }}</h3>
              <div class="item-meta">
                <span v-if="req.year">{{ req.year }}</span>
                <span v-if="typeLabels[req.type || '']" class="type-tag">{{ typeLabels[req.type || ''] }}</span>
              </div>
            </div>
            <span class="status" :class="statusConfig[req.status]?.cls || 'pending'">
              <component :is="statusIcon(req.status)" :size="13" />
              {{ statusConfig[req.status]?.label || req.status }}
            </span>
          </div>
          <p v-if="req.note" class="item-note">{{ req.note }}</p>
          <p v-if="req.admin_note" class="item-reply">
            <span class="reply-label">管理员回复</span>{{ req.admin_note }}
          </p>
          <p class="item-date">{{ formatDate(req.created_at) }}</p>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.request-view {
  min-height: 100vh;
  background: #070b12;
  color: #e5e7eb;
  padding-bottom: 3rem;
}

.container {
  max-width: 680px;
  margin: 0 auto;
  padding: 0 1.25rem;
}

/* 头部 */
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 2.25rem 0 1.5rem;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.375rem;
  font-weight: 700;
  color: #fafafa;
  margin: 0;
}

.page-title svg {
  color: #22d3ee;
}

.page-sub {
  margin: 0.375rem 0 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.45);
}

.head-actions {
  display: flex;
  gap: 0.5rem;
}

/* 卡片 */
.card {
  background: rgba(13, 18, 24, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 16px;
  padding: 1.25rem;
  margin-bottom: 1.25rem;
}

.form-card {
  animation: cardIn 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes cardIn {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: none; }
}

.form-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.field {
  margin-bottom: 0.75rem;
  display: flex;
  flex-direction: column;
}

.grow { flex: 1 1 240px; }
.year-field { flex: 0 1 110px; }
.type-field { flex: 0 1 130px; }

.field-label {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  margin-bottom: 0.375rem;
}

.field input,
.field select,
.field textarea {
  width: 100%;
  padding: 0.5625rem 0.75rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: #fafafa;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.2s ease;
  box-sizing: border-box;
  font-family: inherit;
}

.field textarea {
  resize: vertical;
  min-height: 56px;
}

.field input:focus,
.field select:focus,
.field textarea:focus {
  border-color: rgba(34, 211, 238, 0.6);
}

.field select option {
  background: #10161d;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.625rem;
  margin-top: 0.25rem;
}

/* 按钮 */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  height: 38px;
  padding: 0 1rem;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
  text-decoration: none;
}

.btn.primary {
  background: linear-gradient(135deg, #22d3ee, #06b6d4);
  color: #fff;
  box-shadow: 0 4px 14px rgba(34, 211, 238, 0.22);
}

.btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.ghost {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.75);
}

.btn.ghost:hover {
  background: rgba(255, 255, 255, 0.1);
}

.icon-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.2s ease;
}

.icon-btn:hover {
  color: #fff;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.625rem;
  padding: 3.5rem 0;
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.8125rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 4rem 1rem;
  text-align: center;
  color: rgba(255, 255, 255, 0.35);
}

.empty-state svg {
  color: rgba(34, 211, 238, 0.4);
}

.empty-state h3 {
  margin: 0.375rem 0 0;
  font-size: 0.9375rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.7);
}

.empty-state p {
  margin: 0;
  font-size: 0.8125rem;
}

/* 列表 */
.request-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.request-item {
  background: rgba(13, 18, 24, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 14px;
  padding: 1rem 1.125rem;
  transition: border-color 0.2s ease;
}

.request-item:hover {
  border-color: rgba(34, 211, 238, 0.2);
}

.item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.item-title-wrap {
  min-width: 0;
}

.item-title {
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 600;
  color: #fafafa;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
}

.type-tag {
  padding: 0.0625rem 0.4375rem;
  background: rgba(34, 211, 238, 0.08);
  border-radius: 6px;
  color: rgba(34, 211, 238, 0.8);
}

.status {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  padding: 0.25rem 0.5625rem;
  border-radius: 8px;
  font-size: 0.6875rem;
  font-weight: 600;
}

.status.pending {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.status.approved {
  background: rgba(59, 130, 246, 0.1);
  color: #60a5fa;
}

.status.rejected {
  background: rgba(239, 68, 68, 0.1);
  color: #f87171;
}

.status.completed {
  background: rgba(34, 211, 238, 0.1);
  color: #34d399;
}

.item-note {
  margin: 0.625rem 0 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.5;
}

.item-reply {
  margin: 0.625rem 0 0;
  padding: 0.5rem 0.75rem;
  background: rgba(34, 211, 238, 0.05);
  border: 1px solid rgba(34, 211, 238, 0.15);
  border-radius: 9px;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.5;
}

.reply-label {
  color: #22d3ee;
  font-weight: 600;
  margin-right: 0.4375rem;
  font-size: 0.75rem;
}

.item-date {
  margin: 0.5rem 0 0;
  font-size: 0.6875rem;
  color: rgba(255, 255, 255, 0.28);
}

@media (max-width: 640px) {
  .page-head {
    padding: 1.75rem 0 1.25rem;
  }

  .year-field {
    flex: 1 1 110px;
  }
}
</style>
