<script setup lang="ts">
/**
 * 个人中心 — 简化版
 *
 * 功能：账号信息、修改密码、Emby 播放密码、退出登录。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  authApi, embyApi, messageApi, subscriptionApi,
  type AuthUser, type AccountCard, type MySubscription, type WatchStats,
} from '@/api'
import {
  deviceApi, inviteApi,
  type MyDevice, type MyDevicesResponse, type MyInviteInfo,
} from '@/api/economy'
import { useToast } from '@/composables/useToast'
import {
  User, Lock, KeyRound, LogOut, ShieldCheck, RefreshCw, Eye, EyeOff, Copy, Check, Film,
  Play, History, Crown, Heart, Sparkles, MonitorSmartphone,
  Clapperboard, Search, Wallet, CalendarCheck, Gift, Inbox, Ticket,
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
// 功能入口里的“状态”字样：未读条数 / 邀请开关与已邀请人数
const unreadCount = ref(0)
const inviteEnabled = ref<boolean | null>(null)
const invitedCount = ref(0)

/**
 * 功能入口（个人中心同时是「功能地图」）
 *
 * 用户端的页面已经不少（媒体库 / 搜索 / 收藏 / 观看记录 / 钱包 / 签到 / 邀请 /
 * 消息 / 求片 / 工单），此前只在顶栏分组（桌面）与 ☰ 抽屉（移动端）里各有一次入口，
 * 个人中心只列了四个，结果就是「邀请返利明明做了，用户却在用户端找不到」。
 * 这里按用途分三组列全，每个入口带一句说明，点一次就到。
 */
const featureGroups = computed(() => [
  {
    title: '内容',
    items: [
      { to: '/media', icon: Clapperboard, label: '媒体库', hint: '全部影片与剧集' },
      { to: '/search', icon: Search, label: '搜索片名', hint: '跨库检索' },
      { to: '/favorites', icon: Heart, label: '我的收藏', hint: '收藏过的条目' },
      { to: '/history', icon: History, label: '观看记录', hint: '进度与正在播放' },
    ],
  },
  {
    title: '经济与奖励',
    items: [
      { to: '/wallet', icon: Wallet, label: '钱包与订阅', hint: '积分 · 兑换 · 订单' },
      { to: '/checkin', icon: CalendarCheck, label: '每日签到', hint: '签到领积分' },
      {
        to: '/invite',
        icon: Gift,
        label: '邀请返利',
        hint: inviteEnabled.value === false
          ? '管理员暂未开启'
          : invitedCount.value > 0
            ? `已邀请 ${invitedCount.value} 位好友`
            : '邀请好友双向得积分',
        alert: inviteEnabled.value === false,
      },
    ],
  },
  {
    title: '互动与支持',
    items: [
      {
        to: '/messages',
        icon: Inbox,
        label: '消息中心',
        hint: unreadCount.value > 0 ? `${unreadCount.value} 条未读` : '工单 / 求片 / 会员提醒',
        alert: unreadCount.value > 0,
      },
      { to: '/request', icon: Film, label: '求片中心', hint: '想看什么就在这提' },
      { to: '/tickets', icon: Ticket, label: '工单支持', hint: '问题与回复记录' },
    ],
  },
])

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

// 播放器一键导入（服务器地址 / 账号 信息集中在本页，首页不再重复）
const importSchemes = computed(() => account.value?.import_schemes || {})
const hasSchemes = computed(() => Object.keys(importSchemes.value).length > 0)

// ===== 多服：我在这几个服各自的地址与会员（一个服一个会员）=====
const realmCards = computed(() => account.value?.realms || [])

function daysLeft(end?: string | null): number {
  if (!end) return 0
  const diff = new Date(end).getTime() - Date.now()
  return diff > 0 ? Math.ceil(diff / 86400000) : 0
}
function openScheme(url: string) {
  window.location.href = url
}

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

// ===== 我的设备（第三方播放器登录设备）=====
// 设备上限由管理端配置；这里让用户自助查看与清理，避免顶到上限后无法登录
const devices = ref<MyDevice[]>([])
const deviceInfo = ref<MyDevicesResponse | null>(null)
const deviceLoading = ref(false)
const removingDevice = ref('')
const pendingRemove = ref('')

