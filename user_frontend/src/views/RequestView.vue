<script setup lang="ts">
/**
 * 求片中心
 *
 * v2.5.0 重构（借鉴 twilight-kotomi 的求片库存检查）：
 * - 提交前自动查库：已在库 → 直接给出播放入口，不占用求片额度
 * - 支持撤回尚未处理的求片（此前提交后无法取消）
 * - 展示今日求片额度（后端限制每日条数）
 * - 状态筛选 + 统一 Aurora 视觉
 *
 * v2.6.24：求片要指明**给哪个服**（片进哪个服的库）。只有一个服的会员时自动带出，
 * 不用用户选；两个服都有会员时才给一个选择器。推送出口（MoviePilot / qB）
 * 仍是全局共享一套，所以这里选的只是「进哪个库」。
 *
 * v2.10.4（本次）：加载态不止出现在骨架屏里，也出现在区块级别——列表框、额度卡、
 * 查库卡各自显示自己的加载中，宁快勿大，等一块出来的等待感少一点。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  Film, Plus, Send, RefreshCw, CheckCircle2, Clock, XCircle, Ban, Search,
  CircleCheck, Loader2, Play, Ticket, Undo2, Info, Layers,
} from 'lucide-vue-next'
import {
  mediaSeekApi, subscriptionApi,
  type MediaSeekRequest, type MediaSeekQuota, type MediaLookupItem, type MySubscription,
} from '@/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const route = useRoute()

// ===== 列表 =====
const loading = ref(true)
const refreshing = ref(false)
const requests = ref<MediaSeekRequest[]>([])
const quota = ref<MediaSeekQuota | null>(null)
const statusFilter = ref<'all' | 'pending' | 'approved' | 'completed' | 'rejected'>('all')
const withdrawing = ref<number | null>(null)

// ===== 表单 =====
const showForm = ref(false)
const submitting = ref(false)
const form = ref({ movie_name: '', year: '', type: 'movie', note: '', realm_id: null as number | null })

/** 我持有会员的服（求片可以指定进哪个服的库） */
const myRealms = ref<{ id: number; name: string }[]>([])
/** 只有唯一一个服时不用麻烦用户选：直接带出并只展示一行说明 */
const onlyRealm = computed(() => (myRealms.value.length === 1 ? myRealms.value[0] : null))

/**
 * 可选的“求给哪个服”：优先用持有生效会员的服；一个会员都没有时退回全部可见的服，
 * 让用户至少能选一个（付费墙开着的站点里没会员也求不了片，但先把选择显出来更诚实）。
 */
async function loadMyRealms() {
  try {
    const subs: MySubscription[] = await subscriptionApi.getMine()
    const seen = new Map<number, string>()
    for (const s of subs || []) {
      if (s.status === 'active' && s.realm_id) seen.set(s.realm_id, s.realm_name || `服 #${s.realm_id}`)
    }
    myRealms.value = [...seen.entries()].map(([id, name]) => ({ id, name }))
    // 单服：默认就是它；多服：不预选，让用户自己拍（预选错会把片子放进另一个库）
    if (onlyRealm.value) form.value.realm_id = onlyRealm.value.id
  } catch {
    myRealms.value = []
  }
}

// ===== 库存检查 =====
const lookupLoading = ref(false)
const lookupDone = ref(false)
const lookupHits = ref<MediaLookupItem[]>([])
let lookupTimer: number | undefined

const typeOptions = [
  { value: 'movie', label: '电影' },
  { value: 'series', label: '剧集' },
  { value: 'anime', label: '动漫' },
  { value: 'documentary', label: '纪录片' },
  { value: 'other', label: '其他' },
]

const typeLabels: Record<string, string> = {
  movie: '电影', series: '剧集', anime: '动漫', documentary: '纪录片', other: '其他',
}

const statusConfig: Record<string, { label: string; cls: string; icon: unknown }> = {
  pending: { label: '待处理', cls: 'amber', icon: Clock },
  approved: { label: '处理中', cls: 'cyan', icon: Loader2 },
  rejected: { label: '已拒绝', cls: 'rose', icon: XCircle },
  completed: { label: '已完成', cls: 'green', icon: CheckCircle2 },
}

const STATUS_TABS: { value: typeof statusFilter.value; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待处理' },
  { value: 'approved', label: '处理中' },
  { value: 'completed', label: '已完成' },
  { value: 'rejected', label: '已拒绝' },
]

const filtered = computed(() =>
  statusFilter.value === 'all'
    ? requests.value
    : requests.value.filter((r) => r.status === statusFilter.value),
)

