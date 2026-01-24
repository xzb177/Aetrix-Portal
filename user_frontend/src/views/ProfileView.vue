<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { userApi, subscriptionApi, authApi } from '@/api'
// 原有组件
import ProfileHeader from '@/components/profile/ProfileHeader.vue'
import EmbyCard from '@/components/profile/EmbyCard.vue'
import QuickGrid from '@/components/profile/QuickGrid.vue'
import SettingsList from '@/components/profile/SettingsList.vue'
import RequestLimitCard from '@/components/profile/RequestLimitCard.vue'
import BridgeDebugSheet from '@/components/profile/BridgeDebugSheet.vue'
import BottomSheet from '@/components/ui/BottomSheet.vue'
// Bridge 组件
import HoloIdCard from '@/components/profile/HoloIdCard.vue'
import TripleDashboard from '@/components/profile/TripleDashboard.vue'
import AccountVault from '@/components/profile/AccountVault.vue'
import AdaptiveDock from '@/components/profile/AdaptiveDock.vue'
import ActivityTimeline, { type TimelineEvent } from '@/components/profile/ActivityTimeline.vue'
import ProfileSettingsSheet from '@/components/profile/ProfileSettingsSheet.vue'
// 线路信息组件
import { RouteInfoCard } from '@/components/ui'
// Composables
import { useToast } from '@/composables/useToast'
import { useAuthSheet } from '@/composables/useAuthSheet'
import { useFeatureFlags } from '@/composables/useFeatureFlags'

const router = useRouter()
const userStore = useUserStore()
const toast = useToast()
const { openAuthSheet } = useAuthSheet()
const { PROFILE_EASTER_EGG, PROFILE_BRIDGE, flags } = useFeatureFlags()

// 调试面板状态
const showDebugSheet = ref(false)

// 设置面板状态
const showSettingsSheet = ref(false)
const settingsSheetRef = ref<InstanceType<typeof ProfileSettingsSheet> | null>(null)

// 模块可见性状态
const moduleVisibility = ref<Record<string, boolean>>({
  holoId: true,
  dashboard: true,
  accountVault: true,
  timeline: true,
})

// 页面加载时间（用于性能监控）
const pageLoadTime = ref(0)
const pageLoadStart = performance.now()

const profile = ref<any>(null)
const loading = ref(true)
const embyAccounts = ref<any[]>([])
const claimingAccount = ref(false)
const vipExpiry = ref<string | undefined>(undefined)

// Activity Timeline 数据
const timelineEvents = ref<TimelineEvent[]>([])
const timelineLoading = ref(false)

// 修改密码弹窗状态
const showChangePasswordSheet = ref(false)
const changePasswordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})
const changePasswordLoading = ref(false)
const changePasswordError = ref('')

const isLoggedIn = computed(() => userStore.isLoggedIn)

// 本地计算 VIP 状态：优先使用 vipExpiry（订阅 API），其次使用 store
const isVIP = computed(() => {
  if (vipExpiry.value) {
    // 有订阅到期时间，检查是否过期
    const expiryDate = new Date(vipExpiry.value)
    const now = new Date()
    return expiryDate > now
  }
  // 回退到 store 中的值
  return userStore.isVIP
})

onMounted(async () => {
  if (!isLoggedIn.value) {
    openAuthSheet()
    return
  }

  // 加载模块可见性设置
  loadModuleVisibility()

  await Promise.all([
    fetchProfile(),
    fetchEmbyAccounts(),
    fetchSubscription(),
    fetchTimelineEvents()
  ])

  // 记录页面加载完成时间
  pageLoadTime.value = performance.now() - pageLoadStart
})

// 长按 Holo-ID 卡片触发调试模式
const handleLongPress = () => {
  if (!PROFILE_EASTER_EGG.value) return

  showDebugSheet.value = true
  toast.success('已进入舰桥调试模式')
}

// 打开设置面板
const handleSettings = () => {
  showSettingsSheet.value = true
}

// 从 localStorage 加载模块可见性设置
const loadModuleVisibility = () => {
  try {
    const stored = localStorage.getItem('profile_visibility')
    if (stored) {
      moduleVisibility.value = JSON.parse(stored)
    }
  } catch {
    // 使用默认值
  }
}

async function fetchProfile() {
  try {
    const res = await userApi.getProfile()
    profile.value = res.data || res
  } catch (error) {
    console.error('Failed to fetch profile:', error)
    // 如果 API 失败，尝试从 store 获取用户信息
    if (userStore.user) {
      profile.value = userStore.user
    }
  }
}

