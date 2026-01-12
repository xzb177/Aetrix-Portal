<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { exchangeCodeApi } from '@/api'
import {
  Gift,
  Calendar,
  CheckCircle,
  XCircle,
  Clock,
  Info,
  Sparkles,
  CalendarPlus,
  Wallet,
  Copy,
  Check
} from 'lucide-vue-next'

const code = ref('')
const loading = ref(false)
const redeeming = ref(false)
const records = ref<any[]>([])
const result = ref<{
  show: boolean
  type: number
  message: string
  details: any
  code?: string
}>({
  show: false,
  type: 0,
  message: '',
  details: null,
  code: ''
})

// 复制状态
const copyState = ref({
  copying: false,
  copied: false,
  showCopy: false
})

// 兑换记录复制状态
const recordCopyStates = ref<Record<number, { copying: boolean; copied: boolean }>>({})

// 兑换码类型说明 - 使用 lucide-vue-next 图标替换 emoji
const codeTypes = [
  { type: 1, name: '激活试用', desc: '激活 Emby 账号并获得试用天数', icon: Sparkles },
  { type: 2, name: '按天续期', desc: '为现有订阅按天续期', icon: CalendarPlus },
  { type: 3, name: '按月续期', desc: '为现有订阅按月续期（30天/月）', icon: Calendar },
  { type: 4, name: '充值余额', desc: '直接充值余额到账户，可用于购买套餐', icon: Wallet }
]

// 兑换兑换码
async function redeemCode() {
  if (!code.value.trim()) {
    result.value = {
      show: true,
      type: 0,
      message: '请输入兑换码',
      details: null
    }
    return
  }

  const codeValue = code.value.trim().toUpperCase()
  redeeming.value = true
  try {
    const res = await exchangeCodeApi.redeem(codeValue)
    const data = res.data || res

    result.value = {
      show: true,
      type: data.type,
      message: data.message,
      details: data.result,
      code: codeValue
    }

    // 如果成功且有需要复制的内容，显示复制按钮
    if (data.type > 0) {
      copyState.value.showCopy = hasCopyableContent(data.type, data.result)
    }

    // 清空输入框并刷新记录
    code.value = ''
    await fetchRecords()
  } catch (error: any) {
    // 错误消息映射（英文 -> 中文）
    const errorMap: Record<string, string> = {
      'Exchange code not found': '兑换码不存在',
      'Exchange code has been disabled': '该兑换码已被禁用',
      'Exchange code already used': '该兑换码已被使用',
      'Invalid exchange code type': '无效的兑换码类型',
      'User not found': '用户不存在',
    }

    let errorMsg = '兑换失败，请稍后重试'
    if (error.response?.data?.detail) {
      const detail = error.response.data.detail
      errorMsg = errorMap[detail] || detail
    } else if (error.message) {
      errorMsg = errorMap[error.message] || error.message
    }

    result.value = {
      show: true,
      type: 0,
      message: errorMsg,
      details: null
    }
    copyState.value.showCopy = false
  } finally {
    redeeming.value = false
  }
}

// 判断是否有可复制的内容
function hasCopyableContent(type: number, details: any): boolean {
  // 激活试用且有 Emby 账号信息
  if (type === 1 && details?.emby_username && details?.emby_password) {
    return true
  }
  return false
}

// 生成复制内容
function getCopyContent(): string {
  if (!result.value.details) return ''

  const d = result.value.details
  let content = ''

  if (result.value.type === 1) {
    // 激活试用
    content = `Emby 账号信息\n`
    content += `服务器: ${d.emby_server || '请联系管理员'}\n`
    content += `用户名: ${d.emby_username}\n`
    content += `密码: ${d.emby_password}\n`
    if (d.expires_at) {
      content += `有效期至: ${formatDate(d.expires_at)}\n`
    }
  } else if (result.value.type === 2 || result.value.type === 3) {
    // 续期
    content = `续期成功\n`
    if (d.new_end_date) {
      content += `有效期至: ${formatDate(d.new_end_date)}\n`
    }
  } else if (result.value.type === 4) {
    // 充值余额
    content = `充值成功\n`
    content += `充值金额: ¥${(d.recharge_amount || 0) / 100} 元\n`
    if (d.new_balance !== undefined) {
      content += `当前余额: ¥${d.new_balance / 100} 元\n`
    }
  }

  return content
}

