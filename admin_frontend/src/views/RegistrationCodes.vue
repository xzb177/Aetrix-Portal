<script setup lang="ts">
/**
 * 卡码管理（v2.6.0 / v2.6.11 改版）
 *
 * 借鉴 twilight-kotomi 的 RegCode 体系：一套入口生成并管理
 * 注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码，并给出运营总览。
 *
 * v2.6.11：改用 DataTable（桌面表格 / 手机卡片列表），并把页面里那套
 * `#737373`、`#a3a3a3` 之类的硬编码灰色换成主题令牌——这些写死的颜色既不符合
 * 后台主题，对比度也不达标（#737373 在深色上只有 3.4:1）。
 *
 * v2.6.24：卡码是**一个服一个**的——一张卡码开的是它所属服的会员（乙服的注册码
 * 在乙服的 EA 上才生效）。默认只看当前服，可切「全部服」汇总；生成时可以指定归属服。
 *
 * v2.54（暗房影院）：PageHeader（范围切换 + 生成入口）· StatTile 总览（诱饵命中才染危险色）·
 * 「注册模式」与「按类型」两张 SectionCard 并排 · 码表 flush + 统一工具条（筛选左、计数与查询右）；
 * 加载失败给可重试的错误态。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  AlertTriangle, CalendarPlus, Copy, DoorOpen, KeySquare, Layers, Plus, RefreshCw, Search, ShieldAlert, TimerOff, Trash2,
} from 'lucide-vue-next'
import { EmptyState, PageHeader, SectionCard, StatTile } from '@/components/ui'
import {
  createRegistrationCodes,
  deleteRegistrationCode,
  fetchCodeList,
  fetchCodeStats,
  fetchRegistrationSettings,
  generateCodes,
  patchRegistrationCode,
  updateRegistrationSettings,
} from '@/api/admin'
import type { CodeStats, RegistrationCode, RegistrationSettings } from '@/types'
import { useRealmStore } from '@/stores/realm'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const realm = useRealmStore()
/** 统计范围：当前服（默认）或全部服 */
const scope = ref<'realm' | 'all'>('realm')
/** 可选归属服（后端下发，跨服汇总时也能用） */
const realmOptions = ref<{ id: number; name: string }[]>([])

const codes = ref<RegistrationCode[]>([])
const stats = ref<CodeStats | null>(null)
const settings = ref<RegistrationSettings>({ mode: 'open', message: '' })
const loading = ref(false)
const total = ref(0)
/** 码表加载失败（区别于「还没有生成过卡码」） */
const loadError = ref(false)

const filters = ref({ code_type: 0, state: '', keyword: '' })

const genVisible = ref(false)
/** 生成 / 行内动作 / 模式保存进行中（按钮 loading，防重复点击） */
const genBusy = ref(false)
const rowBusyId = ref<number | null>(null)
const modeBusy = ref(false)
const genForm = ref({
  code_type: 1 as 1 | 2 | 3,
  count: 5,
  days: 30,
  max_uses: 1,
  expires_days: 30,
  algorithm: 'base32-20',
  is_decoy: false,
  target_username: '',
  note: '',
  /** 这批码开通哪个服的会员 */
  realm_id: null as number | null,
})
const generated = ref<{ code: string; days_text: string }[]>([])
const resultVisible = ref(false)

const ALGORITHMS = [
  { value: 'base32-20', label: 'Base32 · 20 位（推荐，便于手抄）' },
  { value: 'base32-16', label: 'Base32 · 16 位' },
  { value: 'hex-24', label: '十六进制 · 24 位' },
  { value: 'urlsafe-24', label: 'URL 安全 · 24 位' },
]

const TYPE_META: Record<number, { label: string; desc: string }> = {
  1: { label: '注册码', desc: '为尚无会员的账号开通会员，已有会员会被拒绝' },
  2: { label: '续期码', desc: '在当前到期时间上叠加天数' },
  3: { label: '白名单码', desc: '置为长期有效（永久）' },
}

