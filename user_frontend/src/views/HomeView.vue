<script setup lang="ts">
/**
 * 首页 — 用户中心
 * 自建 Emby 统一后端（portal 账号即 Emby 账号）。
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
  MessageSquare, Film, Shield, User, Inbox, LogOut, type LucideIcon,
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
</script>

<template>
  <div class="home-view">
    <!-- Hero -->
    <section class="hero">
      <div class="hero-glow" aria-hidden="true"></div>
      <div class="container">
        <div class="hero-row">
          <div class="hero-left">
            <p class="hero-eyebrow">{{ greeting }}，欢迎回来</p>
            <h1 class="hero-title">{{ user?.username || '观影用户' }}</h1>
            <p class="hero-sub">
              你的门户账号即 Emby 账号 — 用同一组凭据登录任意客户端即可开始观影。
            </p>
            <div class="hero-actions">
              <RouterLink class="btn btn-primary" to="/media">
                <Play :size="16" />
                进入媒体库
              </RouterLink>
              <RouterLink class="btn btn-ghost" to="/requests">
                <Film :size="16" />
                求片
              </RouterLink>
            </div>
          </div>
          <div class="hero-badges">
            <div class="badge-item">
              <Shield :size="15" />
              <span>JWT 安全认证</span>
            </div>
            <div class="badge-item">
              <Server :size="15" />
              <span>自建 Emby 服务</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <main class="container main">
      <!-- 继续观看 -->
      <MediaRow v-if="resumeItems.length" title="继续观看" :items="resumeItems.slice(0, 12)" class="resume-row" />

      <section class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title">
              <Key :size="17" />
              Emby 连接信息
            </h2>
            <p class="card-desc">以下凭据与你的门户账号一致，适用于所有 Emby 客户端</p>
          </div>
          <button class="icon-btn" title="刷新" @click="refreshProfile">
            <RefreshCw :size="15" :class="{ spinning: loading }" />
          </button>
        </header>

        <div class="cred-grid" :class="{ loading }">
          <div class="cred-row">
            <span class="cred-label">服务器地址</span>
            <span class="cred-value mono">{{ serverUrl }}</span>
            <button class="copy-btn" title="复制" @click="copyText(serverUrl, 'server')">
              <Check v-if="copiedField === 'server'" :size="14" class="ok" />
              <Copy v-else :size="14" />
            </button>
          </div>
          <div class="cred-row">
            <span class="cred-label">用户名</span>
            <span class="cred-value mono">{{ embyUsername }}</span>
            <button class="copy-btn" title="复制" @click="copyText(embyUsername, 'user')">
              <Check v-if="copiedField === 'user'" :size="14" class="ok" />
              <Copy v-else :size="14" />
            </button>
          </div>
          <div class="cred-row">
            <span class="cred-label">密码</span>
            <span class="cred-value mono">
              <template v-if="hasPassword">
                {{ showPassword ? '与门户密码相同' : '••••••••' }}
              </template>
              <template v-else>未设置</template>
            </span>
            <button class="copy-btn" title="显示状态" @click="showPassword = !showPassword">
              <Eye v-if="showPassword" :size="14" />
              <Lock v-else :size="14" />
            </button>
            <button v-if="hasPassword" class="copy-btn" title="复制全部" @click="copyAll">
              <Check v-if="copiedField === 'all'" :size="14" class="ok" />
              <Copy v-else :size="14" />
            </button>
          </div>
        </div>

        <div class="cred-foot">
          <Lock :size="13" />
          <span>密码与门户登录密码相同，可在「个人中心」修改</span>
          <RouterLink to="/profile" class="link">修改密码 →</RouterLink>
        </div>
      </section>

      <section class="quick-grid">
        <RouterLink to="/messages" class="quick-card">
          <div class="quick-icon" :class="{ 'has-unread': unreadCount > 0 }">
            <Inbox :size="18" />
          </div>
          <div class="quick-body">
            <span class="quick-title">消息通知</span>
            <span class="quick-desc">
              {{ unreadCount > 0 ? `${unreadCount} 条未读` : '暂无未读' }}
            </span>
          </div>
          <span v-if="unreadCount > 0" class="dot-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
        </RouterLink>

        <RouterLink to="/tickets" class="quick-card">
          <div class="quick-icon">
            <MessageSquare :size="18" />
          </div>
          <div class="quick-body">
            <span class="quick-title">工单支持</span>
            <span class="quick-desc">遇到问题？提交工单</span>
          </div>
        </RouterLink>

        <RouterLink to="/requests" class="quick-card">
          <div class="quick-icon">
            <Film :size="18" />
          </div>
          <div class="quick-body">
            <span class="quick-title">求片</span>
            <span class="quick-desc">想看的片子告诉我们</span>
          </div>
        </RouterLink>

        <RouterLink to="/profile" class="quick-card">
          <div class="quick-icon">
            <User :size="18" />
          </div>
          <div class="quick-body">
            <span class="quick-title">个人中心</span>
            <span class="quick-desc">资料与安全设置</span>
          </div>
        </RouterLink>
      </section>

      <section v-if="notices.length" class="card">
        <header class="card-head">
          <h2 class="card-title">
            <Inbox :size="17" />
            最新公告
          </h2>
        </header>
        <ul class="notice-list">
          <li v-for="n in notices.slice(0, 3)" :key="n.id" class="notice-item">
            <span class="notice-dot"></span>
            <div class="notice-body">
              <p class="notice-title">{{ n.title }}</p>
              <p class="notice-meta">{{ new Date(n.created_at).toLocaleDateString() }}</p>
            </div>
          </li>
        </ul>
        <RouterLink to="/messages" class="link notice-more">查看全部 →</RouterLink>
      </section>

      <!-- 一键导入播放器 -->
      <section v-if="Object.keys(importSchemes).length" class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title">
              <Server :size="17" />
              一键导入播放器
            </h2>
            <p class="card-desc">点击自动填充服务器与账号信息到对应客户端</p>
          </div>
        </header>
        <div class="scheme-grid">
          <button
            v-for="(url, name) in importSchemes"
            :key="name"
            class="scheme-btn"
            @click="openScheme(url)"
          >
            <component :is="schemeIcons[name as string] || Play" :size="15" />
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
  background: #05070a;
  color: #e5e7eb;
}

.container {
  max-width: 880px;
  margin: 0 auto;
  padding: 0 1.25rem;
}

.hero {
  position: relative;
  padding: 3.5rem 0 2.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
}

.hero-glow {
  position: absolute;
  top: -30%;
  right: -10%;
  width: 480px;
  height: 380px;
  background: radial-gradient(ellipse at center, rgba(16, 185, 129, 0.1) 0%, transparent 70%);
  filter: blur(48px);
  pointer-events: none;
}

.hero-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1.5rem;
  flex-wrap: wrap;
}

.hero-eyebrow {
  font-size: 0.8125rem;
  color: #10b981;
  margin: 0 0 0.5rem;
}

.hero-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: #fafafa;
  margin: 0 0 0.625rem;
}

.hero-sub {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.5);
  max-width: 440px;
  line-height: 1.6;
  margin: 0 0 1.25rem;
}

.hero-actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
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
  transition: all 0.2s ease;
  border: none;
}

.btn-primary {
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
  box-shadow: 0 4px 14px rgba(16, 185, 129, 0.25);
}

.btn-primary:hover {
  box-shadow: 0 6px 18px rgba(16, 185, 129, 0.35);
}

.btn-ghost {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.09);
  color: #fff;
}

.btn-ghost.danger {
  color: #f87171;
}

.btn-ghost.danger:hover {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.25);
}

.hero-badges {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.badge-item {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4375rem 0.75rem;
  background: rgba(16, 185, 129, 0.06);
  border: 1px solid rgba(16, 185, 129, 0.18);
  border-radius: 9px;
  color: rgba(16, 185, 129, 0.85);
  font-size: 0.75rem;
}

.main {
  padding: 2rem 1.25rem 3rem;
}

.resume-row {
  margin-bottom: 2rem;
}

.card {
  background: rgba(13, 18, 24, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 16px;
  padding: 1.375rem;
  margin-bottom: 1.25rem;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
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

.card-desc {
  margin: 0.375rem 0 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.42);
}

.icon-btn {
  flex-shrink: 0;
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
  background: rgba(255, 255, 255, 0.09);
  color: #fff;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.cred-grid {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  transition: opacity 0.2s ease;
}

.cred-grid.loading {
  opacity: 0.45;
  pointer-events: none;
}

.cred-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6875rem 0.875rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 11px;
}

.cred-label {
  flex-shrink: 0;
  width: 76px;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.45);
}

.cred-value {
  flex: 1;
  min-width: 0;
  font-size: 0.8125rem;
  color: #e5e7eb;
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
  transition: all 0.15s ease;
}

.copy-btn:hover {
  background: rgba(255, 255, 255, 0.07);
  color: #fff;
}

.copy-btn .ok {
  color: #10b981;
}

.cred-foot {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  margin-top: 1rem;
  padding-top: 0.875rem;
  border-top: 1px dashed rgba(255, 255, 255, 0.08);
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.35);
}

.cred-foot .link {
  margin-left: auto;
}

.link {
  color: #10b981;
  text-decoration: none;
  font-size: 0.8125rem;
  white-space: nowrap;
}

.link:hover {
  text-decoration: underline;
}

/* 一键导入播放器 */
.scheme-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.scheme-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  height: 36px;
  padding: 0 0.875rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.scheme-btn:hover {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}

