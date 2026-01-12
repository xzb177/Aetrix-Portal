<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  RefreshCw,
  Plus,
  Edit,
  Trash2,
  Star,
  Check,
  X,
  Save,
  Calendar,
  Receipt,
  Users,
} from 'lucide-vue-next'
import {
  getSubscriptionPlans,
  createSubscriptionPlan,
  updateSubscriptionPlan,
  deleteSubscriptionPlan,
  getSubscriptionOrders,
  getSubscriptions,
} from '@/api/portal'
import {
  TopBar,
  Tabs,
  PrimaryButton,
  IconButton,
  Chip,
  ActionCard,
  type TabItem,
} from '@/components/ui'

const loading = ref(false)
const plans = ref<any[]>([])
const orders = ref<any[]>([])
const subscriptions = ref<any[]>([])

// 对话框状态
const showPlanDialog = ref(false)
const showDeleteDialog = ref(false)
const editingPlan = ref<any>(null)
const planToDelete = ref<any>(null)
const saving = ref(false)

// 标签页
const activeTab = ref('plans')

// Tab 配置
const tabItems: TabItem[] = [
  { id: 'plans', label: '套餐管理' },
  { id: 'orders', label: '订单记录' },
  { id: 'subscriptions', label: '用户订阅' },
]

// 表单数据
const planForm = ref({
  name: '',
  description: '',
  price: 0,
  duration_days: 30,
  features: [''],
  is_active: true,
  is_popular: false,
  sort_order: 0,
})

// 显示提示
const showToast = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error' | 'warning' | 'info'>('success')

const showToastMessage = (message: string, type: 'success' | 'error' | 'warning' | 'info') => {
  toastMessage.value = message
  toastType.value = type
  showToast.value = true
  setTimeout(() => {
    showToast.value = false
  }, 3000)
}

// 加载套餐列表
const loadPlans = async () => {
  loading.value = true
  try {
    const res = await getSubscriptionPlans()
    plans.value = res
  } catch (error) {
    console.error('加载套餐列表失败:', error)
    showToastMessage('加载失败，请稍后重试', 'error')
  } finally {
    loading.value = false
  }
}

// 加载订单列表
const loadOrders = async () => {
  loading.value = true
  try {
    const res = await getSubscriptionOrders({})
    orders.value = res
  } catch (error) {
    console.error('加载订单列表失败:', error)
    showToastMessage('加载失败，请稍后重试', 'error')
  } finally {
    loading.value = false
  }
}

// 加载订阅列表
const loadSubscriptions = async () => {
  loading.value = true
  try {
    const res = await getSubscriptions({})
    subscriptions.value = res
  } catch (error) {
    console.error('加载订阅列表失败:', error)
    showToastMessage('加载失败，请稍后重试', 'error')
  } finally {
    loading.value = false
  }
}

// 打开创建套餐对话框
const handleCreatePlan = () => {
  editingPlan.value = null
  planForm.value = {
    name: '',
    description: '',
    price: 0,
    duration_days: 30,
    features: [''],
    is_active: true,
    is_popular: false,
    sort_order: 0,
  }
  showPlanDialog.value = true
}

// 打开编辑套餐对话框
const handleEditPlan = (plan: any) => {
  editingPlan.value = plan
  planForm.value = {
    name: plan.name,
    description: plan.description,
    price: plan.price,
    duration_days: plan.duration_days,
    features: [...plan.features],
    is_active: plan.is_active,
    is_popular: plan.is_popular,
    sort_order: plan.sort_order,
  }
  showPlanDialog.value = true
}

// 保存套餐
const handleSavePlan = async () => {
  saving.value = true
  try {
    // 过滤空特性
    const features = planForm.value.features.filter(f => f.trim())

    if (editingPlan.value) {
      await updateSubscriptionPlan(editingPlan.value.id, {
        ...planForm.value,
        features,
      })
      showToastMessage('套餐更新成功', 'success')
    } else {
      await createSubscriptionPlan({
        ...planForm.value,
        features,
      })
      showToastMessage('套餐创建成功', 'success')
    }
    showPlanDialog.value = false
    loadPlans()
  } catch (error) {
    console.error('保存套餐失败:', error)
    showToastMessage('保存失败，请稍后重试', 'error')
  } finally {
    saving.value = false
  }
}