async function fetchEmbyAccounts() {
  try {
    const res = await fetch('/api/user/emby/servers', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`
      }
    })
    if (res.ok) {
      const data = await res.json()
      // 后端返回格式: { code: 200, message: "获取成功", data: [...] }
      embyAccounts.value = data.data || []
    } else {
      embyAccounts.value = []
    }
  } catch (error) {
    console.error('Failed to fetch Emby accounts:', error)
    embyAccounts.value = []
  } finally {
    loading.value = false
  }
}

async function fetchSubscription() {
  try {
    const res = await subscriptionApi.getMySubscription()
    // 后端返回的字段是 end_date，不是 expires_at
    if (res.data && res.data.end_date) {
      const expiryDate = new Date(res.data.end_date)
      const now = new Date()
      // 检查订阅是否已过期
      if (expiryDate > now) {
        vipExpiry.value = res.data.end_date
        // 订阅有效，更新 store 中的 VIP 状态
        userStore.updateUser({ is_vip: true })
      } else {
        // 订阅已过期
        vipExpiry.value = undefined
        userStore.updateUser({ is_vip: false })
      }
    } else {
      // 没有订阅数据
      vipExpiry.value = undefined
      userStore.updateUser({ is_vip: false })
    }
  } catch (error) {
    // 没有订阅或订阅已过期是正常情况
    vipExpiry.value = undefined
    userStore.updateUser({ is_vip: false })
  }
}

async function fetchTimelineEvents() {
  timelineLoading.value = true
  try {
    // 从后端获取活动时间线
    const res = await fetch('/api/user/timeline', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`
      }
    })

    if (res.ok) {
      const data = await res.json()
      timelineEvents.value = data || []
    } else {
      // 如果 API 不存在或出错，返回空数组
      timelineEvents.value = []
    }
  } catch (error) {
    console.error('Failed to fetch timeline:', error)
    // API 不可用时返回空数组，不影响页面显示
    timelineEvents.value = []
  } finally {
    timelineLoading.value = false
  }
}

async function handleClaimAccount() {
  if (claimingAccount.value) return

  claimingAccount.value = true
  try {
    const res = await fetch('/api/user/emby/claim', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        'Content-Type': 'application/json'
      }
    })

    if (res.ok) {
      const data = await res.json()
      toast.success('账号领取成功')
      await fetchEmbyAccounts()
    } else {
      const error = await res.json()
      toast.error(error.detail || '领取失败，请稍后重试')
    }
  } catch (error) {
    console.error('Failed to claim account:', error)
    toast.error('网络异常，请稍后重试')
  } finally {
    claimingAccount.value = false
  }
}

function handleCopy(text: string, type: string) {
  toast.success('已复制到剪贴板')
}

// 打开修改密码弹窗
function handleChangePassword() {
  changePasswordForm.value = {
    oldPassword: '',
    newPassword: '',
    confirmPassword: ''
  }
  changePasswordError.value = ''
  showChangePasswordSheet.value = true
}

// 关闭修改密码弹窗
function closeChangePasswordSheet() {
  showChangePasswordSheet.value = false
}

// 提交修改密码
async function submitChangePassword() {
  changePasswordError.value = ''

  // 验证输入
  if (!changePasswordForm.value.oldPassword) {
    changePasswordError.value = '请输入当前密码'
    return
  }
  if (!changePasswordForm.value.newPassword) {
    changePasswordError.value = '请输入新密码'
    return
  }
  if (changePasswordForm.value.newPassword.length < 6) {
    changePasswordError.value = '新密码至少需要 6 位字符'
    return
  }
  if (changePasswordForm.value.newPassword !== changePasswordForm.value.confirmPassword) {
    changePasswordError.value = '两次输入的新密码不一致'
    return
  }

  changePasswordLoading.value = true
  try {
    await authApi.changePassword({
      old_password: changePasswordForm.value.oldPassword,
      new_password: changePasswordForm.value.newPassword
    })
    toast.success('密码修改成功，请重新登录')
    closeChangePasswordSheet()
    // 登出并返回首页
    setTimeout(() => {
      userStore.logout()
      router.push('/')
    }, 1500)
  } catch (error: any) {
    const errorMsg = error.response?.data?.detail || '修改密码失败，请稍后重试'
    changePasswordError.value = errorMsg
    if (errorMsg.includes('原密码错误')) {
      changePasswordError.value = '当前密码不正确'
    }
  } finally {
    changePasswordLoading.value = false
  }
}

