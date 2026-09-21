<script setup lang="ts">
/**
 * 兑换码管理：批量生成（积分/订阅型）、停用/启用、使用审计
 */
import { onMounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, RefreshCw } from 'lucide-vue-next'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

/** 手机卡片：兑换码为标题，奖励/使用/状态/有效期做键值行 */
const columns: DataColumn[] = [
  { key: 'code', label: '兑换码', width: 180, mobile: 'title' },
  { key: 'type', label: '类型', width: 90 },
  { key: 'reward', label: '奖励内容', minWidth: 150 },
  { key: 'use_count', label: '使用', width: 90 },
  { key: 'expires_at', label: '有效期至', width: 120 },
  { key: 'note', label: '备注', minWidth: 120, mobile: 'hide' },
  { key: 'is_active', label: '状态', width: 90 },
  { key: 'used_by', label: '核销记录', minWidth: 160, mobile: 'hide' },
  { key: 'actions', label: '操作', width: 110, fixed: 'right', align: 'right' },
]
import {
  fetchExchangeCodes,
  createExchangeCodes,
  updateExchangeCode,
  fetchEconomyPlans,
  type ExchangeCodeRow,
  type PlanRowFull,
} from '@/api/economy'

const loading = ref(false)
const codes = ref<ExchangeCodeRow[]>([])
const plans = ref<PlanRowFull[]>([])

// 生成表单
const genVisible = ref(false)
const genForm = ref({
  count: 10,
  type: 'points' as 'points' | 'subscription',
  points_value: 50,
  plan_id: undefined as number | undefined,
  duration_days: 30,
  max_uses: 1,
  expires_days: 30,
  note: '',
})
const genLoading = ref(false)
const genResult = ref<string[]>([])
const resultVisible = ref(false)

async function load() {
  loading.value = true
  try {
    const [c, p] = await Promise.all([
      fetchExchangeCodes({ limit: 200 }),
      fetchEconomyPlans().catch(() => ({ plans: [] })),
    ])
    codes.value = c.codes
    plans.value = (p as { plans: PlanRowFull[] }).plans
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  genLoading.value = true
  try {
    const res = await createExchangeCodes({
      count: genForm.value.count,
      type: genForm.value.type,
      points_value: genForm.value.type === 'points' ? genForm.value.points_value : undefined,
      plan_id: genForm.value.type === 'subscription' ? genForm.value.plan_id : undefined,
      duration_days: genForm.value.type === 'subscription' ? genForm.value.duration_days : undefined,
      max_uses: genForm.value.max_uses,
      expires_days: genForm.value.expires_days,
      note: genForm.value.note || undefined,
    })
    genResult.value = res.codes.map(c => c.code)
    resultVisible.value = true
    genVisible.value = false
    ElMessage.success(`成功生成 ${genResult.value.length} 个兑换码`)
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '生成失败')
  } finally {
    genLoading.value = false
  }
}

async function toggleCode(row: ExchangeCodeRow) {
  try {
    await updateExchangeCode(row.id, !row.is_active)
    row.is_active = !row.is_active
    ElMessage.success(row.is_active ? '已启用' : '已停用')
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '操作失败')
  }
}

const rewardText = (row: ExchangeCodeRow) =>
  row.type === 'points' ? `${row.points_value} 积分` : `${row.plan_name || '套餐'} × ${row.duration_days} 天`

function copyAll() {
  navigator.clipboard.writeText(genResult.value.join('\n'))
  ElMessage.success('已复制全部')
}

function usedNames(row: ExchangeCodeRow): string {
  return (row.used_by || []).map(u => u.username).join('、')
}

const usedSummary = computed(() =>
  codes.value.reduce((acc, c) => acc + c.use_count, 0),
)

function fmtTime(iso?: string | null) {
  return iso ? iso.slice(0, 10) : '—'
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">兑换码</h1>
        <p class="admin-page-subtitle">积分 / 订阅兑换码生成与核销审计（已核销 {{ usedSummary }} 次）</p>
      </div>
      <div class="head-actions">
        <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="genVisible = true">批量生成</el-button>
      </div>
    </div>

    <div class="admin-card">
      <DataTable :rows="codes" :columns="columns" :loading="loading" empty="暂无兑换码">
        <template #cell-code="{ row }">
          <span class="mono code">{{ row.code }}</span>
        </template>

        <template #cell-type="{ row }">
          <el-tag :type="row.type === 'points' ? 'success' : 'primary'" size="small">
            {{ row.type === 'points' ? '积分' : '订阅' }}
          </el-tag>
        </template>

        <template #cell-reward="{ row }">{{ rewardText(row) }}</template>

        <template #cell-use_count="{ row }">{{ row.use_count }}/{{ row.max_uses }}</template>

        <template #cell-expires_at="{ row }">{{ fmtTime(row.expires_at) }}</template>

        <template #cell-note="{ row }">
          <span v-if="!row.note" class="muted">—</span>
          <span v-else>{{ row.note }}</span>
        </template>

        <template #cell-is_active="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>

        <template #cell-used_by="{ row }">
          <span v-if="!row.used_by?.length" class="muted">—</span>
          <span v-else class="muted">{{ usedNames(row) }}</span>
        </template>

        <template #cell-actions="{ row }">
          <el-button
            size="small"
            :type="row.is_active ? 'warning' : 'success'"
            plain
            @click="toggleCode(row)"
          >
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
        </template>
      </DataTable>
    </div>

    <!-- 生成对话框 -->
    <el-dialog v-model="genVisible" title="批量生成兑换码" width="480px">
      <el-form label-position="top">
        <el-form-item label="类型">
          <el-radio-group v-model="genForm.type">
            <el-radio-button value="points">积分</el-radio-button>
            <el-radio-button value="subscription">订阅</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="genForm.type === 'points'" label="积分数">
          <el-input-number v-model="genForm.points_value" :min="1" :max="100000" style="width: 100%" />
        </el-form-item>
        <template v-else>
          <el-form-item label="套餐">
            <el-select v-model="genForm.plan_id" placeholder="选择订阅套餐" style="width: 100%">
              <el-option v-for="p in plans" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="时长（天）">
            <el-input-number v-model="genForm.duration_days" :min="1" :max="3650" style="width: 100%" />
          </el-form-item>
        </template>
        <el-form-item label="数量">
          <el-input-number v-model="genForm.count" :min="1" :max="100" style="width: 100%" />
        </el-form-item>
        <el-form-item label="每码次数">
          <el-input-number v-model="genForm.max_uses" :min="1" :max="1000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="有效天数">
          <el-input-number v-model="genForm.expires_days" :min="1" :max="3650" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="genForm.note" placeholder="活动名称等（选填）" maxlength="60" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="genLoading" @click="handleGenerate">生成</el-button>
      </template>
    </el-dialog>

    <!-- 生成结果 -->
    <el-dialog v-model="resultVisible" title="生成结果（请保存）" width="420px">
      <el-input
        :model-value="genResult.join('\n')"
        type="textarea"
        :rows="10"
        readonly
        class="mono"
      />
      <template #footer>
        <el-button type="primary" @click="copyAll">复制全部</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions { display: flex; gap: 8px; }

.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.code { letter-spacing: 0.06em; font-weight: 600; color: var(--primary); }
.muted { color: var(--text-muted); font-size: 12px; }
</style>
