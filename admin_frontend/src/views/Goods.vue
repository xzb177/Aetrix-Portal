<script setup lang="ts">
/**
 * 商品管理：订阅套餐 CRUD + 充值套餐 CRUD
 *
 * v2.6.20：订阅套餐是**一个服一个**的（买哪份就开哪个服的会员），所以套餐表里显示归属服，
 * 新建 / 编辑时也能改归属（把套餐从一个服搬到另一个服）。积分充值套餐是全服共用的。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshCw } from 'lucide-vue-next'
import DataTable from '@/components/DataTable.vue'
import type { DataColumn } from '@/components/DataTable.vue'
import { useRealmStore } from '@/stores/realm'

const realm = useRealmStore()
/** 套餐统计范围：当前服（默认）或全部服 */
const scope = ref<'realm' | 'all'>('realm')

const planColumns: DataColumn[] = [
  { key: 'name', label: '名称', width: 170, mobile: 'title' },
  { key: 'realm_name', label: '归属服', width: 130 },
  { key: 'description', label: '描述', minWidth: 170, mobile: 'hide' },
  { key: 'price', label: '价格', width: 100 },
  { key: 'duration_days', label: '时长', width: 90 },
  { key: 'is_popular', label: '推荐', width: 80, mobile: 'hide' },
  { key: 'is_active', label: '状态', width: 90 },
  { key: 'sort_order', label: '排序', width: 80, mobile: 'hide' },
  { key: 'actions', label: '操作', width: 150, fixed: 'right', align: 'right' },
]

const pkgColumns: DataColumn[] = [
  { key: 'name', label: '名称', width: 170, mobile: 'title' },
  { key: 'amount', label: '积分', width: 110 },
  { key: 'total', label: '合计', width: 100 },
  { key: 'price', label: '价格', width: 100 },
  { key: 'is_popular', label: '推荐', width: 80, mobile: 'hide' },
  { key: 'is_active', label: '状态', width: 90 },
  { key: 'sort_order', label: '排序', width: 80, mobile: 'hide' },
  { key: 'actions', label: '操作', width: 150, fixed: 'right', align: 'right' },
]
import {
  fetchEconomyPlans,
  createEconomyPlan,
  updateEconomyPlan,
  deleteEconomyPlan,
  fetchEconomyPackages,
  createEconomyPackage,
  updateEconomyPackage,
  deleteEconomyPackage,
  type PlanRowFull,
  type PackageRow,
} from '@/api/economy'

const loading = ref(false)
const plans = ref<PlanRowFull[]>([])
const packages = ref<PackageRow[]>([])

// ===== 套餐表单 =====
const planVisible = ref(false)
const planEditing = ref<PlanRowFull | null>(null)
const planForm = ref({
  name: '', description: '', price: 19.9, duration_days: 30,
  features: '', is_active: true, is_popular: false, sort_order: 0,
  realm_id: null as number | null,
})

/** 可选的归属服：默认取面板当前服 */
const realmOptions = computed(() => realm.realms)

function openPlanCreate() {
  planEditing.value = null
  planForm.value = {
    name: '', description: '', price: 19.9, duration_days: 30, features: '',
    is_active: true, is_popular: false, sort_order: 0,
    realm_id: realm.activeId,
  }
  planVisible.value = true
}

function openPlanEdit(row: PlanRowFull) {
  planEditing.value = row
  planForm.value = {
    name: row.name,
    description: row.description || '',
    price: row.price,
    duration_days: row.duration_days,
    features: (row.features || []).join('\n'),
    is_active: row.is_active,
    is_popular: row.is_popular,
    sort_order: row.sort_order,
    realm_id: row.realm_id ?? realm.activeId,
  }
  planVisible.value = true
}

async function savePlan() {
  const f = planForm.value
  if (!f.name.trim()) { ElMessage.warning('请输入套餐名称'); return }
  const payload = {
    name: f.name.trim(),
    description: f.description.trim() || null,
    price: f.price,
    duration_days: f.duration_days,
    features: f.features.split('\n').map(s => s.trim()).filter(Boolean),
    is_active: f.is_active,
    is_popular: f.is_popular,
    sort_order: f.sort_order,
    // 一个服一个：留空时后端归到面板当前服
    realm_id: f.realm_id ?? undefined,
  }
  try {
    if (planEditing.value) {
      await updateEconomyPlan(planEditing.value.id, payload)
      ElMessage.success('套餐已更新')
    } else {
      await createEconomyPlan(payload)
      ElMessage.success('套餐已创建')
    }
    planVisible.value = false
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '保存失败')
  }
}