const counts = computed(() => ({
  pending: requests.value.filter((r) => r.status === 'pending').length,
  processing: requests.value.filter((r) => r.status === 'approved').length,
}))

const quotaLeft = computed(() => quota.value?.remaining ?? 0)
const quotaExhausted = computed(() => quota.value != null && quota.value.remaining <= 0)
const inLibrary = computed(() => lookupDone.value && lookupHits.value.length > 0)

// ===== 数据 =====
async function load(showSpinner = true) {
  if (showSpinner) loading.value = true
  try {
    const res = await mediaSeekApi.getMyRequests()
    requests.value = res.requests || []
    quota.value = res.quota || null
  } catch {
    requests.value = []
  } finally {
    loading.value = false
  }
}

async function loadRequests() {
  loading.value = true
  try {
    const res = await mediaSeekApi.getMyRequests()
    requests.value = res.requests || []
    quota.value = res.quota || null
  } catch {
    requests.value = []
  } finally {
    loading.value = false
  }
}

async function runLookup() {
  const name = form.value.movie_name.trim()
  if (name.length < 2) {
    lookupDone.value = false
    lookupHits.value = []
    return
  }
  lookupLoading.value = true
  try {
    const res = await mediaSeekApi.lookup(name)
    lookupHits.value = res.items || []
    lookupDone.value = true
  } catch {
    lookupDone.value = false
    lookupHits.value = []
  } finally {
    lookupLoading.value = false
  }
}

// 片名输入防抖查库
watch(() => form.value.movie_name, () => {
  window.clearTimeout(lookupTimer)
  lookupDone.value = false
  if (form.value.movie_name.trim().length < 2) {
    lookupHits.value = []
    return
  }
  lookupTimer = window.setTimeout(runLookup, 420)
})

function openForm() {
  showForm.value = !showForm.value
  if (!showForm.value) {
    lookupHits.value = []
    lookupDone.value = false
  }
}

