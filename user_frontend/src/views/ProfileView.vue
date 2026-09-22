<script setup lang="ts">
/**
 * 个人中心 — 账号页（v2.6.30 重设；v2.10.0 加入「正在播放」）
 *
 * 这里只放「账号自身」的事：身份卡（用户名 / 邮箱 / 注册时间 / 观看数据）、
 * Emby 账号（服务器地址 / 播放密码 / 多服 / 一键导入）、我的订阅、我的设备、
 * 正在播放（远程控制播放会话）、安全设置。
 *
 * 页面上不再铺功能磁贴：个人中心不是功能地图。全站入口由一份导航定义承担
 * （src/config/navigation.ts）——桌面在顶栏，低频入口在头像菜单，
 * 「个人中心 = 一堆按钮」的观感就此结束。
 *
 * 「正在播放」为什么在这里：它讲的是**控制**（哪台设备在放、能不能停），
 * 不是「我看过什么」——后者留在媒体库的观看记录分段。v2.10.0 从观看记录页迁过来。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  authApi, embyApi, subscriptionApi, isExpiringSoon,
  type AuthUser, type AccountCard, type AccountRealmCard, type MySubscription, type WatchStats,
} from '@/api'
import { deviceApi, type MyDevice, type MyDevicesResponse } from '@/api/economy'
import { useToast } from '@/composables/useToast'
import PlaybackSessions from '@/components/media/PlaybackSessions.vue'
import {
  Mail, CalendarDays, Crown, Lock, KeyRound, LogOut, RefreshCw,
  Eye, EyeOff, Copy, Check, Sparkles, MonitorSmartphone, ChevronRight, TriangleAlert,
  MonitorPlay,
} from 'lucide-vue-next'

const router = useRouter()
const userStore = useUserStore()
const toast = useToast()

const user = computed(() => userStore.user as AuthUser | null)

// 身份卡上的首字母头像：比一个通用小人图标更像「我的账号」
const initial = computed(() => (user.value?.username || 'U').charAt(0).toUpperCase())

// ===== 数据 =====
const loading = ref(true)
const account = ref<AccountCard | null>(null)
const stats = ref<WatchStats | null>(null)
const subscriptions = ref<MySubscription[]>([])

const activeSub = computed(() => subscriptions.value.find(s => s.status === 'active' && s.days_left > 0) || null)
// 临期：与后台到期提醒同口径（默认 7 天），续费入口就在钱包页
const expiringSoon = computed(() => isExpiringSoon(activeSub.value))
const watchHours = computed(() => {
  if (!stats.value) return '—'
  const h = Math.floor(stats.value.total_seconds / 3600)
  return h >= 1 ? `${h} 小时` : `${Math.floor(stats.value.total_seconds / 60)} 分钟`
})

const copiedField = ref('')
const showPlayPassword = ref(false)

const embyUsername = computed(() => account.value?.emby_username || user.value?.emby_username || user.value?.username || '—')
const serverUrl = computed(() => account.value?.base_url || window.location.origin)
const hasPlayPassword = computed(() => !!account.value?.has_password)

// 播放器一键导入（服务器地址 / 账号信息集中在本页，首页不再重复）
const importSchemes = computed(() => account.value?.import_schemes || {})
const hasSchemes = computed(() => Object.keys(importSchemes.value).length > 0)

// ===== 多服：我在这几个服各自的地址与会员（一个服一个会员）=====
const realmCards = computed(() => account.value?.realms || [])

// ===== 公益服（v2.7.0）：本服免费开放，不需要会员 =====
const isFreeRealm = computed(() => !!account.value?.is_free || userStore.isFreeRealm)
const realmNote = computed(
  () => account.value?.access_note || userStore.realmNote || '本服为公益服 · 免费开放：无需开通会员即可观看全库内容。',
)
// 公益服：没订阅也算“能看”，卡片不该写成「未开通」把用户吓回去
function realmState(r: AccountRealmCard) {
  if (r.is_free) return '公益服 · 免费开放'
  return r.subscribed ? `会员剩 ${daysLeft(r.end_date)} 天` : '未开通'
}

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

function refreshAccount() {
  loading.value = true
  embyApi.getAccountCard()
    .then(a => { account.value = a })
    .finally(() => { loading.value = false })
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
  <div class="au-page profile-page">
    <!-- 身份卡：账号是谁、看了多少 -->
    <section class="id-card">
      <div class="id-body">
        <div class="id-avatar">{{ initial }}</div>
        <div class="id-main">
          <h1 class="id-name">
            <span>{{ user?.username || '用户' }}</span>
            <span v-if="user?.is_vip" class="id-vip"><Crown :size="12" /> VIP</span>
            <span v-if="activeSub" class="id-sub">{{ activeSub.plan_name }} · 剩 {{ activeSub.days_left }} 天</span>
          </h1>
          <div class="id-meta">
            <span><Mail :size="13" />{{ user?.email || '未绑定邮箱' }}</span>
            <span><CalendarDays :size="13" />注册于 {{ formatDate(user?.created_at) }}</span>
          </div>
        </div>
      </div>

      <div class="id-stats">
        <div class="id-stat">
          <strong class="accent">{{ watchHours }}</strong>
          <span>累计观看</span>
        </div>
        <div class="id-stat">
          <strong>{{ stats?.total_plays ?? '—' }}</strong>
          <span>播放次数</span>
        </div>
        <div class="id-stat">
          <strong>{{ stats?.watched_items ?? '—' }}</strong>
          <span>看过影片</span>
        </div>
      </div>
    </section>

    <!-- 账号的两栏：左边是「怎么连播放器」，右边是「我的钱 / 我的设备 / 我的安全」 -->
    <div class="p-grid">
      <!-- Emby 账号 -->
      <section class="pane">
        <header class="pane-head">
          <h2 class="pane-title">
            <KeyRound :size="17" />
            Emby 账号
          </h2>
          <button class="icon-btn" title="刷新" @click="refreshAccount">
            <RefreshCw :size="15" :class="{ spinning: loading }" />
          </button>
        </header>

        <!-- 公益服：一进来就说清这个服不要钱、规则是什么，别让用户去找开通入口 -->
        <div v-if="isFreeRealm" class="rows">
          <div class="row">
            <span class="row-label">接入方式</span>
            <span class="row-value">
              <span class="badge free">公益服 · 免费开放</span>
            </span>
          </div>
          <div class="row">
            <span class="row-label">规则</span>
            <span class="row-value wrap">{{ realmNote }}</span>
          </div>
        </div>

        <div class="rows" :class="{ loading }">
          <div class="row">
            <span class="row-label">服务器</span>
            <span class="row-value mono">{{ serverUrl }}</span>
            <button class="copy-btn" title="复制" @click="copyText(serverUrl, 'server')">
              <Check v-if="copiedField === 'server'" :size="14" class="ok" />
              <Copy v-else :size="14" />
            </button>
          </div>
          <div class="row">
            <span class="row-label">用户名</span>
            <span class="row-value mono">{{ embyUsername }}</span>
            <button class="copy-btn" title="复制" @click="copyText(embyUsername, 'user')">
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
            <button v-if="hasPlayPassword" class="copy-btn" :title="showPlayPassword ? '隐藏' : '查看'" @click="showPlayPassword = !showPlayPassword">
              <Eye v-if="showPlayPassword" :size="14" />
              <EyeOff v-else :size="14" />
            </button>
            <button class="text-btn" @click="showSetPlayPwd = true">
              {{ hasPlayPassword ? '修改' : '设置' }}
            </button>
          </div>
        </div>

        <!-- 多服：每个服一个地址与一份会员（没订阅的服后端不下发） -->
        <div v-if="realmCards.length > 1" class="sub-block">
          <span class="block-label">我的服</span>
          <div class="realm-list">
            <div v-for="r in realmCards" :key="r.id" class="realm-item">
              <div class="realm-head">
                <strong>{{ r.name }}</strong>
                <span v-if="r.is_free" class="badge free">公益服 · 免费开放</span>
                <span v-else-if="r.subscribed" class="badge ok">会员剩 {{ daysLeft(r.end_date) }} 天</span>
                <span v-else class="badge off">未开通</span>
              </div>
              <div class="realm-url">
                <span class="mono">{{ r.base_url || '管理员还没填这个服的地址' }}</span>
                <button v-if="r.base_url" class="copy-btn" title="复制" @click="copyText(r.base_url, `realm-${r.id}`)">
                  <Check v-if="copiedField === `realm-${r.id}`" :size="13" class="ok" />
                  <Copy v-else :size="13" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <div v-if="hasSchemes" class="sub-block">
          <span class="block-label">一键导入到客户端</span>
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

        <p class="pane-tip">
          播放密码用于 Emby 客户端登录，与门户密码相互独立；也可以用上面的按钮一键导入。
        </p>
      </section>

      <div class="p-side">
        <!-- 我的订阅 -->
        <section class="pane">
          <header class="pane-head">
            <h2 class="pane-title">
              <Crown :size="17" />
              我的订阅
            </h2>
          </header>

          <div v-if="activeSub" class="sub-active" :class="{ warn: expiringSoon }">
            <div class="sub-info">
              <div class="sub-plan">{{ activeSub.plan_name }}</div>
              <div class="sub-end">{{ activeSub.end_date.slice(0, 10) }} 到期 · 剩余 {{ activeSub.days_left }} 天</div>
              <p v-if="expiringSoon" class="sub-warn">
                <TriangleAlert :size="13" />
                即将到期，前往「钱包」续费后可无缝接续
              </p>
            </div>
            <span class="badge" :class="expiringSoon ? 'warn' : 'ok'">
              {{ expiringSoon ? '即将到期' : '生效中' }}
            </span>
          </div>
          <!-- 公益服：没有订阅是正常的，不是“未开通”，也不能引导去购买 -->
          <div v-else-if="isFreeRealm" class="sub-free">
            <span class="badge free">公益服 · 免费开放</span>
            <p class="pane-empty">{{ realmNote }}</p>
          </div>
          <p v-else class="pane-empty">暂无生效中的订阅。如需开通，请联系管理员。</p>

          <ul v-if="subscriptions.length > 1" class="sub-history">
            <li v-for="s in subscriptions.slice(0, 4)" :key="s.id" class="sub-history-item">
              <span>{{ s.plan_name }}<em v-if="s.realm_name" class="sub-realm">（{{ s.realm_name }}）</em></span>
              <span class="sub-history-date">{{ s.start_date.slice(0, 10) }} ~ {{ s.end_date.slice(0, 10) }}</span>
              <span class="badge" :class="s.status === 'active' ? 'ok' : 'off'">
                {{ s.status === 'active' ? '生效中' : '已结束' }}
              </span>
            </li>
          </ul>
        </section>

        <!-- 我的设备 -->
        <section class="pane">
          <header class="pane-head">
            <h2 class="pane-title">
              <MonitorSmartphone :size="17" />
              我的设备
              <span v-if="deviceInfo && deviceInfo.limit" class="count-chip">
                {{ deviceInfo.active_count }} / {{ deviceInfo.limit }}
              </span>
            </h2>
            <button class="icon-btn" title="刷新" @click="loadDevices">
              <RefreshCw :size="15" :class="{ spinning: deviceLoading }" />
            </button>
          </header>

          <p v-if="devices.length === 0" class="pane-empty">
            还没有客户端登录记录。用 Emby 客户端（Infuse / Forward 等）登录后会出现在这里。
          </p>
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
              <span v-if="d.is_blocked" class="badge off">已禁用</span>
              <span v-else-if="!d.is_online_recent" class="badge idle">已闲置</span>
              <span v-else class="badge ok">活跃</span>
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

          <p class="pane-tip">
            <template v-if="deviceInfo && deviceInfo.limit">
              账号最多同时使用 {{ deviceInfo.limit }} 台设备（近 {{ deviceInfo.active_days }} 天内登录过）。
              {{ deviceInfo.auto_evict ? '超限时会自动停用最久未用的设备。' : '超限时请先移除不再使用的设备。' }}
            </template>
            <template v-else>移除后该设备登录状态立即失效，需重新输入账号密码。</template>
          </p>
        </section>

        <!-- 正在播放：讲的是「控制」（哪台设备在放、能不能停），不是「我看过什么」，
             所以它在这里，而历史留在媒体库的观看记录分段 -->
        <section class="pane">
          <header class="pane-head">
            <h2 class="pane-title">
              <MonitorPlay :size="17" />
              正在播放
            </h2>
          </header>
          <PlaybackSessions />
          <p class="pane-tip">远程结束播放只会终止会话，不会删除观看记录。</p>
        </section>

        <!-- 安全设置 -->
        <section class="pane">
          <header class="pane-head">
            <h2 class="pane-title">
              <Lock :size="17" />
              安全设置
            </h2>
          </header>

          <div class="list">
            <button class="list-item" @click="showChangePwd = true">
              <Lock :size="16" class="list-icon" />
              <span class="list-text">修改登录密码</span>
              <ChevronRight class="list-arrow" :size="15" />
            </button>
            <!-- 管理员入口只在顶栏头像菜单里出现一次（同源 /admin/，后台接管当前登录态） -->
            <button class="list-item danger" @click="handleLogout">
              <LogOut :size="16" class="list-icon" />
              <span class="list-text">退出登录</span>
              <ChevronRight class="list-arrow" :size="15" />
            </button>
          </div>
        </section>
      </div>
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
.profile-page {
  display: flex;
  flex-direction: column;
  gap: 1.125rem;
}

/* ==================== 身份卡 ==================== */
.id-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  flex-wrap: wrap;
  padding: 1.375rem 1.5rem;
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-xl);
  background:
    radial-gradient(120% 160% at 0% 0%, var(--au-primary-soft) 0%, transparent 58%),
    var(--au-surface);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.id-body {
  display: flex;
  align-items: center;
  gap: 1.125rem;
  min-width: 0;
}