async function removePlan(row: PlanRowFull) {
  await ElMessageBox.confirm(`确认删除套餐「${row.name}」？已有订单引用时会自动改为停用。`, '删除套餐', { type: 'warning' })
  try {
    const res = await deleteEconomyPlan(row.id)
    ElMessage.success(res.message || '已删除')
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '删除失败')
  }
}

// ===== 充值套餐表单 =====
const pkgVisible = ref(false)
const pkgEditing = ref<PackageRow | null>(null)
const pkgForm = ref({ name: '', amount: 500, price: 25, bonus: 50, is_active: true, is_popular: false, sort_order: 0 })

function openPkgCreate() {
  pkgEditing.value = null
  pkgForm.value = { name: '', amount: 500, price: 25, bonus: 50, is_active: true, is_popular: false, sort_order: 0 }
  pkgVisible.value = true
}

function openPkgEdit(row: PackageRow) {
  pkgEditing.value = row
  pkgForm.value = {
    name: row.name, amount: row.amount, price: row.price, bonus: row.bonus,
    is_active: row.is_active, is_popular: row.is_popular, sort_order: row.sort_order,
  }
  pkgVisible.value = true
}

async function savePkg() {
  const f = pkgForm.value
  if (!f.name.trim()) { ElMessage.warning('请输入套餐名称'); return }
  const payload = { ...f, name: f.name.trim() }
  try {
    if (pkgEditing.value) {
      await updateEconomyPackage(pkgEditing.value.id, payload)
      ElMessage.success('充值套餐已更新')
    } else {
      await createEconomyPackage(payload)
      ElMessage.success('充值套餐已创建')
    }
    pkgVisible.value = false
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '保存失败')
  }
}

async function removePkg(row: PackageRow) {
  await ElMessageBox.confirm(`确认删除充值套餐「${row.name}」？`, '删除', { type: 'warning' })
  try {
    const res = await deleteEconomyPackage(row.id)
    ElMessage.success(res.message || '已删除')
    load()
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '删除失败')
  }
}

