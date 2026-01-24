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
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { announcementApi, authApi, subscriptionApi, userApi, embyApi } from '@/api'
import { useToast } from '@/composables/useToast'
import { useAuthSheet } from '@/composables/useAuthSheet'
import { getP0AnnouncementInstance } from '@/composables/useP0Announcement'
import P0AnnouncementModal from '@/components/P0AnnouncementModal.vue'
import AnnouncementSummaryBar from '@/components/AnnouncementSummaryBar.vue'
import PlayerSelectorSheet from '@/components/PlayerSelectorSheet.vue'
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
const { showAuthSheet, openAuthSheet, closeAuthSheet } = useAuthSheet()

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
  // 调试日志
  console.log('[handleMainCTA] 被调用', {
    isExternal: mainCTA.value.isExternal,
    link: mainCTA.value.link,
    text: mainCTA.value.text,
    embyAccountsLength: embyAccounts.value.length
  })

  if (mainCTA.value.isExternal) {
    // 多线路优化：如果有多个账号，显示线路选择器
    if (embyAccounts.value.length === 0) {
      toast.error('没有可用的 Emby 账号')
      return
    }

    if (embyAccounts.value.length === 1) {
      // 只有一个账号，直接打开播放器选择器
      selectedAccount.value = embyAccounts.value[0]
      showPlayerSelector.value = true
    } else {
      // 多个账号，显示线路选择器
      showRouteSelector.value = true
    }
  } else if (mainCTA.value.link.startsWith('#')) {
    // 滚动到账号区域
    document.querySelector('.account-section')?.scrollIntoView({ behavior: 'smooth' })
  } else {
    router.push(mainCTA.value.link)
  }
}

// 线路选择器状态
const showRouteSelector = ref(false)

// 选择线路并打开播放器选择器
const selectRoute = (account: any) => {
  selectedAccount.value = account
  showRouteSelector.value = false
  showPlayerSelector.value = true
}

