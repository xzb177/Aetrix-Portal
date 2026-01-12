<script setup lang="ts">
/**
 * 首页 V4 - 单CTA转化优化版
 *
 * 核心改进：
 * - 首屏只保留1个主CTA按钮，消除双按钮冲突
 * - 到期提醒条移除内部按钮，只做信息与信任展示
 * - 次要操作降级为文字链接（查看套餐/权益说明）
 * - 主按钮增加"（推荐）"标签引导用户
 *
 * 转化路径：用户无需纠结 → 点击唯一主按钮 → 进入订阅页
 */
import { ref, onMounted, computed } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { announcementApi, authApi, subscriptionApi, userApi, embyApi } from '@/api'
import { useToast } from '@/composables/useToast'
import { getP0AnnouncementInstance } from '@/composables/useP0Announcement'
import P0AnnouncementModal from '@/components/P0AnnouncementModal.vue'
import AnnouncementSummaryBar from '@/components/AnnouncementSummaryBar.vue'
import AuthSheet from '@/components/AuthSheet.vue'
import {
  Play,
  Copy,
  Check,
  RefreshCw,
  Wallet,
  Users,
  Ticket,
  Crown,
  Eye,
  EyeOff,
  Github,
  MessageSquare,
  FileText,
  Activity,
  Gift,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Sparkles,
  HelpCircle,
  Key,
  Server,
  Lock,
  Info,
  Smartphone,
  Shield,
} from 'lucide-vue-next'

const router = useRouter()
const userStore = useUserStore()
const toast = useToast()

// P0 公告实例（仅首页使用）
const p0Announcement = getP0AnnouncementInstance()

// 数据状态
const announcements = ref<any[]>([])
const embyAccounts = ref<any[]>([])
const subscription = ref<any>(null)
const userBalance = ref(0)
const loading = ref(true)
const userStats = ref({ totalUsers: 0, activeUsers: 0 })

// 密码可见性状态
const visiblePasswords = ref<Set<number>>(new Set())
const showAccountDetail = ref(false)
const expandedAccountId = ref<number | null>(null)

// 问候语
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 9) return '早上好'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  if (hour < 22) return '晚上好'
  return '深夜了'
})

// VIP 状态
const isVIP = computed(() => userStore.isVIP)
const user = computed(() => userStore.user)
const isLoggedIn = computed(() => userStore.isLoggedIn)

// ============ V3 新增：主 CTA 按钮动态逻辑 ============
interface MainCTA {
  text: string
  link: string
  icon: any
  isExternal: boolean
}

const mainCTA = computed((): MainCTA => {
  const hasSub = !!subscription.value
  const daysLeft = subscription.value?.days_remaining ?? 0
  const hasAccount = embyAccounts.value.length > 0

  // 未订阅 → 开通会员
  if (!hasSub) {
    return {
      text: '开通会员',
      link: '/subscription',
      icon: Crown,
      isExternal: false
    }
  }

  // 已过期 → 立即续费
  if (daysLeft <= 0) {
    return {
      text: '立即续费',
      link: '/subscription',
      icon: RefreshCw,
      isExternal: false
    }
  }

  // 快到期（7天内）→ 续费享优惠
  if (daysLeft <= 7) {
    return {
      text: '续费享优惠',
      link: '/subscription',
      icon: Sparkles,
      isExternal: false
    }
  }

  // 有账号 → 进入 Emby
  if (hasAccount) {
    return {
      text: '进入 Emby',
      link: embyAccounts.value[0]?.server_url || '#',
      icon: Play,
      isExternal: true
    }
  }

  // 已订阅无账号 → 领取账号
  return {
    text: '领取账号',
    link: '#account',
    icon: Key,
    isExternal: false
  }
})

// V3 新增：是否显示脉冲动画（快到期时）
const shouldPulseCTA = computed(() => {
  const daysLeft = subscription.value?.days_remaining ?? 0
  return daysLeft >= 0 && daysLeft <= 7
})

// ============ V3 新增：3 步流程指示器 ============
interface Step {
  id: number
  label: string
  status: 'completed' | 'active' | 'pending'
}

const progressSteps = computed((): Step[] => {
  const hasSub = !!subscription.value
  const daysLeft = subscription.value?.days_remaining ?? 0
  const hasAccount = embyAccounts.value.length > 0
  const isActive = hasSub && daysLeft > 0

  return [
    {
      id: 1,
      label: '订阅会员',
      status: isActive ? 'completed' : (hasSub ? 'completed' : 'active')
    },
    {
      id: 2,
      label: '领取账号',
      status: hasAccount ? 'completed' : (isActive ? 'active' : 'pending')
    },
    {
      id: 3,
      label: '打开 Emby',
      status: hasAccount ? 'active' : 'pending'
    }
  ]
})

