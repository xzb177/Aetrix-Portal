<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Users, TrendingUp, Gift, RefreshCw, Settings, User, Copy, Check } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import {
  getInvitationConfig,
  updateInvitationConfig,
  getInvitationStats,
  getInvitationCodes,
  getInvitationRecords,
} from '@/api/portal'
import GlassCard from '@/components/glass/GlassCard.vue'
import StatCard from '@/components/glass/StatCard.vue'
import SectionHeader from '@/components/glass/SectionHeader.vue'
import ListRow from '@/components/glass/ListRow.vue'
import LoadingState from '@/components/feedback/LoadingState.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'

// 配置数据
const config = ref({
  invitation_enabled: true,
  invitation_reward_points: 100,
  invitation_invitee_reward_points: 50,
})

const configLoading = ref(false)
const configSaving = ref(false)

// 统计数据
const stats = ref({
  total_codes: 0,
  total_invitations: 0,
  total_rewards: 0,
})

const statsLoading = ref(false)

// 邀请码列表
const codes = ref<any[]>([])
const codesLoading = ref(false)

// 复制状态映射
const copyStates = ref<Record<number, { copying: boolean; copied: boolean }>>({})

// 获取复制状态
function getCopyState(codeId: number) {
  if (!copyStates.value[codeId]) {
    copyStates.value[codeId] = { copying: false, copied: false }
  }
  return copyStates.value[codeId]
}

// 邀请记录列表
const records = ref<any[]>([])
const recordsLoading = ref(false)

// 获取邀请配置
async function fetchConfig() {
  configLoading.value = true
  try {
    const res = await getInvitationConfig()
    config.value = res.data || res || config.value
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '获取配置失败')
  } finally {
    configLoading.value = false
  }
}

// 更新邀请配置
async function saveConfig() {
  configSaving.value = true
  try {
    await updateInvitationConfig({
      invitation_enabled: config.value.invitation_enabled,
      invitation_reward_points: config.value.invitation_reward_points,
      invitation_invitee_reward_points: config.value.invitation_invitee_reward_points,
    })
    ElMessage.success('配置保存成功')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    configSaving.value = false
  }
}

// 获取统计数据
async function fetchStats() {
  statsLoading.value = true
  try {
    const res = await getInvitationStats()
    stats.value = res.data || res || stats.value
  } catch (error) {
    console.error('获取统计数据失败:', error)
  } finally {
    statsLoading.value = false
  }
}

// 获取邀请码列表
async function fetchCodes() {
  codesLoading.value = true
  try {
    const res = await getInvitationCodes({ limit: 20 })
    codes.value = res.data || res || []
  } catch (error) {
    console.error('获取邀请码列表失败:', error)
  } finally {
    codesLoading.value = false
  }
}

// 获取邀请记录列表
async function fetchRecords() {
  recordsLoading.value = true
  try {
    const res = await getInvitationRecords({ limit: 20 })
    records.value = res.data || res || []
  } catch (error) {
    console.error('获取邀请记录失败:', error)
  } finally {
    recordsLoading.value = false
  }
}

// 刷新所有数据
function refreshAll() {
  fetchConfig()
  fetchStats()
  fetchCodes()
  fetchRecords()
}

// 复制邀请码
async function copyCode(code: string, codeId: number) {
  const state = getCopyState(codeId)
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

    // 2秒后重置状态
    setTimeout(() => {
      state.copied = false
    }, 2000)
  } catch (err) {
    // 降级方案：使用 textarea 复制
    try {
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
        throw new Error('复制失败')
      }
    } catch (fallbackErr) {
      console.error('复制失败:', fallbackErr)
      ElMessage.error({
        message: '复制失败，请手动复制',
        duration: 3000
      })
    }
  } finally {
    state.copying = false
  }
}

// 格式化时间
function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000)

  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 604800) return `${Math.floor(diff / 86400)}天前`

  return date.toLocaleDateString('zh-CN')
}

onMounted(() => {
  refreshAll()
})
</script>

