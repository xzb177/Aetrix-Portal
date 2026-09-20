<script setup lang="ts">
/**
 * 个人中心 — 简化版
 *
 * 功能：账号信息、修改密码、Emby 播放密码、退出登录。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { authApi, embyApi, subscriptionApi, type AuthUser, type AccountCard, type MySubscription, type WatchStats } from '@/api'
import { useToast } from '@/composables/useToast'
import {
  User, Lock, KeyRound, LogOut, ShieldCheck, RefreshCw, Eye, EyeOff, Copy, Check, Film,
  Play, History, Crown,
} from 'lucide-vue-next'

const router = useRouter()
const userStore = useUserStore()
const toast = useToast()

const user = computed(() => userStore.user as AuthUser | null)

// ===== 数据 =====
const loading = ref(true)
const account = ref<AccountCard | null>(null)
const stats = ref<WatchStats | null>(null)
const subscriptions = ref<MySubscription[]>([])

const activeSub = computed(() => subscriptions.value.find(s => s.status === 'active' && s.days_left > 0) || null)
const watchHours = computed(() => {
  if (!stats.value) return '0'
  const h = Math.floor(stats.value.total_seconds / 3600)
  return h >= 1 ? `${h} 小时` : `${Math.floor(stats.value.total_seconds / 60)} 分钟`
})

function fmtWatchTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}

const copiedField = ref('')
const showPlayPassword = ref(false)

const embyUsername = computed(() => account.value?.emby_username || user.value?.emby_username || user.value?.username || '—')
const serverUrl = computed(() => account.value?.base_url || window.location.origin)
const hasPlayPassword = computed(() => !!account.value?.has_password)

const copyText = async (text: string, field: string) => {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = field
    toast.success('已复制')
    setTimeout(() => { if (copiedField.value === field) copiedField.value = '' }, 1600)
  } catch {
    toast.error('复制失败')
  }
}

// ===== 修改门户密码 =====
const showChangePwd = ref(false)
const pwdForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const pwdLoading = ref(false)
const pwdError = ref('')

async function handleChangePassword() {
  const { oldPassword, newPassword, confirmPassword } = pwdForm.value
  if (!oldPassword || !newPassword || !confirmPassword) {
    pwdError.value = '请填写完整'
    return
  }
  if (newPassword.length < 6) {
    pwdError.value = '新密码至少 6 位'
    return
  }
  if (newPassword !== confirmPassword) {
    pwdError.value = '两次输入的新密码不一致'
    return
  }
  pwdError.value = ''
  pwdLoading.value = true
  try {
    await authApi.changePassword({ old_password: oldPassword, new_password: newPassword })
    toast.success('密码修改成功，播放密码已同步')
    showChangePwd.value = false
    pwdForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    pwdError.value = typeof detail === 'string' ? detail : '修改失败，请稍后重试'
  } finally {
    pwdLoading.value = false
  }
}

// ===== 设置播放密码 =====
const showSetPlayPwd = ref(false)
const playPwd = ref('')
const playPwdLoading = ref(false)

async function handleSetPlayPassword() {
  if (playPwd.value.length < 6) {
    toast.error('播放密码至少 6 位')
    return
  }
  playPwdLoading.value = true
  try {
    await embyApi.setPassword(playPwd.value)
    toast.success('播放密码已设置')
    showSetPlayPwd.value = false
    playPwd.value = ''
    account.value = await embyApi.getAccountCard()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '设置失败')
  } finally {
    playPwdLoading.value = false
  }
}

// ===== 退出登录 =====
async function handleLogout() {
  await userStore.logout()
  router.push('/login')
}

// ===== 初始化 =====
onMounted(async () => {
  try {
    // 观看统计与订阅加载失败不阻塞页面（新用户可能无数据）
    const [accountCard, watchStats, subs] = await Promise.all([
      embyApi.getAccountCard(),
      embyApi.getStats().catch((): WatchStats | null => null),
      subscriptionApi.getMine().catch((): MySubscription[] => []),
    ])
    account.value = accountCard
    stats.value = watchStats
    subscriptions.value = subs
  } catch {
    // 401 已由拦截器处理
  } finally {
    loading.value = false
  }
})

function formatDate(iso?: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="profile-view">
    <div class="container">
      <!-- 头部 -->
      <section class="head">
        <div class="avatar">
          <User :size="26" />
        </div>
        <div class="head-info">
          <h1 class="head-name">{{ user?.username || '用户' }}</h1>
          <p class="head-meta">
            <span v-if="user?.email">{{ user.email }}</span>
            <span v-else>未绑定邮箱</span>
            <span class="dot">·</span>
            <span>注册于 {{ formatDate(user?.created_at) }}</span>
          </p>
        </div>
        <div v-if="user?.is_vip" class="vip-badge">
          <ShieldCheck :size="14" />
          VIP
        </div>
      </section>

      <!-- Emby 账号卡 -->
      <section class="card">
        <header class="card-head">
          <h2 class="card-title">
            <KeyRound :size="17" />
            Emby 账号
          </h2>
          <button class="icon-btn" title="刷新" @click="loading = true; embyApi.getAccountCard().then(a => account = a).finally(() => loading = false)">
            <RefreshCw :size="15" :class="{ spinning: loading }" />
          </button>
        </header>

        <div class="rows" :class="{ loading }">
          <div class="row">
            <span class="row-label">服务器</span>
            <span class="row-value mono">{{ serverUrl }}</span>
            <button class="copy-btn" @click="copyText(serverUrl, 'server')">
              <Check v-if="copiedField === 'server'" :size="14" class="ok" />
              <Copy v-else :size="14" />
            </button>
          </div>
          <div class="row">
            <span class="row-label">用户名</span>
            <span class="row-value mono">{{ embyUsername }}</span>
            <button class="copy-btn" @click="copyText(embyUsername, 'user')">
              <Check v-if="copiedField === 'user'" :size="14" class="ok" />
              <Copy v-else :size="14" />
            </button>
          </div>
          <div class="row">
            <span class="row-label">播放密码</span>
            <span class="row-value mono">
              <template v-if="hasPlayPassword">{{ showPlayPassword ? '已设置' : '••••••••' }}</template>
              <template v-else>未设置</template>
            </span>
            <button v-if="hasPlayPassword" class="copy-btn" @click="showPlayPassword = !showPlayPassword">
              <Eye v-if="showPlayPassword" :size="14" />
              <EyeOff v-else :size="14" />
            </button>
            <button class="text-btn" @click="showSetPlayPwd = true">
              {{ hasPlayPassword ? '修改' : '设置' }}
            </button>
          </div>
        </div>

        <p class="card-tip">
          播放密码用于 Emby 客户端登录，与门户密码相互独立。
        </p>
      </section>

      <!-- 观看统计 -->
      <section v-if="stats" class="card">
        <header class="card-head">
          <h2 class="card-title">
            <History :size="17" />
            观看统计
          </h2>
        </header>

        <div class="stats-grid">
          <div class="stat-box">
            <div class="stat-num accent">{{ watchHours }}</div>
            <div class="stat-cap">累计观看</div>
          </div>
          <div class="stat-box">
            <div class="stat-num">{{ stats.total_plays }}</div>
            <div class="stat-cap">播放次数</div>
          </div>
          <div class="stat-box">
            <div class="stat-num">{{ stats.watched_items }}</div>
            <div class="stat-cap">看过影片</div>
          </div>
        </div>

        <template v-if="stats.recent.length > 0">
          <div class="recent-head">最近观看</div>
          <div v-for="r in stats.recent.slice(0, 5)" :key="r.item + (r.at || '')" class="recent-row">
            <Play :size="13" class="recent-icon" />
            <span class="recent-name">{{ r.item }}</span>
            <span class="recent-time">{{ fmtWatchTime(r.at) }}</span>
          </div>
        </template>
      </section>

      <!-- 我的订阅 -->
      <section class="card">
        <header class="card-head">
          <h2 class="card-title">
            <Crown :size="17" />
            我的订阅
          </h2>
        </header>

        <div v-if="activeSub" class="sub-active">
          <div class="sub-info">
            <div class="sub-plan">{{ activeSub.plan_name }}</div>
            <div class="sub-end">{{ activeSub.end_date.slice(0, 10) }} 到期 · 剩余 {{ activeSub.days_left }} 天</div>
          </div>
          <span class="sub-badge">生效中</span>
        </div>
        <p v-else class="sub-empty">
          暂无生效中的订阅。如需开通，请联系管理员。
        </p>

        <ul v-if="subscriptions.length > 1" class="sub-history">
          <li v-for="s in subscriptions.slice(0, 4)" :key="s.id" class="sub-history-item">
            <span>{{ s.plan_name }}</span>
            <span class="sub-history-date">{{ s.start_date.slice(0, 10) }} ~ {{ s.end_date.slice(0, 10) }}</span>
            <span class="sub-status" :class="s.status === 'active' ? 'ok' : 'off'">
              {{ s.status === 'active' ? '生效中' : '已结束' }}
            </span>
          </li>
        </ul>
      </section>

      <!-- 安全设置 -->
      <section class="card">
        <header class="card-head">
          <h2 class="card-title">
            <Lock :size="17" />
            安全设置
          </h2>
        </header>

        <div class="list">
          <button class="list-item" @click="showChangePwd = true">
            <Lock :size="16" class="list-icon" />
            <span class="list-text">修改登录密码</span>
            <span class="list-arrow">›</span>
          </button>
          <button class="list-item danger" @click="handleLogout">
            <LogOut :size="16" class="list-icon" />
            <span class="list-text">退出登录</span>
            <span class="list-arrow">›</span>
          </button>
        </div>
      </section>

      <!-- 关联入口 -->
      <section class="links-row">
        <RouterLink to="/requests" class="link-card">
          <Film :size="16" />
          我的求片
        </RouterLink>
        <RouterLink to="/tickets" class="link-card">
          <User :size="16" />
          我的工单
        </RouterLink>
      </section>
    </div>

    <!-- 修改密码弹窗 -->
    <div v-if="showChangePwd" class="modal-mask" @click.self="showChangePwd = false">
      <div class="modal">
        <h3 class="modal-title">修改登录密码</h3>
        <div class="field">
          <label class="field-label">当前密码</label>
          <input v-model="pwdForm.oldPassword" type="password" autocomplete="current-password" />
        </div>
        <div class="field">
          <label class="field-label">新密码</label>
          <input v-model="pwdForm.newPassword" type="password" autocomplete="new-password" />
        </div>
        <div class="field">
          <label class="field-label">确认新密码</label>
          <input v-model="pwdForm.confirmPassword" type="password" autocomplete="new-password" />
        </div>
        <p v-if="pwdError" class="form-error">{{ pwdError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showChangePwd = false">取消</button>
          <button class="btn primary" :disabled="pwdLoading" @click="handleChangePassword">
            {{ pwdLoading ? '提交中…' : '确认修改' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 设置播放密码弹窗 -->
    <div v-if="showSetPlayPwd" class="modal-mask" @click.self="showSetPlayPwd = false">
      <div class="modal">
        <h3 class="modal-title">设置 Emby 播放密码</h3>
        <p class="modal-desc">此密码用于在 Emby 客户端（Infuse、Forward 等）中登录</p>
        <div class="field">
          <label class="field-label">播放密码</label>
          <input v-model="playPwd" type="password" autocomplete="new-password" placeholder="至少 6 位" />
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showSetPlayPwd = false">取消</button>
          <button class="btn primary" :disabled="playPwdLoading || !playPwd" @click="handleSetPlayPassword">
            {{ playPwdLoading ? '提交中…' : '确认设置' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-view {
  min-height: 100vh;
  background: #05070a;
  color: #e5e7eb;
  padding-bottom: 3rem;
}

.container {
  max-width: 680px;
  margin: 0 auto;
  padding: 0 1.25rem;
}

/* 头部 */
.head {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 2.5rem 0 1.75rem;
}