// 删除套餐
const handleDeletePlan = (plan: any) => {
  planToDelete.value = plan
  showDeleteDialog.value = true
}

const confirmDelete = async () => {
  if (!planToDelete.value) return
  try {
    await deleteSubscriptionPlan(planToDelete.value.id)
    showToastMessage('套餐删除成功', 'success')
    showDeleteDialog.value = false
    loadPlans()
  } catch (error: any) {
    console.error('删除套餐失败:', error)
    showToastMessage(error.response?.data?.detail || '删除失败', 'error')
  }
}

// 添加特性
const addFeature = () => {
  planForm.value.features.push('')
}

// 删除特性
const removeFeature = (index: number) => {
  planForm.value.features.splice(index, 1)
}

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 格式化金额
const formatPrice = (price: number) => {
  return `¥${price.toFixed(2)}`
}

// 订单状态映射
const getOrderStatusChip = (status: string) => {
  const map: Record<string, { variant: any, text: string }> = {
    pending: { variant: 'warning' as const, text: '待支付' },
    paid: { variant: 'success' as const, text: '已支付' },
    cancelled: { variant: 'default' as const, text: '已取消' },
    expired: { variant: 'danger' as const, text: '已过期' },
  }
  return map[status] || { variant: 'default' as const, text: status }
}

const getSubscriptionStatusChip = (status: string) => {
  const map: Record<string, { variant: any, text: string }> = {
    active: { variant: 'success' as const, text: '有效' },
    expired: { variant: 'danger' as const, text: '过期' },
    cancelled: { variant: 'default' as const, text: '已取消' },
  }
  return map[status] || { variant: 'default' as const, text: status }
}

// Tab 切换处理
const handleTabChange = (tabId: string) => {
  activeTab.value = tabId
  if (tabId === 'orders') {
    loadOrders()
  } else if (tabId === 'subscriptions') {
    loadSubscriptions()
  } else {
    loadPlans()
  }
}

// 订单卡片数据
const orderCards = computed(() => {
  return orders.value.map(order => ({
    id: order.id,
    title: order.order_id,
    subtitle: order.plan_name,
    value: formatPrice(order.amount),
    icon: Receipt,
  }))
})

// 订阅卡片数据
const subscriptionCards = computed(() => {
  return subscriptions.value.map(sub => ({
    id: sub.id,
    title: sub.username,
    subtitle: `${sub.plan_name} · ${formatDate(sub.start_date)}`,
    value: formatDate(sub.end_date),
    icon: Users,
  }))
})

onMounted(() => {
  loadPlans()
})
</script>

