<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh, Film, Clock, CircleCheck, CircleClose, Loading,
  Search, Delete, View, Edit, Download, Picture, User
} from '@element-plus/icons-vue'
import {
  getMediaRequests,
  getMediaRequestStats,
  updateMediaRequestStatus,
  deleteMediaRequest,
  getMediaRequestDetail,
  getRequestSubscribers,
  testMoviePilotConnection,
  addSubscribe
} from '@/api/portal'

const loading = ref(false)
const submitting = ref(false)
const requests = ref<any[]>([])
const selectedRequest = ref<any>(null)
const requestDetail = ref<any>(null)
const subscribers = ref<any[]>([])

// 筛选条件
const filters = ref({
  status: '',
  type: '',
  search: ''
})

// 分页
const pagination = ref({
  page: 1,
  pageSize: 20,
  total: 0
})

// 统计数据
const stats = ref({
  total: 0,
  pending: 0,
  approved: 0,
  completed: 0,
  rejected: 0,
  today: 0
})

// 对话框状态
const showDetailDialog = ref(false)
const showStatusDialog = ref(false)
const showSubscribeDialog = ref(false)

// 状态更新表单
const statusForm = ref({
  status: '',
  admin_note: '',
  status_remark: '',
  emby_item_id: '',
  poster_url: '',
  tmdb_id: ''
})

// MoviePilot 配置
const moviePilotConfig = ref({
  url: '',
  api_token: ''
})

// 订阅表单
const subscribeForm = ref({
  name: '',
  year: '',
  type: 'movie',
  tmdb_id: '',
  season: null,
  note: ''
})

// 测试连接状态
const testingConnection = ref(false)
const connectionStatus = ref<'idle' | 'success' | 'error'>('idle')

// 响应式检测
const isMobile = computed(() => {
  if (typeof window === 'undefined') return false
  return window.innerWidth < 768
})

const dialogWidth = computed(() => {
  if (typeof window === 'undefined') return '600px'
  if (window.innerWidth < 480) return '95%'
  if (window.innerWidth < 768) return '90%'
  return '600px'
})

// 加载统计
const loadStats = async () => {
  try {
    const response = await getMediaRequestStats()
    stats.value = response || stats.value
  } catch (error) {
    console.error('加载统计失败:', error)
  }
}

