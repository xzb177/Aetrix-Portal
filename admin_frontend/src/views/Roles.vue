<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Shield, Plus, Edit, Trash2, Save, X, CheckCircle2 } from 'lucide-vue-next'
import request from '@/utils/request'

interface PermissionGroup {
  [key: string]: string[]
}

interface Permission {
  name: string
  description: string
  group: string
}

interface Role {
  id: number
  name: string
  display_name: string
  description: string
  permissions: string[]
  is_system: boolean
  user_count: number
  created_at: string
}

const loading = ref(false)
const roles = ref<Role[]>([])
const permissionGroups = ref<PermissionGroup>({})
const permissionDescriptions = ref<Record<string, string>>({})

// 弹窗状态
const showRoleModal = ref(false)
const editingRole = ref<Role | null>(null)

// 表单数据
const formData = ref({
  name: '',
  display_name: '',
  description: '',
  permissions: [] as string[]
})

// 选中的权限分组
const selectedGroups = ref<Set<string>>(new Set())

// 展开的分组
const expandedGroups = ref<Set<string>>(new Set())

const loadData = async () => {
  loading.value = true
  try {
    const [rolesRes, permsRes] = await Promise.all([
      request.get<any>('/roles') as any,
      request.get<any>('/permissions') as any
    ])
    roles.value = rolesRes
    permissionGroups.value = permsRes.groups
    permissionDescriptions.value = permsRes.descriptions
  } finally {
    loading.value = false
  }
}

const allPermissions = computed(() => {
  const result: Permission[] = []
  for (const [group, perms] of Object.entries(permissionGroups.value)) {
    for (const perm of perms) {
      result.push({
        name: perm,
        description: permissionDescriptions.value[perm] || perm,
        group
      })
    }
  }
  return result
})

const openCreateModal = () => {
  editingRole.value = null
  formData.value = {
    name: '',
    display_name: '',
    description: '',
    permissions: []
  }
  selectedGroups.value = new Set()
  expandedGroups.value = new Set(Object.keys(permissionGroups.value))
  showRoleModal.value = true
}

const openEditModal = (role: Role) => {
  editingRole.value = role
  formData.value = {
    name: role.name,
    display_name: role.display_name,
    description: role.description || '',
    permissions: [...(role.permissions || [])]
  }

  // 计算选中的分组
  const groups = new Set<string>()
  for (const perm of formData.value.permissions) {
    for (const [groupName, perms] of Object.entries(permissionGroups.value)) {
      if (perms.includes(perm)) {
        groups.add(groupName)
      }
    }
  }
  selectedGroups.value = groups
  expandedGroups.value = groups

  showRoleModal.value = true
}

const closeModal = () => {
  showRoleModal.value = false
  editingRole.value = null
}

const toggleGroup = (groupName: string) => {
  if (expandedGroups.value.has(groupName)) {
    expandedGroups.value.delete(groupName)
  } else {
    expandedGroups.value.add(groupName)
  }
}

const selectGroup = (groupName: string) => {
  if (selectedGroups.value.has(groupName)) {
    selectedGroups.value.delete(groupName)
    // 移除该分组下的所有权限
    const groupPerms = permissionGroups.value[groupName] || []
    formData.value.permissions = formData.value.permissions.filter(p => !groupPerms.includes(p))
  } else {
    selectedGroups.value.add(groupName)
    // 添加该分组下的所有权限
    const groupPerms = permissionGroups.value[groupName] || []
    for (const perm of groupPerms) {
      if (!formData.value.permissions.includes(perm)) {
        formData.value.permissions.push(perm)
      }
    }
  }
}

const isGroupFullySelected = (groupName: string) => {
  const groupPerms = permissionGroups.value[groupName] || []
  return groupPerms.every(perm => formData.value.permissions.includes(perm))
}

const isGroupPartiallySelected = (groupName: string) => {
  const groupPerms = permissionGroups.value[groupName] || []
  return groupPerms.some(perm => formData.value.permissions.includes(perm))
}