<template>
  <div class="subscriptions-page">
    <!-- 顶部导航栏 -->
    <TopBar
      title="订阅套餐管理"
      subtitle="管理用户订阅套餐和订单"
    >
      <template #actions>
        <template v-if="activeTab === 'plans'">
          <PrimaryButton
            :icon="Plus"
            size="sm"
            @click="handleCreatePlan"
          >
            创建套餐
          </PrimaryButton>
        </template>
        <template v-else>
          <IconButton
            :icon="RefreshCw"
            @click="activeTab === 'orders' ? loadOrders() : loadSubscriptions()"
          />
        </template>
      </template>
    </TopBar>

    <div class="page-content">
      <!-- 标签页 -->
      <Tabs
        :items="tabItems"
        v-model="activeTab"
        type="pills"
        @change="handleTabChange"
      />

      <!-- 套餐管理 -->
      <div v-if="activeTab === 'plans'" class="content-section">
        <div v-if="!loading && plans.length > 0" class="plans-grid">
          <div
            v-for="plan in plans"
            :key="plan.id"
            class="plan-card"
            :class="{ 'plan-popular': plan.is_popular, 'plan-inactive': !plan.is_active }"
          >
            <div v-if="plan.is_popular" class="plan-badge">
              <Star :size="12" />
              推荐
            </div>
            <div class="plan-header">
              <h3 class="plan-name">{{ plan.name }}</h3>
              <p class="plan-description">{{ plan.description }}</p>
            </div>
            <div class="plan-price">
              <span class="plan-amount">{{ formatPrice(plan.price) }}</span>
              <span class="plan-duration">/ {{ plan.duration_days }} 天</span>
            </div>
            <ul class="plan-features">
              <li v-for="feature in plan.features" :key="feature">
                <Check :size="14" class="feature-icon" />
                {{ feature }}
              </li>
            </ul>
            <div class="plan-footer">
              <Chip :variant="plan.is_active ? 'success' : 'default'" size="sm">
                {{ plan.is_active ? '启用中' : '已停用' }}
              </Chip>
              <span class="plan-servers">{{ plan.server_count || 0 }} 个服务器</span>
              <div class="plan-actions">
                <IconButton :icon="Edit" variant="primary" :size="32" @click="handleEditPlan(plan)" />
                <IconButton :icon="Trash2" variant="danger" :size="32" @click="handleDeletePlan(plan)" />
              </div>
            </div>
          </div>
        </div>
        <div v-else-if="loading" class="loading-grid">
          <div v-for="i in 3" :key="i" class="plan-skeleton">
            <div class="skeleton-bar skeleton-title"></div>
            <div class="skeleton-bar skeleton-price"></div>
            <div class="skeleton-bar skeleton-feature"></div>
          </div>
        </div>
        <div v-else class="empty-state">
          <div class="empty-icon">📦</div>
          <p class="empty-text">暂无订阅套餐</p>
          <PrimaryButton :icon="Plus" @click="handleCreatePlan">
            创建第一个套餐
          </PrimaryButton>
        </div>
      </div>

      <!-- 订单记录 -->
      <div v-if="activeTab === 'orders'" class="content-section">
        <div v-if="!loading && orders.length > 0" class="list-items">
          <div
            v-for="order in orders"
            :key="order.id"
            class="list-item"
          >
            <div class="item-left">
              <Receipt :size="18" class="item-icon" />
              <div class="item-content">
                <div class="item-title">{{ order.order_id }}</div>
                <div class="item-subtitle">{{ order.username }} · {{ order.plan_name }}</div>
              </div>
            </div>
            <div class="item-right">
              <div class="item-amount">{{ formatPrice(order.amount) }}</div>
              <Chip :variant="getOrderStatusChip(order.status).variant" size="sm">
                {{ getOrderStatusChip(order.status).text }}
              </Chip>
            </div>
          </div>
        </div>
        <div v-else-if="loading" class="loading-list">
          <div v-for="i in 5" :key="i" class="list-item-skeleton">
            <div class="skeleton-bar"></div>
          </div>
        </div>
        <div v-else class="empty-state">
          <div class="empty-icon">📄</div>
          <p class="empty-text">暂无订单记录</p>
        </div>
      </div>

      <!-- 用户订阅 -->
      <div v-if="activeTab === 'subscriptions'" class="content-section">
        <div v-if="!loading && subscriptions.length > 0" class="list-items">
          <div
            v-for="sub in subscriptions"
            :key="sub.id"
            class="list-item"
          >
            <div class="item-left">
              <Users :size="18" class="item-icon" />
              <div class="item-content">
                <div class="item-title">{{ sub.username }}</div>
                <div class="item-subtitle">{{ sub.plan_name }}</div>
              </div>
            </div>
            <div class="item-right">
              <Chip :variant="sub.auto_renew ? 'success' : 'default'" size="sm">
                {{ sub.auto_renew ? '自动续费' : '手动续费' }}
              </Chip>
              <Chip :variant="getSubscriptionStatusChip(sub.status).variant" size="sm">
                {{ getSubscriptionStatusChip(sub.status).text }}
              </Chip>
            </div>
          </div>
        </div>
        <div v-else-if="loading" class="loading-list">
          <div v-for="i in 5" :key="i" class="list-item-skeleton">
            <div class="skeleton-bar"></div>
          </div>
        </div>
        <div v-else class="empty-state">
          <div class="empty-icon">👥</div>
          <p class="empty-text">暂无订阅记录</p>
        </div>
      </div>
    </div>

    <!-- 创建/编辑套餐对话框 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showPlanDialog" class="modal-overlay" @click.self="showPlanDialog = false">
        <div class="modal-content">
          <div class="modal-header">
            <h2 class="modal-title">{{ editingPlan ? '编辑套餐' : '创建套餐' }}</h2>
            <IconButton :icon="X" variant="ghost" :size="36" @click="showPlanDialog = false" />
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">套餐名称</label>
              <input v-model="planForm.name" type="text" class="input" placeholder="例如：月度会员" />
            </div>
            <div class="form-group">
              <label class="form-label">套餐描述</label>
              <input v-model="planForm.description" type="text" class="input" placeholder="简短描述套餐特点" />
            </div>
            <div class="form-row">
              <div class="form-group">
                <label class="form-label">价格 (元)</label>
                <input v-model.number="planForm.price" type="number" class="input" min="0" step="0.01" />
              </div>
              <div class="form-group">
                <label class="form-label">时长 (天)</label>
                <input v-model.number="planForm.duration_days" type="number" class="input" min="1" />
              </div>
            </div>
            <div class="form-group">
              <label class="form-label">套餐特性</label>
              <div class="features-list">
                <div v-for="(feature, index) in planForm.features" :key="index" class="feature-input">
                  <input v-model="planForm.features[index]" type="text" class="input" placeholder="特性描述" />
                  <IconButton
                    v-if="planForm.features.length > 1"
                    :icon="X"
                    variant="danger"
                    :size="28"
                    @click="removeFeature(index)"
                  />
                </div>
                <PrimaryButton variant="ghost" :icon="Plus" size="sm" @click="addFeature">
                  添加特性
                </PrimaryButton>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group checkbox-group">
                <label class="checkbox-label">
                  <input v-model="planForm.is_active" type="checkbox" />
                  <span>启用套餐</span>
                </label>
              </div>
              <div class="form-group checkbox-group">
                <label class="checkbox-label">
                  <input v-model="planForm.is_popular" type="checkbox" />
                  <span>推荐套餐</span>
                </label>
              </div>
            </div>
            <div class="form-group">
              <label class="form-label">排序顺序</label>
              <input v-model.number="planForm.sort_order" type="number" class="input" min="0" />
            </div>
          </div>
          <div class="modal-footer">
            <PrimaryButton variant="secondary" @click="showPlanDialog = false">
              取消
            </PrimaryButton>
            <PrimaryButton :loading="saving" :icon="Save" @click="handleSavePlan">
              {{ saving ? '保存中...' : '保存' }}
            </PrimaryButton>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 删除确认对话框 -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="showDeleteDialog" class="modal-overlay" @click.self="showDeleteDialog = false">
        <div class="modal-content modal-small">
          <div class="delete-header">
            <div class="delete-icon">
              <Trash2 :size="24" />
            </div>
            <div class="delete-title-section">
              <h3 class="delete-title">确认删除</h3>
              <p class="delete-subtitle">此操作不可恢复</p>
            </div>
          </div>
          <p class="delete-message">
            确定要删除套餐 <span class="delete-name">{{ planToDelete?.name }}</span> 吗？
          </p>
          <div class="delete-actions">
            <PrimaryButton variant="secondary" @click="showDeleteDialog = false">
              取消
            </PrimaryButton>
            <PrimaryButton variant="danger" @click="confirmDelete">
              确认删除
            </PrimaryButton>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Toast 提示 -->
    <Transition
      enter-active-class="transition-all duration-300"
      enter-from-class="opacity-0 translate-x-4"
      enter-to-class="opacity-100 translate-x-0"
      leave-active-class="transition-all duration-300"
      leave-from-class="opacity-100 translate-x-0"
      leave-to-class="opacity-0 translate-x-4"
    >
      <div v-if="showToast" :class="['toast', `toast-${toastType}`]">
        <span class="toast-icon">{{ toastType === 'success' ? '✓' : toastType === 'error' ? '✕' : 'ℹ' }}</span>
        <span>{{ toastMessage }}</span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.subscriptions-page {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg-primary);
}

