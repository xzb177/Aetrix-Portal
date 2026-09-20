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
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Copy, Plus, RefreshCw, ShieldAlert, Trash2 } from 'lucide-vue-next'
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
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const codes = ref<RegistrationCode[]>([])
const stats = ref<CodeStats | null>(null)
const settings = ref<RegistrationSettings>({ mode: 'open', message: '' })
const loading = ref(false)
const total = ref(0)

const filters = ref({ code_type: 0, state: '', keyword: '' })

const genVisible = ref(false)
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
const columns: DataColumn[] = [
  { key: 'code', label: '卡码', minWidth: 210, mobile: 'title' },
  { key: 'code_type', label: '类型', width: 96 },
  { key: 'days_text', label: '授予', width: 90 },
  { key: 'use_count', label: '用量', width: 84, mobile: 'hide' },
  { key: 'state', label: '状态', width: 92 },
  { key: 'target_username', label: '指名', width: 110, mobile: 'hide' },
  { key: 'expires_at', label: '有效期至', width: 150 },
  { key: 'note', label: '备注', minWidth: 120, mobile: 'hide' },
  { key: 'used_by', label: '使用者', minWidth: 150, mobile: 'hide' },
  { key: 'actions', label: '操作', width: 150, fixed: 'right', align: 'right' },
]

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
  try {
    const [list, stat, setting] = await Promise.all([
      fetchCodeList({
        code_type: filters.value.code_type || undefined,
        state: filters.value.state || undefined,
        keyword: filters.value.keyword || undefined,
        limit: 200,
      }),
      fetchCodeStats(),
      fetchRegistrationSettings(),
    ])
    codes.value = list.codes
    total.value = list.total
    stats.value = stat
    settings.value = setting
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openGenerate(codeType: 1 | 2 | 3) {
  genForm.value.code_type = codeType
  genForm.value.days = codeType === 2 ? 7 : 30
  genForm.value.is_decoy = false
  genForm.value.target_username = ''
  genVisible.value = true
}

async function generate() {
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
  })
  generated.value = res.codes.map((c) => ({ code: c.code, days_text: c.days_text }))
  genVisible.value = false
  resultVisible.value = true
  ElMessage.success(res.message)
  load()
}

async function toggle(row: RegistrationCode) {
  await patchRegistrationCode(row.id, { is_active: !row.is_active })
  ElMessage.success(row.is_active ? '已停用' : '已启用')
  load()
}

async function remove(row: RegistrationCode) {
  await ElMessageBox.confirm(`确认删除卡码 ${row.code}？`, '删除卡码', { type: 'warning' })
  const res = await deleteRegistrationCode(row.id)
  ElMessage.success(res.message)
  load()
}

async function saveMode() {
  await updateRegistrationSettings({ mode: settings.value.mode, message: settings.value.message })
  ElMessage.success('注册模式已更新')
}