// 加载求片列表
const loadRequests = async () => {
  loading.value = true
  try {
    const res = await getMediaRequests({
      skip: (pagination.value.page - 1) * pagination.value.pageSize,
      limit: pagination.value.pageSize,
      status_filter: filters.value.status || undefined,
      type_filter: filters.value.type || undefined,
      search: filters.value.search || undefined
    })
    requests.value = res?.items || []
    pagination.value.total = res?.total || 0
  } catch (error: any) {
    console.error('加载求片列表失败:', error)
    ElMessage.error(error.response?.data?.detail || '加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

// 分页变化
const handlePageChange = (page: number) => {
  pagination.value.page = page
  loadRequests()
}

// 查看详情
const handleViewDetail = async (request: any) => {
  selectedRequest.value = request
  loading.value = true
  try {
    const [detailRes, subsRes] = await Promise.all([
      getMediaRequestDetail(request.id),
      getRequestSubscribers(request.id)
    ])
    requestDetail.value = detailRes
    subscribers.value = subsRes || []

    subscribeForm.value = {
      name: detailRes.movie_name || '',
      year: detailRes.year || '',
      type: detailRes.type || 'movie',
      tmdb_id: detailRes.tmdb_id || '',
      season: null,
      note: `求片ID: ${request.id}`
    }

    showDetailDialog.value = true
  } catch (error) {
    ElMessage.error('加载详情失败')
  } finally {
    loading.value = false
  }
}

// 打开状态对话框
const handleStatusDialog = (request: any) => {
  selectedRequest.value = request
  statusForm.value = {
    status: request.status,
    admin_note: request.admin_note || '',
    status_remark: request.status_remark || '',
    emby_item_id: request.emby_item_id || '',
    poster_url: request.poster_url || '',
    tmdb_id: request.tmdb_id || ''
  }
  showStatusDialog.value = true
}

// 更新状态
const handleUpdateStatus = async () => {
  submitting.value = true
  try {
    await updateMediaRequestStatus(selectedRequest.value.id, statusForm.value)
    ElMessage.success('状态已更新')
    showStatusDialog.value = false
    loadRequests()
    loadStats()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '更新失败')
  } finally {
    submitting.value = false
  }
}

// 删除求片
const handleDelete = async (request: any) => {
  try {
    await ElMessageBox.confirm(`确定要删除「${request.movie_name}」吗？`, '确认删除', {
      type: 'warning'
    })
    await deleteMediaRequest(request.id)
    ElMessage.success('已删除')
    loadRequests()
    loadStats()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

// 打开订阅对话框
const handleSubscribeDialog = (request: any) => {
  selectedRequest.value = request
  subscribeForm.value = {
    name: request.movie_name || '',
    year: request.year || '',
    type: request.type || 'movie',
    tmdb_id: request.tmdb_id || '',
    season: null,
    note: `求片ID: ${request.id}`
  }
  connectionStatus.value = 'idle'
  showSubscribeDialog.value = true
}

// 测试 MoviePilot 连接
const handleTestConnection = async () => {
  testingConnection.value = true
  connectionStatus.value = 'idle'
  try {
    const res = await testMoviePilotConnection({
      url: moviePilotConfig.value.url,
      api_token: moviePilotConfig.value.api_token
    })
    connectionStatus.value = 'success'
    ElMessage.success('连接成功')
  } catch (error: any) {
    connectionStatus.value = 'error'
    ElMessage.error(error.response?.data?.detail || '连接失败')
  } finally {
    testingConnection.value = false
  }
}

// 添加订阅
const handleAddSubscribe = async () => {
  submitting.value = true
  try {
    await addSubscribe({
      moviepilot: {
        url: moviePilotConfig.value.url,
        api_token: moviePilotConfig.value.api_token
      },
      name: subscribeForm.value.name,
      year: subscribeForm.value.year || undefined,
      type: subscribeForm.value.type,
      tmdb_id: subscribeForm.value.tmdb_id || undefined,
      season: subscribeForm.value.season || undefined,
      note: subscribeForm.value.note || undefined
    })
    ElMessage.success('订阅已添加到 MoviePilot')
    showSubscribeDialog.value = false

    if (selectedRequest.value) {
      await updateMediaRequestStatus(selectedRequest.value.id, {
        status: 'approved'
      })
      loadRequests()
      loadStats()
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '添加订阅失败')
  } finally {
    submitting.value = false
  }
}

// 状态标签
const getStatusTag = (status: string) => {
  const statusMap: Record<string, { label: string; type: any; class: string }> = {
    pending: { label: '待审核', type: 'info', class: 'status-pending' },
    approved: { label: '已批准', type: 'success', class: 'status-approved' },
    completed: { label: '已完成', type: 'success', class: 'status-completed' },
    rejected: { label: '已拒绝', type: 'danger', class: 'status-rejected' }
  }
  return statusMap[status] || { label: status, type: 'info', class: 'status-default' }
}

// 格式化日期
const formatDate = (date: string) => {
  if (!date) return '-'
  return new Date(date).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 筛选
const handleFilter = () => {
  pagination.value.page = 1
  loadRequests()
}

// 重置筛选
const handleResetFilter = () => {
  filters.value = { status: '', type: '', search: '' }
  pagination.value.page = 1
  loadRequests()
}

// 统计卡片点击
const handleStatClick = (status: string) => {
  filters.value.status = status
  handleFilter()
}

onMounted(() => {
  loadStats()
  loadRequests()
})
</script>

<template>
  <div class="media-requests-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="btn-action" @click="loadRequests" :class="{ spinning: loading }">
        <Refresh />
        刷新
      </button>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card" :class="{ 'active': filters.status === '' }" @click="handleStatClick('')">
        <div class="stat-icon default">
          <Film />
        </div>
        <div class="stat-content">
          <div class="stat-label">全部</div>
          <div class="stat-value">{{ stats.total }}</div>
        </div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'pending' }" @click="handleStatClick('pending')">
        <div class="stat-icon warning">
          <Clock />
        </div>
        <div class="stat-content">
          <div class="stat-label">待审核</div>
          <div class="stat-value">{{ stats.pending }}</div>
        </div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'approved' }" @click="handleStatClick('approved')">
        <div class="stat-icon success">
          <CircleCheck />
        </div>
        <div class="stat-content">
          <div class="stat-label">已批准</div>
          <div class="stat-value">{{ stats.approved }}</div>
        </div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'completed' }" @click="handleStatClick('completed')">
        <div class="stat-icon success">
          <CircleCheck />
        </div>
        <div class="stat-content">
          <div class="stat-label">已完成</div>
          <div class="stat-value">{{ stats.completed }}</div>
        </div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'rejected' }" @click="handleStatClick('rejected')">
        <div class="stat-icon danger">
          <CircleClose />
        </div>
        <div class="stat-content">
          <div class="stat-label">已拒绝</div>
          <div class="stat-value">{{ stats.rejected }}</div>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="admin-card filter-bar">
      <div class="filter-left">
        <input
          v-model="filters.search"
          type="text"
          placeholder="搜索影片名称..."
          class="filter-input"
          @keyup.enter="handleFilter"
        />
        <select v-model="filters.status" class="filter-select">
          <option value="">全部状态</option>
          <option value="pending">待审核</option>
          <option value="approved">已批准</option>
          <option value="completed">已完成</option>
          <option value="rejected">已拒绝</option>
        </select>
        <select v-model="filters.type" class="filter-select">
          <option value="">全部类型</option>
          <option value="movie">电影</option>
          <option value="tv">电视剧</option>
        </select>
        <button class="btn-primary" @click="handleFilter">
          <Search />
          搜索
        </button>
        <button class="btn-secondary" @click="handleResetFilter">
          重置
        </button>
      </div>
    </div>

    <!-- 求片列表 -->
    <div class="admin-card requests-card">
      <div v-loading="loading" class="requests-container">
        <div v-if="requests.length === 0 && !loading" class="empty-state">
          <Film :size="48" />
          <p class="empty-state-text">暂无求片记录</p>
        </div>

        <div v-else class="requests-list">
          <div
            v-for="request in requests"
            :key="request.id"
            class="request-item"
            :class="[`request-${request.status}`]"
          >
            <div class="request-poster" v-if="request.poster_url">
              <img :src="request.poster_url" :alt="request.movie_name" />
            </div>
            <div class="request-poster placeholder" v-else>
              <Picture />
            </div>

            <div class="request-content">
              <div class="request-header">
                <h3 class="request-title">{{ request.movie_name }}</h3>
                <span class="status-tag" :class="getStatusTag(request.status).class">
                  {{ getStatusTag(request.status).label }}
                </span>
              </div>

              <div class="request-meta">
                <span v-if="request.year" class="meta-item">{{ request.year }}</span>
                <span v-if="request.type" class="meta-item">{{ request.type === 'movie' ? '电影' : '电视剧' }}</span>
                <span class="meta-item">
                  <User :size="12" />
                  {{ request.username }}
                </span>
              </div>

              <div class="request-time">
                <Clock :size="12" />
                {{ formatDate(request.created_at) }}
              </div>

              <div class="request-note" v-if="request.note">
                备注: {{ request.note }}
              </div>

              <div class="request-actions">
                <button class="btn-icon" @click="handleViewDetail(request)" title="详情">
                  <View :size="16" />
                </button>
                <button class="btn-icon btn-primary" @click="handleSubscribeDialog(request)" title="订阅下载">
                  <Download :size="16" />
                </button>
                <button class="btn-icon" @click="handleStatusDialog(request)" title="更新状态">
                  <Edit :size="16" />
                </button>
                <button class="btn-icon btn-danger" @click="handleDelete(request)" title="删除">
                  <Delete :size="16" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div class="pagination-bar" v-if="pagination.total > 0">
        <el-pagination
          v-model:current-page="pagination.page"
          :page-size="pagination.pageSize"
          :total="pagination.total"
          layout="total, prev, pager, next"
          @current-change="handlePageChange"
        />
      </div>
    </div>

    <!-- 详情对话框 -->
    <el-dialog
      v-model="showDetailDialog"
      title="求片详情"
      :width="dialogWidth"
      :close-on-click-modal="false"
    >
      <div v-if="requestDetail" class="detail-content">
        <div class="detail-poster" v-if="requestDetail.poster_url">
          <img :src="requestDetail.poster_url" :alt="requestDetail.movie_name" />
        </div>

        <div class="detail-info">
          <h2>{{ requestDetail.movie_name }}</h2>

          <div class="detail-row">
            <span class="label">类型:</span>
            <span>{{ requestDetail.type === 'movie' ? '电影' : '电视剧' }}</span>
          </div>
          <div class="detail-row" v-if="requestDetail.year">
            <span class="label">年份:</span>
            <span>{{ requestDetail.year }}</span>
          </div>
          <div class="detail-row">
            <span class="label">状态:</span>
            <span class="status-tag" :class="getStatusTag(requestDetail.status).class">
              {{ getStatusTag(requestDetail.status).label }}
            </span>
          </div>
          <div class="detail-row" v-if="requestDetail.tmdb_id">
            <span class="label">TMDB ID:</span>
            <span>{{ requestDetail.tmdb_id }}</span>
          </div>
          <div class="detail-row" v-if="requestDetail.note">
            <span class="label">备注:</span>
            <span>{{ requestDetail.note }}</span>
          </div>

          <div class="detail-section" v-if="subscribers.length > 0">
            <h4>订阅用户 ({{ subscribers.length }})</h4>
            <div class="subscribers-list">
              <span v-for="sub in subscribers" :key="sub.id" class="subscriber-tag">
                {{ sub.username || sub.user_id }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <button class="btn-secondary" @click="showDetailDialog = false">关闭</button>
        <button class="btn-primary" @click="handleSubscribeDialog(selectedRequest)">
          <Download />
          添加到 MoviePilot
        </button>
      </template>
    </el-dialog>

    <!-- 状态更新对话框 -->
    <el-dialog
      v-model="showStatusDialog"
      title="更新状态"
      :width="dialogWidth"
      :close-on-click-modal="false"
    >
      <el-form :model="statusForm" label-width="100px">
        <el-form-item label="状态">
          <el-select v-model="statusForm.status">
            <el-option label="待审核" value="pending" />
            <el-option label="已批准" value="approved" />
            <el-option label="已完成" value="completed" />
            <el-option label="已拒绝" value="rejected" />
          </el-select>
        </el-form-item>
        <el-form-item label="管理员备注">
          <el-input v-model="statusForm.admin_note" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="状态说明">
          <el-input v-model="statusForm.status_remark" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="TMDB ID">
          <el-input v-model="statusForm.tmdb_id" />
        </el-form-item>
        <el-form-item label="海报 URL">
          <el-input v-model="statusForm.poster_url" />
        </el-form-item>
        <el-form-item label="Emby ID">
          <el-input v-model="statusForm.emby_item_id" />
        </el-form-item>
      </el-form>

      <template #footer>
        <button class="btn-secondary" @click="showStatusDialog = false">取消</button>
        <button class="btn-primary" :loading="submitting" @click="handleUpdateStatus">
          确认更新
        </button>
      </template>
    </el-dialog>

    <!-- MoviePilot 订阅对话框 -->
    <el-dialog
      v-model="showSubscribeDialog"
      title="添加到 MoviePilot 订阅"
      :width="dialogWidth"
      :close-on-click-modal="false"
    >
      <div class="config-section">
        <h4>MoviePilot 配置</h4>
        <div class="form-group">
          <label>地址</label>
          <el-input
            v-model="moviePilotConfig.url"
            placeholder="http://localhost:3000"
          />
        </div>
        <div class="form-group">
          <label>API Token</label>
          <el-input
            v-model="moviePilotConfig.api_token"
            type="password"
            placeholder="默认: moviepilot"
            show-password
          />
        </div>
        <button class="btn-secondary" @click="handleTestConnection" :loading="testingConnection">
          测试连接
        </button>
        <span v-if="connectionStatus === 'success'" class="status-tag success">连接成功</span>
        <span v-if="connectionStatus === 'error'" class="status-tag danger">连接失败</span>
      </div>

      <div class="divider"></div>

      <div class="config-section">
        <h4>订阅信息</h4>
        <div class="form-group">
          <label>影片名称</label>
          <el-input v-model="subscribeForm.name" />
        </div>
        <div class="form-group">
          <label>年份</label>
          <el-input v-model="subscribeForm.year" placeholder="2024" />
        </div>
        <div class="form-group">
          <label>类型</label>
          <el-radio-group v-model="subscribeForm.type">
            <el-radio value="movie">电影</el-radio>
            <el-radio value="tv">电视剧</el-radio>
          </el-radio-group>
        </div>
        <div class="form-group">
          <label>TMDB ID</label>
          <el-input v-model="subscribeForm.tmdb_id" placeholder="可选" />
        </div>
      </div>

      <template #footer>
        <button class="btn-secondary" @click="showSubscribeDialog = false">取消</button>
        <button class="btn-primary" :loading="submitting" @click="handleAddSubscribe">
          添加订阅
        </button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.media-requests-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

/* 操作按钮区 */
.page-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}

.btn-action {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: 6px;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-action:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-action.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  background: var(--bg-card);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--border-base);
  cursor: pointer;
  transition: all 0.2s;
}