const saveRole = async () => {
  if (!formData.value.name || !formData.value.display_name) {
    alert('请填写角色名称和显示名称')
    return
  }

  try {
    if (editingRole.value) {
      await request.put(`/roles/${editingRole.value.id}`, formData.value)
    } else {
      await request.post('/roles', formData.value)
    }
    closeModal()
    await loadData()
  } catch (err: any) {
    alert(err.message || '保存失败')
  }
}

const deleteRole = async (role: Role) => {
  if (role.is_system) {
    alert('系统角色不能删除')
    return
  }
  if (role.user_count > 0) {
    alert(`还有 ${role.user_count} 个管理员使用此角色，无法删除`)
    return
  }
  if (!confirm(`确定要删除角色「${role.display_name}」吗？`)) {
    return
  }

  try {
    await request.delete(`/roles/${role.id}`)
    await loadData()
  } catch (err: any) {
    alert(err.message || '删除失败')
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="roles-page">
    <!-- 操作按钮 -->
    <div class="page-actions">
      <button class="btn-primary" @click="openCreateModal">
        <Plus :size="18" />
        新建角色
      </button>
    </div>

    <!-- 角色列表 -->
    <div class="roles-list">
      <div v-for="role in roles" :key="role.id" class="role-card" :class="{ system: role.is_system }">
        <div class="role-header">
          <div class="role-info">
            <h3 class="role-name">
              {{ role.display_name }}
              <span v-if="role.is_system" class="system-badge">系统角色</span>
            </h3>
            <p class="role-code">{{ role.name }}</p>
          </div>
          <div class="role-actions">
            <button v-if="!role.is_system" class="btn-icon" @click="openEditModal(role)" title="编辑">
              <Edit :size="16" />
            </button>
            <button v-if="!role.is_system" class="btn-icon btn-danger" @click="deleteRole(role)" title="删除">
              <Trash2 :size="16" />
            </button>
          </div>
        </div>

        <p v-if="role.description" class="role-description">{{ role.description }}</p>

        <div class="role-meta">
          <span class="meta-item">
            <strong>{{ role.permissions?.length || 0 }}</strong> 项权限
          </span>
          <span class="meta-item">
            <strong>{{ role.user_count }}</strong> 位管理员
          </span>
        </div>
      </div>
    </div>

    <!-- 角色编辑弹窗 -->
    <div v-if="showRoleModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal-content">
        <div class="modal-header">
          <h2>{{ editingRole ? '编辑角色' : '新建角色' }}</h2>
          <button class="btn-icon" @click="closeModal">
            <X :size="20" />
          </button>
        </div>

        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">角色标识 <span class="required">*</span></label>
            <input
              v-model="formData.name"
              type="text"
              class="form-input"
              placeholder="如: custom_admin"
              :disabled="!!editingRole"
            />
            <p class="form-hint">英文标识，创建后不可修改</p>
          </div>

          <div class="form-group">
            <label class="form-label">显示名称 <span class="required">*</span></label>
            <input
              v-model="formData.display_name"
              type="text"
              class="form-input"
              placeholder="如: 自定义管理员"
            />
          </div>

          <div class="form-group">
            <label class="form-label">描述</label>
            <textarea
              v-model="formData.description"
              class="form-textarea"
              placeholder="角色职责描述..."
            ></textarea>
          </div>

          <div class="form-group">
            <label class="form-label">权限配置</label>
            <div class="permission-groups">
              <div
                v-for="(perms, groupName) in permissionGroups"
                :key="groupName"
                class="perm-group"
              >
                <div
                  class="perm-group-header"
                  :class="{
                    selected: isGroupFullySelected(groupName),
                    partial: !isGroupFullySelected(groupName) && isGroupPartiallySelected(groupName)
                  }"
                  @click="selectGroup(groupName)"
                >
                  <div class="perm-group-toggle" @click.stop="toggleGroup(groupName)">
                    <ChevronRight
                      :size="16"
                      :class="{ rotated: expandedGroups.has(groupName) }"
                    />
                  </div>
                  <span class="perm-group-name">{{ groupName }}</span>
                  <span class="perm-group-count">({{ perms.length }})</span>
                </div>
                <div v-if="expandedGroups.has(groupName)" class="perm-group-items">
                  <label
                    v-for="perm in perms"
                    :key="perm"
                    class="perm-item"
                  >
                    <input
                      type="checkbox"
                      :checked="formData.permissions.includes(perm)"
                      @change="(e: any) => {
                        if (e.target.checked) {
                          formData.permissions.push(perm)
                        } else {
                          formData.permissions = formData.permissions.filter(p => p !== perm)
                        }
                      }"
                    />
                    <span>{{ permissionDescriptions[perm] || perm }}</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-secondary" @click="closeModal">取消</button>
          <button class="btn-primary" @click="saveRole">
            <Save :size="16" />
            保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { ChevronRight } from 'lucide-vue-next'

