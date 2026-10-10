<script setup lang="ts">
/**
 * Google Drive 账号（Fix 6）
 *
 * 用户实际用的是 Google Drive（100 个 Service Account），不是 115。
 * 本页展示 SA 状态：数量、当前轮换位置、磁盘压力、rclone 缓存大小，
 * 并支持手动触发 SA 轮换。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Cloud, RefreshCw, RotateCw, HardDrive } from 'lucide-vue-next'
import { PageHeader, SectionCard, StatTile, EmptyState } from '@/components/ui'
import { fetchGDriveSaStatus, rotateGDriveSa } from '@/api/admin'

interface SaStatus {
  sa_count: number
  sa_files: string[]
  sa_truncated: boolean
  current_sa: string | null
  rotation_index: number
  disk: Record<string, unknown>
  cache_size_bytes: number
  cache_size_human: string
}

const loading = ref(false)
const status = ref<SaStatus | null>(null)
const loadError = ref(false)
const rotating = ref(false)

async function load() {
  loading.value = true
  loadError.value = false
  try {
    status.value = await fetchGDriveSaStatus()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

async function rotate() {
  try {
    await ElMessageBox.confirm('确定要切换到下一个 Service Account 吗？', '手动轮换', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  rotating.value = true
  try {
    const data = await rotateGDriveSa()
    ElMessage.success(`已切换到 ${data.sa_file || '下一个账号'}`)
    await load()
  } catch (err: any) {
    ElMessage.error(err?.message || '轮换失败')
  } finally {
    rotating.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="gdrive-page">
    <PageHeader title="Google Drive 账号" description="Service Account 状态与轮换管理" />

    <div v-if="loadError" class="error-state">
      <EmptyState title="加载失败" description="无法获取 SA 状态" />
      <button class="btn primary" @click="load">重试</button>
    </div>

    <template v-else-if="status">
      <div class="stat-row">
        <StatTile label="SA 账号数" :value="String(status.sa_count)" :icon="Cloud" />
        <StatTile label="当前账号" :value="status.current_sa || '—'" :icon="RefreshCw" />
        <StatTile label="缓存大小" :value="status.cache_size_human" :icon="HardDrive" />
      </div>

      <SectionCard title="账号列表">
        <template #actions>
          <button class="btn primary" :disabled="rotating" @click="rotate">
            <RotateCw :size="15" :class="{ spinning: rotating }" />
            {{ rotating ? '轮换中…' : '手动轮换' }}
          </button>
          <button class="icon-btn" title="刷新" @click="load">
            <RefreshCw :size="15" :class="{ spinning: loading }" />
          </button>
        </template>
        <ul class="sa-list">
          <li
            v-for="f in status.sa_files"
            :key="f"
            class="sa-item"
            :class="{ active: f === status.current_sa }"
          >
            <Cloud :size="15" />
            <span class="sa-name">{{ f }}</span>
            <span v-if="f === status.current_sa" class="badge ok">当前</span>
          </li>
        </ul>
        <p v-if="status.sa_truncated" class="truncated-hint">
          仅显示前 20 个，共 {{ status.sa_count }} 个
        </p>
      </SectionCard>

      <SectionCard v-if="status.disk && Object.keys(status.disk).length" title="磁盘状态">
        <pre class="disk-info">{{ JSON.stringify(status.disk, null, 2) }}</pre>
      </SectionCard>
    </template>

    <div v-else class="loading-state">
      <RefreshCw :size="24" class="spinning" />
      <p>加载中…</p>
    </div>
  </div>
</template>

<style scoped>
.gdrive-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  max-width: 1200px;
  margin: 0 auto;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}
.sa-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sa-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--au-border, #2a2a2a);
  border-radius: 8px;
}
.sa-item.active {
  border-color: var(--au-primary, #e8a84a);
  background: color-mix(in srgb, var(--au-primary, #e8a84a) 8%, transparent);
}
.sa-name {
  flex: 1;
  font-family: monospace;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.badge.ok {
  background: #1a7f37;
  color: #fff;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}
.truncated-hint {
  color: var(--au-text-2, #888);
  font-size: 13px;
  margin-top: 12px;
}
.disk-info {
  background: var(--au-bg-soft, #1a1a1a);
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  overflow-x: auto;
}
.error-state, .loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px;
}
.spinning {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
