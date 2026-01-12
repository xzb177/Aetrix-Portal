<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  Shield,
  Clock,
  Globe,
  Smartphone,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Eye,
  EyeOff,
  Trash2,
  RefreshCw,
  Bell,
  Lock,
  Key,
  History,
  Activity
} from 'lucide-vue-next'
import {
  getLoginHistory,
  getActiveSessions,
  revokeSession,
  revokeAllOtherSessions,
  getSecurityStats,
  updateSecuritySettings,
  checkPasswordStrength
} from '@/api/security'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

// 数据状态
const loading = ref(false)
const activeTab = ref<'overview' | 'sessions' | 'history' | 'settings'>('overview')

// 安全统计
const securityStats = ref({
  total_logins: 0,
  failed_attempts: 0,
  active_sessions: 0,
  last_password_change: '',
  security_score: 0,
  risk_level: 'low' as 'low' | 'medium' | 'high'
})

// 登录历史
const loginHistory = ref<any[]>([])
const historyPage = ref(1)
const historyTotal = ref(0)

// 活跃会话
const activeSessions = ref<any[]>([])
const currentSessionId = ref('')

// 安全设置
const securitySettings = ref({
  enable_login_alert: true,
  enable_2fa: false,
  trusted_ips: [] as string[]
})
const savingSettings = ref(false)

// 新增信任IP
const newIp = ref('')

// 加载数据
const loadSecurityStats = async () => {
  try {
    const response = await getSecurityStats() as any
    securityStats.value = response
  } catch (error) {
    console.error('加载安全统计失败:', error)
  }
}

const loadLoginHistory = async () => {
  loading.value = true
  try {
    const response = await getLoginHistory({ page: historyPage.value }) as any
    loginHistory.value = response.items || []
    historyTotal.value = response.total || 0
  } catch (error) {
    console.error('加载登录历史失败:', error)
  } finally {
    loading.value = false
  }
}

const loadActiveSessions = async () => {
  try {
    const response = await getActiveSessions() as any
    activeSessions.value = response.sessions || []
    currentSessionId.value = response.current_session_id || ''
  } catch (error) {
    console.error('加载活跃会话失败:', error)
  }
}

// 操作函数
const handleRevokeSession = async (sessionId: string) => {
  if (sessionId === currentSessionId.value) {
    alert('不能撤销当前会话')
    return
  }

  if (!confirm('确定要撤销此会话吗？')) return

  try {
    await revokeSession(sessionId)
    await loadActiveSessions()
    await loadSecurityStats()
  } catch (error: any) {
    alert(error?.response?.data?.detail || '撤销失败')
  }
}

const handleRevokeAllOthers = async () => {
  if (!confirm('确定要撤销所有其他会话吗？此操作不可撤销。')) return

  try {
    await revokeAllOtherSessions()
    await loadActiveSessions()
    await loadSecurityStats()
  } catch (error: any) {
    alert(error?.response?.data?.detail || '撤销失败')
  }
}

const handleSaveSecuritySettings = async () => {
  savingSettings.value = true
  try {
    await updateSecuritySettings(securitySettings.value)
    alert('安全设置已保存')
  } catch (error: any) {
    alert(error?.response?.data?.detail || '保存失败')
  } finally {
    savingSettings.value = false
  }
}

const handleAddTrustedIp = () => {
  const ip = newIp.value.trim()
  if (!ip) return

  // 简单的IP格式验证
  const ipPattern = /^(\d{1,3}\.){3}\d{1,3}$|^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/
  if (!ipPattern.test(ip)) {
    alert('请输入有效的IP地址（如：192.168.1.1 或 192.168.1.0/24）')
    return
  }

  if (securitySettings.value.trusted_ips.includes(ip)) {
    alert('该IP已在列表中')
    return
  }

  securitySettings.value.trusted_ips.push(ip)
  newIp.value = ''
}

const handleRemoveTrustedIp = (ip: string) => {
  securitySettings.value.trusted_ips = securitySettings.value.trusted_ips.filter(i => i !== ip)
}