// 复制内容
async function copyResult() {
  const content = getCopyContent()
  if (!content) return

  copyState.value.copying = true
  try {
    await navigator.clipboard.writeText(content)
    copyState.value.copied = true
    setTimeout(() => {
      copyState.value.copied = false
    }, 2000)
  } catch (err) {
    // 降级方案
    const textarea = document.createElement('textarea')
    textarea.value = content
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      copyState.value.copied = true
      setTimeout(() => {
        copyState.value.copied = false
      }, 2000)
    } catch (e) {
      console.error('复制失败', e)
    }
    document.body.removeChild(textarea)
  } finally {
    copyState.value.copying = false
  }
}

// 获取兑换记录
async function fetchRecords() {
  loading.value = true
  try {
    const res = await exchangeCodeApi.getMyRecords({ limit: 10 })
    records.value = res.data || res || []
  } catch (error) {
    console.error('获取兑换记录失败:', error)
  } finally {
    loading.value = false
  }
}

// 获取兑换记录的复制状态
function getRecordCopyState(recordId: number) {
  if (!recordCopyStates.value[recordId]) {
    recordCopyStates.value[recordId] = { copying: false, copied: false }
  }
  return recordCopyStates.value[recordId]
}

// 复制兑换记录信息
async function copyRecord(record: any) {
  const state = getRecordCopyState(record.id)
  state.copying = true
  state.copied = false

  // 生成复制内容
  let content = `【兑换记录】\n`
  content += `兑换类型: ${record.type_name || getTypeName(record.type)}\n`
  content += `兑换码: ${record.code}\n`
  if (record.description) {
    content += `说明: ${record.description}\n`
  }
  content += `兑换时间: ${formatDate(record.created_at || record.used_at)}\n`

  // 如果有详细信息，也复制
  if (record.effect && typeof record.effect === 'object') {
    content += `\n【兑换详情】\n`
    const effect = record.effect
    if (effect.trial_days) {
      content += `试用天数: ${effect.trial_days} 天\n`
    }
    if (effect.emby_server) {
      content += `服务器: ${effect.emby_server}\n`
    }
    if (effect.emby_username) {
      content += `用户名: ${effect.emby_username}\n`
    }
    if (effect.emby_password) {
      content += `密码: ${effect.emby_password}\n`
    }
    if (effect.extended_days) {
      content += `续期: +${effect.extended_days} 天\n`
    }
    if (effect.extended_months) {
      content += `续期: +${effect.extended_months} 个月\n`
    }
    if (effect.recharge_amount) {
      content += `充值: ¥${effect.recharge_amount / 100} 元\n`
    }
    if (effect.new_end_date) {
      content += `有效期至: ${formatDate(effect.new_end_date)}\n`
    }
  }

  try {
    await navigator.clipboard.writeText(content)
    state.copied = true
    setTimeout(() => {
      state.copied = false
    }, 2000)
  } catch (err) {
    // 降级方案
    const textarea = document.createElement('textarea')
    textarea.value = content
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      state.copied = true
      setTimeout(() => {
        state.copied = false
      }, 2000)
    } catch (e) {
      console.error('复制失败', e)
    }
    document.body.removeChild(textarea)
  } finally {
    state.copying = false
  }
}

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function getTypeName(type: number) {
  const typeInfo = codeTypes.find(t => t.type === type)
  return typeInfo ? typeInfo.name : '未知'
}

function closeResult() {
  result.value.show = false
}

onMounted(() => {
  fetchRecords()
})
</script>

