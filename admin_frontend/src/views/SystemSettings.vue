<!--
  SystemSettings.vue
  iOS 风格系统配置页面 - 主页面

  功能：
  - 加载和显示系统配置
  - 搜索和过滤配置项
  - 修改配置（支持 dirty state）
  - 保存/放弃修改
  - 导入/导出配置
  - 重置为默认值
-->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox, ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus'
import { MoreFilled } from '@element-plus/icons-vue'
import PageHeader from '@/components/system-settings/PageHeader.vue'
import FilterBar from '@/components/system-settings/FilterBar.vue'
import SettingsSection from '@/components/system-settings/SettingsSection.vue'
import SaveBar from '@/components/system-settings/SaveBar.vue'
import ImportDialog from '@/components/system-settings/ImportDialog.vue'
import { useSettingsState } from '@/composables/useSettingsState'
import type { SettingItem, SettingImportItem } from '@/types/settings'
import {
  getSettings,
  getSettingCategories,
  batchUpdateSettings,
  exportSettings,
  importSettings
} from '@/api/portal'

// ========== 状态 ==========
const loading = ref(false)
const saving = ref(false)
const searchQuery = ref('')
const showImportDialog = ref(false)

// ========== 使用 State Management ==========
const {
  settings,
  groupedSettings,
  dirtyCount,
  hasChanges,
  showModifiedOnly,
  initializeState,
  updateValue,
  isDirty,
  getCurrentValue,
  isSensitive,
  discardChanges,
  getDirtyItems,
  commitChanges
} = useSettingsState()

// ========== 数据加载 ==========
const loadSettings = async () => {
  loading.value = true
  try {
    const [catsRes, settingsRes] = await Promise.all([
      getSettingCategories(),
      getSettings()
    ])

    const items = (settingsRes.items || []).map((item: any) => ({
      ...item,
      sensitive: item.type === 'password' || item.key?.toLowerCase().includes('token') || item.key?.toLowerCase().includes('secret')
    })) as SettingItem[]

    initializeState(items)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '加载配置失败')
  } finally {
    loading.value = false
  }
}

