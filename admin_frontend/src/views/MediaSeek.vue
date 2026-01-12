<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { Film, Check, X, RefreshCw, Filter, Eye } from 'lucide-vue-next'

// ==================== 类型定义 ====================
interface MediaSeek {
  id: number
  title: string
  description: string
  year?: string
  type?: string
  userId: number
  userName: string
  nickName: string
  status: number  // 0=待处理, 1=已处理, 2=下载中, -1=已取消
  statusRemark?: string
  seekCount: number
  createdAt: string
  updatedAt: string
}

// ==================== 数据状态 ====================
const seeks = ref<MediaSeek[]>([])
const total = ref(0)
const loading = ref(false)

// 分页和筛选
const currentPage = ref(1)
const pageSize = ref(10)
const statusFilter = ref<number | null>(null)
const searchKeyword = ref('')

// 状态弹窗
const showDetailModal = ref(false)
const showStatusModal = ref(false)
const selectedSeek = ref<MediaSeek | null>(null)
const statusForm = ref({
  status: 1,
  remark: ''
})

// ==================== 计算属性 ====================
const totalPages = computed(() => Math.ceil(total.value / pageSize.value))

const statusMap: Record<number, { text: string; class: string }> = {
  '-1': { text: '已取消', class: 'status-cancelled' },
  '0': { text: '待处理', class: 'status-pending' },
  '1': { text: '已处理', class: 'status-completed' },
  '2': { text: '下载中', class: 'status-downloading' }
}

// ==================== 数据获取 ====================
const fetchSeeks = async () => {
  loading.value = true
  try {
    // TODO: 实际API调用
    // const response = await api.get('/api/admin/media-seek', {
    //   params: {
    //     page: currentPage.value,
    //     pageSize: pageSize.value,
    //     status: statusFilter.value,
    //     search: searchKeyword.value
    //   }
    // })
    // seeks.value = response.data.list
    // total.value = response.data.total

    // 模拟数据
    seeks.value = []
    total.value = 0
  } catch (error) {
    console.error('获取求片列表失败:', error)
  } finally {
    loading.value = false
  }
}

// ==================== 求片操作 ====================
const viewDetail = (seek: MediaSeek) => {
  selectedSeek.value = seek
  showDetailModal.value = true
}

const openStatusModal = (seek: MediaSeek) => {
  selectedSeek.value = seek
  statusForm.value = {
    status: seek.status === 0 ? 1 : seek.status,
    remark: seek.statusRemark || ''
  }
  showStatusModal.value = true
}

const updateStatus = async () => {
  if (!selectedSeek.value) return

  try {
    // TODO: API调用
    // await api.put(`/api/admin/media-seek/${selectedSeek.value.id}`, {
    //   status: statusForm.value.status,
    //   remark: statusForm.value.remark
    // })

    if (selectedSeek.value) {
      selectedSeek.value.status = statusForm.value.status
      selectedSeek.value.statusRemark = statusForm.value.remark
    }

    showStatusModal.value = false
    fetchSeeks()
  } catch (error) {
    console.error('更新状态失败:', error)
  }
}

// ==================== 搜索和分页 ====================
const handleFilter = () => {
  currentPage.value = 1
  fetchSeeks()
}

const resetFilter = () => {
  statusFilter.value = null
  searchKeyword.value = ''
  currentPage.value = 1
  fetchSeeks()
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchSeeks()
}

// ==================== 生命周期 ====================
onMounted(() => {
  fetchSeeks()
})
</script>