.id-avatar {
  width: 58px;
  height: 58px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-lg);
  background: var(--au-gradient);
  color: var(--au-on-primary);
  font-size: 1.375rem;
  font-weight: 800;
  box-shadow: 0 6px 20px var(--au-primary-glow);
}

.id-main { min-width: 0; }

.id-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin: 0;
  font-size: 1.3125rem;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--au-text);
}

.id-vip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  border-radius: var(--au-r-full);
  background: var(--au-gradient-warm);
  color: var(--au-on-primary);
  font-size: 0.6875rem;
  font-weight: 700;
}

.id-sub {
  padding: 0.125rem 0.5rem;
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-full);
  background: var(--au-primary-soft);
  color: var(--au-primary);
  font-size: 0.6875rem;
  font-weight: 600;
}

.id-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.375rem 1rem;
  margin: 0.4375rem 0 0;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.id-meta span {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.id-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(76px, auto));
}

.id-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 0 1.125rem;
  border-left: 1px solid var(--au-border);
}

.id-stat:first-child { border-left: none; padding-left: 0; }

.id-stat strong {
  font-size: 1.125rem;
  font-weight: 800;
  color: var(--au-text);
  font-variant-numeric: tabular-nums;
}

.id-stat strong.accent { color: var(--au-primary); }