// 快速打开播放器（跳过选择，直接使用第一个账号）
const quickOpenPlayer = (account: any) => {
  selectedAccount.value = account
  showPlayerSelector.value = true
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

// 播放器选择 Sheet 状态
const showPlayerSelector = ref(false)
const selectedAccount = ref<any>(null)

// 登录成功回调
const handleAuthSuccess = async () => {
  // 刷新用户数据
  await loadUserData()
}

// 加载用户数据（统一入口）
const loadUserData = async () => {
  if (!isLoggedIn.value) return
  loading.value = true
  try {
    await Promise.all([
      fetchAnnouncements(),
      fetchEmbyAccounts(),
      fetchSubscription(),
      fetchUserBalance()
    ])
  } finally {
    loading.value = false
  }
}

// 监听登录状态变化 - 当从未登录变为已登录时自动加载数据
watch(isLoggedIn, (newValue, oldValue) => {
  // 只在从未登录变为已登录时触发
  if (newValue && !oldValue) {
    loadUserData()
  }
})

const handleP0SummaryClick = () => {
  // 从摘要条打开弹窗（非强制模式）
  if (p0Announcement.p0Announcement.value) {
    p0Announcement.openP0Modal(p0Announcement.p0Announcement.value)
  }
}

// 页面加载
onMounted(async () => {
  await fetchUserStats()
  // 如果已登录，加载用户数据
  if (isLoggedIn.value) {
    await loadUserData()
  } else {
    loading.value = false
  }

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

    <!-- 骨架屏 - 加载中 -->
    <div v-else-if="loading && isLoggedIn" class="skeleton-view">
      <!-- 骨架：3 步流程指示器 -->
      <div class="progress-stepper skeleton-stepper">
        <div class="step" v-for="i in 3" :key="i">
          <div class="skeleton-step-dot"></div>
          <div class="skeleton-step-label"></div>
        </div>
        <div class="skeleton-step-line" v-for="i in 2" :key="`line-${i}`"></div>
      </div>

      <!-- 骨架：状态卡片 -->
      <div class="status-card skeleton-card">
        <div class="skeleton-header">
          <div class="skeleton-greeting"></div>
          <div class="skeleton-badge"></div>
        </div>
        <div class="skeleton-divider"></div>
        <div class="skeleton-cta-button"></div>
        <div class="skeleton-secondary-links"></div>
        <div class="skeleton-divider"></div>
        <!-- 骨架：账号预览 -->
        <div class="skeleton-account-preview">
          <div class="skeleton-preview-header"></div>
          <div class="skeleton-preview-body">
            <div class="skeleton-preview-field" v-for="i in 3" :key="i"></div>
          </div>
        </div>
      </div>

      <!-- 骨架：快捷网格 -->
      <div class="quick-grid skeleton-grid">
        <div class="skeleton-quick-item" v-for="i in 4" :key="i">
          <div class="skeleton-quick-icon"></div>
          <div class="skeleton-quick-label"></div>
        </div>
      </div>
    </div>

    <!-- 已登录状态 - V3 改造 -->
    <div v-else class="logged-in-view">
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
                  <span class="account-label">
                    {{ account.server_name || 'Emby 账号' }}
                    <span v-if="account.is_expired" class="account-expired-tag">已过期</span>
                  </span>
                  <span class="account-username">{{ account.username }}</span>
                </div>
                <ChevronDown
                  :size="16"
                  class="account-chevron"
                  :class="{ 'rotated': expandedAccountId === account.id }"
                />
              </div>

              <div v-show="expandedAccountId === account.id" class="account-detail">
                <!-- 服务器地址 + 协议 -->
                <div class="detail-row">
                  <span class="detail-label">服务器</span>
                  <code class="detail-value detail-url">{{ account.server_url }}</code>
                  <button
                    @click.stop="copyToClipboard(account.server_url, account.id, '服务器地址')"
                    class="btn-icon-sm"
                    title="复制"
                  >
                    <Copy :size="12" />
                  </button>
                </div>
                <!-- 端口 -->
                <div class="detail-row">
                  <span class="detail-label">端口</span>
                  <code class="detail-value">{{ account.server_url?.match(/:(\d+)/)?.[1] || (account.server_url?.startsWith('https') ? '443' : '80') }}</code>
                  <button
                    @click.stop="copyToClipboard(account.server_url?.match(/:(\d+)/)?.[1] || (account.server_url?.startsWith('https') ? '443' : '80'), account.id, '端口')"
                    class="btn-icon-sm"
                    title="复制"
                  >
                    <Copy :size="12" />
                  </button>
                </div>
                <!-- 用户名 -->
                <div class="detail-row">
                  <span class="detail-label">用户名</span>
                  <code class="detail-value">{{ account.username }}</code>
                  <button
                    @click.stop="copyToClipboard(account.username, account.id, '用户名')"
                    class="btn-icon-sm"
                    title="复制"
                  >
                    <Copy :size="12" />
                  </button>
                </div>
                <!-- 密码 -->
                <div class="detail-row">
                  <span class="detail-label">密码</span>
                  <code class="detail-value">
                    {{ isPasswordVisible(account.id) ? account.password : '••••••' }}
                  </code>
                  <button
                    @click.stop="togglePassword(account.id)"
                    class="btn-icon-sm"
                    :title="isPasswordVisible(account.id) ? '隐藏' : '显示'"
                  >
                    <Eye v-if="!isPasswordVisible(account.id)" :size="12" />
                    <EyeOff v-else :size="12" />
                  </button>
                  <button
                    @click.stop="copyToClipboard(account.password, account.id, '密码')"
                    class="btn-icon-sm"
                    title="复制"
                  >
                    <Copy :size="12" />
                  </button>
                </div>
                <!-- 一键复制全部 -->
                <button
                  @click.stop="copyAllAccountInfo(account)"
                  class="btn-copy-all"
                >
                  <Copy :size="14" />
                  一键复制全部信息
                </button>
                <!-- 一键导入播放器 -->
                <button
                  @click.stop="quickOpenPlayer(account)"
                  class="btn-import-player"
                >
                  <Play :size="14" />
                  一键导入播放器
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
      :show="(showAuthSheet as boolean)"
      @update:show="closeAuthSheet"
      @success="handleAuthSuccess"
    />

    <!-- 播放器选择 Bottom Sheet -->
    <PlayerSelectorSheet
      :show="showPlayerSelector && selectedAccount !== null"
      :account="selectedAccount || { server_url: '', username: '', password: '' }"
      @update:show="showPlayerSelector = $event"
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

/* ==================== V3: 空状态账号预览 (Neo-Noir 2.0) ==================== */
.account-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--neo-space-5, 20px) var(--neo-space-4, 16px);
  text-align: center;
}

.empty-icon {
  width: 3rem;
  height: 3rem;
  border-radius: var(--neo-radius-sm, 12px);
  background: var(--neo-primary-dim, rgba(16, 185, 129, 0.12));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-primary, #10B981);
  margin-bottom: var(--neo-space-3, 12px);
}

.empty-title {
  font-size: var(--neo-font-size-md, 14px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  margin: 0 0 var(--neo-space-1, 4px);
}

.empty-desc {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.68));
  margin: 0 0 var(--neo-space-4, 16px);
}

