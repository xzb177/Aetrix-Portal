<script setup lang="ts">
/**
 * 用户管理
 *
 * v2.4.0 重构：
 * - 新增「用户 360°」详情抽屉（资料 / 订阅 / 积分 / 订单 / 邀请 / 签到 / 观看）
 * - 授予订阅、调整积分、重置密码、发送消息改为正规对话框（原先靠输入序号）
 * - 行内操作收敛为「详情 + 更多」下拉，表格不再横向堆 6 个按钮
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CalendarCheck, Coins, Crown, Eye, Film, Gift, KeyRound, Megaphone,
  MoreHorizontal, RefreshCw, Search, ShieldCheck, Wallet,
} from 'lucide-vue-next'
import {
  broadcastMessage, extendSubscription, fetchPlans, fetchUserDetail, fetchUsers,
  grantSubscription, resetUserPassword, sendUserMessage, updateUser, type PlanRow,
} from '@/api/admin'
import { adjustUserPoints } from '@/api/economy'
import type { AdminUserRow, UserDetail } from '@/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const users = ref<AdminUserRow[]>([])
const total = ref(0)
const search = ref('')
const activeFilter = ref<string>('')
const subFilter = ref<string>('')
const loading = ref(false)
const page = ref(0)
const PAGE_SIZE = 20

/** 后端 /users 未支持订阅筛选，这里做客户端补筛（当前页） */
const visibleUsers = computed(() => {
  if (subFilter.value === 'has') return users.value.filter((u) => u.has_subscription)
  if (subFilter.value === 'none') return users.value.filter((u) => !u.has_subscription)
  return users.value
})

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { limit: PAGE_SIZE, offset: page.value * PAGE_SIZE }
    if (search.value) params.search = search.value
    if (activeFilter.value !== '') params.active = activeFilter.value === 'true'
    const res = await fetchUsers(params)
    users.value = res.users
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(), loadPlans()])
})

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

function fmtDay(s: string | null): string {
  return s ? s.slice(0, 10) : '—'
}

// ==================== 套餐 ====================

const plans = ref<PlanRow[]>([])

async function loadPlans() {
  try {
    plans.value = (await fetchPlans()).plans
  } catch {
    plans.value = []
  }
}

// ==================== 360° 详情 ====================

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<UserDetail | null>(null)
const detailTab = ref('overview')
const detailUser = ref<AdminUserRow | null>(null)

async function openDetail(u: AdminUserRow) {
  detailUser.value = u
  detailTab.value = 'overview'
  detail.value = null
  detailVisible.value = true
  detailLoading.value = true
  try {
    detail.value = await fetchUserDetail(u.id)
  } catch {
    // 错误提示由 HTTP 拦截器统一弹出，这里只需收尾
  } finally {
    detailLoading.value = false
  }
}

/** 详情里的快捷操作后刷新两侧数据 */
async function refreshDetail() {
  if (detailUser.value) await openDetail(detailUser.value)
}

// ==================== 授予 / 延长订阅 ====================

const subDialog = reactive({
  visible: false,
  mode: 'grant' as 'grant' | 'extend',
  user: null as AdminUserRow | null,
  planId: undefined as number | undefined,
  days: 30,
})

const grantPreview = computed(() => {
  const u = subDialog.user
  if (!u) return ''
  const base = u.has_subscription && u.subscription_end ? new Date(u.subscription_end) : new Date()
  const from = base.getTime() > Date.now() ? base : new Date()
  const end = new Date(from.getTime() + subDialog.days * 86400000)
  return `${from.toISOString().slice(0, 10)} → ${end.toISOString().slice(0, 10)}`
})

function openGrant(u: AdminUserRow) {
  subDialog.mode = 'grant'
  subDialog.user = u
  subDialog.planId = plans.value[0]?.id
  subDialog.days = plans.value[0]?.duration_days ?? 30
  subDialog.visible = true
}

function openExtend(u: AdminUserRow) {
  subDialog.mode = 'extend'
  subDialog.user = u
  subDialog.days = 30
  subDialog.visible = true
}

function onPlanChange(id: number | undefined) {
  const plan = plans.value.find((p) => p.id === id)
  if (plan) subDialog.days = plan.duration_days
}

const subSaving = ref(false)