/** 旧版「批量生成」入口保留：走类型化接口，默认注册码 */
async function quickGenerate() {
  const res = await createRegistrationCodes({
    count: 5, max_uses: 1, expires_days: 30, note: '快捷生成',
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
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">卡码管理</h1>
        <p class="admin-page-subtitle">
          注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码 —— 生成、审计与注册模式管控
        </p>
      </div>
      <div class="admin-page-actions">
        <el-button @click="quickGenerate">
          <Plus :size="14" style="margin-right: 4px" />快捷生成 5 个注册码
        </el-button>
        <el-button type="primary" @click="openGenerate(1)">
          <Plus :size="15" style="margin-right: 4px" />类型化生成
        </el-button>
        <el-button class="icon-only" @click="load" aria-label="刷新">
          <RefreshCw :size="15" />
        </el-button>
      </div>
    </div>

    <!-- 运营总览 -->
    <div v-if="stats" class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label">卡码总数</div>
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-hint">可用 {{ stats.active }} · 停用 {{ stats.disabled }}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">已过期 / 已用尽</div>
        <div class="stat-value">{{ stats.expired }} / {{ stats.used_up }}</div>
        <div class="stat-hint">到期与次数用尽的卡码</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">累计授予</div>
        <div class="stat-value">{{ stats.days_granted }} <span class="unit">天</span></div>
        <div class="stat-hint">不含白名单（永久）与诱饵码</div>
      </div>
      <div class="stat-tile" :class="{ 'is-alert': stats.decoy.triggered > 0 }">
        <div class="stat-label">诱饵码命中</div>
        <div class="stat-value">{{ stats.decoy.triggered }} / {{ stats.decoy.total }}</div>
        <div class="stat-hint">命中即自动封禁使用者账号</div>
      </div>
    </div>

    <!-- 按类型统计 -->
    <div v-if="stats?.by_type.length" class="admin-card type-row-card">
      <div v-for="t in stats.by_type" :key="t.code_type" class="type-chip">
        <span class="type-name">{{ t.code_type_name }}</span>
        <span class="type-num">{{ t.available }} 可用 / {{ t.total }} 总计</span>
        <span class="type-used">已核销 {{ t.used }} 次</span>
      </div>
    </div>

    <!-- 注册模式 -->
    <div class="admin-card mode-card">
      <div class="mode-row">
        <span class="mode-label">注册模式</span>
        <el-radio-group v-model="settings.mode" @change="saveMode">
          <el-radio-button value="open">开放注册</el-radio-button>
          <el-radio-button value="code">凭码注册</el-radio-button>
          <el-radio-button value="closed">关闭注册</el-radio-button>
        </el-radio-group>
        <span class="mode-desc">{{ modeDesc(settings.mode) }}</span>
      </div>
      <div v-if="settings.mode === 'closed'" class="mode-row">
        <span class="mode-label">关闭提示</span>
        <el-input
          v-model="settings.message"
          placeholder="关闭注册时展示给用户的消息"
          style="max-width: 420px"
        />
        <el-button size="small" @click="saveMode">保存</el-button>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="admin-card filter-bar">
      <el-select v-model="filters.code_type" placeholder="全部类型" style="width: 140px" @change="load">
        <el-option :value="0" label="全部类型" />
        <el-option :value="1" label="注册码" />
        <el-option :value="2" label="续期码" />
        <el-option :value="3" label="白名单码" />
      </el-select>
      <el-select v-model="filters.state" placeholder="全部状态" style="width: 140px" @change="load">
        <el-option value="" label="全部状态" />
        <el-option value="active" label="可用" />
        <el-option value="disabled" label="已停用" />
        <el-option value="expired" label="已过期" />
        <el-option value="used_up" label="已用尽" />
      </el-select>
      <el-input
        v-model="filters.keyword"
        placeholder="搜索卡码 / 备注 / 指名账号"
        style="max-width: 260px"
        clearable
        @keyup.enter="load"
        @clear="load"
      />
      <el-button @click="load">查询</el-button>
      <span class="filter-count">共 {{ total }} 条</span>
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
          <span class="form-hint" style="margin-left: 10px">本次授予：{{ dailyDefault }}</span>
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
          <div class="form-hint">
            <ShieldAlert :size="12" /> 蜜罐：在盗版渠道流通，使用即自动封禁账号
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" @click="generate">生成</el-button>
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

    <!-- 码表：桌面表格 / 手机卡片 -->
    <div class="admin-card">
      <DataTable :rows="codes" :columns="columns" :loading="loading" empty="还没有生成过卡码">
        <template #cell-code="{ row }">
          <div class="code-cell">
            <button class="code-chip" @click.stop="copyText(row.code)">
              {{ row.code }}<Copy :size="12" />
            </button>
            <span v-if="row.is_decoy" class="mini-badge danger">诱饵</span>
          </div>
        </template>

        <template #cell-code_type="{ row }">
          <span class="mini-badge" :class="`type-${row.code_type}`">{{ row.code_type_name }}</span>
        </template>

        <template #cell-days_text="{ row }">{{ row.days_text }}</template>

        <template #cell-use_count="{ row }">{{ row.use_count }} / {{ row.max_uses }}</template>

        <template #cell-state="{ row }">
          <span class="mini-badge" :class="row.state === 'active' ? 'ok' : 'off'">
            {{ STATE_LABEL[row.state] || row.state }}
          </span>
        </template>

        <template #cell-target_username="{ row }">
          <span v-if="!row.target_username" class="muted">—</span>
          <span v-else>{{ row.target_username }}</span>
        </template>

        <template #cell-expires_at="{ row }">{{ fmtDateTime(row.expires_at) }}</template>

        <template #cell-note="{ row }">
          <span v-if="!row.note" class="muted">—</span>
          <span v-else>{{ row.note }}</span>
        </template>

        <template #cell-used_by="{ row }">
          <span v-if="row.used_by.length === 0" class="muted">—</span>
          <span v-else>{{ usedByNames(row) }}</span>
        </template>

        <template #cell-actions="{ row }">
          <el-button
            size="small"
            :type="row.is_active ? 'danger' : 'success'"
            plain
            @click="toggle(row)"
          >
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">
            <Trash2 :size="13" style="margin-right: 2px" />删除
          </el-button>
        </template>
      </DataTable>
    </div>
  </div>
</template>

<style scoped>
/* 页面只保留自己专有的样式；卡片、徽标、统计瓦片、form-hint 都走全局原语 */

.stat-tile .unit { font-size: 14px; font-weight: 500; color: var(--text-tertiary); }
.stat-tile.is-alert { border-color: var(--danger-border); }

.type-row-card { display: flex; gap: 20px; flex-wrap: wrap; }
.type-chip { display: flex; flex-direction: column; gap: 3px; }
.type-name { font-size: var(--font-size-sm); font-weight: 600; color: var(--text-primary); }
.type-num { font-size: var(--font-size-xs); color: var(--text-tertiary); }
.type-used { font-size: var(--font-size-xs); color: var(--text-muted); }

.mode-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.mode-row + .mode-row { margin-top: 12px; }
.mode-label { font-size: var(--font-size-sm); font-weight: 600; color: var(--text-tertiary); }
.mode-desc { font-size: var(--font-size-xs); color: var(--text-muted); }

.filter-bar { margin-bottom: 0; }
.filter-count { font-size: var(--font-size-xs); color: var(--text-muted); margin-left: auto; }

.code-cell { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.code-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  letter-spacing: 0.06em;
  background: var(--primary-soft);
  color: #7fe6f6;
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-sm);
  padding: 5px 10px;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.code-chip:hover { background: var(--primary-bg); }

/* 用 .admin-page 前缀把权重抬到高于全局徽标规则，颜色才不会被覆盖 */
.admin-page .mini-badge.type-1 { background: var(--info-bg); color: #93c5fd; border-color: var(--info-border); }
.admin-page .mini-badge.type-2 { background: rgba(167, 139, 250, 0.14); color: #c4b5fd; border-color: rgba(167, 139, 250, 0.3); }
.admin-page .mini-badge.type-3 { background: var(--warning-bg); color: #fcd34d; border-color: var(--warning-border); }

.gen-list { display: flex; flex-direction: column; gap: 8px; max-height: 52vh; overflow-y: auto; }

.gen-code {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-family: var(--font-mono);
  letter-spacing: 0.06em;
  background: var(--bg-inset);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  cursor: pointer;
  text-align: left;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.gen-code:hover { border-color: var(--primary-border); background: var(--primary-soft); }
.gen-days { font-size: var(--font-size-xs); color: var(--text-tertiary); white-space: nowrap; }

/* 手机：主操作按钮铺满，次要按钮并排 */
@media (max-width: 640px) {
  .admin-page-actions > .el-button.is-primary { flex: 1 1 100%; }
}
</style>