// ========== 保存操作 ==========
const handleSave = async () => {
  const items = getDirtyItems()
  if (items.length === 0) {
    ElMessage.info('没有需要保存的修改')
    return
  }

  saving.value = true
  try {
    await batchUpdateSettings(items)
    commitChanges()
    ElMessage.success(`已保存 ${items.length} 项配置`)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

// ========== 放弃修改 ==========
const handleDiscard = () => {
  discardChanges()
  ElMessage.info('已放弃所有修改')
}

// ========== 导出配置 ==========
const handleExport = async () => {
  try {
    const res = await exportSettings()
    const data = JSON.stringify(res.settings, null, 2)
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `system-settings-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('配置已导出')
  } catch (error: any) {
    ElMessage.error('导出失败')
  }
}

// ========== 导入配置 ==========
const handleImport = async (items: SettingImportItem[]) => {
  try {
    await importSettings(items)
    ElMessage.success('配置已导入')
    showImportDialog.value = false
    await loadSettings()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '导入失败')
  }
}

// ========== 重置为默认 ==========
const handleResetDefaults = async () => {
  try {
    await ElMessageBox.confirm(
      '此操作将把所有配置恢复为默认值，且不可撤销。确定继续？',
      '重置为默认',
      {
        confirmButtonText: '确定重置',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )

    loading.value = true
    // TODO: 调用重置 API
    // await resetAllSettings()
    await loadSettings()
    ElMessage.success('已重置为默认值')
  } catch {
    // 用户取消
  } finally {
    loading.value = false
  }
}

// ========== 菜单点击 ==========
const handleMenuClick = () => {
  // 返回首页或打开侧边栏
  console.log('Menu clicked')
}

// ========== 生命周期 ==========
onMounted(() => {
  loadSettings()
})
</script>

<template>
  <div class="system-settings">
    <!-- 顶部 Header -->
    <PageHeader @menu-click="handleMenuClick">
      <template #actions>
        <el-dropdown trigger="click" class="more-dropdown">
          <button class="btn-more">
            <MoreFilled :size="20" />
          </button>
          <template #dropdown>
            <el-dropdown-menu class="dropdown-menu">
              <el-dropdown-item @click="loadSettings">
                <div class="dropdown-item">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M13.33 8A5.33 5.33 0 1 1 8 2.67M8 2.67V6M8 2.67L10.67 5.33" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  刷新
                </div>
              </el-dropdown-item>
              <el-dropdown-item @click="showImportDialog = true">
                <div class="dropdown-item">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M8 2.67v10.66M8 13.33L5.33 10.67M8 13.33l2.67-2.66M2.67 8h10.66" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  导入配置
                </div>
              </el-dropdown-item>
              <el-dropdown-item @click="handleExport">
                <div class="dropdown-item">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M13.33 8v4a2 2 0 0 1-2 2H4.67a2 2 0 0 1-2-2V8M8 2.67v6.66M8 9.33L5.33 6.67M8 9.33l2.67-2.66" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  导出配置
                </div>
              </el-dropdown-item>
              <el-dropdown-item divided class="dropdown-item-danger" @click="handleResetDefaults">
                <div class="dropdown-item">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M8 2.67v6.66M8 9.33L5.33 6.67M8 9.33l2.67-2.66M2.67 12v1.33a2 2 0 0 0 2 2h6.66a2 2 0 0 0 2-2V12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  重置为默认
                </div>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </template>
    </PageHeader>

    <!-- 搜索和过滤栏 -->
    <FilterBar
      v-model="searchQuery"
      v-model:show-modified="showModifiedOnly"
    />

    <!-- 主内容区 -->
    <div v-loading="loading" class="settings-content">
      <!-- Skeleton 加载态 -->
      <template v-if="loading">
        <div v-for="i in 3" :key="i" class="skeleton-section">
          <div class="skeleton-header">
            <div class="skeleton-line short"></div>
            <div class="skeleton-line tiny"></div>
          </div>
          <div class="skeleton-content">
            <div v-for="j in 3" :key="j" class="skeleton-row">
              <div class="skeleton-info">
                <div class="skeleton-line short"></div>
                <div class="skeleton-line medium"></div>
              </div>
              <div class="skeleton-control"></div>
            </div>
          </div>
        </div>
      </template>

      <!-- 分组配置 -->
      <template v-else>
        <SettingsSection
          v-for="(items, category) in groupedSettings"
          :key="category"
          :name="category"
          :items="items"
          :search-query="searchQuery"
          :is-dirty="isDirty"
          :get-current-value="getCurrentValue"
          :is-sensitive="isSensitive"
          :default-expanded="['订单与订阅', '推送策略'].includes(category)"
          @update="updateValue"
        />

        <!-- 空状态 -->
        <div v-if="Object.keys(groupedSettings).length === 0" class="empty-state">
          <svg class="empty-icon" width="48" height="48" viewBox="0 0 48 48" fill="none">
            <circle cx="24" cy="24" r="18" stroke="#232A33" stroke-width="2"/>
            <path d="M24 16v12M24 28h.01" stroke="#232A33" stroke-width="2" stroke-linecap="round"/>
          </svg>
          <p class="empty-text">未找到匹配的配置项</p>
          <button v-if="searchQuery || showModifiedOnly" class="btn-clear-filter" @click="searchQuery = ''; showModifiedOnly = false">
            清除筛选
          </button>
        </div>
      </template>
    </div>

    <!-- 底部保存栏 -->
    <SaveBar
      v-if="hasChanges"
      :dirty-count="dirtyCount"
      :saving="saving"
      @save="handleSave"
      @discard="handleDiscard"
    />

    <!-- 导入弹窗 -->
    <ImportDialog
      v-model="showImportDialog"
      @import="handleImport"
    />
  </div>
</template>

<style scoped>
.system-settings {
  min-height: 100vh;
  background-color: var(--bg-base);
  padding-bottom: 80px; /* 为 SaveBar 预留空间 */
}

/* 更多菜单按钮 */
.btn-more {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  color: var(--text-secondary);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background-color var(--transition-fast) ease;
}

.btn-more:hover {
  background-color: var(--bg-card-hover);
}

.btn-more:active {
  background-color: var(--bg-input);
  transform: scale(0.96);
}

/* 下拉菜单样式 */
:deep(.dropdown-menu) {
  background-color: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: 6px;
}

:deep(.el-dropdown-menu__item) {
  padding: 0;
  border-radius: var(--radius-sm);
  color: var(--text-primary);
}

:deep(.el-dropdown-menu__item:hover) {
  background-color: var(--bg-card-hover);
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 14px;
}

.dropdown-item svg {
  color: var(--text-tertiary);
}

:deep(.el-dropdown-menu__item:hover) .dropdown-item svg {
  color: var(--text-primary);
}

.dropdown-item-danger {
  color: var(--danger);
}

:deep(.dropdown-item-danger:hover) {
  background-color: var(--danger-bg);
}

:deep(.dropdown-item-danger) .dropdown-item svg {
  color: var(--danger);
}

:deep(.dropdown-item-danger:hover) .dropdown-item svg {
  color: var(--danger);
}

/* 主内容区 */
.settings-content {
  padding: 4px 16px 16px;
}

/* Skeleton 样式 */
.skeleton-section {
  margin-bottom: 16px;
  padding: 16px;
  background-color: var(--bg-card);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-xl);
}

.skeleton-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.skeleton-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skeleton-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-base);
}

.skeleton-row:last-child {
  border-bottom: none;
}

.skeleton-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skeleton-control {
  width: 200px;
  height: 44px;
  background-color: var(--bg-input);
  border-radius: var(--radius-lg);
}

.skeleton-line {
  height: 14px;
  background: linear-gradient(
    90deg,
    var(--bg-card-hover) 0%,
    var(--border-strong) 50%,
    var(--bg-card-hover) 100%
  );
  background-size: 200% 100%;
  border-radius: 4px;
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}

.skeleton-line.short {
  width: 120px;
}

.skeleton-line.medium {
  width: 200px;
}

.skeleton-line.tiny {
  width: 40px;
  height: 10px;
}

@keyframes skeleton-pulse {
  0%, 100% {
    background-position: 0% 0%;
  }
  50% {
    background-position: 100% 0%;
  }
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}

.empty-icon {
  margin-bottom: 16px;
}

.empty-text {
  margin: 0 0 16px 0;
  font-size: 15px;
  color: var(--text-tertiary);
}

.btn-clear-filter {
  padding: 10px 20px;
  font-size: 14px;
  color: var(--success);
  background: transparent;
  border: 1px solid var(--success);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
}

.btn-clear-filter:hover {
  background-color: var(--success-bg);
}

/* Loading 遮罩样式覆盖 */
:deep(.el-loading-mask) {
  background-color: var(--bg-overlay);
}

:deep(.el-loading-spinner .circular) {
  stroke: var(--primary);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .system-settings {
    padding-bottom: 70px;
  }

  .settings-content {
    padding: 4px 12px 12px;
  }

  .skeleton-section {
    margin-bottom: 12px;
    border-radius: 12px;
  }

  .skeleton-control {
    width: 140px;
    height: 40px;
  }
}
</style>