const currentStep = computed(() => {
  const steps = progressSteps.value
  const activeIndex = steps.findIndex(s => s.status === 'active')
  return activeIndex >= 0 ? activeIndex + 1 : 1
})

// 会员到期状态（V3 增强）
const expiryStatus = computed(() => {
  if (!subscription.value) return { text: '未开通', color: 'text-gray-400', showWarning: false, warningText: '' }
  const days = subscription.value.days_remaining
  if (days <= 0) return { text: '已过期', color: 'text-red-400', showWarning: true, warningText: '会员已过期，请续费', trustHint: '续费后立即生效' }
  if (days <= 3) return { text: `还剩 ${days} 天`, color: 'text-red-400', showWarning: true, warningText: '会员即将到期，请及时续费', trustHint: '续费后立即生效' }
  if (days <= 7) return { text: `还剩 ${days} 天`, color: 'text-yellow-400', showWarning: true, warningText: '会员即将到期', trustHint: '续费后立即生效' }
  return { text: `还剩 ${days} 天`, color: 'text-green-400', showWarning: false, warningText: '', trustHint: '' }
})

// 切换账号详情展开
const toggleAccountDetail = (accountId: number) => {
  if (expandedAccountId.value === accountId) {
    expandedAccountId.value = null
  } else {
    expandedAccountId.value = accountId
  }
}

// 一键复制全部账号信息
const copyAllAccountInfo = async (account: any) => {
  try {
    const text = `服务器: ${account.server_url}\n用户名: ${account.username}\n密码: ${account.password}`
    await navigator.clipboard.writeText(text)
    toast.success('已复制全部账号信息')
  } catch (err) {
    toast.error('复制失败')
  }
}