async function loadDevices() {
  deviceLoading.value = true
  try {
    const res = await deviceApi.mine()
    devices.value = res.devices
    deviceInfo.value = res
  } catch {
    // 静默：设备卡加载失败不影响页面
  } finally {
    deviceLoading.value = false
  }
}

async function handleRemoveDevice(device: MyDevice) {
  if (pendingRemove.value !== device.device_id) {
    pendingRemove.value = device.device_id
    window.setTimeout(() => {
      if (pendingRemove.value === device.device_id) pendingRemove.value = ''
    }, 4000)
    return
  }
  pendingRemove.value = ''
  removingDevice.value = device.device_id
  try {
    const res = await deviceApi.remove(device.device_id)
    toast.success(res.message || '设备已移除')
    await loadDevices()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '移除失败，请稍后重试')
  } finally {
    removingDevice.value = ''
  }
}

function deviceAgo(iso?: string | null, isBlocked = false) {
  if (isBlocked) return '已禁用'
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(diff) || diff < 0) return '刚刚'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
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
  loadDevices()
  loadHubHints()
})

/** 功能入口上的状态字样（未读数 / 邀请开关）——单独发，失败不影响页面 */
async function loadHubHints() {
  const [unread, invite] = await Promise.all([
    messageApi.getUnreadCount().catch((): { unread_count: number } | null => null),
    inviteApi.myCode().catch((): MyInviteInfo | null => null),
  ])
  if (unread) unreadCount.value = unread.unread_count ?? 0
  if (invite) {
    inviteEnabled.value = invite.config?.enabled !== false
    invitedCount.value = invite.invited_count ?? 0
  }
}

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
    <div class="container is-narrow">
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

      <!-- 功能入口：用户端全部页面的地图（按用途分组） -->
      <section class="hub">
        <div v-for="group in featureGroups" :key="group.title" class="hub-group">
          <h2 class="hub-group-title">{{ group.title }}</h2>
          <div class="hub-grid">
            <RouterLink
              v-for="item in group.items"
              :key="item.to"
              :to="item.to"
              class="hub-tile"
              :class="{ alert: item.alert }"
            >
              <span class="hub-ic"><component :is="item.icon" :size="17" /></span>
              <span class="hub-text">
                <span class="hub-label">{{ item.label }}</span>
                <span class="hub-hint">{{ item.hint }}</span>
              </span>
            </RouterLink>
          </div>
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

        <!-- 多服：每个服一个地址与一份会员（没订阅的服后端不下发） -->
        <div v-if="realmCards.length > 1" class="realm-row">
          <span class="scheme-label">我的服</span>
          <div class="realm-list">
            <div v-for="r in realmCards" :key="r.id" class="realm-item">
              <div class="realm-head">
                <strong>{{ r.name }}</strong>
                <span v-if="r.subscribed" class="realm-badge ok">会员剩 {{ daysLeft(r.end_date) }} 天</span>
                <span v-else class="realm-badge off">未开通</span>
              </div>
              <div class="realm-url">
                <span class="mono">{{ r.base_url || '管理员还没填这个服的地址' }}</span>
                <button v-if="r.base_url" class="copy-btn" @click="copyText(r.base_url, `realm-${r.id}`)">
                  <Check v-if="copiedField === `realm-${r.id}`" :size="13" class="ok" />
                  <Copy v-else :size="13" />
                </button>
              </div>
            </div>
          </div>
          <p class="card-tip">
            一个面板下可以同时有几个「服」：会员一个服一个，在哪个服开的会员就连哪个服的地址播放。
          </p>
        </div>

        <div v-if="hasSchemes" class="scheme-row">
          <span class="scheme-label">一键导入到客户端</span>
          <div class="scheme-btns">
            <button
              v-for="(url, name) in importSchemes"
              :key="name"
              class="scheme-btn"
              @click="openScheme(url)"
            >
              <Sparkles :size="13" />
              {{ name }}
            </button>
          </div>
        </div>

        <p class="card-tip">
          播放密码用于 Emby 客户端登录，与门户密码相互独立；也可用上方按钮一键导入。
        </p>
      </section>

      <!-- 我的设备：第三方播放器登录设备自助管理 -->
      <section class="card">
        <header class="card-head">
          <h2 class="card-title">
            <MonitorSmartphone :size="17" />
            我的设备
            <span v-if="deviceInfo && deviceInfo.limit" class="dev-count">
              {{ deviceInfo.active_count }} / {{ deviceInfo.limit }}
            </span>
          </h2>
          <button class="icon-btn" title="刷新" @click="loadDevices">
            <RefreshCw :size="15" :class="{ spinning: deviceLoading }" />
          </button>
        </header>

        <div v-if="devices.length === 0" class="dev-empty">
          还没有客户端登录记录。用 Emby 客户端（Infuse / Forward 等）登录后会出现在这里。
        </div>
        <template v-else>
          <div v-for="d in devices" :key="d.device_id" class="dev-row">
            <div class="dev-main">
              <span class="dev-name">{{ d.name || '未命名设备' }}</span>
              <span class="dev-meta">
                {{ d.client || '未知客户端' }}
                <template v-if="d.app_version"> v{{ d.app_version }}</template>
                · {{ deviceAgo(d.last_seen_at, d.is_blocked) }}
                <template v-if="d.ip"> · {{ d.ip }}</template>
              </span>
            </div>
            <span v-if="d.is_blocked" class="dev-badge off">已禁用</span>
            <span v-else-if="!d.is_online_recent" class="dev-badge idle">已闲置</span>
            <span v-else class="dev-badge ok">活跃</span>
            <button
              class="text-btn danger"
              :class="{ confirming: pendingRemove === d.device_id }"
              :disabled="removingDevice === d.device_id"
              @click="handleRemoveDevice(d)"
            >
              {{ pendingRemove === d.device_id ? '确认移除' : '移除' }}
            </button>
          </div>
        </template>

        <p class="card-tip">
          <template v-if="deviceInfo && deviceInfo.limit">
            账号最多同时使用 {{ deviceInfo.limit }} 台设备（近 {{ deviceInfo.active_days }} 天内登录过）。
            {{ deviceInfo.auto_evict ? '超限时会自动停用最久未用的设备。' : '超限时请先移除不再使用的设备。' }}
          </template>
          <template v-else>移除后该设备登录状态立即失效，需重新输入账号密码。</template>
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
            <span>{{ s.plan_name }}<em v-if="s.realm_name" class="sub-realm">（{{ s.realm_name }}）</em></span>
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
          <!-- 管理员：直达管理后台。门户与后台同源、同一套 JWT，后台会自动接管当前登录态，
               所以这里是一次登录两端通行的入口，不再要求二次登录 -->
          <a v-if="userStore.user?.is_staff" href="/admin/" class="list-item">
            <ShieldCheck :size="16" class="list-icon" />
            <span class="list-text">管理后台</span>
            <span class="list-arrow">›</span>
          </a>
          <button class="list-item danger" @click="handleLogout">
            <LogOut :size="16" class="list-icon" />
            <span class="list-text">退出登录</span>
            <span class="list-arrow">›</span>
          </button>
        </div>
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
  background: #070b12;
  color: #e5e7eb;
  padding-bottom: 3rem;
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
  background: rgba(34, 211, 238, 0.12);
  border: 1px solid rgba(34, 211, 238, 0.25);
  color: #22d3ee;
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
  color: #22d3ee;
}

