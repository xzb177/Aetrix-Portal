<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Megaphone, Plus, Edit, Trash2, Eye, EyeOff, Menu, RefreshCw, X } from 'lucide-vue-next'

interface Announcement {
  id: number
  title: string
  content: string
  is_active: boolean
  created_at: string
  updated_at: string
}

const announcements = ref<Announcement[]>([])
const loading = ref(false)
const showDialog = ref(false)
const showMoreMenu = ref(false)

// 新建/编辑公告表单
const editingId = ref<number | null>(null)
const formTitle = ref('')
const formContent = ref('')
const formActive = ref(true)
const saving = ref(false)

const loadAnnouncements = async () => {
  loading.value = true
  try {
    // TODO: API 调用
    // const response = await api.get('/api/admin/announcements')
    // announcements.value = response.data
    announcements.value = []
  } catch (error) {
    console.error('加载公告失败:', error)
  } finally {
    loading.value = false
  }
}

const toggleActive = async (announcement: Announcement) => {
  try {
    // TODO: API 调用
    // await api.put(`/api/admin/announcements/${announcement.id}`, {
    //   is_active: !announcement.is_active
    // })
    announcement.is_active = !announcement.is_active
  } catch (error) {
    console.error('更新公告状态失败:', error)
  }
}

const deleteAnnouncement = async (id: number) => {
  if (!confirm('确定要删除此公告吗？')) return
  try {
    // TODO: API 调用
    // await api.delete(`/api/admin/announcements/${id}`)
    announcements.value = announcements.value.filter(a => a.id !== id)
  } catch (error) {
    console.error('删除公告失败:', error)
  }
}

const formatDate = (date: string) => {
  return new Date(date).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  })
}

// 打开新建对话框
const openCreateDialog = () => {
  editingId.value = null
  formTitle.value = ''
  formContent.value = ''
  formActive.value = true
  showDialog.value = true
}

// 打开编辑对话框
const openEditDialog = (announcement: Announcement) => {
  editingId.value = announcement.id
  formTitle.value = announcement.title
  formContent.value = announcement.content
  formActive.value = announcement.is_active
  showDialog.value = true
}

// 关闭对话框
const closeDialog = () => {
  showDialog.value = false
  editingId.value = null
  formTitle.value = ''
  formContent.value = ''
}

// 保存公告
const saveAnnouncement = async () => {
  // 校验
  if (!formTitle.value.trim()) {
    alert('请输入公告标题')
    return
  }
  if (!formContent.value.trim()) {
    alert('请输入公告内容')
    return
  }

  saving.value = true
  try {
    if (editingId.value) {
      // 编辑
      // TODO: API 调用
      // await api.put(`/api/admin/announcements/${editingId.value}`, {
      //   title: formTitle.value,
      //   content: formContent.value,
      //   is_active: formActive.value
      // })
      const index = announcements.value.findIndex(a => a.id === editingId.value)
      if (index !== -1) {
        announcements.value[index] = {
          ...announcements.value[index],
          title: formTitle.value,
          content: formContent.value,
          is_active: formActive.value
        }
      }
    } else {
      // 新建
      // TODO: API 调用
      // const response = await api.post('/api/admin/announcements', {
      //   title: formTitle.value,
      //   content: formContent.value,
      //   is_active: formActive.value
      // })
      const newAnnouncement: Announcement = {
        id: Date.now(),
        title: formTitle.value,
        content: formContent.value,
        is_active: formActive.value,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      }
      announcements.value.unshift(newAnnouncement)
    }
    closeDialog()
  } catch (error) {
    console.error('保存公告失败:', error)
    alert('保存失败，请稍后重试')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadAnnouncements()
})
</script>