<template>
  <div class="media-seek">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-group">
        <Filter :size="16" />
        <select v-model.number="statusFilter" class="filter-select" @change="handleFilter">
          <option :value="null">全部状态</option>
          <option :value="0">待处理</option>
          <option :value="1">已处理</option>
          <option :value="2">下载中</option>
          <option :value="-1">已取消</option>
        </select>
      </div>
      <div class="search-group">
        <input
          v-model="searchKeyword"
          type="text"
          placeholder="搜索片名或用户..."
          class="search-input"
          @keyup.enter="handleFilter"
        />
        <button class="btn btn-secondary" @click="handleFilter">搜索</button>
        <button class="btn btn-ghost" @click="resetFilter">重置</button>
      </div>
    </div>

    <!-- 数据列表 -->
    <div class="seek-list">
      <div v-if="loading" class="loading">加载中...</div>
      <div v-else-if="seeks.length === 0" class="empty">暂无求片记录</div>

      <div
        v-for="seek in seeks"
        :key="seek.id"
        class="seek-card"
      >
        <div class="seek-main">
          <div class="seek-poster">
            <Film :size="32" />
          </div>
          <div class="seek-info">
            <div class="seek-header">
              <h3 class="seek-title">{{ seek.title }}</h3>
              <span :class="['status-badge', statusMap[seek.status]?.class]">
                {{ statusMap[seek.status]?.text }}
              </span>
            </div>
            <div class="seek-meta">
              <span v-if="seek.year">{{ seek.year }}</span>
              <span v-if="seek.type">{{ seek.type }}</span>
              <span>{{ seek.userName || seek.nickName }}</span>
              <span>{{ seek.seekCount }} 人同求</span>
            </div>
            <p v-if="seek.description" class="seek-description">{{ seek.description }}</p>
          </div>
        </div>
        <div class="seek-actions">
          <button class="icon-btn" @click="viewDetail(seek)" title="查看详情">
            <Eye :size="16" />
          </button>
          <button class="icon-btn" @click="openStatusModal(seek)" title="更新状态">
            <Check :size="16" />
          </button>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div class="pagination" v-if="totalPages > 1">
      <button
        :disabled="currentPage === 1"
        class="pagination-btn"
        @click="handlePageChange(currentPage - 1)"
      >
        上一页
      </button>
      <span class="pagination-info">{{ currentPage }} / {{ totalPages }}</span>
      <button
        :disabled="currentPage === totalPages"
        class="pagination-btn"
        @click="handlePageChange(currentPage + 1)"
      >
        下一页
      </button>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="showDetailModal && selectedSeek" class="modal-overlay" @click.self="showDetailModal = false">
      <div class="modal">
        <div class="modal-header">
          <h2>求片详情</h2>
          <button class="icon-btn" @click="showDetailModal = false">
            <X :size="20" />
          </button>
        </div>
        <div class="modal-body">
          <div class="detail-row">
            <span class="detail-label">片名</span>
            <span class="detail-value">{{ selectedSeek.title }}</span>
          </div>
          <div v-if="selectedSeek.year" class="detail-row">
            <span class="detail-label">年份</span>
            <span class="detail-value">{{ selectedSeek.year }}</span>
          </div>
          <div v-if="selectedSeek.type" class="detail-row">
            <span class="detail-label">类型</span>
            <span class="detail-value">{{ selectedSeek.type }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">发起用户</span>
            <span class="detail-value">{{ selectedSeek.userName || selectedSeek.nickName }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">同求人数</span>
            <span class="detail-value">{{ selectedSeek.seekCount }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">当前状态</span>
            <span :class="['detail-value', 'status-badge', statusMap[selectedSeek.status]?.class]">
              {{ statusMap[selectedSeek.status]?.text }}
            </span>
          </div>
          <div v-if="selectedSeek.statusRemark" class="detail-row">
            <span class="detail-label">状态备注</span>
            <span class="detail-value">{{ selectedSeek.statusRemark }}</span>
          </div>
          <div v-if="selectedSeek.description" class="detail-row">
            <span class="detail-label">描述</span>
            <span class="detail-value">{{ selectedSeek.description }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">创建时间</span>
            <span class="detail-value">{{ selectedSeek.createdAt }}</span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showDetailModal = false">关闭</button>
          <button class="btn btn-primary" @click="showDetailModal = false; openStatusModal(selectedSeek!)">
            更新状态
          </button>
        </div>
      </div>
    </div>

    <!-- 状态更新弹窗 -->
    <div v-if="showStatusModal && selectedSeek" class="modal-overlay" @click.self="showStatusModal = false">
      <div class="modal modal-small">
        <div class="modal-header">
          <h2>更新状态</h2>
          <button class="icon-btn" @click="showStatusModal = false">
            <X :size="20" />
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>状态</label>
            <select v-model.number="statusForm.status" class="input">
              <option :value="1">已处理</option>
              <option :value="2">下载中</option>
              <option :value="-1">已取消</option>
            </select>
          </div>
          <div class="form-group">
            <label>备注</label>
            <textarea v-model="statusForm.remark" class="input" rows="3" placeholder="状态备注信息"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showStatusModal = false">取消</button>
          <button class="btn btn-primary" @click="updateStatus">确定</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.media-seek {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  background: white;
  padding: 1rem;
  border-radius: 12px;
  border: 1px solid #e8edf3;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.filter-select {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 0.875rem;
}

.search-group {
  display: flex;
  gap: 0.5rem;
}

.search-input {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 0.875rem;
  min-width: 200px;
}

/* 求片列表 */
.seek-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.seek-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  transition: all 0.2s ease;
}

.seek-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.seek-main {
  display: flex;
  gap: 1rem;
  flex: 1;
}

.seek-poster {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.1) 0%, rgba(103, 58, 183, 0.1) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #4CAF50;
  flex-shrink: 0;
}

.seek-info {
  flex: 1;
}

.seek-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.375rem;
}

.seek-title {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

.seek-meta {
  display: flex;
  gap: 0.75rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.seek-description {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin: 0.375rem 0 0 0;
}

.seek-actions {
  display: flex;
  gap: 0.5rem;
}

/* 状态徽章 */
.status-badge {
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-pending {
  background: rgba(255, 152, 0, 0.15);
  color: #FF9800;
}

.status-completed {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.status-downloading {
  background: rgba(33, 150, 243, 0.15);
  color: #2196F3;
}

.status-cancelled {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
}

.pagination-btn {
  padding: 0.5rem 1rem;
  border: 1px solid var(--border-color);
  background: white;
  border-radius: 8px;
  cursor: pointer;
}

.pagination-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pagination-info {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

/* 按钮 */
.btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  border-radius: 8px;
  border: none;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-primary {
  background: var(--gradient-brand);
  color: white;
}

.btn-secondary {
  background: #f1f5f9;
  color: var(--text-secondary);
}

.btn-ghost {
  background: transparent;
  color: var(--text-muted);
}

.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* 模态框 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 480px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-small {
  max-width: 400px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.25rem;
  border-bottom: 1px solid #f1f5f9;
}

.modal-header h2 {
  font-size: 1.125rem;
  font-weight: 600;
  margin: 0;
}

.modal-body {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid #f1f5f9;
}

/* 详情 */
.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0;
  border-bottom: 1px solid #f8fafc;
}

.detail-label {
  font-weight: 500;
  color: var(--text-muted);
}

.detail-value {
  color: var(--text-primary);
}

/* 表单 */
.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.input {
  padding: 0.625rem 0.875rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 0.875rem;
}

.input:focus {
  outline: none;
  border-color: #4CAF50;
}

.loading, .empty {
  text-align: center;
  padding: 3rem;
  color: var(--text-muted);
}
</style>
