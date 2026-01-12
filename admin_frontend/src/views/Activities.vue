<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, RefreshCw, Trash2, Power } from 'lucide-vue-next'
import { http } from '@/utils/request'

interface Activity {
  id: number
  name: string
  description: string
  activity_type: string
  target_count: number
  reward_mp: number
  reward_title: string
  is_active: boolean
  start_date: string
  end_date: string
  participant_count: number
  completed_count: number
}

const loading = ref(false)
const activities = ref<Activity[]>([])

const dialogVisible = ref(false)
const formData = ref({
  name: '',
  description: '',
  activity_type: 'genre',
  filter_genre: '',
  target_count: 5,
  reward_mp: 100,
  reward_title: '',
})

const deleteDialog = ref(false)
const activityToDelete = ref<Activity | null>(null)
const deleting = ref(false)

const toastMessage = ref('')
const showToast = ref(false)

const showToastMessage = (message: string) => {
  toastMessage.value = message
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

const loadActivities = async () => {
  loading.value = true
  try {
    const res = await http.get('/activities')
    activities.value = res.items
  } catch (error) {
    console.error('加载活动列表失败:', error)
  } finally {
    loading.value = false
  }
}

const handleCreate = () => {
  formData.value = {
    name: '',
    description: '',
    activity_type: 'genre',
    filter_genre: '',
    target_count: 5,
    reward_mp: 100,
    reward_title: '',
  }
  dialogVisible.value = true
}

const handleSubmit = async () => {
  try {
    await http.post('/activities', formData.value)
    showToastMessage('活动创建成功')
    dialogVisible.value = false
    loadActivities()
  } catch (error) {
    console.error('创建活动失败:', error)
    showToastMessage('创建失败，请稍后重试')
  }
}

const handleToggleStatus = async (activity: Activity) => {
  try {
    await http.post(`/activities/${activity.id}/toggle`)
    activity.is_active = !activity.is_active
    showToastMessage(`活动已${activity.is_active ? '启用' : '禁用'}`)
  } catch (error) {
    console.error('切换活动状态失败:', error)
    showToastMessage('操作失败，请稍后重试')
  }
}

const handleDeleteClick = (activity: Activity) => {
  activityToDelete.value = activity
  deleteDialog.value = true
}

const confirmDelete = async () => {
  if (!activityToDelete.value) return

  deleting.value = true
  try {
    await http.delete(`/activities/${activityToDelete.value.id}`)
    showToastMessage('活动已删除')
    deleteDialog.value = false
    loadActivities()
  } catch (error) {
    console.error('删除活动失败:', error)
    showToastMessage('删除失败，请稍后重试')
  } finally {
    deleting.value = false
  }
}

const getTypeName = (type: string) => {
  const types: Record<string, string> = {
    genre: '类型',
    director: '导演',
    series: '系列',
    custom: '自定义',
  }
  return types[type] || type
}

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(() => {
  loadActivities()
})
</script>

<template>
  <div class="activities-page">
    <!-- 操作按钮 -->
    <div class="page-actions">
      <button class="btn-secondary btn-icon" @click="loadActivities" :disabled="loading">
        <RefreshCw :size="18" :class="{ 'animate-spin': loading }" />
        刷新
      </button>
      <button class="btn-primary" @click="handleCreate">
        <Plus :size="18" />
        创建活动
      </button>
    </div>

    <!-- 活动列表 -->
    <div class="card table-card">
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th class="table-hide-mobile">ID</th>
              <th>活动名称</th>
              <th class="table-hide-mobile">类型</th>
              <th class="table-hide-mobile">目标/奖励</th>
              <th>参与/完成</th>
              <th>状态</th>
              <th class="table-hide-mobile">开始时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody v-if="!loading && activities.length > 0">
            <tr v-for="activity in activities" :key="activity.id">
              <td class="table-hide-mobile activity-id">{{ activity.id }}</td>
              <td>
                <div class="activity-name">{{ activity.name }}</div>
                <div class="activity-desc">{{ activity.description }}</div>
              </td>
              <td class="table-hide-mobile">
                <span class="tag tag-info">{{ getTypeName(activity.activity_type) }}</span>
              </td>
              <td class="table-hide-mobile">
                <span class="text-primary">观看 {{ activity.target_count }} 部</span>
                <span v-if="activity.reward_mp" class="text-purple">/ {{ activity.reward_mp }} MP</span>
              </td>
              <td>
                <span class="text-primary">{{ activity.participant_count }}</span>
                <span class="text-muted"> / </span>
                <span class="text-success">{{ activity.completed_count }}</span>
              </td>
              <td>
                <span :class="['tag', activity.is_active ? 'tag-success' : 'tag-gray']">
                  {{ activity.is_active ? '进行中' : '已禁用' }}
                </span>
              </td>
              <td class="table-hide-mobile text-sm text-secondary">{{ formatDate(activity.start_date) }}</td>
              <td>
                <div class="action-buttons">
                  <button
                    :class="[
                      'toggle-btn',
                      activity.is_active ? 'toggle-disable' : 'toggle-enable'
                    ]"
                    @click="handleToggleStatus(activity)"
                  >
                    <Power :size="14" class="inline mr-1" />
                    {{ activity.is_active ? '禁用' : '启用' }}
                  </button>
                  <button
                    class="delete-btn-sm"
                    title="删除活动"
                    @click="handleDeleteClick(activity)"
                  >
                    <Trash2 :size="16" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
          <tbody v-else-if="loading">
            <tr v-for="i in 5" :key="i">
              <td v-for="j in 8" :key="j" class="py-4">
                <div class="skeleton-bar"></div>
              </td>
            </tr>
          </tbody>
          <tbody v-else>
            <tr>
              <td colspan="8">
                <div class="empty-state">
                  <div class="empty-state-icon">🎬</div>
                  <p class="empty-state-text">暂无活动</p>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 创建活动对话框 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="dialogVisible" class="modal-overlay" @click.self="dialogVisible = false">
        <div class="modal-content create-modal">
          <h2 class="modal-title">创建活动</h2>
          <div class="form-grid">
            <div class="form-group">
              <label class="form-label">活动名称 <span class="required">*</span></label>
              <input v-model="formData.name" type="text" placeholder="请输入活动名称" class="input" />
            </div>

            <div class="form-group">
              <label class="form-label">活动描述</label>
              <textarea
                v-model="formData.description"
                :rows="2"
                placeholder="请输入活动描述"
                class="input resize-none"
              />
            </div>

            <div class="form-row">
              <div class="form-group">
                <label class="form-label">活动类型 <span class="required">*</span></label>
                <select v-model="formData.activity_type" class="select">
                  <option value="genre">类型活动</option>
                  <option value="director">导演活动</option>
                  <option value="series">系列活动</option>
                  <option value="custom">自定义</option>
                </select>
              </div>

              <div class="form-group" v-if="formData.activity_type === 'genre'">
                <label class="form-label">类型过滤</label>
                <input v-model="formData.filter_genre" type="text" placeholder="如: Horror,Sci-Fi" class="input" />
              </div>

              <div class="form-group">
                <label class="form-label">目标数量</label>
                <input v-model.number="formData.target_count" type="number" min="1" max="100" class="input" />
              </div>

              <div class="form-group">
                <label class="form-label">奖励MP</label>
                <input v-model.number="formData.reward_mp" type="number" min="0" max="10000" class="input" />
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">奖励称号</label>
              <input v-model="formData.reward_title" type="text" placeholder="可选" class="input" />
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn-secondary" @click="dialogVisible = false">取消</button>
            <button class="btn-primary" @click="handleSubmit">确定</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 删除确认对话框 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="deleteDialog" class="modal-overlay" @click.self="deleteDialog = false">
        <div class="modal-content delete-modal">
          <div class="delete-modal-header">
            <div class="delete-modal-icon">
              <Trash2 :size="24" class="text-red-500" />
            </div>
            <div class="delete-modal-title">
              <h3 class="delete-title">确认删除</h3>
              <p class="delete-subtitle">此操作不可恢复</p>
            </div>
          </div>
          <p class="delete-message">
            确定要删除活动 <span class="delete-activity-name">"{{ activityToDelete?.name }}"</span> 吗？
          </p>
          <div class="modal-actions">
            <button class="btn-secondary" @click="deleteDialog = false" :disabled="deleting">
              取消
            </button>
            <button class="btn-danger" @click="confirmDelete" :disabled="deleting">
              <span v-if="deleting" class="loading-spinner mr-2"></span>
              确认删除
            </button>
          </div>
        </div>
      </div>
    </Transition>

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
.activities-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 操作按钮区 */
.page-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.btn-icon {
  gap: 0.5rem;
}

