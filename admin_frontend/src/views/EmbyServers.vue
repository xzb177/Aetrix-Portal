<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  RefreshCw,
  Plus,
  Edit,
  Trash2,
  Server,
  Check,
  X,
  Save,
  Users,
  Link,
  Zap,
  Database,
  RotateCw,
  Scan,
} from 'lucide-vue-next'
import {
  getEmbyServers,
  createEmbyServer,
  updateEmbyServer,
  deleteEmbyServer,
  syncEmbyServer,
  testEmbyServer,
  getSubscriptionPlans,
  getPlanServers,
  addServerToPlan,
  removeServerFromPlan,
} from '@/api/portal'
import { http } from '@/utils/request'

const loading = ref(false)
const syncing = ref<number | null>(null)
const testing = ref(false)
const servers = ref<any[]>([])
const plans = ref<any[]>([])

// 对话框状态
const showServerDialog = ref(false)
const showDeleteDialog = ref(false)
const showPlanDialog = ref(false)
const editingServer = ref<any>(null)
const serverToDelete = ref<any>(null)
const saving = ref(false)
const selectedServerForPlans = ref<any>(null)

// 表单数据
const serverForm = ref({
  name: '',
  url: '',
  api_key: '',
  max_users: 0,
  is_active: true,
})

// 关联套餐数据
const serverPlans = ref<any[]>([])

// 媒体库管理
const showLibraryDialog = ref(false)
const selectedServerForLibraries = ref<any>(null)
const libraries = ref<any[]>([])
const refreshingLibrary = ref<string | null>(null)
const scanningLibrary = ref<string | null>(null)

// 显示提示
const showToast = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error' | 'warning' | 'info'>('success')

