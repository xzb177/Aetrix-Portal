<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  Shield, Zap, Activity, AlertTriangle, CheckCircle, XCircle,
  RefreshCw, Settings, Bell, Trash2, Plus, Save, Eye, EyeOff
} from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'

// ==================== 类型定义 ====================

interface FeatureFlag {
  key: string
  value: string
  label: string
  description: string
  type: 'boolean' | 'number' | 'text'
  default: string
}

interface RateLimitRule {
  id?: number
  name: string
  endpoint: string
  limit: number
  window: number
  scope: 'user' | 'ip' | 'anon'
  enabled: boolean
}

interface BlacklistEntry {
  id?: number
  type: 'ip' | 'user_id' | 'anon_id'
  value: string
  reason?: string
  expires_at?: string
  enabled: boolean
}

interface EventStats {
  date: string
  total_events: number
  by_type: Record<string, number>
  error_rate: number
  top_errors: Array<{
    type: string
    user_id?: number
    ip?: string
    details: any
    timestamp: string
  }>
}

interface AlertConfig {
  id?: number
  name: string
  event_type: string
  threshold: number
  window_minutes: number
  enabled: boolean
  telegram_notify: boolean
}

// ==================== 状态 ====================

const activeTab = ref('flags')
const loading = ref(false)
const saving = ref(false)

// Feature Flags
const featureFlags = ref<FeatureFlag[]>([])
const flagsLastUpdated = ref<Date | null>(null)

// Rate Limits
const rateLimits = ref<RateLimitRule[]>([])
const showRateLimitDialog = ref(false)
const editingRateLimit = ref<RateLimitRule | null>(null)

// Blacklist
const blacklist = ref<BlacklistEntry[]>([])
const showBlacklistDialog = ref(false)
const editingBlacklist = ref<BlacklistEntry | null>(null)

// Stats
const todayStats = ref<EventStats | null>(null)
const recentErrors = ref<any[]>([])

// Alerts
const alerts = ref<AlertConfig[]>([])
const showAlertDialog = ref(false)
const editingAlert = ref<AlertConfig | null>(null)

// ==================== 计算属性 ====================

const booleanFlags = computed(() => featureFlags.value.filter(f => f.type === 'boolean'))
const hasChanges = computed(() => {
  // 简化的脏检查 - 实际实现中需要更复杂的逻辑
  return false
})

// ==================== 方法 ====================

async function loadFeatureFlags() {
  loading.value = true
  try {
    const response = await fetch('/api/admin-ops/feature-flags', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
    })
    if (response.ok) {
      const data = await response.json()
      featureFlags.value = data.flags
      flagsLastUpdated.value = data.last_updated ? new Date(data.last_updated) : null
    }
  } catch (error) {
    ElMessage.error('加载 Feature Flags 失败')
  } finally {
    loading.value = false
  }
}

async function toggleFlag(flag: FeatureFlag) {
  const newValue = flag.value === 'true' ? 'false' : 'true'

  try {
    const response = await fetch(`/api/admin-ops/feature-flags/${flag.key}?value=${newValue}`, {
      method: 'PUT',
      headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
    })
    if (response.ok) {
      flag.value = newValue
      ElMessage.success('Feature Flag 已更新')
    } else {
      ElMessage.error('更新失败')
    }
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

async function loadRateLimits() {
  try {
    const response = await fetch('/api/admin-ops/rate-limits', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
    })
    if (response.ok) {
      rateLimits.value = await response.json()
    }
  } catch (error) {
    console.error('加载限速规则失败:', error)
  }
}

async function loadBlacklist() {
  try {
    const response = await fetch('/api/admin-ops/blacklist', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
    })
    if (response.ok) {
      blacklist.value = await response.json()
    }
  } catch (error) {
    console.error('加载黑名单失败:', error)
  }
}

async function loadStats() {
  try {
    const [statsRes, errorsRes] = await Promise.all([
      fetch('/api/admin-ops/stats/today', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
      }),
      fetch('/api/admin-ops/stats/recent-errors?limit=10', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
      })
    ])

    if (statsRes.ok) {
      todayStats.value = await statsRes.json()
    }
    if (errorsRes.ok) {
      recentErrors.value = await errorsRes.json()
    }
  } catch (error) {
    console.error('加载统计数据失败:', error)
  }
}

async function loadAlerts() {
  try {
    const response = await fetch('/api/admin-ops/alerts', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
    })
    if (response.ok) {
      alerts.value = await response.json()
    }
  } catch (error) {
    console.error('加载告警配置失败:', error)
  }
}