async function submitSub() {
  const u = subDialog.user
  if (!u) return
  subSaving.value = true
  try {
    if (subDialog.mode === 'grant') {
      if (!subDialog.planId) {
        ElMessage.warning('请选择套餐')
        return
      }
      await grantSubscription(u.id, { plan_id: subDialog.planId, duration_days: subDialog.days })
      ElMessage.success('订阅已授予并通知用户')
    } else {
      if (!u.subscription_id) return
      await extendSubscription(u.subscription_id, subDialog.days)
      ElMessage.success('订阅已延长并通知用户')
    }
    subDialog.visible = false
    await load()
    if (detailVisible.value) await refreshDetail()
  } catch {
    // 拦截器已提示
  } finally {
    subSaving.value = false
  }
}

// ==================== 积分调整 ====================

const pointsDialog = reactive({
  visible: false,
  user: null as AdminUserRow | null,
  amount: 0,
  reason: '',
})
const pointsSaving = ref(false)

function openPoints(u: AdminUserRow) {
  pointsDialog.user = u
  pointsDialog.amount = 0
  pointsDialog.reason = ''
  pointsDialog.visible = true
}

async function submitPoints() {
  const u = pointsDialog.user
  if (!u) return
  if (!pointsDialog.amount) {
    ElMessage.warning('请输入不为 0 的调整数额')
    return
  }
  pointsSaving.value = true
  try {
    const res = await adjustUserPoints(u.id, {
      amount: pointsDialog.amount,
      reason: pointsDialog.reason || '管理员人工调整',
    })
    ElMessage.success(`已调整，当前余额 ${res.balance}`)
    pointsDialog.visible = false
    if (detailVisible.value) await refreshDetail()
  } catch {
    // 拦截器已提示
  } finally {
    pointsSaving.value = false
  }
}

// ==================== 其他操作 ====================

async function toggleActive(u: AdminUserRow) {
  const action = u.is_active ? '禁用' : '启用'
  await ElMessageBox.confirm(`确定要${action}用户「${u.username}」吗？`, '确认', { type: 'warning' })
  await updateUser(u.id, { is_active: !u.is_active })
  ElMessage.success(`已${action}`)
  load()
}

async function toggleStaff(u: AdminUserRow) {
  if (u.id === auth.admin?.id) {
    ElMessage.warning('不能修改自己的权限')
    return
  }
  const action = u.is_staff ? '移除管理员' : '设为管理员'
  await ElMessageBox.confirm(`确定要${action}「${u.username}」吗？`, '确认', { type: 'warning' })
  await updateUser(u.id, { is_staff: !u.is_staff })
  ElMessage.success('已更新')
  load()
}

const pwdDialog = reactive({ visible: false, user: null as AdminUserRow | null, value: '' })
const pwdSaving = ref(false)

function openPwd(u: AdminUserRow) {
  pwdDialog.user = u
  pwdDialog.value = ''
  pwdDialog.visible = true
}

async function submitPwd() {
  const u = pwdDialog.user
  if (!u) return
  if (pwdDialog.value.length < 6) {
    ElMessage.warning('密码长度需为 6-64 位')
    return
  }
  pwdSaving.value = true
  try {
    await resetUserPassword(u.id, pwdDialog.value)
    ElMessage.success('密码已重置并同步 Emby')
    pwdDialog.visible = false
  } catch {
    // 拦截器已提示
  } finally {
    pwdSaving.value = false
  }
}

const msgDialog = reactive({ visible: false, user: null as AdminUserRow | null, title: '', content: '' })
const msgSaving = ref(false)

function openMsg(u: AdminUserRow) {
  msgDialog.user = u
  msgDialog.title = '管理员消息'
  msgDialog.content = ''
  msgDialog.visible = true
}

async function submitMsg() {
  const u = msgDialog.user
  if (!u || !msgDialog.content.trim()) {
    ElMessage.warning('请输入消息内容')
    return
  }
  msgSaving.value = true
  try {
    await sendUserMessage(u.id, { title: msgDialog.title || '管理员消息', content: msgDialog.content })
    ElMessage.success('消息已发送')
    msgDialog.visible = false
  } catch {
    // 拦截器已提示
  } finally {
    msgSaving.value = false
  }
}

const broadcastVisible = ref(false)
const broadcastForm = reactive({ title: '系统广播', content: '' })