const showToastMessage = (message: string, type: 'success' | 'error' | 'warning' | 'info') => {
  toastMessage.value = message
  toastType.value = type
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

// 加载服务器列表
const loadServers = async () => {
  loading.value = true
  try {
    const res = await getEmbyServers()
    servers.value = res
  } catch (error) {
    console.error('加载服务器列表失败:', error)
    showToastMessage('加载失败，请稍后重试', 'error')
  } finally {
    loading.value = false
  }
}

// 加载套餐列表
const loadPlans = async () => {
  try {
    const res = await getSubscriptionPlans()
    plans.value = res
  } catch (error) {
    console.error('加载套餐列表失败:', error)
  }
}

// 打开创建服务器对话框
const handleCreateServer = () => {
  editingServer.value = null
  serverForm.value = {
    name: '',
    url: '',
    api_key: '',
    max_users: 0,
    is_active: true,
  }
  showServerDialog.value = true
}

// 打开编辑服务器对话框
const handleEditServer = (server: any) => {
  editingServer.value = server
  serverForm.value = {
    name: server.name,
    url: server.url,
    api_key: server.api_key,
    max_users: server.max_users,
    is_active: server.is_active,
  }
  showServerDialog.value = true
}

// 测试连接
const handleTestConnection = async () => {
  testing.value = true
  try {
    await testEmbyServer({
      url: serverForm.value.url,
      api_key: serverForm.value.api_key,
    })
    showToastMessage('连接测试成功', 'success')
  } catch (error) {
    console.error('连接测试失败:', error)
    showToastMessage('连接测试失败，请检查配置', 'error')
  } finally {
    testing.value = false
  }
}

// 保存服务器
const handleSaveServer = async () => {
  saving.value = true
  try {
    if (editingServer.value) {
      await updateEmbyServer(editingServer.value.id, serverForm.value)
      showToastMessage('服务器更新成功', 'success')
    } else {
      await createEmbyServer(serverForm.value)
      showToastMessage('服务器创建成功', 'success')
    }
    showServerDialog.value = false
    loadServers()
  } catch (error) {
    console.error('保存服务器失败:', error)
    showToastMessage('保存失败，请稍后重试', 'error')
  } finally {
    saving.value = false
  }
}

// 同步服务器用户数
const handleSyncServer = async (serverId: number) => {
  syncing.value = serverId
  try {
    await syncEmbyServer(serverId)
    showToastMessage('同步成功', 'success')
    loadServers()
  } catch (error) {
    console.error('同步失败:', error)
    showToastMessage('同步失败，请稍后重试', 'error')
  } finally {
    syncing.value = null
  }
}

// 删除服务器
const handleDeleteServer = (server: any) => {
  serverToDelete.value = server
  showDeleteDialog.value = true
}

const confirmDelete = async () => {
  if (!serverToDelete.value) return
  try {
    await deleteEmbyServer(serverToDelete.value.id)
    showToastMessage('服务器删除成功', 'success')
    showDeleteDialog.value = false
    loadServers()
  } catch (error: any) {
    console.error('删除服务器失败:', error)
    showToastMessage(error.response?.data?.detail || '删除失败', 'error')
  }
}

// 管理套餐关联
const handleManagePlans = async (server: any) => {
  selectedServerForPlans.value = server
  await loadServerPlans(server.id)
  showPlanDialog.value = true
}

const loadServerPlans = async (serverId: number) => {
  try {
    // 获取所有套餐及其关联的服务器
    const planRelations: any[] = []
    for (const plan of plans.value) {
      const planServers = await getPlanServers(plan.id)
      const relation = planServers.find((ps: any) => ps.server_id === serverId)
      planRelations.push({
        plan_id: plan.id,
        plan_name: plan.name,
        is_linked: !!relation,
        relation_id: relation?.id,
        weight: relation?.weight || 1,
      })
    }
    serverPlans.value = planRelations
  } catch (error) {
    console.error('加载套餐关联失败:', error)
  }
}

const togglePlanLink = async (item: any) => {
  try {
    if (item.is_linked) {
      await removeServerFromPlan(item.relation_id)
      showToastMessage('已移除套餐关联', 'success')
    } else {
      await addServerToPlan(item.plan_id, { server_id: selectedServerForPlans.value.id })
      showToastMessage('已添加套餐关联', 'success')
    }
    await loadServerPlans(selectedServerForPlans.value.id)
  } catch (error) {
    console.error('操作失败:', error)
    showToastMessage('操作失败，请稍后重试', 'error')
  }
}

// 管理媒体库
const handleManageLibraries = async (server: any) => {
  selectedServerForLibraries.value = server
  await loadLibraries(server.id)
  showLibraryDialog.value = true
}

// 加载媒体库列表
const loadLibraries = async (serverId: number) => {
  try {
    const response = await http.get<{ libraries: any[] }>(`/emby-sessions/servers/${serverId}/libraries`)
    libraries.value = response.libraries || []
  } catch (error) {
    console.error('加载媒体库失败:', error)
    showToastMessage('加载媒体库失败', 'error')
  }
}

// 刷新媒体库
const handleRefreshLibrary = async (libraryId: string | null) => {
  refreshingLibrary.value = libraryId || 'all'
  try {
    const serverId = selectedServerForLibraries.value.id
    await http.post(`/emby-sessions/servers/${serverId}/libraries/refresh`, {
      library_id: libraryId
    })
    showToastMessage(libraryId ? '媒体库刷新任务已提交' : '所有媒体库刷新任务已提交', 'success')
  } catch (error) {
    console.error('刷新失败:', error)
    showToastMessage('刷新失败，请稍后重试', 'error')
  } finally {
    refreshingLibrary.value = null
  }
}

// 扫描媒体库
const handleScanLibrary = async (libraryId: string | null) => {
  scanningLibrary.value = libraryId || 'all'
  try {
    const serverId = selectedServerForLibraries.value.id
    await http.post(`/emby-sessions/servers/${serverId}/libraries/scan`, {
      library_id: libraryId
    })
    showToastMessage(libraryId ? '媒体库扫描任务已提交' : '所有媒体库扫描任务已提交', 'success')
  } catch (error) {
    console.error('扫描失败:', error)
    showToastMessage('扫描失败，请稍后重试', 'error')
  } finally {
    scanningLibrary.value = null
  }
}

// 格式化 URL 显示
const formatUrl = (url: string) => {
  try {
    const urlObj = new URL(url)
    return urlObj.hostname
  } catch {
    return url
  }
}

// 计算使用率
const getUsagePercent = (current: number, max: number) => {
  if (max === 0) return 0
  return Math.round((current / max) * 100)
}

const getUsageColor = (percent: number) => {
  if (percent >= 90) return 'text-red-500'
  if (percent >= 70) return 'text-amber-500'
  return 'text-emerald-500'
}

onMounted(() => {
  loadServers()
  loadPlans()
})
</script>

<template>
  <div class="emby-servers-page">
    <!-- 操作按钮 -->
    <div class="page-actions">
      <button class="btn-primary" @click="handleCreateServer">
        <Plus :size="18" />
        添加服务器
      </button>
    </div>

    <!-- 服务器列表 -->
    <div v-if="!loading && servers.length > 0" class="servers-grid">
      <div
        v-for="server in servers"
        :key="server.id"
        class="server-card"
        :class="{ 'server-inactive': !server.is_active }"
      >
        <div class="server-header">
          <div class="server-icon">
            <Server :size="24" />
          </div>
          <div class="server-info">
            <h3 class="server-name">{{ server.name }}</h3>
            <p class="server-url">{{ formatUrl(server.url) }}</p>
          </div>
          <div class="server-status">
            <span :class="['status-dot', server.is_active ? 'status-active' : 'status-inactive']"></span>
            <span class="status-text">{{ server.is_active ? '运行中' : '已停用' }}</span>
          </div>
        </div>

        <div class="server-metrics">
          <div class="metric">
            <div class="metric-icon metric-icon-blue">
              <Users :size="18" />
            </div>
            <div class="metric-content">
              <p class="metric-value">{{ server.current_users }}</p>
              <p class="metric-label">当前用户</p>
            </div>
          </div>
          <div class="metric-divider"></div>
          <div class="metric">
            <div class="metric-icon metric-icon-purple">
              <Zap :size="18" />
            </div>
            <div class="metric-content">
              <p class="metric-value">{{ server.max_users === 0 ? '无限制' : server.max_users }}</p>
              <p class="metric-label">容量限制</p>
            </div>
          </div>
          <div class="metric-divider"></div>
          <div class="metric">
            <div class="metric-icon metric-icon-emerald">
              <Link :size="18" />
            </div>
            <div class="metric-content">
              <p class="metric-value">{{ server.plan_count || 0 }}</p>
              <p class="metric-label">关联套餐</p>
            </div>
          </div>
        </div>

        <div v-if="server.max_users > 0" class="server-usage">
          <div class="usage-bar">
            <div
              class="usage-fill"
              :class="getUsagePercent(server.current_users, server.max_users) >= 90 ? 'usage-fill-high' : getUsagePercent(server.current_users, server.max_users) >= 70 ? 'usage-fill-medium' : 'usage-fill-low'"
              :style="{ width: `${getUsagePercent(server.current_users, server.max_users)}%` }"
            ></div>
          </div>
          <p :class="['usage-text', getUsageColor(getUsagePercent(server.current_users, server.max_users))]">
            {{ getUsagePercent(server.current_users, server.max_users) }}% 使用率
          </p>
        </div>

        <div class="server-footer">
          <div class="server-actions">
            <button class="action-btn action-sync" @click="handleSyncServer(server.id)" :disabled="syncing === server.id">
              <RefreshCw :size="16" :class="{ 'animate-spin': syncing === server.id }" />
              {{ syncing === server.id ? '同步中...' : '同步' }}
            </button>
            <button class="action-btn action-libraries" @click="handleManageLibraries(server)">
              <Database :size="16" />
              媒体库
            </button>
            <button class="action-btn action-plans" @click="handleManagePlans(server)">
              <Link :size="16" />
              套餐
            </button>
            <button class="action-btn action-edit" @click="handleEditServer(server)">
              <Edit :size="16" />
            </button>
            <button class="action-btn action-delete" @click="handleDeleteServer(server)">
              <Trash2 :size="16" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-else-if="loading" class="loading-state">
      <div v-for="i in 3" :key="i" class="server-skeleton">
        <div class="skeleton-header">
          <div class="skeleton-icon"></div>
          <div class="skeleton-lines">
            <div class="skeleton-bar"></div>
            <div class="skeleton-bar skeleton-bar-sm"></div>
          </div>
        </div>
        <div class="skeleton-metrics">
          <div v-for="j in 3" :key="j" class="skeleton-metric">
            <div class="skeleton-bar"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <div class="empty-state-icon">🖥️</div>
      <p class="empty-state-text">暂无 Emby 服务器</p>
      <button class="btn-primary" @click="handleCreateServer">
        <Plus :size="18" />
        添加第一个服务器
      </button>
    </div>

    <!-- 创建/编辑服务器对话框 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showServerDialog" class="modal-overlay" @click.self="showServerDialog = false">
        <div class="modal-content server-modal">
          <div class="modal-header">
            <h2 class="modal-title">{{ editingServer ? '编辑服务器' : '添加服务器' }}</h2>
            <button class="modal-close" @click="showServerDialog = false">
              <X :size="24" />
            </button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">服务器名称</label>
              <input v-model="serverForm.name" type="text" class="input" placeholder="例如：主服务器" />
            </div>
            <div class="form-group">
              <label class="form-label">服务器地址</label>
              <input v-model="serverForm.url" type="url" class="input" placeholder="https://emby.example.com" />
            </div>
            <div class="form-group">
              <label class="form-label">API Key</label>
              <input v-model="serverForm.api_key" type="text" class="input" placeholder="Emby API 密钥" />
            </div>
            <div class="form-group">
              <label class="form-label">最大用户数</label>
              <input v-model.number="serverForm.max_users" type="number" class="input" min="0" placeholder="0 表示无限制" />
            </div>
            <div class="form-group checkbox-group">
              <label class="checkbox-label">
                <input v-model="serverForm.is_active" type="checkbox" />
                <span>启用服务器</span>
              </label>
            </div>
            <div v-if="serverForm.url && serverForm.api_key" class="test-section">
              <button class="btn-test" @click="handleTestConnection" :disabled="testing">
                <RefreshCw :size="16" :class="{ 'animate-spin': testing }" />
                {{ testing ? '测试中...' : '测试连接' }}
              </button>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="showServerDialog = false">取消</button>
            <button class="btn-primary" @click="handleSaveServer" :disabled="saving">
              <Save :size="18" />
              {{ saving ? '保存中...' : '保存' }}
            </button>
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
      <div v-if="showDeleteDialog" class="modal-overlay" @click.self="showDeleteDialog = false">
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
            确定要删除服务器 <span class="delete-server-name">{{ serverToDelete?.name }}</span> 吗？
          </p>
          <div class="delete-modal-actions">
            <button class="btn-secondary" @click="showDeleteDialog = false">取消</button>
            <button class="btn-danger" @click="confirmDelete">确认删除</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 套餐关联对话框 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showPlanDialog" class="modal-overlay" @click.self="showPlanDialog = false">
        <div class="modal-content plan-modal">
          <div class="modal-header">
            <h2 class="modal-title">套餐关联管理</h2>
            <button class="modal-close" @click="showPlanDialog = false">
              <X :size="24" />
            </button>
          </div>
          <div class="modal-body">
            <p class="modal-subtitle">服务器: {{ selectedServerForPlans?.name }}</p>
            <div class="plan-list">
              <div
                v-for="item in serverPlans"
                :key="item.plan_id"
                class="plan-item"
                :class="{ 'plan-item-linked': item.is_linked }"
              >
                <div class="plan-item-info">
                  <Link :size="18" :class="item.is_linked ? 'text-emerald-500' : 'text-gray-500'" />
                  <span class="plan-item-name">{{ item.plan_name }}</span>
                </div>
                <button
                  class="plan-item-toggle"
                  :class="{ 'plan-item-toggle-on': item.is_linked }"
                  @click="togglePlanLink(item)"
                >
                  <Check v-if="item.is_linked" :size="16" />
                  <span>{{ item.is_linked ? '已关联' : '关联' }}</span>
                </button>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="showPlanDialog = false">关闭</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 媒体库管理对话框 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showLibraryDialog" class="modal-overlay" @click.self="showLibraryDialog = false">
        <div class="modal-content library-modal">
          <div class="modal-header">
            <h2 class="modal-title">媒体库管理</h2>
            <button class="modal-close" @click="showLibraryDialog = false">
              <X :size="24" />
            </button>
          </div>
          <div class="modal-body">
            <p class="modal-subtitle">服务器: {{ selectedServerForLibraries?.name }}</p>

            <!-- 全局操作 -->
            <div class="library-global-actions">
              <button
                class="global-action-btn"
                @click="handleRefreshLibrary(null)"
                :disabled="refreshingLibrary === 'all'"
              >
                <RotateCw :size="16" :class="{ 'animate-spin': refreshingLibrary === 'all' }" />
                {{ refreshingLibrary === 'all' ? '刷新中...' : '刷新全部' }}
              </button>
              <button
                class="global-action-btn global-action-scan"
                @click="handleScanLibrary(null)"
                :disabled="scanningLibrary === 'all'"
              >
                <Scan :size="16" :class="{ 'animate-spin': scanningLibrary === 'all' }" />
                {{ scanningLibrary === 'all' ? '扫描中...' : '扫描全部' }}
              </button>
            </div>

            <!-- 媒体库列表 -->
            <div class="library-list">
              <div
                v-for="lib in libraries"
                :key="lib.id"
                class="library-item"
              >
                <div class="library-info">
                  <Database :size="20" class="library-icon" />
                  <div>
                    <div class="library-name">{{ lib.name }}</div>
                    <div class="library-meta">
                      {{ lib.collection_type || '未知类型' }}
                      <span v-if="lib.locations?.length"> · {{ lib.locations.length }} 个路径</span>
                    </div>
                  </div>
                </div>
                <div class="library-actions">
                  <button
                    class="library-btn library-btn-refresh"
                    @click="handleRefreshLibrary(lib.id)"
                    :disabled="refreshingLibrary === lib.id"
                    title="刷新元数据"
                  >
                    <RotateCw :size="14" :class="{ 'animate-spin': refreshingLibrary === lib.id }" />
                  </button>
                  <button
                    class="library-btn library-btn-scan"
                    @click="handleScanLibrary(lib.id)"
                    :disabled="scanningLibrary === lib.id"
                    title="扫描新内容"
                  >
                    <Scan :size="14" :class="{ 'animate-spin': scanningLibrary === lib.id }" />
                  </button>
                </div>
              </div>
            </div>

            <!-- 空状态 -->
            <div v-if="libraries.length === 0" class="library-empty">
              <Database :size="48" />
              <p>没有找到媒体库</p>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="showLibraryDialog = false">关闭</button>
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
      <div
        v-if="showToast"
        :class="['toast', `toast-${toastType}`]"
      >
        <span class="text-xl">{{ toastType === 'success' ? '✓' : toastType === 'error' ? '✕' : 'ℹ' }}</span>
        <span>{{ toastMessage }}</span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.emby-servers-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}





