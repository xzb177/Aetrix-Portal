<script setup lang="ts">
/**
 * 邀请返利 — 我的邀请码、邀请记录、返利台账
 */
import { ref, computed, onMounted } from 'vue'
import {
  Gift, Users, Coins, Percent, Copy, Check, Share2, UserPlus, Link2, Handshake,
} from 'lucide-vue-next'
import {
  inviteApi,
  type MyInviteInfo, type InvitationRecordRow, type RebateRow,
} from '@/api/economy'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const loading = ref(true)
const info = ref<MyInviteInfo | null>(null)
const records = ref<InvitationRecordRow[]>([])
const rebates = ref<RebateRow[]>([])
const totalRebate = ref(0)
const copied = ref('')

const inviteLink = computed(() => {
  if (!info.value?.code) return ''
  const base = window.location.origin
  return `${base}/login?invite=${info.value.code}`
})

const copiedField = ref('')

async function copyText(text: string, field: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = field
    toast.success('已复制')
    setTimeout(() => { if (copiedField.value === field) copiedField.value = '' }, 1800)
  } catch {
    // 降级方案：选中文字
    toast.error('复制失败，请手动复制')
  }
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}

async function load() {
  loading.value = true
  try {
    const emptyRecords = { total: 0, records: [] as InvitationRecordRow[] }
    const emptyRebates = { total_rebate: 0, rebates: [] as RebateRow[] }
    const [my, rec, reb] = await Promise.all([
      inviteApi.myCode(),
      inviteApi.records({ limit: 50 }).catch(() => emptyRecords),
      inviteApi.rebates({ limit: 50 }).catch(() => emptyRebates),
    ])
    info.value = my
    records.value = rec.records
    rebates.value = reb.rebates
    totalRebate.value = reb.total_rebate
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="au-page invite-view">
    <!-- 邀请主卡 -->
    <section class="invite-hero au-anim-up">
      <div class="hero-glow" aria-hidden="true" />
      <div class="hero-content">
        <span class="hero-badge"><Gift :size="14" /> 邀请返利计划</span>
        <h1>邀请好友 <span class="au-gradient-text">双向得奖励</span></h1>
        <p class="hero-desc">
          分享你的专属邀请码，好友注册成功后：
          <template v-if="info">
            你得 <strong>+{{ info.config.reward_points }}</strong> 积分，
            好友得 <strong>+{{ info.config.invitee_reward_points }}</strong> 积分；
            好友每笔充值你还能拿 <strong>{{ info.config.rebate_percent }}%</strong> 返利。
          </template>
        </p>

        <div class="code-box">
          <div class="code-label">
            <Link2 :size="14" />
            我的专属邀请码
          </div>
          <div class="code-row">
            <span class="code-value">{{ info?.code || '···' }}</span>
            <button
              class="au-btn au-btn-primary au-btn-sm"
              :disabled="!info?.code"
              @click="copyText(info?.code || '', 'code')"
            >
              <Check v-if="copiedField === 'code'" :size="14" />
              <Copy v-else :size="14" />
              复制邀请码
            </button>
          </div>
          <div class="code-row link-row">
            <input class="au-input link-input" :value="inviteLink" readonly>
            <button
              class="au-btn au-btn-ghost au-btn-sm"
              :disabled="!inviteLink"
              @click="copyText(inviteLink, 'link')"
            >
              <Share2 :size="14" />
              复制链接
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- 统计 -->
    <section class="stat-grid au-anim-up" style="animation-delay: 70ms">
      <div class="stat-card">
        <span class="stat-icon c1"><Users :size="18" /></span>
        <span class="stat-num">{{ info?.invited_count ?? '—' }}</span>
        <span class="stat-label">累计邀请人数</span>
      </div>
      <div class="stat-card">
        <span class="stat-icon c2"><Handshake :size="18" /></span>
        <span class="stat-num">{{ info?.use_count ?? '—' }}</span>
        <span class="stat-label">邀请码使用次数</span>
      </div>
      <div class="stat-card">
        <span class="stat-icon c3"><Coins :size="18" /></span>
        <span class="stat-num">{{ totalRebate }}</span>
        <span class="stat-label">累计返利积分</span>
      </div>
      <div class="stat-card">
        <span class="stat-icon c4"><Percent :size="18" /></span>
        <span class="stat-num">{{ info?.config.rebate_percent ?? '—' }}%</span>
        <span class="stat-label">充值返利比例</span>
      </div>
    </section>

    <!-- 邀请记录 / 返利台账 -->
    <div class="list-grid au-anim-up" style="animation-delay: 120ms">
      <section class="au-card au-card-pad">
        <header class="list-head">
          <h3><UserPlus :size="16" /> 邀请记录</h3>
          <span class="au-badge au-badge-cyan">{{ records.length }} 条</span>
        </header>
        <div v-if="!records.length" class="au-empty compact">
          <UserPlus :size="26" />
          <p>还没有邀请记录，快去分享吧</p>
        </div>
        <ul v-else class="rows">
          <li v-for="r in records" :key="r.id">
            <span class="row-avatar">{{ r.invitee_username.charAt(0).toUpperCase() }}</span>
            <span class="row-main">
              <span class="row-title">{{ r.invitee_username }}</span>
              <span class="row-sub">{{ fmtTime(r.created_at) }} 加入</span>
            </span>
            <strong class="row-amt">+{{ r.reward_points }}</strong>
          </li>
        </ul>
      </section>

      <section class="au-card au-card-pad">
        <header class="list-head">
          <h3><Coins :size="16" /> 返利台账</h3>
          <span class="au-badge au-badge-green">累计 +{{ totalRebate }}</span>
        </header>
        <div v-if="!rebates.length" class="au-empty compact">
          <Coins :size="26" />
          <p>好友充值后返利将自动到账</p>
        </div>
        <ul v-else class="rows">
          <li v-for="r in rebates" :key="r.id">
            <span class="row-dot" />
            <span class="row-main">
              <span class="row-title">{{ r.description || '充值返利' }}</span>
              <span class="row-sub">{{ fmtTime(r.created_at) }}</span>
            </span>
            <strong class="row-amt">+{{ r.amount }}</strong>
          </li>
        </ul>
      </section>
    </div>

    <!-- 规则说明 -->
    <section class="rules au-card au-card-pad au-anim-up" style="animation-delay: 170ms">
      <h3><Gift :size="16" /> 活动规则</h3>
      <ol>
        <li>好友通过你的邀请码或链接注册，双方即刻获得积分奖励。</li>
        <li>好友每次充值成功，你将按比例获得返利积分，自动入账。</li>
        <li>积分可在钱包兑换订阅时长或参与其他活动。</li>
        <li>请勿使用邀请码进行刷号等违规操作，违规将取消奖励。</li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.invite-view { display: flex; flex-direction: column; gap: 1.125rem; }

/* ===== 主卡 ===== */
.invite-hero {
  position: relative;
  overflow: hidden;
  border-radius: var(--au-r-xl);
  border: 1px solid var(--au-primary-border);
  background: linear-gradient(150deg, rgba(167, 139, 250, 0.14), rgba(34, 211, 238, 0.1) 55%, rgba(10, 16, 26, 0.4));
  backdrop-filter: blur(14px);
  padding: 2rem 1.5rem;
}

.hero-glow {
  position: absolute;
  top: -50%;
  right: -10%;
  width: 380px;
  height: 260px;
  background: radial-gradient(ellipse, rgba(167, 139, 250, 0.22), transparent 70%);
  filter: blur(34px);
  pointer-events: none;
}

.hero-content { position: relative; display: flex; flex-direction: column; gap: 0.75rem; }

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  width: fit-content;
  padding: 0.3125rem 0.75rem;
  background: var(--au-gradient-warm);
  color: #fff;
  font-size: 0.6875rem;
  font-weight: 700;
  border-radius: var(--au-r-full);
}

.hero-content h1 { margin: 0; font-size: 1.625rem; font-weight: 800; letter-spacing: -0.02em; }

.hero-desc { margin: 0; font-size: 0.875rem; color: var(--au-text-2); line-height: 1.7; max-width: 560px; }
.hero-desc strong { color: var(--au-primary); font-weight: 700; }

.code-box {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
  padding: 1rem;
  background: rgba(7, 11, 18, 0.5);
  border: 1px dashed var(--au-border-strong);
  border-radius: var(--au-r-lg);
  max-width: 560px;
}

.code-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.code-row { display: flex; align-items: center; gap: 0.625rem; }

.code-value {
  flex: 1;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 1.5rem;
  font-weight: 800;
  letter-spacing: 0.18em;
  background: var(--au-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.link-row .link-input { flex: 1; font-size: 0.75rem; color: var(--au-text-2); }

/* ===== 统计 ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.875rem;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.3125rem;
  padding: 1.125rem 0.75rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-lg);
  text-align: center;
}

.stat-icon {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--au-r-md);
  margin-bottom: 0.25rem;
}
.stat-icon.c1 { background: var(--au-primary-soft); color: var(--au-primary); }
.stat-icon.c2 { background: rgba(167, 139, 250, 0.12); color: var(--au-violet); }
.stat-icon.c3 { background: var(--au-success-soft); color: var(--au-success); }
.stat-icon.c4 { background: var(--au-warning-soft); color: var(--au-warning); }

.stat-num {
  font-size: 1.375rem;
  font-weight: 800;
  color: var(--au-text);
  font-variant-numeric: tabular-nums;
}
.stat-label { font-size: 0.6875rem; color: var(--au-text-3); }

/* ===== 列表 ===== */
.list-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.125rem;
  align-items: start;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.875rem;
}
.list-head h3 {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 700;
  color: var(--au-text);
}
.list-head svg { color: var(--au-primary); }

.rows { list-style: none; margin: 0; padding: 0; }
.rows li {
  display: flex;
  align-items: center;
  gap: 0.6875rem;
  padding: 0.625rem 0;
  border-bottom: 1px solid var(--au-border);
}
.rows li:last-child { border-bottom: none; }

.row-avatar {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--au-gradient);
  color: #05141c;
  font-size: 0.75rem;
  font-weight: 800;
  flex-shrink: 0;
}

.row-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--au-success);
  flex-shrink: 0;
  margin: 0 11px;
}

.row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.0625rem; }
.row-title { font-size: 0.8125rem; color: var(--au-text); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-sub { font-size: 0.6875rem; color: var(--au-text-4); }

.row-amt { color: var(--au-success); font-size: 0.875rem; font-variant-numeric: tabular-nums; flex-shrink: 0; }

/* ===== 规则 ===== */
.rules h3 {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  margin: 0 0 0.75rem;
  font-size: 0.9375rem;
  font-weight: 700;
  color: var(--au-text);
}
.rules svg { color: var(--au-violet); }
.rules ol { margin: 0; padding-left: 1.25rem; display: flex; flex-direction: column; gap: 0.4375rem; }
.rules li { font-size: 0.8125rem; color: var(--au-text-2); line-height: 1.6; }

.au-empty.compact { padding: 2rem 1rem; }
.au-empty.compact p { margin: 0; font-size: 0.8125rem; }

@media (max-width: 720px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .list-grid { grid-template-columns: 1fr; }
  .code-row { flex-wrap: wrap; }
  .code-value { font-size: 1.25rem; }
}
</style>
