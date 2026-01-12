<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Search, RefreshCw, ChevronLeft, ChevronRight, Crown, Trash2, Monitor, Menu, Eye } from 'lucide-vue-next'
import { getUsers, toggleVIP, deleteUser } from '@/api/user'
import type { User } from '@/types/user'

const router = useRouter()

const loading = ref(false)
const users = ref<User[]>([])
const pagination = ref({
  page: 1,
  page_size: 20,
  total: 0,
  total_pages: 0,
})

const searchForm = ref({
  keyword: '',
  is_vip: undefined as boolean | undefined,
  has_emby: undefined as boolean | undefined,
})

// 对话框状态
const showDeleteDialog = ref(false)
const deleteUserLoading = ref(false)
const userToDelete = ref<User | null>(null)

// 计算显示的用户名
const getDisplayName = (user: User) => {
  return user.emby_account || user.username || `ID: ${user.tg_id}`
}

// 加载用户列表
const loadUsers = async () => {
  loading.value = true
  try {
    const res = await getUsers({
      page: pagination.value.page,
      page_size: pagination.value.page_size,
      keyword: searchForm.value.keyword || undefined,
      is_vip: searchForm.value.is_vip,
      has_emby: searchForm.value.has_emby,
      sort_by: 'tg_id',
      sort_order: 'desc',
    })
    users.value = res.items
    pagination.value.total = res.total
    pagination.value.total_pages = res.total_pages
  } catch (error) {
    console.error('加载用户列表失败:', error)
  } finally {
    loading.value = false
  }
}

// 搜索
const handleSearch = () => {
  pagination.value.page = 1
  loadUsers()
}

// 重置搜索
const handleReset = () => {
  searchForm.value = {
    keyword: '',
    is_vip: undefined,
    has_emby: undefined,
  }
  pagination.value.page = 1
  loadUsers()
}

// 分页变化
const handlePageChange = (page: number) => {
  pagination.value.page = page
  loadUsers()
}

const handleSizeChange = (e: Event) => {
  const size = Number((e.target as HTMLSelectElement).value)
  pagination.value.page_size = size
  pagination.value.page = 1
  loadUsers()
}

// VIP 切换
const handleToggleVIP = async (user: User) => {
  try {
    await toggleVIP(user.tg_id)
    loadUsers()
  } catch (error) {
    console.error('切换 VIP 失败:', error)
  }
}

// 删除用户
const handleDeleteClick = (user: User) => {
  userToDelete.value = user
  showDeleteDialog.value = true
}

const confirmDelete = async () => {
  if (!userToDelete.value) return

  deleteUserLoading.value = true
  try {
    await deleteUser(userToDelete.value.tg_id)
    showDeleteDialog.value = false
    loadUsers()
  } catch (error) {
    console.error('删除用户失败:', error)
  } finally {
    deleteUserLoading.value = false
  }
}

// 格式化时长
const formatMinutes = (minutes: number) => {
  if (minutes < 60) return `${minutes}分钟`
  return `${(minutes / 60).toFixed(1)}小时`
}

// 格式化数字
const formatNumber = (num: number) => {
  return num.toLocaleString()
}

// 分页按钮
const pageNumbers = computed(() => {
  const current = pagination.value.page
  const total = pagination.value.total_pages
  const delta = 2
  const range = []

  for (let i = Math.max(2, current - delta); i <= Math.min(total - 1, current + delta); i++) {
    range.push(i)
  }

  if (current - delta > 2) {
    range.unshift(-1)
  }
  if (current + delta < total - 1) {
    range.push(-1)
  }

  return range
})

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

onMounted(() => {
  loadUsers()
})
</script>

