<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { Tickets, CircleCheck, CircleX, Search, RefreshCw, Plus, Copy, Trash2, Menu, Calendar, User, Check } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import {
  getExchangeCodes,
  createExchangeCode,
  batchCreateExchangeCodes,
  updateExchangeCodeStatus,
  deleteExchangeCode,
  getExchangeCodeStats
} from '@/api/portal'

// 兑换码类型
const codeTypes = [
  { label: '激活试用', value: 1, color: 'var(--success)' },
  { label: '按天续期', value: 2, color: 'var(--primary)' },
  { label: '按月续期', value: 3, color: 'var(--warning)' },
  { label: '充值余额', value: 4, color: 'var(--danger)' }
]

// 兑换码状态
const codeStatus = [
  { label: '未使用', value: 0, color: 'var(--info)' },
  { label: '已使用', value: 1, color: 'var(--success)' },
  { label: '已禁用', value: -1, color: 'var(--text-tertiary)' }
]

const loading = ref(false)
const codes = ref<any[]>([])
const total = ref(0)
const stats = ref<any>({})

// 搜索条件
const searchForm = ref({
  search: '',
  status: undefined as number | undefined,
  type: undefined as number | undefined
})

// 分页
const pagination = ref({
  page: 1,
  pageSize: 20
})

// 创建/批量创建弹窗
const showCreateDialog = ref(false)
const showBatchDialog = ref(false)
const createForm = ref({
  code: '',
  type: 1,
  exchange_count: 1,
  note: ''
})
const batchForm = ref({
  count: 10,
  type: 1,
  exchange_count: 1,
  note: ''
})
const creating = ref(false)
const batchCreating = ref(false)
const batchResult = ref<string[]>([])
const showBatchResultDialog = ref(false)

// 复制状态
const copyStates = ref<Record<number, { copying: boolean; copied: boolean }>>({})

// 根据兑换码类型获取字段标签
function getCountLabel(type: number): string {
  const labels: Record<number, string> = {
    1: '试用天数',
    2: '续期天数',
    3: '续期月数',
    4: '充值金额（元）'
  }
  return labels[type] || '数量'
}

// 根据兑换码类型获取占位符
function getCountPlaceholder(type: number): string {
  const placeholders: Record<number, string> = {
    1: '输入试用天数，如：7',
    2: '输入续期天数，如：30',
    3: '输入续期月数，如：1',
    4: '输入充值金额（元），如：10'
  }
  return placeholders[type] || '请输入'
}

// 根据兑换码类型获取最大值
function getCountMax(type: number): number {
  const maxValues: Record<number, number> = {
    1: 365,    // 试用最多1年
    2: 3650,   // 天数最多10年
    3: 120,    // 月数最多10年
    4: 10000   // 余额最多10000元
  }
  return maxValues[type] || 3650
}

// 获取统计数据
async function fetchStats() {
  try {
    const res = await getExchangeCodeStats()
    stats.value = res || {}
  } catch (error) {
    console.error('获取统计数据失败:', error)
  }
}

// 获取兑换码列表
async function fetchCodes() {
  loading.value = true
  try {
    const res = await getExchangeCodes({
      skip: (pagination.value.page - 1) * pagination.value.pageSize,
      limit: pagination.value.pageSize,
      ...searchForm.value
    })
    codes.value = res?.items || []
    total.value = res?.total || 0
  } catch (error) {
    console.error('获取兑换码列表失败:', error)
  } finally {
    loading.value = false
  }
}

// 搜索
function handleSearch() {
  pagination.value.page = 1
  fetchCodes()
}

// 重置搜索
function handleReset() {
  searchForm.value = {
    search: '',
    status: undefined,
    type: undefined
  }
  pagination.value.page = 1
  fetchCodes()
}

// 分页变化
function handlePageChange(page: number) {
  pagination.value.page = page
  fetchCodes()
}

// 打开创建弹窗
function openCreateDialog() {
  createForm.value = {
    code: '',
    type: 1,
    exchange_count: 1,
    note: ''
  }
  showCreateDialog.value = true
}

// 创建兑换码
async function handleCreate() {
  creating.value = true
  try {
    await createExchangeCode(createForm.value)
    showCreateDialog.value = false
    pagination.value.page = 1
    await fetchCodes()
    fetchStats()
  } catch (error: any) {
    console.error('创建失败:', error)
  } finally {
    creating.value = false
  }
}

