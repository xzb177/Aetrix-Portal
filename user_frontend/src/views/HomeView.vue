<script setup lang="ts">
/**
 * 首页 — 用户中心
 * 信息架构：媒体内容（续看）→ 账号速览 → 服务入口 → 公告/播放器导入（次要）
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { embyApi, messageApi, announcementApi, type AccountCard, type Announcement } from '@/api'
import { useToast } from '@/composables/useToast'
import MediaRow from '@/components/media/MediaRow.vue'
import { embyApi as protocolApi, type EmbyItem } from '@/api/emby'
import {
  Play, Copy, Check, RefreshCw, Key, Server, Lock, Eye,
  MessageSquare, Film, Shield, User, Inbox, LogOut, ChevronRight,
  Wallet, CalendarCheck, Gift, Sparkles, Megaphone, Tv, type LucideIcon,
} from 'lucide-vue-next'

const router = useRouter()
const userStore = useUserStore()
const toast = useToast()

const serverOrigin = window.location.origin

const loading = ref(true)
const account = ref<AccountCard | null>(null)
const notices = ref<Announcement[]>([])
const unreadCount = ref(0)
const resumeItems = ref<EmbyItem[]>([])

const copiedField = ref('')
const showPassword = ref(false)

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

const user = computed(() => userStore.user)
const embyUsername = computed(() => account.value?.emby_username || user.value?.username || '—')
const serverUrl = computed(() => account.value?.base_url || serverOrigin)
const hasPassword = computed(() => !!account.value?.has_password)
const importSchemes = computed(() => account.value?.import_schemes || {})
const hasSchemes = computed(() => Object.keys(importSchemes.value).length > 0)

async function copyText(text: string, field: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = field
    toast.success('已复制')
    setTimeout(() => { if (copiedField.value === field) copiedField.value = '' }, 1600)
  } catch {
    toast.error('复制失败')
  }
}

const copyAll = () => {
  const lines = [
    `服务器: ${serverUrl.value}`,
    `用户名: ${embyUsername.value}`,
    '密码: 与门户登录密码相同',
  ]
  copyText(lines.join('\n'), 'all')
}

// 播放器一键导入
const schemeIcons: Record<string, LucideIcon> = {}
const openScheme = (url: string) => {
  window.location.href = url
}

onMounted(async () => {
  try {
    const [card, unread, anns, resume] = await Promise.all([
      embyApi.getAccountCard(),
      messageApi.getUnreadCount().catch((): { unread_count: number } => ({ unread_count: 0 })),
      announcementApi.getAnnouncements().catch((): Announcement[] => []),
      protocolApi.getResume(12).catch((): EmbyItem[] => []),
    ])
    account.value = card
    unreadCount.value = (unread as any)?.unread_count ?? 0
    notices.value = Array.isArray(anns) ? anns : []
    resumeItems.value = resume
  } catch (err: any) {
    if (err?.response?.status !== 401) {
      toast.error('加载失败，请刷新重试')
    }
  } finally {
    loading.value = false
  }
})

async function refreshProfile() {
  loading.value = true
  try {
    account.value = await embyApi.getAccountCard()
  } catch {
    // 401 已由拦截器处理
  } finally {
    loading.value = false
  }
}

async function handleLogout() {
  await userStore.logout()
  router.push('/login')
}

const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
}
</script>

<template>
  <div class="home-view">
    <!-- Hero：问候 + 主行动 + 账号速览（合并原 hero 与连接信息卡） -->
    <section class="hero">
      <div class="hero-glow" aria-hidden="true"></div>
      <div class="container hero-grid">
        <div class="hero-left">
          <p class="hero-eyebrow">{{ greeting }}，欢迎回来</p>
          <h1 class="hero-title">{{ user?.username || '观影用户' }}</h1>
          <p class="hero-sub">
            门户账号即 Emby 账号 — 用同一组凭据登录任意客户端即可开始观影。
          </p>
          <div class="hero-actions">
            <RouterLink class="btn btn-primary" to="/media">
              <Play :size="16" />
              进入媒体库
            </RouterLink>
            <RouterLink class="btn btn-ghost" to="/request">
              <Film :size="16" />
              求片
            </RouterLink>
          </div>

          <!-- 账号速览行（连接信息压缩为三个可复制 chip） -->
          <div class="cred-strip" :class="{ loading }">
            <button
              v-for="row in [
                { key: 'server', label: '服务器', value: serverUrl, mono: true },
                { key: 'user', label: '用户名', value: embyUsername, mono: true },
                { key: 'pwd', label: '密码', value: hasPassword ? '与门户密码相同' : '未设置', mono: false },
              ]"
              :key="row.key"
              class="cred-chip"
              :title="`点击复制${row.label}`"
              @click="row.key !== 'pwd' && copyText(row.value, row.key)"
            >
              <span class="cred-chip-label">{{ row.label }}</span>
              <span class="cred-chip-value mono" :class="{ dim: row.key === 'pwd' }">{{ row.value }}</span>
              <Check v-if="copiedField === row.key" :size="13" class="chip-ok" />
              <Copy v-else-if="row.key !== 'pwd'" :size="13" class="chip-copy" />
              <Lock v-else :size="13" class="chip-copy" />
            </button>
          </div>
          <p class="cred-hint">
            <Key :size="12" />
            三个凭据均可在「个人中心」管理 ·
            <button class="hint-link" @click="copyAll">复制全部</button>
            <span v-if="hasPassword" class="hint-eye" @click="showPassword = !showPassword">
              <Eye v-if="showPassword" :size="12" />
              <Lock v-else :size="12" />
            </span>
          </p>
        </div>

        <!-- 右侧：公告卡片（合并原公告与消息） -->
        <aside v-if="notices.length || unreadCount > 0" class="hero-aside au-card">
          <header class="aside-head">
            <h2 class="aside-title">
              <Megaphone :size="15" />
              站点动态
            </h2>
            <RouterLink to="/messages" class="aside-link">
              全部
              <ChevronRight :size="13" />
            </RouterLink>
          </header>
          <ul class="notice-list">
            <li v-for="n in notices.slice(0, 3)" :key="n.id" class="notice-item">
              <span class="notice-dot"></span>
              <div class="notice-body">
                <p class="notice-title">{{ n.title }}</p>
                <p class="notice-meta">{{ fmtDate(n.created_at) }}</p>
              </div>
            </li>
          </ul>
          <RouterLink to="/messages" class="unread-row">
            <Inbox :size="15" />
            <span>消息中心</span>
            <span class="unread-pill" :class="{ hot: unreadCount > 0 }">
              {{ unreadCount > 0 ? `${unreadCount} 条未读` : '暂无未读' }}
            </span>
          </RouterLink>
        </aside>
      </div>
    </section>

    <main class="container main">
      <!-- 继续观看：绝对主视觉 -->
      <MediaRow v-if="resumeItems.length" title="继续观看" :items="resumeItems.slice(0, 12)" class="resume-row" />

      <!-- 服务网格：统一规格的入口卡（替代原先 7 张零散 quick-card + 独立公告卡） -->
      <section class="svc-section">
        <header class="svc-head">
          <h2 class="svc-title">我的服务</h2>
          <p class="svc-desc">签到赚积分 · 充值订阅 · 邀请返利 · 工单求片，都在这里</p>
        </header>
        <div class="svc-grid">
          <RouterLink v-for="svc in [
            { to: '/wallet', icon: Wallet, title: '我的钱包', desc: '余额 · 充值 · 订单', badge: '' },
            { to: '/checkin', icon: CalendarCheck, title: '每日签到', desc: '连签加成得积分', badge: '' },
            { to: '/invite', icon: Gift, title: '邀请返利', desc: '邀好友双方得奖', badge: '' },
            { to: '/messages', icon: Inbox, title: '消息通知', desc: '公告与私信', badge: unreadCount > 0 ? String(unreadCount > 99 ? '99+' : unreadCount) : '' },
            { to: '/tickets', icon: MessageSquare, title: '工单支持', desc: '遇到问题提交工单', badge: '' },
            { to: '/request', icon: Film, title: '求片', desc: '想看的片子告诉我们', badge: '' },
            { to: '/profile', icon: User, title: '个人中心', desc: '资料与安全设置', badge: '' },
          ]" :key="svc.to" :to="svc.to" class="svc-card">
            <div class="svc-icon">
              <component :is="svc.icon" :size="18" />
              <span v-if="svc.badge" class="svc-badge">{{ svc.badge }}</span>
            </div>
            <div class="svc-body">
              <span class="svc-name">{{ svc.title }}</span>
              <span class="svc-sub">{{ svc.desc }}</span>
            </div>
            <ChevronRight :size="15" class="svc-arrow" />
          </RouterLink>
        </div>
      </section>

      <!-- 次要区：播放器导入 + 退出（合并为一行，弱化视觉重量） -->
      <section v-if="hasSchemes" class="scheme-bar au-card">
        <div class="scheme-info">
          <Tv :size="16" />
          <div>
            <p class="scheme-title">一键导入播放器</p>
            <p class="scheme-desc">点击自动填充服务器与账号到客户端</p>
          </div>
        </div>
        <div class="scheme-grid">
          <button
            v-for="(url, name) in importSchemes"
            :key="name"
            class="scheme-btn"
            @click="openScheme(url)"
          >
            <Sparkles :size="14" />
            {{ name }}
          </button>
        </div>
      </section>

      <section class="footer-actions">
        <button class="btn btn-ghost danger" @click="handleLogout">
          <LogOut :size="15" />
          退出登录
        </button>
      </section>
    </main>
  </div>
</template>

<style scoped>
.home-view {
  min-height: 100vh;
  color: var(--au-text);
}

.container {
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 1.25rem;
}

/* ==================== Hero ==================== */