function openRateLimitDialog(rule?: RateLimitRule) {
  editingRateLimit.value = rule || {
    name: '',
    endpoint: 'register',
    limit: 10,
    window: 60,
    scope: 'ip',
    enabled: true
  }
  showRateLimitDialog.value = true
}

async function saveRateLimit() {
  if (!editingRateLimit.value) return

  try {
    const response = await fetch('/api/admin-ops/rate-limits', {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(editingRateLimit.value)
    })
    if (response.ok) {
      ElMessage.success('限速规则已保存')
      showRateLimitDialog.value = false
      loadRateLimits()
    } else {
      ElMessage.error('保存失败')
    }
  } catch (error) {
    ElMessage.error('保存失败')
  }
}

async function deleteRateLimit(index: number) {
  try {
    await ElMessageBox.confirm('确定要删除这个限速规则吗？', '确认删除')
    // 实现删除逻辑
    rateLimits.value.splice(index, 1)
    ElMessage.success('限速规则已删除')
  } catch {
    // 用户取消
  }
}

function openBlacklistDialog(entry?: BlacklistEntry) {
  editingBlacklist.value = entry || {
    type: 'ip',
    value: '',
    reason: '',
    enabled: true
  }
  showBlacklistDialog.value = true
}

async function saveBlacklist() {
  if (!editingBlacklist.value) return

  try {
    const response = await fetch('/api/admin-ops/blacklist', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(editingBlacklist.value)
    })
    if (response.ok) {
      ElMessage.success('黑名单条目已添加')
      showBlacklistDialog.value = false
      loadBlacklist()
    } else {
      ElMessage.error('添加失败')
    }
  } catch (error) {
    ElMessage.error('添加失败')
  }
}

async function removeBlacklist(entry: BlacklistEntry, index: number) {
  if (!entry.id) return

  try {
    await ElMessageBox.confirm(`确定要删除 ${entry.value} 吗？`, '确认删除')

    const response = await fetch(`/api/admin-ops/blacklist/${entry.id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${localStorage.getItem('admin_token')}` }
    })
    if (response.ok) {
      blacklist.value.splice(index, 1)
      ElMessage.success('黑名单条目已删除')
    } else {
      ElMessage.error('删除失败')
    }
  } catch {
    // 用户取消
  }
}

function openAlertDialog(alert?: AlertConfig) {
  editingAlert.value = alert || {
    name: '',
    event_type: 'payment_fail',
    threshold: 10,
    window_minutes: 5,
    enabled: true,
    telegram_notify: true
  }
  showAlertDialog.value = true
}

async function saveAlert() {
  if (!editingAlert.value) return

  try {
    const response = await fetch('/api/admin-ops/alerts', {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('admin_token')}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(editingAlert.value)
    })
    if (response.ok) {
      ElMessage.success('告警配置已保存')
      showAlertDialog.value = false
      loadAlerts()
    } else {
      ElMessage.error('保存失败')
    }
  } catch (error) {
    ElMessage.error('保存失败')
  }
}

function refreshAll() {
  loadFeatureFlags()
  loadRateLimits()
  loadBlacklist()
  loadStats()
  loadAlerts()
  ElMessage.success('数据已刷新')
}

// ==================== 生命周期 ====================

onMounted(() => {
  refreshAll()
  // 定期刷新统计数据
  const interval = setInterval(() => {
    if (activeTab.value === 'stats') {
      loadStats()
    }
  }, 30000)

  onUnmounted(() => clearInterval(interval))
})
</script>