.id-stat span {
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

/* ==================== 卡片 ==================== */
.p-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  gap: 1.125rem;
  align-items: start;
}

.p-side {
  display: flex;
  flex-direction: column;
  gap: 1.125rem;
  min-width: 0;
}

.pane {
  padding: 1.25rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.pane-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 700;
  color: var(--au-text);
}

.pane-title svg { color: var(--au-primary); }

.pane-empty {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--au-text-3);
}

.pane-tip {
  margin: 0.875rem 0 0;
  padding-top: 0.875rem;
  border-top: 1px dashed var(--au-border);
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--au-text-4);
}

.badge {
  flex-shrink: 0;
  padding: 0.0625rem 0.5rem;
  border-radius: var(--au-r-full);
  font-size: 0.6875rem;
  background: var(--au-surface-2);
  color: var(--au-text-3);
}

.badge.ok { background: var(--au-success-soft); color: var(--au-success); }
.badge.idle { background: var(--au-surface-2); color: var(--au-text-3); }
.badge.off { background: var(--au-danger-soft); color: var(--au-danger); }
/* 临期：与后台「到期前提醒」同色系 */
.badge.warn { background: var(--au-warning-soft); color: var(--au-warning); }
/* 公益服：免费开放不是“未开通”，用站点主色单独区分 */
.badge.free { background: var(--au-primary-soft); color: var(--au-primary); }