// 计算属性
const securityScore = computed(() => {
  const score = securityStats.value.security_score
  if (score >= 80) return { level: 'high', color: '#4CAF50', text: '高' }
  if (score >= 50) return { level: 'medium', color: '#FF9800', text: '中' }
  return { level: 'low', color: '#F44336', text: '低' }
})

const failedLogins = computed(() => {
  return loginHistory.value.filter(log => log.action.includes('failed'))
})

const successfulLogins = computed(() => {
  return loginHistory.value.filter(log => log.action.includes('success'))
})

// 获取设备图标
const getDeviceIcon = (userAgent: string) => {
  const ua = userAgent.toLowerCase()
  if (ua.includes('mobile') || ua.includes('android') || ua.includes('iphone')) {
    return Smartphone
  }
  return Globe
}

// 获取浏览器信息
const getBrowserInfo = (userAgent: string) => {
  const ua = userAgent.toLowerCase()
  if (ua.includes('chrome')) return 'Chrome'
  if (ua.includes('firefox')) return 'Firefox'
  if (ua.includes('safari')) return 'Safari'
  if (ua.includes('edge')) return 'Edge'
  return 'Unknown'
}

// 格式化时间
const formatTime = (timeStr: string) => {
  if (!timeStr) return '-'
  const date = new Date(timeStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)} 天前`

  return date.toLocaleString('zh-CN')
}

// 获取状态样式
const getStatusClass = (action: string) => {
  if (action.includes('success')) return 'status-success'
  if (action.includes('failed')) return 'status-error'
  if (action.includes('locked')) return 'status-warning'
  return 'status-info'
}

const getStatusText = (action: string) => {
  if (action.includes('success')) return '登录成功'
  if (action.includes('failed')) return '登录失败'
  if (action.includes('locked')) return '账号锁定'
  if (action.includes('expired')) return '会话过期'
  if (action.includes('logout')) return '登出'
  return action
}

// Tabs
const tabs = [
  { key: 'overview' as const, icon: Shield, label: '安全概览' },
  { key: 'sessions' as const, icon: Globe, label: '活跃会话' },
  { key: 'history' as const, icon: History, label: '登录历史' },
  { key: 'settings' as const, icon: Lock, label: '安全设置' },
]

onMounted(() => {
  loadSecurityStats()
  loadLoginHistory()
  loadActiveSessions()
})
</script>

<template>
  <div class="security-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="refresh-btn" @click="() => { loadSecurityStats(); loadLoginHistory(); loadActiveSessions() }" :class="{ spinning: loading }">
        <RefreshCw :size="18" />
      </button>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="['tab-btn', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key"
      >
        <component :is="tab.icon" :size="16" />
        <span>{{ tab.label }}</span>
        <span v-if="tab.key === 'sessions' && activeSessions.length > 0" class="tab-badge">
          {{ activeSessions.length }}
        </span>
      </button>
    </div>

    <!-- 安全概览 -->
    <div v-if="activeTab === 'overview'" class="overview-content">
      <!-- 安全评分 -->
      <div class="security-score-card">
        <div class="score-circle">
          <div class="score-value">{{ securityStats.security_score }}</div>
          <div class="score-label">安全评分</div>
        </div>
        <div class="score-info">
          <h3>安全等级: <span :style="{ color: securityScore.color }">{{ securityScore.text }}</span></h3>
          <p>根据您的账户活动、登录历史和安全设置计算</p>
        </div>
      </div>

      <!-- 安全统计 -->
      <div class="stats-grid">
        <div class="stat-card stat-success">
          <div class="stat-icon"><CheckCircle :size="20" /></div>
          <div class="stat-content">
            <p class="stat-value">{{ securityStats.total_logins }}</p>
            <p class="stat-label">总登录次数</p>
          </div>
        </div>
        <div class="stat-card stat-error">
          <div class="stat-icon"><XCircle :size="20" /></div>
          <div class="stat-content">
            <p class="stat-value">{{ securityStats.failed_attempts }}</p>
            <p class="stat-label">失败尝试</p>
          </div>
        </div>
        <div class="stat-card stat-info">
          <div class="stat-icon"><Activity :size="20" /></div>
          <div class="stat-content">
            <p class="stat-value">{{ securityStats.active_sessions }}</p>
            <p class="stat-label">活跃会话</p>
          </div>
        </div>
      </div>

      <!-- 安全建议 -->
      <div class="security-tips">
        <h3>
          <Bell :size="18" />
          安全建议
        </h3>
        <div class="tips-list">
          <div v-if="securityStats.security_score < 100" class="tip-item tip-warning">
            <AlertTriangle :size="16" />
            <span>您的安全分数不是满分，建议开启所有安全功能</span>
          </div>
          <div class="tip-item tip-success">
            <CheckCircle :size="16" />
            <span>定期更换密码可以有效保护账户安全</span>
          </div>
          <div class="tip-item tip-success">
            <CheckCircle :size="16" />
            <span>检查活跃会话，及时撤销异常登录</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 活跃会话 -->
    <div v-if="activeTab === 'sessions'" class="sessions-content">
      <div class="sessions-header">
        <h3>当前活跃会话 ({{ activeSessions.length }})</h3>
        <button v-if="activeSessions.length > 1" class="btn-danger" @click="handleRevokeAllOthers">
          <Trash2 :size="14" />
          撤销所有其他会话
        </button>
      </div>

      <div class="sessions-list">
        <div v-for="session in activeSessions" :key="session.id" class="session-card" :class="{ 'current-session': session.id === currentSessionId }">
          <div class="session-icon">
            <component :is="getDeviceIcon(session.user_agent)" :size="24" />
          </div>
          <div class="session-info">
            <div class="session-main">
              <span class="session-device">{{ getBrowserInfo(session.user_agent) }}</span>
              <span v-if="session.id === currentSessionId" class="current-badge">当前</span>
            </div>
            <div class="session-details">
              <span>{{ session.ip_address }}</span>
              <span>{{ formatTime(session.created_at) }}</span>
            </div>
          </div>
          <div class="session-actions">
            <span class="session-last-active">活跃: {{ formatTime(session.last_active) }}</span>
            <button
              v-if="session.id !== currentSessionId"
              class="btn-icon btn-danger"
              @click="handleRevokeSession(session.id)"
              title="撤销会话"
            >
              <XCircle :size="16" />
            </button>
          </div>
        </div>

        <div v-if="activeSessions.length === 0" class="empty-state">
          <Globe :size="48" />
          <p>暂无活跃会话</p>
        </div>
      </div>
    </div>

    <!-- 登录历史 -->
    <div v-if="activeTab === 'history'" class="history-content">
      <div class="history-header">
        <h3>登录历史</h3>
        <div class="history-filters">
          <button :class="['filter-btn', { active: true }]">全部</button>
          <button :class="['filter-btn']">成功</button>
          <button :class="['filter-btn']">失败</button>
        </div>
      </div>

      <div class="history-list">
        <div v-for="log in loginHistory" :key="log.id" class="history-item">
          <div class="history-icon" :class="getStatusClass(log.action)">
            <CheckCircle v-if="log.action.includes('success')" :size="16" />
            <XCircle v-else-if="log.action.includes('failed')" :size="16" />
            <AlertTriangle v-else :size="16" />
          </div>
          <div class="history-info">
            <span class="history-action">{{ getStatusText(log.action) }}</span>
            <span class="history-time">{{ formatTime(log.created_at) }}</span>
          </div>
          <div class="history-details">
            <span>{{ log.ip_address }}</span>
            <span class="history-browser">{{ getBrowserInfo(log.user_agent || '') }}</span>
          </div>
        </div>

        <div v-if="loginHistory.length === 0 && !loading" class="empty-state">
          <History :size="48" />
          <p>暂无登录记录</p>
        </div>
      </div>
    </div>

    <!-- 安全设置 -->
    <div v-if="activeTab === 'settings'" class="settings-content">
      <div class="settings-section">
        <h3>
          <Bell :size="18" />
          登录通知
        </h3>
        <div class="setting-item">
          <div class="setting-info">
            <p class="setting-label">登录提醒</p>
            <p class="setting-desc">当新设备登录时发送通知</p>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" v-model="securitySettings.enable_login_alert">
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>

      <div class="settings-section">
        <h3>
          <Key :size="18" />
          两步验证
        </h3>
        <div class="setting-item">
          <div class="setting-info">
            <p class="setting-label">启用两步验证</p>
            <p class="setting-desc">登录时需要额外的验证码（暂未开放）</p>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" v-model="securitySettings.enable_2fa" disabled>
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>

      <div class="settings-section">
        <h3>
          <Shield :size="18" />
          信任IP
        </h3>
        <p class="section-desc">来自以下IP的登录将跳过部分安全检查</p>

        <div class="trusted-ips">
          <div v-for="(ip, index) in securitySettings.trusted_ips" :key="index" class="ip-tag">
            <code>{{ ip }}</code>
            <button class="ip-remove" @click="handleRemoveTrustedIp(ip)">
              <XCircle :size="14" />
            </button>
          </div>
          <div v-if="securitySettings.trusted_ips.length === 0" class="no-ips">暂无信任IP</div>
        </div>

        <div class="add-ip-form">
          <input
            v-model="newIp"
            type="text"
            placeholder="输入IP地址，如: 192.168.1.1"
            @keyup.enter="handleAddTrustedIp"
          >
          <button class="btn-secondary" @click="handleAddTrustedIp">添加</button>
        </div>
      </div>

      <div class="settings-actions">
        <button class="btn-primary" @click="handleSaveSecuritySettings" :disabled="savingSettings">
          <span v-if="savingSettings" class="spinner"></span>
          <RefreshCw v-else :size="16" class="btn-icon" />
          保存设置
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.security-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 页面标题 */





.refresh-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.refresh-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.refresh-btn.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Tabs */
.tabs {
  display: flex;
  gap: 0.5rem;
  padding: 0.5rem;
  background: var(--bg-elevated);
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: linear-gradient(135deg, #673AB7 0%, #7B1FA2 100%);
  color: white;
}

.tab-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 10px;
  font-size: 0.7rem;
}

.tab-btn:not(.active) .tab-badge {
  background: #673AB7;
  color: white;
}

/* 安全概览 */
.overview-content {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.security-score-card {
  display: flex;
  align-items: center;
  gap: 2rem;
  padding: 2rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
}

.score-circle {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: conic-gradient(
    #4CAF50 0deg,
    #4CAF50 calc(var(--score, 80) * 3.6deg),
    var(--border-color) calc(var(--score, 80) * 3.6deg),
    var(--border-color) 360deg
  );
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.score-circle::before {
  content: '';
  position: absolute;
  width: 100px;
  height: 100px;
  background: var(--bg-card);
  border-radius: 50%;
}

.score-value {
  position: relative;
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--text-primary);
}

.score-label {
  position: absolute;
  bottom: 25px;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.score-info h3 {
  font-size: 1.25rem;
  margin: 0 0 0.5rem 0;
  color: var(--text-primary);
}

.score-info p {
  color: var(--text-muted);
  margin: 0;
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.5rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-success .stat-icon { background: rgba(76, 175, 80, 0.15); color: #4CAF50; }
.stat-error .stat-icon { background: rgba(244, 67, 54, 0.15); color: #F44336; }
.stat-info .stat-icon { background: rgba(103, 58, 183, 0.15); color: #673AB7; }

.stat-content {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-label {
  font-size: 0.875rem;
  color: var(--text-muted);
}

/* 安全建议 */
.security-tips {
  padding: 1.5rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.security-tips h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  margin: 0 0 1rem 0;
  color: var(--text-primary);
}

.tips-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.tip-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
}

.tip-warning {
  background: rgba(255, 152, 0, 0.1);
  color: #FF9800;
}

.tip-success {
  background: rgba(76, 175, 80, 0.1);
  color: #4CAF50;
}

/* 会话列表 */
.sessions-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.sessions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sessions-header h3 {
  font-size: 1rem;
  margin: 0;
  color: var(--text-primary);
}

.btn-danger {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-danger:hover {
  background: rgba(244, 67, 54, 0.25);
}

.sessions-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.session-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  transition: all 0.2s ease;
}

.session-card.current-session {
  border-color: #4CAF50;
  background: rgba(76, 175, 80, 0.05);
}

.session-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}

.session-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.session-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.session-device {
  font-weight: 500;
  color: var(--text-primary);
}

.current-badge {
  padding: 0.125rem 0.5rem;
  background: #4CAF50;
  color: white;
  border-radius: 4px;
  font-size: 0.7rem;
}

.session-details {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
  color: var(--text-muted);
}

.session-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.session-last-active {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.btn-icon {
  width: 32px;
  height: 32px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  color: var(--text-muted);
}

.btn-icon:hover {
  background: var(--bg-hover);
}

.btn-icon.btn-danger:hover {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

/* 登录历史 */
.history-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.history-filters {
  display: flex;
  gap: 0.5rem;
}

.filter-btn {
  padding: 0.5rem 1rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 0.875rem;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-btn:hover {
  background: var(--bg-hover);
}

.filter-btn.active {
  background: #673AB7;
  color: white;
  border-color: #673AB7;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.history-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-success { background: rgba(76, 175, 80, 0.15); color: #4CAF50; }
.status-error { background: rgba(244, 67, 54, 0.15); color: #F44336; }
.status-warning { background: rgba(255, 152, 0, 0.15); color: #FF9800; }
.status-info { background: rgba(103, 58, 183, 0.15); color: #673AB7; }

.history-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.history-action {
  font-weight: 500;
  color: var(--text-primary);
}

.history-time {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.history-details {
  display: flex;
  gap: 1rem;
  font-size: 0.875rem;
  color: var(--text-muted);
}

.history-browser {
  padding: 0.125rem 0.5rem;
  background: var(--bg-hover);
  border-radius: 4px;
}

/* 安全设置 */
.settings-content {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.settings-section {
  padding: 1.5rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.settings-section h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  margin: 0 0 1rem 0;
  color: var(--text-primary);
}

.section-desc {
  font-size: 0.875rem;
  color: var(--text-muted);
  margin: -0.5rem 0 1rem 0;
}

.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 0;
}

.setting-info {
  display: flex;
  flex-direction: column;
}

.setting-label {
  font-weight: 500;
  color: var(--text-primary);
}

.setting-desc {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}

/* Toggle Switch */
.toggle-switch {
  position: relative;
  width: 48px;
  height: 26px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--border-color);
  border-radius: 26px;
  transition: 0.3s;
}

.toggle-slider:before {
  position: absolute;
  content: '';
  height: 20px;
  width: 20px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: 0.3s;
}

.toggle-switch input:checked + .toggle-slider {
  background: #673AB7;
}

.toggle-switch input:checked + .toggle-slider:before {
  transform: translateX(22px);
}

.toggle-switch input:disabled + .toggle-slider {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 信任IP */
.trusted-ips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.ip-tag {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-hover);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.ip-tag code {
  font-family: 'Courier New', monospace;
  font-size: 0.875rem;
  color: var(--text-primary);
}

.ip-remove {
  padding: 0;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
}

.ip-remove:hover {
  color: #F44336;
}

.no-ips {
  color: var(--text-muted);
  font-size: 0.875rem;
}

.add-ip-form {
  display: flex;
  gap: 0.5rem;
}

.add-ip-form input {
  flex: 1;
  padding: 0.625rem 1rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 0.875rem;
}

.btn-secondary {
  padding: 0.625rem 1.25rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  background: var(--bg-hover);
}

.settings-actions {
  display: flex;
  justify-content: flex-end;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: linear-gradient(135deg, #673AB7 0%, #7B1FA2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(103, 58, 183, 0.3);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem;
  color: var(--text-muted);
}

.empty-state svg {
  margin-bottom: 1rem;
  opacity: 0.5;
}

/* 响应式 */
@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .security-score-card {
    flex-direction: column;
    text-align: center;
  }

  .history-item {
    flex-wrap: wrap;
  }

  .history-details {
    width: 100%;
    margin-top: 0.5rem;
  }

  .session-card {
    flex-wrap: wrap;
  }

  .session-actions {
    width: 100%;
    justify-content: flex-end;
    margin-top: 0.5rem;
  }
}
</style>