<template>
  <div class="exchange-page">
    <!-- 背景质感层 -->
    <div class="exchange-bg"></div>

    <div class="exchange-container">
      <!-- 兑换码输入区域 - AppCard -->
      <div class="app-card">
        <div class="card-header">
          <div class="app-icon-tile">
            <Gift :size="20" class="text-white/70" />
          </div>
          <div class="header-content">
            <h1 class="card-title">兑换码兑换</h1>
            <p class="card-subtitle">输入兑换码即可激活试用、续期或充值余额</p>
          </div>
        </div>

        <div class="redeem-section">
          <input
            v-model="code"
            type="text"
            class="app-input"
            placeholder="请输入兑换码"
            maxlength="64"
            @keyup.enter="redeemCode"
          />
          <button
            @click="redeemCode"
            :disabled="redeeming || !code.trim()"
            class="app-btn-primary"
          >
            <Clock v-if="redeeming" :size="18" class="spin" />
            <CheckCircle v-else :size="18" class="text-white/70" />
            {{ redeeming ? '兑换中...' : '立即兑换' }}
          </button>
        </div>
      </div>

      <!-- 兑换结果弹窗 -->
      <Transition name="modal">
        <div v-if="result.show" class="result-modal" @click.self="closeResult">
          <div class="result-content app-card">
            <div class="result-icon" :class="result.type > 0 ? 'success' : 'error'">
              <CheckCircle v-if="result.type > 0" :size="28" />
              <XCircle v-else :size="28" />
            </div>
            <h3 class="result-title">{{ result.message }}</h3>

            <!-- 兑换详情 -->
            <div v-if="result.details" class="result-details">
              <div v-if="result.type === 1" class="detail-item">
                <span class="detail-label">试用天数</span>
                <span class="detail-value">{{ result.details.trial_days }} 天</span>
              </div>
              <div v-if="result.type === 1 && result.details.emby_server" class="detail-item">
                <span class="detail-label">服务器</span>
                <span class="detail-value">{{ result.details.emby_server }}</span>
              </div>
              <div v-if="result.type === 1 && result.details.emby_username" class="detail-item">
                <span class="detail-label">Emby 账号</span>
                <span class="detail-value selectable">{{ result.details.emby_username }}</span>
              </div>
              <div v-if="result.type === 1 && result.details.emby_password" class="detail-item">
                <span class="detail-label">密码</span>
                <span class="detail-value selectable">{{ result.details.emby_password }}</span>
              </div>
              <div v-if="result.type === 2" class="detail-item">
                <span class="detail-label">续期天数</span>
                <span class="detail-value">+{{ result.details.extended_days }} 天</span>
              </div>
              <div v-if="result.type === 3" class="detail-item">
                <span class="detail-label">续期月数</span>
                <span class="detail-value">+{{ result.details.extended_months }} 个月 ({{ result.details.extended_days }}天)</span>
              </div>
              <div v-if="result.type === 4" class="detail-item">
                <span class="detail-label">充值余额</span>
                <span class="detail-value">+¥{{ (result.details.recharge_amount || 0) / 100 }} 元</span>
              </div>
              <div v-if="result.type === 4 && result.details.new_balance !== undefined" class="detail-item">
                <span class="detail-label">当前余额</span>
                <span class="detail-value">¥{{ result.details.new_balance / 100 }} 元</span>
              </div>
              <div v-if="result.details.new_end_date" class="detail-item">
                <span class="detail-label">有效期至</span>
                <span class="detail-value">{{ formatDate(result.details.new_end_date) }}</span>
              </div>
            </div>

            <div class="result-actions">
              <button v-if="copyState.showCopy" @click="copyResult" class="app-btn-copy">
                <component :is="copyState.copied ? Check : Copy" :size="16" />
                {{ copyState.copied ? '已复制' : '复制信息' }}
              </button>
              <button @click="closeResult" class="app-btn-secondary">
                确定
              </button>
            </div>
          </div>
        </div>
      </Transition>

      <!-- 兑换码类型说明 - ListItem 单选列表样式 -->
      <div class="app-card">
        <h2 class="section-title">
          <Info :size="17" class="text-white/50" />
          兑换码类型
        </h2>
        <div class="type-list">
          <div
            v-for="type in codeTypes"
            :key="type.type"
            class="type-list-item"
          >
            <div class="app-icon-tile">
              <component :is="type.icon" :size="18" class="text-white/60" />
            </div>
            <div class="type-item-content">
              <span class="type-item-name">{{ type.name }}</span>
              <span class="type-item-desc">{{ type.desc }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 兑换记录 -->
      <div class="app-card">
        <h2 class="section-title">
          <Calendar :size="17" class="text-white/50" />
          兑换记录
        </h2>

        <div v-if="loading" class="loading-state">
          <div class="spinner"></div>
          <p class="text-white/40">加载中...</p>
        </div>

        <div v-else-if="records.length === 0" class="empty-state">
          <div class="app-icon-tile empty-icon">
            <Clock :size="24" class="text-white/30" />
          </div>
          <p class="empty-title">暂无兑换记录</p>
          <p class="empty-desc">兑换成功后记录将显示在这里</p>
        </div>

        <div v-else class="records-list">
          <div v-for="record in records" :key="record.id" class="record-item">
            <div class="record-type">
              <span class="type-badge">{{ getTypeName(record.type) }}</span>
            </div>
            <div class="record-info">
              <p class="record-code">{{ record.code }}</p>
              <p class="record-note" v-if="record.note || record.description">{{ record.note || record.description }}</p>
              <p class="record-date">
                <Calendar :size="11" class="text-white/30" />
                {{ formatDate(record.created_at || record.used_at) }}
              </p>
            </div>
            <button
              class="record-copy-btn"
              :class="{ 'record-copy-copied': getRecordCopyState(record.id).copied }"
              @click.stop="copyRecord(record)"
            >
              <Check v-if="getRecordCopyState(record.id).copied" :size="14" />
              <Copy v-else :size="14" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 容器与背景 ==================== */
.exchange-page {
  min-height: 100vh;
  min-height: 100svh;
  position: relative;
  padding: 1.5rem 1rem;
  padding-top: max(1.5rem, env(safe-area-inset-top, 0));
  padding-bottom: max(1.5rem, env(safe-area-inset-bottom, 0));
}

/* 背景层：深色渐变 + 噪点 + 微光晕 */
.exchange-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(ellipse at 20% 0%, rgba(60, 60, 60, 0.15) 0%, transparent 60%),
    radial-gradient(ellipse at 80% 100%, rgba(50, 50, 50, 0.1) 0%, transparent 50%),
    linear-gradient(180deg, #1a1a1a 0%, #0a0a0a 100%);
}

.exchange-bg::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-repeat: repeat;
  opacity: 0.03;
  pointer-events: none;
}