/* 预览卡片 (Neo-Noir 2.0) */
.account-preview {
  width: 100%;
  max-width: 280px;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--neo-border-default, rgba(255, 255, 255, 0.08));
  border-radius: var(--neo-radius-lg, 18px);
  overflow: hidden;
  margin-bottom: var(--neo-space-4, 16px);
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--neo-space-2, 8px) var(--neo-space-3, 12px);
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border-bottom: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.05));
}

.preview-label {
  font-size: var(--neo-font-size-xs, 11px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.preview-tag {
  padding: var(--neo-space-1, 4px) var(--neo-space-2, 8px);
  background: var(--neo-bg-surface-3, rgba(255, 255, 255, 0.08));
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  font-size: 10px;
  border-radius: var(--neo-radius-xs, 8px);
}

.preview-body {
  padding: var(--neo-space-3, 12px);
}

.preview-field {
  display: flex;
  align-items: center;
  gap: var(--neo-space-2, 8px);
  padding: var(--neo-space-2, 8px) 0;
  border-bottom: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.03));
}

.preview-field:last-child {
  border-bottom: none;
}

.field-icon {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  flex-shrink: 0;
}

.field-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  min-width: 3rem;
  text-align: left;
}

.field-value {
  font-size: var(--neo-font-size-sm, 12px);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  flex: 1;
  text-align: right;
}

.preview-footer {
  padding: var(--neo-space-2, 8px) var(--neo-space-3, 12px);
  background: var(--neo-primary-dim, rgba(16, 185, 129, 0.08));
  border-top: 1px solid var(--neo-border-focus, rgba(16, 185, 129, 0.1));
}

.preview-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--neo-space-1, 4px);
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-primary, #10B981);
}

/* 空状态 CTA 按钮 (Neo-Noir 2.0) */
.empty-cta {
  display: inline-flex;
  align-items: center;
  gap: var(--neo-space-1, 4px);
  padding: var(--neo-space-3, 12px) var(--neo-space-5, 20px);
  background: var(--neo-primary, #10B981);
  color: var(--neo-text-inverse, #ffffff);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-semibold, 600);
  border-radius: var(--neo-radius-sm, 12px);
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
  box-shadow: var(--neo-glow-primary, 0 4px 16px rgba(16, 185, 129, 0.3));
  text-decoration: none;
}

.empty-cta:hover {
  transform: translateY(-1px);
  box-shadow: var(--neo-shadow-lg, 0 8px 24px rgba(16, 185, 129, 0.4));
  background: var(--neo-primary-hover, #059669);
}

.empty-cta:active {
  transform: scale(var(--neo-scale-press, 0.98));
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

/* ==================== 账号列表 (Neo-Noir 2.0) ==================== */
.accounts-list {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-2, 8px);
}

.account-item {
  border: 1px solid var(--neo-border-default, rgba(255, 255, 255, 0.08));
  border-radius: var(--neo-radius-lg, 18px);
  overflow: hidden;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
}

.account-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--neo-space-3, 12px) var(--neo-space-4, 16px);
  cursor: pointer;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  transition: background var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
}

.account-header:active {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.08));
}

