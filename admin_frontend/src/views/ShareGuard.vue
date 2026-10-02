<script setup lang="ts">
/**
 * 防共享（v2.43.0）：跨城市行为轨迹 + 同播检测
 *
 * 这一页回答两个问题，顺序就是运营看它的顺序：
 *
 * 1. **现在开着没有、开到哪一档**（策略卡）。四档：关闭 / 只记录 / 记录并告警 /
 *    记录、告警并处置。**默认关闭**，「处置」档会停用账号、拦下多余播放会话，
 *    只能由超级管理员显式打开——判错一次就是误伤正常用户。
 * 2. **判出来过什么**（事件流水）。两种 kind 共用一张时间轴：跨城市轨迹与
 *    同播检测是同一件事（账号被多人共用）的两面，翻一个页签就能看全。
 *
 * **没配「IP 与地理位置」能力时跨城市检测不判定**：查不到城市就不知道人在哪，
 * 这里照实显示「未配置地理能力」，而不是假装检测开着。
 *
 * 判定与处置逻辑在后端 `backend/share_guard.py`，本页只做配置与展示。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CalendarClock, Eraser, MapPin, MonitorPlay, RefreshCw, Save, ShieldAlert, TriangleAlert,
} from 'lucide-vue-next'
import {
  fetchShareGuard,
  purgeShareGuardEvents,
  saveShareGuardPolicy,
  type ShareGuardAction,
  type ShareGuardPolicy,
  type ShareGuardResponse,
} from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
import { confirmIrreversible } from '@/composables/useDangerOps'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

/** 手机卡片：用户为标题，城市/处置/详情/时间做键值行（事件类型与并发数在标题里） */
const columns: DataColumn[] = [
  { key: 'username', label: '用户', width: 130, mobile: 'title' },
  { key: 'created_at', label: '时间', width: 170 },
  { key: 'kind', label: '检测', width: 120 },
  { key: 'action', label: '处置', width: 130 },
  { key: 'region', label: '城市', width: 170 },
  { key: 'detail', label: '说明', minWidth: 260 },
]

const data = ref<ShareGuardResponse | null>(null)
const loading = ref(false)
const saving = ref(false)
const kindFilter = ref('')

/** 本地草稿：改完点「保存」才写后端，不动后端就不算改 */
const draft = ref<ShareGuardPolicy | null>(null)
const dirty = computed(() => {
  const cur = data.value?.policy
  const d = draft.value
  if (!cur || !d) return false
  return (
    cur.travel_action !== d.travel_action ||
    cur.travel_window_minutes !== d.travel_window_minutes ||
    cur.concurrent_action !== d.concurrent_action ||
    cur.concurrent_limit !== d.concurrent_limit ||
    cur.retention_days !== d.retention_days
  )
})

const auth = useAuthStore()
/** 与导航锁标记、危险操作页同一口径：只有超级管理员能改这档配置 */
const canWrite = computed(() => auth.admin?.is_super !== false)
const WRITE_HINT = '防共享的「处置」档会停用账号、拦下播放会话，需要超级管理员才能打开'

/** 清理复用危险操作那一份确认（手打「清理」），与登录日志页同一份实现 */

const ACTION_OPTIONS = [
  { value: 'off', label: '关闭', hint: '不判定、不写库、不通知' },
  { value: 'record', label: '只记录', hint: '写事件流水，后台可查，不打扰任何人' },
  { value: 'alert', label: '记录并告警', hint: '额外给管理员发站内信，不影响用户' },
  { value: 'enforce', label: '记录、告警并处置', hint: '停用账号 / 拦下多余会话（会误伤，请先只记录观察几天）' },
]