<template>
  <div class="admin-ops-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">
          <Shield :size="24" />
          运营中控台
        </h1>
        <p class="page-description">Feature Flags • 风控 • 观测</p>
      </div>
      <div class="header-actions">
        <button class="btn-icon" @click="refreshAll" :disabled="loading">
          <RefreshCw :size="18" :class="{ spinning: loading }" />
        </button>
      </div>
    </div>

    <!-- 标签页 -->
    <div class="tabs">
      <button
        v-for="tab in [
          { id: 'flags', label: 'Feature Flags', icon: Settings },
          { id: 'ratelimit', label: '风控', icon: Shield },
          { id: 'stats', label: '观测', icon: Activity }
        ]"
        :key="tab.id"
        class="tab"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <component :is="tab.icon" :size="16" />
        {{ tab.label }}
      </button>
    </div>

    <!-- Feature Flags 面板 -->
    <div v-show="activeTab === 'flags'" class="panel">
      <div class="panel-header">
        <h2 class="panel-title">功能开关配置</h2>
        <span v-if="flagsLastUpdated" class="last-updated">
          更新于 {{ flagsLastUpdated.toLocaleTimeString() }}
        </span>
      </div>

      <div class="flags-grid">
        <div v-for="flag in featureFlags" :key="flag.key" class="flag-card">
          <div class="flag-header">
            <span class="flag-label">{{ flag.label }}</span>
            <button
              class="toggle-switch"
              :class="{ active: flag.value === 'true' }"
              @click="toggleFlag(flag)"
            >
              <span class="toggle-slider"></span>
            </button>
          </div>
          <p class="flag-description">{{ flag.description }}</p>
          <div class="flag-meta">
            <code class="flag-key">{{ flag.key }}</code>
            <span class="flag-default">默认: {{ flag.default }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 风控面板 -->
    <div v-show="activeTab === 'ratelimit'" class="panel">
      <div class="panel-section">
        <div class="section-header">
          <h2 class="section-title">限速规则</h2>
          <button class="btn-primary" @click="openRateLimitDialog()">
            <Plus :size="16" />
            添加规则
          </button>
        </div>

        <div class="rule-list">
          <div v-for="(rule, index) in rateLimits" :key="rule.name" class="rule-card">
            <div class="rule-info">
              <div class="rule-name">{{ rule.name }}</div>
              <div class="rule-details">
                <span class="rule-detail">{{ rule.endpoint }}</span>
                <span class="rule-detail">{{ rule.limit }}次/{{ rule.window }}秒</span>
                <span class="rule-detail">{{ rule.scope }}</span>
              </div>
            </div>
            <div class="rule-actions">
              <span class="status-badge" :class="{ active: rule.enabled }">
                {{ rule.enabled ? '启用' : '禁用' }}
              </span>
              <button class="btn-icon" @click="openRateLimitDialog(rule)">
                <Settings :size="16" />
              </button>
              <button class="btn-icon danger" @click="deleteRateLimit(index)">
                <Trash2 :size="16" />
              </button>
            </div>
          </div>

          <div v-if="rateLimits.length === 0" class="empty-state">
            <Shield :size="32" />
            <p>暂无限速规则</p>
          </div>
        </div>
      </div>

      <div class="panel-section">
        <div class="section-header">
          <h2 class="section-title">黑名单</h2>
          <button class="btn-primary" @click="openBlacklistDialog()">
            <Plus :size="16" />
            添加
          </button>
        </div>

        <div class="blacklist-list">
          <div v-for="(entry, index) in blacklist" :key="entry.id || entry.value" class="blacklist-card">
            <div class="blacklist-info">
              <div class="blacklist-type">{{ entry.type }}</div>
              <code class="blacklist-value">{{ entry.value }}</code>
              <span v-if="entry.reason" class="blacklist-reason">{{ entry.reason }}</span>
            </div>
            <div class="blacklist-actions">
              <span class="status-badge" :class="{ active: entry.enabled }">
                {{ entry.enabled ? '启用' : '禁用' }}
              </span>
              <button class="btn-icon danger" @click="removeBlacklist(entry, index)">
                <Trash2 :size="16" />
              </button>
            </div>
          </div>

          <div v-if="blacklist.length === 0" class="empty-state">
            <Shield :size="32" />
            <p>黑名单为空</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 观测面板 -->
    <div v-show="activeTab === 'stats'" class="panel">
      <div class="panel-section">
        <div class="section-header">
          <h2 class="section-title">今日统计</h2>
          <button class="btn-icon" @click="loadStats">
            <RefreshCw :size="16" />
          </button>
        </div>

        <div v-if="todayStats" class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">{{ todayStats.total_events }}</div>
            <div class="stat-label">总事件</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ (todayStats.error_rate * 100).toFixed(1) }}%</div>
            <div class="stat-label">错误率</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ Object.keys(todayStats.by_type).length }}</div>
            <div class="stat-label">事件类型</div>
          </div>
        </div>

        <div class="events-list">
          <h3 class="subsection-title">事件分布</h3>
          <div class="event-bars">
            <div v-for="(count, type) in todayStats.by_type" :key="type" class="event-bar">
              <span class="event-name">{{ type }}</span>
              <div class="bar-container">
                <div class="bar-fill" :style="{ width: `${(count / todayStats.total_events * 100)}%` }"></div>
              </div>
              <span class="event-count">{{ count }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="panel-section">
        <div class="section-header">
          <h2 class="section-title">最近错误</h2>
        </div>

        <div class="errors-list">
          <div v-for="error in recentErrors" :key="error.id" class="error-item">
            <div class="error-type">{{ error.action }}</div>
            <div class="error-message">{{ error.details }}</div>
            <div class="error-time">{{ new Date(error.created_at).toLocaleString() }}</div>
          </div>

          <div v-if="recentErrors.length === 0" class="empty-state">
            <CheckCircle :size="32" />
            <p>没有错误记录</p>
          </div>
        </div>
      </div>

      <div class="panel-section">
        <div class="section-header">
          <h2 class="section-title">告警配置</h2>
          <button class="btn-primary" @click="openAlertDialog()">
            <Plus :size="16" />
            添加告警
          </button>
        </div>

        <div class="alerts-list">
          <div v-for="alert in alerts" :key="alert.id || alert.name" class="alert-card">
            <div class="alert-info">
              <div class="alert-name">{{ alert.name }}</div>
              <div class="alert-details">
                <span>{{ alert.event_type }}</span>
                <span>超过 {{ alert.threshold }} 次/{{ alert.window_minutes }} 分钟</span>
              </div>
            </div>
            <div class="alert-actions">
              <Bell :size="16" :class="{ active: alert.telegram_notify }" />
              <span class="status-badge" :class="{ active: alert.enabled }">
                {{ alert.enabled ? '启用' : '禁用' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 限速规则对话框 -->
    <div v-if="showRateLimitDialog" class="dialog-overlay" @click.self="showRateLimitDialog = false">
      <div class="dialog">
        <h3>{{ editingRateLimit?.id ? '编辑' : '添加' }}限速规则</h3>
        <div class="form-group">
          <label>规则名称</label>
          <input v-model="editingRateLimit.name" placeholder="如：注册限速" />
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>接口</label>
            <select v-model="editingRateLimit.endpoint">
              <option value="register">注册</option>
              <option value="login">登录</option>
              <option value="invite">邀请</option>
              <option value="request">求片</option>
              <option value="payment">支付</option>
            </select>
          </div>
          <div class="form-group">
            <label>作用域</label>
            <select v-model="editingRateLimit.scope">
              <option value="ip">IP</option>
              <option value="user">用户ID</option>
              <option value="anon">匿名ID</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>限制次数</label>
            <input type="number" v-model.number="editingRateLimit.limit" />
          </div>
          <div class="form-group">
            <label>时间窗口（秒）</label>
            <input type="number" v-model.number="editingRateLimit.window" />
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-secondary" @click="showRateLimitDialog = false">取消</button>
          <button class="btn-primary" @click="saveRateLimit">保存</button>
        </div>
      </div>
    </div>

    <!-- 黑名单对话框 -->
    <div v-if="showBlacklistDialog" class="dialog-overlay" @click.self="showBlacklistDialog = false">
      <div class="dialog">
        <h3>添加黑名单</h3>
        <div class="form-group">
          <label>类型</label>
          <select v-model="editingBlacklist.type">
            <option value="ip">IP 地址</option>
            <option value="user_id">用户 ID</option>
            <option value="anon_id">匿名 ID</option>
          </select>
        </div>
        <div class="form-group">
          <label>值</label>
          <input v-model="editingBlacklist.value" :placeholder="editingBlacklist.type === 'ip' ? '127.0.0.1' : '123'" />
        </div>
        <div class="form-group">
          <label>原因</label>
          <input v-model="editingBlacklist.reason" placeholder="如：恶意请求" />
        </div>
        <div class="form-actions">
          <button class="btn-secondary" @click="showBlacklistDialog = false">取消</button>
          <button class="btn-primary" @click="saveBlacklist">添加</button>
        </div>
      </div>
    </div>

    <!-- 告警配置对话框 -->
    <div v-if="showAlertDialog" class="dialog-overlay" @click.self="showAlertDialog = false">
      <div class="dialog">
        <h3>{{ editingAlert?.id ? '编辑' : '添加' }}告警</h3>
        <div class="form-group">
          <label>告警名称</label>
          <input v-model="editingAlert.name" placeholder="如：支付失败告警" />
        </div>
        <div class="form-group">
          <label>事件类型</label>
          <input v-model="editingAlert.event_type" placeholder="如：payment_fail" />
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>阈值（次）</label>
            <input type="number" v-model.number="editingAlert.threshold" />
          </div>
          <div class="form-group">
            <label>时间窗口（分钟）</label>
            <input type="number" v-model.number="editingAlert.window_minutes" />
          </div>
        </div>
        <div class="form-actions">
          <button class="btn-secondary" @click="showAlertDialog = false">取消</button>
          <button class="btn-primary" @click="saveAlert">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-ops-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
  color: #fff;
}

/* 页面头部 */
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
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 24px;
  font-weight: 600;
  margin: 0;
}

.page-description {
  color: rgba(255, 255, 255, 0.5);
  font-size: 14px;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 12px;
}

/* 标签页 */
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  background: rgba(255, 255, 255, 0.05);
  padding: 4px;
  border-radius: 12px;
  width: fit-content;
}

.tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
}

.tab:hover {
  background: rgba(255, 255, 255, 0.05);
}

.tab.active {
  background: var(--primary, #10b981);
  color: #fff;
}

/* 面板 */
.panel {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.last-updated {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
}

.panel-section {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  padding: 20px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.subsection-title {
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 12px 0;
}

/* Feature Flags */
.flags-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.flag-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 16px;
}

.flag-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.flag-label {
  font-weight: 500;
}

.flag-description {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 12px 0;
  line-height: 1.5;
}

.flag-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.flag-key {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.3);
  background: rgba(255, 255, 255, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
}

.flag-default {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.3);
}

/* 开关按钮 */
.toggle-switch {
  position: relative;
  width: 44px;
  height: 24px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  border: none;
  cursor: pointer;
  transition: background 0.2s;
}

.toggle-switch.active {
  background: var(--primary, #10b981);
}

.toggle-slider {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
}

.toggle-switch.active .toggle-slider {
  transform: translateX(20px);
}

/* 限速规则/黑名单 */
.rule-list, .blacklist-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rule-card, .blacklist-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 16px;
}

.rule-info, .blacklist-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rule-name {
  font-weight: 500;
}

.rule-details {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}

.rule-detail {
  background: rgba(255, 255, 255, 0.05);
  padding: 2px 8px;
  border-radius: 4px;
}

.blacklist-type {
  font-size: 12px;
  color: var(--primary, #10b981);
  text-transform: uppercase;
}

.blacklist-value {
  font-family: monospace;
  font-size: 13px;
  color: rgba(255, 255, 255, 255, 0.7);
}

.blacklist-reason {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.4);
}

.rule-actions, .blacklist-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.status-badge {
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.4);
}

