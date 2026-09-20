<script setup lang="ts">
/**
 * 兑换码管理：批量生成（积分/订阅型）、停用/启用、使用审计
 */
import { onMounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, RefreshCw } from 'lucide-vue-next'
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
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-title">运营 · 兑换码</h2>
        <p class="page-sub">积分/订阅兑换码生成与核销审计（已核销 {{ usedSummary }} 次）</p>
      </div>
      <div class="head-actions">
        <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="genVisible = true">批量生成</el-button>
      </div>
    </header>

    <el-table :data="codes" v-loading="loading" stripe>
      <el-table-column prop="code" label="兑换码" width="170">
        <template #default="{ row }">
          <span class="mono code">{{ row.code }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="row.type === 'points' ? 'success' : 'primary'" size="small">
            {{ row.type === 'points' ? '积分' : '订阅' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="奖励内容" min-width="150">
        <template #default="{ row }">{{ rewardText(row) }}</template>
      </el-table-column>
      <el-table-column label="使用" width="80">
        <template #default="{ row }">{{ row.use_count }}/{{ row.max_uses }}</template>
      </el-table-column>
      <el-table-column label="有效期至" width="110">
        <template #default="{ row }">{{ fmtTime(row.expires_at) }}</template>
      </el-table-column>
      <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="核销记录" min-width="160">
        <template #default="{ row }">
          <span v-if="!row.used_by?.length" class="muted">—</span>
          <span v-else class="muted">{{ usedNames(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :type="row.is_active ? 'warning' : 'success'" @click="toggleCode(row)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 生成对话框 -->
    <el-dialog v-model="genVisible" title="批量生成兑换码" width="480">
      <el-form label-width="90px">
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
    <el-dialog v-model="resultVisible" title="生成结果（请保存）" width="420">
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
.page { display: flex; flex-direction: column; gap: 16px; }

.page-head { display: flex; align-items: flex-start; justify-content: space-between; }
.page-title { margin: 0 0 4px; font-size: 20px; font-weight: 700; }
.page-sub { margin: 0; font-size: 13px; opacity: 0.6; }

.head-actions { display: flex; gap: 8px; }

.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.code { letter-spacing: 0.06em; font-weight: 600; }
.muted { opacity: 0.65; font-size: 12px; }
</style>