// Deep Link 尝试打开 Emby
const openEmbyApp = (account: any) => {
  const serverUrl = account.server_url?.replace(/^https?:\/\//, '') || ''
  const deepLink = `emby://${serverUrl}#${account.username}@${account.password || ''}`
  const startTime = Date.now()
  window.location.href = deepLink
  setTimeout(() => {
    if (Date.now() - startTime < 2500) {
      window.open(account.server_url, '_blank')
      toast.info('请在浏览器中登录 Emby')
    }
  }, 2000)
}

// 主 CTA 点击处理
const handleMainCTA = () => {
  if (mainCTA.value.isExternal) {
    openEmbyApp(embyAccounts.value[0])
  } else if (mainCTA.value.link.startsWith('#')) {
    // 滚动到账号区域
    document.querySelector('.account-section')?.scrollIntoView({ behavior: 'smooth' })
  } else {
    router.push(mainCTA.value.link)
  }
}

// 复制到剪贴板
const copyToClipboard = async (text: string, id: number, label = '内容') => {
  try {
    await navigator.clipboard.writeText(text)
    toast.copySuccess(label)
    embyAccounts.value.forEach((a: any) => {
      if (a.id === id) a.copied = true
    })
    setTimeout(() => {
      embyAccounts.value.forEach((a: any) => {
        if (a.id === id) a.copied = false
      })
    }, 1500)
  } catch (err) {
    toast.error('复制失败，请重试')
  }
}

// 切换密码可见性
const togglePassword = (id: number) => {
  if (visiblePasswords.value.has(id)) {
    visiblePasswords.value.delete(id)
  } else {
    visiblePasswords.value.add(id)
  }
}

const isPasswordVisible = (id: number) => visiblePasswords.value.has(id)

// 重置 Emby 账号
const resetAccount = async (accountId: number) => {
  if (!confirm('确定要重置此账号吗？重置后原账号将无法使用。')) return
  try {
    await embyApi.resetPassword(accountId)
    toast.success('账号重置成功')
    fetchEmbyAccounts()
  } catch (error) {
    toast.error('重置失败，请稍后重试')
  }
}

// 获取公告
const fetchAnnouncements = async () => {
  try {
    const res = await announcementApi.getAnnouncements({ limit: 3 })
    announcements.value = res.data || []
  } catch (error) {
    announcements.value = []
  }
}

// 获取 Emby 账号
const fetchEmbyAccounts = async () => {
  try {
    const response = await embyApi.getServers()
    // 响应拦截器已经解包了 data，直接使用 response
    const accounts = Array.isArray(response) ? response : (response?.data || [])
    embyAccounts.value = accounts.map((a: any) => ({ ...a, copied: false }))
  } catch (error) {
    console.error('Failed to fetch emby accounts:', error)
  }
}

// 获取订阅信息
const fetchSubscription = async () => {
  try {
    const response = await subscriptionApi.getMySubscription()
    subscription.value = response?.data?.data || response?.data
  } catch (error) {
    subscription.value = null
  }
}

// 获取用户余额
const fetchUserBalance = async () => {
  try {
    const response = await authApi.getCurrentUser() as any
    // API 拦截器已经返回了 res.data，所以直接访问 response.balance
    // balance 单位是分，需要转换为元
    userBalance.value = (response?.balance || response?.points || 0) / 100
  } catch (error) {
    userBalance.value = 0
  }
}

// 获取用户统计数据
const fetchUserStats = async () => {
  try {
    const response = await userApi.getStats()
    userStats.value = response?.data || { totalUsers: 0, activeUsers: 0 }
  } catch (error) {
    userStats.value = { totalUsers: 0, activeUsers: 0 }
  }
}

// P0 公告相关处理
const handleP0Copy = async () => {
  const content = p0Announcement.p0Content.value
  const title = p0Announcement.p0Announcement.value?.title || '公告'
  try {
    await navigator.clipboard.writeText(`${title}\n\n${content}`)
    toast.copySuccess('公告内容')
  } catch (err) {
    toast.error('复制失败')
  }
}

// Auth Sheet 状态
const showAuthSheet = ref(false)

// 打开登录/注册 Sheet
const openAuthSheet = () => {
  showAuthSheet.value = true
}

// 登录成功回调
const handleAuthSuccess = () => {
  // 刷新用户数据
  Promise.all([
    fetchEmbyAccounts(),
    fetchSubscription(),
    fetchUserBalance()
  ])
}

const handleP0SummaryClick = () => {
  // 从摘要条打开弹窗（非强制模式）
  if (p0Announcement.p0Announcement.value) {
    p0Announcement.openP0Modal(p0Announcement.p0Announcement.value)
  }
}

// 页面加载
onMounted(async () => {
  await fetchUserStats()
  if (!isLoggedIn.value) {
    loading.value = false
    return
  }
  await Promise.all([
    fetchAnnouncements(),
    fetchEmbyAccounts(),
    fetchSubscription(),
    fetchUserBalance()
  ])
  loading.value = false

  // 初始化 P0 公告（仅在首页触发）
  await p0Announcement.init()
})
</script>

<template>
  <div class="home-page">
    <!-- 未登录状态 - Apple TV 风格 -->
    <div v-if="!isLoggedIn" class="guest-view">
      <!-- 背景质感层（噪点 + 光晕） -->
      <div class="guest-bg"></div>

      <!-- 主内容区 -->
      <main class="guest-main">
        <!-- 主播放图标 -->
        <div class="hero-play-icon">
          <svg
            width="41"
            height="41"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.75"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M5 3l14 9-14 9V3z" />
            <rect x="2" y="2" width="20" height="20" rx="4" opacity="0.15" />
          </svg>
        </div>

        <!-- 标题 -->
        <h1 class="guest-title">私享影院，静候开启</h1>

        <!-- 副标题 -->
        <p class="guest-subtitle">领取账号 · 即刻观影</p>

        <!-- 唯一主 CTA（玻璃质感，非亮渐变） -->
        <button class="guest-cta" @click="openAuthSheet">
          <span>登录 / 注册</span>
        </button>

        <!-- 信任小字（简化） -->
        <p class="guest-trust">无自动续费 · 订单可查</p>

        <!-- 分割线 -->
        <div class="divider-line"></div>

        <!-- 一行三要点（非卡片） -->
        <div class="features-row">
          <div class="feature-item">
            <span class="feature-label">4K 超清</span>
          </div>
          <div class="feature-item">
            <span class="feature-label">多端同步</span>
          </div>
          <div class="feature-item">
            <span class="feature-label">即时开通</span>
          </div>
        </div>

        <!-- 分割线 -->
        <div class="divider-line"></div>

        <!-- 极弱次要入口 -->
        <div class="guest-secondary">
          <RouterLink to="/subscription" class="weak-link">套餐说明</RouterLink>
          <span class="weak-divider">·</span>
          <RouterLink to="/tickets" class="weak-link">联系客服</RouterLink>
        </div>
      </main>
    </div>

    <!-- 已登录状态 - V3 改造 -->
    <div v-else-if="!loading" class="logged-in-view">
      <!-- V3: 3 步流程指示器 -->
      <div class="progress-stepper">
        <div
          v-for="step in progressSteps"
          :key="step.id"
          class="step"
          :class="{
            'active': step.status === 'active' || step.status === 'completed',
            'completed': step.status === 'completed'
          }"
        >
          <div class="step-dot">
            <Check v-if="step.status === 'completed'" :size="14" />
            <span v-else>{{ step.id }}</span>
          </div>
          <span class="step-label">{{ step.label }}</span>
        </div>
        <div class="step-line" :class="{ active: progressSteps[1].status === 'completed' }"></div>
        <div class="step-line" :class="{ active: progressSteps[2].status === 'completed' }"></div>
      </div>

      <!-- 状态卡片 -->
      <div class="status-card glass-card">
        <!-- 状态头部 -->
        <div class="status-header">
          <div class="status-user">
            <span class="status-greeting">{{ greeting }}，{{ user?.username || '用户' }}</span>
          </div>
          <div class="status-badges">
            <span class="status-badge" :class="expiryStatus.color">
              <Crown :size="14" />
              {{ expiryStatus.text }}
            </span>
          </div>
        </div>

        <!-- V4: 到期提醒条（纯信息展示，移除内部按钮避免CTA冲突） -->
        <div v-if="expiryStatus.showWarning" class="expiry-info-bar">
          <AlertTriangle :size="14" class="expiry-icon" />
          <div class="expiry-content">
            <span class="expiry-text">{{ expiryStatus.warningText }}</span>
            <span class="expiry-trust">续费后立即生效 · 订单可查</span>
          </div>
        </div>

        <!-- P0 公告摘要条（已读后显示） -->
        <AnnouncementSummaryBar
          :show="p0Announcement.showSummaryBar"
          :announcement="p0Announcement.p0Announcement"
          @click="handleP0SummaryClick"
        />

        <!-- V4: 动态主 CTA 按钮（全宽，唯一的行动按钮） -->
        <button
          @click="handleMainCTA"
          class="main-cta-button"
          :class="{ pulse: shouldPulseCTA }"
        >
          <component :is="mainCTA.icon" :size="20" />
          <span>{{ mainCTA.text }}<span v-if="shouldPulseCTA" class="cta-recommend">（推荐）</span></span>
          <ChevronRight v-if="!mainCTA.isExternal" :size="18" class="cta-arrow" />
        </button>

        <!-- V4: 次要文字链接（查看套餐/权益） -->
        <div class="secondary-links">
          <RouterLink to="/subscription" class="text-link">
            查看套餐
          </RouterLink>
          <span class="link-divider">·</span>
          <RouterLink to="/subscription" class="text-link">
            权益说明
          </RouterLink>
        </div>

        <!-- 有 Emby 账号 -->
        <template v-if="embyAccounts.length > 0">
          <div class="status-divider"></div>

          <!-- 账号列表 -->
          <div class="accounts-list account-section">
            <div
              v-for="account in embyAccounts"
              :key="account.id"
              class="account-item"
              :class="{ 'expanded': expandedAccountId === account.id }"
            >
              <div class="account-header" @click="toggleAccountDetail(account.id)">
                <div class="account-info">
                  <span class="account-label">Emby 账号</span>
                  <span class="account-username">{{ account.username }}</span>
                </div>
                <ChevronDown
                  :size="16"
                  class="account-chevron"
                  :class="{ 'rotated': expandedAccountId === account.id }"
                />
              </div>

              <div v-show="expandedAccountId === account.id" class="account-detail">
                <div class="detail-row">
                  <span class="detail-label">服务器</span>
                  <code class="detail-value">{{ account.server_url }}</code>
                  <button
                    @click.stop="copyToClipboard(account.server_url, account.id, '服务器地址')"
                    class="btn-icon-sm"
                  >
                    <Copy :size="12" />
                  </button>
                </div>
                <div class="detail-row">
                  <span class="detail-label">用户名</span>
                  <code class="detail-value">{{ account.username }}</code>
                  <button
                    @click.stop="copyToClipboard(account.username, account.id, '用户名')"
                    class="btn-icon-sm"
                  >
                    <Copy :size="12" />
                  </button>
                </div>
                <div class="detail-row">
                  <span class="detail-label">密码</span>
                  <code class="detail-value">
                    {{ isPasswordVisible(account.id) ? account.password : '••••••' }}
                  </code>
                  <button
                    @click.stop="togglePassword(account.id)"
                    class="btn-icon-sm"
                  >
                    <Eye v-if="!isPasswordVisible(account.id)" :size="12" />
                    <EyeOff v-else :size="12" />
                  </button>
                  <button
                    @click.stop="copyToClipboard(account.password, account.id, '密码')"
                    class="btn-icon-sm"
                  >
                    <Copy :size="12" />
                  </button>
                </div>
                <button
                  @click.stop="copyAllAccountInfo(account)"
                  class="btn-copy-all"
                >
                  <Copy :size="14" />
                  一键复制全部信息
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- V3: 空状态（增强版 - 账号预览卡片） -->
        <template v-else>
          <div class="status-divider"></div>
          <div class="account-empty-state">
            <!-- 图标 -->
            <div class="empty-icon">
              <Key :size="32" />
            </div>

            <h3 class="empty-title">Emby 账号</h3>
            <p class="empty-desc">订阅后您将获得专属 Emby 观影账号</p>

            <!-- 预览卡片 -->
            <div class="account-preview">
              <div class="preview-header">
                <span class="preview-label">账号预览</span>
                <span class="preview-tag">示例</span>
              </div>
              <div class="preview-body">
                <div class="preview-field">
                  <Server :size="14" class="field-icon" />
                  <span class="field-label">服务器地址</span>
                  <span class="field-value">play.example.com</span>
                </div>
                <div class="preview-field">
                  <Users :size="14" class="field-icon" />
                  <span class="field-label">用户名</span>
                  <span class="field-value">user_12345</span>
                </div>
                <div class="preview-field">
                  <Lock :size="14" class="field-icon" />
                  <span class="field-label">密码</span>
                  <span class="field-value">••••••••</span>
                </div>
              </div>
              <div class="preview-footer">
                <span class="preview-tip">
                  <Info :size="12" />
                  支付成功后，账号信息将显示在此处
                </span>
              </div>
            </div>

            <!-- CTA 按钮 -->
            <RouterLink to="/subscription" class="empty-cta">
              开通会员
              <ChevronRight :size="16" />
            </RouterLink>
          </div>
        </template>
      </div>

      <!-- 快捷操作 2x2 网格 -->
      <div class="quick-grid">
        <RouterLink to="/recharge" class="quick-item">
          <div class="quick-icon">
            <Wallet :size="24" />
          </div>
          <span class="quick-label">余额</span>
          <span class="quick-value">¥{{ userBalance }}</span>
        </RouterLink>

        <RouterLink to="/invite" class="quick-item">
          <div class="quick-icon">
            <Users :size="24" />
          </div>
          <span class="quick-label">邀请</span>
          <span class="quick-value">赚取奖励</span>
        </RouterLink>

        <RouterLink to="/exchange-code" class="quick-item">
          <div class="quick-icon">
            <Gift :size="24" />
          </div>
          <span class="quick-label">兑换码</span>
          <span class="quick-value">兑换奖励</span>
        </RouterLink>

        <RouterLink to="/tickets" class="quick-item">
          <div class="quick-icon">
            <Ticket :size="24" />
          </div>
          <span class="quick-label">客服</span>
          <span class="quick-value">联系客服</span>
        </RouterLink>
      </div>

      <!-- 公告 -->
      <div v-if="announcements.length > 0" class="announcements-section">
        <div class="announcement-list glass-card">
          <div
            v-for="item in announcements"
            :key="item.id"
            class="announcement-item"
          >
            <span class="announcement-tag">{{ item.type || '通知' }}</span>
            <span class="announcement-text">{{ item.title }}</span>
            <ChevronRight :size="14" class="announcement-arrow" />
          </div>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading && isLoggedIn" class="loading-state">
      <div class="spinner spinner-lg"></div>
      <p>加载中...</p>
    </div>

    <!-- P0 公告弹层（仅在首页强制弹出） -->
    <P0AnnouncementModal
      :show="p0Announcement.showP0Modal"
      :announcement="p0Announcement.p0Announcement"
      :content="p0Announcement.p0Content"
      :show-copy-button="true"
      @close="p0Announcement.closeP0Modal"
      @copy="handleP0Copy"
    />

    <!-- 登录/注册 Bottom Sheet -->
    <AuthSheet
      :show="showAuthSheet"
      @update:show="showAuthSheet = $event"
      @success="handleAuthSuccess"
    />
  </div>