async function submitBroadcast() {
  if (!broadcastForm.content.trim()) {
    ElMessage.warning('请输入广播内容')
    return
  }
  await broadcastMessage({ title: broadcastForm.title || '系统广播', content: broadcastForm.content })
  ElMessage.success('广播已发送给全部用户')
  broadcastVisible.value = false
  broadcastForm.content = ''
}

function onRowCommand(cmd: string, row: AdminUserRow) {
  const map: Record<string, () => void> = {
    detail: () => openDetail(row),
    grant: () => openGrant(row),
    extend: () => openExtend(row),
    points: () => openPoints(row),
    password: () => openPwd(row),
    message: () => openMsg(row),
    active: () => toggleActive(row),
    staff: () => toggleStaff(row),
  }
  map[cmd]?.()
}

const LOGIN_LIMIT = 8
function logTypeLabel(type: string): string {
  const map: Record<string, string> = {
    checkin: '签到', rebate: '返利', recharge: '充值', exchange: '兑换',
    subscribe: '订阅', admin: '人工调整', order: '订单', refund: '退款',
  }
  return map[type] || type
}
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">用户管理</h1>
        <p class="admin-page-subtitle">共 {{ total }} 位用户 · 点击用户名或「详情」可查看完整画像</p>
      </div>
      <div class="toolbar">
        <el-input
          v-model="search"
          placeholder="搜索用户名 / 邮箱"
          clearable
          style="width: 220px"
          @keyup.enter="page = 0; load()"
          @clear="page = 0; load()"
        >
          <template #prefix><Search :size="14" /></template>
        </el-input>
        <el-select v-model="activeFilter" placeholder="账号状态" clearable style="width: 120px" @change="page = 0; load()">
          <el-option label="正常" value="true" />
          <el-option label="已禁用" value="false" />
        </el-select>
        <el-select v-model="subFilter" placeholder="订阅状态" clearable style="width: 120px">
          <el-option label="订阅中" value="has" />
          <el-option label="未订阅" value="none" />
        </el-select>
        <el-button @click="broadcastVisible = true"><Megaphone :size="14" style="margin-right: 4px" />全站广播</el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <div class="admin-card">
      <el-table :data="visibleUsers" v-loading="loading" style="width: 100%">
        <el-table-column label="用户" min-width="200">
          <template #default="{ row }">
            <div class="user-cell">
              <button class="user-link" @click="openDetail(row)">{{ row.username }}</button>
              <span v-if="row.is_staff" class="mini-badge staff">管理员</span>
              <span v-if="!row.is_active" class="mini-badge disabled">已禁用</span>
            </div>
            <div class="user-sub">{{ row.email || '未绑定邮箱' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Emby 账号" min-width="130">
          <template #default="{ row }">{{ row.emby_username || '—' }}</template>
        </el-table-column>
        <el-table-column label="订阅" min-width="160">
          <template #default="{ row }">
            <template v-if="row.has_subscription">
              <span class="mini-badge vip">生效中</span>
              <div class="user-sub">至 {{ fmtDay(row.subscription_end) }}</div>
            </template>
            <span v-else class="user-sub">未订阅</span>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="150">
          <template #default="{ row }">{{ fmtDate(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="注册时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">
              <Eye :size="14" style="margin-right: 2px" />详情
            </el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => onRowCommand(cmd, row)">
              <el-button size="small" text>
                <MoreHorizontal :size="16" />
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="grant">授予订阅</el-dropdown-item>
                  <el-dropdown-item v-if="row.subscription_id" command="extend">延长订阅</el-dropdown-item>
                  <el-dropdown-item command="points">调整积分</el-dropdown-item>
                  <el-dropdown-item command="password" divided>重置密码</el-dropdown-item>
                  <el-dropdown-item command="message">发送消息</el-dropdown-item>
                  <el-dropdown-item command="active" divided>
                    {{ row.is_active ? '禁用账号' : '启用账号' }}
                  </el-dropdown-item>
                  <el-dropdown-item command="staff">
                    {{ row.is_staff ? '移除管理员' : '设为管理员' }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager" v-if="total > PAGE_SIZE">
        <el-pagination
          layout="prev, pager, next, total"
          :total="total"
          :page-size="PAGE_SIZE"
          :current-page="page + 1"
          @current-change="(p: number) => { page = p - 1; load() }"
        />
      </div>
    </div>

    <!-- ==================== 用户 360° 详情 ==================== -->
    <el-drawer v-model="detailVisible" size="620px" :title="detailUser ? `用户画像 · ${detailUser.username}` : '用户详情'">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="detail">
          <!-- 概览 -->
          <div class="detail-hero">
            <div class="hero-avatar">{{ detail.profile.username.charAt(0).toUpperCase() }}</div>
            <div class="hero-main">
              <div class="hero-name">
                {{ detail.profile.username }}
                <span v-if="detail.profile.is_staff" class="mini-badge staff">管理员</span>
                <span v-if="!detail.profile.is_active" class="mini-badge disabled">已禁用</span>
              </div>
              <div class="hero-sub">
                ID {{ detail.profile.id }} · {{ detail.profile.email || '未绑定邮箱' }} ·
                Emby {{ detail.profile.emby_username || '—' }}
              </div>
              <div class="hero-sub">注册 {{ fmtDate(detail.profile.created_at) }} · 最近登录 {{ fmtDate(detail.profile.last_login_at) }}</div>
            </div>
          </div>

          <div class="detail-stats">
            <div class="ds-item">
              <span class="ds-label"><Crown :size="12" /> 订阅</span>
              <span class="ds-value">
                <template v-if="detail.subscription.active">
                  {{ detail.subscription.active.plan_name }}
                  <em>剩 {{ detail.subscription.active.days_left }} 天</em>
                </template>
                <template v-else><em class="muted">未订阅</em></template>
              </span>
            </div>
            <div class="ds-item">
              <span class="ds-label"><Coins :size="12" /> 积分</span>
              <span class="ds-value">{{ detail.points.balance }}</span>
            </div>
            <div class="ds-item">
              <span class="ds-label"><CalendarCheck :size="12" /> 签到</span>
              <span class="ds-value">{{ detail.checkin.total }} 次<em>连签 {{ detail.checkin.streak }}</em></span>
            </div>
            <div class="ds-item">
              <span class="ds-label"><Gift :size="12" /> 邀请</span>
              <span class="ds-value">{{ detail.invitation.count }} 人<em>返利 {{ detail.invitation.rebate_total }}</em></span>
            </div>
            <div class="ds-item">
              <span class="ds-label"><Wallet :size="12" /> 累计付费</span>
              <span class="ds-value">¥{{ detail.orders.paid_total.toFixed(2) }}</span>
            </div>
            <div class="ds-item">
              <span class="ds-label"><Film :size="12" /> 观看</span>
              <span class="ds-value">{{ detail.watch.plays }} 次<em>已看 {{ detail.watch.watched_items }}</em></span>
            </div>
          </div>

          <div class="detail-actions">
            <el-button size="small" type="primary" @click="detailUser && openGrant(detailUser)">
              <Crown :size="13" style="margin-right: 4px" />授予订阅
            </el-button>
            <el-button v-if="detailUser?.subscription_id" size="small" @click="detailUser && openExtend(detailUser)">延长订阅</el-button>
            <el-button size="small" @click="detailUser && openPoints(detailUser)">
              <Coins :size="13" style="margin-right: 4px" />调整积分
            </el-button>
            <el-button size="small" @click="detailUser && openPwd(detailUser)">
              <KeyRound :size="13" style="margin-right: 4px" />重置密码
            </el-button>
            <el-button size="small" @click="detailUser && openMsg(detailUser)">发送消息</el-button>
            <el-button size="small" @click="detailUser && toggleStaff(detailUser)">
              <ShieldCheck :size="13" style="margin-right: 4px" />{{ detailUser?.is_staff ? '移除管理员' : '设为管理员' }}
            </el-button>
          </div>

          <el-tabs v-model="detailTab" class="detail-tabs">
            <el-tab-pane label="订阅记录" name="overview">
              <div v-if="detail.subscription.history.length === 0" class="empty-hint">暂无订阅记录</div>
              <el-table v-else :data="detail.subscription.history" size="small">
                <el-table-column prop="plan_name" label="套餐" min-width="120" />
                <el-table-column label="有效期" min-width="180">
                  <template #default="{ row }">{{ fmtDay(row.start_date) }} → {{ fmtDay(row.end_date) }}</template>
                </el-table-column>
                <el-table-column label="剩余" width="80">
                  <template #default="{ row }">{{ row.days_left }} 天</template>
                </el-table-column>
                <el-table-column label="状态" width="90">
                  <template #default="{ row }">
                    <span class="mini-badge" :class="row.status === 'active' && row.days_left > 0 ? 'vip' : 'off'">
                      {{ row.status === 'active' && row.days_left > 0 ? '生效中' : '已结束' }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane label="积分流水" name="points">
              <div class="mini-summary">
                累计获得 <strong class="ok">+{{ detail.points.income }}</strong>
                · 累计消耗 <strong class="bad">-{{ detail.points.expense }}</strong>
                · 当前 <strong>{{ detail.points.balance }}</strong>
              </div>
              <div v-if="detail.points.recent.length === 0" class="empty-hint">暂无积分流水</div>
              <div v-for="l in detail.points.recent.slice(0, LOGIN_LIMIT)" :key="l.id" class="line-row">
                <span class="line-tag">{{ logTypeLabel(l.type) }}</span>
                <span class="line-desc">{{ l.description || '—' }}</span>
                <span class="line-amount" :class="l.amount >= 0 ? 'ok' : 'bad'">
                  {{ l.amount >= 0 ? '+' : '' }}{{ l.amount }}
                </span>
                <span class="line-date">{{ fmtDate(l.created_at) }}</span>
              </div>
            </el-tab-pane>

            <el-tab-pane label="订单" name="orders">
              <div v-if="!detail.orders.recharge.length && !detail.orders.subscription.length" class="empty-hint">暂无订单</div>
              <div v-for="o in detail.orders.recharge" :key="o.order_id" class="line-row">
                <span class="line-tag">充值</span>
                <span class="line-desc">{{ o.item_name }} · {{ o.points }} 积分</span>
                <span class="line-amount">¥{{ o.amount }}</span>
                <span class="line-date">{{ fmtDate(o.created_at) }}</span>
              </div>
              <div v-for="o in detail.orders.subscription" :key="o.order_id" class="line-row">
                <span class="line-tag">订阅</span>
                <span class="line-desc">{{ o.item_name }}</span>
                <span class="line-amount">¥{{ o.amount }}</span>
                <span class="line-date">{{ fmtDate(o.created_at) }}</span>
              </div>
            </el-tab-pane>

            <el-tab-pane label="邀请" name="invite">
              <div v-if="detail.invitation.invitees.length === 0" class="empty-hint">暂无邀请记录</div>
              <div v-for="(i, idx) in detail.invitation.invitees" :key="idx" class="line-row">
                <span class="line-tag">邀请</span>
                <span class="line-desc">{{ i.username }}</span>
                <span class="line-amount ok">+{{ i.reward_points }}</span>
                <span class="line-date">{{ fmtDate(i.created_at) }}</span>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>

    <!-- ==================== 授予 / 延长订阅 ==================== -->
    <el-dialog
      v-model="subDialog.visible"
      :title="subDialog.mode === 'grant' ? '授予订阅' : '延长订阅'"
      width="440px"
    >
      <el-form label-width="80px">
        <el-form-item label="用户">
          <span class="dialog-user">{{ subDialog.user?.username }}</span>
        </el-form-item>
        <el-form-item v-if="subDialog.mode === 'grant'" label="套餐">
          <el-select v-model="subDialog.planId" style="width: 100%" @change="onPlanChange">
            <el-option
              v-for="p in plans"
              :key="p.id"
              :label="`${p.name}（${p.duration_days} 天 / ¥${p.price}）`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="当前到期">
          <span class="dialog-user">{{ fmtDay(subDialog.user?.subscription_end ?? null) }}</span>
        </el-form-item>
        <el-form-item label="天数">
          <el-input-number v-model="subDialog.days" :min="1" :max="3650" style="width: 100%" />
        </el-form-item>
        <el-form-item label="预期区间">
          <span class="dialog-hint">{{ grantPreview }}</span>
        </el-form-item>
        <el-form-item v-if="plans.length === 0 && subDialog.mode === 'grant'" label=" ">
          <span class="dialog-hint warn">暂无可用套餐，请先在「商品与套餐」中创建</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="subDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="subSaving" @click="submitSub">确认</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 积分调整 ==================== -->
    <el-dialog v-model="pointsDialog.visible" title="调整积分" width="420px">
      <el-form label-width="80px">
        <el-form-item label="用户">
          <span class="dialog-user">{{ pointsDialog.user?.username }}</span>
        </el-form-item>
        <el-form-item label="调整数额">
          <el-input-number v-model="pointsDialog.amount" :min="-1000000" :max="1000000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="pointsDialog.reason" placeholder="例如：活动补偿 / 客服补偿" />
        </el-form-item>
        <el-form-item label=" ">
          <span class="dialog-hint">正数为发放，负数为扣减；操作会写入积分台账与管理员日志</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pointsDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="pointsSaving" @click="submitPoints">确认调整</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 重置密码 ==================== -->
    <el-dialog v-model="pwdDialog.visible" title="重置密码" width="400px">
      <el-form label-width="80px">
        <el-form-item label="用户">
          <span class="dialog-user">{{ pwdDialog.user?.username }}</span>
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdDialog.value" type="password" show-password placeholder="6-64 位，将同步为 Emby 密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="submitPwd">确认重置</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 发送消息 ==================== -->
    <el-dialog v-model="msgDialog.visible" title="发送站内消息" width="460px">
      <el-form label-width="80px">
        <el-form-item label="收件人">
          <span class="dialog-user">{{ msgDialog.user?.username }}</span>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="msgDialog.title" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="msgDialog.content" type="textarea" :rows="4" placeholder="输入消息内容…" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="msgDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="msgSaving" @click="submitMsg">发送</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 全站广播 ==================== -->
    <el-dialog v-model="broadcastVisible" title="全站广播" width="460px">
      <el-form label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="broadcastForm.title" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="broadcastForm.content" type="textarea" :rows="4" placeholder="将推送给全部用户…" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="broadcastVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBroadcast">发送广播</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.user-cell { display: flex; align-items: center; gap: 6px; }
.user-link {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
}
.user-link:hover { color: var(--primary); }
.user-sub { font-size: 12px; color: var(--text-muted); }

.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: var(--radius-full); font-weight: 600; }
.mini-badge.staff { background: var(--primary-bg); color: var(--primary); }
.mini-badge.disabled { background: var(--danger-bg); color: var(--danger); }
.mini-badge.vip { background: var(--warning-bg); color: var(--warning); }
.mini-badge.off { background: var(--bg-hover); color: var(--text-muted); }

.pager { display: flex; justify-content: flex-end; padding: 14px 0 4px; }

/* ===== 详情抽屉 ===== */
.detail-body { min-height: 260px; }

.detail-hero { display: flex; gap: 14px; align-items: center; margin-bottom: 16px; }

.hero-avatar {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 700;
  color: var(--primary-on);
  background: var(--gradient-brand);
  flex-shrink: 0;
}

.hero-main { min-width: 0; }
.hero-name { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; }
.hero-sub { font-size: 12px; color: var(--text-muted); margin-top: 3px; }

.detail-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.ds-item {
  background: var(--bg-glass);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}

.ds-label { display: flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--text-muted); }
.ds-value { display: block; font-size: 15px; font-weight: 600; margin-top: 3px; }
.ds-value em { font-style: normal; font-size: 11.5px; color: var(--text-secondary); font-weight: 400; margin-left: 6px; }
.ds-value em.muted { margin-left: 0; }

.detail-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.detail-tabs { margin-top: 6px; }

.mini-summary { font-size: 12.5px; color: var(--text-secondary); margin-bottom: 10px; }
.ok { color: var(--success); }
.bad { color: var(--danger); }

.line-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
}
.line-row:last-child { border-bottom: none; }
.line-tag {
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-bg);
  border-radius: var(--radius-xs);
  padding: 1px 7px;
  flex-shrink: 0;
}
.line-desc { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.line-amount { font-weight: 600; }
.line-date { font-size: 11.5px; color: var(--text-muted); flex-shrink: 0; }

.empty-hint { font-size: 13px; color: var(--text-muted); padding: 14px 0; text-align: center; }
.dialog-user { font-weight: 600; }
.dialog-hint { font-size: 12px; color: var(--text-muted); }
.dialog-hint.warn { color: var(--warning); }
</style>