<template>
  <div class="announcements-page page-container">
    <!-- 新建按钮 -->
    <button class="btn-create mobile-card" @click="openCreateDialog">
      <Plus :size="18" />
      <span>新建公告</span>
    </button>

    <!-- 公告列表 -->
    <div class="announcements-list">
      <!-- 加载状态 -->
      <div v-if="loading && announcements.length === 0" class="loading-state">
        <div class="loading-spinner"></div>
        <p>加载中...</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="announcements.length === 0" class="empty-state">
        <div class="empty-icon">📢</div>
        <p class="empty-text">暂无公告</p>
        <button class="btn-create-empty" @click="showDialog = true">
          <Plus :size="16" />
          创建第一个公告
        </button>
      </div>

      <!-- 公告卡片列表 -->
      <div v-else class="announcement-cards">
        <div
          v-for="announcement in announcements"
          :key="announcement.id"
          class="announcement-card mobile-card"
        >
          <div class="announcement-header">
            <h3 class="announcement-title">{{ announcement.title }}</h3>
            <div class="announcement-actions">
              <button
                class="icon-btn"
                @click="toggleActive(announcement)"
                :title="announcement.is_active ? '隐藏' : '显示'"
              >
                <EyeOff v-if="announcement.is_active" :size="16" />
                <Eye v-else :size="16" />
              </button>
              <button class="icon-btn" @click="openEditDialog(announcement)" title="编辑">
                <Edit :size="16" />
              </button>
              <button
                class="icon-btn icon-btn-danger"
                @click="deleteAnnouncement(announcement.id)"
                title="删除"
              >
                <Trash2 :size="16" />
              </button>
            </div>
          </div>
          <p class="announcement-content">{{ announcement.content }}</p>
          <div class="announcement-meta">
            <span class="status-badge" :class="{ active: announcement.is_active }">
              {{ announcement.is_active ? '已发布' : '草稿' }}
            </span>
            <span class="announcement-date">
              创建于 {{ formatDate(announcement.created_at) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建/编辑对话框 -->
    <Transition name="dialog">
      <div v-if="showDialog" class="dialog-overlay" @click.self="closeDialog">
        <div class="dialog-content glass-card">
          <!-- 对话框标题 -->
          <div class="dialog-header">
            <h3 class="dialog-title">{{ editingId ? '编辑公告' : '新建公告' }}</h3>
            <button class="dialog-close" @click="closeDialog">
              <X :size="18" />
            </button>
          </div>

          <!-- 对话框表单 -->
          <div class="dialog-body">
            <div class="form-group">
              <label class="form-label">公告标题</label>
              <input
                v-model="formTitle"
                type="text"
                class="form-input"
                placeholder="请输入公告标题"
                maxlength="100"
              />
            </div>

            <div class="form-group">
              <label class="form-label">公告内容</label>
              <textarea
                v-model="formContent"
                class="form-textarea"
                rows="6"
                placeholder="请输入公告内容"
                maxlength="1000"
              ></textarea>
            </div>

            <div class="form-group">
              <label class="form-checkbox">
                <input
                  v-model="formActive"
                  type="checkbox"
                  class="checkbox-input"
                />
                <span class="checkbox-label">立即发布</span>
              </label>
            </div>
          </div>

          <!-- 对话框底部 -->
          <div class="dialog-footer">
            <button class="btn-cancel" @click="closeDialog" :disabled="saving">
              取消
            </button>
            <button class="btn-primary" @click="saveAnnouncement" :disabled="saving">
              <RefreshCw v-if="saving" :size="16" class="spin" />
              <span v-else>{{ editingId ? '保存' : '发布' }}</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.announcements-page {
  background: var(--bg-primary);
}

/* ===== 顶部栏 ===== */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
}

/* 桌面端：隐藏此 top-bar（使用 Layout 的 header） */
@media (min-width: 1024px) {
  .top-bar {
    display: none;
  }
}

.top-bar-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.menu-btn {
  display: none;
}

@media (max-width: 768px) {
  .menu-btn {
    display: flex;
  }
}

.top-icon {
  color: var(--primary);
}

.top-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
  line-height: var(--line-height-tight);
}

