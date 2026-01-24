<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh, Film, Clock, CircleCheck, CircleClose, Loading,
  Search, Delete, View, Edit, Download, Picture, User, UserFilled
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
const configLoaded = ref(false)
const configError = ref('')

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

// 状态标签配置
const getStatusConfig = (status: string) => {
  const statusMap: Record<string, { label: string; color: string; bgColor: string; icon: any }> = {
    pending: { label: '待审核', color: '#f59e0b', bgColor: 'rgba(245, 158, 11, 0.12)', icon: Clock },
    approved: { label: '处理中', color: '#3b82f6', bgColor: 'rgba(59, 130, 246, 0.12)', icon: Loading },
    completed: { label: '已完成', color: '#10b981', bgColor: 'rgba(16, 185, 129, 0.12)', icon: CircleCheck },
    rejected: { label: '已拒绝', color: '#ef4444', bgColor: 'rgba(239, 68, 68, 0.12)', icon: CircleClose }
  }
  return statusMap[status] || { label: status, color: '#6b7280', bgColor: 'rgba(107, 114, 128, 0.12)', icon: Film }
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

// 加载 MoviePilot 配置
const loadMoviePilotConfig = async () => {
  try {
    const res = await getMoviePilotConfig()
    moviePilotConfig.value = {
      url: res.url || '',
      api_token: res.api_token || ''
    }
    configLoaded.value = true
    if (!res.url || !res.api_token) {
      configError.value = '请在系统配置中设置 MoviePilot'
    }
  } catch (error: any) {
    configError.value = '加载配置失败'
    console.error('加载 MoviePilot 配置失败:', error)
  }
}

onMounted(() => {
  loadStats()
  loadRequests()
  loadMoviePilotConfig()
})
</script>

<template>
  <div class="media-requests-page">
    <!-- 顶部操作栏 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">求片管理</h1>
        <p class="page-subtitle">管理和处理用户的求片请求</p>
      </div>
      <button class="btn-refresh" @click="loadRequests" :class="{ spinning: loading }">
        <Refresh :size="16" />
        刷新
      </button>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card" :class="{ 'active': filters.status === '' }" @click="handleStatClick('')">
        <div class="stat-icon-wrapper">
          <div class="stat-icon default">
            <Film :size="20" />
          </div>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.total }}</div>
          <div class="stat-label">全部求片</div>
        </div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'pending' }" @click="handleStatClick('pending')">
        <div class="stat-icon-wrapper">
          <div class="stat-icon warning">
            <Clock :size="20" />
          </div>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.pending }}</div>
          <div class="stat-label">待审核</div>
        </div>
        <div class="stat-indicator" v-if="stats.pending > 0"></div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'approved' }" @click="handleStatClick('approved')">
        <div class="stat-icon-wrapper">
          <div class="stat-icon info">
            <Loading :size="20" />
          </div>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.approved }}</div>
          <div class="stat-label">处理中</div>
        </div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'completed' }" @click="handleStatClick('completed')">
        <div class="stat-icon-wrapper">
          <div class="stat-icon success">
            <CircleCheck :size="20" />
          </div>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.completed }}</div>
          <div class="stat-label">已完成</div>
        </div>
      </div>
      <div class="stat-card" :class="{ 'active': filters.status === 'rejected' }" @click="handleStatClick('rejected')">
        <div class="stat-icon-wrapper">
          <div class="stat-icon danger">
            <CircleClose :size="20" />
          </div>
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.rejected }}</div>
          <div class="stat-label">已拒绝</div>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-left">
        <div class="search-box">
          <Search :size="16" class="search-icon" />
          <input
            v-model="filters.search"
            type="text"
            placeholder="搜索影片名称..."
            class="search-input"
            @keyup.enter="handleFilter"
          />
        </div>
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
          <Search :size="14" />
          搜索
        </button>
        <button class="btn-secondary" @click="handleResetFilter">
          重置
        </button>
      </div>
    </div>

    <!-- 求片列表 -->
    <div class="requests-container">
      <div v-loading="loading" class="requests-wrapper">
        <!-- 空状态 -->
        <div v-if="requests.length === 0 && !loading" class="empty-state">
          <div class="empty-icon">
            <Film :size="64" />
          </div>
          <h3 class="empty-title">暂无求片记录</h3>
          <p class="empty-desc">当用户提交求片请求时，会显示在这里</p>
        </div>

        <!-- 求片卡片网格 -->
        <div v-else class="requests-grid">
          <div
            v-for="request in requests"
            :key="request.id"
            class="request-card"
            :class="[`status-${request.status}`]"
          >
            <!-- 海报区域 -->
            <div class="card-poster">
              <img
                v-if="request.poster_url"
                :src="request.poster_url"
                :alt="request.movie_name"
                class="poster-image"
              />
              <div v-else class="poster-placeholder">
                <Picture :size="32" />
              </div>
              <!-- 状态徽章 -->
              <div class="status-badge" :style="{
                backgroundColor: getStatusConfig(request.status).bgColor,
                color: getStatusConfig(request.status).color
              }">
                <component :is="getStatusConfig(request.status).icon" :size="12" />
                {{ getStatusConfig(request.status).label }}
              </div>
            </div>

            <!-- 内容区域 -->
            <div class="card-content">
              <!-- 标题 -->
              <h3 class="card-title" :title="request.movie_name">
                {{ request.movie_name }}
              </h3>

              <!-- 元信息 -->
              <div class="card-meta">
                <span v-if="request.year" class="meta-tag year">{{ request.year }}</span>
                <span v-if="request.type" class="meta-tag type">
                  {{ request.type === 'movie' ? '电影' : '剧集' }}
                </span>
                <span class="meta-tag subscriber">
                  <UserFilled :size="12" />
                  {{ request.subscriber_count || 1 }} 人订阅
                </span>
              </div>

              <!-- 用户信息 -->
              <div class="card-user">
                <User :size="12" />
                <span>{{ request.username || '未知用户' }}</span>
                <span class="user-time">{{ formatDate(request.created_at) }}</span>
              </div>

              <!-- 备注 -->
              <div class="card-note" v-if="request.note" :title="request.note">
                <span class="note-icon">💬</span>
                {{ request.note }}
              </div>

              <!-- 管理备注 -->
              <div class="card-admin-note" v-if="request.admin_note" :title="request.admin_note">
                <span class="note-icon">📝</span>
                {{ request.admin_note }}
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="card-actions">
              <button class="action-btn detail" @click="handleViewDetail(request)" title="查看详情">
                <View :size="14" />
                详情
              </button>
              <button class="action-btn subscribe" @click="handleSubscribeDialog(request)" title="添加订阅">
                <Download :size="14" />
                订阅
              </button>
              <button class="action-btn edit" @click="handleStatusDialog(request)" title="更新状态">
                <Edit :size="14" />
                状态
              </button>
              <button class="action-btn delete" @click="handleDelete(request)" title="删除">
                <Delete :size="14" />
              </button>
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
      class="detail-dialog"
    >
      <div v-if="requestDetail" class="detail-content">
        <div class="detail-poster" v-if="requestDetail.poster_url">
          <img :src="requestDetail.poster_url" :alt="requestDetail.movie_name" />
        </div>

        <div class="detail-info">
          <h2>{{ requestDetail.movie_name }}</h2>

          <div class="detail-meta">
            <div class="detail-row">
              <span class="label">类型</span>
              <span class="value">{{ requestDetail.type === 'movie' ? '电影' : '电视剧' }}</span>
            </div>
            <div class="detail-row" v-if="requestDetail.year">
              <span class="label">年份</span>
              <span class="value">{{ requestDetail.year }}</span>
            </div>
            <div class="detail-row">
              <span class="label">状态</span>
              <span class="status-tag" :style="{
                backgroundColor: getStatusConfig(requestDetail.status).bgColor,
                color: getStatusConfig(requestDetail.status).color
              }">
                <component :is="getStatusConfig(requestDetail.status).icon" :size="12" />
                {{ getStatusConfig(requestDetail.status).label }}
              </span>
            </div>
            <div class="detail-row" v-if="requestDetail.tmdb_id">
              <span class="label">TMDB ID</span>
              <span class="value">{{ requestDetail.tmdb_id }}</span>
            </div>
            <div class="detail-row" v-if="requestDetail.note">
              <span class="label">用户备注</span>
              <span class="value">{{ requestDetail.note }}</span>
            </div>
          </div>

          <div class="detail-section" v-if="subscribers.length > 0">
            <h4>
              <UserFilled :size="16" />
              订阅用户 ({{ subscribers.length }})
            </h4>
            <div class="subscribers-list">
              <span v-for="sub in subscribers" :key="sub.id" class="subscriber-tag">
                <User :size="12" />
                {{ sub.username || `用户${sub.user_id}` }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="showDetailDialog = false">关闭</el-button>
        <el-button type="primary" @click="handleSubscribeDialog(selectedRequest)">
          <Download :size="14" />
          添加到 MoviePilot
        </el-button>
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
        <el-button @click="showStatusDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleUpdateStatus">
          确认更新
        </el-button>
      </template>
    </el-dialog>

    <!-- MoviePilot 订阅对话框 -->
    <el-dialog
      v-model="showSubscribeDialog"
      title="添加到 MoviePilot 订阅"
      :width="dialogWidth"
      :close-on-click-modal="false"
    >
      <!-- 配置状态提示 -->
      <div class="config-status" :class="{ error: !!configError, success: !configError && configLoaded }">
        <span v-if="configError" class="status-text error">
          ⚠️ {{ configError }}
        </span>
        <span v-else-if="configLoaded" class="status-text success">
          ✅ 已从系统配置加载 MoviePilot 设置
        </span>
        <span v-else class="status-text loading">
          正在加载配置...
        </span>
      </div>

      <el-divider />

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
        <el-button @click="showSubscribeDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!!configError || !configLoaded"
          @click="handleAddSubscribe"
        >
          添加订阅
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 页面容器 */
.media-requests-page {
  padding: 24px;
  max-width: 1600px;
  margin: 0 auto;
}

/* 顶部操作栏 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.page-subtitle {
  margin: 0;
  font-size: 14px;
  color: var(--text-tertiary);
}

.btn-refresh {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-refresh:hover {
  border-color: var(--primary);
  color: var(--primary);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.2);
}

.btn-refresh.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  position: relative;
  background: var(--bg-card);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.stat-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.15);
}

.stat-card.active {
  border-color: var(--primary);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(99, 102, 241, 0.02));
}

.stat-icon-wrapper {
  position: relative;
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.stat-icon.default { background: linear-gradient(135deg, #6366f1, #4f46e5); }
.stat-icon.warning { background: linear-gradient(135deg, #f59e0b, #d97706); }
.stat-icon.info { background: linear-gradient(135deg, #3b82f6, #2563eb); }
.stat-icon.success { background: linear-gradient(135deg, #10b981, #059669); }
.stat-icon.danger { background: linear-gradient(135deg, #ef4444, #dc2626); }

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 13px;
  color: var(--text-tertiary);
  font-weight: 500;
}

.stat-indicator {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--warning);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.2); }
}

/* 筛选栏 */
.filter-bar {
  background: var(--bg-card);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.filter-left {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 14px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.search-input {
  padding: 10px 14px 10px 40px;
  border: 1px solid var(--border-base);
  border-radius: 10px;
  font-size: 14px;
  width: 240px;
  background: var(--bg-elevated);
  color: var(--text-primary);
  transition: all 0.2s;
}

.search-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.filter-select {
  padding: 10px 14px;
  border: 1px solid var(--border-base);
  border-radius: 10px;
  font-size: 14px;
  background: var(--bg-elevated);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
}

.filter-select:focus {
  outline: none;
  border-color: var(--primary);
}

/* 按钮 */
.btn-primary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover {
  background: var(--primary-dark);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  border-color: var(--text-tertiary);
  background: var(--bg-hover);
}

/* 求片容器 */
.requests-container {
  background: var(--bg-card);
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  overflow: hidden;
}

.requests-wrapper {
  padding: 24px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: var(--text-tertiary);
}

.empty-icon {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: var(--bg-elevated);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
  color: var(--text-tertiary);
}

.empty-title {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-secondary);
}

.empty-desc {
  margin: 0;
  font-size: 14px;
  color: var(--text-tertiary);
}

/* 求片网格 */
.requests-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 20px;
}

/* 求片卡片 */
.request-card {
  background: var(--bg-elevated);
  border-radius: 16px;
  overflow: hidden;
  display: flex;
  border: 1px solid var(--border-base);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.request-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.12);
  border-color: var(--primary);
}

