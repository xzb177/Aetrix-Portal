<script setup lang="ts">
/**
 * 公益服·公益用户管理：列表 / 开通续期 / 取消资格 / 批量延期
 *
 * v2.55（暗房影院统一）：PageHeader + StatTile + SectionCard(flush)，
 * 逻辑与 PR #432 一致，仅模板迁移到共享组件。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { AlertTriangle, Clock3, ListFilter, Plus, RefreshCw, Search, Users, X } from 'lucide-vue-next'
import { PageHeader, SectionCard, StatTile } from '@/components/ui'
import {
  fetchWelfareUsers,
  grantWelfare,
  revokeWelfare,
  bulkExtendWelfare,
  type WelfareUserRow,
} from '@/api/welfare'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'

const list = ref<WelfareUserRow[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')

const columns = computed<DataColumn[]>(() => [
  { key: 'username', label: '用户名', width: 140, mobile: 'title' },
  { key: 'is_welfare', label: '公益', width: 80 },
  { key: 'welfare_expires_at', label: '到期时间', width: 170 },
  { key: 'days_left', label: '剩余天数', width: 100 },
  { key: 'welfare_grant_channel', label: '开通渠道', width: 120 },
  { key: 'actions', label: '操作', width: 200, fixed: 'right', align: 'right' },
])

const statActive = computed(() => list.value.filter(r => r.is_welfare).length)
const statExpiring = computed(() => list.value.filter(r => r.days_left !== null && r.days_left >= 0 && r.days_left <= 7).length)
const statExpired = computed(() => list.value.filter(r => r.days_left !== null && r.days_left < 0).length)

async function load() {
  loading.value = true
  try {
    const res = await fetchWelfareUsers({ page: page.value, page_size: pageSize.value, keyword: keyword.value })
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function fmtDate(s: string | null) {
  if (!s) return '永不过期'
  return s.replace('T', ' ').slice(0, 19)
}

// ===== 开通/续期弹窗 =====
const grantDlg = ref({ visible: false, user: null as WelfareUserRow | null, days: 30 })
function openGrant(row: WelfareUserRow) {
  grantDlg.value = { visible: true, user: row, days: 30 }
}
async function doGrant() {
  if (!grantDlg.value.user) return
  await grantWelfare({ user_id: grantDlg.value.user.id, days: grantDlg.value.days })
  ElMessage.success('已开通/续期')
  grantDlg.value.visible = false
  load()
}

async function doRevoke(row: WelfareUserRow) {
  await ElMessageBox.confirm(`确定取消 ${row.username} 的公益资格？`, '确认', { type: 'warning' })
  await revokeWelfare(row.id)
  ElMessage.success('已取消')
  load()
}

// ===== 批量延期 =====
const bulkDlg = ref({ visible: false, min_expired_days: 0, max_expired_days: 30, add_days: 30, busy: false })
async function doBulkExtend() {
  bulkDlg.value.busy = true
  try {
    const res = await bulkExtendWelfare({
      min_expired_days: bulkDlg.value.min_expired_days,
      max_expired_days: bulkDlg.value.max_expired_days,
      add_days: bulkDlg.value.add_days,
    })
    ElMessage.success(`已延期 ${res.affected} 个用户`)
    bulkDlg.value.visible = false
    load()
  } finally {
    bulkDlg.value.busy = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="公益服"
      title="公益用户"
      description="开通、续期、取消公益资格，支持按过期范围批量延期"
    >
      <template #actions>
        <el-input v-model="keyword" placeholder="搜索用户名" clearable style="width: 200px" @keyup.enter="load">
          <template #prefix><Search :size="14" /></template>
        </el-input>
        <el-button :icon="RefreshCw" @click="load">刷新</el-button>
        <el-button type="primary" @click="bulkDlg.visible = true">批量延期</el-button>
      </template>
    </PageHeader>

    <div class="stat-row">
      <StatTile label="公益中" :value="statActive" :icon="Users" tone="ok" />
      <StatTile label="7天内到期" :value="statExpiring" :icon="Clock3" tone="warn" />
      <StatTile label="已过期" :value="statExpired" :icon="AlertTriangle" tone="danger" />
      <StatTile label="全部" :value="total" :icon="ListFilter" tone="plain" />
    </div>

    <SectionCard title="用户列表" :meta="`共 ${total} 人`" flush>
      <DataTable :columns="columns" :rows="list" :loading="loading">
        <template #cell-is_welfare="{ row }">
          <el-tag :type="row.is_welfare ? 'success' : 'info'">{{ row.is_welfare ? '是' : '否' }}</el-tag>
        </template>
        <template #cell-welfare_expires_at="{ row }">{{ fmtDate(row.welfare_expires_at) }}</template>
        <template #cell-days_left="{ row }">
          <span v-if="row.days_left === null">∞</span>
          <span v-else :style="{ color: row.days_left <= 3 ? 'var(--au-danger)' : '' }">{{ row.days_left }} 天</span>
        </template>
        <template #cell-actions="{ row }">
          <el-button link type="primary" :icon="Plus" @click="openGrant(row)">续期</el-button>
          <el-button link type="danger" :icon="X" @click="doRevoke(row)">取消</el-button>
        </template>
      </DataTable>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" layout="total, prev, pager, next" @change="load"
        class="au-pagination" />
    </SectionCard>

    <!-- 开通/续期弹窗 -->
    <el-dialog v-model="grantDlg.visible" title="开通/续期公益" width="400px">
      <p v-if="grantDlg.user">用户：{{ grantDlg.user.username }}</p>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item label="天数">
          <el-input-number v-model="grantDlg.days" :min="0" :max="3650" />
          <span class="au-hint">0 = 永不过期</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="grantDlg.visible = false">取消</el-button>
        <el-button type="primary" @click="doGrant">确定</el-button>
      </template>
    </el-dialog>

    <!-- 批量延期弹窗 -->
    <el-dialog v-model="bulkDlg.visible" title="批量延期" width="420px">
      <el-form label-width="110px">
        <el-form-item label="过期天数范围">
          <el-input-number v-model="bulkDlg.min_expired_days" :min="0" style="width: 110px" />
          <span style="margin: 0 6px">~</span>
          <el-input-number v-model="bulkDlg.max_expired_days" :min="0" style="width: 110px" />
        </el-form-item>
        <el-form-item label="增加天数">
          <el-input-number v-model="bulkDlg.add_days" :min="1" :max="365" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bulkDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="bulkDlg.busy" @click="doBulkExtend">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stat-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.stat-row > * { flex: 1 1 160px; }
.au-pagination {
  margin-top: 12px;
  justify-content: flex-end;
  padding: 0 16px 16px;
}
.au-hint {
  margin-left: 8px;
  color: var(--au-text-2);
}
</style>