/* ==================== Servers Grid ==================== */
.servers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 1.5rem;
}

.server-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  padding: 1.5rem;
  transition: all 0.3s ease;
}

.server-card:hover {
  border-color: var(--primary);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.server-inactive {
  opacity: 0.6;
}

.server-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.server-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2) 0%, rgba(139, 92, 246, 0.2) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
}

.server-info {
  flex: 1;
}

.server-name {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}

.server-url {
  font-size: 0.75rem;
  color: var(--text-tertiary);
}

.server-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-active {
  background: var(--success);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.5);
}

.status-inactive {
  background: var(--text-secondary);
}

.status-text {
  font-size: 0.75rem;
  color: var(--text-tertiary);
}

/* ==================== Metrics ==================== */
.server-metrics {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: var(--bg-elevated);
  border-radius: 0.75rem;
  margin-bottom: 1rem;
}

.metric {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
}

.metric-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.metric-icon-blue { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.metric-icon-purple { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
.metric-icon-emerald { background: rgba(16, 185, 129, 0.15); color: #10b981; }

.metric-content {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.metric-value {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.metric-label {
  font-size: 0.625rem;
  color: var(--text-muted);
  text-transform: uppercase;
}

.metric-divider {
  width: 1px;
  height: 32px;
  background: var(--border-base);
}

/* ==================== Usage Bar ==================== */
.server-usage {
  margin-bottom: 1rem;
}

.usage-bar {
  height: 6px;
  background: var(--bg-elevated);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.usage-fill {
  height: 100%;
  transition: width 0.3s ease;
}

.usage-fill-low { background: linear-gradient(90deg, #10b981, #34d399); }
.usage-fill-medium { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.usage-fill-high { background: linear-gradient(90deg, #ef4444, #f87171); }

.usage-text {
  font-size: 0.75rem;
  color: var(--text-tertiary);
}

/* ==================== Footer Actions ==================== */
.server-footer {
  padding-top: 1rem;
  border-top: 1px solid var(--border-base);
}

.server-actions {
  display: flex;
  gap: 0.5rem;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-sync {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.action-sync:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.25);
}

.action-sync:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-plans {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.action-plans:hover {
  background: rgba(16, 185, 129, 0.25);
}

.action-libraries {
  background: rgba(168, 85, 247, 0.15);
  color: #a855f7;
}

.action-libraries:hover {
  background: rgba(168, 85, 247, 0.25);
}

.action-edit {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.action-edit:hover {
  background: rgba(245, 158, 11, 0.25);
}

.action-delete {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.action-delete:hover {
  background: rgba(239, 68, 68, 0.25);
}

/* ==================== Loading & Empty ==================== */
.loading-state {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 1.5rem;
}

.server-skeleton {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  padding: 1.5rem;
}

.skeleton-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.skeleton-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--bg-hover);
}

.skeleton-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.skeleton-bar {
  height: 12px;
  background: var(--bg-hover);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.skeleton-bar-sm {
  width: 60%;
}

.skeleton-metrics {
  display: flex;
  gap: 1rem;
}

.skeleton-metric {
  flex: 1;
}

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

.empty-state {
  text-align: center;
  padding: 4rem 2rem;
}

.empty-state-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.empty-state-text {
  color: var(--text-tertiary);
  margin: 0 0 1.5rem 0;
}

/* ==================== Modal ==================== */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.8);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.modal-content {
  width: 100%;
  max-width: 500px;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-base);
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem;
  border-bottom: 1px solid var(--border-base);
}

.modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.modal-close {
  padding: 0.5rem;
  border-radius: 0.5rem;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
}

.modal-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.modal-body {
  padding: 1.5rem;
  max-height: 60vh;
  overflow-y: auto;
}

.modal-subtitle {
  font-size: 0.875rem;
  color: var(--text-muted);
  margin-bottom: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.form-label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.input {
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-base);
  background: var(--bg-elevated);
  color: var(--text-primary);
  font-size: 0.875rem;
}

.input:focus {
  outline: none;
  border-color: var(--primary);
}

.checkbox-group {
  flex-direction: row;
  align-items: center;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.test-section {
  display: flex;
  justify-content: center;
  padding: 1rem;
  background: var(--bg-elevated);
  border-radius: 0.5rem;
  margin-top: 0.5rem;
}

.btn-test {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  border: 1px dashed var(--border-base);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-base) ease;
}

.btn-test:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-test:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--border-base);
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
  color: var(--text-tertiary);
}

.delete-message {
  font-size: 0.875rem;
  margin-bottom: 1.5rem;
  color: var(--text-secondary);
}

.delete-server-name {
  font-weight: 500;
  color: var(--text-primary);
}

.delete-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

/* ==================== Plan Modal ==================== */
.plan-modal {
  max-width: 450px;
}

.plan-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.plan-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: var(--bg-elevated);
  border-radius: 0.5rem;
  border: 1px solid var(--border-base);
  transition: all var(--transition-base) ease;
}

.plan-item-linked {
  border-color: rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.05);
}

.plan-item-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.plan-item-name {
  font-size: 0.875rem;
  color: var(--text-primary);
}

.plan-item-toggle {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  background: var(--bg-hover);
  color: var(--text-tertiary);
  border: none;
  cursor: pointer;
  transition: all var(--transition-base) ease;
}

.plan-item-toggle:hover {
  background: var(--bg-elevated);
}

.plan-item-toggle-on {
  background: var(--success-bg);
  color: var(--success);
}

.plan-item-toggle-on:hover {
  background: rgba(16, 185, 129, 0.25);
}

/* ==================== Library Modal ==================== */
.library-modal {
  max-width: 500px;
}

.library-global-actions {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--border-base);
}

.global-action-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.global-action-btn:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.25);
}

.global-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.global-action-scan {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.global-action-scan:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.25);
}

.library-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-height: 400px;
  overflow-y: auto;
}

.library-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  background: var(--bg-elevated);
  border-radius: 0.75rem;
  border: 1px solid var(--border-base);
  transition: all var(--transition-base) ease;
}

.library-item:hover {
  border-color: var(--primary);
}

.library-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
}