.quick-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  background: rgba(13, 18, 24, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 14px;
  text-decoration: none;
  transition: border-color 0.2s ease, transform 0.2s ease, background 0.2s ease;
}

.quick-card:hover {
  border-color: rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.03);
  transform: translateY(-2px);
}

.quick-icon {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 11px;
  color: #10b981;
}

.quick-icon.has-unread {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.3);
  color: #f59e0b;
}

.quick-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.quick-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: #fafafa;
}

.quick-desc {
  margin-top: 0.1875rem;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dot-badge {
  position: absolute;
  top: 0.625rem;
  right: 0.625rem;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f59e0b;
  color: #1c1917;
  font-size: 0.625rem;
  font-weight: 700;
  border-radius: 9px;
}

.notice-list {
  list-style: none;
  margin: 0 0 0.875rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
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
  background: #10b981;
}

.notice-body {
  min-width: 0;
}

.notice-title {
  margin: 0;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.85);
  line-height: 1.45;
}

.notice-meta {
  margin: 0.125rem 0 0;
  font-size: 0.6875rem;
  color: rgba(255, 255, 255, 0.3);
}

.notice-more {
  display: inline-block;
}

.footer-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 0.5rem;
}

@media (max-width: 640px) {
  .hero {
    padding: 2.5rem 0 2rem;
  }

  .hero-title {
    font-size: 1.5rem;
  }

  .quick-grid {
    grid-template-columns: 1fr;
  }

  .cred-label {
    width: 64px;
  }
}
</style>