// 打开批量创建弹窗
function openBatchDialog() {
  batchForm.value = {
    count: 10,
    type: 1,
    exchange_count: 1,
    note: ''
  }
  batchResult.value = []
  showBatchDialog.value = true
}

// 批量创建兑换码
async function handleBatchCreate() {
  batchCreating.value = true
  try {
    const res = await batchCreateExchangeCodes(batchForm.value)
    batchResult.value = res?.codes || []
    showBatchDialog.value = false
    pagination.value.page = 1
    await fetchCodes()
    fetchStats()
    if (batchResult.value.length > 0) {
      showBatchResultDialog.value = true
    }
  } catch (error: any) {
    console.error('创建失败:', error)
  } finally {
    batchCreating.value = false
  }
}

// 复制兑换码
async function copyCode(code: string, codeId: number) {
  const state = copyStates.value[codeId] || { copying: false, copied: false }
  copyStates.value[codeId] = state
  state.copying = true
  state.copied = false

  try {
    await navigator.clipboard.writeText(code)
    state.copied = true
    ElMessage.success({
      message: '已复制到剪贴板',
      duration: 2000,
      showClose: false
    })

    setTimeout(() => {
      state.copied = false
    }, 2000)
  } catch (err) {
    // 降级方案
    const textarea = document.createElement('textarea')
    textarea.value = code
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const successful = document.execCommand('copy')
    document.body.removeChild(textarea)

    if (successful) {
      state.copied = true
      ElMessage.success({
        message: '已复制到剪贴板',
        duration: 2000,
        showClose: false
      })

      setTimeout(() => {
        state.copied = false
      }, 2000)
    } else {
      ElMessage.error({
        message: '复制失败，请手动复制',
        duration: 3000
      })
    }
  } finally {
    state.copying = false
  }
}

// 复制批量生成的兑换码
function copyAllCodes() {
  const text = batchResult.value.join('\n')
  navigator.clipboard.writeText(text)
}

// 更新状态
async function handleStatusChange(row: any, newStatus: number) {
  try {
    await updateExchangeCodeStatus(row.id, { status: newStatus })
    fetchStats()
  } catch (error: any) {
    console.error('更新失败:', error)
    row.status = row.status
  }
}

// 删除兑换码
function handleDelete(row: any) {
  if (!confirm(`确定要删除兑换码 "${row.code}" 吗？`)) return
  deleteExchangeCode(row.id).then(() => {
    fetchCodes()
    fetchStats()
  }).catch((err) => {
    console.error('删除失败:', err)
  })
}

function getTypeName(type: number) {
  const t = codeTypes.find(t => t.value === type)
  return t ? t.label : '未知'
}

// 根据类型获取数量单位标签
function getCountUnit(type: number): string {
  const units: Record<number, string> = {
    1: '天',
    2: '天',
    3: '个月',
    4: '元'
  }
  return units[type] || ''
}

function getTypeColor(type: number) {
  const t = codeTypes.find(t => t.value === type)
  return t ? t.color : 'var(--text-tertiary)'
}

function getStatusName(status: number) {
  const s = codeStatus.find(s => s.value === status)
  return s ? s.label : '未知'
}

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const filteredCodes = computed(() => {
  return codes.value
})

onMounted(() => {
  fetchStats()
  fetchCodes()
})
</script>

