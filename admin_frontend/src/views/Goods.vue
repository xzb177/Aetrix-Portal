<script setup lang="ts">
/**
 * 商品管理：订阅套餐 CRUD + 充值套餐 CRUD
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshCw } from 'lucide-vue-next'
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
})

function openPlanCreate() {
  planEditing.value = null
  planForm.value = { name: '', description: '', price: 19.9, duration_days: 30, features: '', is_active: true, is_popular: false, sort_order: 0 }
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
    const [p, k] = await Promise.all([fetchEconomyPlans(), fetchEconomyPackages()])
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
        <p class="admin-page-subtitle">订阅套餐与积分充值套餐配置</p>
      </div>
      <el-button :icon="RefreshCw" :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- 订阅套餐 -->
    <section class="admin-card block">
      <header class="block-head">
        <h3>订阅套餐</h3>
        <el-button type="primary" size="small" :icon="Plus" @click="openPlanCreate">新增套餐</el-button>
      </header>
      <el-table :data="plans" v-loading="loading" size="default">
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
        <el-table-column label="价格" width="100">
          <template #default="{ row }">¥ {{ Number(row.price).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="时长" width="90">
          <template #default="{ row }">{{ row.duration_days }} 天</template>
        </el-table-column>
        <el-table-column label="推荐" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_popular" type="warning" size="small">推荐</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '上架' : '下架' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sort_order" label="排序" width="70" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openPlanEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removePlan(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 充值套餐 -->
    <section class="admin-card block">
      <header class="block-head">
        <h3>积分充值套餐</h3>
        <el-button type="primary" size="small" :icon="Plus" @click="openPkgCreate">新增套餐</el-button>
      </header>
      <el-table :data="packages" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column label="积分" width="100">
          <template #default="{ row }">{{ row.amount }} + {{ row.bonus }}</template>
        </el-table-column>
        <el-table-column label="合计" width="100">
          <template #default="{ row }"><strong>{{ row.amount + row.bonus }}</strong></template>
        </el-table-column>
        <el-table-column label="价格" width="100">
          <template #default="{ row }">¥ {{ Number(row.price).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="推荐" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_popular" type="warning" size="small">超值</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '上架' : '下架' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sort_order" label="排序" width="70" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openPkgEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removePkg(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 订阅套餐对话框 -->
    <el-dialog v-model="planVisible" :title="planEditing ? '编辑订阅套餐' : '新增订阅套餐'" width="520">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="planForm.name" maxlength="50" /></el-form-item>
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
    <el-dialog v-model="pkgVisible" :title="pkgEditing ? '编辑充值套餐' : '新增充值套餐'" width="480">
      <el-form label-width="100px">
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
</style>
