<script setup lang="ts">
/**
 * 挂载目录浏览（从「存储来源」页搬出来的独立组件）
 *
 * 为什么单独抽一个组件：这个弹窗本来住在存储来源页里，和那一页的表格 / 表单
 * 状态缠在一起。挂载管理并进「服务器」页后，浏览能力要能在两处复用，所以把它
 * 变成「给一个挂载、弹一个浏览框」的纯组件，自己管自己的状态。
 */
import { computed, ref, watch } from 'vue'
import { FolderOpen } from 'lucide-vue-next'
import { browseMount } from '@/api/admin'
import type { MountDirEntry, StorageMount } from '@/types'

const props = defineProps<{
  modelValue: boolean
  mount: StorageMount | null
  /** 类型元数据里声明了 root_key（115 的 cid）时，点目录可回写 */
  rootKeyLabel?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  /** 点目录时把它当成新的挂载根（父组件决定要不要写回） */
  pick: [rel: string, entry: MountDirEntry]
}>()

const rel = ref('/')
const entries = ref<MountDirEntry[]>([])
const loading = ref(false)

async function browseTo(next: string) {
  if (!props.mount) return
  loading.value = true
  try {
    const res = await browseMount(props.mount.id, next)
    rel.value = res.rel || '/'
    entries.value = res.entries || []
  } finally {
    loading.value = false
  }
}

// 打开时从根目录开始：同一个挂载连开两次，看到的应该是同一个起点
watch(() => props.modelValue, (open) => {
  if (open) {
    rel.value = '/'
    entries.value = []
    browseTo('/')
  }
})

/** 115 的条目带 cid，回显出来管理员才知道该往路径里填什么 */
function entryIdLabel(e: MountDirEntry): string {
  return e.entry_id ? `ID ${e.entry_id}` : ''
}

function pickEntry(e: MountDirEntry) {
  if (e.is_dir) {
    browseTo(e.rel)
    emit('pick', e.rel, e)
    return
  }
  emit('pick', e.rel, e)
}

const title = computed(() => `浏览：${props.mount?.name || ''}`)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="560px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="browse-bar">
      <el-button size="small" text :disabled="rel === '/'" @click="browseTo('/')">根目录</el-button>
      <span class="browse-path">{{ rel }}</span>
      <el-button size="small" text :loading="loading" @click="browseTo(rel)">刷新</el-button>
    </div>
    <div v-loading="loading" class="browse-list">
      <div
        v-for="e in entries"
        :key="e.rel"
        class="browse-item"
        :class="{ dir: e.is_dir }"
        @click="pickEntry(e)"
      >
        <FolderOpen v-if="e.is_dir" :size="14" />
        <span class="browse-name">{{ e.name }}</span>
        <span v-if="entryIdLabel(e)" class="browse-id">{{ entryIdLabel(e) }}</span>
        <span v-else class="browse-size">{{ e.is_dir ? '' : (e.size / 1024 / 1024).toFixed(1) + ' MB' }}</span>
      </div>
      <div v-if="entries.length === 0 && !loading" class="browse-empty">目录为空</div>
    </div>
    <template #footer>
      <span v-if="rootKeyLabel" class="form-hint">
        点目录可把它设为挂载根{{ rootKeyLabel === 'prefix' ? '前缀' : '目录' }}。
      </span>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.browse-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.browse-path {
  flex: 1; font-size: var(--font-size-xs); color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.browse-list { min-height: 180px; max-height: 46vh; overflow-y: auto; }
.browse-item {
  display: flex; align-items: center; gap: 8px; padding: 7px 8px;
  border-radius: var(--radius-sm); cursor: pointer; font-size: var(--font-size-sm);
}
.browse-item:hover { background: var(--bg-hover); }
.browse-item.dir { font-weight: 500; }
.browse-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.browse-id, .browse-size {
  font-size: var(--font-size-xs); color: var(--text-muted); flex-shrink: 0;
}
.browse-empty { padding: 24px; text-align: center; color: var(--text-muted); }
.form-hint { font-size: var(--font-size-xs); color: var(--text-muted); margin-right: 8px; }
</style>