<template>
  <div class="users-page page-container">
    <!-- 搜索筛选卡片 -->
    <div class="filter-card mobile-card">
      <div class="search-box">
        <Search :size="18" class="search-icon" />
        <input
          v-model="searchForm.keyword"
          type="text"
          class="search-input"
          placeholder="搜索用户ID或Emby账号..."
          @keyup.enter="handleSearch"
        />
        <button class="btn-search" @click="handleSearch">搜索</button>
      </div>

      <div class="filter-row">
        <select v-model="searchForm.is_vip" class="filter-select">
          <option :value="undefined">全部VIP状态</option>
          <option :value="true">VIP用户</option>
          <option :value="false">普通用户</option>
        </select>

        <select v-model="searchForm.has_emby" class="filter-select">
          <option :value="undefined">全部Emby绑定</option>
          <option :value="true">已绑定</option>
          <option :value="false">未绑定</option>
        </select>

        <button class="btn-reset" @click="handleReset">重置</button>
      </div>
    </div>

    <!-- 移动端卡片列表 -->
    <div class="users-list mobile-only">
      <!-- 加载状态 -->
      <div v-if="loading && users.length === 0" class="loading-state">
        <div class="loading-spinner"></div>
        <p>加载中...</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="users.length === 0" class="empty-state">
        <div class="empty-icon">👥</div>
        <p class="empty-text">暂无用户数据</p>
      </div>

      <!-- 用户卡片 -->
      <div v-else class="user-cards">
        <div
          v-for="user in users"
          :key="user.tg_id"
          class="user-card mobile-card"
          @click="router.push(`/users/${user.tg_id}`)"
        >
          <div class="user-card-header">
            <div class="user-id-wrapper">
              <span class="user-id">ID: {{ user.tg_id }}</span>
              <span :class="['vip-tag', user.is_vip ? 'vip-active' : 'vip-normal']">
                <Crown :size="12" />
                {{ user.is_vip ? 'VIP' : '普通' }}
              </span>
            </div>
            <button
              class="icon-btn-sm"
              @click.stop="handleToggleVIP(user)"
              :title="user.is_vip ? '取消VIP' : '设为VIP'"
            >
              <Crown :size="14" />
            </button>
          </div>

          <div class="user-card-body">
            <div class="user-info-row">
              <span class="user-label">Emby账号</span>
              <span class="user-value">{{ user.emby_account || '-' }}</span>
            </div>
            <div class="user-info-row">
              <span class="user-label">魔力值</span>
              <span class="user-value">{{ formatNumber(user.points) }}</span>
            </div>
            <div class="user-info-row">
              <span class="user-label">银行存款</span>
              <span class="user-value">{{ formatNumber(user.bank_points) }}</span>
            </div>
            <div class="user-info-row">
              <Eye :size="14" class="row-icon" />
              <span class="user-label">观影时长</span>
              <span class="user-value">{{ formatMinutes(user.total_watch_minutes) }}</span>
            </div>
            <div class="user-info-row">
              <span class="user-label">签到天数</span>
              <span class="user-value">{{ user.total_checkin_days }} 天</span>
            </div>
          </div>

          <div class="user-card-footer">
            <button
              class="btn-delete"
              @click.stop="handleDeleteClick(user)"
            >
              <Trash2 :size="14" />
              删除用户
            </button>
            <button
              class="btn-view"
              @click.stop="router.push(`/users/${user.tg_id}`)"
            >
              查看详情
            </button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="pagination.total > 0" class="pagination">
        <span class="pagination-info">共 {{ pagination.total }} 条</span>
        <div class="pagination-controls">
          <select
            v-model="pagination.page_size"
            class="page-size-select"
            @change="handleSizeChange"
          >
            <option :value="10">10</option>
            <option :value="20">20</option>
            <option :value="50">50</option>
          </select>
          <button
            class="page-btn"
            :disabled="pagination.page <= 1"
            @click="handlePageChange(pagination.page - 1)"
          >
            <ChevronLeft :size="16" />
          </button>
          <span class="page-current">{{ pagination.page }}</span>
          <button
            class="page-btn"
            :disabled="pagination.page >= pagination.total_pages"
            @click="handlePageChange(pagination.page + 1)"
          >
            <ChevronRight :size="16" />
          </button>
        </div>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <div v-if="showDeleteDialog" class="modal-overlay" @click.self="showDeleteDialog = false">
      <div class="modal-content modal-small">
        <div class="delete-header">
          <div class="delete-icon">
            <Trash2 :size="24" />
          </div>
          <div>
            <h3 class="delete-title">确认删除</h3>
            <p class="delete-subtitle">此操作不可恢复</p>
          </div>
        </div>
        <p class="delete-message">
          确定要删除用户 <span class="delete-username">{{ userToDelete ? getDisplayName(userToDelete) : '' }}</span> 吗？
        </p>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showDeleteDialog = false" :disabled="deleteUserLoading">
            取消
          </button>
          <button class="btn-danger" @click="confirmDelete" :disabled="deleteUserLoading">
            {{ deleteUserLoading ? '删除中...' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.users-page {
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

.icon-btn-sm {
  width: 32px;
  height: 32px;
  padding: 0;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-btn-sm:active {
  background: var(--primary-bg);
  color: var(--primary);
}

/* ===== 筛选卡片 ===== */
.filter-card {
  padding: var(--space-4);
}

.search-box {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
}

.search-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.btn-search {
  padding: var(--space-2) var(--space-3);
  background: var(--primary);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
}

.filter-row {
  display: flex;
  gap: var(--space-2);
}

.filter-select {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  background: var(--bg-input);
  outline: none;
}

.btn-reset {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  background: var(--bg-input);
  cursor: pointer;
}

/* ===== 用户列表 ===== */
.users-list {
  display: flex;
  flex-direction: column;
}

.mobile-only {
  display: flex;
}

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

.user-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.user-card {
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.user-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.user-id-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
}

.user-id {
  font-family: monospace;
  font-size: var(--font-size-md);
  background: var(--primary-bg);
  color: var(--primary);
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
}

.vip-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.vip-active {
  background: rgba(245, 158, 11, 0.15);
  color: var(--warning);
}

.vip-normal {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-tertiary);
}

.user-card-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.user-info-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.row-icon {
  color: var(--text-tertiary);
}

.user-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  min-width: 70px;
}

.user-value {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.user-card-footer {
  display: flex;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.btn-delete, .btn-view {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
}

.btn-delete {
  background: var(--danger-bg);
  color: var(--danger);
}

.btn-view {
  background: var(--primary-bg);
  color: var(--primary);
}

/* ===== 分页 ===== */
.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) 0;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.pagination-info {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.page-size-select {
  padding: var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  color: var(--text-primary);
  background: var(--bg-input);
}

.page-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-primary);
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-current {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  min-width: 24px;
  text-align: center;
}

/* ===== 弹窗 ===== */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  z-index: var(--z-modal);
}

.modal-content {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  width: 100%;
  max-width: 360px;
}

.modal-small {
  max-width: 320px;
}

.delete-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.delete-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--danger-bg);
  color: var(--danger);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.delete-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0;
}

.delete-subtitle {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  margin: 2px 0 0 0;
}

.delete-message {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
}

.delete-username {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.modal-actions {
  display: flex;
  gap: var(--space-2);
}

.btn-secondary {
  flex: 1;
  padding: var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  background: var(--bg-input);
  cursor: pointer;
}

.btn-danger {
  flex: 1;
  padding: var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: white;
  background: var(--danger);
  cursor: pointer;
}

/* ===== 响应式 ===== */
@media (max-width: 480px) {
  .filter-row {
    flex-wrap: wrap;
  }

  .filter-select {
    min-width: 100px;
  }

  .btn-reset {
    width: 100%;
  }

  .pagination {
    flex-direction: column;
  }

  .pagination-controls {
    width: 100%;
    justify-content: center;
  }
}
</style>