.page-subtitle {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin: 0;
}

.top-bar-right {
  display: flex;
  gap: var(--space-2);
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: var(--glass-gradient);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.icon-btn:active {
  transform: scale(0.95);
  background: var(--bg-card-hover);
}

.icon-btn.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.icon-btn-danger:hover {
  background: var(--danger-bg);
  color: var(--danger);
}

/* ===== 新建按钮 ===== */
.btn-create {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--primary);
  color: white;
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-create:active {
  transform: scale(0.98);
  background: var(--primary-active);
}

/* ===== 加载状态 ===== */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
  color: var(--text-tertiary);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-subtle);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* ===== 空状态 ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
}

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

.empty-text {
  color: var(--text-tertiary);
  margin: 0;
}

.btn-create-empty {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--primary-bg);
  color: var(--primary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-create-empty:active {
  background: var(--primary);
  color: white;
}

/* ===== 公告列表 ===== */
.announcement-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.announcement-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.announcement-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.announcement-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.announcement-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
}

.announcement-content {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  line-height: 1.6;
  margin: 0;
}

.announcement-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.status-badge {
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  background: var(--bg-input);
  color: var(--text-tertiary);
}

.status-badge.active {
  background: var(--success-bg);
  color: var(--success);
}

.announcement-date {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin-left: auto;
}

/* ===== 响应式 ===== */
@media (max-width: 480px) {
  .announcement-header {
    flex-wrap: wrap;
  }

  .announcement-actions {
    margin-left: auto;
  }

  .announcement-meta {
    flex-wrap: wrap;
  }

  .announcement-date {
    margin-left: 0;
  }
}

/* ===== 新建/编辑对话框 ===== */
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(4px);
}

.dialog-content {
  width: 100%;
  max-width: 480px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border-subtle);
}

.dialog-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
}

.dialog-close {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast) ease;
}

.dialog-close:hover {
  background: var(--bg-card-hover);
  color: var(--text-secondary);
}

.dialog-body {
  padding: 1.5rem;
  overflow-y: auto;
  flex: 1;
}

.form-group {
  margin-bottom: 1rem;
}

.form-label {
  display: block;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}

.form-input,
.form-textarea {
  width: 100%;
  padding: 0.75rem 1rem;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--font-size-md);
  transition: all var(--transition-fast) ease;
}

.form-input:focus,
.form-textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.1);
}

.form-input::placeholder,
.form-textarea::placeholder {
  color: var(--text-tertiary);
}

.form-textarea {
  resize: vertical;
  min-height: 120px;
}

.form-checkbox {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  cursor: pointer;
}

.checkbox-input {
  width: 18px;
  height: 18px;
  accent-color: var(--primary);
}

.checkbox-label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--border-subtle);
}

.btn-cancel {
  padding: 0.625rem 1.25rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-cancel:hover:not(:disabled) {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}

.btn-cancel:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  border-radius: var(--radius-sm);
  border: none;
  background: var(--primary);
  color: white;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-primary:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-primary:active:not(:disabled) {
  transform: scale(0.98);
}

.btn-primary:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 对话框过渡动画 */
.dialog-enter-active,
.dialog-leave-active {
  transition: all 0.25s ease;
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}

.dialog-enter-from .dialog-content,
.dialog-leave-to .dialog-content {
  transform: scale(0.95);
}

/* 对话框移动端适配 */
@media (max-width: 480px) {
  .dialog-overlay {
    padding: 0.5rem;
    align-items: flex-end;
  }

  .dialog-content {
    max-width: 100%;
    max-height: 85vh;
    border-radius: var(--radius-md) var(--radius-md) 0 0;
  }

  .dialog-header,
  .dialog-body,
  .dialog-footer {
    padding-left: 1rem;
    padding-right: 1rem;
  }
}
</style>