.status-badge.active {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 20px;
  text-align: center;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--primary, #10b981);
}

.stat-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}

/* 事件条 */
.event-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.event-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.event-name {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.7);
  min-width: 100px;
}

.bar-container {
  flex: 1;
  height: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: var(--primary, #10b981);
  transition: width 0.3s ease;
}

.event-count {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  min-width: 40px;
  text-align: right;
}

/* 错误列表 */
.errors-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.error-item {
  display: grid;
  grid-template-columns: 1fr 2fr auto;
  gap: 12px;
  padding: 12px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  font-size: 13px;
}

.error-type {
  color: #ef4444;
}

.error-message {
  color: rgba(255, 255, 255, 0.7);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.error-time {
  color: rgba(255, 255, 255, 0.4);
  font-size: 11px;
}

/* 告警列表 */
.alerts-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.alert-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: 16px;
}

.alert-name {
  font-weight: 500;
}

.alert-details {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}

.alert-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.alert-actions svg {
  color: rgba(255, 255, 255, 0.3);
}

.alert-actions svg.active {
  color: #10b981;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: rgba(255, 255, 255, 0.3);
}

.empty-state svg {
  margin-bottom: 12px;
  opacity: 0.5;
}

/* 对话框 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.dialog {
  background: #1a1a1a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 24px;
  width: 100%;
  max-width: 400px;
}

.dialog h3 {
  margin: 0 0 20px 0;
  font-size: 18px;
}

.form-group {
  margin-bottom: 16px;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
}

.form-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}

/* 按钮 */
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: var(--primary, #10b981);
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-secondary {
  padding: 10px 20px;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}

.btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
}

.btn-icon:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
}

.btn-icon.spinning svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.btn-icon.danger {
  color: #ef4444;
}

.btn-icon.danger:hover {
  background: rgba(239, 68, 68, 0.1);
}

/* 动画 */
.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