/* 状态边框 */
.request-card.status-pending { border-left: 4px solid #f59e0b; }
.request-card.status-approved { border-left: 4px solid #3b82f6; }
.request-card.status-completed { border-left: 4px solid #10b981; }
.request-card.status-rejected { border-left: 4px solid #ef4444; }

/* 海报区域 */
.card-poster {
  position: relative;
  width: 140px;
  flex-shrink: 0;
}

.poster-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  min-height: 200px;
}

.poster-placeholder {
  width: 100%;
  height: 100%;
  min-height: 200px;
  background: linear-gradient(135deg, var(--bg-hover), var(--bg-elevated));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
}

/* 状态徽章 */
.status-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  backdrop-filter: blur(10px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* 内容区域 */
.card-content {
  flex: 1;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 40px;
}

.card-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.meta-tag.year {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.meta-tag.type {
  background: rgba(168, 85, 247, 0.12);
  color: #a855f7;
}

.meta-tag.subscriber {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.card-user {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-tertiary);
}

.user-time {
  margin-left: auto;
  font-size: 12px;
}

.card-note,
.card-admin-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-note {
  background: rgba(99, 102, 241, 0.06);
  color: #6366f1;
}

.card-admin-note {
  background: rgba(245, 158, 11, 0.06);
  color: #f59e0b;
}

.note-icon {
  flex-shrink: 0;
}

/* 操作按钮 */
.card-actions {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 2px;
  padding: 12px 16px;
  background: var(--bg-hover);
  border-top: 1px solid var(--border-base);
}

.action-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 8px;
  background: transparent;
  border: none;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: var(--bg-card);
}

.action-btn.detail:hover { color: #3b82f6; background: rgba(59, 130, 246, 0.1); }
.action-btn.subscribe:hover { color: #10b981; background: rgba(16, 185, 129, 0.1); }
.action-btn.edit:hover { color: #f59e0b; background: rgba(245, 158, 11, 0.1); }
.action-btn.delete:hover { color: #ef4444; background: rgba(239, 68, 68, 0.1); }

/* 分页 */
.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 20px;
  border-top: 1px solid var(--border-base);
  background: var(--bg-hover);
}

/* 详情对话框 */
.detail-content {
  display: flex;
  gap: 24px;
}

.detail-poster {
  width: 160px;
  flex-shrink: 0;
}

.detail-poster img {
  width: 100%;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

.detail-info {
  flex: 1;
}

.detail-info h2 {
  margin: 0 0 20px 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.detail-meta {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.detail-row .label {
  width: 80px;
  color: var(--text-tertiary);
  font-size: 14px;
  flex-shrink: 0;
}

.detail-row .value {
  color: var(--text-primary);
  font-size: 14px;
}

.detail-row .status-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}

.detail-section {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--border-base);
}

.detail-section h4 {
  margin: 0 0 12px 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.subscribers-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.subscriber-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: var(--bg-hover);
  border-radius: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  border: 1px solid var(--border-base);
}

/* 配置区域 */
.config-section {
  margin-bottom: 20px;
}

.config-section h4 {
  margin: 0 0 16px 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.test-connection {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.test-connection .status-tag {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}

.test-connection .status-tag.success {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.test-connection .status-tag.error {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

/* 响应式 */
@media (max-width: 768px) {
  .media-requests-page {
    padding: 16px;
  }

  .page-header {
    flex-direction: column;
    align-items: stretch;
    gap: 16px;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }

  .stat-card {
    padding: 16px;
  }

  .stat-icon {
    width: 44px;
    height: 44px;
  }

  .stat-value {
    font-size: 24px;
  }

  .requests-grid {
    grid-template-columns: 1fr;
  }

  .request-card {
    flex-direction: column;
  }

  .card-poster {
    width: 100%;
    height: 180px;
  }

  .poster-image,
  .poster-placeholder {
    min-height: 180px;
  }

  .filter-left {
    flex-direction: column;
    align-items: stretch;
  }

  .search-input,
  .filter-select {
    width: 100%;
  }

  .detail-content {
    flex-direction: column;
  }

  .detail-poster {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .card-actions {
    grid-template-columns: repeat(4, 1fr);
  }

  .action-btn {
    padding: 12px 4px;
    font-size: 11px;
  }
}

/* 配置状态提示 */
.config-status {
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  text-align: center;
}

.config-status.success {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.3);
}

.config-status.error {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
}

.status-text {
  font-size: 14px;
  font-weight: 500;
}

.status-text.success {
  color: #10b981;
}

.status-text.error {
  color: #ef4444;
}

.status-text.loading {
  color: var(--text-tertiary);
}
</style>
