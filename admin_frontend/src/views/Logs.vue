<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RefreshCw, FileText, Shield, Trash2, Lock, Bell } from 'lucide-vue-next'
import { http } from '@/utils/request'

interface AdminLog {
  id: number
  admin_username: string
  action: string
  resource: string
  resource_id: string
  details: any
  ip_address: string
  created_at: string
}

const loading = ref(false)
const logs = ref<AdminLog[]>([])

const loadLogs = async () => {
  loading.value = true
  try {
    logs.value = await http.get<AdminLog[]>('/stats/logs?limit=100')
  } catch (error) {
    console.error('加载日志失败:', error)
  } finally {
    loading.value = false
  }
}

const getActionName = (action: string) => {
  const actions: Record<string, string> = {
    login: '登录',
    logout: '登出',
    update_user: '更新用户',
    toggle_vip: '切换VIP',
    delete_user: '删除用户',
    unbind_emby: '解绑Emby',
    create_activity: '创建活动',
    update_activity: '更新活动',
    delete_activity: '删除活动',
    toggle_activity: '切换活动状态',
    update_push_config: '更新推送配置',
    change_password: '修改密码',
  }
  return actions[action] || action
}

const getActionIcon = (action: string) => {
  const icons: Record<string, any> = {
    login: Shield,
    logout: Shield,
    update_user: FileText,
    toggle_vip: Bell,
    delete_user: Trash2,
    unbind_emby: Lock,
    create_activity: FileText,
    update_activity: FileText,
    delete_activity: Trash2,
    toggle_activity: Bell,
    update_push_config: FileText,
    change_password: Lock,
  }
  return icons[action] || FileText
}

const getActionColor = (action: string) => {
  const colors: Record<string, string> = {
    login: 'tag-success',
    logout: 'tag-gray',
    toggle_vip: 'tag-warning',
    delete_user: 'tag-danger',
    create_activity: 'tag-info',
    change_password: 'tag-purple',
  }
  return colors[action] || 'tag-gray'
}

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

onMounted(() => {
  loadLogs()
})
</script>

<template>
  <div class="logs-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="btn-secondary btn-icon" @click="loadLogs" :disabled="loading">
        <RefreshCw :size="18" :class="{ 'animate-spin': loading }" />
        刷新
      </button>
    </div>

    <!-- 日志列表 -->
    <div class="card table-card">
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th class="table-hide-mobile">ID</th>
              <th class="table-hide-mobile">管理员</th>
              <th>操作</th>
              <th class="table-hide-mobile">资源</th>
              <th class="table-hide-mobile">资源ID</th>
              <th class="table-hide-mobile">详情</th>
              <th class="table-hide-mobile">IP地址</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody v-if="!loading && logs.length > 0">
            <tr v-for="log in logs" :key="log.id">
              <td class="table-hide-mobile log-id">{{ log.id }}</td>
              <td class="table-hide-mobile log-admin">{{ log.admin_username }}</td>
              <td>
                <span :class="['action-tag', getActionColor(log.action)]">
                  <component :is="getActionIcon(log.action)" :size="12" class="mr-1" />
                  {{ getActionName(log.action) }}
                </span>
              </td>
              <td class="table-hide-mobile log-resource">{{ log.resource || '-' }}</td>
              <td class="table-hide-mobile log-resource-id">{{ log.resource_id || '-' }}</td>
              <td class="table-hide-mobile">
                <span v-if="log.details" class="log-details">
                  {{ JSON.stringify(log.details) }}
                </span>
                <span v-else class="log-empty">-</span>
              </td>
              <td class="table-hide-mobile log-ip">{{ log.ip_address }}</td>
              <td class="log-time">{{ formatDate(log.created_at) }}</td>
            </tr>
          </tbody>
          <tbody v-else-if="loading">
            <tr v-for="i in 8" :key="i">
              <td v-for="j in 8" :key="j" class="py-4">
                <div class="skeleton-bar"></div>
              </td>
            </tr>
          </tbody>
          <tbody v-else>
            <tr>
              <td colspan="8">
                <div class="empty-state">
                  <div class="empty-state-icon">📋</div>
                  <p class="empty-state-text">暂无日志记录</p>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== Page Layout ==================== */
.logs-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 操作按钮区 */
.page-actions {
  display: flex;
  justify-content: flex-end;
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

.log-id {
  font-weight: 500;
  color: var(--brand-primary);
}

.log-admin {
  font-weight: 500;
  color: var(--text-primary);
}

.log-resource {
  color: var(--text-secondary);
}

.log-resource-id {
  font-size: 0.75rem;
  font-family: 'Courier New', monospace;
  color: var(--text-secondary);
}

.log-details {
  display: inline-block;
  font-size: 0.75rem;
  color: var(--text-muted);
  font-family: 'Courier New', monospace;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-empty {
  color: var(--text-muted);
}

.log-ip {
  font-size: 0.75rem;
  font-family: 'Courier New', monospace;
  color: var(--text-muted);
}

.log-time {
  color: var(--text-secondary);
}

/* ==================== Action Tag ==================== */
.action-tag {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.625rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
}

.mr-1 {
  margin-right: 0.25rem;
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

/* ==================== Mobile Responsive ==================== */
@media (max-width: 640px) {

  .page-title {
    font-size: 1.25rem;
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