export default {
  components: { ChevronRight }
}
</script>

<style scoped>
.roles-page {
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

/* 角色列表 */
.roles-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.role-card {
  background: white;
  border-radius: 12px;
  padding: 1.25rem;
  border: 1px solid #e8edf3;
  transition: all 0.2s;
}

.role-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.role-card.system {
  background: linear-gradient(135deg, rgba(103, 58, 183, 0.03), rgba(76, 175, 80, 0.03));
  border-color: rgba(103, 58, 183, 0.2);
}

.role-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 0.5rem;
}

.role-name {
  font-size: 1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.system-badge {
  font-size: 0.7rem;
  padding: 0.125rem 0.5rem;
  background: rgba(103, 58, 183, 0.15);
  color: #673AB7;
  border-radius: 4px;
}

.role-code {
  font-size: 0.75rem;
  color: #94a3b8;
  font-family: monospace;
  margin: 0;
}

.role-actions {
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

.btn-icon:hover {
  background: #e2e8f0;
  color: #1a1a2e;
}

.btn-icon.btn-danger:hover {
  background: rgba(244, 67, 54, 0.1);
  color: #F44336;
}

.role-description {
  font-size: 0.875rem;
  color: #64748b;
  margin: 0.5rem 0 1rem;
}

.role-meta {
  display: flex;
  gap: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
}

.meta-item {
  font-size: 0.75rem;
  color: #94a3b8;
}

.meta-item strong {
  color: #1a1a2e;
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
  max-width: 600px;
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
  overflow-y: auto;
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

.form-input {
  width: 100%;
  padding: 0.625rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
}

.form-input:disabled {
  background: #f1f5f9;
}

.form-textarea {
  width: 100%;
  min-height: 80px;
  padding: 0.625rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  resize: vertical;
}

.form-hint {
  font-size: 0.75rem;
  color: #94a3b8;
  margin-top: 0.25rem;
}

/* 权限分组 */
.permission-groups {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.perm-group {
  border-bottom: 1px solid #e2e8f0;
}

.perm-group:last-child {
  border-bottom: none;
}

.perm-group-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: #f8fafc;
  cursor: pointer;
  transition: background 0.2s;
}

.perm-group-header:hover {
  background: #f1f5f9;
}

.perm-group-header.selected {
  background: rgba(76, 175, 80, 0.1);
}

.perm-group-header.partial {
  background: rgba(255, 152, 0, 0.05);
}

.perm-group-toggle {
  transition: transform 0.2s;
}

.perm-group-toggle.rotated {
  transform: rotate(90deg);
}

.perm-group-name {
  flex: 1;
  font-size: 0.875rem;
  font-weight: 500;
  color: #1a1a2e;
}

.perm-group-count {
  font-size: 0.75rem;
  color: #94a3b8;
}

.perm-group-items {
  padding: 0.75rem 1rem;
  background: white;
}

.perm-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0;
  font-size: 0.875rem;
  color: #475569;
  cursor: pointer;
}

.perm-item input {
  accent-color: #673AB7;
}

/* 移动端适配 */
@media (max-width: 768px) {

  .btn-primary {
    width: 100%;
    justify-content: center;
  }

  .roles-list {
    grid-template-columns: 1fr;
  }
}
</style>