.hero {
  position: relative;
  padding: 3rem 0 2.25rem;
  border-bottom: 1px solid var(--au-border);
  overflow: hidden;
}

.hero-glow {
  position: absolute;
  top: -30%;
  right: -10%;
  width: 520px;
  height: 400px;
  background: radial-gradient(ellipse at center, rgba(34, 211, 238, 0.1) 0%, transparent 70%);
  filter: blur(52px);
  pointer-events: none;
}

.hero-grid {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 2.5rem;
  align-items: start;
}

.hero-eyebrow {
  font-size: 0.8125rem;
  color: var(--au-primary);
  margin: 0 0 0.5rem;
}

.hero-title {
  font-size: 1.875rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--au-text);
  margin: 0 0 0.625rem;
}

.hero-sub {
  font-size: 0.875rem;
  color: var(--au-text-3);
  max-width: 480px;
  line-height: 1.65;
  margin: 0 0 1.375rem;
}

.hero-actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 1.75rem;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  height: 40px;
  padding: 0 1.125rem;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
  border: none;
}

.btn-primary {
  background: linear-gradient(135deg, var(--au-primary), var(--au-primary-strong));
  color: #05141c;
  font-weight: 600;
  box-shadow: 0 4px 14px var(--au-primary-glow);
}

.btn-primary:hover {
  box-shadow: 0 6px 18px var(--au-primary-glow);
  transform: translateY(-1px);
}