async function load() {
  loading.value = true
  try {
    const [p, k] = await Promise.all([
      fetchEconomyPlans(scope.value === 'all' ? 0 : undefined),
      fetchEconomyPackages(),
    ])
    plans.value = p.plans
    packages.value = k.packages
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <div class="admin-page-header">
      <div>
        <h1 class="admin-page-title">商品与套餐</h1>
        <p class="admin-page-subtitle">
          订阅套餐与积分充值套餐配置 · 订阅套餐一个服一个，充值套餐全服共用
        </p>
      </div>
      <div class="page-actions">
        <el-radio-group v-model="scope" size="small" @change="load">
          <el-radio-button value="realm">当前服套餐</el-radio-button>
          <el-radio-button value="all">全部服套餐</el-radio-button>
        </el-radio-group>
        <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 订阅套餐 -->
    <section class="admin-card block">
      <header class="block-head">
        <h3>订阅套餐</h3>
        <el-button type="primary" size="small" :icon="Plus" @click="openPlanCreate">新增套餐</el-button>
      </header>
      <DataTable :rows="plans" :columns="planColumns" :loading="loading" empty="还没有订阅套餐">
        <template #cell-name="{ row }">
          <span class="item-name">{{ row.name }}</span>
        </template>

        <template #cell-realm_name="{ row }">
          <el-tag size="small" :type="row.realm_name ? 'info' : 'warning'">
            {{ row.realm_name || '未标注' }}
          </el-tag>
        </template>

        <template #cell-description="{ row }">
          <span v-if="!row.description" class="muted">—</span>
          <span v-else>{{ row.description }}</span>
        </template>

        <template #cell-price="{ row }">
          <span class="price">¥ {{ Number(row.price).toFixed(2) }}</span>
        </template>

        <template #cell-duration_days="{ row }">{{ row.duration_days }} 天</template>

        <template #cell-is_popular="{ row }">
          <el-tag v-if="row.is_popular" type="warning" size="small">推荐</el-tag>
          <span v-else class="muted">—</span>
        </template>

        <template #cell-is_active="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '上架' : '下架' }}
          </el-tag>
        </template>

        <template #cell-sort_order="{ row }">{{ row.sort_order }}</template>

        <template #cell-actions="{ row }">
          <el-button size="small" @click="openPlanEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="removePlan(row)">删除</el-button>
        </template>
      </DataTable>
    </section>

    <!-- 充值套餐 -->
    <section class="admin-card block">
      <header class="block-head">
        <h3>积分充值套餐</h3>
        <el-button type="primary" size="small" :icon="Plus" @click="openPkgCreate">新增套餐</el-button>
      </header>
      <DataTable :rows="packages" :columns="pkgColumns" :loading="loading" empty="还没有充值套餐">
        <template #cell-name="{ row }">
          <span class="item-name">{{ row.name }}</span>
        </template>

        <template #cell-amount="{ row }">{{ row.amount }} + {{ row.bonus }}</template>

        <template #cell-total="{ row }">
          <span class="price">{{ row.amount + row.bonus }}</span>
        </template>

        <template #cell-price="{ row }">
          <span class="price">¥ {{ Number(row.price).toFixed(2) }}</span>
        </template>

        <template #cell-is_popular="{ row }">
          <el-tag v-if="row.is_popular" type="warning" size="small">超值</el-tag>
          <span v-else class="muted">—</span>
        </template>

        <template #cell-is_active="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '上架' : '下架' }}
          </el-tag>
        </template>

        <template #cell-sort_order="{ row }">{{ row.sort_order }}</template>

        <template #cell-actions="{ row }">
          <el-button size="small" @click="openPkgEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="removePkg(row)">删除</el-button>
        </template>
      </DataTable>
    </section>

    <!-- 订阅套餐对话框 -->
    <el-dialog v-model="planVisible" :title="planEditing ? '编辑订阅套餐' : '新增订阅套餐'" width="520px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="planForm.name" maxlength="50" /></el-form-item>
        <el-form-item label="归属服">
          <el-select v-model="planForm.realm_id" placeholder="选择这个套餐属于哪个服" style="width: 100%">
            <el-option v-for="r in realmOptions" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
          <p class="field-help">
            用户在哪个服买这份套餐，会员就开在那个服（不同服的会员互不影响）。
          </p>
        </el-form-item>
        <el-form-item label="描述"><el-input v-model="planForm.description" maxlength="200" /></el-form-item>
        <el-form-item label="价格 (¥)"><el-input-number v-model="planForm.price" :min="0" :precision="2" style="width: 100%" /></el-form-item>
        <el-form-item label="时长 (天)"><el-input-number v-model="planForm.duration_days" :min="1" :max="3650" style="width: 100%" /></el-form-item>
        <el-form-item label="特性">
          <el-input v-model="planForm.features" type="textarea" :rows="3" placeholder="每行一条，如：4K 原画" />
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="planForm.sort_order" :min="0" style="width: 100%" /></el-form-item>
        <el-form-item label="选项">
          <el-checkbox v-model="planForm.is_active">上架</el-checkbox>
          <el-checkbox v-model="planForm.is_popular">推荐</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planVisible = false">取消</el-button>
        <el-button type="primary" @click="savePlan">保存</el-button>
      </template>
    </el-dialog>

    <!-- 充值套餐对话框 -->
    <el-dialog v-model="pkgVisible" :title="pkgEditing ? '编辑充值套餐' : '新增充值套餐'" width="480px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="pkgForm.name" maxlength="50" /></el-form-item>
        <el-form-item label="积分数"><el-input-number v-model="pkgForm.amount" :min="1" style="width: 100%" /></el-form-item>
        <el-form-item label="赠送积分"><el-input-number v-model="pkgForm.bonus" :min="0" style="width: 100%" /></el-form-item>
        <el-form-item label="价格 (¥)"><el-input-number v-model="pkgForm.price" :min="0" :precision="2" style="width: 100%" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="pkgForm.sort_order" :min="0" style="width: 100%" /></el-form-item>
        <el-form-item label="选项">
          <el-checkbox v-model="pkgForm.is_active">上架</el-checkbox>
          <el-checkbox v-model="pkgForm.is_popular">超值推荐</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pkgVisible = false">取消</el-button>
        <el-button type="primary" @click="savePkg">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.block-head h3 { margin: 0; font-size: 14.5px; font-weight: 600; }

.muted { color: var(--text-muted); }

.page-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.field-help { color: var(--text-muted); font-size: var(--font-size-xs); margin: 5px 0 0; line-height: 1.6; }
</style>
