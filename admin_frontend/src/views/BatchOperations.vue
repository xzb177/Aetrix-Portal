<script setup lang="ts">
import { ref, computed } from 'vue'
import { Users, Clock, CreditCard, CheckCircle, Search, Filter } from 'lucide-vue-next'

interface User {
  id: string
  username: string
  emby: string
  vipLevel: string
  expireDate: string
  status: 'active' | 'expiring' | 'expired'
}

const selectedUsers = ref<Set<string>>(new Set())
const filterStatus = ref<string>('all')
const searchQuery = ref('')

// 模拟用户数据
const users = ref<User[]>([
  { id: '1', username: 'user123', emby: 'user123', vipLevel: 'VIP月卡', expireDate: '2024-01-15', status: 'expiring' },
  { id: '2', username: 'user456', emby: 'user456', vipLevel: 'VIP季卡', expireDate: '2024-03-20', status: 'active' },
  { id: '3', username: 'user789', emby: 'user789', vipLevel: 'VIP年卡', expireDate: '2024-01-03', status: 'expired' },
  { id: '4', username: 'user321', emby: 'user321', vipLevel: 'VIP月卡', expireDate: '2024-01-20', status: 'expiring' },
  { id: '5', username: 'user654', emby: 'user654', vipLevel: 'VIP季卡', expireDate: '2024-02-15', status: 'active' },
])

const operationType = ref<'extend' | 'upgrade' | 'downgrade' | 'notify' | ''>('')
const extendDays = ref(30)
const newVipLevel = ref('')
const notifyMessage = ref('')

const selectAll = ref(false)

const filtered = computed(() => {
  let result = [...users.value]

  if (searchQuery.value) {
    result = result.filter((u: User) =>
      u.username.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      u.emby.toLowerCase().includes(searchQuery.value.toLowerCase())
    )
  }

  if (filterStatus.value !== 'all') {
    result = result.filter((u: User) => u.status === filterStatus.value)
  }

  return result
})

const toggleSelect = (userId: string) => {
  if (selectedUsers.value.has(userId)) {
    selectedUsers.value.delete(userId)
  } else {
    selectedUsers.value.add(userId)
  }
}

const toggleSelectAll = () => {
  selectAll.value = !selectAll.value
  if (selectAll.value) {
    filtered.value.forEach((u: User) => selectedUsers.value.add(u.id))
  } else {
    selectedUsers.value.clear()
  }
}

const getStatusClass = (status: string) => {
  switch (status) {
    case 'active': return 'status-active'
    case 'expiring': return 'status-expiring'
    case 'expired': return 'status-expired'
    default: return ''
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'active': return '正常'
    case 'expiring': return '即将到期'
    case 'expired': return '已过期'
    default: return status
  }
}

const executeOperation = () => {
  if (selectedUsers.value.size === 0) {
    alert('请先选择用户')
    return
  }

  let message = `将对 ${selectedUsers.value.size} 位用户执行操作：\n`

  switch (operationType.value) {
    case 'extend':
      message += `延长 ${extendDays.value} 天`
      break
    case 'upgrade':
      message += `升级到 ${newVipLevel.value}`
      break
    case 'downgrade':
      message += `降级到 ${newVipLevel.value}`
      break
    case 'notify':
      message += `发送通知：${notifyMessage.value}`
      break
  }

  if (confirm(message + '\n\n确认执行？')) {
    alert('操作已执行！')
    selectedUsers.value.clear()
    selectAll.value = false
  }
}
</script>