.sub-free { display: flex; flex-direction: column; gap: 0.375rem; align-items: flex-start; }

.count-chip {
  margin-left: 0.125rem;
  padding: 0.0625rem 0.4375rem;
  border-radius: var(--au-r-full);
  background: var(--au-surface-2);
  font-size: 0.6875rem;
  font-weight: 500;
  color: var(--au-text-3);
}

.icon-btn {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-sm);
  color: var(--au-text-2);
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.icon-btn:hover {
  color: var(--au-text);
  border-color: var(--au-border-strong);
}

.spinning { animation: spin 0.9s linear infinite; }

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ==================== Emby 账号信息行 ==================== */
.rows {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  transition: opacity var(--au-fast) var(--au-ease);
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
  background: var(--au-bg-soft);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
}

.row-label {
  flex-shrink: 0;
  width: 64px;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.row-value {
  flex: 1;
  min-width: 0;
  font-size: 0.8125rem;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 公益规则这类长文本要换行，不能像地址那样截断 */
.row-value.wrap { overflow: visible; white-space: normal; line-height: 1.6; }

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
  border-radius: var(--au-r-sm);
  color: var(--au-text-4);
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.copy-btn:hover {
  background: var(--au-surface-2);
  color: var(--au-text);
}

.copy-btn .ok { color: var(--au-primary); }

.text-btn {
  flex-shrink: 0;
  padding: 0.25rem 0.5rem;
  background: transparent;
  border: none;
  border-radius: var(--au-r-sm);
  color: var(--au-primary);
  font-size: 0.8125rem;
  cursor: pointer;
}

.text-btn:hover { background: var(--au-primary-soft); }

.text-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.text-btn.danger { color: var(--au-text-3); }
.text-btn.danger:hover { background: var(--au-danger-soft); color: var(--au-danger); }
.text-btn.danger.confirming { color: var(--au-danger); font-weight: 600; }

/* 多服 / 一键导入：与信息行之间用虚线分隔，避免整张卡看起来是一堆块 */
.sub-block {
  margin-top: 0.875rem;
  padding-top: 0.875rem;
  border-top: 1px dashed var(--au-border);
}

.block-label {
  display: block;
  margin-bottom: 0.5rem;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

.realm-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

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

/* ==================== 我的设备 ==================== */
.dev-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.625rem 0;
}

.dev-row + .dev-row { border-top: 1px solid var(--au-border); }

.dev-main {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
  flex: 1;
}

.dev-name {
  font-size: 0.875rem;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dev-meta {
  font-size: 0.75rem;
  color: var(--au-text-3);
}

/* ==================== 我的订阅 ==================== */
.sub-active {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-md);
}

.sub-plan {
  font-weight: 600;
  color: var(--au-text);
}

.sub-end {
  margin-top: 0.125rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

/* 临期状态：整块底色换成警示色，避免“还剩 3 天”淹没在常规配色里 */
.sub-active.warn {
  background: var(--au-warning-soft);
  border-color: var(--au-warning-soft);
}

.sub-warn {
  display: flex;
  align-items: center;
  gap: 0.3125rem;
  margin: 0.375rem 0 0;
  font-size: 0.75rem;
  color: var(--au-warning);
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
  padding: 0.4375rem 0;
  font-size: 0.75rem;
  color: var(--au-text-2);
}

.sub-history-item + .sub-history-item { border-top: 1px solid var(--au-border); }

.sub-history-date {
  flex: 1;
  color: var(--au-text-4);
}

.sub-realm {
  font-style: normal;
  font-size: 0.6875rem;
  color: var(--au-text-4);
}

/* ==================== 安全设置 ==================== */
.list {
  display: flex;
  flex-direction: column;
}

.list-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.8125rem 0.25rem;
  background: transparent;
  border: none;
  border-top: 1px solid var(--au-border);
  color: var(--au-text-2);
  font-size: 0.875rem;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  transition: color var(--au-fast) var(--au-ease);
}

.list-item:first-child { border-top: none; }

.list-item:hover { color: var(--au-text); }

.list-item.danger { color: var(--au-danger); }

.list-icon { color: var(--au-text-4); }

.list-item.danger .list-icon { color: var(--au-danger); opacity: 0.8; }

.list-text { flex: 1; }

.list-arrow { color: var(--au-text-4); }

/* ==================== 弹窗 ==================== */
.modal-mask {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background: var(--au-scrim);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 100;
}

.modal {
  width: 100%;
  max-width: 360px;
  padding: 1.5rem;
  background: var(--au-bg-soft);
  border: 1px solid var(--au-border-strong);
  border-radius: var(--au-r-lg);
}

.modal-title {
  margin: 0 0 0.375rem;
  font-size: 1.0625rem;
  font-weight: 700;
  color: var(--au-text);
}

.modal-desc {
  margin: 0 0 1rem;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--au-text-3);
}

.field { margin-bottom: 0.875rem; }

.field-label {
  display: block;
  margin-bottom: 0.375rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.field input {
  width: 100%;
  height: 42px;
  padding: 0 0.75rem;
  background: var(--au-bg);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-sm);
  color: var(--au-text);
  font-size: 0.875rem;
  outline: none;
  transition: border-color var(--au-fast) var(--au-ease), box-shadow var(--au-fast) var(--au-ease);
  box-sizing: border-box;
}

.field input:focus {
  border-color: var(--au-border-focus);
  box-shadow: 0 0 0 3px var(--au-primary-soft);
}

.form-error {
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--au-danger-soft);
  border: 1px solid var(--au-danger-border);
  border-radius: var(--au-r-sm);
  color: var(--au-danger);
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
  border: none;
  border-radius: var(--au-r-md);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.btn.ghost {
  background: var(--au-surface-2);
  color: var(--au-text-2);
}

.btn.ghost:hover { background: var(--au-surface-3); }

.btn.primary {
  background: var(--au-gradient);
  color: var(--au-on-primary);   /* 青底配白字只有 1.9:1，与全站主按钮统一为深墨色文字 */
}

.btn.primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ==================== 响应式 ==================== */
@media (max-width: 900px) {
  .p-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .id-card {
    padding: 1.25rem;
    align-items: flex-start;
  }

  .id-body { gap: 0.875rem; }

  .id-stats {
    width: 100%;
    padding-top: 1rem;
    border-top: 1px solid var(--au-border);
    grid-template-columns: repeat(3, 1fr);
  }

  .id-stat {
    padding: 0 0.5rem;
  }

  .id-stat:first-child { padding-left: 0.5rem; }
}

@media (prefers-reduced-motion: reduce) {
  .spinning { animation-duration: 2.4s; }
}
</style>