</template>

<style scoped>
/* ==================== 基础样式 ==================== */
.home-page {
  min-height: 100vh;
  background: transparent;
}

/* ==================== V3: 3 步流程指示器 ==================== */
.progress-stepper {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 1rem 1rem 1.5rem;
  margin-bottom: 0.5rem;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  position: relative;
  z-index: 1;
}

.step-dot {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: #262626;
  color: #525252;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  border: 2px solid #262626;
  transition: all 0.3s ease;
}

.step.active .step-dot {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  border-color: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.15);
}

.step.completed .step-dot {
  background: #10b981;
  color: white;
  border-color: #10b981;
}

.step-label {
  font-size: 0.688rem;
  color: #525252;
  font-weight: 500;
  transition: color 0.3s ease;
}

.step.active .step-label {
  color: #d4d4d4;
}

.step.completed .step-label {
  color: #10b981;
}

.step-line {
  width: 2.5rem;
  height: 2px;
  background: #262626;
  margin: 0 -0.25rem;
  margin-bottom: 1.125rem;
  z-index: 0;
  transition: background 0.3s ease;
}

.step-line.active {
  background: linear-gradient(90deg, #10b981 0%, #059669 100%);
}

/* ==================== V3: 主 CTA 按钮 ==================== */
.main-cta-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  padding: 1rem 1.5rem;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  font-size: 1rem;
  font-weight: 600;
  border-radius: 1rem;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 20px rgba(16, 185, 129, 0.3);
}

