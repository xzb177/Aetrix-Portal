<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  Route, Plus, Search, RefreshCw, Power, PowerOff, Wrench, Copy, Trash2,
  ChevronDown, ChevronUp, Globe, Zap, Shield, Activity, Settings,
  ChevronUp as MoveUp, ChevronDown as MoveDown, Play, Copy as CopyIcon
} from 'lucide-vue-next'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'

// ============================================================
// 类型定义
// ============================================================

interface Route {
  id: number
  name: string
  description?: string
  enabled: boolean
  priority: number
  status: 'ok' | 'maintenance' | 'degraded' | 'down'
  domain: string
  tls: boolean
  base_path: string
  tags: string[]
  region_scope: string[]
  worker_route?: string
  origin_type: string
  rollout_percent: number
  health_last_ok_at?: string
  health_fail_count: number
  created_at: string
  updated_at: string
}

interface RouteForm {
  name: string
  description?: string
  enabled: boolean
  priority: number
  tags: string[]
  region_scope: string[]
  domain: string
  tls: boolean
  base_path: string
  worker_route?: string
  origin_type: 'emby' | 'jellyfin' | 'http'
  rewrite_from?: string
  rewrite_to?: string
  status: 'ok' | 'maintenance' | 'degraded' | 'down'
  maintenance_message?: string
  rollout_percent: number
  health_url?: string
  health_expect_status: number
  health_timeout_ms: number
}

interface PreviewData {
  user_id?: number
  tg_id?: number
  emby_user_id?: string
  anon_id?: string
  region?: string
  device?: string
}

interface PreviewResult {
  selected_route: Route | null
  available_routes: Route[]
  explanation: string
  debug_info: {
    total_routes: number
    enabled_routes: number
    status_ok_routes: number
    region_matched: boolean
    in_allow_list: boolean
    in_deny_list: boolean
    rollout_passed: boolean
    hash_value?: number
    matched_rules: string[]
  }
}

// ============================================================
// 状态
// ============================================================

const loading = ref(false)
const routes = ref<Route[]>([])
const showEditDialog = ref(false)
const showPreviewDialog = ref(false)
const editingRoute = ref<Route | null>(null)
const editForm = ref<RouteForm | null>(null)

// 策略预览
const previewData = ref<PreviewData>({
  user_id: undefined,
  tg_id: undefined,
  emby_user_id: undefined,
  anon_id: undefined,
  region: undefined,
  device: undefined
})
const previewResult = ref<PreviewResult | null>(null)
const previewLoading = ref(false)

// 搜索筛选
const searchForm = ref({
  search: '',
  enabled: undefined as boolean | undefined,
  status: undefined as string | undefined,
  tags: ''
})

// 展开状态
const expandedRoutes = ref<Set<number>>(new Set())

function toggleExpand(routeId: number) {
  if (expandedRoutes.value.has(routeId)) {
    expandedRoutes.value.delete(routeId)
  } else {
    expandedRoutes.value.add(routeId)
  }
}

// ============================================================
// 状态配置
// ============================================================

const statusOptions = [
  { label: '正常', value: 'ok', color: 'success' },
  { label: '维护中', value: 'maintenance', color: 'warning' },
  { label: '降级', value: 'degraded', color: 'info' },
  { label: '宕机', value: 'down', color: 'danger' }
]

function getStatusInfo(status: string) {
  return statusOptions.find(s => s.value === status) || statusOptions[0]
}

// ============================================================
// API 调用
// ============================================================

const API_BASE = '/api/routes'