<template>
  <div class="exchange-codes-page page-container">
    <!-- 顶部栏 -->
    <div class="top-bar">
      <div class="top-bar-left">
        <button class="icon-btn menu-btn">
          <Menu :size="20" />
        </button>
        <Tickets :size="22" class="top-icon" />
        <div class="top-titles">
          <h1 class="page-title">兑换码管理</h1>
          <p class="page-subtitle">创建和管理兑换码</p>
        </div>
      </div>
      <div class="top-bar-right">
        <button class="icon-btn" @click="fetchCodes" :class="{ spinning: loading }">
          <Refresh :size="18" />
        </button>
        <button class="icon-btn">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="1" />
            <circle cx="19" cy="12" r="1" />
            <circle cx="5" cy="12" r="1" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card mobile-card">
        <div class="stat-icon stat-blue">
          <Tickets :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.total || 0 }}</p>
          <p class="stat-label">总计</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-green">
          <CircleCheck :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.unused || 0 }}</p>
          <p class="stat-label">未使用</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-purple">
          <CircleX :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.used || 0 }}</p>
          <p class="stat-label">已使用</p>
        </div>
      </div>

      <div class="stat-card mobile-card">
        <div class="stat-icon stat-orange">
          <CircleX :size="20" />
        </div>
        <div class="stat-content">
          <p class="stat-value">{{ stats.disabled || 0 }}</p>
          <p class="stat-label">已禁用</p>
        </div>
      </div>
    </div>

    <!-- 搜索和筛选 -->
    <div class="filter-card mobile-card">
      <div class="search-box">
        <Search :size="18" class="search-icon" />
        <input
          v-model="searchForm.search"
          type="text"
          class="search-input"
          placeholder="搜索兑换码..."
          @keyup.enter="handleSearch"
        />
      </div>

      <div class="filter-row">
        <select v-model="searchForm.status" class="filter-select" @change="handleSearch">
          <option :value="undefined">全部状态</option>
          <option v-for="s in codeStatus" :key="s.value" :value="s.value">
            {{ s.label }}
          </option>
        </select>

        <select v-model="searchForm.type" class="filter-select" @change="handleSearch">
          <option :value="undefined">全部类型</option>
          <option v-for="t in codeTypes" :key="t.value" :value="t.value">
            {{ t.label }}
          </option>
        </select>

        <button class="btn-reset" @click="handleReset">
          重置
        </button>
      </div>

      <div class="action-buttons">
        <button class="btn-primary" @click="openCreateDialog">
          <Plus :size="16" />
          添加兑换码
        </button>
        <button class="btn-success" @click="openBatchDialog">
          <Plus :size="16" />
          批量生成
        </button>
      </div>
    </div>

    <!-- 移动端卡片列表 -->
    <div class="codes-list mobile-only">
      <!-- 加载状态 -->
      <div v-if="loading && codes.length === 0" class="loading-state">
        <div class="loading-spinner"></div>
        <p>加载中...</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="codes.length === 0" class="empty-state">
        <div class="empty-icon">🎫</div>
        <p class="empty-text">暂无兑换码</p>
      </div>

      <!-- 兑换码卡片 -->
      <div v-else class="code-cards">
        <div v-for="row in codes" :key="row.id" class="code-card mobile-card">
          <div class="code-card-header">
            <div class="code-title-wrapper">
              <Tickets :size="16" class="code-icon" />
              <code class="code-text">{{ row.code }}</code>
            </div>
            <span class="type-badge" :style="{ background: `${getTypeColor(row.type)}20`, color: getTypeColor(row.type) }">
              {{ getTypeName(row.type) }}
            </span>
          </div>

          <div class="code-card-body">
            <div class="code-info-row">
              <span class="code-label">状态</span>
              <select
                v-if="row.status !== 1"
                v-model="row.status"
                class="status-select"
                @change="handleStatusChange(row, row.status)"
              >
                <option :value="0">未使用</option>
                <option :value="-1">已禁用</option>
              </select>
              <span v-else class="status-tag status-used">已使用</span>
            </div>
            <div class="code-info-row">
              <span class="code-label">数量</span>
              <span class="code-value">{{ row.exchange_count }}{{ getCountUnit(row.type) }}</span>
            </div>
            <div v-if="row.used_by_username" class="code-info-row">
              <User :size="14" class="row-icon" />
              <span class="code-label">使用用户</span>
              <span class="code-value">{{ row.used_by_username }}</span>
            </div>
            <div v-if="row.note" class="code-info-row">
              <span class="code-label">备注</span>
              <span class="code-value">{{ row.note }}</span>
            </div>
            <div class="code-info-row">
              <Calendar :size="14" class="row-icon" />
              <span class="code-label">创建时间</span>
              <span class="code-value code-date">{{ formatDate(row.created_at) }}</span>
            </div>
          </div>

          <div class="code-card-footer">
            <button
              v-if="row.status === 0"
              class="btn-copy"
              :class="{ 'btn-copy-copied': copyStates[row.id]?.copied, 'btn-copying': copyStates[row.id]?.copying }"
              @click="copyCode(row.code, row.id)"
            >
              <Check v-if="copyStates[row.id]?.copied" :size="14" />
              <Copy v-else :size="14" />
              {{ copyStates[row.id]?.copied ? '已复制' : '复制' }}
            </button>
            <button
              v-if="row.status !== 1"
              class="btn-delete"
              @click="handleDelete(row)"
            >
              <Trash2 :size="14" />
              删除
            </button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="total > 0" class="pagination">
        <span class="pagination-info">共 {{ total }} 条</span>
        <div class="pagination-controls">
          <button
            class="page-btn"
            :disabled="pagination.page <= 1"
            @click="handlePageChange(pagination.page - 1)"
          >
            &lt;
          </button>
          <span class="page-current">{{ pagination.page }}</span>
          <button
            class="page-btn"
            :disabled="pagination.page * pagination.pageSize >= total"
            @click="handlePageChange(pagination.page + 1)"
          >
            &gt;
          </button>
        </div>
      </div>
    </div>

    <!-- 创建弹窗 -->
    <div v-if="showCreateDialog" class="modal-overlay" @click.self="showCreateDialog = false">
      <div class="modal-content">
        <h3 class="modal-title">添加兑换码</h3>
        <div class="modal-form">
          <div class="form-group">
            <label class="form-label">兑换码</label>
            <input
              v-model="createForm.code"
              type="text"
              class="form-input"
              placeholder="留空自动生成16位兑换码"
              maxlength="64"
            />
          </div>
          <div class="form-group">
            <label class="form-label">兑换码类型</label>
            <select v-model="createForm.type" class="form-select">
              <option v-for="t in codeTypes" :key="t.value" :value="t.value">
                {{ t.label }}
              </option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">{{ getCountLabel(createForm.type) }}</label>
            <input
              v-model.number="createForm.exchange_count"
              type="number"
              class="form-input"
              :placeholder="getCountPlaceholder(createForm.type)"
              min="1"
              :max="getCountMax(createForm.type)"
              step="0.01"
            />
            <span class="form-hint">
              <template v-if="createForm.type === 4">
                用户兑换后将获得对应金额的余额（单位：元）
              </template>
              <template v-else-if="createForm.type === 1">
                用户兑换后将获得对应天数的试用会员
              </template>
              <template v-else-if="createForm.type === 2">
                用户兑换后会员将延长对应天数
              </template>
              <template v-else>
                用户兑换后会员将延长对应月数
              </template>
            </span>
          </div>
          <div class="form-group">
            <label class="form-label">备注</label>
            <textarea
              v-model="createForm.note"
              class="form-textarea"
              rows="2"
              placeholder="选填，用于记录兑换码用途"
            ></textarea>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showCreateDialog = false">取消</button>
          <button class="btn-primary" :disabled="creating" @click="handleCreate">
            {{ creating ? '创建中...' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 批量生成弹窗 -->
    <div v-if="showBatchDialog" class="modal-overlay" @click.self="showBatchDialog = false">
      <div class="modal-content">
        <h3 class="modal-title">批量生成兑换码</h3>
        <div class="modal-form">
          <div class="form-group">
            <label class="form-label">生成数量</label>
            <input
              v-model.number="batchForm.count"
              type="number"
              class="form-input"
              min="1"
              max="100"
            />
          </div>
          <div class="form-group">
            <label class="form-label">兑换码类型</label>
            <select v-model="batchForm.type" class="form-select">
              <option v-for="t in codeTypes" :key="t.value" :value="t.value">
                {{ t.label }}
              </option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">{{ getCountLabel(batchForm.type) }}</label>
            <input
              v-model.number="batchForm.exchange_count"
              type="number"
              class="form-input"
              :placeholder="getCountPlaceholder(batchForm.type)"
              min="1"
              :max="getCountMax(batchForm.type)"
              step="0.01"
            />
            <span class="form-hint">
              <template v-if="batchForm.type === 4">
                用户兑换后将获得对应金额的余额（单位：元）
              </template>
              <template v-else-if="batchForm.type === 1">
                用户兑换后将获得对应天数的试用会员
              </template>
              <template v-else-if="batchForm.type === 2">
                用户兑换后会员将延长对应天数
              </template>
              <template v-else>
                用户兑换后会员将延长对应月数
              </template>
            </span>
          </div>
          <div class="form-group">
            <label class="form-label">备注</label>
            <textarea
              v-model="batchForm.note"
              class="form-textarea"
              rows="2"
              placeholder="选填"
            ></textarea>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showBatchDialog = false">取消</button>
          <button class="btn-primary" :disabled="batchCreating" @click="handleBatchCreate">
            {{ batchCreating ? '生成中...' : '生成' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 批量结果弹窗 -->
    <div v-if="showBatchResultDialog" class="modal-overlay" @click.self="showBatchResultDialog = false">
      <div class="modal-content modal-large">
        <h3 class="modal-title">生成结果 ({{ batchResult.length }} 个)</h3>
        <div class="result-codes">
          <code v-for="(code, i) in batchResult" :key="i" class="result-code">{{ code }}</code>
        </div>
        <div class="modal-actions">
          <button class="btn-primary" @click="copyAllCodes">复制全部</button>
          <button class="btn-secondary" @click="showBatchResultDialog = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.exchange-codes-page {
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

/* ===== 统计卡片 ===== */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}

@media (min-width: 640px) {
  .stats-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

.stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
}

.stat-blue {
  background: linear-gradient(135deg, var(--primary), #6366f1);
}

.stat-green {
  background: linear-gradient(135deg, var(--success), #10b981);
}

.stat-purple {
  background: linear-gradient(135deg, #8b5cf6, #6366f1);
}

.stat-orange {
  background: linear-gradient(135deg, var(--warning), #f59e0b);
}

.stat-content {
  flex: 1;
  min-width: 0;
}

.stat-value {
  font-size: var(--font-size-4xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  margin: 0;
  line-height: 1;
}

.stat-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  margin: var(--space-1) 0 0 0;
}

/* ===== 筛选栏 ===== */
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

.filter-row {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}

.filter-select {
  flex: 1;
  min-width: 100px;
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

.action-buttons {
  display: flex;
  gap: var(--space-2);
}

.btn-primary, .btn-success {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  flex: 1;
  padding: var(--space-3) var(--space-4);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-primary {
  background: var(--primary);
  color: white;
}

.btn-success {
  background: var(--success);
  color: white;
}

.btn-primary:active, .btn-success:active {
  transform: scale(0.98);
}

/* ===== 兑换码列表 ===== */
.codes-list {
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

.code-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.code-card {
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.code-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.code-title-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
}

.code-icon {
  color: var(--primary);
  flex-shrink: 0;
}

.code-text {
  font-family: monospace;
  font-size: var(--font-size-md);
  background: var(--primary-bg);
  color: var(--primary);
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  overflow: hidden;
  text-overflow: ellipsis;
}

.type-badge {
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  flex-shrink: 0;
}

.code-card-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.code-info-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.row-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.code-label {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  min-width: 70px;
}

.code-value {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.code-date {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.status-select {
  padding: 4px var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  background: var(--bg-input);
  color: var(--text-primary);
}

.status-tag {
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.status-used {
  background: var(--success-bg);
  color: var(--success);
}

.code-card-footer {
  display: flex;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.btn-copy, .btn-delete {
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

.btn-copy {
  background: var(--primary-bg);
  color: var(--primary);
  transition: all 150ms ease;
}

.btn-copy:active {
  transform: scale(0.95);
}

.btn-copy-copied {
  background: var(--success-bg) !important;
  color: var(--success) !important;
  border: 1px solid var(--success);
}

.btn-copying {
  opacity: 0.6;
  cursor: wait;
}

.btn-copying svg {
  animation: spin 0.5s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.btn-delete {
  background: var(--danger-bg);
  color: var(--danger);
}

/* ===== 分页 ===== */
.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) 0;
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
  max-height: 80vh;
  overflow-y: auto;
}

.modal-large {
  max-width: 500px;
}

.modal-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin: 0 0 var(--space-4) 0;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.form-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.form-hint {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  line-height: 1.4;
}

.form-input, .form-select, .form-textarea {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-md);
  color: var(--text-primary);
  background: var(--bg-input);
  outline: none;
}

.form-textarea {
  resize: vertical;
  min-height: 60px;
}

.form-input:focus, .form-select:focus, .form-textarea:focus {
  border-color: var(--primary);
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

.result-codes {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  max-height: 200px;
  overflow-y: auto;
  padding: var(--space-2);
  background: var(--bg-input);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-4);
}

.result-code {
  display: block;
  font-family: monospace;
  font-size: var(--font-size-xs);
  color: var(--text-primary);
  padding: 4px var(--space-2);
  background: var(--bg-card);
  border-radius: 4px;
  word-break: break-all;
}

/* ===== 响应式 ===== */
@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .filter-row {
    flex-direction: column;
  }

  .filter-select {
    width: 100%;
  }

  .action-buttons {
    flex-direction: column;
  }

  .modal-content {
    max-width: calc(100vw - 32px);
  }
}
</style>