.btn-ghost {
  background: var(--au-surface-2);
  color: var(--au-text-2);
  border: 1px solid var(--au-border);
}

.btn-ghost:hover {
  background: var(--au-surface-3);
  color: var(--au-text);
}

.btn-ghost.danger {
  color: var(--au-danger);
}

.btn-ghost.danger:hover {
  background: var(--au-danger-soft);
  border-color: rgba(251, 113, 133, 0.3);
}

/* 账号速览 chip 行 */
.cred-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  transition: opacity var(--au-fast) var(--au-ease);
}

.cred-strip.loading {
  opacity: 0.45;
  pointer-events: none;
}

.cred-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  max-width: 100%;
  height: 36px;
  padding: 0 0.75rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}

.cred-chip:hover {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
}

.cred-chip-label {
  flex-shrink: 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.cred-chip-value {
  font-size: 0.75rem;
  color: var(--au-text-2);
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cred-chip-value.dim {
  letter-spacing: 0.12em;
}

.chip-copy,
.chip-ok {
  flex-shrink: 0;
  color: var(--au-text-4);
}

.cred-chip:hover .chip-copy {
  color: var(--au-primary);
}

.chip-ok {
  color: var(--au-primary);
}

.cred-hint {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin: 0.75rem 0 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.hint-link {
  background: none;
  border: none;
  padding: 0;
  font-size: inherit;
  color: var(--au-primary);
  cursor: pointer;
}

.hint-link:hover {
  text-decoration: underline;
}

.hint-eye {
  display: inline-flex;
  color: var(--au-text-4);
  cursor: pointer;
}

.hint-eye:hover {
  color: var(--au-primary);
}

/* ==================== Hero 侧栏（站点动态） ==================== */

.hero-aside {
  padding: 1.125rem 1.125rem 0.875rem;
}

.aside-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.875rem;
}

.aside-title {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  margin: 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--au-text);
}

.aside-title svg {
  color: var(--au-primary);
}

.aside-link {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  font-size: 0.75rem;
  color: var(--au-text-4);
  text-decoration: none;
  transition: color var(--au-fast) var(--au-ease);
}

.aside-link:hover {
  color: var(--au-primary);
}

.notice-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.notice-item {
  display: flex;
  gap: 0.625rem;
  align-items: flex-start;
}

.notice-dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  margin-top: 0.4375rem;
  border-radius: 50%;
  background: var(--au-primary);
}