.avatar {
  width: 60px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #10b981;
}

.head-info {
  flex: 1;
  min-width: 0;
}

.head-name {
  font-size: 1.25rem;
  font-weight: 700;
  color: #fafafa;
  margin: 0 0 0.25rem;
}

.head-meta {
  margin: 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.4);
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  flex-wrap: wrap;
}

.dot {
  color: rgba(255, 255, 255, 0.2);
}

.vip-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  padding: 0.3125rem 0.625rem;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 8px;
  color: #f59e0b;
  font-size: 0.75rem;
  font-weight: 600;
}

/* 卡片 */
.card {
  background: rgba(13, 18, 24, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 16px;
  padding: 1.375rem;
  margin-bottom: 1.25rem;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.125rem;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9375rem;
  font-weight: 600;
  color: #fafafa;
  margin: 0;
}

.card-title svg {
  color: #10b981;
}

.card-tip {
  margin: 0.875rem 0 0;
  padding-top: 0.875rem;
  border-top: 1px dashed rgba(255, 255, 255, 0.08);
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.35);
  line-height: 1.5;
}

.icon-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 9px;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.2s ease;
}

.icon-btn:hover {
  color: #fff;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 行 */
.rows {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  transition: opacity 0.2s ease;
}

.rows.loading {
  opacity: 0.45;
  pointer-events: none;
}

.row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6875rem 0.875rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 11px;
}