.account-info {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-1, 4px);
}

.account-label {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  font-weight: var(--neo-font-weight-medium, 500);
  letter-spacing: 0.02em;
  display: flex;
  align-items: center;
  gap: var(--neo-space-1, 4px);
  text-transform: uppercase;
}

.account-label::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--neo-primary, #10B981);
  box-shadow: var(--neo-glow-primary, 0 0 8px rgba(16, 185, 129, 0.4));
}

.account-username {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-semibold, 600);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  font-family: 'SF Mono', ui-monospace, monospace;
}

.account-chevron {
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  transition: transform var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
}

.account-chevron.rotated {
  transform: rotate(180deg);
}

/* 账号详情 (Neo-Noir 2.0) */
.account-detail {
  display: flex;
  flex-direction: column;
  gap: var(--neo-space-2, 8px);
  padding: var(--neo-space-3, 12px);
  border-top: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
}

.detail-row {
  display: flex;
  align-items: center;
  gap: var(--neo-space-2, 8px);
  padding: var(--neo-space-1, 4px) 0;
}

.detail-label {
  width: 3rem;
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  font-weight: var(--neo-font-weight-medium, 500);
}

.detail-value {
  flex: 1;
  font-size: var(--neo-font-size-sm, 12px);
  padding: var(--neo-space-2, 8px) 10px;
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: var(--neo-radius-sm, 12px);
  font-family: 'SF Mono', ui-monospace, monospace;
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-value.detail-url {
  color: var(--neo-primary, #10B981);
}

/* 小图标按钮 (Neo-Noir 2.0) */
.btn-icon-sm {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--neo-icon-btn-sm, 32px);
  height: var(--neo-icon-btn-sm, 32px);
  border-radius: var(--neo-radius-xs, 8px);
  border: 1px solid var(--neo-border-subtle, rgba(255, 255, 255, 0.06));
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
  flex-shrink: 0;
}

.btn-icon-sm:hover {
  background: var(--neo-primary-dim, rgba(16, 185, 129, 0.12));
  border-color: var(--neo-border-focus, rgba(16, 185, 129, 0.3));
  color: var(--neo-primary, #10B981);
}

.btn-icon-sm:active {
  transform: scale(var(--neo-scale-press, 0.98));
}

/* 一键复制全部按钮 (Neo-Noir 2.0) */
.btn-copy-all {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--neo-space-2, 8px);
  width: 100%;
  padding: var(--neo-space-3, 12px);
  margin-top: var(--neo-space-1, 4px);
  background: var(--neo-primary-dim, rgba(16, 185, 129, 0.12));
  border: 1px solid var(--neo-border-focus, rgba(16, 185, 129, 0.25));
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-primary, #10B981);
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
}

.btn-copy-all:hover {
  background: rgba(16, 185, 129, 0.18);
  border-color: var(--neo-border-focus, rgba(16, 185, 129, 0.4));
}

.btn-copy-all:active {
  transform: scale(var(--neo-scale-press, 0.98));
}

/* 一键导入播放器按钮 (Neo-Noir 2.0) */
.btn-import-player {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--neo-space-2, 8px);
  width: 100%;
  padding: var(--neo-space-3, 12px);
  margin-top: var(--neo-space-2, 8px);
  background: var(--neo-bg-surface-2, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--neo-border-default, rgba(255, 255, 255, 0.12));
  border-radius: var(--neo-radius-sm, 12px);
  color: var(--neo-text-secondary, rgba(255, 255, 255, 0.7));
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  cursor: pointer;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
}

