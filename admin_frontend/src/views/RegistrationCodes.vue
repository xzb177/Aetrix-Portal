<script setup lang="ts">
/** 注册码管理：批量生成/停用/复制/使用审计 + 注册模式开关 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Copy, Plus, RefreshCw } from 'lucide-vue-next'
import {
  createRegistrationCodes,
  fetchRegistrationCodes,
  fetchRegistrationSettings,
  updateRegistrationCode,
  updateRegistrationSettings,
} from '@/api/admin'
import type { RegistrationCode, RegistrationSettings } from '@/types'

const codes = ref<RegistrationCode[]>([])
const settings = ref<RegistrationSettings>({ mode: 'open', message: '' })
const loading = ref(false)

const genVisible = ref(false)
const genForm = ref({ count: 5, max_uses: 1, expires_days: 30, note: '' })
const generated = ref<string[]>([])
const resultVisible = ref(false)

async function load() {
  loading.value = true
  try {
    const [c, s] = await Promise.all([fetchRegistrationCodes(), fetchRegistrationSettings()])
    codes.value = c.codes
    settings.value = s
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function generate() {
  const res = await createRegistrationCodes({
    count: genForm.value.count,
    max_uses: genForm.value.max_uses,
    expires_days: genForm.value.expires_days,
    note: genForm.value.note || undefined,
  })
  generated.value = res.codes.map((c) => c.code)
  genVisible.value = false
  resultVisible.value = true
  ElMessage.success(`已生成 ${generated.value.length} 个注册码`)
  load()
}

async function toggle(c: RegistrationCode) {
  await updateRegistrationCode(c.id, !c.is_active)
  ElMessage.success(c.is_active ? '已停用' : '已启用')
  load()
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

async function saveMode() {
  await updateRegistrationSettings({ mode: settings.value.mode, message: settings.value.message })
  ElMessage.success('注册模式已更新')
}

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 10)
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
        <h1 class="admin-page-title">注册码</h1>
        <p class="admin-page-subtitle">卡码体系：生成、审计与注册模式管控</p>
      </div>
      <div class="toolbar">
        <el-button type="primary" @click="genVisible = true">
          <Plus :size="14" style="margin-right: 4px" />批量生成
        </el-button>
        <el-button @click="load"><RefreshCw :size="14" /></el-button>
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
        <el-input v-model="settings.message" placeholder="关闭注册时展示给用户的消息" style="max-width: 420px" />
        <el-button size="small" @click="saveMode">保存</el-button>
      </div>
    </div>

    <!-- 生成弹窗 -->
    <el-dialog v-model="genVisible" title="批量生成注册码" width="420px">
      <el-form label-width="90px">
        <el-form-item label="数量"><el-input-number v-model="genForm.count" :min="1" :max="100" /></el-form-item>
        <el-form-item label="每码次数"><el-input-number v-model="genForm.max_uses" :min="1" :max="1000" /></el-form-item>
        <el-form-item label="有效天数"><el-input-number v-model="genForm.expires_days" :min="1" :max="365" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="genForm.note" placeholder="可选，如：2026 秋季活动" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" @click="generate">生成</el-button>
      </template>
    </el-dialog>

    <!-- 生成结果 -->
    <el-dialog v-model="resultVisible" title="生成结果（点击复制）" width="420px">
      <div class="gen-list">
        <button v-for="c in generated" :key="c" class="gen-code" @click="copyText(c)">{{ c }}</button>
      </div>
      <template #footer>
        <el-button @click="copyText(generated.join('\n'))">复制全部</el-button>
        <el-button type="primary" @click="resultVisible = false">完成</el-button>
      </template>
    </el-dialog>

    <!-- 码表 -->
    <div class="admin-card">
      <el-table :data="codes" v-loading="loading" style="width: 100%">
        <el-table-column label="注册码" min-width="160">
          <template #default="{ row }">
            <button class="code-chip" @click="copyText(row.code)">{{ row.code }}<Copy :size="12" /></button>
          </template>
        </el-table-column>
        <el-table-column label="使用" width="90">
          <template #default="{ row }">{{ row.use_count }} / {{ row.max_uses }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="mini-badge" :class="row.is_active ? 'ok' : 'off'">{{ row.is_active ? '生效中' : '已停用' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="有效期至" width="110">
          <template #default="{ row }">{{ fmtDate(row.expires_at) }}</template>
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
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text :type="row.is_active ? 'danger' : 'success'" @click="toggle(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 8px; }
.mode-card { margin-bottom: 14px; }
.mode-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.mode-row + .mode-row { margin-top: 12px; }
.mode-label { font-size: 13px; color: var(--color-text-secondary, #a3a3a3); }
.mode-desc { font-size: 12px; color: var(--color-text-muted, #737373); }

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

.mini-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; font-weight: 600; }
.mini-badge.ok { background: var(--success-bg); color: var(--success); }
.mini-badge.off { background: rgba(255, 255, 255, 0.08); color: var(--color-text-muted, #737373); }
.muted { color: var(--color-text-muted, #737373); }

.gen-list { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; }
.gen-code {
  font-family: ui-monospace, monospace;
  font-size: 14px;
  letter-spacing: 2px;
  text-align: center;
  background: var(--primary-bg);
  color: var(--primary);
  border: 1px dashed var(--primary-border);
  border-radius: 10px;
  padding: 10px;
  cursor: pointer;
}
</style>