.row-label {
  flex-shrink: 0;
  width: 64px;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.45);
}

.row-value {
  flex: 1;
  min-width: 0;
  font-size: 0.8125rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
}

.copy-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: 7px;
  color: rgba(255, 255, 255, 0.35);
  cursor: pointer;
}

.copy-btn:hover {
  background: rgba(255, 255, 255, 0.07);
  color: #fff;
}

.copy-btn .ok {
  color: #10b981;
}

.text-btn {
  flex-shrink: 0;
  background: transparent;
  border: none;
  color: #10b981;
  font-size: 0.8125rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
}

.text-btn:hover {
  text-decoration: underline;
}

/* 列表 */
.list {
  display: flex;
  flex-direction: column;
}

.list-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 0.25rem;
  background: transparent;
  border: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.85);
  font-size: 0.875rem;
  cursor: pointer;
  text-align: left;
}

.list-item:last-child {
  border-bottom: none;
}

.list-item:hover {
  color: #fff;
}

.list-item.danger {
  color: #f87171;
}

.list-icon {
  color: rgba(255, 255, 255, 0.35);
}

.list-item.danger .list-icon {
  color: rgba(239, 68, 68, 0.6);
}

.list-text {
  flex: 1;
}

.list-arrow {
  color: rgba(255, 255, 255, 0.2);
  font-size: 1.125rem;
}