.stat-card:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-sm);
}

.stat-card.active {
  border-color: var(--primary);
  background: var(--info-bg);
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.stat-icon.default { background: var(--text-tertiary); }
.stat-icon.warning { background: var(--warning); }
.stat-icon.success { background: var(--primary); }
.stat-icon.info { background: var(--info); }
.stat-icon.danger { background: var(--danger); }

.stat-content {
  flex: 1;
}

.stat-label {
  font-size: 12px;
  color: var(--text-tertiary);
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 筛选栏 */
.filter-bar {
  padding: 16px 20px;
  margin-bottom: 20px;
}

.filter-left {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-input {
  padding: 8px 12px;
  border: 1px solid var(--border-base);
  border-radius: 6px;
  font-size: 14px;
  width: 200px;
}

.filter-select {
  padding: 8px 12px;
  border: 1px solid var(--border-base);
  border-radius: 6px;
  font-size: 14px;
  background: var(--bg-card);
}

/* 按钮 */
.btn-primary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover {
  background: var(--primary-dark);
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--bg-card);
  color: var(--text-secondary);
  border: 1px solid var(--border-base);
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  border-color: var(--text-tertiary);
}

.btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--bg-hover);
  border: none;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-elevated);
}

.btn-icon.btn-primary {
  background: var(--primary);
  color: #fff;
}