async function handleSubmit() {
  const name = form.value.movie_name.trim()
  if (!name) {
    toast.error('请填写片名')
    return
  }
  submitting.value = true
  try {
    if (!onlyRealm.value && myRealms.value.length < 1) {
      toast.error('还没有可用的服务器：请先开通会员后再求片')
      return
    }
    if (myRealms.value.length > 1 && !form.value.realm_id) {
      toast.error('请先选择这部片要进哪个服的库')
      return
    }
    await mediaSeekApi.create({
      movie_name: name,
      year: form.value.year || undefined,
      type: form.value.type,
      note: form.value.note || undefined,
      realm_id: form.value.realm_id ?? undefined,
    })
    toast.success('求片已提交，管理员会尽快处理')
    form.value = { movie_name: '', year: '', type: 'movie', note: '', realm_id: onlyRealm.value?.id ?? null }
    lookupHits.value = []
    lookupDone.value = false
    showForm.value = false
    await load(false)
    await loadRequests()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

async function withdraw(req: MediaSeekRequest) {
  withdrawing.value = req.id
  try {
    await mediaSeekApi.withdraw(req.id)
    toast.success('已撤回该求片')
    requests.value = requests.value.filter((r) => r.id !== req.id)
    await loadRequests()
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    toast.error(typeof detail === 'string' ? detail : '撤回失败')
  } finally {
    withdrawing.value = null
  }
}

async function refresh() {
  refreshing.value = true
  try {
    await load(false)
  } finally {
    refreshing.value = false
  }
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

onMounted(async () => {
  await Promise.all([loadRequests(), loadMyRealms()])
  // 从搜索页/首页带入片名（/request?name=xxx）：直接展开表单并查库
  const prefill = ((route.query.name as string) || '').trim()
  if (prefill) {
    form.value.movie_name = prefill
    showForm.value = true
    runLookup()
  }
})
</script>

<template>
  <div class="request-view">
    <div class="au-page">
      <!-- 头部 -->
      <header class="page-head au-anim-up">
        <div>
          <h1 class="page-title">
            <Film :size="20" />
            求片中心
          </h1>
          <p class="page-sub">
            <template v-if="requests.length || loading">
              <span v-if="loading">正在加载中，请稍候……</span>
              <template v-else>共 {{ requests.length }} 条 · {{ counts.pending }} 条待处理 · {{ counts.processing }} 条处理中</template>
            </template>
            <template v-else>告诉我们你想看的影视作品，管理员会尽快入库</template>
          </p>
        </div>
        <div class="head-actions">
          <button class="au-btn au-btn-ghost au-btn-sm" :disabled="loading" @click="refresh">
            <RefreshCw :size="14" :class="{ spinning: refreshing }" />
            刷新
          </button>
          <button
            class="au-btn au-btn-primary au-btn-sm"
            :disabled="quotaExhausted && !showForm || loading"
            @click="openForm"
          >
            <component :is="showForm ? XCircle : Plus" :size="14" />
            {{ showForm ? '收起' : '我要求片' }}
          </button>
        </div>
      </header>

      <!-- 今日额度 -->
      <div v-if="quota" class="quota-bar au-anim-up" :class="{ empty: quotaExhausted }">
        <Ticket :size="14" />
        <span>
          今日额度：已提交 <strong>{{ quota.used_today }}</strong> / {{ quota.daily_limit }}，
          剩余 <strong>{{ quota.remaining }}</strong> 条
        </span>
        <span v-if="quotaExhausted" class="quota-tip">今日额度已用完，明天再来</span>
      </div>

      <!-- 提交表单 -->
      <section v-if="showForm" class="au-card au-card-pad form-card au-anim-up">
        <div class="form-row">
          <div class="field grow">
            <label class="au-label">片名 *</label>
            <input
              v-model="form.movie_name"
              class="au-input"
              type="text"
              placeholder="影视作品名称（输入后自动检查是否已在库）"
              @keyup.enter="handleSubmit"
            />
          </div>
          <div class="field year-field">
            <label class="au-label">年份</label>
            <input v-model="form.year" class="au-input" type="text" placeholder="如 2024" />
          </div>
          <div class="field type-field">
            <label class="au-label">类型</label>
            <select v-model="form.type" class="au-input">
              <option v-for="opt in typeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
        </div>

        <!-- 库存检查结果 -->
        <div v-if="lookupLoading" class="lookup-box checking">
          <Loader2 :size="14" class="spinning" />
          <span>正在检查媒体库…</span>
        </div>

        <div v-else-if="inLibrary" class="lookup-box hit">
          <div class="lookup-head">
            <CircleCheck :size="15" />
            <span>媒体库中已有相关影片，无需排队，直接看吧</span>
          </div>
          <div class="hit-list">
            <RouterLink
              v-for="hit in lookupHits.slice(0, 4)"
              :key="hit.id"
              class="hit-item"
              :to="`/media/${hit.id}`"
            >
              <div class="hit-poster">
                <img v-if="hit.poster_url" :src="hit.poster_url" :alt="hit.name" loading="lazy" />
                <Film v-else :size="14" />
              </div>
              <div class="hit-body">
                <span class="hit-name">{{ hit.name }}</span>
                <span class="hit-meta">{{ hit.year || '—' }}</span>
              </div>
              <Play :size="13" class="hit-play" />
            </RouterLink>
          </div>
          <p class="lookup-note">
            <Info :size="12" />
            如果上面的版本不满足需求（画质/字幕等），仍可继续提交求片
          </p>
        </div>

        <div v-else-if="lookupDone" class="lookup-box miss">
          <Search :size="14" />
          <span>媒体库中未找到该片，可以提交求片，管理员会尽快处理</span>
        </div>

        <!-- 这部片给哪个服：只有一个服的会员就一带而过，两个服才需要选 -->
        <div v-if="myRealms.length" class="field">
          <label class="au-label">
            <Layers :size="12" />
            求给哪个服务器
            <span v-if="!onlyRealm" class="req">*</span>
          </label>
          <template v-if="onlyRealm">
            <div class="realm-fixed">
              <span class="realm-chip">{{ onlyRealm.name }}</span>
              <span class="realm-hint">你只有一个服的会员，默认进它的库</span>
            </div>
          </template>
          <template v-else>
            <div class="realm-list">
              <button
                v-for="r in myRealms"
                :key="r.id"
                type="button"
                class="realm-opt"
                :class="{ on: form.realm_id === r.id }"
                @click="form.realm_id = r.id"
              >
                {{ r.name }}
              </button>
            </div>
            <p class="realm-hint">
              你有多个服的会员：选一个，这部片入库后就在那个服的媒体库里播放。
            </p>
          </template>
        </div>

        <div class="field">
          <label class="au-label">备注</label>
          <textarea
            v-model="form.note"
            class="au-input textarea"
            rows="2"
            placeholder="补充说明（选填）：季数、字幕偏好、画质要求等"
          ></textarea>
        </div>

        <div class="form-actions">
          <button class="au-btn au-btn-ghost" @click="showForm = false">取消</button>
          <button
            class="au-btn au-btn-primary"
            :disabled="submitting || !form.movie_name.trim() || quotaExhausted || (myRealms.length > 1 && !form.realm_id)"
            @click="handleSubmit"
          >
            <Send :size="14" />
            {{ submitting ? '提交中…' : '提交求片' }}
          </button>
        </div>
      </section>

      <!-- 状态筛选 -->
      <div v-if="requests.length" class="status-tabs au-anim-up">
        <button
          v-for="t in STATUS_TABS"
          :key="t.value"
          class="status-tab"
          :class="{ active: statusFilter === t.value }"
          @click="statusFilter = t.value"
        >
          {{ t.label }}
        </button>
      </div>

      <!-- 加载中 -->
      <div v-if="loading && requests.length === 0" class="skeleton-list">
        <div v-for="i in 3" :key="i" class="au-skeleton skel" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="filtered.length === 0" class="au-empty">
        <Film :size="30" />
        <h3>{{ requests.length ? '该状态下没有记录' : '还没有求片记录' }}</h3>
        <p>{{ requests.length ? '换个状态看看' : '点击右上角「我要求片」提交第一个请求' }}</p>
      </div>

      <!-- 列表 -->
      <ul v-else class="request-list">
        <li v-for="req in filtered" :key="req.id" class="au-card request-item au-anim-up">
          <div class="item-head">
            <div class="item-title-wrap">
              <h3 class="item-title">{{ req.movie_name }}</h3>
              <div class="item-meta">
                <span v-if="req.year">{{ req.year }}</span>
                <span v-if="req.year && typeLabels[req.type || '']" class="meta-sep">·</span>
                <span v-if="typeLabels[req.type || '']">{{ typeLabels[req.type || ''] }}</span>
                <template v-if="req.realm_name">
                  <span class="meta-sep">·</span>
                  <span class="item-realm"><Layers :size="11" />{{ req.realm_name }}</span>
                </template>
                <span class="meta-sep">·</span>
                <span>{{ fmtDate(req.created_at) }}</span>
              </div>
            </div>
            <span class="au-badge" :class="`au-badge-${statusConfig[req.status]?.cls || 'cyan'}`">
              <component :is="statusConfig[req.status]?.icon || Clock" :size="11" />
              {{ statusConfig[req.status]?.label || req.status }}
            </span>
          </div>

          <p v-if="req.note" class="item-note">{{ req.note }}</p>

          <p v-if="req.admin_note" class="item-reply">
            <span class="reply-label">管理员回复</span>{{ req.admin_note }}
          </p>

          <div v-if="req.status === 'pending'" class="item-actions">
            <button
              class="au-btn au-btn-ghost au-btn-sm"
              :disabled="withdrawing === req.id"
              @click="withdraw(req)"
            >
              <Undo2 :size="12" />
              {{ withdrawing === req.id ? '撤回中…' : '撤回' }}
            </button>
          </div>
        </li>
      </ul>

      <div v-if="!loading && requests.length && filtered.length === 0" class="au-empty">
        <Ban :size="26" />
        <p>没有符合筛选条件的记录</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 页头与页面骨架见 styles/aurora.css「页面骨架」一节（原先这里写了一份同样的） */

/* 额度条 */
.quota-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.625rem 0.875rem;
  margin-bottom: 1rem;
  border-radius: var(--au-r-md);
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  color: var(--au-text-2);
  font-size: 0.8125rem;
}

.quota-bar svg { color: var(--au-primary); }
.quota-bar strong { color: var(--au-primary); }
.quota-bar.empty {
  background: var(--au-warning-soft);
  border-color: rgba(251, 191, 36, 0.3);
}
.quota-bar.empty svg,
.quota-bar.empty strong { color: var(--au-warning); }
.quota-tip { margin-left: auto; color: var(--au-warning); font-size: 0.75rem; }

/* 表单 */
.form-card { margin-bottom: 1.25rem; }

.form-row { display: flex; gap: 0.75rem; flex-wrap: wrap; }

/* ===== 求给哪个服 ===== */
.field .au-label .req { color: var(--au-danger); margin-left: 0.125rem; }

.realm-list { display: flex; flex-wrap: wrap; gap: 0.4375rem; }

.realm-opt {
  padding: 0.4375rem 0.8125rem;
  background: var(--au-surface);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-full);
  color: var(--au-text-2);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.realm-opt:hover { border-color: var(--au-border-strong); color: var(--au-text); }

.realm-opt.on {
  background: var(--au-primary-soft);
  border-color: var(--au-primary-border);
  color: var(--au-primary);
}

.realm-fixed { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }

.realm-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.3125rem 0.6875rem;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-full);
  color: var(--au-primary);
  font-size: 0.8125rem;
  font-weight: 600;
}