.library-icon {
  color: #a855f7;
}

.library-name {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.library-meta {
  font-size: 0.75rem;
  color: var(--text-tertiary);
  margin-top: 2px;
}

.library-actions {
  display: flex;
  gap: 0.5rem;
}

.library-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 0.5rem;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.library-btn-refresh {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.library-btn-refresh:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.25);
}

.library-btn-scan {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.library-btn-scan:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.25);
}

.library-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.library-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1rem;
  color: var(--text-tertiary);
}

.library-empty svg {
  margin-bottom: 1rem;
  opacity: 0.5;
}

/* ==================== Buttons ==================== */
.btn-primary,
.btn-secondary,
.btn-danger {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary {
  background: var(--primary);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-elevated);
  color: var(--text-primary);
  border: 1px solid var(--border-base);
}

.btn-secondary:hover {
  background: var(--bg-hover);
}

.btn-danger {
  background: #ef4444;
  color: white;
}

.btn-danger:hover {
  background: #dc2626;
}

/* ==================== Toast ==================== */
.toast {
  position: fixed;
  bottom: 2rem;
  right: 2rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  background: var(--bg-card);
  border-radius: 0.75rem;
  border: 1px solid var(--border-color);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
}

.toast-success { border-color: var(--success); }
.toast-error { border-color: var(--danger); }

/* ==================== Responsive ==================== */
@media (max-width: 768px) {
  .servers-grid {
    grid-template-columns: 1fr;
  }

  .server-metrics {
    flex-wrap: wrap;
  }

  .metric-divider {
    display: none;
  }

  .form-row {
    grid-template-columns: 1fr;
  }
}
</style>