/** 表格列定义：手机端只保留最关键的几列，其余（用量 / 指名 / 备注 / 使用者）收进详情，避免卡片过长 */
const columns = computed<DataColumn[]>(() => [
  { key: 'code', label: '卡码', minWidth: 210, mobile: 'title' },
  { key: 'code_type', label: '类型', width: 96 },
  // 卡码开哪个服的会员：跨服汇总时才需要这一列
  ...(scope.value === 'all'
    ? [{ key: 'realm', label: '归属服', minWidth: 120 } as DataColumn]
    : []),
  { key: 'days_text', label: '授予', width: 90 },
  { key: 'use_count', label: '用量', width: 84, mobile: 'hide' },
  { key: 'state', label: '状态', width: 92 },
  { key: 'target_username', label: '指名', width: 110, mobile: 'hide' },
  { key: 'expires_at', label: '有效期至', width: 150 },
  { key: 'note', label: '备注', minWidth: 120, mobile: 'hide' },
  { key: 'used_by', label: '使用者', minWidth: 150, mobile: 'hide' },
  { key: 'actions', label: '操作', width: 150, fixed: 'right', align: 'right' },
])

/** 归属服展示名（未标注 = 升级前的老卡码，按当前服算） */
function realmLabel(row: RegistrationCode): string {
  if (!row.realm_id) return '未标注'
  return row.realm_name || realmOptions.value.find((r) => r.id === row.realm_id)?.name || `#${row.realm_id}`
}

const dailyDefault = computed(() =>
  genForm.value.code_type === 3 ? '永久' : `${genForm.value.days} 天`)

const STATE_LABEL: Record<string, string> = {
  active: '可用',
  disabled: '已停用',
  expired: '已过期',
  used_up: '已用尽',
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    // realm_id=0 → 全部服；其余按服过滤（后端以当前服作为兜底）
    const scopeId = scope.value === 'all' ? 0 : (realm.activeId ?? 0)
    const [list, stat, setting] = await Promise.all([
      fetchCodeList({
        code_type: filters.value.code_type || undefined,
        state: filters.value.state || undefined,
        keyword: filters.value.keyword || undefined,
        realm_id: scopeId,
        limit: 200,
      }),
      fetchCodeStats(scopeId),
      fetchRegistrationSettings(),
    ])
    codes.value = list.codes
    total.value = list.total
    stats.value = stat
    settings.value = setting
    if (list.realms?.length) realmOptions.value = list.realms
  } catch {
    // 错误提示由 HTTP 拦截器统一处理；这里只记下失败，给出重试入口
    loadError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)

const hasFilter = computed(() => !!(filters.value.code_type || filters.value.state || filters.value.keyword))

function resetFilters() {
  filters.value = { code_type: 0, state: '', keyword: '' }
  load()
}

/** 类型徽章：注册 / 续期 / 白名单 三种各一档（不再用紫色） */
const TYPE_BADGE: Record<number, string> = { 1: 'au-badge-info', 2: 'au-badge-amber', 3: 'badge-warn' }

function openGenerate(codeType: 1 | 2 | 3) {
  genForm.value.code_type = codeType
  genForm.value.days = codeType === 2 ? 7 : 30
  genForm.value.is_decoy = false
  genForm.value.target_username = ''
  // 默认开当前服的会员（就是列表正在看的这个服）
  genForm.value.realm_id = realm.activeId ?? null
  genVisible.value = true
}

async function generate() {
  genBusy.value = true
  try {
    const res = await generateCodes({
      code_type: genForm.value.code_type,
      count: genForm.value.count,
      days: genForm.value.code_type === 3 ? -1 : genForm.value.days,
      max_uses: genForm.value.max_uses,
      expires_days: genForm.value.expires_days,
      algorithm: genForm.value.algorithm,
      is_decoy: genForm.value.is_decoy,
      target_username: genForm.value.target_username || undefined,
      note: genForm.value.note || undefined,
      realm_id: genForm.value.realm_id ?? undefined,
    })
    generated.value = res.codes.map((c) => ({ code: c.code, days_text: c.days_text }))
    genVisible.value = false
    resultVisible.value = true
    ElMessage.success(res.message)
    load()
  } finally {
    genBusy.value = false
  }
}

async function toggle(row: RegistrationCode) {
  rowBusyId.value = row.id
  try {
    await patchRegistrationCode(row.id, { is_active: !row.is_active })
    ElMessage.success(row.is_active ? '已停用' : '已启用')
    load()
  } finally {
    rowBusyId.value = null
  }
}