/* 观看统计 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.625rem;
}

.stat-box {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 0.75rem 0.5rem;
  text-align: center;
}

.stat-num {
  font-size: 1.25rem;
  font-weight: 700;
  color: #fafafa;
}

.stat-num.accent {
  color: #10b981;
}

.stat-cap {
  margin-top: 0.25rem;
  font-size: 0.6875rem;
  color: rgba(255, 255, 255, 0.4);
}

.recent-head {
  margin: 1rem 0 0.5rem;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
}

.recent-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0;
  font-size: 0.8125rem;
}

.recent-icon {
  color: rgba(16, 185, 129, 0.6);
  flex-shrink: 0;
}

.recent-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(255, 255, 255, 0.85);
}

.recent-time {
  font-size: 0.6875rem;
  color: rgba(255, 255, 255, 0.35);
  flex-shrink: 0;
}

/* 我的订阅 */
.sub-active {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 12px;
  padding: 0.875rem 1rem;
}

.sub-plan {
  font-weight: 600;
  color: #fafafa;
}

.sub-end {
  margin-top: 0.125rem;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.45);
}

.sub-badge {
  font-size: 0.6875rem;
  font-weight: 600;
  color: #10b981;
  background: rgba(16, 185, 129, 0.15);
  border-radius: 999px;
  padding: 0.1875rem 0.625rem;
  flex-shrink: 0;
}

.sub-empty {
  margin: 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.6;
}

.sub-history {
  list-style: none;
  margin: 0.75rem 0 0;
  padding: 0;
}

.sub-history-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.6);
}

.sub-history-date {
  flex: 1;
  color: rgba(255, 255, 255, 0.35);
}

.sub-status {
  font-size: 0.625rem;
  border-radius: 999px;
  padding: 0.0625rem 0.5rem;
}

.sub-status.ok {
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
}

.sub-status.off {
  color: rgba(255, 255, 255, 0.35);
  background: rgba(255, 255, 255, 0.06);
}

/* 链接卡 */
.links-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.link-card {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  height: 52px;
  background: rgba(13, 18, 24, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 14px;
  color: rgba(255, 255, 255, 0.75);
  font-size: 0.875rem;
  text-decoration: none;
  transition: all 0.2s ease;
}

.link-card:hover {
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
}

/* 弹窗 */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  z-index: 100;
}

.modal {
  width: 100%;
  max-width: 360px;
  background: #10161d;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 18px;
  padding: 1.5rem;
  animation: modalIn 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes modalIn {
  from { opacity: 0; transform: scale(0.96) translateY(8px); }
  to { opacity: 1; transform: none; }
}

.modal-title {
  margin: 0 0 0.375rem;
  font-size: 1.0625rem;
  font-weight: 600;
  color: #fafafa;
}

.modal-desc {
  margin: 0 0 1rem;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.5;
}

.field {
  margin-bottom: 0.875rem;
}

.field-label {
  display: block;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  margin-bottom: 0.375rem;
}

.field input {
  width: 100%;
  height: 42px;
  padding: 0 0.75rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: #fafafa;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.2s ease;
  box-sizing: border-box;
}

.field input:focus {
  border-color: rgba(16, 185, 129, 0.6);
}

.form-error {
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 9px;
  color: #f87171;
  font-size: 0.8125rem;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.625rem;
  margin-top: 1.125rem;
}

.btn {
  height: 38px;
  padding: 0 1rem;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}

.btn.ghost {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.75);
}

.btn.ghost:hover {
  background: rgba(255, 255, 255, 0.1);
}

.btn.primary {
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .head {
    padding: 2rem 0 1.5rem;
  }
}
</style>