async function fetchRoutes() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (searchForm.value.search) params.append('search', searchForm.value.search)
    if (searchForm.value.enabled !== undefined) params.append('enabled', String(searchForm.value.enabled))
    if (searchForm.value.status) params.append('status', searchForm.value.status)
    if (searchForm.value.tags) params.append('tags', searchForm.value.tags)

    const response = await fetch(`${API_BASE}?${params}`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`
      }
    })

    if (response.ok) {
      routes.value = await response.json()
    } else {
      ElMessage.error('获取线路列表失败')
    }
  } catch (error) {
    console.error('获取线路列表失败:', error)
    ElMessage.error('获取线路列表失败')
  } finally {
    loading.value = false
  }
}

async function toggleRouteStatus(route: Route) {
  try {
    const response = await fetch(`${API_BASE}/${route.id}/toggle`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ enabled: !route.enabled })
    })

    if (response.ok) {
      ElMessage.success(route.enabled ? '已禁用' : '已启用')
      await fetchRoutes()
    } else {
      ElMessage.error('操作失败')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

async function setMaintenance(route: Route) {
  const newStatus = route.status === 'maintenance' ? 'ok' : 'maintenance'
  const message = newStatus === 'maintenance'
    ? prompt('请输入维护消息：', '系统维护中，请稍后访问')
    : null

  if (newStatus === 'maintenance' && message === null) {
    return
  }

  try {
    const response = await fetch(`${API_BASE}/${route.id}/maintenance`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        status: newStatus,
        maintenance_message: message
      })
    })

    if (response.ok) {
      ElMessage.success(newStatus === 'maintenance' ? '已进入维护模式' : '已恢复正常')
      await fetchRoutes()
    } else {
      ElMessage.error('操作失败')
    }
  } catch (error) {
    ElMessage.error('操作失败')
  }
}

async function copyRoute(route: Route) {
  const newName = prompt('请输入新线路名称：', `${route.name} - 副本`)
  if (!newName) return

  try {
    const response = await fetch(`${API_BASE}/${route.id}/copy`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ name: newName })
    })

    if (response.ok) {
      ElMessage.success('线路复制成功')
      await fetchRoutes()
    } else {
      const error = await response.json()
      ElMessage.error(error.detail || '复制失败')
    }
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

async function deleteRoute(route: Route) {
  try {
    await ElMessageBox.confirm(
      `确定要删除线路「${route.name}」吗？此操作不可恢复。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const response = await fetch(`${API_BASE}/${route.id}`, {
      method: 'DELETE',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`
      }
    })

    if (response.ok) {
      ElMessage.success('删除成功')
      await fetchRoutes()
    } else {
      ElMessage.error('删除失败')
    }
  } catch (error) {
    // 用户取消
  }
}

function openCreateDialog() {
  editingRoute.value = null
  editForm.value = {
    name: '',
    description: '',
    enabled: true,
    priority: 100,
    tags: [],
    region_scope: ['GLOBAL'],
    domain: '',
    tls: true,
    base_path: '',
    origin_type: 'emby',
    status: 'ok',
    rollout_percent: 100,
    health_expect_status: 200,
    health_timeout_ms: 5000
  }
  showEditDialog.value = true
}

async function saveRoute() {
  if (!editForm.value) return

  // 验证
  if (!editForm.value.name) {
    ElMessage.error('请输入线路名称')
    return
  }
  if (!editForm.value.domain) {
    ElMessage.error('请输入域名')
    return
  }

  const isEdit = editingRoute.value !== null
  const url = isEdit
    ? `${API_BASE}/${editingRoute.value.id}`
    : API_BASE

  try {
    const response = await fetch(url, {
      method: isEdit ? 'PUT' : 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(editForm.value)
    })

    if (response.ok) {
      ElMessage.success(isEdit ? '保存成功' : '创建成功')
      showEditDialog.value = false
      await fetchRoutes()
    } else {
      const error = await response.json()
      ElMessage.error(error.detail || '保存失败')
    }
  } catch (error) {
    ElMessage.error('保存失败')
  }
}

// ============================================================
// 优先级排序
// ============================================================

async function movePriority(route: Route, direction: 'up' | 'down') {
  const currentRoutes = [...routes.value].sort((a, b) => a.priority - b.priority)
  const currentIndex = currentRoutes.findIndex(r => r.id === route.id)

  if (direction === 'up' && currentIndex === 0) {
    ElMessage.warning('已经是最高优先级')
    return
  }
  if (direction === 'down' && currentIndex === currentRoutes.length - 1) {
    ElMessage.warning('已经是最低优先级')
    return
  }

  const targetRoute = direction === 'up'
    ? currentRoutes[currentIndex - 1]
    : currentRoutes[currentIndex + 1]

  if (!targetRoute) return

  // 交换优先级
  try {
    // 获取新优先级（直接交换值）
    const newPriority = targetRoute.priority

    const response = await fetch(`${API_BASE}/${route.id}/priority`, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ priority: newPriority })
    })

    if (response.ok) {
      ElMessage.success('优先级已调整')
      await fetchRoutes()
    } else {
      const error = await response.json()
      ElMessage.error(error.detail || '调整失败')
    }
  } catch (error) {
    ElMessage.error('调整失败')
  }
}

// ============================================================
// 策略预览
// ============================================================

function openPreviewDialog() {
  previewResult.value = null
  showPreviewDialog.value = true
}

async function runPreview() {
  previewLoading.value = true
  try {
    const response = await fetch(`${API_BASE}/preview`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(previewData.value)
    })

    if (response.ok) {
      previewResult.value = await response.json()
    } else {
      const error = await response.json()
      ElMessage.error(error.detail || '预览失败')
    }
  } catch (error) {
    ElMessage.error('预览失败')
  } finally {
    previewLoading.value = false
  }
}

function copyDiagnosticInfo() {
  if (!previewResult.value) return

  const info = {
    input: previewData.value,
    selected_route: previewResult.value.selected_route?.name || 'None',
    explanation: previewResult.value.explanation,
    debug: previewResult.value.debug_info
  }

  const text = JSON.stringify(info, null, 2)
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('诊断信息已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

// 计算显示的 sticky_key
const displayStickyKey = computed(() => {
  if (previewData.value.tg_id) return `tg:${previewData.value.tg_id}`
  if (previewData.value.emby_user_id) return `emby:${previewData.value.emby_user_id}`
  if (previewData.value.user_id) return `user:${previewData.value.user_id}`
  if (previewData.value.anon_id) return `anon:${previewData.value.anon_id}`
  return 'unknown'
})

// ============================================================
// 生命周期
// ============================================================

onMounted(() => {
  fetchRoutes()
})
</script>

<template>
  <div class="routes-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">
          <Route :size="24" />
          线路管理
        </h1>
        <p class="page-description">配置多域名入口和 Cloudflare Worker 路由</p>
      </div>
      <div class="header-actions">
        <el-button @click="fetchRoutes" :loading="loading">
          <RefreshCw :size="16" />
          刷新
        </el-button>
        <el-button @click="openPreviewDialog">
          <Play :size="16" />
          策略预览
        </el-button>
        <el-button type="primary" @click="openCreateDialog">
          <Plus :size="16" />
          新建线路
        </el-button>
      </div>
    </div>

    <!-- 搜索筛选 -->
    <div class="search-bar">
      <el-input
        v-model="searchForm.search"
        placeholder="搜索线路名称或域名..."
        clearable
        @change="fetchRoutes"
      >
        <template #prefix>
          <Search :size="16" />
        </template>
      </el-input>

      <el-select
        v-model="searchForm.enabled"
        placeholder="状态"
        clearable
        @change="fetchRoutes"
      >
        <el-option label="启用" :value="true" />
        <el-option label="禁用" :value="false" />
      </el-select>

      <el-select
        v-model="searchForm.status"
        placeholder="线路状态"
        clearable
        @change="fetchRoutes"
      >
        <el-option
          v-for="status in statusOptions"
          :key="status.value"
          :label="status.label"
          :value="status.value"
        />
      </el-select>

      <el-input
        v-model="searchForm.tags"
        placeholder="标签（逗号分隔）"
        clearable
        @change="fetchRoutes"
      />
    </div>

    <!-- 线路列表 -->
    <div class="routes-list" v-loading="loading">
      <div
        v-for="route in routes"
        :key="route.id"
        class="route-card"
        :class="{
          'route-disabled': !route.enabled,
          'route-maintenance': route.status === 'maintenance'
        }"
      >
        <!-- 基础信息 -->
        <div class="route-header">
          <div class="route-title">
            <el-tag
              v-if="!route.enabled"
              type="info"
              size="small"
            >
              禁用
            </el-tag>
            <el-tag
              :type="getStatusInfo(route.status).color"
              size="small"
            >
              {{ getStatusInfo(route.status).label }}
            </el-tag>
            <span class="route-name">{{ route.name }}</span>
            <span class="route-priority">P{{ route.priority }}</span>
          </div>

          <div class="route-actions">
            <el-button
              size="small"
              :icon="MoveUp"
              @click="movePriority(route, 'up')"
              :disabled="routes.indexOf(route) === 0"
            >
              上移
            </el-button>
            <el-button
              size="small"
              :icon="MoveDown"
              @click="movePriority(route, 'down')"
              :disabled="routes.indexOf(route) === routes.length - 1"
            >
              下移
            </el-button>
            <el-button
              size="small"
              :icon="route.enabled ? PowerOff : Power"
              @click="toggleRouteStatus(route)"
            >
              {{ route.enabled ? '禁用' : '启用' }}
            </el-button>
            <el-button
              size="small"
              :icon="Wrench"
              @click="setMaintenance(route)"
            >
              {{ route.status === 'maintenance' ? '恢复' : '维护' }}
            </el-button>
            <el-button
              size="small"
              :icon="Copy"
              @click="copyRoute(route)"
            >
              复制
            </el-button>
            <el-button
              size="small"
              type="danger"
              :icon="Trash2"
              @click="deleteRoute(route)"
            >
              删除
            </el-button>
          </div>
        </div>

        <!-- 域名和配置 -->
        <div class="route-details">
          <div class="route-domain">
            <Globe :size="16" />
            <span class="domain-text">
              {{ route.tls ? 'https://' : 'http://' }}{{ route.domain }}{{ route.base_path }}
            </span>
          </div>

          <div class="route-meta">
            <span v-if="route.worker_route" class="meta-item">
              <Zap :size="14" />
              Worker: {{ route.worker_route }}
            </span>
            <span class="meta-item">
              <Shield :size="14" />
              {{ route.origin_type }}
            </span>
            <span class="meta-item">
              <Activity :size="14" />
              灰度: {{ route.rollout_percent }}%
            </span>
            <span v-if="route.health_last_ok_at" class="meta-item">
              上次检测: {{ new Date(route.health_last_ok_at).toLocaleString() }}
            </span>
            <span v-if="route.health_fail_count > 0" class="meta-item danger">
              失败: {{ route.health_fail_count }} 次
            </span>
          </div>
        </div>

        <!-- 标签 -->
        <div class="route-tags" v-if="route.tags.length > 0">
          <el-tag
            v-for="tag in route.tags"
            :key="tag"
            size="small"
            type="info"
          >
            {{ tag }}
          </el-tag>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && routes.length === 0" class="empty-state">
        <Route :size="48" />
        <p>暂无线路配置</p>
        <el-button type="primary" @click="openCreateDialog">
          创建第一条线路
        </el-button>
      </div>
    </div>

    <!-- 编辑对话框 -->
    <el-dialog
      v-model="showEditDialog"
      :title="editingRoute ? '编辑线路' : '新建线路'"
      width="600px"
    >
      <el-form
        v-if="editForm"
        :model="editForm"
        label-width="120px"
      >
        <el-form-item label="线路名称" required>
          <el-input v-model="editForm.name" placeholder="如：主线路 CF Worker" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="editForm.description"
            type="textarea"
            placeholder="线路描述..."
          />
        </el-form-item>

        <el-form-item label="域名" required>
          <el-input v-model="editForm.domain" placeholder="example.com" />
        </el-form-item>

        <el-form-item label="协议">
          <el-radio-group v-model="editForm.tls">
            <el-radio :label="true">HTTPS</el-radio>
            <el-radio :label="false">HTTP</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="基础路径">
          <el-input v-model="editForm.base_path" placeholder="/" />
        </el-form-item>

        <el-form-item label="优先级">
          <el-input-number
            v-model="editForm.priority"
            :min="0"
            :max="999"
          />
          <span class="form-tip">越小越优先（0-999）</span>
        </el-form-item>

        <el-form-item label="Worker 路由">
          <el-input v-model="editForm.worker_route" placeholder="可选，如：/api/*" />
        </el-form-item>

        <el-form-item label="源类型">
          <el-select v-model="editForm.origin_type">
            <el-option label="Emby" value="emby" />
            <el-option label="Jellyfin" value="jellyfin" />
            <el-option label="HTTP" value="http" />
          </el-select>
        </el-form-item>

        <el-form-item label="状态">
          <el-select v-model="editForm.status">
            <el-option label="正常" value="ok" />
            <el-option label="维护中" value="maintenance" />
            <el-option label="降级" value="degraded" />
            <el-option label="宕机" value="down" />
          </el-select>
        </el-form-item>

        <el-form-item label="灰度百分比">
          <el-slider v-model="editForm.rollout_percent" :min="0" :max="100" />
          <span class="form-tip">{{ editForm.rollout_percent }}%</span>
        </el-form-item>

        <el-form-item label="标签">
          <el-input
            v-model="editForm.tags as any"
            placeholder="逗号分隔，如：primary,cf-worker"
          />
        </el-form-item>

        <el-form-item label="地区范围">
          <el-input
            v-model="editForm.region_scope as any"
            placeholder="逗号分隔，如：GLOBAL,CN"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="saveRoute">保存</el-button>
      </template>
    </el-dialog>

    <!-- 策略预览对话框 -->
    <el-dialog
      v-model="showPreviewDialog"
      title="策略预览"
      width="700px"
    >
      <!-- 输入表单 -->
      <el-form label-width="120px" style="max-width: 600px">
        <el-form-item label="用户ID">
          <el-input-number v-model="previewData.user_id" :min="1" placeholder="用户ID" />
        </el-form-item>
        <el-form-item label="Telegram ID">
          <el-input-number v-model="previewData.tg_id" :min="1" placeholder="Telegram ID" />
        </el-form-item>
        <el-form-item label="Emby 用户ID">
          <el-input v-model="previewData.emby_user_id" placeholder="Emby 用户ID" />
        </el-form-item>
        <el-form-item label="匿名ID">
          <el-input v-model="previewData.anon_id" placeholder="localStorage anonId" />
        </el-form-item>
        <el-form-item label="地区">
          <el-select v-model="previewData.region" placeholder="选择地区" clearable>
            <el-option label="全球" value="GLOBAL" />
            <el-option label="中国" value="CN" />
            <el-option label="美国" value="US" />
            <el-option label="香港" value="HK" />
            <el-option label="台湾" value="TW" />
            <el-option label="新加坡" value="SG" />
            <el-option label="日本" value="JP" />
          </el-select>
        </el-form-item>
      </el-form>

      <!-- 预览结果 -->
      <div v-if="previewResult" class="preview-result">
        <div class="preview-section">
          <h4>预览结果</h4>
          <div v-if="previewResult.selected_route" class="result-success">
            <p><strong>选中线路：</strong>{{ previewResult.selected_route.name }}</p>
            <p><strong>域名：</strong>{{ previewResult.selected_route.domain }}</p>
            <p><strong>优先级：</strong>{{ previewResult.selected_route.priority }}</p>
            <p><strong>说明：</strong>{{ previewResult.explanation }}</p>
            <p><strong>Sticky Key：</strong><code>{{ displayStickyKey }}</code></p>
          </div>
          <div v-else class="result-error">
            <p>没有符合条件的线路</p>
            <p>{{ previewResult.explanation }}</p>
          </div>
        </div>

        <div class="preview-section">
          <h4>调试信息</h4>
          <div class="debug-info">
            <p>总线路数：{{ previewResult.debug_info.total_routes }}</p>
            <p>启用线路：{{ previewResult.debug_info.enabled_routes }}</p>
            <p>正常状态：{{ previewResult.debug_info.status_ok_routes }}</p>
            <p>白名单：{{ previewResult.debug_info.in_allow_list ? '是' : '否' }}</p>
            <p>黑名单：{{ previewResult.debug_info.in_deny_list ? '是' : '否' }}</p>
            <p>灰度通过：{{ previewResult.debug_info.rollout_passed ? '是' : '否' }}</p>
            <p v-if="previewResult.debug_info.hash_value !== null">
              灰度值：{{ previewResult.debug_info.hash_value }}
            </p>
          </div>
          <div class="matched-rules">
            <p><strong>匹配规则：</strong></p>
            <ul>
              <li v-for="(rule, idx) in previewResult.debug_info.matched_rules" :key="idx">
                {{ rule }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="copyDiagnosticInfo" :disabled="!previewResult">
          <CopyIcon :size="16" />
          复制诊断
        </el-button>
        <el-button @click="showPreviewDialog = false">关闭</el-button>
        <el-button type="primary" @click="runPreview" :loading="previewLoading">
          <Play :size="16" />
          运行预览
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.routes-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 26px;
  font-weight: 700;
  margin: 0;
  color: var(--el-text-color-primary);
}

.page-title svg {
  color: var(--el-color-primary);
}

.page-description {
  color: var(--el-text-color-regular);
  font-size: 14px;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.search-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  padding: 16px;
  background: var(--el-bg-color-page);
  border-radius: 12px;
  border: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
  align-items: center;
}

.search-bar .el-input {
  width: 240px;
}

.search-bar .el-select {
  width: 140px;
}

.routes-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.route-card {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 20px;
  background: var(--el-bg-color);
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;
}

.route-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--el-color-success);
}

.route-card:hover {
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  border-color: var(--el-color-primary-light-5);
  transform: translateY(-2px);
}

.route-card.route-disabled::before {
  background: var(--el-text-color-disabled);
}

.route-card.route-disabled {
  opacity: 0.7;
  background: var(--el-fill-color-extra-light);
}

.route-card.route-maintenance::before {
  background: var(--el-color-warning);
}

.route-card.route-maintenance {
  border-color: var(--el-color-warning-light-5);
}

.route-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.route-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.route-name {
  font-weight: 600;
  font-size: 17px;
  color: var(--el-text-color-primary);
}

.route-priority {
  font-size: 11px;
  font-weight: 600;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  padding: 3px 10px;
  border-radius: 20px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.route-actions {
  display: flex;
  gap: 6px;
}

.route-actions .el-button {
  border-radius: 8px;
}

.route-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 12px;
}

.route-domain {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-color-primary);
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', monospace;
  font-size: 14px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  width: fit-content;
}

.route-domain svg {
  flex-shrink: 0;
}

.domain-text {
  word-break: break-all;
}

.route-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  padding: 8px 0;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--el-fill-color-extra-light);
  border-radius: 6px;
}

.meta-item svg {
  width: 14px;
  height: 14px;
}

.meta-item.danger {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.route-tags {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: var(--el-text-color-secondary);
  background: var(--el-bg-color-page);
  border-radius: 16px;
  border: 2px dashed var(--el-border-color);
}

.empty-state svg {
  margin-bottom: 20px;
  opacity: 0.3;
  width: 64px;
  height: 64px;
}

.empty-state p {
  font-size: 16px;
  margin-bottom: 24px;
}

.form-tip {
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 策略预览对话框样式 */
.preview-result {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--el-border-color);
}

.preview-section {
  margin-bottom: 16px;
  padding: 16px;
  background: var(--el-fill-color-light);
  border-radius: 12px;
}

.preview-section h4 {
  margin: 0 0 16px 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-success {
  padding: 16px;
  background: var(--el-color-success-light-9);
  border-radius: 10px;
  border-left: 4px solid var(--el-color-success);
}

.result-success p {
  margin: 6px 0;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.result-success strong {
  color: var(--el-color-success);
}

.result-error {
  padding: 16px;
  background: var(--el-color-warning-light-9);
  border-radius: 10px;
  border-left: 4px solid var(--el-color-warning);
}

.result-error p {
  margin: 6px 0;
  font-size: 14px;
}

.debug-info {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  padding: 16px;
  background: var(--el-bg-color);
  border-radius: 10px;
}

.debug-info p {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.matched-rules {
  margin-top: 12px;
  padding: 16px;
  background: var(--el-bg-color);
  border-radius: 10px;
}

.matched-rules p {
  margin: 0 0 10px 0;
  font-size: 13px;
  font-weight: 500;
}

.matched-rules ul {
  margin: 0;
  padding-left: 24px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.matched-rules li {
  margin: 6px 0;
}

code {
  padding: 3px 8px;
  background: var(--el-fill-color);
  border-radius: 6px;
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
  font-size: 12px;
  color: var(--el-color-primary);
  font-weight: 500;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .routes-page {
    padding: 16px;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }

  .header-actions {
    width: 100%;
    justify-content: space-between;
  }

  .search-bar {
    padding: 12px;
  }

  .search-bar .el-input,
  .search-bar .el-select {
    width: 100%;
    flex: 1 1 100px;
  }

  .route-card {
    padding: 16px;
  }

  .route-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .route-actions {
    width: 100%;
    overflow-x: auto;
  }
}
</style>