.btn-import-player:hover {
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.1));
  border-color: var(--neo-border-hover, rgba(255, 255, 255, 0.2));
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.9));
}

.btn-import-player:active {
  transform: scale(var(--neo-scale-press, 0.98));
}

/* 账号过期标签 */
.account-expired-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  margin-left: var(--neo-space-1, 4px);
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 4px;
  font-size: 10px;
  color: #ef4444;
  font-weight: 500;
}

/* ==================== 快捷网格 (Neo-Noir 2.0) ==================== */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--neo-space-3, 12px);
  margin-bottom: var(--neo-space-5, 20px);
}

.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--neo-space-2, 8px);
  padding: var(--neo-space-4, 16px);
  background: var(--neo-bg-surface-1, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--neo-border-default, rgba(255, 255, 255, 0.08));
  border-radius: var(--neo-radius-lg, 18px);
  text-decoration: none;
  transition: all var(--neo-duration-fast, 150ms) var(--neo-ease-default, cubic-bezier(0.4, 0, 0.2, 1));
  min-height: 90px;
}

.quick-item:active {
  transform: scale(var(--neo-scale-press, 0.98));
  background: var(--neo-bg-surface-hover, rgba(255, 255, 255, 0.08));
}

.quick-icon {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: var(--neo-radius-sm, 12px);
  background: var(--neo-primary-dim, rgba(16, 185, 129, 0.15));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neo-primary, #10B981);
}

.quick-label {
  font-size: var(--neo-font-size-sm, 12px);
  font-weight: var(--neo-font-weight-medium, 500);
  color: var(--neo-text-primary, rgba(255, 255, 255, 0.92));
}

.quick-value {
  font-size: var(--neo-font-size-xs, 11px);
  color: var(--neo-text-tertiary, rgba(255, 255, 255, 0.48));
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

/* ==================== 骨架屏 + 品牌脉冲圆环加载动画 ==================== */

/* 骨架屏视图容器 */
.skeleton-view {
  max-width: 600px;
  margin: 0 auto;
  padding: 1rem 1rem 1.5rem;
  animation: skeleton-fade-in 0.3s ease-out;
}

@keyframes skeleton-fade-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 骨架屏基础动画 - 微光扫过效果 */
@keyframes skeleton-shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

/* 骨架基础样式 */
.skeleton-bg {
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.03) 0%,
    rgba(255, 255, 255, 0.08) 50%,
    rgba(255, 255, 255, 0.03) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 6px;
}

/* 骨架卡片 */
.skeleton-card {
  background: rgba(26, 26, 26, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
  padding: 1rem;
  margin-bottom: 1rem;
}

/* 骨架头部 */
.skeleton-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.skeleton-greeting {
  width: 120px;
  height: 24px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.04) 0%,
    rgba(255, 255, 255, 0.1) 50%,
    rgba(255, 255, 255, 0.04) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 6px;
}

.skeleton-badge {
  width: 80px;
  height: 28px;
  background: linear-gradient(
    90deg,
    rgba(16, 185, 129, 0.1) 0%,
    rgba(16, 185, 129, 0.2) 50%,
    rgba(16, 185, 129, 0.1) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 9999px;
}

/* 骨架分割线 */
.skeleton-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.06);
  margin: 1rem 0;
}

/* 骨架 CTA 按钮 */
.skeleton-cta-button {
  width: 100%;
  height: 52px;
  background: linear-gradient(
    90deg,
    rgba(16, 185, 129, 0.15) 0%,
    rgba(16, 185, 129, 0.3) 50%,
    rgba(16, 185, 129, 0.15) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

/* CTA 按钮中心的品牌脉冲圆环 */
.skeleton-cta-button::after {
  content: '';
  position: absolute;
  width: 32px;
  height: 32px;
}

/* 品牌脉冲圆环 - 使用伪元素实现 */
.skeleton-cta-button::before {
  content: '';
  position: absolute;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 3px solid transparent;
  border-top-color: #10b981;
  border-right-color: #10b981;
  animation: brand-pulse-spin 0.8s linear infinite;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4);
}

/* 骨架次要链接 */
.skeleton-secondary-links {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 0.75rem;
}

.skeleton-secondary-links::before,
.skeleton-secondary-links::after {
  content: '';
  width: 50px;
  height: 14px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.03) 0%,
    rgba(255, 255, 255, 0.08) 50%,
    rgba(255, 255, 255, 0.03) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
}