async function remove(row: RegistrationCode) {
  await ElMessageBox.confirm(`确认删除卡码 ${row.code}？`, '删除卡码', { type: 'warning' })
  rowBusyId.value = row.id
  try {
    const res = await deleteRegistrationCode(row.id)
    ElMessage.success(res.message)
    load()
  } finally {
    rowBusyId.value = null
  }
}

async function saveMode() {
  modeBusy.value = true
  try {
    await updateRegistrationSettings({ mode: settings.value.mode, message: settings.value.message })
    ElMessage.success('注册模式已更新')
  } finally {
    modeBusy.value = false
  }
}

/** 旧版「批量生成」入口保留：走类型化接口，默认注册码 */
async function quickGenerate() {
  const res = await createRegistrationCodes({
    count: 5, max_uses: 1, expires_days: 30, note: '快捷生成',
    // 快捷生成不看列表范围：永远开「当前服」的会员（要选服请用类型化生成）
    realm_id: realm.activeId ?? undefined,
  })
  generated.value = res.codes.map((c) => ({ code: c.code, days_text: '30 天' }))
  resultVisible.value = true
  ElMessage.success(`已生成 ${generated.value.length} 个注册码`)
  load()
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

function fmtDateTime(s: string | null): string {
  return s ? fmtDate(s) : '—'
}

function modeDesc(mode: string): string {
  if (mode === 'open') return '开放注册：任何人可注册'
  if (mode === 'code') return '凭码注册：必须携带有效注册码'
  return '关闭注册：暂停新用户加入'
}

function usedByNames(row: RegistrationCode): string {
  return row.used_by.map((u) => u.username).join('、')
}
</script>

<template>
  <div class="admin-page codes-page">
    <PageHeader
      eyebrow="运营中心"
      title="卡码管理"
      description="注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码——生成、审计与注册模式管控。卡码开的是它所属服的会员。"
    >
      <template #actions>
        <el-radio-group v-model="scope" @change="load">
          <el-radio-button value="realm">当前服</el-radio-button>
          <el-radio-button value="all">全部服</el-radio-button>
        </el-radio-group>
        <el-button :icon="RefreshCw" :loading="loading" aria-label="刷新" @click="load">刷新</el-button>
        <el-button :icon="Plus" @click="quickGenerate">快捷生成 5 个注册码</el-button>
        <el-button type="primary" :icon="Plus" @click="openGenerate(1)">类型化生成</el-button>
      </template>
    </PageHeader>

    <!-- 运营总览：数字走正文色，只有诱饵码被命中才染危险色 -->
    <section v-if="stats" class="stat-row" aria-label="卡码总览">
      <StatTile label="卡码总数" :value="stats.total" :icon="KeySquare" :hint="`可用 ${stats.active} · 停用 ${stats.disabled}`" />
      <StatTile
        label="已过期 / 已用尽"
        :value="stats.expired"
        :suffix="`/ ${stats.used_up}`"
        :icon="TimerOff"
        hint="到期与次数用尽的卡码"
      />
      <StatTile
        label="累计授予"
        :value="stats.days_granted"
        suffix="天"
        :icon="CalendarPlus"
        hint="不含白名单（永久）与诱饵码"
      />
      <StatTile
        label="诱饵码命中"
        :value="stats.decoy.triggered"
        :suffix="`/ ${stats.decoy.total}`"
        :icon="ShieldAlert"
        :tone="stats.decoy.triggered > 0 ? 'danger' : 'plain'"
        hint="命中即自动封禁使用者账号"
      />
    </section>

    <div class="split">
      <!-- 注册模式：全站级开关，切换即保存 -->
      <SectionCard title="注册模式" :icon="DoorOpen" :description="modeDesc(settings.mode)">
        <div class="mode-body">
          <el-radio-group v-model="settings.mode" @change="saveMode">
            <el-radio-button value="open">开放注册</el-radio-button>
            <el-radio-button value="code">凭码注册</el-radio-button>
            <el-radio-button value="closed">关闭注册</el-radio-button>
          </el-radio-group>
          <div v-if="settings.mode === 'closed'" class="mode-msg">
            <label class="mode-label" for="close-msg">关闭提示</label>
            <div class="mode-msg-row">
              <el-input id="close-msg" v-model="settings.message" placeholder="关闭注册时展示给用户的消息" />
              <el-button :loading="modeBusy" @click="saveMode">保存</el-button>
            </div>
          </div>
        </div>
      </SectionCard>

      <!-- 按类型统计 -->
      <SectionCard title="按类型" :icon="Layers" flush>
        <ul v-if="stats?.by_type.length" class="type-list">
          <li v-for="t in stats.by_type" :key="t.code_type" class="type-row">
            <span class="au-badge" :class="TYPE_BADGE[t.code_type] || 'au-badge-muted'">{{ t.code_type_name }}</span>
            <span class="type-num"><strong>{{ t.available }}</strong> 可用 / {{ t.total }} 总计</span>
            <span class="type-used">已核销 {{ t.used }} 次</span>
          </li>
        </ul>
        <EmptyState v-else compact title="还没有按类型的统计" description="生成第一批卡码后这里会分类统计。" />
      </SectionCard>
    </div>

    <!-- 生成弹窗 -->
    <el-dialog v-model="genVisible" title="生成卡码" width="520px">
      <el-form label-position="top">
        <el-form-item label="卡码类型">
          <el-radio-group v-model="genForm.code_type">
            <el-radio-button :value="1">注册码</el-radio-button>
            <el-radio-button :value="2">续期码</el-radio-button>
            <el-radio-button :value="3">白名单码</el-radio-button>
          </el-radio-group>
          <div class="form-hint">{{ TYPE_META[genForm.code_type].desc }}</div>
        </el-form-item>
        <!-- 卡码开哪个服的会员：注册码决定新用户拿到哪个服的会员 -->
        <el-form-item label="归属服">
          <el-select v-model="genForm.realm_id" placeholder="选择归属服" style="width: 220px">
            <el-option v-for="r in realmOptions" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
          <div class="form-hint">核销后开通的是该服的会员，也只在该服的播放节点上生效。</div>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="genForm.count" :min="1" :max="200" />
        </el-form-item>
        <el-form-item label="会员天数">
          <el-input-number
            v-model="genForm.days"
            :min="1"
            :max="3650"
            :disabled="genForm.code_type === 3"
          />
          <span class="form-hint inline-hint">本次授予：{{ dailyDefault }}</span>
        </el-form-item>
        <el-form-item label="每码次数">
          <el-input-number v-model="genForm.max_uses" :min="1" :max="1000" />
        </el-form-item>
        <el-form-item label="有效天数">
          <el-input-number v-model="genForm.expires_days" :min="1" :max="3650" />
          <div class="form-hint">卡码自身的兑换期限，过期作废</div>
        </el-form-item>
        <el-form-item label="随机算法">
          <el-select v-model="genForm.algorithm" style="width: 100%">
            <el-option v-for="a in ALGORITHMS" :key="a.value" :value="a.value" :label="a.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="指名账号">
          <el-input v-model="genForm.target_username" placeholder="留空表示不限；填写后仅该账号可用" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="genForm.note" placeholder="可选，如：2026 秋季活动" />
        </el-form-item>
        <el-form-item label="诱饵码">
          <el-switch v-model="genForm.is_decoy" />
          <div class="form-hint decoy-hint">
            <ShieldAlert :size="12" /> 蜜罐：在盗版渠道流通，使用即自动封禁账号
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="genBusy" @click="generate">生成</el-button>
      </template>
    </el-dialog>

    <!-- 生成结果 -->
    <el-dialog v-model="resultVisible" title="生成结果（点击复制）" width="460px">
      <div class="gen-list">
        <button v-for="c in generated" :key="c.code" class="gen-code" @click="copyText(c.code)">
          {{ c.code }}<span class="gen-days">{{ c.days_text }}</span>
        </button>
      </div>
      <template #footer>
        <el-button @click="copyText(generated.map((c) => c.code).join('\n'))">复制全部</el-button>
        <el-button type="primary" @click="resultVisible = false">完成</el-button>
      </template>
    </el-dialog>

    <!-- 码表：筛选在左、计数与查询在右；桌面表格 / 手机卡片 -->
    <SectionCard
      title="全部卡码"
      :icon="KeySquare"
      :meta="`共 ${total} 条${scope === 'realm' ? '（当前服）' : '（全部服）'}`"
      flush
    >
      <div class="view-toolbar">
        <div class="view-toolbar__filters">
          <el-input
            v-model="filters.keyword"
            class="f-search"
            placeholder="搜索卡码 / 备注 / 指名账号"
            clearable
            @keyup.enter="load"
            @clear="load"
          >
            <template #prefix><Search :size="14" /></template>
          </el-input>
          <el-select v-model="filters.code_type" class="f-select" placeholder="全部类型" @change="load">
            <el-option :value="0" label="全部类型" />
            <el-option :value="1" label="注册码" />
            <el-option :value="2" label="续期码" />
            <el-option :value="3" label="白名单码" />
          </el-select>
          <el-select v-model="filters.state" class="f-select" placeholder="全部状态" @change="load">
            <el-option value="" label="全部状态" />
            <el-option value="active" label="可用" />
            <el-option value="disabled" label="已停用" />
            <el-option value="expired" label="已过期" />
            <el-option value="used_up" label="已用尽" />
          </el-select>
        </div>
        <div class="view-toolbar__actions">
          <el-button v-if="hasFilter" text @click="resetFilters">清空筛选</el-button>
          <el-button type="primary" :icon="Search" @click="load">查询</el-button>
        </div>
      </div>

      <EmptyState v-if="loadError && !codes.length" :icon="AlertTriangle" title="卡码加载失败" description="网络或服务暂时不可用，稍后重试。">
        <template #actions><el-button :loading="loading" @click="load">重试</el-button></template>
      </EmptyState>

      <DataTable v-else class="flush-table" :rows="codes" :columns="columns" :loading="loading" empty="还没有生成过卡码">
        <template #cell-code="{ row }">
          <div class="code-cell">
            <button type="button" class="code-chip" title="点击复制" @click.stop="copyText(row.code)">
              {{ row.code }}<Copy :size="12" />
            </button>
            <span v-if="row.is_decoy" class="au-badge au-badge-rose">诱饵</span>
          </div>
        </template>

        <template #cell-code_type="{ row }">
          <span class="au-badge" :class="TYPE_BADGE[row.code_type] || 'au-badge-muted'">{{ row.code_type_name }}</span>
        </template>

        <template #cell-realm="{ row }">
          <span class="au-badge" :class="row.realm_id ? 'au-badge-info' : 'au-badge-muted'">{{ realmLabel(row) }}</span>
        </template>

        <template #cell-days_text="{ row }">{{ row.days_text }}</template>

        <template #cell-use_count="{ row }"><span class="num">{{ row.use_count }} / {{ row.max_uses }}</span></template>

        <template #cell-state="{ row }">
          <span class="au-badge" :class="row.state === 'active' ? 'au-badge-green' : 'au-badge-muted'">
            {{ STATE_LABEL[row.state] || row.state }}
          </span>
        </template>

        <template #cell-target_username="{ row }">
          <span v-if="!row.target_username" class="faint">—</span>
          <span v-else>{{ row.target_username }}</span>
        </template>

        <template #cell-expires_at="{ row }"><span class="num">{{ fmtDateTime(row.expires_at) }}</span></template>

        <template #cell-note="{ row }">
          <span v-if="!row.note" class="faint">—</span>
          <span v-else>{{ row.note }}</span>
        </template>

        <template #cell-used_by="{ row }">
          <span v-if="row.used_by.length === 0" class="faint">—</span>
          <span v-else>{{ usedByNames(row) }}</span>
        </template>

        <template #cell-actions="{ row }">
          <el-button
            size="small"
            :type="row.is_active ? 'warning' : 'success'"
            plain
            :loading="rowBusyId === row.id"
            @click="toggle(row)"
          >
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button size="small" type="danger" plain :icon="Trash2" :loading="rowBusyId === row.id" @click="remove(row)">
            删除
          </el-button>
        </template>

        <template #empty>
          <EmptyState
            compact
            :icon="KeySquare"
            :title="hasFilter ? '没有符合条件的卡码' : '还没有生成过卡码'"
            :description="hasFilter ? '换个条件，或清空筛选看全部。' : '用右上角「类型化生成」发一批注册码 / 续期码。'"
          >
            <template #actions>
              <el-button v-if="hasFilter" size="small" @click="resetFilters">清空筛选</el-button>
              <el-button v-else size="small" type="primary" :icon="Plus" @click="openGenerate(1)">类型化生成</el-button>
            </template>
          </EmptyState>
        </template>
      </DataTable>
    </SectionCard>
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

/* 注册模式 + 按类型：并排，窄屏叠起来 */
.split {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.mode-body { display: flex; flex-direction: column; gap: 14px; }
.mode-msg { display: flex; flex-direction: column; gap: 6px; }
.mode-label { font-size: 12px; color: var(--au-text-3); }
.mode-msg-row { display: flex; gap: 8px; }

.type-list { list-style: none; margin: 0; padding: 0; }
.type-row {
  display: flex;
  align-items: center;
  gap: 8px 12px;
  flex-wrap: wrap;
  padding: 10px 20px;
  font-size: 12.5px;
}
.type-row + .type-row { border-top: 1px solid var(--au-border); }
.type-num { flex: 1 1 auto; color: var(--au-text-2); font-variant-numeric: tabular-nums; }
.type-num strong { color: var(--au-text); font-weight: 700; }
.type-used { color: var(--au-text-4); font-variant-numeric: tabular-nums; }

/* ---------- 工具条：筛选在左、动作在右 ---------- */
.view-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px 12px;
  flex-wrap: wrap;
  padding: 4px 20px 14px;
  border-bottom: 1px solid var(--au-border);
}
.view-toolbar__filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: 1 1 auto; min-width: 0; }
.view-toolbar__actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.f-search { width: 240px; }
.f-select { width: 130px; }