<template>
  <PageContainer class="invitations-page">
    <!-- 刷新按钮 -->
    <div class="page-actions">
      <button class="btn-refresh" @click="refreshAll" :class="{ 'btn-refresh-loading': statsLoading }">
        <RefreshCw :size="16" />
        <span>刷新</span>
      </button>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <StatCard
        :value="stats.total_codes"
        label="邀请码总数"
        :icon="Users"
        icon-color="primary"
        :loading="statsLoading"
      />
      <StatCard
        :value="stats.total_invitations"
        label="邀请成功"
        :icon="Check"
        icon-color="success"
        :loading="statsLoading"
      />
      <StatCard
        :value="`¥${stats.total_rewards}`"
        label="累计发放奖励"
        :icon="TrendingUp"
        icon-color="warning"
        :loading="statsLoading"
      />
    </div>

    <!-- 配置管理 -->
    <GlassCard class="config-card">
      <div class="config-header">
        <div class="config-title-wrapper">
          <div class="config-icon">
            <Settings :size="20" />
          </div>
          <div>
            <h3 class="config-title">邀请配置</h3>
            <p class="config-subtitle">管理邀请系统的奖励规则</p>
          </div>
        </div>
      </div>

      <div class="config-list">
        <!-- 邀请系统开关 -->
        <div class="config-item">
          <div class="config-item-left">
            <div class="config-item-icon config-icon-primary">
              <Settings :size="18" />
            </div>
            <div class="config-item-info">
              <span class="config-item-label">邀请系统开关</span>
              <span class="config-item-desc">控制用户是否可以使用邀请功能</span>
            </div>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" v-model="config.invitation_enabled" />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <!-- 邀请者奖励 -->
        <div class="config-item">
          <div class="config-item-left">
            <div class="config-item-icon config-icon-warning">
              <Gift :size="18" />
            </div>
            <div class="config-item-info">
              <span class="config-item-label">邀请者奖励</span>
              <span class="config-item-desc">成功邀请好友后获得的余额</span>
            </div>
          </div>
          <div class="config-item-control">
            <div class="reward-input-group">
              <input
                type="number"
                v-model.number="config.invitation_reward_points"
                min="0"
                max="10000"
                class="reward-input"
              />
              <span class="reward-unit">余额</span>
            </div>
          </div>
        </div>

        <!-- 被邀请者奖励 -->
        <div class="config-item">
          <div class="config-item-left">
            <div class="config-item-icon config-icon-success">
              <User :size="18" />
            </div>
            <div class="config-item-info">
              <span class="config-item-label">被邀请者奖励</span>
              <span class="config-item-desc">新用户注册后获得的余额</span>
            </div>
          </div>
          <div class="config-item-control">
            <div class="reward-input-group">
              <input
                type="number"
                v-model.number="config.invitation_invitee_reward_points"
                min="0"
                max="10000"
                class="reward-input"
              />
              <span class="reward-unit">余额</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 保存按钮 -->
      <div class="config-actions">
        <button
          class="btn-save"
          :class="{ 'btn-save-loading': configSaving }"
          @click="saveConfig"
          :disabled="configSaving"
        >
          <span v-if="!configSaving">保存配置</span>
          <span v-else>保存中...</span>
        </button>
        <button class="btn-reset" @click="fetchConfig" :disabled="configSaving">
          重置
        </button>
      </div>
    </GlassCard>

    <!-- 邀请码列表 -->
    <GlassCard padding="none">
      <SectionHeader
        title="邀请码列表"
        :badge="codes.length"
        badge-type="primary"
      />

      <!-- 加载状态 -->
      <LoadingState v-if="codesLoading" type="skeleton" :rows="3" />

      <!-- 空状态 -->
      <EmptyState
        v-else-if="codes.length === 0"
        :icon="Users"
        title="暂无邀请码"
        description="还没有用户生成邀请码"
      />

      <!-- 列表 -->
      <div v-else class="code-list">
        <ListRow
          v-for="code in codes"
          :key="code.id"
          :title="code.code"
          :subtitle="`所属用户: ${code.username || '-'} · ${code.use_count} 次使用`"
          :show-arrow="false"
        >
          <template #right>
            <button
              class="btn-copy"
              :class="{ 'btn-copy-copied': getCopyState(code.id).copied, 'btn-copying': getCopyState(code.id).copying }"
              @click.stop="copyCode(code.code, code.id)"
            >
              <Check v-if="getCopyState(code.id).copied" :size="14" />
              <Copy v-else :size="14" />
            </button>
          </template>
        </ListRow>
      </div>
    </GlassCard>

    <!-- 邀请记录列表 -->
    <GlassCard padding="none">
      <SectionHeader
        title="邀请记录"
        :badge="records.length"
        badge-type="success"
      />

      <!-- 加载状态 -->
      <LoadingState v-if="recordsLoading" type="skeleton" :rows="3" />

      <!-- 空状态 -->
      <EmptyState
        v-else-if="records.length === 0"
        :icon="TrendingUp"
        title="暂无邀请记录"
        description="还没有用户完成邀请"
      />

      <!-- 列表 -->
      <div v-else class="record-list">
        <ListRow
          v-for="(record, index) in records"
          :key="index"
          :title="`${record.inviter_username} 邀请了 ${record.invitee_username}`"
          :subtitle="`${formatDate(record.created_at)}`"
          :badge="`+¥${record.reward_points}`"
          badge-type="success"
          :show-arrow="false"
        />
      </div>
    </GlassCard>
  </PageContainer>