.card-tip {
  margin: 0.875rem 0 0;
  padding-top: 0.875rem;
  border-top: 1px dashed rgba(255, 255, 255, 0.08);
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.35);
  line-height: 1.5;
}

/* 我的设备 */
.dev-count {
  margin-left: 0.5rem;
  padding: 0.0625rem 0.4375rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.07);
  font-size: 0.6875rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.55);
}

.dev-empty {
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.6;
}

.dev-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 0;
}

.dev-row + .dev-row {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.dev-main {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
  flex: 1;
}

.dev-name {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dev-meta {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
}

.dev-badge {
  flex-shrink: 0;
  padding: 0.0625rem 0.5rem;
  border-radius: 999px;
  font-size: 0.6875rem;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.5);
}

.dev-badge.ok {
  background: var(--au-success-soft);
  color: var(--au-success);
}

.dev-badge.idle {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.45);
}

.dev-badge.off {
  background: var(--au-danger-soft);
  color: var(--au-danger);
}

.text-btn.danger {
  color: rgba(251, 113, 133, 0.85);
}

.text-btn.danger.confirming {
  color: var(--au-danger);
  font-weight: 600;
}

/* 多服：一个服一个地址与会员 */
.realm-row {
  margin-top: 0.875rem;
  padding-top: 0.875rem;
  border-top: 1px dashed rgba(255, 255, 255, 0.08);
}