.exchange-container {
  max-width: 480px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* ==================== AppCard 统一样式 ==================== */
.app-card {
  border-radius: 1.5rem;
  padding: 1.25rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.55);
}

/* ==================== AppIconTile 统一样式 ==================== */
.app-icon-tile {
  height: 40px;
  width: 40px;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: grid;
  place-items: center;
  ring: 1px solid rgba(52, 211, 153, 0.2);
  box-shadow: 0 0 0 1px rgba(52, 211, 153, 0.1);
}

/* ==================== AppButton Primary ==================== */
.app-btn-primary {
  height: 56px;
  width: 100%;
  border-radius: 1rem;
  background: rgba(16, 185, 129, 0.16);
  border: 1px solid rgba(52, 211, 153, 0.2);
  color: rgba(255, 255, 255, 0.92);
  font-size: 1rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.app-btn-primary:active:not(:disabled) {
  transform: scale(0.98);
  background: rgba(16, 185, 129, 0.22);
}

.app-btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ==================== AppButton Secondary ==================== */
.app-btn-secondary {
  height: 48px;
  width: 100%;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.938rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.app-btn-secondary:active {
  transform: scale(0.98);
  background: rgba(255, 255, 255, 0.12);
}

/* ==================== Input ==================== */
.app-input {
  height: 48px;
  width: 100%;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.88);
  font-size: 1rem;
  font-family: ui-monospace, monospace;
  letter-spacing: 0.05em;
  padding: 0 1rem;
  transition: all 0.15s ease;
  margin-bottom: 0.75rem;
}

.app-input::placeholder {
  color: rgba(255, 255, 255, 0.35);
  letter-spacing: normal;
  font-family: system-ui, -apple-system, sans-serif;
}

.app-input:focus {
  outline: none;
  border-color: rgba(52, 211, 153, 0.3);
  box-shadow: 0 0 0 2px rgba(52, 211, 153, 0.15);
}

/* ==================== 卡片头部 ==================== */
.card-header {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding-bottom: 1rem;
  margin-bottom: 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.header-content {
  flex: 1;
}

.card-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin: 0 0 0.25rem 0;
  letter-spacing: -0.01em;
}

.card-subtitle {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
  line-height: 1.4;
}

/* ==================== 兑换区域 ==================== */
.redeem-section {
  padding: 0.5rem 0 0;
}

/* ==================== 结果弹窗 ==================== */
.result-modal {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.result-content {
  max-width: 360px;
  width: 100%;
  padding: 1.75rem;
  text-align: center;
}

.result-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1rem;
}

.result-icon.success {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  box-shadow: 0 0 0 1px rgba(52, 211, 153, 0.2);
}

.result-icon.error {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  box-shadow: 0 0 0 1px rgba(248, 113, 113, 0.2);
}

.result-title {
  font-size: 1rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
  margin: 0 0 1.25rem 0;
}

.result-details {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  margin-bottom: 1.5rem;
  text-align: left;
}

.detail-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 0.75rem;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.detail-label {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.5);
}