.realm-hint {
  margin: 0.375rem 0 0;
  font-size: 0.6875rem;
  color: var(--au-text-4);
  line-height: 1.5;
}

.realm-fixed .realm-hint { margin: 0; }

.field { margin-bottom: 0.875rem; display: flex; flex-direction: column; }
.grow { flex: 1 1 260px; }
.year-field { flex: 0 1 120px; }
.type-field { flex: 0 1 140px; }

.textarea {
  height: auto;
  padding: 0.625rem 0.875rem;
  resize: vertical;
  min-height: 58px;
  font-family: inherit;
  line-height: 1.5;
}

select.au-input { appearance: none; cursor: pointer; }
select.au-input option { background: #0d1420; }

/* 库存检查 */
.lookup-box {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.75rem 0.875rem;
  margin-bottom: 0.875rem;
  border-radius: var(--au-r-md);
  font-size: 0.8125rem;
  line-height: 1.5;
  flex-wrap: wrap;
}

.lookup-box.checking,
.lookup-box.miss {
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  color: var(--au-text-2);
}

.lookup-box.hit {
  background: var(--au-success-soft);
  border: 1px solid rgba(52, 211, 153, 0.28);
  color: var(--au-success);
  flex-direction: column;
}

.lookup-head { display: flex; align-items: center; gap: 0.4375rem; font-weight: 600; }

.hit-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.5rem;
  width: 100%;
  margin-top: 0.5rem;
}