function handleLogout() {
  userStore.logout()
  router.push('/')
}

// 原有设置项（非 Bridge 模式）
const settingsItems = computed(() => {
  if (!profile.value) return []

  return [
    {
      label: '用户 ID',
      value: `#${profile.value.id}`,
      copyable: true,
      copyValue: String(profile.value.id)
    },
    {
      label: '注册时间',
      value: formatDate(profile.value.registered_date),
      copyable: false
    }
  ]
})

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}
</script>

<template>
  <div class="profile-page" :class="{ 'profile-bridge': PROFILE_BRIDGE }">
    <div class="profile-container">
      <!-- Loading Skeleton -->
      <div v-if="loading" class="profile-content">
        <ProfileHeader :profile="null" :loading="true" />
        <EmbyCard :is-VIP="false" :emby-accounts="[]" :loading="true" />
        <QuickGrid />
        <SettingsList :items="[]" />
      </div>

      <!-- ============================================== -->
      <!-- Bridge 模式 (Aetrix Bridge Profile) -->
      <!-- ============================================== -->
      <div v-else-if="PROFILE_BRIDGE" class="profile-content profile-bridge-content">
        <!-- 1. Holo-ID 全息身份卡 -->
        <HoloIdCard
          v-if="moduleVisibility.holoId"
          :profile="profile || userStore.user"
          :is-VIP="isVIP"
          :vip-expiry="vipExpiry"
          :enable-easter-egg="PROFILE_EASTER_EGG"
          @long-press="handleLongPress"
        />

        <!-- 2. 三联仪表盘 -->
        <TripleDashboard
          v-if="moduleVisibility.dashboard"
          :is-VIP="isVIP"
          :vip-expiry="vipExpiry"
          :balance="(profile?.balance || profile?.points || 0)"
          :completed-requests="profile?.completed_requests_count || 0"
        />

        <!-- 3. 账号保险箱 -->
        <AccountVault
          v-if="moduleVisibility.accountVault"
          :is-VIP="isVIP"
          :emby-accounts="embyAccounts"
          :vip-expiry="vipExpiry"
          @claim-account="handleClaimAccount"
          @copy="handleCopy"
        />

        <!-- 4. 活动时间线 -->
        <ActivityTimeline
          v-if="moduleVisibility.timeline"
          :events="timelineEvents"
          :loading="timelineLoading"
          :max-items="3"
        />

        <!-- 5. 线路信息（功能开关控制） -->
        <RouteInfoCard />

        <!-- 6. 自适应 Dock -->
        <AdaptiveDock
          :show-logout="true"
          @logout="handleLogout"
          @settings="handleSettings"
        />
      </div>

      <!-- ============================================== -->
      <!-- 传统模式 (Legacy Profile) -->
      <!-- ============================================== -->
      <div v-else class="profile-content">
        <!-- 顶部概览条 -->
        <ProfileHeader
          :profile="profile || userStore.user"
          :is-VIP="isVIP"
          :vip-expiry="vipExpiry"
          :enable-easter-egg="PROFILE_EASTER_EGG"
          @long-press="handleLongPress"
        />

        <!-- 求片限制卡片 -->
        <RequestLimitCard :is-VIP="isVIP" />

        <!-- Emby 账号主卡（三态） -->
        <EmbyCard
          :is-VIP="isVIP"
          :emby-accounts="embyAccounts"
          :vip-expiry="vipExpiry"
          @claim-account="handleClaimAccount"
          @copy="handleCopy"
        />

        <!-- 快捷入口宫格 -->
        <QuickGrid />

        <!-- 线路信息（功能开关控制） -->
        <RouteInfoCard />

        <!-- 账号信息设置列表 -->
        <SettingsList
          :items="settingsItems"
          @logout="handleLogout"
          @copy="handleCopy"
          @change-password="handleChangePassword"
        />
      </div>
    </div>

    <!-- 舰桥调试模式（彩蛋） -->
    <BridgeDebugSheet
      :show="showDebugSheet"
      @update:show="showDebugSheet = $event"
      :feature-flags="flags"
      :page-load-time="pageLoadTime"
      @refresh="() => {}"
    />

    <!-- 个人中心设置面板 -->
    <ProfileSettingsSheet
      v-if="PROFILE_BRIDGE"
      :show="showSettingsSheet"
      @update:show="showSettingsSheet = $event"
      ref="settingsSheetRef"
    />

    <!-- 修改密码弹窗 -->
    <BottomSheet
      :show="showChangePasswordSheet"
      @update:show="closeChangePasswordSheet"
      max-height="70vh"
    >
      <div class="change-password-sheet">
        <h2 class="sheet-title">修改密码</h2>

        <div class="form-group">
          <label class="form-label">当前密码</label>
          <input
            v-model="changePasswordForm.oldPassword"
            type="password"
            class="form-input"
            placeholder="请输入当前密码"
            :disabled="changePasswordLoading"
          />
        </div>

        <div class="form-group">
          <label class="form-label">新密码</label>
          <input
            v-model="changePasswordForm.newPassword"
            type="password"
            class="form-input"
            placeholder="至少 6 位字符"
            :disabled="changePasswordLoading"
          />
        </div>

        <div class="form-group">
          <label class="form-label">确认新密码</label>
          <input
            v-model="changePasswordForm.confirmPassword"
            type="password"
            class="form-input"
            placeholder="再次输入新密码"
            :disabled="changePasswordLoading"
          />
        </div>

        <div v-if="changePasswordError" class="error-message">
          {{ changePasswordError }}
        </div>

        <div class="form-actions">
          <button
            class="btn-cancel"
            @click="closeChangePasswordSheet"
            :disabled="changePasswordLoading"
          >
            取消
          </button>
          <button
            class="btn-confirm"
            @click="submitChangePassword"
            :disabled="changePasswordLoading"
          >
            <span v-if="changePasswordLoading">提交中...</span>
            <span v-else>确认修改</span>
          </button>
        </div>
      </div>
    </BottomSheet>
  </div>