.main-cta-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 30px rgba(16, 185, 129, 0.4);
}

.main-cta-button:active {
  transform: scale(0.98);
}

.cta-arrow {
  margin-left: 0.25rem;
  transition: transform 0.2s ease;
}

.main-cta-button:hover .cta-arrow {
  transform: translateX(4px);
}

/* 快到期时的脉冲动画 */
.main-cta-button.pulse {
  animation: cta-pulse 2s ease-in-out infinite;
}

@keyframes cta-pulse {
  0%, 100% {
    box-shadow: 0 4px 20px rgba(16, 185, 129, 0.3);
  }
  50% {
    box-shadow: 0 4px 30px rgba(16, 185, 129, 0.6), 0 0 0 4px rgba(16, 185, 129, 0.2);
  }
}

/* CTA 推荐标签 */
.cta-recommend {
  font-size: 0.75rem;
  font-weight: 400;
  opacity: 0.9;
  margin-left: 0.125rem;
}

/* ==================== V4: 次要文字链接 ==================== */
.secondary-links {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding-bottom: 0.5rem;
}

.text-link {
  font-size: 0.813rem;
  color: #737373;
  text-decoration: none;
  transition: color 0.2s ease;
}

.text-link:hover {
  color: #a3a3a3;
  text-decoration: underline;
}