/* 骨架账号预览 */
.skeleton-account-preview {
  width: 100%;
  max-width: 280px;
  margin: 0 auto;
  background: rgba(26, 26, 26, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.75rem;
  overflow: hidden;
}

.skeleton-preview-header {
  height: 36px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.03) 0%,
    rgba(255, 255, 255, 0.08) 50%,
    rgba(255, 255, 255, 0.03) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.skeleton-preview-body {
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.skeleton-preview-field {
  height: 36px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.02) 0%,
    rgba(255, 255, 255, 0.06) 50%,
    rgba(255, 255, 255, 0.02) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

/* 骨架流程指示器 */
.skeleton-stepper {
  opacity: 0.7;
}

.skeleton-step-dot {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.04) 0%,
    rgba(255, 255, 255, 0.1) 50%,
    rgba(255, 255, 255, 0.04) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border: 2px solid rgba(255, 255, 255, 0.08);
  margin: 0 auto 0.5rem;
}

.skeleton-step-label {
  width: 40px;
  height: 12px;
  margin: 0 auto;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.03) 0%,
    rgba(255, 255, 255, 0.08) 50%,
    rgba(255, 255, 255, 0.03) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
}

.skeleton-step-line {
  width: 2.5rem;
  height: 2px;
  background: rgba(255, 255, 255, 0.08);
  margin: 0 -0.25rem;
  margin-bottom: 1.125rem;
}

/* 骨架快捷网格 */
.skeleton-grid {
  opacity: 0.7;
}

.skeleton-quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  background: rgba(26, 26, 26, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.75rem;
  min-height: 90px;
}

.skeleton-quick-icon {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.5rem;
  background: linear-gradient(
    90deg,
    rgba(16, 185, 129, 0.1) 0%,
    rgba(16, 185, 129, 0.2) 50%,
    rgba(16, 185, 129, 0.1) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
}

.skeleton-quick-label {
  width: 60px;
  height: 14px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.04) 0%,
    rgba(255, 255, 255, 0.1) 50%,
    rgba(255, 255, 255, 0.04) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
}

/* ==================== 品牌脉冲圆环动画 ==================== */

/* 圆环旋转动画 */
@keyframes brand-pulse-spin {
  0% {
    transform: rotate(0deg);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(16, 185, 129, 0);
  }
  100% {
    transform: rotate(360deg);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  }
}

/* 品牌圆环呼吸光效 */
@keyframes brand-pulse-glow {
  0%, 100% {
    opacity: 1;
    filter: drop-shadow(0 0 4px rgba(16, 185, 129, 0.6));
  }
  50% {
    opacity: 0.8;
    filter: drop-shadow(0 0 12px rgba(16, 185, 129, 0.9));
  }
}

/* ==================== 骨架屏响应式 ==================== */
@media (max-width: 640px) {
  .skeleton-view {
    padding: 0.75rem 0.75rem 1rem;
  }

  .skeleton-stepper {
    padding: 0.75rem 0.5rem 1rem;
  }

  .skeleton-step-dot {
    width: 1.5rem;
    height: 1.5rem;
  }

  .skeleton-step-label {
    width: 36px;
    height: 10px;
  }

  .skeleton-step-line {
    width: 2rem;
  }

  .skeleton-greeting {
    width: 100px;
    height: 20px;
  }

  .skeleton-badge {
    width: 70px;
    height: 24px;
  }

  .skeleton-cta-button {
    height: 48px;
  }
}
</style>
