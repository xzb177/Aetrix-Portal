<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Megaphone, Plus, Edit, Trash2, Eye, EyeOff, Menu, RefreshCw } from 'lucide-vue-next'

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

onMounted(() => {
  loadAnnouncements()
})
</script>

<template>
  <div class="announcements-page page-container">
    <!-- 顶部栏 -->
    <div class="top-bar">
      <div class="top-bar-left">
        <button class="icon-btn menu-btn">
          <Menu :size="20" />
        </button>
        <Megaphone :size="22" class="top-icon" />
        <div class="top-titles">
          <h1 class="page-title">公告管理</h1>
          <p class="page-subtitle">发布和管理站点公告</p>
        </div>
      </div>
      <div class="top-bar-right">
        <button class="icon-btn" @click="loadAnnouncements" :class="{ spinning: loading }">
          <RefreshCw :size="18" />
        </button>
        <button class="icon-btn" @click="showMoreMenu = !showMoreMenu">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="1" />
            <circle cx="19" cy="12" r="1" />
            <circle cx="5" cy="12" r="1" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 新建按钮 -->
    <button class="btn-create mobile-card" @click="showDialog = true">
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
              <button class="icon-btn" title="编辑">
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
</style>