.link-divider {
  color: #404040;
  font-size: 0.75rem;
}

/* ==================== V4: 到期信息条（纯信息展示，无按钮） ==================== */
.expiry-info-bar {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  margin-bottom: 1rem;
  background: linear-gradient(90deg,
    rgba(245, 158, 11, 0.12) 0%,
    rgba(245, 158, 11, 0.04) 100%);
  border-left: 3px solid rgb(245, 158, 11);
  border-radius: 0 0.75rem 0.75rem 0;
}

.expiry-icon {
  color: rgb(245, 158, 11);
  flex-shrink: 0;
  margin-top: 0.125rem;
}

.expiry-content {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
}

.expiry-text {
  font-size: 0.875rem;
  color: #e5e5e5;
  font-weight: 500;
}

.expiry-trust {
  font-size: 0.75rem;
  color: #a3a3a3;
}

/* ==================== V3: 空状态账号预览 ==================== */
.account-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1.5rem 1rem;
  text-align: center;
}

.empty-icon {
  width: 3rem;
  height: 3rem;
  border-radius: 0.75rem;
  background: rgba(16, 185, 129, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #10b981;
  margin-bottom: 0.75rem;
}

.empty-title {
  font-size: 1rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 0.25rem;
}

.empty-desc {
  font-size: 0.813rem;
  color: #a3a3a3;
  margin: 0 0 1rem;
}

/* 预览卡片 */
.account-preview {
  width: 100%;
  max-width: 280px;
  background: rgba(26, 26, 26, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.75rem;
  overflow: hidden;
  margin-bottom: 1rem;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.preview-label {
  font-size: 0.688rem;
  font-weight: 600;
  color: #737373;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.preview-tag {
  padding: 0.125rem 0.375rem;
  background: rgba(255, 255, 255, 0.05);
  color: #525252;
  font-size: 0.625rem;
  border-radius: 0.25rem;
}

.preview-body {
  padding: 0.75rem;
}

.preview-field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.preview-field:last-child {
  border-bottom: none;
}

.field-icon {
  color: #525252;
  flex-shrink: 0;
}

.field-label {
  font-size: 0.75rem;
  color: #737373;
  min-width: 3rem;
  text-align: left;
}

.field-value {
  font-size: 0.813rem;
  color: #d4d4d4;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  flex: 1;
  text-align: right;
}

.preview-footer {
  padding: 0.5rem 0.75rem;
  background: rgba(16, 185, 129, 0.05);
  border-top: 1px solid rgba(16, 185, 129, 0.1);
}

.preview-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  font-size: 0.688rem;
  color: #10b981;
}

.empty-cta {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.75rem 1.5rem;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  font-size: 0.875rem;
  font-weight: 600;
  border-radius: 0.75rem;
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(16, 185, 129, 0.3);
  text-decoration: none;
}

.empty-cta:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 24px rgba(16, 185, 129, 0.4);
}

/* ==================== Hero 主播放图标 ==================== */
.hero-play-icon {
  width: 64px;
  height: 64px;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow:
    0 2px 8px rgba(0, 0, 0, 0.2),
    0 0 0 1px rgba(16, 185, 129, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1.5rem;
  transition: all 0.15s ease;
}

.hero-play-icon:active {
  transform: scale(0.96);
  background: rgba(255, 255, 255, 0.08);
}

.hero-play-icon svg {
  color: rgba(255, 255, 255, 0.85);
  flex-shrink: 0;
}

/* ==================== 未登录 Apple TV 风格样式 ==================== */
.guest-view {
  min-height: 100svh;
  min-height: 100dvh;
  position: relative;
  display: flex;
  flex-direction: column;
  padding-top: env(safe-area-inset-top, 0);
  padding-bottom: env(safe-area-inset-bottom, 0);
  overflow-x: hidden;
}

/* 背景层：深色渐变 + 噪点 + 微光晕 */
.guest-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  background:
    /* 径向光晕（左上暗角） */
    radial-gradient(ellipse at 20% 0%, rgba(60, 60, 60, 0.15) 0%, transparent 60%),
    /* 径向光晕（右下微光） */
    radial-gradient(ellipse at 80% 100%, rgba(50, 50, 50, 0.1) 0%, transparent 50%),
    /* 主渐变：从深灰到近黑 */
    linear-gradient(180deg, #1a1a1a 0%, #0a0a0a 100%);
}

/* 噪点质感（用伪元素实现） */
.guest-bg::before {
  content: '';
  position: absolute;
  inset: 0;
  /* SVG 噪点 data URI（极细噪点） */
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-repeat: repeat;
  opacity: 0.03;
  pointer-events: none;
}

/* 主内容区 */
.guest-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 3rem 1.25rem 1.5rem;
  text-align: center;
}

/* 主标题 */
.guest-title {
  font-size: 1.375rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin: 0 0 0.75rem;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

/* 副标题 */
.guest-subtitle {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 2rem;
  font-weight: 400;
  letter-spacing: 0.01em;
}

/* 唯一主 CTA（玻璃质感，非亮渐变） */
.guest-cta {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  max-width: 280px;
  height: 52px;
  /* 玻璃态，低饱和 */
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.95);
  font-size: 1rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  transition: all 0.2s ease;
  cursor: pointer;
  /* 触控高度 */
  min-height: 52px;
}

.guest-cta:active {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.3);
  transform: scale(0.98);
}