.flush-table :deep(.dt-cards) { padding: 12px 12px 8px; }

/* ---------- 单元格 ---------- */
.num { font-variant-numeric: tabular-nums; }
.faint { color: var(--au-text-4); }
.badge-warn { background: var(--au-warning-soft); color: var(--au-warning); border-color: var(--au-warning-border); }
.code-cell { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.code-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  letter-spacing: 0.06em;
  color: var(--au-primary);
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-sm);
  cursor: pointer;
  transition: background var(--au-fast) var(--au-ease);
}
.code-chip:hover { background: var(--au-primary-mid); }
.code-chip:focus-visible { outline: 2px solid var(--au-border-focus); outline-offset: 2px; }

/* ---------- 弹窗 ---------- */
.inline-hint { margin-left: 10px; }
.decoy-hint { display: inline-flex; align-items: center; gap: 4px; }

.gen-list { display: flex; flex-direction: column; gap: 8px; max-height: 52vh; overflow-y: auto; }
.gen-code {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  font-family: var(--font-mono);
  letter-spacing: 0.06em;
  text-align: left;
  color: var(--au-text);
  background: var(--au-surface-2);
  border: 1px solid var(--au-border);
  border-radius: var(--au-r-md);
  cursor: pointer;
  transition: border-color var(--au-fast) var(--au-ease), background var(--au-fast) var(--au-ease);
}
.gen-code:hover { border-color: var(--au-primary-border); background: var(--au-primary-soft); }
.gen-days { font-size: 12px; color: var(--au-text-3); white-space: nowrap; }

@media (max-width: 1000px) {
  .split { grid-template-columns: minmax(0, 1fr); }
}

@media (max-width: 768px) {
  .view-toolbar { padding: 2px 16px 12px; }
  .view-toolbar__filters > .f-search { flex: 1 1 100%; width: auto; }
  .view-toolbar__filters > .f-select { flex: 1 1 120px; width: auto; }
  .view-toolbar__actions { width: 100%; justify-content: flex-end; }
  .type-row { padding: 10px 16px; }
  .mode-body :deep(.el-radio-group) { display: flex; width: 100%; }
  .mode-body :deep(.el-radio-button) { flex: 1; }
  .mode-body :deep(.el-radio-button__inner) { width: 100%; }
}
</style>
