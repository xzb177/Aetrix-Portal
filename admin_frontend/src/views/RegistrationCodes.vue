<script setup lang="ts">
/**
 * 卡码管理（v2.6.0）
 *
 * 借鉴 twilight-kotomi 的 RegCode 体系：一套入口生成并管理
 * 注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码，并给出运营总览。
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
      <div class="toolbar">
        <el-button @click="quickGenerate">
          <Plus :size="14" style="margin-right: 4px" />快捷生成 5 个注册码
        </el-button>
        <el-button type="primary" @click="openGenerate(1)">
          <Plus :size="14" style="margin-right: 4px" />类型化生成
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
      </div>
    </div>

    <!-- 运营总览 -->
    <div v-if="stats" class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">卡码总数</div>
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-hint">可用 {{ stats.active }} · 停用 {{ stats.disabled }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已过期 / 已用尽</div>
        <div class="stat-value">{{ stats.expired }} / {{ stats.used_up }}</div>
        <div class="stat-hint">到期与次数用尽的卡码</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">累计授予</div>
        <div class="stat-value">{{ stats.days_granted }} 天</div>
        <div class="stat-hint">不含白名单（永久）与诱饵码</div>
      </div>
      <div class="stat-card" :class="{ danger: stats.decoy.triggered > 0 }">
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
      <el-form label-width="96px">
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
          <span class="form-hint" style="margin-left: 10px">卡码自身的兑换期限，过期作废</span>
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
          <span class="form-hint" style="margin-left: 10px">
            <ShieldAlert :size="12" /> 蜜罐：在盗版渠道流通，使用即自动封禁账号
          </span>
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

    <!-- 码表 -->
    <div class="admin-card">
      <el-table :data="codes" v-loading="loading" style="width: 100%">
        <el-table-column label="卡码" min-width="200">
          <template #default="{ row }">
            <button class="code-chip" @click="copyText(row.code)">
              {{ row.code }}<Copy :size="12" />
            </button>
            <span v-if="row.is_decoy" class="mini-badge danger">诱饵</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="96">
          <template #default="{ row }">
            <span class="mini-badge" :class="`type-${row.code_type}`">{{ row.code_type_name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="授予" width="90">
          <template #default="{ row }">{{ row.days_text }}</template>
        </el-table-column>
        <el-table-column label="用量" width="80">
          <template #default="{ row }">{{ row.use_count }} / {{ row.max_uses }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="mini-badge" :class="row.state === 'active' ? 'ok' : 'off'">
              {{ STATE_LABEL[row.state] || row.state }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="指名" width="110">
          <template #default="{ row }">
            <span v-if="!row.target_username" class="muted">—</span>
            <span v-else>{{ row.target_username }}</span>
          </template>
        </el-table-column>
        <el-table-column label="有效期至" width="150">
          <template #default="{ row }">{{ fmtDateTime(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column label="备注" min-width="120">
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
        <el-table-column label="使用者" min-width="150">
          <template #default="{ row }">
            <span v-if="row.used_by.length === 0" class="muted">—</span>
            <span v-else>{{ usedByNames(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              text
              :type="row.is_active ? 'danger' : 'success'"
              @click="toggle(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
            <el-button size="small" text type="danger" @click="remove(row)">
              <Trash2 :size="13" />
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.stat-card {
  background: var(--card-bg, #171717);
  border: 1px solid var(--border-color, #262626);
  border-radius: 12px;
  padding: 14px 16px;
}
.stat-card.danger { border-color: rgba(239, 68, 68, 0.45); }
.stat-label { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }
.stat-value { font-size: 22px; font-weight: 600; margin: 4px 0 2px; }
.stat-hint { font-size: 11px; color: var(--color-text-muted, #737373); }

.type-row-card { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 14px; }
.type-chip { display: flex; flex-direction: column; gap: 2px; }
.type-name { font-size: 13px; font-weight: 600; }
.type-num { font-size: 12px; color: var(--color-text-secondary, #a3a3a3); }
.type-used { font-size: 11px; color: var(--color-text-muted, #737373); }

.mode-card { margin-bottom: 14px; }
.mode-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.mode-row + .mode-row { margin-top: 12px; }
.mode-label { font-size: 13px; color: var(--color-text-secondary, #a3a3a3); }
.mode-desc { font-size: 12px; color: var(--color-text-muted, #737373); }

.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.filter-count { font-size: 12px; color: var(--color-text-muted, #737373); margin-left: auto; }

.form-hint {
  font-size: 12px;
  color: var(--color-text-muted, #737373);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
}

.code-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  letter-spacing: 1px;
  background: var(--primary-bg);
  color: var(--primary);
  border: none;
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
}
.code-chip:hover { filter: brightness(1.15); }
.mini-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  background: var(--border-color, #262626);
  color: var(--color-text-secondary, #a3a3a3);
}
.mini-badge.ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.mini-badge.off { background: rgba(115, 115, 115, 0.2); color: #a3a3a3; }
.mini-badge.danger { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.mini-badge.type-1 { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.mini-badge.type-2 { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
.mini-badge.type-3 { background: rgba(250, 204, 21, 0.15); color: #facc15; }
.muted { color: var(--color-text-muted, #737373); }

.gen-list { display: flex; flex-direction: column; gap: 8px; }
.gen-code {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: ui-monospace, monospace;
  letter-spacing: 1px;
  background: var(--primary-bg);
  color: var(--primary);
  border: none;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  text-align: left;
}
.gen-code:hover { filter: brightness(1.15); }
.gen-days { font-size: 12px; opacity: 0.75; }
</style>