/* 信任小字 */
.guest-trust {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.35);
  margin-top: 1rem;
  letter-spacing: 0.02em;
}

/* 分割线（极细） */
.divider-line {
  width: 100%;
  max-width: 200px;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.1) 50%,
    transparent 100%
  );
  margin: 1.5rem 0;
}

/* 一行三要点（非卡片） */
.features-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  width: 100%;
}

.feature-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
}

.feature-item::before {
  content: '';
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.feature-label {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  font-weight: 400;
}

/* 极弱次要入口 */
.guest-secondary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.weak-link {
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.35);
  text-decoration: none;
  transition: color 0.15s ease;
}

.weak-link:active {
  color: rgba(255, 255, 255, 0.5);
}

.weak-divider {
  color: rgba(255, 255, 255, 0.15);
  font-size: 0.75rem;
}

/* ==================== 已登录视图 ==================== */
.logged-in-view {
  max-width: 600px;
  margin: 0 auto;
  padding: 1rem 1rem 1.5rem;
}

/* ==================== 状态卡片 ==================== */
.status-card {
  margin-bottom: 1rem;
  padding: 1rem;
}

.status-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.status-user {
  flex: 1;
}

.status-greeting {
  font-size: 1rem;
  font-weight: 600;
  color: #fafafa;
}

