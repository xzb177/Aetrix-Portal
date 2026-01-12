<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Users, Plus, Edit, Trash2, Save, Key, Shield, Lock, Eye, EyeOff } from 'lucide-vue-next'
import request from '@/utils/request'

interface Admin {
  id: number
  username: string
  role: string
  role_display_name: string
  is_active: boolean
  last_login: string | null
  created_at: string
}

interface Role {
  name: string
  display_name: string
}

const loading = ref(false)
const admins = ref<Admin[]>([])
const roles = ref<Role[]>([])

// 弹窗状态
const showAdminModal = ref(false)
const editingAdmin = ref<Admin | null>(null)
const showPassword = ref(false)

// 表单数据
const formData = ref({
  username: '',
  password: '',
  role: 'operator',
  is_active: true
})

const loadData = async () => {
  loading.value = true
  try {
    const [adminsRes, rolesRes] = await Promise.all([
      request.get<any>('/admins') as any,
      request.get<any>('/roles') as any
    ])
    admins.value = adminsRes
    roles.value = rolesRes
  } finally {
    loading.value = false
  }
}

const openCreateModal = () => {
  editingAdmin.value = null
  formData.value = {
    username: '',
    password: '',
    role: 'operator',
    is_active: true
  }
  showPassword.value = false
  showAdminModal.value = true
}

const openEditModal = (admin: Admin) => {
  editingAdmin.value = admin
  formData.value = {
    username: admin.username,
    password: '',
    role: admin.role,
    is_active: admin.is_active
  }
  showPassword.value = false
  showAdminModal.value = true
}

const closeModal = () => {
  showAdminModal.value = false
  editingAdmin.value = null
}

const saveAdmin = async () => {
  if (!formData.value.username) {
    alert('请填写用户名')
    return
  }

  if (!editingAdmin.value && !formData.value.password) {
    alert('请填写密码')
    return
  }

  if (formData.value.password && formData.value.password.length < 6) {
    alert('密码长度至少为6位')
    return
  }

  try {
    if (editingAdmin.value) {
      await request.put(`/admins/${editingAdmin.value.id}`, formData.value)
    } else {
      await request.post('/admins', formData.value)
    }
    closeModal()
    await loadData()
  } catch (err: any) {
    alert(err.message || '保存失败')
  }
}

const deleteAdmin = async (admin: Admin) => {
  if (admin.role === 'super_admin') {
    alert('不能删除超级管理员')
    return
  }
  if (!confirm(`确定要删除管理员「${admin.username}」吗？`)) {
    return
  }

  try {
    await request.delete(`/admins/${admin.id}`)
    await loadData()
  } catch (err: any) {
    alert(err.message || '删除失败')
  }
}