.detail-value {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.9);
  font-weight: 500;
}

.detail-value.selectable {
  user-select: text;
  -webkit-user-select: text;
  font-family: ui-monospace, monospace;
  letter-spacing: 0.05em;
}

/* 结果弹窗操作按钮 */
.result-actions {
  display: flex;
  gap: 0.625rem;
}

.app-btn-copy {
  flex: 1;
  height: 48px;
  border-radius: 1rem;
  background: rgba(52, 211, 153, 0.16);
  border: 1px solid rgba(52, 211, 153, 0.3);
  color: rgba(52, 211, 153, 0.9);
  font-size: 0.938rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.app-btn-copy:active {
  transform: scale(0.98);
  background: rgba(52, 211, 153, 0.25);
}

/* 弹窗动画 */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .result-content,
.modal-leave-to .result-content {
  transform: scale(0.95);
}

/* ==================== 模块标题 ==================== */
.section-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.938rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.7);
  margin: 0 0 1rem 0;
  letter-spacing: -0.01em;
}

/* ==================== 兑换码类型列表（Apple TV 设置页风格）==================== */
.type-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.type-list-item {
  display: flex;
  align-items: center;
  gap: 0.875rem;
  padding: 0.875rem 0.5rem;
  border-radius: 0.875rem;
  transition: all 0.15s ease;
  cursor: default;
}

.type-list-item:active {
  background: rgba(255, 255, 255, 0.06);
  transform: scale(0.99);
}

.type-item-content {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  flex: 1;
}

.type-item-name {
  font-size: 0.938rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
}

.type-item-desc {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
  line-height: 1.3;
}

/* ==================== 加载状态 ==================== */
.loading-state {
  text-align: center;
  padding: 2.5rem 1rem;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 2px solid rgba(255, 255, 255, 0.08);
  border-top-color: rgba(52, 211, 153, 0.6);
  border-radius: 50%;
  margin: 0 auto 0.875rem;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.spin {
  animation: spin 1s linear infinite;
}

/* ==================== 空状态 ==================== */
.empty-state {
  text-align: center;
  padding: 2.5rem 1rem;
}

.empty-state .empty-icon {
  margin: 0 auto 1rem;
  background: rgba(255, 255, 255, 0.03);
  box-shadow: none;
}

.empty-title {
  font-size: 0.938rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 0.375rem 0;
}

.empty-desc {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.35);
  margin: 0;
}

/* ==================== 兑换记录列表 ==================== */
.records-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.record-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 1rem;
  transition: all 0.15s ease;
}

.record-item:active {
  background: rgba(255, 255, 255, 0.05);
}

.type-badge {
  padding: 0.25rem 0.625rem;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.7);
  border-radius: 0.5rem;
  font-size: 0.688rem;
  font-weight: 500;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.record-info {
  flex: 1;
  min-width: 0;
}

.record-code {
  font-family: ui-monospace, monospace;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  margin: 0 0 0.25rem 0;
  font-size: 0.875rem;
  overflow: hidden;
  text-overflow: ellipsis;
}

.record-note {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.45);
  margin: 0 0 0.25rem 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.record-date {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.688rem;
  color: rgba(255, 255, 255, 0.35);
  margin: 0;
}

.record-count {
  padding: 0.25rem 0.5rem;
  background: rgba(52, 211, 153, 0.12);
  color: rgba(52, 211, 153, 0.8);
  border-radius: 0.5rem;
  font-size: 0.688rem;
  font-weight: 600;
  border: 1px solid rgba(52, 211, 153, 0.15);
  flex-shrink: 0;
}

/* 兑换记录复制按钮 */
.record-copy-btn {
  width: 32px;
  height: 32px;
  border-radius: 0.5rem;
  border: none;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.record-copy-btn:active {
  transform: scale(0.92);
}

.record-copy-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
}

.record-copy-btn.record-copy-copied {
  background: rgba(16, 185, 129, 0.2);
  color: rgba(52, 211, 153, 0.9);
  border: 1px solid rgba(52, 211, 153, 0.3);
}
</style>