.notice-body {
  min-width: 0;
}

.notice-title {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--au-text-2);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.notice-meta {
  margin: 0.125rem 0 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.unread-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.875rem;
  padding: 0.625rem 0.75rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: 10px;
  color: var(--au-text-2);
  font-size: 0.8125rem;
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease);
}

.unread-row:hover {
  border-color: var(--au-primary-border);
}

.unread-pill {
  margin-left: auto;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.unread-pill.hot {
  padding: 0.125rem 0.5rem;
  background: var(--au-warning-soft);
  color: var(--au-warning);
  border-radius: var(--au-r-full);
  font-weight: 600;
}

/* ==================== 主体 ==================== */

.main {
  padding: 2rem 1.25rem 3rem;
}

.resume-row {
  margin-bottom: 2.25rem;
}

/* 服务网格 */

.svc-section {
  margin-bottom: 2rem;
}

.svc-head {
  margin-bottom: 1rem;
}

.svc-title {
  margin: 0 0 0.25rem;
  font-size: 1.0625rem;
  font-weight: 600;
  color: var(--au-text);
}

.svc-desc {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--au-text-4);
}

.svc-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
}

.svc-card {
  display: flex;
  align-items: center;
  gap: 0.6875rem;
  padding: 0.9375rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease), transform var(--au-fast) var(--au-ease);
}

.svc-card:hover {
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
  transform: translateY(-2px);
}

.svc-icon {
  position: relative;
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: 10px;
  color: var(--au-primary);
}

.svc-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-warning);
  color: #1c1917;
  font-size: 0.5625rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

.svc-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.svc-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text);
}

.svc-sub {
  margin-top: 0.125rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.svc-arrow {
  flex-shrink: 0;
  margin-left: auto;
  color: var(--au-text-4);
  opacity: 0;
  transform: translateX(-3px);
  transition: all var(--au-fast) var(--au-ease);
}

.svc-card:hover .svc-arrow {
  opacity: 1;
  transform: translateX(0);
  color: var(--au-primary);
}

/* ==================== 播放器导入条 ==================== */

.scheme-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.25rem;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}

.scheme-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  color: var(--au-primary);
}

.scheme-title {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text);
}

.scheme-desc {
  margin: 0.125rem 0 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.scheme-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.scheme-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  height: 34px;
  padding: 0 0.875rem;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-sm);
  color: var(--au-text-2);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.scheme-btn:hover {
  background: var(--au-primary-soft);
  border-color: var(--au-primary-border);
  color: var(--au-primary);
}

/* ==================== 底部 ==================== */

.footer-actions {
  display: flex;
  justify-content: center;
  padding: 0.5rem 0 0;
}

@media (max-width: 960px) {
  .hero-grid {
    grid-template-columns: 1fr;
    gap: 2rem;
  }

  .hero-aside {
    max-width: 480px;
  }
}

@media (max-width: 760px) {
  .svc-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .hero {
    padding: 2.25rem 0 1.875rem;
  }

  .hero-title {
    font-size: 1.5rem;
  }

  .svc-grid {
    grid-template-columns: 1fr;
  }

  .scheme-bar {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