async function load() {
  loading.value = true
  try {
    data.value = await fetchShareGuard({ kind: kindFilter.value || undefined, limit: 300 })
    draft.value = { ...data.value.policy }
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function save() {
  const d = draft.value
  if (!d) return
  saving.value = true
  try {
    const res = await saveShareGuardPolicy({
      travel_action: d.travel_action,
      travel_window_minutes: d.travel_window_minutes,
      concurrent_action: d.concurrent_action,
      concurrent_limit: d.concurrent_limit,
      retention_days: d.retention_days,
    })
    data.value = { ...(data.value as ShareGuardResponse), policy: res.policy }
    // 以后端返回的**真实生效值**回填，不自己猜（非法值后端会保持原值不动）
    draft.value = { ...res.policy }
    ElMessage.success('防共享配置已保存并立即生效')
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

function revert() {
  if (data.value) draft.value = { ...data.value.policy }
}

/** 清空事件：走危险操作那一份（手打「清理」），不留第二个确认口径 */
const purging = ref(false)
const pruning = ref(false)

/** 按保留天数删掉过期的那部分（保留天数 = 0 时无事可做，按钮置灰） */
async function pruneOld() {
  // 按**已保存**的保留天数执行，不拿草稿值（否则会出现「按还没保存的天数删了」）
  const days = data.value?.policy.retention_days ?? 0
  if (days <= 0) return
  const ok = await confirmIrreversible(
    `将删除 ${days} 天前的判定记录（基线轨迹与账号状态不受影响）。`,
    '清理',
    '清理过期防共享事件',
  )
  if (!ok) return
  pruning.value = true
  try {
    const res = await purgeShareGuardEvents(days)
    ElMessage.success(res.message)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    pruning.value = false
  }
}

async function purge() {
  const ok = await confirmIrreversible(
    '清空后这些判定记录就查不到了（账号状态与已生效的处置不受影响）。',
    '清理',
    '清理防共享事件',
  )
  if (!ok) return
  purging.value = true
  try {
    const res = await purgeShareGuardEvents(0)
    ElMessage.success(res.message)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    purging.value = false
  }
}

function fmt(ts: string | null): string {
  return ts ? ts.slice(0, 19).replace('T', ' ') : '—'
}

/** 空态要说清「为什么空」：两个开关全关时，压根不会有判定发生 */
const emptyText = computed(() => {
  const p = data.value?.policy
  if (!p) return '暂无防共享事件'
  const allOff = p.travel_action === 'off' && p.concurrent_action === 'off'
  return allOff
    ? '防共享当前全部关闭，判定不会发生；开启后命中的事件会出现在这里'
    : '还没有命中过判定：检测开着但没人触发'
})
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">防共享</h1>
        <p class="admin-page-desc">
          跨城市行为轨迹与同播检测。默认全部关闭；「处置」档会停用账号、拦下多余会话。
        </p>
      </div>
      <div class="toolbar">
        <el-button :loading="loading" @click="load">
          <RefreshCw :size="14" style="margin-right: 4px" />刷新
        </el-button>
        <el-button
          :loading="pruning"
          :disabled="!data || data.policy.retention_days <= 0"
          @click="pruneOld"
        >
          <CalendarClock :size="14" style="margin-right: 4px" />清理过期
        </el-button>
        <el-button :loading="purging" @click="purge">
          <Eraser :size="14" style="margin-right: 4px" />清空事件
        </el-button>
      </div>
    </div>

    <div v-if="data" class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label"><ShieldAlert :size="13" /> 事件总数</div>
        <div class="stat-value">{{ data.summary.total }}</div>
        <div class="stat-hint">跨城市 + 同播，一条时间轴</div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': data.summary.travel_24h > 0 }">
        <div class="stat-label"><MapPin :size="13" /> 24h 跨城市</div>
        <div class="stat-value">{{ data.summary.travel_24h }}</div>
        <div class="stat-hint">窗口内换城市的判定</div>
      </div>
      <div class="stat-tile" :class="{ 'is-warn': data.summary.concurrent_24h > 0 }">
        <div class="stat-label"><MonitorPlay :size="13" /> 24h 同播</div>
        <div class="stat-value">{{ data.summary.concurrent_24h }}</div>
        <div class="stat-hint">并发路数超出上限的判定</div>
      </div>
      <div class="stat-tile" :class="{ 'is-danger': data.summary.enforced_24h > 0 }">
        <div class="stat-label"><TriangleAlert :size="13" /> 24h 已处置</div>
        <div class="stat-value">{{ data.summary.enforced_24h }}</div>
        <div class="stat-hint">停用了账号或拦下了会话</div>
      </div>
    </div>

    <!-- 策略 -->
    <section class="admin-card">
      <header class="card-header">
        <h2>检测策略</h2>
        <span v-if="dirty" class="fact warn">有未保存的改动</span>
      </header>

      <el-alert
        v-if="data && !data.policy.geo_ready"
        type="info"
        :closable="false"
        show-icon
        class="sg-alert"
      >
        <strong>跨城市检测现在不会判定</strong>：城市来自「系统设置 → 能力与服务 → IP 与地理位置」，
        没配提供方就查不到人在哪。此时下面第一项选了任何档位都只会空转
        （不判定、不写库）。先把那个能力配上，再回来开启跨城市检测。
      </el-alert>

      <el-alert
        v-if="!canWrite"
        type="warning"
        :closable="false"
        show-icon
        class="sg-alert"
      >
        {{ WRITE_HINT }}。下面的按钮已置灰，但内容仍然可读。
      </el-alert>

      <div v-if="draft" class="sg-grid">
        <!-- 跨城市 -->
        <div class="sg-block">
          <h3><MapPin :size="15" style="margin-right: 6px" />跨城市行为轨迹</h3>
          <p class="sg-hint">
            登录与开始播放时记下「IP → 城市」。同一个账号在
            <strong>时间窗口内</strong>出现在两个城市，物理上几乎不可能，判定为异常。
            没配地理能力时这一项不会判定（见上面的提示）。
          </p>
          <el-form label-position="top" class="sg-form">
            <el-form-item label="命中后怎么办">
              <el-select v-model="draft.travel_action" :disabled="!canWrite" style="width: 100%">
                <el-option
                  v-for="opt in ACTION_OPTIONS"
                  :key="opt.value"
                  :value="opt.value as ShareGuardAction"
                  :label="opt.label"
                >
                  <div class="sg-option">
                    <span>{{ opt.label }}</span>
                    <span class="sg-option-hint">{{ opt.hint }}</span>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="时间窗口（分钟）">
              <el-input-number
                v-model="draft.travel_window_minutes"
                :min="1"
                :max="1440"
                :step="5"
                :disabled="!canWrite"
                controls-position="right"
                style="width: 160px"
              />
              <span class="sg-hint">
                窗口内换城市才算异常。出差、回家、换网络都是正常行为，窗口调太小会大量误报。
              </span>
            </el-form-item>
          </el-form>
        </div>

        <!-- 同播 -->
        <div class="sg-block">
          <h3><MonitorPlay :size="15" style="margin-right: 6px" />同播检测</h3>
          <p class="sg-hint">
            同一个账号同时有多路播放会话时判定为异常。「上限 N」= 允许 N 路并发，
            第 N+1 路才算超。一家人一台机各看各的不算超，所以别把上限设成 1。
          </p>
          <el-form label-position="top" class="sg-form">
            <el-form-item label="命中后怎么办">
              <el-select v-model="draft.concurrent_action" :disabled="!canWrite" style="width: 100%">
                <el-option
                  v-for="opt in ACTION_OPTIONS"
                  :key="opt.value"
                  :value="opt.value as ShareGuardAction"
                  :label="opt.label"
                >
                  <div class="sg-option">
                    <span>{{ opt.label }}</span>
                    <span class="sg-option-hint">{{ opt.hint }}</span>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="同时播放数上限">
              <el-input-number
                v-model="draft.concurrent_limit"
                :min="1"
                :max="20"
                :disabled="!canWrite"
                controls-position="right"
                style="width: 160px"
              />
              <span class="sg-hint">
                当前策略：上限 {{ draft.concurrent_limit }} 路。
                超出部分在「处置」档会被拦下并给客户端一个明确的提示。
              </span>
            </el-form-item>
          </el-form>
        </div>
      </div>

      <div class="sg-actions">
        <el-button
          type="primary"
          :disabled="!canWrite || !dirty"
          :loading="saving"
          @click="save"
        >
          <Save :size="14" style="margin-right: 4px" />保存
        </el-button>
        <el-button :disabled="!canWrite || !dirty" @click="revert">还原</el-button>
        <span v-if="draft" class="sg-keep">
          <span class="sg-keep-label">记录保留</span>
          <el-input-number
            v-model="draft.retention_days"
            :min="0"
            :max="3650"
            :step="10"
            :disabled="!canWrite"
            controls-position="right"
            size="small"
            style="width: 130px"
          />
          <span class="sg-hint">天。0 = 永不清理；点上方「清理过期」立即按它执行一次（不影响账号状态）。</span>
        </span>
      </div>
    </section>

    <!-- 事件流水 -->
    <section class="admin-card">
      <header class="card-header">
        <h2>判定记录</h2>
        <div class="sg-facts">
          <el-select v-model="kindFilter" style="width: 160px" @change="load">
            <el-option
              v-for="k in data?.kinds || [{ value: '', label: '全部' }]"
              :key="k.value"
              :value="k.value"
              :label="k.label"
            />
          </el-select>
        </div>
      </header>
      <p class="sg-hint">
        这里只列<strong>判定</strong>：行里的「甲城 → 乙城」是跨城市异常，「同时播放 N 路」是同播。
        「用户还在原地」这类基线记录不列在这里（判定靠它记住上一次的城市）。
      </p>
      <DataTable
        :rows="data?.events || []"
        :columns="columns"
        :loading="loading"
        :empty="emptyText"
      >
        <template #cell-username="{ row }">
          <span class="user-name">{{ row.username || '—' }}</span>
        </template>

        <template #cell-created_at="{ row }">{{ fmt(row.created_at) }}</template>

        <template #cell-kind="{ row }">
          <span class="mini-badge" :class="row.kind === 'travel' ? 'info' : 'warn'">
            {{ row.kind_label }}
          </span>
        </template>

        <template #cell-action="{ row }">
          <span
            class="mini-badge"
            :class="row.action === 'enforce' ? 'danger' : row.action === 'alert' ? 'warn' : 'muted'"
          >
            {{ row.action_label }}
          </span>
        </template>

        <template #cell-region="{ row }">
          <span v-if="row.prev_region" class="sg-region">
            {{ row.prev_region }} → {{ row.region || '未知' }}
          </span>
          <span v-else-if="row.region" class="sg-region">{{ row.region }}</span>
          <span v-else class="muted">—</span>
          <span v-if="row.ip" class="sg-ip mono">{{ row.ip }}</span>
        </template>

        <template #cell-detail="{ row }">
          <span v-if="!row.detail" class="muted">—</span>
          <span v-else>{{ row.detail }}</span>
        </template>
      </DataTable>
    </section>
  </div>
</template>

<style scoped>
.sg-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.sg-block {
  min-width: 0;
}
.sg-block h3 {
  display: flex;
  align-items: center;
  margin: 0 0 6px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}
.sg-hint {
  display: block;
  margin: 0 0 8px;
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  line-height: 1.8;
}
.sg-alert { margin: 0 0 12px; }
/* 保留天数：跟在保存/还原旁边的小控件（自己就是入口，不再指向另一个页面） */
.sg-keep {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sg-keep-label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  white-space: nowrap;
}
.sg-keep .sg-hint { margin: 0; }
.sg-form :deep(.el-form-item) { margin-bottom: 12px; }
.sg-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}
.sg-facts {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
/* 下拉里的选项：标题 + 一行「点下去会发生什么」 */
.sg-option { display: flex; flex-direction: column; gap: 2px; }
.sg-option-hint {
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.5;
}
.sg-region {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}
.sg-ip {
  display: block;
  font-size: 11.5px;
  color: var(--text-muted);
}
.user-name { font-weight: var(--font-weight-semibold); color: var(--text-primary); }
.fact.warn { color: var(--warning); font-size: var(--font-size-xs); }
.stat-tile.is-warn { border-color: var(--warning-border); }
.stat-tile.is-danger { border-color: var(--danger-border); }

/* 手机：两张策略卡竖排，按钮独占一行；统计瓦片沿用全局原语 */
@media (max-width: 767px) {
  .sg-grid { grid-template-columns: 1fr; gap: 14px; }
  .sg-actions .el-button { flex: 1 1 auto; }
  .sg-actions .sg-hint { flex: 1 1 100%; }
}
</style>