<template>
  <div class="batch-ops-page">
    <!-- 操作面板 -->
    <div class="operation-panel">
      <h2 class="panel-title">选择操作类型</h2>
      <div class="operation-types">
        <button
          :class="['op-type-btn', { active: operationType === 'extend' }]"
          @click="operationType = 'extend'"
        >
          <Clock :size="20" />
          <span>批量续期</span>
        </button>
        <button
          :class="['op-type-btn', { active: operationType === 'upgrade' }]"
          @click="operationType = 'upgrade'"
        >
          <CreditCard :size="20" />
          <span>批量升级</span>
        </button>
        <button
          :class="['op-type-btn', { active: operationType === 'downgrade' }]"
          @click="operationType = 'downgrade'"
        >
          <CreditCard :size="20" />
          <span>批量降级</span>
        </button>
        <button
          :class="['op-type-btn', { active: operationType === 'notify' }]"
          @click="operationType = 'notify'"
        >
          <CheckCircle :size="20" />
          <span>批量通知</span>
        </button>
      </div>

      <!-- 操作参数 -->
      <div v-if="operationType" class="operation-params">
        <!-- 续期参数 -->
        <div v-if="operationType === 'extend'" class="param-group">
          <label>续期天数</label>
          <div class="param-inputs">
            <button @click="extendDays = Math.max(1, extendDays - 7)">-7天</button>
            <input type="number" v-model.number="extendDays" />
            <button @click="extendDays += 7">+7天</button>
          </div>
        </div>

        <!-- 升级/降级参数 -->
        <div v-if="operationType === 'upgrade' || operationType === 'downgrade'" class="param-group">
          <label>{{ operationType === 'upgrade' ? '升级' : '降级' }}到</label>
          <select v-model="newVipLevel" class="param-select">
            <option value="">请选择套餐</option>
            <option value="trial">体验卡</option>
            <option value="month">VIP月卡</option>
            <option value="quarter">VIP季卡</option>
            <option value="year">VIP年卡</option>
          </select>
        </div>

        <!-- 通知参数 -->
        <div v-if="operationType === 'notify'" class="param-group">
          <label>通知内容</label>
          <textarea v-model="notifyMessage" class="param-textarea" placeholder="请输入通知内容..."></textarea>
        </div>
      </div>
    </div>

    <!-- 用户筛选和列表 -->
    <div class="users-section">
      <div class="users-header">
        <div class="header-left">
          <label class="select-all">
            <input type="checkbox" :checked="selectAll" @change="toggleSelectAll" />
            <span>全选</span>
          </label>
          <span class="selected-count">已选择 {{ selectedUsers.size }} 位用户</span>
        </div>

        <div class="header-right">
          <div class="search-box">
            <Search :size="18" />
            <input v-model="searchQuery" type="text" placeholder="搜索用户名或 Emby 账号..." />
          </div>

          <select v-model="filterStatus" class="filter-select">
            <option value="all">全部状态</option>
            <option value="active">正常</option>
            <option value="expiring">即将到期</option>
            <option value="expired">已过期</option>
          </select>
        </div>
      </div>

      <div class="users-table">
        <div class="table-header">
          <span>用户</span>
          <span>Emby 账号</span>
          <span>当前套餐</span>
          <span>到期时间</span>
          <span>状态</span>
        </div>

        <div
          v-for="user in filtered"
          :key="user.id"
          class="table-row"
          :class="{ selected: selectedUsers.has(user.id) }"
          @click="toggleSelect(user.id)"
        >
          <label class="row-checkbox">
            <input type="checkbox" :checked="selectedUsers.has(user.id)" @change="toggleSelect(user.id)" />
            <span>{{ user.username }}</span>
          </label>
          <span>{{ user.emby }}</span>
          <span>{{ user.vipLevel }}</span>
          <span>{{ user.expireDate }}</span>
          <span class="status-badge" :class="getStatusClass(user.status)">
            {{ getStatusText(user.status) }}
          </span>
        </div>
      </div>
    </div>

    <!-- 执行按钮 -->
    <div class="execute-section">
      <button
        class="btn-execute"
        :disabled="!operationType || selectedUsers.size === 0"
        @click="executeOperation"
      >
        <CheckCircle :size="18" />
        执行操作 ({{ selectedUsers.size }} 位用户)
      </button>
    </div>
  </div>
</template>

<style scoped>
.batch-ops-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}




/* 操作面板 */
.operation-panel {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.panel-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 1rem 0;
}

.operation-types {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}

@media (max-width: 768px) {
  .operation-types {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .operation-types {
    grid-template-columns: 1fr;
  }

  .page-title {
    font-size: 1.25rem;
  }
}

.op-type-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1.25rem;
  background: #f8fafc;
  border: 2px solid #e2e8f0;
  border-radius: 10px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s ease;
}

.op-type-btn:hover {
  border-color: #673AB7;
  color: #673AB7;
}

.op-type-btn.active {
  border-color: #673AB7;
  background: rgba(103, 58, 183, 0.08);
  color: #673AB7;
}

.operation-params {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid #f1f5f9;
}

.param-group {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.param-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}

.param-inputs {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.param-inputs button {
  padding: 0.5rem 1rem;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  cursor: pointer;
}

.param-inputs input {
  width: 80px;
  padding: 0.5rem;
  text-align: center;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.param-select,
.param-textarea {
  width: 100%;
  max-width: 400px;
  padding: 0.625rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
}

.param-textarea {
  min-height: 100px;
  resize: vertical;
}

/* 用户列表 */
.users-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.users-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  gap: 1rem;
  flex-wrap: wrap;
}


.select-all {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: #475569;
  cursor: pointer;
}

.selected-count {
  font-size: 0.875rem;
  color: #673AB7;
}


.search-box {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.search-box input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 0.875rem;
  width: 200px;
}

@media (max-width: 768px) {
  .users-header {
    flex-direction: column;
    align-items: flex-start;
  }


.filter-select {
  padding: 0.5rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  background: white;
}

/* 表格 */
.users-table {
  display: flex;
  flex-direction: column;
  overflow-x: auto;
}

@media (max-width: 640px) {
  .table-header {
    min-width: 500px;
  }

  .table-row {
    min-width: 500px;
  }
}

.table-header {
  display: grid;
  grid-template-columns: 2fr 2fr 1.5fr 1.5fr 1fr;
  gap: 1rem;
  padding: 0.75rem 1rem;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 500;
  color: #64748b;
}

.table-row {
  display: grid;
  grid-template-columns: 2fr 2fr 1.5fr 1.5fr 1fr;
  gap: 1rem;
  padding: 0.875rem 1rem;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.2s;
}

.table-row:hover {
  background: #f8fafc;
}

.table-row.selected {
  background: rgba(103, 58, 183, 0.08);
}

.row-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.status-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-active {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.status-expiring {
  background: rgba(255, 152, 0, 0.15);
  color: #FF9800;
}

.status-expired {
  background: rgba(244, 67, 54, 0.15);
  color: #F44336;
}

/* 执行按钮 */
.execute-section {
  display: flex;
  justify-content: center;
}

.btn-execute {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.875rem 2rem;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
}

.btn-execute:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.btn-execute:not(:disabled):hover {
  background: #43A047;
}
</style>