.btn-icon.btn-primary:hover {
  background: var(--primary-dark);
}

.btn-icon.btn-danger {
  background: var(--danger);
  color: #fff;
}

.btn-icon.btn-danger:hover {
  background: var(--danger-dark);
}

/* 求片列表 */
.requests-card {
  min-height: 400px;
}

.requests-container {
  padding: 20px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-tertiary);
}

.empty-state svg {
  margin-bottom: 16px;
}

.requests-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 16px;
}

.request-item {
  display: flex;
  gap: 16px;
  padding: 16px;
  background: var(--bg-elevated);
  border-radius: 8px;
  border-left: 3px solid transparent;
  transition: all 0.2s;
}

.request-item:hover {
  background: var(--bg-hover);
  box-shadow: var(--shadow-sm);
}

.request-item.request-pending { border-left-color: var(--warning); }
.request-item.request-approved { border-left-color: var(--primary); }
.request-item.request-completed { border-left-color: var(--primary); }
.request-item.request-rejected { border-left-color: var(--danger); }

.request-poster {
  width: 80px;
  height: 120px;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
}

.request-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.request-poster.placeholder {
  background: var(--bg-elevated);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
}

.request-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.request-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.request-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.request-meta {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: var(--text-tertiary);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.request-time {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.request-note {
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--bg-card);
  padding: 6px 10px;
  border-radius: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.request-actions {
  display: flex;
  gap: 6px;
  margin-top: auto;
}

/* 分页 */
.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 16px;
  border-top: 1px solid var(--border-base);
}

/* 状态标签 */
.status-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.status-pending { background: var(--warning-bg); color: var(--warning); }
.status-approved { background: var(--info-bg); color: var(--primary); }
.status-completed { background: var(--info-bg); color: var(--primary); }
.status-rejected { background: var(--danger-bg); color: var(--danger); }
.status-default { background: var(--bg-hover); color: var(--text-tertiary); }

/* 详情对话框 */
.detail-content {
  display: flex;
  gap: 20px;
}

.detail-poster {
  width: 140px;
  flex-shrink: 0;
}

.detail-poster img {
  width: 100%;
  border-radius: 8px;
}

.detail-info {
  flex: 1;
}

.detail-info h2 {
  margin: 0 0 16px 0;
  font-size: 20px;
}

.detail-row {
  display: flex;
  margin-bottom: 10px;
}

.detail-row .label {
  width: 80px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.detail-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-base);
}

.detail-section h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
}

.subscribers-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.subscriber-tag {
  padding: 4px 10px;
  background: var(--bg-hover);
  border-radius: 12px;
  font-size: 12px;
}

/* 配置区域 */
.config-section {
  margin-bottom: 16px;
}

.config-section h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: var(--text-secondary);
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.divider {
  height: 1px;
  background: var(--bg-hover);
  margin: 16px 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .media-requests-page {
    padding: 12px;
  }

  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }

  .stat-card {
    padding: 12px;
  }

  .stat-icon {
    width: 32px;
    height: 32px;
  }

  .stat-value {
    font-size: 16px;
  }

  .requests-list {
    grid-template-columns: 1fr;
  }

  .request-item {
    flex-direction: column;
  }

  .request-poster {
    width: 100%;
    height: 160px;
  }

  .filter-left {
    flex-direction: column;
    align-items: stretch;
  }

  .filter-input,
  .filter-select {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