.realm-list { display: flex; flex-direction: column; gap: 0.5rem; }

.realm-item {
  padding: 0.5rem 0.6875rem;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-sm);
}

.realm-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
  color: var(--au-text-2);
}

.realm-head strong { color: var(--au-text); }

.realm-badge {
  font-size: 0.625rem;
  border-radius: 999px;
  padding: 0.0625rem 0.5rem;
}

.realm-badge.ok { background: var(--au-primary-soft); color: var(--au-primary); }
.realm-badge.off { background: rgba(255, 255, 255, 0.06); color: var(--au-text-4); }

.realm-url {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.25rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  word-break: break-all;
}

.realm-url .mono { flex: 1; }

.sub-realm { font-style: normal; color: var(--au-text-4); font-size: 0.6875rem; }

/* 一键导入到客户端 */
.scheme-row {
  margin-top: 0.875rem;
  padding-top: 0.875rem;
  border-top: 1px dashed rgba(255, 255, 255, 0.08);
}

.scheme-label {
  display: block;
  margin-bottom: 0.5rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.scheme-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.scheme-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  height: 32px;
  padding: 0 0.8125rem;
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
  color: #22d3ee;
}

.text-btn {
  flex-shrink: 0;
  background: transparent;
  border: none;
  color: #22d3ee;
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
  /* 同一套样式同时用于 button 与 a（管理员入口） */
  text-decoration: none;
  width: 100%;
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
  color: #22d3ee;
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
  color: rgba(34, 211, 238, 0.6);
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
  background: rgba(34, 211, 238, 0.08);
  border: 1px solid rgba(34, 211, 238, 0.25);
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
  color: #22d3ee;
  background: rgba(34, 211, 238, 0.15);
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
  color: #22d3ee;
  background: rgba(34, 211, 238, 0.12);
}

.sub-status.off {
  color: rgba(255, 255, 255, 0.35);
  background: rgba(255, 255, 255, 0.06);
}

/* 链接卡 */
/* 功能入口：分组标题 + 自适应磁贴（窄屏两列，宽屏自动铺开） */
.hub {
  display: flex;
  flex-direction: column;
  gap: 1.125rem;
  margin-bottom: 1.25rem;
}

.hub-group-title {
  margin: 0 0 0.5rem 0.125rem;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--au-text-4);
}

.hub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.5rem;
}

.hub-tile {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.6875rem 0.75rem;
  min-width: 0;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  text-decoration: none;
  transition: background-color var(--au-fast) var(--au-ease),
              border-color var(--au-fast) var(--au-ease),
              transform var(--au-fast) var(--au-ease);
}

.hub-tile:hover {
  background: var(--au-surface-2);
  border-color: var(--au-border-strong);
  transform: translateY(-1px);
}

.hub-tile:active {
  transform: none;
}

.hub-tile:focus-visible {
  outline: 2px solid var(--au-primary);
  outline-offset: 2px;
}

.hub-ic {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: var(--au-r-sm);
  background: var(--au-primary-soft);
  color: var(--au-primary);
}

.hub-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.hub-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text);
}

.hub-hint {
  font-size: 0.6875rem;
  color: var(--au-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 未读 / 未开启：图标底色退到中性，不抢主色 */
.hub-tile.alert .hub-ic {
  background: var(--au-surface-3);
  color: var(--au-text-3);
}

.hub-tile.alert .hub-hint {
  color: var(--au-warning);
}

@media (hover: none) {
  .hub-tile:hover {
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hub-tile {
    transition: none;
  }
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
  border-color: rgba(34, 211, 238, 0.6);
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
  background: var(--au-gradient);
  color: #05141c;   /* 青底配白字只有 1.9:1，与全站主按钮统一为深墨色文字 */
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