.page-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4);
}

.content-section {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
}

/* 套餐卡片网格 */
.plans-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-4);
}

@media (min-width: 640px) {
  .plans-grid {
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  }
}

.plan-card {
  position: relative;
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  transition: all var(--transition-base) ease;
}

.plan-card:active {
  border-color: var(--primary);
  box-shadow: var(--shadow-md);
}

.plan-popular {
  border-color: var(--warning);
}

.plan-inactive {
  opacity: 0.6;
}

.plan-badge {
  position: absolute;
  top: -8px;
  right: var(--space-4);
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px var(--space-2);
  background: var(--warning);
  color: white;
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.plan-header {
  margin-bottom: var(--space-3);
}

.plan-name {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  margin-bottom: 4px;
}

.plan-description {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.plan-price {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.plan-amount {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--primary);
}

.plan-duration {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.plan-features {
  list-style: none;
  padding: 0;
  margin: 0 0 var(--space-4) 0;
}

.plan-features li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.feature-icon {
  flex-shrink: 0;
  color: var(--primary);
}

.plan-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-subtle);
  flex-wrap: wrap;
  gap: var(--space-2);
}

.plan-servers {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.plan-actions {
  display: flex;
  gap: var(--space-2);
}

/* 列表项（订单/订阅） */
.list-items {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  transition: background-color var(--transition-fast) ease;
}

.list-item:active {
  background: var(--bg-card-hover);
}

.item-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
}

.item-icon {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.item-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.item-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-subtitle {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.item-amount {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

/* Loading 骨架屏 */
.loading-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

.plan-skeleton {
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
}

.skeleton-bar {
  height: 16px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.skeleton-title {
  width: 60%;
  margin-bottom: var(--space-3);
}

.skeleton-price {
  width: 40%;
  margin-bottom: var(--space-3);
}

.skeleton-feature {
  width: 80%;
}

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

.loading-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.list-item-skeleton {
  padding: var(--space-3) var(--space-4);
  height: var(--list-item-min);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: var(--space-6) var(--space-4);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--space-3);
  opacity: 0.5;
}

.empty-text {
  color: var(--text-tertiary);
  margin: 0 0 var(--space-4) 0;
}

/* 对话框 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  backdrop-filter: blur(8px);
  z-index: var(--z-modal-backdrop);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
}

.modal-content {
  width: 100%;
  max-width: 500px;
  max-height: 90vh;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-small {
  max-width: 360px;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}

.modal-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.modal-body {
  padding: var(--space-4);
  overflow-y: auto;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--border-subtle);
}

/* 表单 */
.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.form-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.input {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: var(--font-size-md);
  transition: all var(--transition-fast) ease;
}

.input:focus {
  outline: none;
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px var(--primary-bg);
}

.features-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.feature-input {
  display: flex;
  gap: var(--space-2);
}

.feature-input input {
  flex: 1;
}

.checkbox-group {
  align-items: center;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  font-size: var(--font-size-md);
  color: var(--text-primary);
}

/* 删除对话框 */
.delete-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.delete-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--danger-bg);
  color: var(--danger);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.delete-title-section {
  flex: 1;
}

.delete-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.delete-subtitle {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.delete-message {
  font-size: var(--font-size-md);
  color: var(--text-secondary);
  margin-bottom: var(--space-5);
}

.delete-name {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.delete-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
}

/* Toast */
.toast {
  position: fixed;
  bottom: var(--space-5);
  right: var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-tooltip);
}

.toast-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
}

.toast-success {
  border-color: var(--success);
}

.toast-success .toast-icon {
  background: var(--success);
  color: white;
}

.toast-error {
  border-color: var(--danger);
}

.toast-error .toast-icon {
  background: var(--danger);
  color: white;
}

/* 响应式 */
@media (max-width: 640px) {
  .form-row {
    grid-template-columns: 1fr;
  }

  .item-right {
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-1);
  }

  .plan-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