const resetPassword = async (admin: Admin) => {
  if (!confirm(`确定要重置管理员「${admin.username}」的密码吗？`)) {
    return
  }

  try {
    const res = await request.post<{ password: string }>(`/admins/${admin.id}/reset-password`) as any
    alert(`新密码：${res.password}\n请妥善保存！`)
  } catch (err: any) {
    alert(err.message || '重置失败')
  }
}

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '从未登录'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const getRoleBadgeColor = (role: string) => {
  switch (role) {
    case 'super_admin': return '#673AB7'
    case 'admin': return '#4CAF50'
    case 'operator': return '#FF9800'
    case 'viewer': return '#94a3b8'
    default: return '#64748b'
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="admins-page">
    <!-- 操作按钮 -->
    <div class="page-actions">
      <button class="btn-primary" @click="openCreateModal">
        <Plus :size="18" />
        新建管理员
      </button>
    </div>

    <!-- 管理员列表 -->
    <div class="admins-table-wrapper">
      <table class="admins-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>角色</th>
            <th>状态</th>
            <th>最后登录</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="admin in admins" :key="admin.id" class="admin-row">
            <td class="username">
              <div class="user-info">
                <div class="user-avatar">{{ admin.username?.[0]?.toUpperCase() || 'A' }}</div>
                <span>{{ admin.username }}</span>
              </div>
            </td>
            <td>
              <span class="role-badge" :style="{ background: `${getRoleBadgeColor(admin.role)}15`, color: getRoleBadgeColor(admin.role) }">
                <Shield :size="12" />
                {{ admin.role_display_name }}
              </span>
            </td>
            <td>
              <span class="status-badge" :class="{ active: admin.is_active }">
                {{ admin.is_active ? '正常' : '已禁用' }}
              </span>
            </td>
            <td class="time">{{ formatDate(admin.last_login) }}</td>
            <td class="time">{{ formatDate(admin.created_at) }}</td>
            <td class="actions">
              <button class="btn-icon" @click="openEditModal(admin)" title="编辑">
                <Edit :size="16" />
              </button>
              <button class="btn-icon" @click="resetPassword(admin)" title="重置密码">
                <Key :size="16" />
              </button>
              <button
                class="btn-icon"
                :class="{ 'btn-danger': admin.role !== 'super_admin' }"
                :disabled="admin.role === 'super_admin'"
                @click="deleteAdmin(admin)"
                title="删除"
              >
                <Trash2 :size="16" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 管理员编辑弹窗 -->
    <div v-if="showAdminModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal-content">
        <div class="modal-header">
          <h2>{{ editingAdmin ? '编辑管理员' : '新建管理员' }}</h2>
          <button class="btn-icon" @click="closeModal">
            <X :size="20" />
          </button>
        </div>

        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">用户名 <span class="required">*</span></label>
            <input
              v-model="formData.username"
              type="text"
              class="form-input"
              placeholder="请输入用户名"
              :disabled="!!editingAdmin"
            />
          </div>

          <div class="form-group">
            <label class="form-label">
              {{ editingAdmin ? '新密码（留空不修改）' : '密码' }}
              <span class="required" v-if="!editingAdmin">*</span>
            </label>
            <div class="password-input">
              <input
                v-model="formData.password"
                :type="showPassword ? 'text' : 'password'"
                class="form-input"
                placeholder="至少6位字符"
              />
              <button class="btn-toggle-password" @click="showPassword = !showPassword">
                <Eye v-if="!showPassword" :size="18" />
                <EyeOff v-else :size="18" />
              </button>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">角色 <span class="required">*</span></label>
            <select v-model="formData.role" class="form-select">
              <option v-for="role in roles" :key="role.name" :value="role.name">
                {{ role.display_name }} ({{ role.name }})
              </option>
            </select>
            <p class="form-hint">
              <Lock :size="12" />
              超级管理员拥有所有权限，请谨慎分配
            </p>
          </div>

          <div class="form-group">
            <label class="form-check">
              <input
                v-model="formData.is_active"
                type="checkbox"
              />
              <span>启用账号</span>
            </label>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-secondary" @click="closeModal">取消</button>
          <button class="btn-primary" @click="saveAdmin">
            <Save :size="16" />
            保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { X } from 'lucide-vue-next'

export default {
  components: { X }
}
</script>

<style scoped>
.admins-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.page-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1rem;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  background: #673AB7;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.875rem;
  cursor: pointer;
}

.btn-primary:hover { background: #552b9f; }

/* 表格 */
.admins-table-wrapper {
  background: white;
  border-radius: 12px;
  border: 1px solid #e8edf3;
  overflow-x: auto;
}

.admins-table {
  width: 100%;
  border-collapse: collapse;
}

.admins-table th {
  text-align: left;
  padding: 1rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid #f1f5f9;
  white-space: nowrap;
}

.admins-table td {
  padding: 1rem;
  border-bottom: 1px solid #f1f5f9;
}

.admin-row:last-child td {
  border-bottom: none;
}

.admin-row:hover {
  background: #f8fafc;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, #673AB7, #4CAF50);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.875rem;
}

.username {
  font-weight: 500;
  color: #1a1a2e;
}

.role-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.status-badge {
  display: inline-block;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  background: #f1f5f9;
  color: #94a3b8;
}

.status-badge.active {
  background: rgba(76, 175, 80, 0.15);
  color: #4CAF50;
}

.time {
  font-size: 0.875rem;
  color: #64748b;
}

.actions {
  display: flex;
  gap: 0.5rem;
}

.btn-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: #f1f5f9;
  border-radius: 6px;
  color: #64748b;
  cursor: pointer;
}

.btn-icon:hover:not(:disabled) {
  background: #e2e8f0;
  color: #1a1a2e;
}

.btn-icon.btn-danger:hover:not(:disabled) {
  background: rgba(244, 67, 54, 0.1);
  color: #F44336;
}

.btn-icon:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 弹窗 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal-content {
  background: white;
  border-radius: 16px;
  width: 100%;
  max-width: 450px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem;
  border-bottom: 1px solid #f1f5f9;
}

.modal-header h2 {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.modal-body {
  padding: 1.5rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1.5rem;
  border-top: 1px solid #f1f5f9;
}

.btn-secondary {
  padding: 0.625rem 1.25rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: #475569;
  cursor: pointer;
}

.form-group {
  margin-bottom: 1.25rem;
}

.form-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
  margin-bottom: 0.5rem;
}

.required {
  color: #F44336;
}

.form-input,
.form-select {
  width: 100%;
  padding: 0.625rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
}

.form-input:disabled {
  background: #f1f5f9;
}

.form-hint {
  font-size: 0.75rem;
  color: #94a3b8;
  margin-top: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.password-input {
  position: relative;
  .btn-toggle-password {
    position: absolute;
    right: 0.75rem;
    top: 50%;
    transform: translateY(-50%);
    background: none;
    border: none;
    color: #94a3b8;
    cursor: pointer;
  }
}

.form-check {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: #475569;
  cursor: pointer;
}

/* 移动端适配 */
@media (max-width: 768px) {

  .btn-primary {
    width: 100%;
    justify-content: center;
  }
}
</style>