.status-badges {
  display: flex;
  gap: 0.5rem;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.375rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.status-badge.text-green-400 {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.status-badge.text-yellow-400 {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}

.status-badge.text-red-400 {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.status-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
  margin: 1rem 0;
}

/* ==================== 账号列表 ==================== */
.accounts-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.account-item {
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.5rem;
  overflow: hidden;
  transition: all 0.2s ease;
}

.account-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.03);
}

.account-header:active {
  background: rgba(255, 255, 255, 0.06);
}

.account-info {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.account-label {
  font-size: 0.75rem;
  color: #a3a3a3;
  font-weight: 500;
  letter-spacing: 0.02em;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.account-label::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.account-username {
  font-size: 0.813rem;
  font-weight: 500;
  color: #fafafa;
  font-family: 'SF Mono', ui-monospace, monospace;
}

.account-chevron {
  color: #737373;
  transition: transform 0.2s ease;
}

.account-chevron.rotated {
  transform: rotate(180deg);
}

/* 账号详情 */
.account-detail {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0 0.75rem 0.75rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.detail-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.detail-label {
  width: 3rem;
  font-size: 0.75rem;
  color: #737373;
}

.detail-value {
  flex: 1;
  font-size: 0.75rem;
  padding: 0.375rem 0.5rem;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  font-family: 'SF Mono', ui-monospace, monospace;
  color: rgba(250, 250, 250, 0.8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-icon-sm {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 4px;
  border: none;
  background: transparent;
  color: #737373;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-icon-sm:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fafafa;
}

.btn-copy-all {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.625rem;
  margin-top: 0.5rem;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 0.5rem;
  color: rgba(250, 250, 250, 0.7);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-copy-all:active {
  background: rgba(255, 255, 255, 0.05);
}

/* ==================== 快捷网格 ==================== */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  background: rgba(26, 26, 26, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.75rem;
  text-decoration: none;
  transition: all 0.15s ease;
  min-height: 90px;
}

.quick-item:active {
  transform: scale(0.98);
  background: rgba(255, 255, 255, 0.03);
}

.quick-icon {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.5rem;
  background: rgba(16, 185, 129, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #10b981;
}

.quick-label {
  font-size: 0.813rem;
  font-weight: 500;
  color: #fafafa;
}

.quick-value {
  font-size: 0.688rem;
  color: #737373;
}

/* ==================== 公告区域 ==================== */
.announcements-section {
  margin-bottom: 1.5rem;
}

.announcement-list {
  overflow: hidden;
}

.announcement-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  transition: background 0.2s ease;
}

.annotation-item:last-child {
  border-bottom: none;
}

.announcement-item:hover {
  background: rgba(255, 255, 255, 0.03);
}

.announcement-tag {
  padding: 0.125rem 0.5rem;
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
  border-radius: 4px;
  font-size: 0.688rem;
  font-weight: 500;
}

.announcement-text {
  flex: 1;
  font-size: 0.813rem;
  color: rgba(255, 255, 255, 0.8);
}

.announcement-arrow {
  color: #525252;
}

/* ==================== Loading ==================== */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 50vh;
  color: rgba(255, 255, 255, 0.6);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== 响应式 ==================== */
@media (max-width: 640px) {
  .logged-in-view {
    padding: 0.75rem 0.75rem 1rem;
  }

  .quick-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 0.5rem;
  }

  .progress-stepper {
    padding: 0.75rem 0.5rem 1rem;
  }

  .step-dot {
    width: 1.5rem;
    height: 1.5rem;
    font-size: 0.688rem;
  }

  .step-label {
    font-size: 0.625rem;
  }

  .step-line {
    width: 2rem;
  }

  .expiry-info-bar {
    padding: 0.75rem 0.875rem;
  }

  .secondary-links {
    gap: 0.375rem;
  }

  .text-link {
    font-size: 0.75rem;
  }
}
</style>
