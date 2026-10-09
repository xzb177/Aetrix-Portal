<script setup lang="ts">
/**
 * 公益服·抽奖配置：奖品增删改 / 启用禁用 / 抽奖记录
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshCw } from 'lucide-vue-next'
import {
  fetchLotteryPrizes,
  createLotteryPrize,
  updateLotteryPrize,
  deleteLotteryPrize,
  fetchLotteryLogs,
  type LotteryPrizeRow,
  type LotteryLogRow,
} from '@/api/welfare'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const prizes = ref<LotteryPrizeRow[]>([])
const loading = ref(false)

const prizeColumns = computed<DataColumn[]>(() => [
  { key: 'name', label: '奖品名', width: 180, mobile: 'title' },
  { key: 'type', label: '类型', width: 110 },
  { key: 'value', label: '值', width: 90 },
  { key: 'probability', label: '权重', width: 90 },
  { key: 'enabled', label: '启用', width: 90 },
  { key: 'actions', label: '操作', width: 170, fixed: 'right', align: 'right' },
])

const typeMap: Record<string, string> = { days: '公益天数', points: '积分', whitelist: '白名单' }

async function loadPrizes() {
  loading.value = true
  try {
    prizes.value = await fetchLotteryPrizes()
  } finally {
    loading.value = false
  }
}

// ===== 新增/编辑弹窗 =====
const dlg = ref({
  visible: false, editing: null as LotteryPrizeRow | null,
  form: { name: '', type: 'days', value: 7, probability: 1, enabled: true },
})
function openCreate() {
  dlg.value = { visible: true, editing: null, form: { name: '', type: 'days', value: 7, probability: 1, enabled: true } }
}
function openEdit(row: LotteryPrizeRow) {
  dlg.value = { visible: true, editing: row, form: { name: row.name, type: row.type, value: row.value, probability: row.probability, enabled: row.enabled } }
}
async function doSave() {
  if (dlg.value.editing) {
    await updateLotteryPrize(dlg.value.editing.id, dlg.value.form)
    ElMessage.success('已更新')
  } else {
    await createLotteryPrize(dlg.value.form)
    ElMessage.success('已新增')
  }
  dlg.value.visible = false
  loadPrizes()
}
async function doDelete(row: LotteryPrizeRow) {
  await ElMessageBox.confirm(`删除奖品「${row.name}」？`, '确认', { type: 'warning' })
  await deleteLotteryPrize(row.id)
  ElMessage.success('已删除')
  loadPrizes()
}
async function toggleEnabled(row: LotteryPrizeRow) {
  await updateLotteryPrize(row.id, { enabled: !row.enabled })
  loadPrizes()
}

// ===== 抽奖记录 =====
const logs = ref<LotteryLogRow[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logColumns = computed<DataColumn[]>(() => [
  { key: 'username', label: '用户', width: 140, mobile: 'title' },
  { key: 'prize_name', label: '奖品', width: 180 },
  { key: 'created_at', label: '时间' },
])
async function loadLogs() {
  const res = await fetchLotteryLogs({ page: logPage.value, page_size: 20 })
  logs.value = res.items
  logTotal.value = res.total
}

onMounted(() => { loadPrizes(); loadLogs() })
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>抽奖配置</h2>
      <div class="head-actions">
        <el-button :icon="RefreshCw" @click="loadPrizes">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增奖品</el-button>
      </div>
    </div>

    <DataTable :columns="prizeColumns" :rows="prizes" :loading="loading">
      <template #cell-type="{ row }">{{ typeMap[row.type] || row.type }}</template>
      <template #cell-enabled="{ row }">
        <el-switch :model-value="row.enabled" @change="toggleEnabled(row)" />
      </template>
      <template #cell-actions="{ row }">
        <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        <el-button link type="danger" @click="doDelete(row)">删除</el-button>
      </template>
    </DataTable>

    <h3 style="margin: 20px 0 12px">抽奖记录</h3>
    <DataTable :columns="logColumns" :rows="logs">
      <template #cell-created_at="{ row }">{{ row.created_at?.replace('T', ' ').slice(0, 19) }}</template>
    </DataTable>
    <el-pagination
      v-model:current-page="logPage" :total="logTotal"
      layout="total, prev, pager, next" @change="loadLogs"
      style="margin-top: 12px; justify-content: flex-end" />

    <el-dialog v-model="dlg.visible" :title="dlg.editing ? '编辑奖品' : '新增奖品'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="dlg.form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="dlg.form.type">
            <el-option label="公益天数" value="days" />
            <el-option label="积分" value="points" />
            <el-option label="白名单" value="whitelist" />
          </el-select>
        </el-form-item>
        <el-form-item label="值"><el-input-number v-model="dlg.form.value" :min="0" /></el-form-item>
        <el-form-item label="权重"><el-input-number v-model="dlg.form.probability" :min="0" :step="0.1" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="dlg.form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" @click="doSave">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-head h2 { margin: 0; font-size: 18px; }
.head-actions { display: flex; gap: 8px; align-items: center; }
</style>