/* ==================== Table Card ==================== */
.table-card {
  overflow: hidden;
}

.table-wrapper {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

thead th {
  padding: 1rem 1rem;
  text-align: left;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--border-color);
  background: rgba(255, 255, 255, 0.02);
  white-space: nowrap;
}

tbody tr {
  border-bottom: 1px solid var(--border-color);
  transition: background 0.15s ease;
}

tbody tr:last-child {
  border-bottom: none;
}

tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

tbody td {
  padding: 1rem;
  font-size: 0.875rem;
  color: var(--text-primary);
  vertical-align: middle;
}

.activity-id {
  font-weight: 500;
  color: var(--brand-primary);
}

.activity-name {
  font-weight: 500;
  color: var(--text-primary);
}

.activity-desc {
  font-size: 0.75rem;
  color: var(--text-muted);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.text-primary {
  color: var(--text-primary);
}

.text-purple {
  color: #a855f7;
}

.text-muted {
  color: var(--text-muted);
}

.text-success {
  color: #10b981;
}

.text-secondary {
  color: var(--text-secondary);
}

/* ==================== Action Buttons ==================== */
.action-buttons {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.toggle-btn {
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.toggle-enable {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.toggle-enable:hover {
  background: rgba(16, 185, 129, 0.25);
}

.toggle-disable {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.toggle-disable:hover {
  background: rgba(245, 158, 11, 0.25);
}

.delete-btn-sm {
  padding: 0.5rem;
  border-radius: 0.5rem;
  border: none;
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  cursor: pointer;
  transition: all 0.2s ease;
}

.delete-btn-sm:hover {
  background: rgba(239, 68, 68, 0.25);
}

/* ==================== Skeleton ==================== */
.skeleton-bar {
  height: 16px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

@keyframes skeleton-pulse {
  0%, 100% {
    opacity: 0.5;
  }
  50% {
    opacity: 1;
  }
}

/* ==================== Modal ==================== */
.modal-content {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  padding: 1.5rem;
  max-width: 90vw;
  max-height: 90vh;
  overflow: auto;
}

.create-modal {
  max-width: 500px;
}

.modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 1.5rem;
}

.form-grid {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.required {
  color: #ef4444;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

/* ==================== Delete Modal ==================== */
.delete-modal {
  max-width: 400px;
}

.delete-modal-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.delete-modal-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: rgba(239, 68, 68, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.delete-modal-title {
  flex: 1;
}

.delete-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.delete-subtitle {
  font-size: 0.875rem;
  color: var(--text-muted);
}

.delete-message {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin-bottom: 1.5rem;
}

.delete-activity-name {
  font-weight: 500;
  color: var(--text-primary);
}

/* ==================== Mobile Responsive ==================== */
@media (max-width: 768px) {

  .header-actions {
    width: 100%;
  }

  .btn-icon, .btn-primary {
    flex: 1;
  }

  .form-row {
    grid-template-columns: 1fr;
  }

  .table-wrapper {
    margin-left: -1rem;
    margin-right: -1rem;
  }

  .table-hide-mobile {
    display: none;
  }
}
</style>