.hit-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4375rem 0.5rem;
  border-radius: var(--au-r-sm);
  background: rgba(7, 11, 18, 0.45);
  border: 1px solid var(--au-border);
  text-decoration: none;
  transition: border-color var(--au-fast) var(--au-ease);
}

.hit-item:hover { border-color: var(--au-primary-border); }

.hit-poster {
  width: 30px;
  height: 42px;
  flex-shrink: 0;
  border-radius: 6px;
  overflow: hidden;
  background: var(--au-surface-3);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--au-text-4);
}

.hit-poster img { width: 100%; height: 100%; object-fit: cover; }

.hit-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }

.hit-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--au-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hit-meta { font-size: 0.6875rem; color: var(--au-text-4); }
.hit-play { color: var(--au-primary); flex-shrink: 0; }

.lookup-note {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin: 0.375rem 0 0;
  font-size: 0.75rem;
  color: var(--au-text-3);
}

.form-actions { display: flex; justify-content: flex-end; gap: 0.625rem; }

/* 筛选 */
.status-tabs { display: flex; gap: 0.375rem; margin-bottom: 0.875rem; flex-wrap: wrap; }

.status-tab {
  height: 30px;
  padding: 0 0.75rem;
  border-radius: var(--au-r-full);
  border: 1px solid var(--au-border);
  background: transparent;
  color: var(--au-text-3);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all var(--au-fast) var(--au-ease);
}

.status-tab:hover { color: var(--au-text); border-color: var(--au-border-strong); }
.status-tab.active {
  color: var(--au-primary);
  border-color: var(--au-primary-border);
  background: var(--au-primary-soft);
}

/* 列表 */
.request-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.request-item { padding: 0.875rem 1rem; transition: border-color var(--au-fast) var(--au-ease); }
.request-item:hover { border-color: var(--au-primary-border); }

.item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.item-title-wrap { min-width: 0; }

.item-title {
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--au-text);
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: var(--au-text-3);
  flex-wrap: wrap;
}

.meta-sep { opacity: 0.5; }

.item-realm { display: inline-flex; align-items: center; gap: 0.1875rem; }

.item-note {
  margin: 0.625rem 0 0;
  font-size: 0.8125rem;
  color: var(--au-text-2);
  line-height: 1.55;
}

.item-reply {
  margin: 0.625rem 0 0;
  padding: 0.5rem 0.75rem;
  border-radius: var(--au-r-sm);
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  font-size: 0.8125rem;
  color: var(--au-text);
  line-height: 1.55;
}

.reply-label {
  color: var(--au-primary);
  font-weight: 600;
  margin-right: 0.4375rem;
  font-size: 0.75rem;
}

.item-actions { display: flex; justify-content: flex-end; margin-top: 0.625rem; }

/* 骨架 */
.skeleton-list { display: flex; flex-direction: column; gap: 0.625rem; }
.skel { height: 92px; }

.spinning { animation: au-spin 0.9s linear infinite; }

@media (max-width: 640px) {
  .quota-tip { margin-left: 0; }
  .item-head { flex-direction: column; }
}
</style>