</template>

<style scoped>
.invitations-page {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* 页面头部 */





.btn-refresh {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: var(--bg-input);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 150ms ease;
}

.btn-refresh:active {
  background: var(--bg-card-hover);
  transform: scale(0.97);
}

.btn-refresh-loading svg {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}

/* 配置卡片 */
.config-card {
  padding: 1.25rem;
}

.config-header {
  margin-bottom: 1rem;
}

.config-title-wrapper {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.config-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.config-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.config-subtitle {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 0.25rem 0 0 0;
}

/* 配置项列表 */
.config-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.config-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  background: var(--bg-input);
  border-radius: 12px;
  border: 1px solid var(--border-base);
}

.config-item-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
}

.config-item-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.config-icon-primary {
  background: var(--primary-bg);
  color: var(--primary);
}

.config-icon-warning {
  background: var(--warning-bg);
  color: var(--warning);
}

.config-icon-success {
  background: var(--success-bg);
  color: var(--success);
}

.config-item-info {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.config-item-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.config-item-desc {
  font-size: 12px;
  color: var(--text-tertiary);
}

.config-item-control {
  flex-shrink: 0;
}

/* 切换开关 */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 28px;
  flex-shrink: 0;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--bg-card-hover);
  border-radius: 28px;
  transition: all 250ms ease;
}

.toggle-slider::before {
  position: absolute;
  content: '';
  height: 22px;
  width: 22px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: all 250ms ease;
}

.toggle-switch input:checked + .toggle-slider {
  background: var(--primary);
}

.toggle-switch input:checked + .toggle-slider::before {
  transform: translateX(20px);
}

/* 奖励输入 */
.reward-input-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.reward-input {
  width: 100px;
  padding: 0.5rem 0.75rem;
  background: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  text-align: center;
}

.reward-input:focus {
  outline: none;
  border-color: var(--primary);
}

.reward-unit {
  padding: 0.375rem 0.625rem;
  background: var(--bg-card-hover);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

/* 配置操作按钮 */
.config-actions {
  display: flex;
  gap: 0.75rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-base);
}

.btn-save,
.btn-reset {
  flex: 1;
  padding: 0.75rem 1rem;
  font-size: 14px;
  font-weight: 500;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  transition: all 150ms ease;
}

.btn-save {
  background: var(--primary);
  color: white;
}

.btn-save:active {
  transform: scale(0.97);
}

.btn-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-reset {
  background: var(--bg-input);
  color: var(--text-secondary);
  border: 1px solid var(--border-base);
}

.btn-reset:active {
  background: var(--bg-card-hover);
}

/* 列表 */
.code-list,
.record-list {
  display: flex;
  flex-direction: column;
}

.btn-copy {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: var(--bg-input);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 150ms ease;
}

.btn-copy:active {
  transform: scale(0.92);
}

.btn-copy:active,
.btn-copy:hover {
  background: var(--bg-card-hover);
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

/* 响应式 */
@media (max-width: 640px) {
  .config-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }

  .config-item-control {
    width: 100%;
    display: flex;
    justify-content: flex-end;
  }

  .config-actions {
    flex-direction: column;
  }
}
</style>