</template>

<style scoped>
.profile-page {
  min-height: 100vh;
  background: var(--bg-primary);
  padding: 0;
}

.profile-container {
  max-width: 600px;
  margin: 0 auto;
}

.profile-content {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.75rem 1rem 2rem;
}

/* ==================== Bridge 模式专用样式 ==================== */
.profile-bridge-content {
  gap: var(--neo-space-3, 12px);
  padding: var(--neo-space-4, 16px);
}

/* Bridge 模式下的页面容器 */
.profile-page.profile-bridge {
  background: var(--neo-bg-base, #0B0F14);
}

/* 确保页面背景是纯黑，更符合 Apple TV+ 风格 */
:deep(.bg-card) {
  background: var(--bg-card);
}

/* Bridge 模式下的卡片间距调整 */
.profile-bridge-content > * {
  animation: bridge-fade-in 0.4s ease backwards;
}

.profile-bridge-content > *:nth-child(1) { animation-delay: 0ms; }
.profile-bridge-content > *:nth-child(2) { animation-delay: 50ms; }
.profile-bridge-content > *:nth-child(3) { animation-delay: 100ms; }
.profile-bridge-content > *:nth-child(4) { animation-delay: 150ms; }
.profile-bridge-content > *:nth-child(5) { animation-delay: 200ms; }

@keyframes bridge-fade-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ==================== 动效降级 ==================== */
@media (prefers-reduced-motion: reduce) {
  .profile-bridge-content > * {
    animation: none;
  }
}

/* ==================== 修改密码弹窗样式 ==================== */
.change-password-sheet {
  padding: 1.5rem 1rem 2rem;
}

.sheet-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 1.5rem 0;
  text-align: center;
}

.form-group {
  margin-bottom: 1rem;
}

.form-label {
  display: block;
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 0.5rem;
}

.form-input {
  width: 100%;
  padding: 0.875rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  color: #ffffff;
  font-size: 1rem;
  transition: all 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.15);
}

.form-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-input::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.error-message {
  color: #ef4444;
  font-size: 0.875rem;
  margin-top: 0.5rem;
  text-align: center;
}

.form-actions {
  display: flex;
  gap: 1rem;
  margin-top: 1.5rem;
}

.btn-cancel,
.btn-confirm {
  flex: 1;
  padding: 0.875rem;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
}

.btn-cancel {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.7);
}

.btn-cancel:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
}

.btn-confirm {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

.btn-confirm:hover:not(:disabled) {
  transform: scale(0.98);
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.3);
}

.btn-cancel:disabled,
.btn-confirm:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}
</style>
